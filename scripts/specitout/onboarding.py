"""Small CLI entry points which do not require a database connection."""
from __future__ import annotations

import importlib.metadata
import os
import platform
import subprocess
from pathlib import Path

from specitout.runtime import AppOwnedPostgresRuntime
from specitout.runtime_paths import resolve_app_data_root, resolve_embedding_cache_dir
from specitout.workspace import CURRENT_PROJECT, init_project


def envelope(command, data, *, status='ok'):
    project = CURRENT_PROJECT.get()
    return {'status': status, 'command': command,
            'scope': {'app_slug': project.app_slug if project else None, 'version_label': None},
            'data': data, 'warnings': [], 'degraded': status != 'ok', 'next_actions': []}


def project_init(args, parser, services):
    from specitout.app import _print_envelope
    project = init_project(args.path, args.app_slug)
    result = envelope("project init", {"state": "initialized", "root": str(project.root), "app_slug": project.app_slug, "data_root": str(project.data_root)})
    result["scope"]["app_slug"] = project.app_slug
    _print_envelope(result, args)
    return 0


def doctor(args, parser, services):
    from specitout.app import _print_envelope
    runtime = AppOwnedPostgresRuntime()
    bin_dir = os.environ.get('SPECITOUT_POSTGRES_BIN_DIR')
    binaries = {name: runtime._resolve_binary(name, bin_dir) for name in ('postgres', 'initdb', 'pg_ctl', 'psql')}
    extension_files = None
    if binaries['postgres']:
        pg_config = Path(binaries['postgres']).resolve().parent / 'pg_config'
        if pg_config.is_file():
            try:
                result = subprocess.run([str(pg_config), '--sharedir'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    directory = Path(result.stdout.strip()) / 'extension'
                    extension_files = {name: (directory / f'{name}.control').is_file() for name in ('pg_trgm', 'pgcrypto', 'vector')}
            except (OSError, subprocess.TimeoutExpired):
                pass  # Passive discovery remains unknown; bootstrap performs the real SQL checks.
    root = resolve_app_data_root()
    existing = next((p for p in (root, *root.parents) if p.exists()), root)
    supported = platform.system() in ('Darwin', 'Linux') and (not hasattr(os, 'geteuid') or os.geteuid() != 0)
    cache = Path(resolve_embedding_cache_dir() or root / 'models')
    data = {'state': 'prerequisites_found' if all(binaries.values()) and supported and os.access(existing, os.W_OK) else 'setup_required',
            'version': importlib.metadata.version('specitout-cli'), 'platform': platform.system(),
            'supported_non_root_platform': supported, 'data_root': str(root), 'binaries': binaries,
            'data_path_writable': os.access(existing, os.W_OK),
            'embedding_model': os.environ.get('SPECITOUT_EMBEDDING_MODEL', 'BAAI/bge-small-en-v1.5'),
            'model_cache': str(cache), 'model_cache_exists': cache.exists(),
            'model_ready': 'not_loaded', 'extension_control_files': extension_files, 'extensions': 'not_checked_in_database; bootstrap verifies pg_trgm, pgcrypto, vector',
            'database_started': False}
    ready = data['state'] == 'prerequisites_found' and (extension_files is None or all(extension_files.values()))
    if not ready:
        data['state'] = 'setup_required'
    _print_envelope(envelope('doctor', data, status='ok' if ready else 'warning'), args)
    return 0 if ready else 2


def runtime_stop(args, parser, services):
    from specitout.app import _print_envelope
    _print_envelope(envelope('runtime stop', AppOwnedPostgresRuntime().stop()), args)
    return 0
