"""Tests for CLI config management."""

import os
import tempfile
import pytest


def test_load_config_reads_toml():
    from app.cli_config import load_config, save_config

    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w") as f:
        f.write('[llm]\nbase_url = "http://localhost:8080"\nmodel = "test-model"\n\n[whisper]\nmodel = "tiny"\n')
        path = f.name
    try:
        config = load_config(path)
        assert config["llm"]["base_url"] == "http://localhost:8080"
        assert config["llm"]["model"] == "test-model"
        assert config["whisper"]["model"] == "tiny"
    finally:
        os.unlink(path)


def test_save_config_writes_toml():
    from app.cli_config import load_config, save_config

    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        path = f.name
    try:
        save_config(path, {
            "llm": {"base_url": "http://localhost:8080", "model": "test-model"},
            "whisper": {"model": "tiny"},
        })
        config = load_config(path)
        assert config["llm"]["base_url"] == "http://localhost:8080"
        assert config["llm"]["model"] == "test-model"
        assert config["whisper"]["model"] == "tiny"
    finally:
        os.unlink(path)


def test_resolve_config_cli_flags_win():
    from app.cli_config import resolve_config

    resolved = resolve_config(
        cli_llm_url="http://cli:8080",
        cli_llm_model="cli-model",
        cli_whisper_model="large-v3",
        config_path="/nonexistent",
    )
    assert resolved["llm_url"] == "http://cli:8080"
    assert resolved["llm_model"] == "cli-model"
    assert resolved["whisper_model"] == "large-v3"


def test_resolve_config_env_vars_second(monkeypatch):
    from app.cli_config import resolve_config

    monkeypatch.setenv("CLIPFORGE_LLM_URL", "http://env:8080")
    monkeypatch.setenv("CLIPFORGE_LLM_MODEL", "env-model")
    monkeypatch.setenv("CLIPFORGE_WHISPER_MODEL", "small")
    resolved = resolve_config(config_path="/nonexistent")
    assert resolved["llm_url"] == "http://env:8080"
    assert resolved["llm_model"] == "env-model"
    assert resolved["whisper_model"] == "small"


def test_resolve_config_file_third():
    from app.cli_config import resolve_config

    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False, mode="w") as f:
        f.write('[llm]\nbase_url = "http://file:8080"\nmodel = "file-model"\n\n[whisper]\nmodel = "medium"\n')
        path = f.name
    try:
        resolved = resolve_config(config_path=path)
        assert resolved["llm_url"] == "http://file:8080"
        assert resolved["llm_model"] == "file-model"
        assert resolved["whisper_model"] == "medium"
    finally:
        os.unlink(path)
