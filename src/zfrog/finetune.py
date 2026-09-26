"""Fine-tuning data built from the user's own clones — data only, no trainer.

Two things this module does, and one it deliberately does not:

* It turns pages the user already cloned into instruction/response pairs
  (:class:`TrainingExample`) that are *true*: every target is derived from the
  page itself (or from a model that actually ran), never invented.
* It exports them as JSONL in the two shapes the common trainers consume: the
  ``{"messages": [...]}`` chat shape used by [OI] chat fine-tuning, and the plain
  Alpaca ``{"instruction", "input", "output"}`` shape.
* It does **not** train anything. Training needs a GPU and a trainer this project
  does not ship, so the last step happens elsewhere: point your trainer at the
  exported file.

That is the difference from :mod:`zfrog.ai.domains`: the domain profiles
specialise the **prompt** at inference time (same weights, better instructions),
while this module prepares data to specialise the **weights**.

Which extraction path was taken is logged, never guessed: when
``zfrog.ai.extraction.extract_structured`` exists and the AI is reachable the
example carries the model's structured extraction; otherwise the example is built
from the page itself (title plus its first sentences), so the pair stays true
instead of being a fabricated "AI answer".

Built examples are persisted at ``<root>/examples.json`` (atomic, mode ``0600``,
because the content is the user's own data), so an export can happen in a later
run. Exporting never overwrites a dataset: with no explicit ``path`` the next
free ``dataset-<n>.jsonl`` is used.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from zfrog.ai.client import is_available
from zfrog.config import settings
from zfrog.utils.text import extract_text

logger = logging.getLogger(__name__)

#: Example kinds the builder knows how to produce.
KINDS: tuple[str, ...] = ("extraction", "qa", "summary", "entities")

#: Export shapes accepted by :meth:`DatasetBuilder.export`.
FORMATS: tuple[str, ...] = ("chat", "alpaca")

#: File holding the persisted examples inside the builder root.
EXAMPLES_FILE = "examples.json"

#: Mode of every file this module writes: the dataset is the user's data.
FILE_MODE = 0o600

#: An output shorter than this teaches nothing useful, so it is rejected.
MIN_OUTPUT_CHARS = 30

#: Page text handed to the model as context, in characters.
MAX_INPUT_CHARS = 4000

#: Ceiling for a single example's output, in characters.
MAX_OUTPUT_CHARS = 1200

#: How many leading sentences an extractive summary keeps.
SUMMARY_SENTENCES = 3

#: Hard ceiling for an extractive summary, in characters.
SUMMARY_MAX_CHARS = 600

#: How many leading sentences the deterministic extraction fallback keeps.
EXTRACTION_SENTENCES = 3

#: A line longer than this is prose, never a heading.
HEADING_MAX_CHARS = 80

#: A heading whose following sentence is shorter than this is not worth a pair.
MIN_HEADING_SENTENCE_CHARS = 20

#: System message used by the chat shape.
SYSTEM_PROMPT = (
    "Você é um assistente que responde apenas com informação presente no conteúdo fornecido."
)

#: Instructions produced by the builder (also what :func:`_classify_instruction` reads).
EXTRACTION_INSTRUCTION = "Extraia os dados principais da página em JSON."
SUMMARY_INSTRUCTION = "Resuma o conteúdo da página em poucas frases."
ENTITIES_INSTRUCTION = "Liste em JSON as entidades nomeadas (pessoas, organizações, locais, datas) do texto."
QA_INSTRUCTION_TEMPLATE = "O que o documento diz sobre «{heading}»?"

#: Human-readable kind labels, used by :func:`dataset_summary`.
KIND_LABELS: dict[str, str] = {
    "extraction": "extração",
    "qa": "perguntas e respostas",
    "summary": "resumo",
    "entities": "entidades",
}

#: Sentence terminator, followed by whitespace or the end of the text.
_SENTENCE_END = re.compile(r"[.!?…]+(?=\s|$)")

#: Name of a generated dataset file.
_DATASET_NAME = re.compile(r"dataset-(\d+)\.jsonl")


@dataclass
class TrainingExample:
    """One instruction/response pair, plus where it came from."""

    instruction: str
    input: str
    output: str
    source: str
    kind: str

def chat_format(example: TrainingExample) -> dict:
    """Render ``example`` in the [OI] chat shape (one JSON object per line)."""
    user = example.instruction.strip()
    context = example.input.strip()
    if context:
        user = f"{user}\n\n{context}"
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": example.output},
        ]
    }


def alpaca_format(example: TrainingExample) -> dict:
    """Render ``example`` in the plain Alpaca shape."""
    return {
        "instruction": example.instruction,
        "input": example.input,
        "output": example.output,
    }


def validate_example(example: TrainingExample) -> list[str]:
    """Return the problems that make ``example`` useless, or ``[]`` when it is fine."""
    problems: list[str] = []
    if not example.instruction.strip():
        problems.append("instrução vazia")
    output = example.output.strip()
    if not output:
        problems.append("saída vazia ou só com espaços")
    elif output == example.input.strip():
        problems.append("saída idêntica à entrada (uma cópia não é um exemplo)")
    elif len(output) < MIN_OUTPUT_CHARS:
        problems.append(
            f"saída com {len(output)} caracteres, abaixo do mínimo de {MIN_OUTPUT_CHARS}"
        )
    return problems


def _clip(text: str, limit: int) -> str:
    """Truncate ``text`` to at most ``limit`` characters, preferring a word break."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip()


def _leading_sentences(text: str, count: int) -> str:
    """Return the first ``count`` sentences of ``text`` verbatim (spacing kept).

    The result is always a substring of ``text``, so an example built from it can
    be checked against the page it came from.
    """
    stripped = text.strip()
    if count <= 0 or not stripped:
        return ""
    ends = [match.end() for match in _SENTENCE_END.finditer(stripped)]
    if len(ends) < count:
        return stripped
    return stripped[: ends[count - 1]].strip()


def _first_sentence(text: str) -> str:
    """Return the first sentence of ``text`` (the whole text when it has none)."""
    return _leading_sentences(text, 1)


def _next_paragraph(lines: list[str], start: int) -> str:
    """Join the lines of the paragraph that starts at ``start`` (blank lines end it)."""
    collected: list[str] = []
    for raw in lines[start:]:
        line = raw.strip()
        if not line:
            if collected:
                break
            continue
        collected.append(line)
    return " ".join(collected)


def _previous_line_ends_sentence(lines: list[str], index: int) -> bool:
    """True when the previous non-empty line closes a sentence (so ``index`` starts one)."""
    for raw in reversed(lines[:index]):
        line = raw.strip()
        if not line:
            return True
        return line.endswith((".", "!", "?", "…", ":"))
    return True


def _headings_from_text(text: str) -> list[tuple[str, str]]:
    """Find ``(heading, first sentence under it)`` pairs with a line heuristic."""
    lines = text.splitlines()
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line or len(line) > HEADING_MAX_CHARS:
            continue
        markdown = line.startswith("#")
        heading = line.lstrip("#").strip() if markdown else line
        if not heading or heading in seen:
            continue
        if not markdown:
            if line.endswith((".", "!", "?", "…", ",", ";", ":")):
                continue
            if not _previous_line_ends_sentence(lines, index):
                continue
        body = _first_sentence(_next_paragraph(lines, index + 1))
        if len(body) < MIN_HEADING_SENTENCE_CHARS:
            continue
        seen.add(heading)
        pairs.append((heading, body))
    return pairs


def _headings_from_html(html: str, text: str) -> list[tuple[str, str]]:
    """Find ``(heading, first sentence under it)`` pairs in the page's HTML headings."""
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:  # pragma: no cover - bs4 ships with the project
        logger.warning("beautifulsoup4 indisponível (%s); usando o texto da página", exc)
        return []
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as exc:
        logger.warning("HTML ilegível (%s); usando o texto da página", exc)
        return []

    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        heading = tag.get_text(" ", strip=True)
        if not heading or heading in seen:
            continue
        seen.add(heading)
        position = text.find(heading)
        if position < 0:
            continue
        tail = text[position + len(heading) :]
        body = _first_sentence(_next_paragraph(tail.splitlines(), 0))
        if len(body) < MIN_HEADING_SENTENCE_CHARS:
            continue
        pairs.append((heading, body))
    return pairs


def _qa_pairs(page: dict, text: str) -> list[tuple[str, str]]:
    """Question/answer pairs taken from the page's own headings and first sentences."""
    html = page.get("html")
    pairs = _headings_from_html(str(html), text) if html else []
    if not pairs:
        pairs = _headings_from_text(text)
    return pairs


def _jsonable(value: Any) -> Any:
    """Convert a model result (pydantic model, dict, list) into JSON-friendly data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _jsonable(dump())
    return str(value)


def _run_coroutine(factory: Callable[[], Awaitable[Any]], timeout: float = 120.0) -> Any:
    """Run the coroutine built by ``factory`` from synchronous code.

    Inside a running event loop the coroutine is executed in a dedicated thread,
    so a synchronous caller in async code does not deadlock the loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    results: list[Any] = []
    errors: list[BaseException] = []

    def _target() -> None:
        try:
            results.append(asyncio.run(factory()))
        except BaseException as exc:  # noqa: BLE001 - re-raised in the calling thread
            errors.append(exc)

    thread = threading.Thread(target=_target, daemon=True, name="zfrog-finetune-ai")
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"chamada de IA excedeu {timeout:.0f}s")
    if errors:
        raise errors[0]
    return results[0]


def _run_maybe_async(factory: Callable[[], Any]) -> Any:
    """Call ``factory`` and await the result when it is awaitable."""
    result = factory()
    if inspect.isawaitable(result):
        return _run_coroutine(lambda: result)
    return result

def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write ``payload`` to ``path`` through a temp file plus ``os.replace``, mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, FILE_MODE)
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _example_from_payload(item: Any) -> TrainingExample | None:
    """Rebuild one example from a persisted payload, or ``None`` when it is unusable."""
    if not isinstance(item, dict):
        logger.warning("exemplo persistido ignorado: não é um objeto JSON")
        return None
    kind = str(item.get("kind") or "").strip()
    if kind not in KINDS:
        logger.warning("exemplo persistido ignorado: tipo desconhecido %r", kind)
        return None
    return TrainingExample(
        instruction=str(item.get("instruction") or ""),
        input=str(item.get("input") or ""),
        output=str(item.get("output") or ""),
        source=str(item.get("source") or ""),
        kind=kind,
    )


def load_dataset(path: Path) -> list[dict]:
    """Read a JSONL dataset back, skipping blank or corrupt lines with a warning."""
    target = Path(path)
    records: list[dict] = []
    for number, raw in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except (ValueError, TypeError) as exc:
            logger.warning("linha %d de %s ignorada: %s", number, target, exc)
            continue
        if not isinstance(record, dict):
            logger.warning("linha %d de %s ignorada: não é um objeto JSON", number, target)
            continue
        records.append(record)
    return records


def _classify_instruction(instruction: str) -> str:
    """Infer the kind of an exported example from its instruction's first line."""
    text = instruction.strip()
    first = text.splitlines()[0].strip() if text else ""
    lowered = first.casefold()
    if first.endswith("?"):
        return "qa"
    if "entidades" in lowered:
        return "entities"
    if "resuma" in lowered or "resumo" in lowered:
        return "summary"
    if "json" in lowered:
        return "extraction"
    return "qa"


def _record_kind(record: dict) -> str:
    """Kind of one exported record, read from either export shape."""
    instruction = str(record.get("instruction") or "")
    if not instruction:
        messages = record.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, dict) and message.get("role") == "user":
                    instruction = str(message.get("content") or "")
                    break
    return _classify_instruction(instruction)


def dataset_summary(path: Path) -> str:
    """One Portuguese sentence: how many examples the dataset holds and of which kinds."""
    target = Path(path)
    counts: dict[str, int] = {}
    total = 0
    for record in load_dataset(target):
        kind = _record_kind(record)
        counts[kind] = counts.get(kind, 0) + 1
        total += 1
    if not total:
        return f"Conjunto {target.name} sem exemplos."
    parts = ", ".join(
        f"{count} de {KIND_LABELS.get(kind, kind)}"
        for kind, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return f"Conjunto {target.name} com {total} exemplos: {parts}."

async def _call_extract(fn: Callable[..., Any], text: str, url: str) -> Any:
    """Call ``extract_structured`` tolerating either signature and sync or async forms."""
    for call in (lambda: fn(text=text, url=url), lambda: fn(text)):
        try:
            result = call()
        except TypeError:
            continue
        if inspect.isawaitable(result):
            result = await result
        return result
    raise TypeError("extract_structured: assinatura não suportada")


class DatasetBuilder:
    """Turn cloned pages into instruction/response pairs and export them as JSONL.

    Args:
        root: Directory holding ``examples.json`` and the exported datasets.
            Defaults to ``settings.finetune_dir``.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else Path(settings.finetune_dir)
        #: Report of the last :meth:`export` (path, format, written, skipped).
        self.last_export: dict[str, Any] = {}
        self._examples: list[TrainingExample] = []
        self._load()

    # ── reading ─────────────────────────────────────────────────────

    def examples(self) -> list[TrainingExample]:
        """Every example built so far, in insertion order."""
        return list(self._examples)

    def counts(self) -> dict[str, int]:
        """How many examples exist per kind (all kinds present, zeros included)."""
        counts = {kind: 0 for kind in KINDS}
        for example in self._examples:
            if example.kind in counts:
                counts[example.kind] += 1
        return counts

    def stats(self) -> dict:
        """Totals: ``examples``, ``valid``, ``invalid``, ``by_kind`` and ``chars``.

        ``chars`` counts instruction, input and output characters of every example.
        """
        valid = sum(1 for example in self._examples if not validate_example(example))
        return {
            "examples": len(self._examples),
            "valid": valid,
            "invalid": len(self._examples) - valid,
            "by_kind": self.counts(),
            "chars": sum(
                len(example.instruction) + len(example.input) + len(example.output)
                for example in self._examples
            ),
        }

    # ── building ────────────────────────────────────────────────────

    def add_pages(self, pages: list[dict], kind: str = "extraction") -> int:
        """Build examples of ``kind`` from ``pages`` and persist them.

        Args:
            pages: ``[{"url", "path", "title", "text", "html"?}]``; ``text`` is
                derived from ``html`` with :func:`zfrog.utils.text.extract_text`
                when missing.
            kind: One of :data:`KINDS`.

        Returns:
            How many examples were added.

        Raises:
            ValueError: ``kind`` is not one of :data:`KINDS`.
        """
        if kind not in KINDS:
            raise ValueError(f"tipo desconhecido: {kind!r} (use um de {', '.join(KINDS)})")
        added = 0
        for page in pages:
            added += self._add_page(page, kind)
        if added:
            self._save()
        return added

    def _add_page(self, page: Any, kind: str) -> int:
        """Build the examples one page yields for ``kind``."""
        entry = page if isinstance(page, dict) else {}
        text = _page_text(entry)
        if not text:
            logger.warning("página sem texto ignorada (%s)", entry.get("url") or entry.get("path"))
            return 0
        source = str(entry.get("url") or entry.get("path") or entry.get("title") or "").strip()
        if not source:
            source = "página sem origem"
        context = _clip(text, MAX_INPUT_CHARS)

        if kind == "extraction":
            output = self._extraction_output(entry, text)
            return self._append(EXTRACTION_INSTRUCTION, context, output, source, kind)

        if kind == "summary":
            output = _clip(_leading_sentences(text, SUMMARY_SENTENCES), SUMMARY_MAX_CHARS)
            return self._append(SUMMARY_INSTRUCTION, context, output, source, kind)

        if kind == "qa":
            pairs = _qa_pairs(entry, text)
            if not pairs:
                logger.warning("nenhum título utilizável em %s: sem exemplos de perguntas", source)
                return 0
            added = 0
            for heading, answer in pairs:
                instruction = QA_INSTRUCTION_TEMPLATE.format(heading=heading)
                added += self._append(
                    instruction, context, _clip(answer, MAX_OUTPUT_CHARS), source, kind
                )
            return added

        entities = self._page_entities(text, source)
        if not entities:
            return 0
        output = json.dumps(
            [{"nome": item.get("name"), "tipo": item.get("type")} for item in entities],
            ensure_ascii=False,
        )
        return self._append(ENTITIES_INSTRUCTION, context, output, source, kind)

    def _append(
        self, instruction: str, context: str, output: str, source: str, kind: str
    ) -> int:
        """Append one example, refusing to store an empty target."""
        if not output.strip():
            logger.warning("exemplo de %s ignorado para %s: saída vazia", kind, source)
            return 0
        self._examples.append(
            TrainingExample(
                instruction=instruction,
                input=context,
                output=output,
                source=source,
                kind=kind,
            )
        )
        return 1

    def _extraction_output(self, page: dict, text: str) -> str:
        """Structured extraction of ``page``: from the model when it can run, else from the page.

        The fallback is not a fake answer: it is the page's own title plus its
        first sentences, which is what makes the pair true.
        """
        if is_available():
            payload = self._model_extraction(text, str(page.get("url") or ""))
            if payload is not None:
                logger.info("exemplo de extração construído pelo modelo (%s)", page.get("url"))
                return payload
        logger.info(
            "exemplo de extração construído a partir da própria página (%s): modelo indisponível",
            page.get("url") or page.get("path"),
        )
        fallback = {
            "titulo": str(page.get("title") or "").strip(),
            "url": str(page.get("url") or "").strip(),
            "trecho": _clip(
                _leading_sentences(text, EXTRACTION_SENTENCES), MAX_OUTPUT_CHARS
            ),
        }
        return json.dumps(fallback, ensure_ascii=False)

    def _model_extraction(self, text: str, url: str) -> str | None:
        """JSON of ``zfrog.ai.extraction.extract_structured``'s answer, or ``None``."""
        from zfrog.ai import extraction as extraction_module  # lazy: sibling module

        function = getattr(extraction_module, "extract_structured", None)
        if function is None:
            logger.info(
                "zfrog.ai.extraction.extract_structured indisponível; extração determinística"
            )
            return None
        try:
            result = _run_maybe_async(lambda: _call_extract(function, text, url))
        except Exception as exc:
            logger.warning("extract_structured falhou (%s); extração determinística", exc)
            return None
        payload = _jsonable(result)
        if payload is None:
            return None
        return json.dumps(payload, ensure_ascii=False)

    def _page_entities(self, text: str, source: str) -> list[dict]:
        """Entities extracted by :mod:`zfrog.ai.entities`; empty when it cannot run."""
        if not is_available():
            logger.warning(
                "IA indisponível: exemplos de entidades ignorados para %s "
                "(nenhuma entidade é inventada)",
                source,
            )
            return []
        from zfrog.ai import entities as entities_module  # lazy: sibling module

        try:
            result = _run_maybe_async(lambda: entities_module.extract_entities(text))
        except Exception as exc:
            logger.warning("extração de entidades falhou para %s (%s)", source, exc)
            return []
        items = result.get("entities") if isinstance(result, dict) else None
        if not isinstance(items, list):
            logger.warning("resultado de entidades inesperado para %s: %r", source, type(result))
            return []
        entities = [item for item in items if isinstance(item, dict) and item.get("name")]
        if not entities:
            logger.warning("nenhuma entidade extraída para %s: exemplo não construído", source)
        return entities

    # ── exporting ───────────────────────────────────────────────────

    def export(self, path: Path | None = None, fmt: str = "chat") -> Path:
        """Write the valid examples as JSONL and return the file path.

        One example per line, in the requested shape. Examples that fail
        :func:`validate_example` are skipped, logged, and counted in
        :attr:`last_export` (``{"path", "format", "written", "skipped"}``).

        With no explicit ``path`` the next free ``root/dataset-<n>.jsonl`` is used,
        so exporting twice never overwrites the first file; an explicit ``path``
        is overwritten.

        Raises:
            ValueError: ``fmt`` is neither ``"chat"`` nor ``"alpaca"``.
        """
        if fmt not in FORMATS:
            raise ValueError(f"formato desconhecido: {fmt!r} (use {' ou '.join(FORMATS)})")
        render = chat_format if fmt == "chat" else alpaca_format
        target = Path(path) if path is not None else self._next_dataset_path()
        target.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        skipped = 0
        handle_fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
                for example in self._examples:
                    problems = validate_example(example)
                    if problems:
                        skipped += 1
                        logger.warning(
                            "exemplo de %s ignorado na exportação (%s): %s",
                            example.kind,
                            example.source,
                            "; ".join(problems),
                        )
                        continue
                    handle.write(json.dumps(render(example), ensure_ascii=False) + "\n")
                    written += 1
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, FILE_MODE)
            os.replace(temp_path, target)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

        self.last_export = {
            "path": str(target),
            "format": fmt,
            "written": written,
            "skipped": skipped,
        }
        logger.info("conjunto exportado para %s (%d exemplos, %d ignorados)", target, written, skipped)
        return target

    def _next_dataset_path(self) -> Path:
        """Next free ``dataset-<n>.jsonl`` under the root, so nothing is overwritten."""
        highest = 0
        if self.root.is_dir():
            for entry in self.root.glob("dataset-*.jsonl"):
                match = _DATASET_NAME.fullmatch(entry.name)
                if match:
                    highest = max(highest, int(match.group(1)))
        return self.root / f"dataset-{highest + 1}.jsonl"

    # ── persistence ─────────────────────────────────────────────────

    def _save(self) -> None:
        """Persist the built examples at ``root/examples.json`` (atomic, mode 0600)."""
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "examples": [asdict(example) for example in self._examples],
        }
        _write_json_atomic(self.root / EXAMPLES_FILE, payload)

    def _load(self) -> None:
        """Load previously built examples, tolerating a missing or corrupt file."""
        path = self.root / EXAMPLES_FILE
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("não foi possível ler %s: %s", path, exc)
            return
        raw = payload.get("examples") if isinstance(payload, dict) else payload
        if not isinstance(raw, list):
            logger.warning("%s não contém uma lista de exemplos", path)
            return
        loaded: list[TrainingExample] = []
        for item in raw:
            example = _example_from_payload(item)
            if example is not None:
                loaded.append(example)
        self._examples = loaded


def _page_text(page: dict) -> str:
    """Text of a page entry, extracting it from ``html`` when ``text`` is missing."""
    text = str(page.get("text") or "").strip()
    if text:
        return text
    html = page.get("html")
    if html:
        return extract_text(str(html)).strip()
    return ""




