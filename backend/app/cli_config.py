"""ClipForge CLI configuration management."""

import os
from pathlib import Path

import tomli
import tomli_w

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.expanduser("~"), ".config", "clipforge", "config.toml"
)


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load config from TOML file. Returns empty dict if file doesn't exist."""
    if not os.path.isfile(path):
        return {}
    with open(path, "rb") as f:
        return tomli.load(f)


def save_config(path: str, config: dict) -> None:
    """Save config to TOML file, creating parent directories if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(config, f)


def resolve_config(
    cli_llm_url: str | None = None,
    cli_llm_model: str | None = None,
    cli_whisper_model: str | None = None,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> dict:
    """Resolve config with priority: CLI flags > env vars > config file > defaults."""
    file_config = load_config(config_path)

    llm_url = (
        cli_llm_url
        or os.environ.get("CLIPFORGE_LLM_URL")
        or file_config.get("llm", {}).get("base_url")
    )
    llm_model = (
        cli_llm_model
        or os.environ.get("CLIPFORGE_LLM_MODEL")
        or file_config.get("llm", {}).get("model")
    )
    whisper_model = (
        cli_whisper_model
        or os.environ.get("CLIPFORGE_WHISPER_MODEL")
        or file_config.get("whisper", {}).get("model")
        or "base"
    )

    return {
        "llm_url": llm_url,
        "llm_model": llm_model,
        "whisper_model": whisper_model,
    }


def interactive_setup(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Prompt user for config values and save to file."""
    from rich.console import Console
    from rich.prompt import Prompt

    console = Console()
    console.print("\n[bold]ClipForge Setup[/bold]\n")

    llm_url = Prompt.ask("LLM endpoint URL", default="http://localhost:8080")
    llm_model = Prompt.ask("LLM model name", default="qwen3.5-9b")
    whisper_model = Prompt.ask(
        "Whisper model",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        default="base",
    )

    config = {
        "llm": {"base_url": llm_url, "model": llm_model},
        "whisper": {"model": whisper_model},
    }
    save_config(config_path, config)
    console.print(f"\n[green]Config saved to {config_path}[/green]")

    return {
        "llm_url": llm_url,
        "llm_model": llm_model,
        "whisper_model": whisper_model,
    }
