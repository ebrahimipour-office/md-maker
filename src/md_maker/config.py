"""Settings: the packaged defaults (data/config.toml), overlaid by TOML files
and command-line flags. Access is by attribute: `settings.ai.models.repair`.
"""

import os
import sys
import tomllib
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

AI_MODES = ("smart", "max", "off")


class ConfigError(ValueError):
    pass


def template() -> str:
    """The commented default settings file."""
    return (files("md_maker") / "data" / "config.toml").read_text(encoding="utf-8")


def _user_dir(kind: str) -> Path:
    """Per-user folder for "config" or "cache" data."""
    if sys.platform == "win32":
        var, fallback = {"config": ("APPDATA", "Roaming"), "cache": ("LOCALAPPDATA", "Local")}[kind]
        base = Path(os.environ.get(var, Path.home() / "AppData" / fallback))
        return base / "md-maker" / ("cache" if kind == "cache" else "")
    var, fallback = {"config": ("XDG_CONFIG_HOME", ".config"), "cache": ("XDG_CACHE_HOME", ".cache")}[kind]
    return Path(os.environ.get(var, Path.home() / fallback)) / "md-maker"


def user_config() -> Path:
    return _user_dir("config") / "config.toml"


def cache_dir(settings) -> Path:
    return Path(settings.cache.dir) if settings.cache.dir else _user_dir("cache")


def sources(explicit: Path | None = None) -> list[Path]:
    """Settings files that exist, lowest priority first."""
    explicit = explicit or (Path(p) if (p := os.environ.get("MD_MAKER_CONFIG")) else None)
    if explicit and not explicit.is_file():
        raise ConfigError(f"config file not found: {explicit}")
    found = [p for p in (user_config(), Path.cwd() / "md-maker.toml") if p.is_file()]
    return found + ([explicit] if explicit else [])


def _merge(base: dict, new: dict, where: str, path: str = ""):
    """Overlay new onto base, rejecting unknown keys and wrong types."""
    for key, value in new.items():
        name = f"{path}{key}"
        if key not in base:
            raise ConfigError(f"{where}: unknown setting `{name}`")
        default = base[key]
        if isinstance(default, dict):
            if not isinstance(value, dict):
                raise ConfigError(f"{where}: `{name}` must be a table")
            _merge(default, value, where, name + ".")
            continue
        ok = isinstance(value, type(default)) or (isinstance(default, float) and type(value) is int)
        if not ok or (type(default) is int and isinstance(value, bool)):
            raise ConfigError(f"{where}: `{name}` must be {type(default).__name__}, got {value!r}")
        base[key] = float(value) if isinstance(default, float) else value


def _validate(data: dict):
    if data["ai"]["mode"] not in AI_MODES:
        raise ConfigError(f"ai.mode must be one of {', '.join(AI_MODES)}")
    if data["ai"]["backend"] != "claude-cli":
        raise ConfigError("ai.backend: only `claude-cli` is supported")
    if data["pdf"]["engine"] not in ("auto", "rtl", "layout"):
        raise ConfigError("pdf.engine must be auto, rtl or layout")
    if data["ocr"]["mode"] not in ("auto", "always", "never"):
        raise ConfigError("ocr.mode must be auto, always or never")
    if data["ai"]["concurrency"] < 1:
        raise ConfigError("ai.concurrency must be at least 1")


def _ns(d: dict):
    return SimpleNamespace(**{k: _ns(v) if isinstance(v, dict) else v for k, v in d.items()})


def as_dict(settings) -> dict:
    return {k: as_dict(v) if isinstance(v, SimpleNamespace) else v for k, v in vars(settings).items()}


def load(explicit: Path | None = None, overrides: dict | None = None):
    """Defaults <- settings files <- $MD_MAKER_AI <- overrides (e.g. CLI flags)."""
    data = tomllib.loads(template())
    for path in sources(explicit):
        try:
            new = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from None
        _merge(data, new, str(path))
    if mode := os.environ.get("MD_MAKER_AI"):
        _merge(data, {"ai": {"mode": mode}}, "$MD_MAKER_AI")
    if overrides:
        _merge(data, overrides, "command line")
    _validate(data)
    return _ns(data)
