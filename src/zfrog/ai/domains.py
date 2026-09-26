"""Domain specialisation for extraction prompts.

What this module does — and, plainly, what it does not: it specialises the
**model's instructions** per domain. A :class:`DomainProfile` carries a
terminology glossary (term -> meaning), few-shot examples, extra instructions and
the entity types worth looking for, and those are composed into the prompt sent
to the language model. No weights are trained, no checkpoint is produced and no
model is fine-tuned: the underlying model is exactly the same before and after,
only the text of the instructions changes.

Profiles live as one JSON file per profile under ``settings.domain_profiles_dir``
(``domains/`` by default), so a shared folder or a git repository works as a
profile library without a server. Three useful profiles — ``legal``,
``ecommerce`` and ``news`` — ship in code (see :meth:`DomainProfileStore.builtin`)
and are never written to disk.

Prompts are capped at :data:`MAX_PROMPT_CHARS`: the terminology list is dropped
entry by entry with an explicit omission notice when the budget runs out, because
a prompt that silently grows without bound is a bug (it costs tokens and pushes
the model out of context).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from zfrog.ai.client import complete_structured, is_available
from zfrog.ai.schemas import ExtractionResult
from zfrog.config import settings

logger = logging.getLogger(__name__)

#: Hard ceiling for a composed system prompt, in characters.
MAX_PROMPT_CHARS = 4000

#: Used when the caller passes no base prompt (or an empty one).
DEFAULT_BASE_PROMPT = (
    "Você é um assistente de extração de dados em português. "
    "Responda apenas com o que está no texto fornecido, sem inventar informação."
)

#: Base prompt used by :func:`extract_with_profile` before the profile is applied.
BASE_EXTRACTION_PROMPT = (
    "Você extrai dados estruturados de páginas web em português. "
    "Devolva apenas os itens que aparecem no texto, com o rótulo e o valor exatos."
)

#: Appended to a prompt when the terminology list had to be cut short.
OMISSION_NOTICE = "\n(+{count} termos omitidos: limite de {budget} caracteres)"

#: Suffix used when even the base prompt alone exceeds the budget.
_CLIP_SUFFIX = " …[truncado]"

_SEPARATOR = re.compile(r"[^a-z0-9]+")

# Heuristic hints for :func:`suggest_profile` (already ASCII-folded and lowercase).
# Host hints are plain substrings (hosts glue words together); text hints are
# regexes so that short words like "reu" only match a whole word.
_LEGAL_HOST_HINTS = ("jus", "law", "court", "tribunal", "juridico", "advocacia", "oab")
_ECOMMERCE_HOST_HINTS = ("shop", "store", "loja", "mercado", "preco", "ecommerce", "compras")
_NEWS_HOST_HINTS = ("news", "noticia", "jornal", "blog", "gazeta", "revista")

_LEGAL_TEXT_HINTS = (
    r"jurisprud",
    r"clausul",
    r"contrato",
    r"peticao",
    r"acordao",
    r"\breu\b",
    r"autos do processo",
)
_ECOMMERCE_TEXT_HINTS = (
    r"\bfrete\b",
    r"carrinho",
    r"\bestoque\b",
    r"\bsku\b",
    r"\bpreco\b",
    r"\bcomprar\b",
)
_NEWS_TEXT_HINTS = (
    r"noticia",
    r"\bjornal\b",
    r"\bveiculo\b",
    r"reportagem",
    r"manchete",
    r"redacao",
)


@dataclass
class DomainProfile:
    """A domain's prompt-level specialisation (terminology, examples, hints)."""

    id: str
    name: str = ""
    description: str = ""
    terminology: dict[str, str] = field(default_factory=dict)
    examples: list[dict] = field(default_factory=list)
    instructions: str = ""
    entity_types: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class DomainProfileStore:
    """JSON-file store of domain profiles, one file per profile, written atomically."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else Path(settings.domain_profiles_dir)

    # ── CRUD ────────────────────────────────────────────────────────

    def save(self, profile: DomainProfile | dict) -> DomainProfile:
        """Store ``profile`` under its id, replacing a profile with that id.

        An id is slugified from ``name`` when it is missing, and a profile with
        neither id nor name is refused (``ValueError``) without writing anything.
        ``created_at`` is kept from the stored profile on an update.
        """
        payload = _as_payload(profile)
        name = str(payload.get("name") or "").strip()
        profile_id = str(payload.get("id") or "").strip()
        if not profile_id:
            profile_id = _slugify(name)
        if not profile_id:
            raise ValueError("o perfil precisa de um id ou de um nome")

        existing = self.get(profile_id)
        created_at = (
            existing.created_at
            if existing is not None and existing.created_at
            else str(payload.get("created_at") or "").strip() or _now()
        )
        stored = DomainProfile(
            id=profile_id,
            name=name or profile_id,
            description=str(payload.get("description") or "").strip(),
            terminology=_clean_terminology(payload.get("terminology")),
            examples=_clean_examples(payload.get("examples")),
            instructions=str(payload.get("instructions") or "").strip(),
            entity_types=_clean_list(payload.get("entity_types")),
            tags=_clean_list(payload.get("tags")),
            created_at=created_at,
            updated_at=_now(),
        )
        self._write_atomic(self._path(profile_id), asdict(stored))
        logger.info("Perfil de domínio %s salvo", profile_id)
        return stored

    def get(self, profile_id: str) -> DomainProfile | None:
        """Return the stored profile with this id, or None when there is none."""
        wanted = str(profile_id or "").strip()
        if not wanted:
            return None
        path = self._path(wanted)
        if not path.is_file():
            return None
        stored = self._read(path)
        if stored is None or stored.id != wanted:
            return None
        return stored

    def list(self) -> list[DomainProfile]:
        """Every stored profile, sorted by id (unreadable files are skipped)."""
        if not self.root.is_dir():
            return []
        profiles = [
            profile
            for profile in (self._read(path) for path in sorted(self.root.glob("*.json")))
            if profile is not None
        ]
        return sorted(profiles, key=lambda profile: profile.id)

    def remove(self, profile_id: str) -> bool:
        """Delete the stored profile with this id; True when a file was removed."""
        wanted = str(profile_id or "").strip()
        if not wanted:
            return False
        path = self._path(wanted)
        if not path.is_file():
            return False
        stored = self._read(path)
        if stored is not None and stored.id != wanted:
            return False
        path.unlink()
        logger.info("Perfil de domínio %s removido", wanted)
        return True

    @staticmethod
    def builtin() -> list[DomainProfile]:
        """The three profiles that ship in code, never written to disk.

        ``legal``, ``ecommerce`` and ``news``: real seeds with terminology,
        few-shot examples and entity types, ready to be resolved by id.
        """
        return [_build(seed) for seed in _BUILTIN_SEEDS]

    # ── internals ───────────────────────────────────────────────────

    def _path(self, profile_id: str) -> Path:
        """File holding ``profile_id``; ids that slugify to nothing use a digest."""
        slug = _slugify(profile_id)
        if not slug:
            slug = hashlib.sha1(profile_id.encode("utf-8")).hexdigest()[:12]
        return self.root / f"{slug}.json"

    def _write_atomic(self, path: Path, payload: dict) -> None:
        """Write ``payload`` to ``path`` through a temp file plus ``os.replace``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        handle_fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

    def _read(self, path: Path) -> DomainProfile | None:
        """Read one profile file, returning None (and logging) when it is unusable."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("perfil não é um objeto JSON")
            profile_id = str(payload["id"]).strip()
            if not profile_id:
                raise ValueError("perfil sem id")
        except Exception as exc:
            logger.warning("perfil de domínio ilegível em %s: %s", path, exc)
            return None
        return DomainProfile(
            id=profile_id,
            name=str(payload.get("name") or profile_id),
            description=str(payload.get("description") or ""),
            terminology=_clean_terminology(payload.get("terminology")),
            examples=_clean_examples(payload.get("examples")),
            instructions=str(payload.get("instructions") or ""),
            entity_types=_clean_list(payload.get("entity_types")),
            tags=_clean_list(payload.get("tags")),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )


def resolve(profile_id: str | None, store: DomainProfileStore | None = None) -> DomainProfile | None:
    """Look ``profile_id`` up in ``store`` first, then among the builtins.

    Returns None for an unknown (or empty) id.
    """
    wanted = str(profile_id or "").strip()
    if not wanted:
        return None
    profile_store = store if store is not None else DomainProfileStore()
    found = profile_store.get(wanted)
    if found is not None:
        return found
    for profile in DomainProfileStore.builtin():
        if profile.id == wanted:
            return profile
    return None


def system_prompt(profile: DomainProfile | None, base: str = "") -> str:
    """Compose the system prompt for ``profile``: base, instructions, terms, entities.

    ``base`` defaults to :data:`DEFAULT_BASE_PROMPT`. Without a profile the base
    is returned as is. The result never exceeds :data:`MAX_PROMPT_CHARS`
    characters; terminology is dropped from the end with an explicit notice when
    it does not fit.
    """
    base_text = (base or "").strip() or DEFAULT_BASE_PROMPT
    if profile is None:
        return _clip(base_text)

    sections = [base_text]
    instructions = str(profile.instructions or "").strip()
    if instructions:
        sections.append(instructions)
    entity_types = [str(item).strip() for item in (profile.entity_types or []) if str(item).strip()]
    if entity_types:
        sections.append("Tipos de entidade a procurar: " + ", ".join(entity_types) + ".")
    head = "\n\n".join(sections)

    entries = [
        f"{term}: {meaning}"
        for term, meaning in (profile.terminology or {}).items()
        if str(term).strip() and str(meaning).strip()
    ]
    if not entries:
        return _clip(head)

    prefix = "\n\nTerminologia do domínio:\n"
    kept: list[str] = []
    for index, entry in enumerate(entries):
        notice = OMISSION_NOTICE.format(count=len(entries) - index - 1, budget=MAX_PROMPT_CHARS)
        candidate = head + prefix + "\n".join([*kept, entry]) + notice
        if len(candidate) > MAX_PROMPT_CHARS:
            break
        kept.append(entry)

    if not kept:
        return _clip(head)
    omitted = len(entries) - len(kept)
    notice = OMISSION_NOTICE.format(count=omitted, budget=MAX_PROMPT_CHARS) if omitted else ""
    return head + prefix + "\n".join(kept) + notice


def few_shot_messages(profile: DomainProfile, limit: int = 2) -> list[dict]:
    """Return the profile's examples as ``user``/``assistant`` message pairs.

    At most ``limit`` examples are used, and incomplete examples are skipped.
    """
    try:
        cap = max(0, int(limit))
    except (TypeError, ValueError):
        cap = 0
    messages: list[dict] = []
    for example in (profile.examples or [])[:cap]:
        if not isinstance(example, dict):
            continue
        user_text = str(example.get("input") or "").strip()
        assistant_text = str(example.get("output") or "").strip()
        if not user_text or not assistant_text:
            continue
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": assistant_text})
    return messages


def apply(
    profile: DomainProfile | None,
    messages: list[dict],
    base_prompt: str = "",
    limit: int = 2,
) -> list[dict]:
    """Return a NEW message list specialised for ``profile``.

    The domain system prompt is prepended (replacing an existing leading system
    message) and the few-shot pairs are inserted right before the last user
    message. Without a profile the messages come back as an equal but distinct
    copy — the input list and its dicts are never mutated.
    """
    prepared = [dict(message) for message in messages]
    if profile is None:
        return prepared

    if prepared and prepared[0].get("role") == "system":
        prepared = prepared[1:]
    head = [{"role": "system", "content": system_prompt(profile, base_prompt)}]
    pairs = few_shot_messages(profile, limit)

    last_user = next(
        (index for index in range(len(prepared) - 1, -1, -1) if prepared[index].get("role") == "user"),
        None,
    )
    if last_user is None:
        return head + prepared + pairs
    return head + prepared[:last_user] + pairs + prepared[last_user:]


def suggest_profile(url: str, text: str = "") -> str | None:
    """Cheap heuristic hint for the builtin profile that fits ``url``/``text``.

    This is a hint, not a classifier: it looks for a handful of keywords in the
    URL host (``jus``/``law``/``court`` -> ``legal``, ``shop``/``store``/``loja``/
    ``preco`` -> ``ecommerce``, ``news``/``noticia``/``jornal``/``blog`` -> ``news``)
    and then in the text. Returns None when nothing matches; callers should let
    the user override the guess.
    """
    host = _fold(_host_of(url))
    for hints, profile_id in (
        (_LEGAL_HOST_HINTS, "legal"),
        (_ECOMMERCE_HOST_HINTS, "ecommerce"),
        (_NEWS_HOST_HINTS, "news"),
    ):
        if any(hint in host for hint in hints):
            return profile_id

    body = _fold(text or "")
    if body:
        for patterns, profile_id in (
            (_LEGAL_TEXT_HINTS, "legal"),
            (_ECOMMERCE_TEXT_HINTS, "ecommerce"),
            (_NEWS_TEXT_HINTS, "news"),
        ):
            if any(re.search(pattern, body) for pattern in patterns):
                return profile_id
    return None


async def extract_with_profile(
    text: str,
    profile: DomainProfile | None = None,
    max_chars: int = 6000,
) -> dict:
    """Extract structured data with the domain instructions applied to the prompt.

    Args:
        text: Content to analyse.
        profile: Domain profile to specialise the prompt with (None keeps the
            generic prompt).
        max_chars: Truncation limit for the input text.

    Returns:
        ``{"items": [{"label", "value", "confidence"}], "summary", "page_title"}``;
        ``"error"`` is added when the text is blank, the AI is unavailable or the
        call failed. Never raises.
    """
    if not str(text or "").strip():
        return _empty("Texto vazio")

    if not is_available():
        return _empty("AI indisponível")

    excerpt = str(text)[: max(0, int(max_chars))]
    messages = [
        {"role": "system", "content": BASE_EXTRACTION_PROMPT},
        {"role": "user", "content": f"Texto:\n\n{excerpt}"},
    ]
    prepared = apply(profile, messages, base_prompt=BASE_EXTRACTION_PROMPT)

    try:
        result = await complete_structured(
            messages=prepared,
            response_model=ExtractionResult,
            temperature=0.0,
        )
    except Exception as exc:
        logger.warning("extração com perfil de domínio falhou: %s", exc)
        return _empty(f"Falha na extração: {exc}")

    return {
        "items": _normalize_items(_items_of(result)),
        "summary": str(_field(result, "summary") or ""),
        "page_title": str(_field(result, "page_title") or ""),
    }


# ── helpers ─────────────────────────────────────────────────────────


def _now() -> str:
    """Current UTC timestamp in ISO-8601 (seconds resolution)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slugify(text: str) -> str:
    """Reduce ``text`` to lowercase ASCII words joined by dashes."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return _SEPARATOR.sub("-", ascii_text).strip("-")


def _fold(text: str) -> str:
    """Lowercase ASCII form of ``text``, keeping spaces (for keyword matching)."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return decomposed.encode("ascii", "ignore").decode("ascii").lower()


def _host_of(url: str) -> str:
    """Host of ``url`` (empty when it cannot be parsed)."""
    try:
        return urlsplit(str(url or "")).netloc
    except ValueError:
        return ""


def _clip(text: str) -> str:
    """Return ``text``, hard-truncated when it exceeds the prompt budget."""
    if len(text) <= MAX_PROMPT_CHARS:
        return text
    return text[: MAX_PROMPT_CHARS - len(_CLIP_SUFFIX)] + _CLIP_SUFFIX


def _as_payload(profile: DomainProfile | dict) -> dict:
    """Normalise a profile or dict into a plain payload dict."""
    if isinstance(profile, DomainProfile):
        return asdict(profile)
    if isinstance(profile, dict):
        return dict(profile)
    raise TypeError(f"perfil inválido: {type(profile).__name__}")


def _clean_list(value: Any) -> list[str]:
    """Return ``value`` as non-empty, de-duplicated, stripped strings in order."""
    if value is None:
        return []
    if isinstance(value, str):
        candidates: list[Any] = [value]
    else:
        try:
            candidates = list(value)
        except TypeError:
            return []
    cleaned: list[str] = []
    for item in candidates:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _clean_terminology(value: Any) -> dict[str, str]:
    """Return ``value`` as a ``term -> meaning`` mapping of non-empty strings."""
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, str] = {}
    for term, meaning in value.items():
        key = str(term).strip()
        text = str(meaning).strip()
        if key and text:
            cleaned[key] = text
    return cleaned


def _clean_examples(value: Any) -> list[dict]:
    """Return ``value`` as a list of ``{"input", "output"}`` example dicts."""
    if not isinstance(value, list):
        return []
    cleaned: list[dict] = []
    for example in value:
        if not isinstance(example, dict):
            continue
        user_text = str(example.get("input") or "").strip()
        assistant_text = str(example.get("output") or "").strip()
        if user_text and assistant_text:
            cleaned.append({"input": user_text, "output": assistant_text})
    return cleaned


def _build(seed: dict) -> DomainProfile:
    """Build a fresh builtin profile from its seed (so callers cannot mutate it)."""
    return DomainProfile(
        id=seed["id"],
        name=seed["name"],
        description=seed["description"],
        terminology=dict(seed["terminology"]),
        examples=[dict(example) for example in seed["examples"]],
        instructions=seed["instructions"],
        entity_types=list(seed["entity_types"]),
        tags=list(seed["tags"]),
        created_at="",
        updated_at="",
    )


def _empty(error: str) -> dict:
    """Empty extraction result carrying the reason it is empty."""
    return {"items": [], "summary": "", "page_title": "", "error": error}


def _field(result: Any, name: str) -> Any:
    """Read ``name`` from a pydantic model or a plain dict."""
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


def _items_of(result: Any) -> Any:
    """Pull the item list out of an ExtractionResult, a dict or a bare list."""
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("items") or []
    return getattr(result, "items", []) or []


def _normalize_items(items: Any) -> list[dict]:
    """Normalise model-provided items into ``{"label", "value", "confidence"}``."""
    if not isinstance(items, (list, tuple)):
        return []
    normalized: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            label = item.get("label")
            value = item.get("value")
            confidence = item.get("confidence", 1.0)
        else:
            label = getattr(item, "label", None)
            value = getattr(item, "value", None)
            confidence = getattr(item, "confidence", 1.0)
        label_text = str(label).strip() if label is not None else ""
        value_text = str(value).strip() if value is not None else ""
        if not label_text and not value_text:
            continue
        normalized.append(
            {
                "label": label_text,
                "value": value_text,
                "confidence": _as_confidence(confidence),
            }
        )
    return normalized


def _as_confidence(value: Any) -> float:
    """Coerce a model-provided confidence into a float clamped to 0-1."""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(1.0, max(0.0, confidence))


_BUILTIN_SEEDS: tuple[dict, ...] = (
    {
        "id": "legal",
        "name": "Jurídico",
        "description": (
            "Contratos, petições, decisões judiciais e diários oficiais: partes, cláusulas, "
            "prazos e jurisprudência."
        ),
        "terminology": {
            "parte": "quem figura no processo (autor, réu, requerente, requerido)",
            "cláusula": "disposição contratual numerada que define direitos e deveres",
            "prazo": "data-limite ou contagem de dias para um ato processual",
            "jurisprudência": "conjunto de decisões de tribunais sobre a mesma matéria",
            "acórdão": "decisão colegiada de um tribunal, com ementa e voto",
            "petição inicial": "peça que abre o processo e formula o pedido",
            "trânsito em julgado": "momento em que a decisão deixa de admitir recurso",
        },
        "examples": [
            {
                "input": "Cláusula 5ª — O prazo para pagamento é de 30 dias, sob pena de multa de 2%.",
                "output": '{"items": [{"label": "cláusula", "value": "5ª"}, '
                '{"label": "prazo", "value": "30 dias"}, {"label": "multa", "value": "2%"}]}',
            },
            {
                "input": "Processo 0001234-56.2024.8.26.0100, autor: Maria Silva, réu: Banco XYZ. "
                "Sentença publicada em 12/03/2024, prazo de recurso de 15 dias.",
                "output": '{"items": [{"label": "processo", "value": "0001234-56.2024.8.26.0100"}, '
                '{"label": "parte", "value": "Maria Silva (autora)"}, '
                '{"label": "parte", "value": "Banco XYZ (réu)"}, '
                '{"label": "prazo", "value": "15 dias para recurso"}]}',
            },
        ],
        "instructions": (
            "Trate o texto como peça jurídica. Preserve a numeração de cláusulas e artigos, "
            "cite prazos com a unidade (dias, meses) e separe as partes pelo papel processual "
            "(autor, réu, requerente). Não resuma a norma: extraia o texto e o número."
        ),
        "entity_types": ["parte", "cláusula", "prazo", "tribunal", "processo", "valor", "advogado"],
        "tags": ["juridico", "contratos", "processos"],
    },
    {
        "id": "ecommerce",
        "name": "E-commerce",
        "description": (
            "Páginas de produto e listagens de loja: produtos, preços, SKU, estoque e frete."
        ),
        "terminology": {
            "produto": "item à venda, com nome comercial como aparece na página",
            "preço": "valor de venda na moeda informada (R$ 1.299,00)",
            "SKU": "código único que identifica a variação do produto",
            "estoque": "quantidade disponível ou indisponibilidade declarada",
            "frete": "custo e prazo de entrega informados no anúncio",
            "variação": "cor, tamanho ou voltagem que distingue versões do mesmo produto",
            "preço promocional": "valor com desconto, distinto do preço de lista",
        },
        "examples": [
            {
                "input": "Fone Bluetooth XZ-200, SKU: XZ200-PTO, R$ 249,90 (de R$ 399,00). "
                "Estoque: 12 unidades. Frete grátis acima de R$ 199.",
                "output": '{"items": [{"label": "produto", "value": "Fone Bluetooth XZ-200"}, '
                '{"label": "sku", "value": "XZ200-PTO"}, '
                '{"label": "preço promocional", "value": "R$ 249,90"}, '
                '{"label": "preço", "value": "R$ 399,00"}, '
                '{"label": "estoque", "value": "12 unidades"}, '
                '{"label": "frete", "value": "grátis acima de R$ 199"}]}',
            },
            {
                "input": "Tênis Runner Pro — tamanhos 38 a 44, cor azul. R$ 189,90. "
                "Indisponível na cor preta. Entrega em até 5 dias úteis.",
                "output": '{"items": [{"label": "produto", "value": "Tênis Runner Pro"}, '
                '{"label": "variação", "value": "tamanhos 38 a 44, azul"}, '
                '{"label": "preço", "value": "R$ 189,90"}, '
                '{"label": "estoque", "value": "indisponível na cor preta"}, '
                '{"label": "frete", "value": "até 5 dias úteis"}]}',
            },
        ],
        "instructions": (
            "Trate o texto como anúncio de produto. Mantenha valores exatamente como aparecem "
            "(símbolo da moeda e separador decimal) e nunca calcule descontos. Diferencie preço "
            "de lista de preço promocional e registre variações (cor, tamanho) como itens próprios."
        ),
        "entity_types": ["produto", "preço", "sku", "estoque", "frete", "categoria", "variação"],
        "tags": ["ecommerce", "produtos", "precos"],
    },
    {
        "id": "news",
        "name": "Notícias",
        "description": (
            "Reportagens e artigos: título, autor, data, veículo e temas cobertos."
        ),
        "terminology": {
            "título": "manchete principal do material, como publicada",
            "autor": "assinatura da reportagem (jornalista ou agência)",
            "data": "data de publicação no formato em que aparece",
            "veículo": "meio que publicou (jornal, portal, agência)",
            "lide": "primeiro parágrafo, que responde o quê, quem, quando e onde",
            "retranca": "editoria ou seção do material (Política, Economia, Esportes)",
            "tema": "assunto central tratado na matéria",
        },
        "examples": [
            {
                "input": "Prefeitura anuncia obras no centro — Por Ana Ribeiro, 14/02/2024. "
                "A obra começa em março e dura 8 meses.",
                "output": '{"items": [{"label": "título", "value": "Prefeitura anuncia obras no centro"}, '
                '{"label": "autor", "value": "Ana Ribeiro"}, '
                '{"label": "data", "value": "14/02/2024"}, '
                '{"label": "tema", "value": "obras públicas no centro"}]}',
            },
            {
                "input": "Jornal da Cidade · Economia · 03/03/2024 · Agência Brasil. "
                "Inflação do mês fica em 0,4%, segundo o IBGE.",
                "output": '{"items": [{"label": "veículo", "value": "Jornal da Cidade"}, '
                '{"label": "retranca", "value": "Economia"}, '
                '{"label": "data", "value": "03/03/2024"}, '
                '{"label": "autor", "value": "Agência Brasil"}, '
                '{"label": "tema", "value": "inflação de 0,4% no mês"}]}',
            },
        ],
        "instructions": (
            "Trate o texto como material jornalístico. Extraia a manchete exatamente como "
            "publicada, a assinatura e a data no formato original, e identifique o veículo. "
            "Distinga opinião do autor de fato relatado ao escolher os temas."
        ),
        "entity_types": ["título", "autor", "data", "veículo", "tema", "retranca", "local"],
        "tags": ["noticias", "midia", "jornalismo"],
    },
)
