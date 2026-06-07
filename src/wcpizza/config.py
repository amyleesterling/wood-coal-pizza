"""Configuration loading.

The pipeline is driven entirely by ``config.yaml`` so that a run is fully
described by (code version + config + cached source snapshots). We expose a
tiny dot-accessible wrapper rather than scattering dictionary lookups through
the codebase.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"


class Section(dict):
    """A dict that also supports attribute access (cfg.osm.endpoint)."""

    def __getattr__(self, name: str) -> Any:
        try:
            value = self[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc
        return Section(value) if isinstance(value, dict) else value


@dataclass
class Config:
    data: Dict[str, Any]
    path: Path

    def __getattr__(self, name: str) -> Any:
        try:
            value = self.data[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(name) from exc
        return Section(value) if isinstance(value, dict) else value

    def census_api_key(self) -> str | None:
        """Return the Census API key from the env var named in config, if set."""
        env_name = self.data.get("census", {}).get("api_key_env", "CENSUS_API_KEY")
        key = os.environ.get(env_name)
        return key or None


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load YAML config from ``path`` (default: repo-root config.yaml)."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(p, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Config(data=data, path=p)
