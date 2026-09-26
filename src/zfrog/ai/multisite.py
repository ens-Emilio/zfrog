"""Multi-site RAG with citations — one index over many cloned sites.

Cloned site directories are chunked into a JSON store; queries are answered
with a numbered context and every answer carries the retrieved chunks as
citations (url + local path), so sources can be shown even without an LLM.

Ranking uses embeddings + cosine similarity when the AI client is available,
and falls back to a BM25 lexical score otherwise.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from zfrog.ai.client import complete, embed, is_available
from zfrog.config import settings
from zfrog.diff import page_url_from_path
from zfrog.utils.text import extract_text

logger = logging.getLogger(__name__)

CHUNK_CHARS = 1000
SNIPPET_CHARS = 300
BM25_K1 = 1.5
BM25_B = 0.75
DEFAULT_TOP_K = 6

_TOKEN_RE = re.compile(r"[0-9a-z]+")

SYSTEM_PROMPT = (
    "Responda à pergunta usando APENAS o contexto numerado fornecido. "
    "Cite as fontes com [n] após cada afirmação, usando o número do trecho. "
    "Se a informação não estiver no contexto, diga que não encontrou."
)


@dataclass
class Citation:
    """A retrieved chunk backing an answer."""

    site: str
    url: str
    path: str
    snippet: str
    score: float


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens."""
    return _TOKEN_RE.findall(text.lower())


def _chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split text into ~`size` char chunks on word boundaries, no overlap."""
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    length = 0

    for word in words:
        # +1 accounts for the joining space.
        if current and length + len(word) + 1 > size:
            chunks.append(" ".join(current))
            current, length = [], 0
        current.append(word)
        length += len(word) + 1

    if current:
        chunks.append(" ".join(current))
    return chunks


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors (0.0 when either has no magnitude)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """Collapse whitespace and truncate for display."""
    flat = " ".join(text.split())
    return flat[:limit]


class MultiSiteIndex:
    """A single chunk index spanning many cloned sites."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else settings.output_dir / ".rag-multi"
        self.root.mkdir(parents=True, exist_ok=True)
        self.chunks_file = self.root / "chunks.json"
        self.embeddings_file = self.root / "embeddings.json"
        self.chunks: list[dict] = []
        self.embeddings: dict[str, list[float]] = {}
        self._load()

    # ── persistence ──────────────────────────────────────────────

    def _load(self) -> None:
        if self.chunks_file.exists():
            try:
                data = json.loads(self.chunks_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning("Chunk store %s is corrupt; starting empty", self.chunks_file)
                data = []
            if isinstance(data, list):
                self.chunks = [c for c in data if isinstance(c, dict)]
        if self.embeddings_file.exists():
            try:
                data = json.loads(self.embeddings_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning("Embedding store %s is corrupt; ignoring", self.embeddings_file)
                data = {}
            if isinstance(data, dict):
                self.embeddings = {k: v for k, v in data.items() if isinstance(v, list)}

    def _save(self) -> None:
        self.chunks_file.write_text(
            json.dumps(self.chunks, ensure_ascii=False), encoding="utf-8"
        )
        self.embeddings_file.write_text(
            json.dumps(self.embeddings, ensure_ascii=False), encoding="utf-8"
        )

    # ── indexing ─────────────────────────────────────────────────

    def _site_files(self, dir_path: Path) -> list[Path]:
        """HTML files under a cloned site, skipping directories named ``*.html``."""
        return sorted(p for p in dir_path.rglob("*.html") if p.is_file())

    def add_text(
        self,
        site: str,
        text: str,
        path: str = "",
        url: str = "",
        replace: bool = False,
    ) -> int:
        """Index raw text under `site`, returning the number of chunks added.

        `replace=True` drops the site's existing chunks first; the default
        appends, so a caller can feed several pages of the same site.
        """
        if replace:
            self._drop_site_chunks(site)

        added = 0
        for index, chunk in enumerate(_chunk_text(text)):
            if not chunk.strip():
                continue
            self.chunks.append(
                {
                    "site": site,
                    "url": url or site,
                    "path": path,
                    "text": chunk,
                    "chunk_id": hashlib.sha1(
                        f"{site}{path}{index}".encode("utf-8")
                    ).hexdigest()[:12],
                }
            )
            added += 1

        self._prune_embeddings()
        self._save()
        return added

    def add_site(self, url: str, dir_path: Path) -> int:
        """Index a cloned site directory, replacing any previous copy of `url`.

        Returns the number of chunks added for this site. A missing directory
        logs a warning and leaves the existing chunks of `url` untouched.
        """
        dir_path = Path(dir_path)
        if not dir_path.is_dir():
            logger.warning("add_site: %s is not a directory, nothing indexed", dir_path)
            return 0

        self._drop_site_chunks(url)

        added = 0
        for file_path in self._site_files(dir_path):
            rel = file_path.relative_to(dir_path).as_posix()
            try:
                html = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("add_site: cannot read %s: %s", file_path, exc)
                continue

            added += self.add_text(
                site=url,
                text=extract_text(html),
                path=rel,
                url=page_url_from_path(rel, url),
            )

        self._prune_embeddings()
        self._save()
        logger.info("Indexed %d chunks from %s (%s)", added, url, dir_path)
        return added

    def remove_site(self, url: str) -> int:
        """Drop every chunk of `url`; returns how many were removed."""
        removed = self._drop_site_chunks(url)
        self._prune_embeddings()
        self._save()
        return removed

    def _drop_site_chunks(self, url: str) -> int:
        before = len(self.chunks)
        self.chunks = [c for c in self.chunks if c.get("site") != url]
        return before - len(self.chunks)

    def _prune_embeddings(self) -> None:
        live = {c["chunk_id"] for c in self.chunks}
        self.embeddings = {k: v for k, v in self.embeddings.items() if k in live}

    # ── introspection ────────────────────────────────────────────

    def sites(self) -> list[dict]:
        """One entry per indexed site: url, page count and chunk count."""
        pages: dict[str, set[str]] = {}
        chunks: Counter[str] = Counter()
        for chunk in self.chunks:
            site = chunk["site"]
            pages.setdefault(site, set()).add(chunk["path"])
            chunks[site] += 1
        return [
            {"url": url, "pages": len(pages[url]), "chunks": chunks[url]}
            for url in sorted(pages)
        ]

    def stats(self) -> dict:
        """Index size summary."""
        site_entries = self.sites()
        return {
            "root": str(self.root),
            "sites": len(site_entries),
            "pages": sum(s["pages"] for s in site_entries),
            "chunks": len(self.chunks),
            "embeddings": len(self.embeddings),
        }

    # ── ranking ──────────────────────────────────────────────────

    async def _ensure_embeddings(self) -> None:
        """Embed chunks that have no vector yet and persist them."""
        pending = [c for c in self.chunks if c["chunk_id"] not in self.embeddings]
        if not pending:
            return
        vectors = await embed([c["text"] for c in pending])
        if len(vectors) != len(pending):
            logger.warning(
                "Embedding count mismatch (%d vectors for %d chunks)", len(vectors), len(pending)
            )
            return
        for chunk, vector in zip(pending, vectors):
            self.embeddings[chunk["chunk_id"]] = [float(x) for x in vector]
        self._save()

    async def _rank(self, question: str, top_k: int) -> list[tuple[float, dict]]:
        """Best chunks for a question as ``(score, chunk)`` pairs."""
        if is_available():
            try:
                await self._ensure_embeddings()
                if self.embeddings:
                    query_vectors = await embed([question])
                    query_vector = [float(x) for x in query_vectors[0]]
                    scored = [
                        (_cosine(query_vector, self.embeddings[c["chunk_id"]]), c)
                        for c in self.chunks
                        if c["chunk_id"] in self.embeddings
                    ]
                    if scored:
                        scored.sort(key=lambda pair: pair[0], reverse=True)
                        return scored[:top_k]
            except Exception as exc:  # provider down, bad model, ...
                logger.warning("Embedding ranking unavailable (%s); using lexical score", exc)
        return self._lexical_rank(question, top_k)

    def _lexical_rank(self, question: str, top_k: int) -> list[tuple[float, dict]]:
        """BM25 ranking over chunk tokens."""
        query_terms = _tokenize(question)
        if not query_terms:
            return [(0.0, c) for c in self.chunks[:top_k]]

        total = len(self.chunks)
        doc_tokens = [_tokenize(c["text"]) for c in self.chunks]
        doc_freq: Counter[str] = Counter()
        for tokens in doc_tokens:
            doc_freq.update(set(tokens))
        avg_len = (sum(len(t) for t in doc_tokens) / total) or 1.0

        scored: list[tuple[float, dict]] = []
        for tokens, chunk in zip(doc_tokens, self.chunks):
            counts = Counter(tokens)
            length = len(tokens) or 1
            score = 0.0
            for term in query_terms:
                freq = counts.get(term, 0)
                if not freq:
                    continue
                idf = math.log(1 + (total - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
                score += idf * (freq * (BM25_K1 + 1)) / (
                    freq + BM25_K1 * (1 - BM25_B + BM25_B * length / avg_len)
                )
            scored.append((score, chunk))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        hits = [(s, c) for s, c in scored[:top_k] if s > 0]
        return hits or scored[:top_k]

    # ── querying ─────────────────────────────────────────────────

    def _context(self, ranked: Iterable[tuple[float, dict]]) -> str:
        blocks = []
        for position, (_, chunk) in enumerate(ranked, start=1):
            blocks.append(f"[{position}] {chunk['url']} ({chunk['path']})\n{chunk['text']}")
        return "\n\n".join(blocks)

    async def query(self, question: str, top_k: int = DEFAULT_TOP_K) -> dict:
        """Answer a question across every indexed site, with citations."""
        top_k = max(1, top_k)
        if not self.chunks:
            return {
                "answer": "Nenhum conteúdo indexado ainda.",
                "citations": [],
                "sites": [],
            }

        ranked = await self._rank(question, top_k)
        citations = [
            Citation(
                site=chunk["site"],
                url=chunk["url"],
                path=chunk["path"],
                snippet=_snippet(chunk["text"]),
                score=round(score, 6),
            )
            for score, chunk in ranked
        ]
        sites: list[str] = []
        for citation in citations:
            if citation.site not in sites:
                sites.append(citation.site)

        if not citations:
            return {
                "answer": "Nenhum trecho relevante encontrado para a pergunta.",
                "citations": [],
                "sites": [],
            }

        context = self._context(ranked)
        answer = await self._answer(question, context, citations)
        return {"answer": answer, "citations": citations, "sites": sites}

    async def _answer(self, question: str, context: str, citations: list[Citation]) -> str:
        """Ask the model to answer from the numbered context, citing [n]."""
        fallback = (
            f"LLM indisponível: encontrei {len(citations)} trechos relevantes em "
            f"{len({c.site for c in citations})} site(s). Veja as citações."
        )
        if not is_available():
            return fallback

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Contexto:\n\n{context}\n\n---\nPergunta: {question}",
            },
        ]
        try:
            answer = await complete(messages=messages, temperature=0.0, max_tokens=1024)
        except Exception as exc:
            logger.warning("Completion failed (%s); returning citations only", exc)
            return fallback
        answer = (answer or "").strip()
        return answer or fallback
