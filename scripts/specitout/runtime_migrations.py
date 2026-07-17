from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from specitout.runtime_errors import SpecItOutRuntimeError


@dataclass(frozen=True)
class RuntimeMigration:
    version: str
    name: str
    path: Path
    checksum: str


def apply_runtime_migrations(
    *,
    psql_binary: str,
    host: str,
    port: int,
    user: str,
    database: str,
    migrations_dir: Path,
    command_cwd: Path,
) -> None:
    _run_psql(
        psql_binary,
        host,
        port,
        user,
        database,
        """
create schema if not exists specitout_runtime;
create table if not exists specitout_runtime.schema_migrations (
  version text primary key,
  name text not null,
  checksum text not null,
  applied_at timestamptz not null default now()
);
""",
        command_cwd,
    )
    for migration in _discover_migrations(migrations_dir):
        recorded = _recorded_checksum(
            psql_binary,
            host,
            port,
            user,
            database,
            migration.version,
            command_cwd,
        )
        if recorded == migration.checksum:
            continue
        if recorded:
            raise SpecItOutRuntimeError(
                "SpecItOut runtime migration checksum drift for "
                f"{migration.path.name}: expected {recorded}, found {migration.checksum}."
            )
        _run_psql_script(psql_binary, host, port, user, database, migration, command_cwd)
        _record_migration(
            psql_binary,
            host,
            port,
            user,
            database,
            migration,
            command_cwd,
        )


def _discover_migrations(migrations_dir: Path) -> list[RuntimeMigration]:
    migrations = []
    for path in sorted(migrations_dir.glob("*.sql")):
        version, _, name = path.stem.partition("_")
        if not version.isdigit() or not name:
            raise SpecItOutRuntimeError(f"invalid SpecItOut runtime migration filename: {path.name}")
        migrations.append(
            RuntimeMigration(
                version=version,
                name=name,
                path=path,
                checksum=_migration_checksum(path),
            )
        )
    if not migrations:
        raise SpecItOutRuntimeError(f"no SpecItOut runtime migrations found in {migrations_dir}.")
    return migrations


def _migration_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    include_dir = path.with_suffix("")
    if include_dir.is_dir():
        for child in sorted(include_dir.rglob("*.sql")):
            digest.update(b"\0")
            digest.update(child.relative_to(include_dir).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(child.read_bytes())
    return digest.hexdigest()


def _recorded_checksum(
    psql_binary: str,
    host: str,
    port: int,
    user: str,
    database: str,
    version: str,
    command_cwd: Path,
) -> str | None:
    output = _run_psql(
        psql_binary,
        host,
        port,
        user,
        database,
        "select checksum from specitout_runtime.schema_migrations "
        f"where version = '{_sql_literal(version)}';",
        command_cwd,
    ).strip()
    return output or None


def _record_migration(
    psql_binary: str,
    host: str,
    port: int,
    user: str,
    database: str,
    migration: RuntimeMigration,
    command_cwd: Path,
) -> None:
    _run_psql(
        psql_binary,
        host,
        port,
        user,
        database,
        "insert into specitout_runtime.schema_migrations (version, name, checksum) values "
        f"('{_sql_literal(migration.version)}', "
        f"'{_sql_literal(migration.name)}', "
        f"'{_sql_literal(migration.checksum)}');",
        command_cwd,
    )


def _run_psql(
    psql_binary: str,
    host: str,
    port: int,
    user: str,
    database: str,
    sql: str,
    command_cwd: Path,
) -> str:
    return _run_command(
        [psql_binary, "-h", host, "-p", str(port), "-U", user, "-d", database, "-Atqc", sql],
        f"run SpecItOut runtime migration SQL against {database}",
        command_cwd,
    )


def _run_psql_script(
    psql_binary: str,
    host: str,
    port: int,
    user: str,
    database: str,
    migration: RuntimeMigration,
    command_cwd: Path,
) -> None:
    include_dir = migration.path.with_suffix("")
    if include_dir.is_dir():
        sql = "".join(path.read_text() for path in sorted(include_dir.glob("*.sql")))
    else:
        sql = migration.path.read_text()
    _run_command(
        [
            psql_binary,
            "-h",
            host,
            "-p",
            str(port),
            "-U",
            user,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            f"SPECITOUT_RUNTIME_MIGRATION={migration.path.name}",
            "-f",
            "-",
        ],
        f"apply SpecItOut runtime migration {migration.path.name}",
        command_cwd,
        stdin=sql,
    )


def _run_command(
    argv: list[str],
    action: str,
    command_cwd: Path,
    *,
    stdin: str | None = None,
) -> str:
    try:
        result = subprocess.run(
            argv,
            cwd=command_cwd,
            input=stdin,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise SpecItOutRuntimeError(f"failed to {action}: {exc}") from exc
    if result.returncode == 0:
        return result.stdout
    detail = (result.stderr or result.stdout).strip()
    raise SpecItOutRuntimeError(f"failed to {action}: {detail or 'unknown error'}")


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")
