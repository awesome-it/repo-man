"""Load configuration from environment and optional config file."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Env vars
ENV_REPO_ROOT = "REPO_MIRROR_REPO_ROOT"
ENV_CONFIG_PATH = "REPO_MIRROR_CONFIG"
ENV_CACHE_VERSIONS_PER_PACKAGE = "CACHE_VERSIONS_PER_PACKAGE"
ENV_METADATA_TTL_SECONDS = "REPO_MIRROR_METADATA_TTL_SECONDS"
ENV_DISK_HIGH_WATERMARK_BYTES = "REPO_MIRROR_DISK_HIGH_WATERMARK_BYTES"
ENV_PACKAGE_HASH_STORE = "REPO_MIRROR_PACKAGE_HASH_STORE"
ENV_REDIS_URL = "REPO_MIRROR_REDIS_URL"
ENV_NO_DEFAULT_UPSTREAMS = "REPO_MIRROR_NO_DEFAULT_UPSTREAMS"
ENV_ENABLE_API = "REPO_MIRROR_ENABLE_API"

DEFAULT_CACHE_VERSIONS_PER_PACKAGE = 3
DEFAULT_PACKAGE_HASH_STORE = "local"
DEFAULT_METADATA_TTL_SECONDS = 1800  # 30 minutes
DEFAULT_DISK_HIGH_WATERMARK_BYTES = 10 * 1024**3  # 10 GiB
DEFAULT_SERVE_BIND = "0.0.0.0"
DEFAULT_SERVE_PORT = 8080


def get_repo_root(override: str | Path | None = None) -> Path:
    """Return repo root directory (for storage)."""
    if override is not None:
        return Path(override)
    value = os.environ.get(ENV_REPO_ROOT)
    if value:
        return Path(value)
    return Path.cwd() / "repo_data"


def get_config_path(override: str | Path | None = None) -> Path | None:
    """Return path to config file if set."""
    if override is not None:
        return Path(override)
    value = os.environ.get(ENV_CONFIG_PATH)
    if value:
        return Path(value)
    return None


def get_cache_versions_per_package() -> int:
    """Return how many versions of each package to keep (latest N)."""
    value = os.environ.get(ENV_CACHE_VERSIONS_PER_PACKAGE)
    if value is None:
        return DEFAULT_CACHE_VERSIONS_PER_PACKAGE
    try:
        n = int(value)
        return max(1, n)
    except ValueError:
        return DEFAULT_CACHE_VERSIONS_PER_PACKAGE


def get_disk_high_watermark_bytes(config_path: Path | None = None) -> int | None:
    """Return repo disk high watermark in bytes; when exceeded, cache (not published) may be pruned. None = disabled."""
    value = os.environ.get(ENV_DISK_HIGH_WATERMARK_BYTES)
    if value is not None and value.strip() != "":
        s = value.strip().lower()
        if s in ("0", "off", "none", "disabled"):
            return None
        try:
            return max(0, int(value))
        except ValueError:
            pass
    if config_path and config_path.exists():
        data = load_config_file(config_path)
        disk = data.get("disk")
        if isinstance(disk, dict) and "high_watermark_bytes" in disk:
            v = disk["high_watermark_bytes"]
            if v is None:
                return None
            try:
                return max(0, int(v))
            except (ValueError, TypeError):
                pass
    return DEFAULT_DISK_HIGH_WATERMARK_BYTES


def get_metadata_ttl_seconds(config_path: Path | None = None) -> int:
    """Return metadata cache TTL in seconds; cached metadata is re-fetched when older than this. Default 30 minutes."""
    value = os.environ.get(ENV_METADATA_TTL_SECONDS)
    if value is not None and value.strip() != "":
        try:
            return max(0, int(value))
        except ValueError:
            pass
    if config_path and config_path.exists():
        data = load_config_file(config_path)
        v = data.get("metadata_ttl_seconds")
        if v is not None:
            try:
                return max(0, int(v))
            except (ValueError, TypeError):
                pass
    return DEFAULT_METADATA_TTL_SECONDS


def get_package_hash_store_type(config_path: Path | None = None) -> str:
    """Return 'redis' or 'local' for package hash storage. Default 'local'."""
    value = os.environ.get(ENV_PACKAGE_HASH_STORE)
    if value is not None and value.strip():
        v = value.strip().lower()
        if v in ("redis", "local"):
            return v
    if config_path and config_path.exists():
        data = load_config_file(config_path)
        v = data.get("package_hash_store")
        if v is not None:
            s = str(v).strip().lower()
            if s in ("redis", "local"):
                return s
    return DEFAULT_PACKAGE_HASH_STORE


def get_enable_api(config_path: Path | None = None) -> bool:
    """Return True if the publish API should be enabled. Default False (API off by default)."""
    value = os.environ.get(ENV_ENABLE_API)
    if value is not None and str(value).strip().lower() in ("1", "true", "yes", "on"):
        return True
    if config_path and config_path.exists():
        data = load_config_file(config_path)
        api = data.get("api")
        if isinstance(api, dict) and api.get("enable") is True:
            return True
    return False


def get_redis_url(config_path: Path | None = None) -> str:
    """Return Redis URL for package hash store when type is redis. Default redis://localhost:6379/0."""
    value = os.environ.get(ENV_REDIS_URL)
    if value is not None and value.strip():
        return value.strip()
    if config_path and config_path.exists():
        data = load_config_file(config_path)
        u = data.get("redis_url")
        if u is not None and str(u).strip():
            return str(u).strip()
    return "redis://localhost:6379/0"


def load_config_file(path: Path) -> dict[str, Any]:
    """Load YAML or TOML config file; return dict. Empty dict if file missing or invalid."""
    if not path.exists():
        return {}
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
            with open(path) as f:
                data = yaml.safe_load(f)
            result = data or {}
            logger.debug("Loaded config from %s", path)
            return result
        except Exception as e:
            logger.warning("Could not load config: path=%s error=%s", path, e)
            return {}
    if suffix == ".toml":
        try:
            import tomllib
            with open(path, "rb") as f:
                result = tomllib.load(f) or {}
            logger.debug("Loaded config from %s", path)
            return result
        except Exception as e:
            logger.warning("Could not load config: path=%s error=%s", path, e)
            return {}
    return {}


def get_upstreams_from_config(config_path: Path | None) -> list[dict[str, Any]]:
    """Return list of upstream config dicts from config file."""
    if config_path is None:
        return []
    data = load_config_file(config_path)
    upstreams = data.get("upstreams") or data.get("upstream") or []
    if isinstance(upstreams, list):
        return upstreams
    return []


def get_default_upstreams() -> list[dict[str, Any]]:
    """Return sane default upstreams when no config is provided (Ubuntu, Debian, Rocky 9, Alpine)."""
    return [
        {
            "name": "ubuntu",
            "url": "http://archive.ubuntu.com/ubuntu/",
            "base_url": "http://archive.ubuntu.com/ubuntu/",
            "format": "apt",
            "layout": "classic",
            "path_prefix": "/ubuntu",
            "suites": ["jammy", "noble", "noble-updates", "noble-security"],
            "components": ["main"],
            "archs": ["amd64"],
        },
        {
            "name": "debian",
            "url": "https://deb.debian.org/debian/",
            "base_url": "https://deb.debian.org/debian/",
            "format": "apt",
            "layout": "classic",
            "path_prefix": "/debian",
            "suites": ["bookworm", "bookworm-updates"],
            "components": ["main"],
            "archs": ["amd64"],
        },
        {
            "name": "rocky9",
            "url": "https://dl.rockylinux.org/pub/rocky/9/BaseOS/x86_64/os/",
            "base_url": "https://dl.rockylinux.org/pub/rocky/9/BaseOS/x86_64/os/",
            "format": "rpm",
            "path_prefix": "/rocky9",
        },
        {
            "name": "alpine",
            "url": "https://dl-cdn.alpinelinux.org/alpine/v3.19/main",
            "base_url": "https://dl-cdn.alpinelinux.org/alpine/v3.19/main",
            "format": "alpine",
            "path_prefix": "/alpine",
        },
    ]


def get_disable_default_upstreams(
    config_path: Path | None,
    flag_override: bool | None = None,
) -> bool:
    """True if default upstreams should be disabled (config key, env var, or --no-default-upstreams)."""
    if flag_override is True:
        return True
    value = os.environ.get(ENV_NO_DEFAULT_UPSTREAMS)
    if value is not None and str(value).strip().lower() in ("1", "true", "yes", "on"):
        return True
    if config_path and config_path.exists():
        data = load_config_file(config_path)
        if data.get("disable_default_upstreams") is True:
            return True
    return False


def get_effective_upstreams(
    config_path: Path | None,
    no_default_upstreams_flag: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Return (upstreams, used_defaults). Upstreams from config if non-empty; else default
    upstreams unless disabled by config, env REPO_MIRROR_NO_DEFAULT_UPSTREAMS, or --no-default-upstreams.
    used_defaults is True when the returned list is the built-in default upstreams.
    """
    from_config = get_upstreams_from_config(config_path) if config_path else []
    if from_config:
        return (from_config, False)
    if get_disable_default_upstreams(config_path, flag_override=no_default_upstreams_flag or None):
        return ([], False)
    return (get_default_upstreams(), True)


def save_upstreams_to_config(config_path: Path, upstreams: list[dict[str, Any]]) -> None:
    """Write upstreams to YAML config file."""
    import yaml
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if config_path.exists():
            data = load_config_file(config_path)
        data["upstreams"] = upstreams
        with open(config_path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        logger.debug("Saved config to %s", config_path)
    except Exception as e:
        logger.error("Could not save config: path=%s error=%s", config_path, e)
        raise


def get_effective_config(
    *,
    config_path_override: Path | None = None,
    repo_root_override: Path | None = None,
    no_default_upstreams: bool = False,
) -> dict[str, Any]:
    """Return effective config as a single dict (for config show). Uses effective upstreams (defaults when no config)."""
    repo_root = get_repo_root(repo_root_override)
    config_path = get_config_path(config_path_override)
    if config_path is None:
        config_path = repo_root / "config.yaml"
    upstreams, _ = get_effective_upstreams(config_path, no_default_upstreams_flag=no_default_upstreams)
    return {
        "repo_root": str(repo_root),
        "config_file": str(config_path) if config_path else None,
        "cache_versions_per_package": get_cache_versions_per_package(),
        "metadata_ttl_seconds": get_metadata_ttl_seconds(config_path),
        "disk_high_watermark_bytes": get_disk_high_watermark_bytes(config_path),
        "package_hash_store": get_package_hash_store_type(config_path),
        "redis_url": get_redis_url(config_path),
        "upstreams": upstreams,
        "serve_bind": DEFAULT_SERVE_BIND,
        "serve_port": DEFAULT_SERVE_PORT,
        "enable_api": get_enable_api(config_path),
    }
