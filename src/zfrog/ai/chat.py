"""Multi-turn chat over cloned sites, with a persisted conversation history.

:meth:`MultiSiteIndex.query <zfrog.ai.multisite.MultiSiteIndex.query>` answers one
question at a time; this module adds the conversation layer on top of the same
index: the retrieved chunks become the citations, the last turns are replayed to
the model so follow-ups like "e o segundo?" keep their context, and every
conversation is stored as one JSON file under ``<output_dir>/chats``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from zfrog.ai.client import complete, is_available
from zfrog.ai.multisite import MultiSiteIndex
from zfrog.config import settings

logger = logging.getLogger(__name__)

DEFAULT_MAX_TURNS = 12
DEFAULT_TOP_K = 6
SNIPPET_CHARS = 300
MAX_ANSWER_TOKENS = 1024
FILE_MODE = 0o600
ROLES = ("user", "assistant")
ROLE_LABELS = {"user": "Usuário", "assistant": "Assistente"}

EMPTY_INDEX_ANSWER = (
    "Nenhum conteúdo indexado ainda: adicione uma pasta de site clonado antes de perguntar."
)

SYSTEM_PROMPT = (
    "Você conversa sobre sites clonados. Responda em português, usando somente o "
    "contexto numerado fornecido e citando as fontes como [1], [2]. "
    "Use o histórico da conversa para entender perguntas de continuação. "
    "Se o contexto não responder, diga o que falta em vez de inventar."
)

def _now() -> str:
    """Current UTC timestamp in ISO 8601 form."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _new_id() -> str:
    """Short random conversation identifier."""
    return uuid.uuid4().hex[:12]

def _snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """Collapse whitespace and truncate a chunk for display."""
    flat = " ".join(text.split())
    return flat[:limit]

@dataclass
class Turn:
    """One message of a conversation, with the chunks that backed it."""

    role: str
    content: str
    citations: list[dict] = field(default_factory=list)
    timestamp: str = field(default_factory=_now)

@dataclass
class Conversation:
    """A chat thread over a set of indexed sites."""

    id: str = field(default_factory=_new_id)
    sites: list[str] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    created_at: str = field(default_factory=_now)

class ChatSession:
    """A conversation over an indexed set of cloned sites.

    The index is shared with the rest of the platform (``MultiSiteIndex``), so a
    session only owns the turns; the retrieval and the ranking stay in the index.
    """

    def __init__(
        self,
        index: MultiSiteIndex | None = None,
        history_dir: Path | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,
    ):
        self.index = index if index is not None else MultiSiteIndex()
        self.history_dir = (
            Path(history_dir) if history_dir is not None else settings.output_dir / "chats"
        )
        self.max_turns = max(1, int(max_turns))
        self.top_k = DEFAULT_TOP_K
        self.conversation = Conversation()

    # ── sites ────────────────────────────────────────────────────

    def add_site(self, url: str, dir_path: Path) -> int:
        """Index a cloned site directory and remember its label."""
        added = self.index.add_site(url, Path(dir_path))
        if url not in self.conversation.sites:
            self.conversation.sites.append(url)
        return added

    def sites(self) -> list[dict]:
        """The indexed sites, as reported by the underlying index."""
        return self.index.sites()

    # ── conversation ─────────────────────────────────────────────

    def history(self) -> list[Turn]:
        """The turns of this conversation, oldest first."""
        return list(self.conversation.turns)

    def reset(self) -> None:
        """Drop the turns, keeping the indexed sites and the conversation id."""
        self.conversation.turns.clear()

    async def ask(self, question: str) -> dict:
        """Answer `question` in the context of this conversation.

        Returns ``{"answer", "citations", "turn"}`` where ``turn`` is the index
        of the assistant turn inside :meth:`history`.
        """
        self._append("user", question, [])
        if not self.index.chunks:
            answer = EMPTY_INDEX_ANSWER
            position = self._append("assistant", answer, [])
            self.save()
            return {"answer": answer, "citations": [], "turn": position}

        context, citations = await self._retrieve(question)
        answer = await self._answer(question, context, citations)
        position = self._append("assistant", answer, citations)
        self.save()
        return {"answer": answer, "citations": citations, "turn": position}

    async def _retrieve(self, question: str) -> tuple[str, list[dict]]:
        """Ranked context and citations for `question`.

        Reuses the index ranking (embeddings when a model is configured, BM25
        otherwise) without asking the index for its own one-shot answer, so the
        conversation history is what reaches the model.
        """
        ranked = await self.index._rank(question, self.top_k)
        citations = [
            {
                "site": chunk["site"],
                "url": chunk["url"],
                "path": chunk["path"],
                "snippet": _snippet(chunk["text"]),
                "score": round(score, 6),
            }
            for score, chunk in ranked
        ]
        return self.index._context(ranked), citations

    async def _answer(self, question: str, context: str, citations: list[dict]) -> str:
        """Ask the model, replaying the recent turns; never raise."""
        fallback = (
            f"IA indisponível: encontrei {len(citations)} trecho(s) relevantes em "
            f"{len({c['site'] for c in citations})} site(s). Veja as citações."
        )
        if not is_available():
            return fallback
        try:
            answer = await complete(
                messages=self._messages(question, context),
                temperature=0.0,
                max_tokens=MAX_ANSWER_TOKENS,
            )
        except Exception as exc:  # provider down, bad model, timeout, ...
            logger.warning("Chat completion failed (%s); returning citations only", exc)
            return fallback
        return (answer or "").strip() or fallback

    def _messages(self, question: str, context: str) -> list[dict[str, str]]:
        """System prompt, the last `max_turns` previous turns, then the question."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        previous = self.conversation.turns[:-1][-self.max_turns :]
        messages.extend({"role": turn.role, "content": turn.content} for turn in previous)
        messages.append(
            {"role": "user", "content": f"Contexto:\n\n{context}\n\n---\nPergunta: {question}"}
        )
        return messages

    def _append(self, role: str, content: str, citations: list[dict]) -> int:
        """Add a turn and return its position in the history."""
        self.conversation.turns.append(Turn(role=role, content=content, citations=citations))
        return len(self.conversation.turns) - 1

    # ── persistence ──────────────────────────────────────────────

    def save(self) -> Path:
        """Write the conversation to ``<history_dir>/<id>.json`` atomically."""
        self.history_dir.mkdir(parents=True, exist_ok=True)
        target = self.history_dir / f"{self.conversation.id}.json"
        payload = {
            "id": self.conversation.id,
            "sites": self.conversation.sites,
            "created_at": self.conversation.created_at,
            "turns": [asdict(turn) for turn in self.conversation.turns],
        }
        handle, temp_name = tempfile.mkstemp(
            dir=self.history_dir, prefix=f".{self.conversation.id}.", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp_name, FILE_MODE)
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return target

    def load(self, conversation_id: str) -> Conversation | None:
        """Load a stored conversation, or ``None`` when missing or corrupt."""
        path = self._path_for(conversation_id)
        if path is None or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            conversation = _conversation_from(data)
        except (OSError, TypeError, ValueError, KeyError) as exc:
            logger.warning("Conversa %s corrompida (%s); ignorando", path, exc)
            return None
        self.conversation = conversation
        return conversation

    def _path_for(self, conversation_id: str) -> Path | None:
        """Path of a conversation file, rejecting ids that escape the directory."""
        name = str(conversation_id)
        if not name or Path(name).name != name:
            return None
        return self.history_dir / f"{name}.json"

def _conversation_from(data: object) -> Conversation:
    """Rebuild a :class:`Conversation` from stored JSON, validating its shape."""
    if not isinstance(data, dict):
        raise TypeError("conversation payload is not an object")
    raw_turns = data.get("turns", [])
    if not isinstance(raw_turns, list):
        raise TypeError("turns is not a list")
    turns: list[Turn] = []
    for raw in raw_turns:
        if not isinstance(raw, dict):
            raise TypeError("turn is not an object")
        role = raw.get("role")
        content = raw.get("content")
        if role not in ROLES or not isinstance(content, str):
            raise ValueError(f"invalid turn: {raw!r}")
        citations = raw.get("citations") or []
        if not isinstance(citations, list):
            raise ValueError("turn citations are not a list")
        turns.append(
            Turn(
                role=role,
                content=content,
                citations=[c for c in citations if isinstance(c, dict)],
                timestamp=str(raw.get("timestamp", "")),
            )
        )
    raw_sites = data.get("sites") or []
    if not isinstance(raw_sites, list):
        raise TypeError("sites is not a list")
    return Conversation(
        id=str(data.get("id") or _new_id()),
        sites=[str(site) for site in raw_sites],
        turns=turns,
        created_at=str(data.get("created_at") or _now()),
    )

def summarize_conversation(conversation: Conversation) -> str:
    """Plain-text transcript of a conversation, as shown by the CLI."""
    lines = []
    for turn in conversation.turns:
        label = ROLE_LABELS.get(turn.role, turn.role)
        lines.append(f"{label}: {turn.content}")
    return "\n".join(lines)
