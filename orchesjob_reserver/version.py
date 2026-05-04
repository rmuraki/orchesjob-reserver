from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from . import __version__ as fallback_version


PACKAGE_NAME = "orchesjob-reserver"


def get_version() -> str:
    """Return installed package version.

    With `pip install -e .`, importlib.metadata reads the version from package
    metadata generated from pyproject.toml. When running directly from source
    without installation, fall back to __version__.
    """
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return fallback_version
