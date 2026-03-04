from __future__ import annotations

from azure_pipelines_validator import auth_chain
from azure_pipelines_validator.auth_chain import TokenKind, TokenSource, resolve_token


def test_resolve_token_prefers_explicit(monkeypatch) -> None:
    monkeypatch.setenv("AZDO_PAT", "env-token")
    resolved = resolve_token(explicit_token="explicit", org_hint="acme")
    assert resolved is not None
    assert resolved.value == "explicit"
    assert resolved.kind == TokenKind.PAT
    assert resolved.source == TokenSource.EXPLICIT


def test_resolve_token_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.setenv("AZDO_PAT", "env-token")
    resolved = resolve_token(explicit_token=None, org_hint="acme")
    assert resolved is not None
    assert resolved.value == "env-token"
    assert resolved.source == TokenSource.ENV


def test_resolve_token_uses_keyring_after_env(monkeypatch) -> None:
    monkeypatch.delenv("AZDO_PAT", raising=False)
    monkeypatch.delenv("SYSTEM_ACCESSTOKEN", raising=False)
    monkeypatch.delenv("PAT", raising=False)
    monkeypatch.setattr(auth_chain, "read_pat", lambda org: "keyring-token")
    resolved = resolve_token(explicit_token=None, org_hint="acme")
    assert resolved is not None
    assert resolved.value == "keyring-token"
    assert resolved.source == TokenSource.KEYCHAIN


def test_resolve_token_uses_azure_cli_last(monkeypatch) -> None:
    monkeypatch.delenv("AZDO_PAT", raising=False)
    monkeypatch.delenv("SYSTEM_ACCESSTOKEN", raising=False)
    monkeypatch.delenv("PAT", raising=False)
    monkeypatch.setattr(auth_chain, "read_pat", lambda org: None)
    monkeypatch.setattr(
        auth_chain,
        "_run_az_account_get_access_token",
        lambda resource: {"accessToken": "bearer-token"},
    )
    resolved = resolve_token(explicit_token=None, org_hint="acme")
    assert resolved is not None
    assert resolved.value == "bearer-token"
    assert resolved.kind == TokenKind.BEARER
    assert resolved.source == TokenSource.AZ_CLI
