from __future__ import annotations

from azure_pipelines_validator import keyring_store


def test_resolve_org_prefers_explicit(monkeypatch) -> None:
    monkeypatch.setenv("AZDO_ORG", "env-org")
    resolved = keyring_store.resolve_org("explicit-org")
    assert resolved == "explicit-org"


def test_resolve_org_from_env(monkeypatch) -> None:
    monkeypatch.setenv("AZDO_ORG", "env-org")
    resolved = keyring_store.resolve_org(None)
    assert resolved == "env-org"


def test_resolve_org_from_git_remote(monkeypatch) -> None:
    monkeypatch.delenv("AZDO_ORG", raising=False)

    class _Remote:
        org = "remote-org"

    class _Context:
        remote = _Remote()

    monkeypatch.setattr(
        keyring_store, "detect_git_context", lambda remote_name="origin": _Context()
    )
    monkeypatch.setattr(keyring_store, "read_default_org", lambda: None)
    resolved = keyring_store.resolve_org(None)
    assert resolved == "remote-org"


def test_read_pat_returns_none_when_backend_missing(monkeypatch) -> None:
    monkeypatch.setattr(keyring_store, "is_keyring_backend_available", lambda: False)
    assert keyring_store.read_pat("acme") is None


def test_clear_default_org_returns_false_without_backend(monkeypatch) -> None:
    monkeypatch.setattr(keyring_store, "is_keyring_backend_available", lambda: False)
    assert keyring_store.clear_default_org() is False
