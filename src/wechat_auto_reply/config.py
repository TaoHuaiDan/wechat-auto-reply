from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when the YAML configuration is missing or invalid."""


@dataclass(frozen=True)
class AppConfig:
    name: str


@dataclass(frozen=True)
class BridgeConfig:
    url: str
    poll_timeout_seconds: float
    poll_limit: int
    request_timeout_seconds: float
    retry_delay_seconds: float


@dataclass(frozen=True)
class DatabaseConfig:
    path: Path


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    file_path: Path
    max_bytes: int
    backup_count: int


@dataclass(frozen=True)
class ContextConfig:
    recent_message_limit: int


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool
    base_url: str
    model: str
    timeout_seconds: float


@dataclass(frozen=True)
class Config:
    app: AppConfig
    bridge: BridgeConfig
    database: DatabaseConfig
    logging: LoggingConfig
    context: ContextConfig
    llm: LLMConfig
    path: Path


def load_config(path: str | Path) -> Config:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigError(f"configuration file does not exist: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"unable to read configuration: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML configuration: {config_path}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a mapping")

    app = _mapping(raw, "app")
    bridge = _mapping(raw, "bridge")
    database = _mapping(raw, "database")
    logging_config = _mapping(raw, "logging")
    context = _mapping(raw, "context")
    llm = _mapping(raw, "llm")

    base_dir = config_path.parent
    return Config(
        app=AppConfig(name=_required_str(app, "name")),
        bridge=BridgeConfig(
            url=_required_str(bridge, "url").rstrip("/"),
            poll_timeout_seconds=_positive_float(bridge, "poll_timeout_seconds"),
            poll_limit=_positive_int(bridge, "poll_limit"),
            request_timeout_seconds=_positive_float(bridge, "request_timeout_seconds"),
            retry_delay_seconds=_positive_float(bridge, "retry_delay_seconds"),
        ),
        database=DatabaseConfig(
            path=_resolve_path(base_dir, _required_str(database, "path")),
        ),
        logging=LoggingConfig(
            level=_required_str(logging_config, "level").upper(),
            file_path=_resolve_path(base_dir, _required_str(logging_config, "file_path")),
            max_bytes=_positive_int(logging_config, "max_bytes"),
            backup_count=_non_negative_int(logging_config, "backup_count"),
        ),
        context=ContextConfig(
            recent_message_limit=_positive_int(context, "recent_message_limit"),
        ),
        llm=LLMConfig(
            enabled=_bool(llm, "enabled"),
            base_url=_required_str(llm, "base_url").rstrip("/"),
            model=_required_str(llm, "model"),
            timeout_seconds=_positive_float(llm, "timeout_seconds"),
        ),
        path=config_path,
    )


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{key!r} must be a mapping")
    return value


def _required_str(parent: dict[str, Any], key: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key!r} must be a non-empty string")
    return value.strip()


def _positive_float(parent: dict[str, Any], key: str) -> float:
    value = parent.get(key)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key!r} must be a positive number") from exc
    if result <= 0:
        raise ConfigError(f"{key!r} must be greater than zero")
    return result


def _positive_int(parent: dict[str, Any], key: str) -> int:
    value = parent.get(key)
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key!r} must be a positive integer") from exc
    if result <= 0:
        raise ConfigError(f"{key!r} must be greater than zero")
    return result


def _non_negative_int(parent: dict[str, Any], key: str) -> int:
    value = parent.get(key)
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key!r} must be a non-negative integer") from exc
    if result < 0:
        raise ConfigError(f"{key!r} must not be negative")
    return result


def _bool(parent: dict[str, Any], key: str) -> bool:
    value = parent.get(key)
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{key!r} must be true or false")


def _resolve_path(base_dir: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()
