"""Environment-backed TraceAid configuration without import-time side effects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _read_bool(value: str | bool, *, name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalised = value.strip().lower()
    if normalised in _TRUE_VALUES:
        return True
    if normalised in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be one of true/false, 1/0, yes/no, or on/off")


class Settings(BaseModel):
    """Runtime settings read from the documented environment variables."""

    model_config = ConfigDict(extra="forbid")

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    enable_live_probes: bool = False
    request_timeout_seconds: float = Field(default=8.0, gt=0, le=30)
    max_response_bytes: int = Field(default=262_144, ge=1024, le=2_097_152)
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8000"])
    log_level: str = "INFO"
    user_agent: str = "TraceAid-AI/1.0"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        return level

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        if environ is None:
            # Resolve .env lazily so importing this module never mutates or
            # snapshots process configuration. Real environment values win.
            try:
                from dotenv import dotenv_values, find_dotenv
            except ImportError:  # pragma: no cover - dependency is optional at runtime
                env: Mapping[str, str] = os.environ
            else:
                dotenv_path = find_dotenv(usecwd=True)
                file_values = {
                    key: value
                    for key, value in (dotenv_values(dotenv_path).items() if dotenv_path else [])
                    if value is not None
                }
                env = {**file_values, **os.environ}
        else:
            # Explicit mappings are deterministic and intentionally ignore .env.
            env = environ
        values: dict[str, object] = {}

        if key := env.get("OPENAI_API_KEY"):
            values["openai_api_key"] = key
        if model := env.get("OPENAI_MODEL"):
            values["openai_model"] = model
        if raw := env.get("TRACEAID_ENABLE_LIVE_PROBES"):
            values["enable_live_probes"] = _read_bool(raw, name="TRACEAID_ENABLE_LIVE_PROBES")
        if raw := env.get("TRACEAID_REQUEST_TIMEOUT_SECONDS"):
            values["request_timeout_seconds"] = float(raw)
        if raw := env.get("TRACEAID_MAX_RESPONSE_BYTES"):
            values["max_response_bytes"] = int(raw)
        if raw := env.get("TRACEAID_ALLOWED_ORIGINS"):
            values["allowed_origins"] = raw
        if raw := env.get("TRACEAID_LOG_LEVEL"):
            values["log_level"] = raw

        return cls.model_validate(values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached immutable-by-convention settings snapshot."""

    return Settings.from_env()


__all__ = ["Settings", "get_settings"]
