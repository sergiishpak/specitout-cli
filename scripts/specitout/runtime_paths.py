from __future__ import annotations

import os
import sys
import tempfile
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Mapping

from specitout.runtime_errors import SpecItOutRuntimeError


def resolve_app_data_root(env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    from specitout.workspace import CURRENT_PROJECT
    project = CURRENT_PROJECT.get()
    if project is not None:
        return project.data_root
    override = source.get("SPECITOUT_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        appdata = source.get("APPDATA")
        if appdata:
            return Path(appdata) / "specitout"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "specitout"
    xdg_data_home = source.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "specitout"
    return Path.home() / ".local" / "share" / "specitout"


def resolve_embedding_cache_dir(env: Mapping[str, str] | None = None) -> str | None:
    source = os.environ if env is None else env
    override = source.get("SPECITOUT_EMBEDDING_CACHE_DIR")
    if override is not None:
        stripped = override.strip()
        return stripped or None
    return str(resolve_app_data_root(source) / "models")


def stage_runtime_migrations(data_root: Path, env: Mapping[str, str] | None = None) -> Path:
    source = os.environ if env is None else env
    override = source.get("SPECITOUT_RUNTIME_MIGRATIONS_DIR")
    if override:
        migrations_dir = Path(override).expanduser().resolve()
        _require_runtime_migrations(migrations_dir)
        return migrations_dir

    stages_root = data_root / "runtime" / "migration-stages"
    resource_root = files("specitout").joinpath("resources", "runtime", "migrations")
    if not resource_root.is_dir():
        raise SpecItOutRuntimeError("packaged SpecItOut runtime migrations are missing from the installation.")

    stages_root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="migrations-", dir=stages_root))
    _copy_resource_tree(resource_root, destination)
    _require_runtime_migrations(destination)
    return destination


def _require_runtime_migrations(migrations_dir: Path) -> None:
    if not migrations_dir.is_dir() or not any(migrations_dir.glob("*.sql")):
        raise SpecItOutRuntimeError(
            f"SpecItOut runtime migrations directory {migrations_dir} does not contain SQL migrations."
        )


def _copy_resource_tree(source: Traversable, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        child_destination = destination / child.name
        if child.is_dir():
            _copy_resource_tree(child, child_destination)
        else:
            temp_destination = child_destination.with_name(f".{child.name}.{os.getpid()}.tmp")
            temp_destination.write_bytes(child.read_bytes())
            temp_destination.replace(child_destination)
