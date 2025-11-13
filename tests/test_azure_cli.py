from __future__ import annotations

from types import SimpleNamespace

from azure_pipelines_validator import azure_cli


def test_discover_pat_prefers_env(monkeypatch) -> None:
    env = {azure_cli.DEVOPS_PAT_ENV: "inline"}
    assert azure_cli.discover_pat("https://dev.azure.com/example", env=env) == "inline"


def test_discover_pat_reads_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(azure_cli, "keyring", None)
    env = {"AZURE_DEVOPS_EXT_CONFIG_DIR": str(tmp_path)}
    (tmp_path / "personalAccessTokens").write_text(
        "[azdevops-cli: https://dev.azure.com/example]\nPersonal Access Token = from-file\n",
        encoding="utf-8",
    )

    token = azure_cli.discover_pat("https://dev.azure.com/example", env=env)

    assert token == "from-file"


def test_discover_pat_falls_back_to_default_key(monkeypatch, tmp_path) -> None:
    dummy_keyring = SimpleNamespace(get_password=lambda key, username: None)
    monkeypatch.setattr(azure_cli, "keyring", dummy_keyring)
    env = {"AZURE_DEVOPS_EXT_CONFIG_DIR": str(tmp_path)}
    (tmp_path / "personalAccessTokens").write_text(
        "[azdevops-cli: default]\nPersonal Access Token = fallback\n",
        encoding="utf-8",
    )

    token = azure_cli.discover_pat("https://dev.azure.com/unknown", env=env)

    assert token == "fallback"


def test_discover_defaults_reads_config(tmp_path) -> None:
    env = {"AZURE_DEVOPS_EXT_CONFIG_DIR": str(tmp_path)}
    (tmp_path / "config").write_text(
        "[defaults]\norganization = https://dev.azure.com/acme\nproject = demo\n",
        encoding="utf-8",
    )

    defaults = azure_cli.discover_defaults(env=env)

    assert defaults.organization == "https://dev.azure.com/acme"
    assert defaults.project == "demo"
