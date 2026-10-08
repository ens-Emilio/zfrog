"""Tests for the multi-turn chat layer over the multi-site index."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from zfrog.ai import chat as chat_module
from zfrog.ai import multisite
from zfrog.ai.chat import ChatSession, Conversation, Turn, summarize_conversation
from zfrog.ai.multisite import MultiSiteIndex
from zfrog.config import settings

SITE_URL = "https://quantum.test"

QUANTUM_TEXT = (
    "Quantum entanglement links particles across a distance, and the superconductor "
    "lattice experiment measured the correlation at very low temperature. The "
    "entanglement correlation survived for microseconds inside the cryostat."
)

def _page(title: str, body: str) -> str:
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{title}</title></head><body><h1>{title}</h1><p>{body}</p></body></html>"
    )

def _write_site(root: Path, name: str, pages: dict[str, str]) -> Path:
    """Create a fake cloned site directory with the given relative pages."""
    site = root / name
    for rel, html in pages.items():
        target = site / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    return site

def _flatten(messages: list[dict[str, str]]) -> str:
    return "\n".join(message["content"] for message in messages)

@pytest.fixture
def index(tmp_path, monkeypatch):
    """Index whose retrieval is lexical, so no embedding provider is needed."""
    monkeypatch.setattr(multisite, "is_available", lambda: False)
    monkeypatch.setattr(settings, "output_dir", tmp_path / "output")
    return MultiSiteIndex()

def _session(tmp_path: Path, index: MultiSiteIndex, **kwargs) -> ChatSession:
    return ChatSession(index=index, history_dir=tmp_path / "chats", **kwargs)

@pytest.fixture
def session(tmp_path, index):
    """A chat session over one cloned site with a single page."""
    session = _session(tmp_path, index)
    site = _write_site(tmp_path, "quantum", {"index.html": _page("Quantum", QUANTUM_TEXT)})
    session.add_site(SITE_URL, site)
    return session

@pytest.fixture
def ai(monkeypatch):
    """AI layer on, recording every prompt handed to `complete`."""
    prompts: list[list[dict[str, str]]] = []
    answers: list[str] = []

    async def fake_complete(messages, **kwargs):
        prompts.append(messages)
        if answers:
            return answers[min(len(prompts) - 1, len(answers) - 1)]
        return "Resposta do modelo."

    monkeypatch.setattr(chat_module, "is_available", lambda: True)
    monkeypatch.setattr(chat_module, "complete", fake_complete)
    return SimpleNamespace(prompts=prompts, answers=answers)

@pytest.fixture
def ai_off(monkeypatch):
    """AI layer off: any completion attempt is a test failure."""

    async def explode(*args, **kwargs):
        raise AssertionError("no AI call expected")

    monkeypatch.setattr(chat_module, "is_available", lambda: False)
    monkeypatch.setattr(chat_module, "complete", explode)
    return explode

async def test_ask_on_empty_index_explains_without_ai(tmp_path, index, monkeypatch):
    """Nothing indexed: a Portuguese answer, no model call, no citations."""
    monkeypatch.setattr(chat_module, "is_available", lambda: True)

    async def explode(*args, **kwargs):
        raise AssertionError("no AI call expected on an empty index")

    monkeypatch.setattr(chat_module, "complete", explode)
    session = _session(tmp_path, index)

    result = await session.ask("o que diz o site?")

    assert "No indexed content yet" in result["answer"]
    assert result["citations"] == []
    assert result["turn"] == 1
    assert [turn.role for turn in session.history()] == ["user", "assistant"]

async def test_ask_without_ai_returns_citations(session, ai_off):
    """The AI being down still yields an answer plus the retrieved sources."""
    result = await session.ask("quantum entanglement superconductor")

    assert result["answer"]
    assert "AI unavailable" in result["answer"]
    assert result["citations"], "retrieved chunks are the citations"
    citation = result["citations"][0]
    assert citation["site"] == SITE_URL
    assert citation["url"].startswith(SITE_URL)
    assert citation["path"] == "index.html"
    assert "entanglement" in citation["snippet"]
    assert citation["score"] > 0
    assert session.history()[-1].content == result["answer"]

async def test_ask_uses_model_answer_and_appends_turn(session, ai):
    """The model answer is the answer, and it becomes an assistant turn."""
    ai.answers.append("A correlação sobreviveu microssegundos no criostato.")

    result = await session.ask("quantum entanglement superconductor")

    assert result["answer"] == "A correlação sobreviveu microssegundos no criostato."
    assert len(ai.prompts) == 1
    prompt = _flatten(ai.prompts[0])
    assert "quantum entanglement superconductor" in prompt
    assert "entanglement correlation survived" in prompt, "the retrieved chunk is the context"
    turns = session.history()
    assert [turn.role for turn in turns] == ["user", "assistant"]
    assert turns[1].content == result["answer"]
    assert turns[1].citations == result["citations"]
    assert turns[1].timestamp
    assert result["turn"] == len(turns) - 1

async def test_follow_up_prompt_carries_previous_turn(session, ai):
    """A follow-up question reaches the model together with the earlier exchange."""
    ai.answers.extend(["Primeira resposta sobre entrelaçamento.", "Segunda resposta."])

    await session.ask("o que o experimento mediu?")
    await session.ask("e o segundo?")

    prompt = _flatten(ai.prompts[1])
    assert "o que o experimento mediu?" in prompt, "the earlier question is replayed"
    assert "Primeira resposta sobre entrelaçamento." in prompt, "the earlier answer is replayed"
    assert "e o segundo?" in prompt

async def test_history_is_capped_at_max_turns(tmp_path, index, ai):
    """Only the last `max_turns` turns are replayed to the model."""
    ai.answers.extend(["Resposta A", "Resposta B", "Resposta C"])
    session = _session(tmp_path, index, max_turns=2)
    site = _write_site(tmp_path, "quantum", {"index.html": _page("Quantum", QUANTUM_TEXT)})
    session.add_site(SITE_URL, site)

    await session.ask("primeira pergunta")
    await session.ask("segunda pergunta")
    await session.ask("terceira pergunta")

    prompt = _flatten(ai.prompts[2])
    assert len(ai.prompts[2]) == 4, "system + two replayed turns + the new question"
    assert "segunda pergunta" in prompt
    assert "Resposta B" in prompt
    assert "primeira pergunta" not in prompt, "older turns are dropped from the prompt"
    assert "Resposta A" not in prompt
    assert len(session.history()) == 6, "the stored history itself is not truncated"

async def test_save_and_load_round_trip(session, ai):
    """Turns, citations and sites survive a save/load cycle; the file is private."""
    ai.answers.append("Resposta persistida.")
    await session.ask("quantum entanglement superconductor")
    conversation_id = session.conversation.id

    path = session.save()

    assert path == session.history_dir / f"{conversation_id}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    leftovers = list(session.history_dir.glob("*.tmp"))
    assert leftovers == [], "the temp file is replaced, not left behind"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["id"] == conversation_id
    assert stored["sites"] == [SITE_URL]
    assert [turn["role"] for turn in stored["turns"]] == ["user", "assistant"]

    reopened = ChatSession(index=session.index, history_dir=session.history_dir)
    loaded = reopened.load(conversation_id)

    assert isinstance(loaded, Conversation)
    assert loaded.id == conversation_id
    assert loaded.sites == [SITE_URL]
    assert [turn.content for turn in loaded.turns] == [
        turn.content for turn in session.history()
    ]
    assert loaded.turns[1].citations == session.history()[1].citations
    assert loaded.turns[1].citations
    assert loaded.created_at == session.conversation.created_at

    transcript = summarize_conversation(loaded)
    assert transcript.splitlines()[0] == "User: quantum entanglement superconductor"
    assert transcript.splitlines()[1] == "Assistant: Resposta persistida."

async def test_load_tolerates_corrupt_file(session, ai):
    """A damaged conversation file warns and yields None instead of raising."""
    await session.ask("quantum entanglement superconductor")
    conversation_id = session.conversation.id
    path = session.save()
    path.write_text("{ isto não é json", encoding="utf-8")

    assert session.load(conversation_id) is None

    path.write_text(json.dumps({"turns": [{"role": "system", "content": "x"}]}), encoding="utf-8")

    assert session.load(conversation_id) is None

def test_load_rejects_unknown_and_escaping_ids(session):
    """Unknown ids and ids that try to leave the history directory are refused."""
    assert session.load("nao-existe") is None
    assert session.load("../../etc/passwd") is None
    assert session.load("") is None

async def test_reset_clears_turns_but_keeps_sites(session, ai):
    """Reset empties the conversation without touching the indexed sites."""
    await session.ask("quantum entanglement superconductor")

    session.reset()

    assert session.history() == []
    assert [site["url"] for site in session.sites()] == [SITE_URL]
    assert session.index.chunks, "the index itself is untouched"

async def test_sessions_do_not_share_history(tmp_path, index, ai):
    """Two conversations with different ids keep separate histories on disk."""
    ai.answers.extend(["Resposta da primeira.", "Resposta da segunda."])
    site = _write_site(tmp_path, "quantum", {"index.html": _page("Quantum", QUANTUM_TEXT)})
    first = _session(tmp_path, index)
    second = _session(tmp_path, index)
    first.add_site(SITE_URL, site)
    second.add_site(SITE_URL, site)

    await first.ask("primeira conversa")
    await second.ask("segunda conversa")

    assert first.conversation.id != second.conversation.id
    first_path = first.save()
    second_path = second.save()
    assert first_path != second_path

    reader = _session(tmp_path, index)
    assert [t.content for t in reader.load(first.conversation.id).turns] == [
        "primeira conversa",
        "Resposta da primeira.",
    ]
    assert [t.content for t in reader.load(second.conversation.id).turns] == [
        "segunda conversa",
        "Resposta da segunda.",
    ]

def test_turn_and_conversation_defaults():
    """Fresh dataclasses carry their own id and timestamp."""
    first = Conversation()
    second = Conversation()

    assert first.id != second.id
    assert first.turns == [] and first.sites == []
    assert first.created_at
    assert Turn(role="user", content="oi").timestamp
