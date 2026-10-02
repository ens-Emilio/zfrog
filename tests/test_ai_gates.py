"""Tests for the AI readiness gates.

The distinction these cover is the one that produced a bug: ``is_available()`` answers
"is litellm importable", which is true on every install, so gating a call on it alone
reaches a default model nobody started and reports a provider error for a feature the
user did not ask for.
"""

from __future__ import annotations

from zfrog.ai import client


class TestGates:
    def test_is_available_only_checks_the_dependency(self, monkeypatch):
        """It must stay a dependency check — callers that need readiness use can_call."""
        monkeypatch.delenv("ZFROG_AI_MODEL", raising=False)
        assert client.is_available() is True

    def test_model_configured_is_false_by_default(self, monkeypatch):
        monkeypatch.delenv("ZFROG_AI_MODEL", raising=False)
        assert client.model_configured() is False

    def test_model_configured_is_true_when_named(self, monkeypatch):
        monkeypatch.setenv("ZFROG_AI_MODEL", "ollama/qwen2.5")
        assert client.model_configured() is True

    def test_can_call_requires_a_named_model(self, monkeypatch):
        monkeypatch.delenv("ZFROG_AI_MODEL", raising=False)
        assert client.can_call() is False

        monkeypatch.setenv("ZFROG_AI_MODEL", "ollama/qwen2.5")
        assert client.can_call() is True

    def test_can_call_is_false_without_litellm(self, monkeypatch):
        monkeypatch.setenv("ZFROG_AI_MODEL", "ollama/qwen2.5")
        monkeypatch.setattr(client, "is_available", lambda: False)
        assert client.can_call() is False

    def test_embedding_gate_is_separate_from_the_chat_one(self, monkeypatch):
        """A chat model does not imply an embedding model, or the reverse."""
        monkeypatch.setenv("ZFROG_AI_MODEL", "ollama/qwen2.5")
        monkeypatch.delenv("ZFROG_AI_EMBEDDING", raising=False)

        assert client.model_configured() is True
        assert client.embedding_configured() is False

    def test_the_defaults_are_the_documented_ones(self, monkeypatch):
        monkeypatch.delenv("ZFROG_AI_MODEL", raising=False)
        monkeypatch.delenv("ZFROG_AI_EMBEDDING", raising=False)

        assert client.get_model() == "ollama/qwen2.5"
        assert client.get_embedding_model() == "sentence-transformers/all-MiniLM-L6-v2"
