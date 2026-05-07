from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def cloud_api_keys_present() -> bool:
    """True when common hosted LLM credentials are available (LiteLLM-compatible)."""
    return bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("AZURE_API_KEY")
        or os.getenv("LITELLM_PROXY_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
    )


class AIConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # "local" = on-device / LAN inference (default). "cloud" = hosted APIs (opt-in).
    inference: Literal["local", "cloud"] = "local"
    local_model: str = "ollama/llama3"
    cloud_model: str = "gpt-4o-mini"
    embedding_model: str = "all-MiniLM-L6-v2"
    temperature: float = 0.3
    max_tokens: int = 2048
    # Legacy keys from older configs — mapped in validator below.
    primary_model: str | None = None
    fallback_model: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _legacy_primary_fallback(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("primary_model") is not None and data.get("cloud_model") is None:
            data = {**data, "cloud_model": data["primary_model"]}
        if data.get("fallback_model") is not None and data.get("local_model") is None:
            data = {**data, "local_model": data["fallback_model"]}
        return data


def resolved_chat_model(ai: AIConfig) -> tuple[str, Literal["local", "cloud"]]:
    """Return the LiteLLM model id and whether this turn targets cloud APIs."""
    if ai.inference == "cloud":
        return ai.cloud_model, "cloud"
    return ai.local_model, "local"


def llm_inference_enabled(ai: AIConfig) -> bool:
    """Whether we should attempt model-backed routing/synthesis for this config."""
    _model, mode = resolved_chat_model(ai)
    if mode == "local":
        return True
    return cloud_api_keys_present()


class ConnectorEntryConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    permissions: list[str] = Field(default_factory=lambda: ["read"])


class WorkflowEntryConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    schedule: str = ""
    steps: list[Any] = Field(default_factory=list)
    prompt: str | None = None
    output: str = "chat"


class AppConfig(BaseModel):
    general: dict[str, Any] = Field(default_factory=dict)
    ai: AIConfig = Field(default_factory=AIConfig)
    connectors: dict[str, ConnectorEntryConfig] = Field(default_factory=dict)
    workflows: dict[str, WorkflowEntryConfig] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    privacy: dict[str, Any] = Field(default_factory=dict)


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UAI_", env_file=".env", extra="ignore")

    config_path: Path = Path("config.yaml")
    data_dir: Path = Path("./data")
    # Overrides config.yaml ai.inference when set to "local" or "cloud".
    inference: Literal["local", "cloud"] | None = None


DEFAULT_CONFIG_YAML = """# Universal AI Interface — starter config (spec §11)
general:
  interface_mode: chat
  timezone: UTC
  language: en
  notification_level: important

ai:
  # local = default (e.g. Ollama on your machine). cloud = hosted APIs (needs keys).
  inference: local
  local_model: ollama/llama3
  cloud_model: gpt-4o-mini
  embedding_model: all-MiniLM-L6-v2
  temperature: 0.3
  max_tokens: 2048

connectors:
  mock_service:
    enabled: true
    permissions: [read, write]
  # Sandboxed read-only file access (paths must stay under roots).
  filesystem:
    enabled: true
    permissions: [read]
    roots:
      - .
    max_depth: 6
    max_read_bytes: 262144
  # Set enabled: true and export GITHUB_TOKEN (classic PAT or fine-grained with repo scope).
  github:
    enabled: false
    permissions: [read]
  # Set enabled: true and export LINEAR_API_KEY from Linear settings.
  linear:
    enabled: false
    permissions: [read]
  # Off by default — fetches user-supplied HTTPS URLs with SSRF filtering.
  http_fetch:
    enabled: false
    permissions: [read]
    max_bytes: 512000
    allow_http: false
  slack:
    enabled: false
    permissions: [read, write]
  email_imap:
    enabled: false
    permissions: [read]
    # Optional overrides (secrets via IMAP_* env): host, folder, port, fetch_limit
    host: imap.gmail.com
    folder: INBOX
  calendar_ics:
    enabled: false
    permissions: [read]
    urls: []
  calendar_google:
    enabled: false
    permissions: [read]

workflows:
  morning_brief:
    enabled: false
    schedule: "0 8 * * *"
    prompt: >-
      Turn the collected items into a tight bullet brief with next actions.
    steps:
      - search: github issues open
      - connector: linear
        action: list_assigned_issues
        params:
          first: 15
    output: chat

memory:
  vector_db: chromadb
  storage_path: ./data
  auto_index: true
  retention: forever

privacy:
  local_mode: true
  encrypt_data: true
  audit_log: true
  excluded_sources: []
"""


def default_config_path(env: EnvSettings) -> Path:
    return env.config_path.expanduser().resolve()


def load_config(path: Path | None = None, env: EnvSettings | None = None) -> AppConfig:
    env = env or EnvSettings()
    cfg_path = path or default_config_path(env)
    if not cfg_path.exists():
        raw: dict[str, Any] = yaml.safe_load(DEFAULT_CONFIG_YAML) or {}
    else:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(raw)


def write_default_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
