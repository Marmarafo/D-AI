"""Layered configuration: defaults < config.toml < environment < overrides."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

from .core.errors import ConfigError
from .paths import config_path, default_db_path


@dataclass(frozen=True)
class Config:
    # network / ingestion
    user_agent: str = "D-AI/1.0 (algorithmic research tool)"
    timeout: float = 15.0
    max_bytes: int = 2_000_000
    max_redirects: int = 5
    retries: int = 1
    max_workers: int = 4
    rate_delay: float = 1.0
    cache_ttl: int = 86400
    respect_robots: bool = True
    allow_private: bool = False
    offline: bool = False
    # research
    max_sources: int = 8
    min_doc_chars: int = 200
    max_claims_per_doc: int = 80
    max_claims: int = 400
    min_relevance: float = 0.34
    max_statements: int = 10
    include_types: tuple = ("fact", "statistic", "forecast", "quote")
    providers: tuple = ("wikipedia",)
    searxng_url: str = ""
    brave_key: str = ""
    default_language: str = "en"
    output_language: str = "auto"
    db_path: str = ""
    # analysis thresholds
    agree_j: float = 0.75
    overlap_j: float = 0.35
    neg_j: float = 0.45
    num_j: float = 0.30
    num_rel_tol: float = 0.001
    cluster_j: float = 0.50
    dup_j: float = 0.50
    # confidence
    conf_prior: float = 0.5
    conf_decay: float = 0.75
    # agent
    agent_rounds: int = 3
    agent_min_independent: int = 3

    def snapshot(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        if d.get("brave_key"):
            d["brave_key"] = "***"
        d["include_types"] = list(d["include_types"])
        d["providers"] = list(d["providers"])
        return d

    def resolved_db_path(self) -> str:
        return self.db_path or str(default_db_path())


def _coerce(name: str, raw, default):
    try:
        if isinstance(default, bool):
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
        if isinstance(default, tuple):
            if isinstance(raw, str):
                return tuple(x.strip() for x in raw.split(",") if x.strip())
            return tuple(raw)
        return str(raw)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"invalid value for {name!r}: {raw!r}") from e


def load_config(overrides: dict | None = None, path: str | Path | None = None) -> Config:
    base = Config()
    names = {f.name for f in fields(base)}
    values: dict = {}

    cfg_file = Path(path) if path else config_path()
    if cfg_file.exists():
        try:
            data = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ConfigError(f"cannot read {cfg_file}: {e}") from e
        data = data.get("dai", data)
        for k, v in data.items():
            if k not in names:
                raise ConfigError(f"unknown config key {k!r} in {cfg_file}")
            values[k] = _coerce(k, v, getattr(base, k))

    for name in names:
        env = os.environ.get("DAI_" + name.upper())
        if env is not None and env != "":
            values[name] = _coerce(name, env, getattr(base, name))
    if not values.get("brave_key") and os.environ.get("BRAVE_API_KEY"):
        values["brave_key"] = os.environ["BRAVE_API_KEY"]

    for k, v in (overrides or {}).items():
        if v is None:
            continue
        if k not in names:
            raise ConfigError(f"unknown config key {k!r}")
        values[k] = _coerce(k, v, getattr(base, k))
    return replace(base, **values)
