from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIConfig(BaseModel):
    primary_model: str = "gpt-4o-mini"
    fallback_model: str = "ollama/llama3"
    embedding_model: str = "all-MiniLM-L6-v2"
    temperature: float = 0.3
    max_tokens: int = 2048


class ConnectorEntryConfig(BaseModel):
    enabled: bool = True
    permissions: list[str] = Field(default_factory=lambda: ["read"])


class WorkflowEntryConfig(BaseModel):
    enabled: bool = False
    schedule: str = ""
    steps: list[str] = Field(default_factory=list)
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


DEFAULT_CONFIG_YAML = """# Universal AI Interface — starter config (spec §11)
general:
  interface_mode: chat
  timezone: UTC
  language: en
  notification_level: important

ai:
  primary_model: gpt-4o-mini
  fallback_model: ollama/llama3
  embedding_model: all-MiniLM-L6-v2
  temperature: 0.3
  max_tokens: 2048

connectors:
  mock_service:
    enabled: true
    permissions: [read, write]

workflows:
  morning_brief:
    enabled: false
    schedule: "0 8 * * *"
    steps: [calendar, tasks, emails, slack, github]
    output: chat

memory:
  vector_db: chromadb
  storage_path: ./data
  auto_index: true
  retention: forever

privacy:
  local_mode: false
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
