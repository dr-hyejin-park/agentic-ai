"""Runtime configuration loaded from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() in {"1", "true", "True", "yes", "on"}


@dataclass
class Settings:
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "").strip())
    agent_model: str = field(default_factory=lambda: os.getenv("AGENT_MODEL", "claude-opus-4-8").strip())
    monitor_interval: float = field(default_factory=lambda: float(os.getenv("MONITOR_INTERVAL", "2.0")))
    require_approval: bool = field(default_factory=lambda: _flag("REQUIRE_APPROVAL"))

    # Size of the rolling time-series window kept per metric.
    history_window: int = 600

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
