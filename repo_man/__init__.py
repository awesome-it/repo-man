"""Linux package mirror and publishing tool (APT pull-through cache + local publish)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("repo-man")
except PackageNotFoundError:
    __version__ = "0.1.0"
