from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from specitout.runtime_migrations import apply_runtime_migrations
from specitout.runtime_errors import SpecItOutRuntimeError
from specitout.runtime_paths import resolve_app_data_root, stage_runtime_migrations


REQUIRED_EXTENSIONS: tuple[str, ...] = ("pg_trgm", "pgcrypto", "vector")
DEFAULT_DATABASE = "specitout"


@dataclass(frozen=True)
class RuntimeStatus:
    state: str
    data_root: str
    bootstrap_action: str
    server_action: str
    migrations: str
    extensions: str
    database: str
    port: int


class AppOwnedPostgresRuntime:
    def __init__(self) -> None:
        self._command_cwd = Path.cwd()
        self._env = os.environ

    def ensure_ready(self) -> RuntimeStatus:
        binaries = self._resolve_binaries()
        data_root = self._resolve_data_root()
        cluster_dir = data_root / "postgres" / "data"
        runtime_dir = data_root / "postgres" / "run"
        log_dir = data_root / "logs"
        metadata_path = data_root / "postgres" / "runtime.json"
        cluster_dir.parent.mkdir(parents=True, exist_ok=True)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        metadata = self._load_metadata(metadata_path)
        port = self._resolve_port(metadata, cluster_dir)
        bootstrap_action = "reused"
        if not (cluster_dir / "PG_VERSION").exists():
            self._run_command(
                [binaries["initdb"], "-D", str(cluster_dir), "-U", "postgres", "-A", "trust"],
                "initialize local Postgres cluster",
            )
            bootstrap_action = "created"

        server_action = "already-running"
        if not self._cluster_server_ready(
            binaries["pg_ctl"],
            binaries["psql"],
            cluster_dir,
            port,
        ):
            log_path = log_dir / "postgres.log"
            self._run_command(
                [
                    binaries["pg_ctl"],
                    "-D",
                    str(cluster_dir),
                    "-l",
                    str(log_path),
                    "-o",
                    f"-c listen_addresses=127.0.0.1 -p {port}",
                    "start",
                ],
                "start local Postgres runtime",
            )
            self._wait_for_server(binaries["psql"], port)
            server_action = "started"

        try:
            missing_extensions = self._missing_available_extensions(binaries["psql"], port)
            if missing_extensions:
                missing = ", ".join(missing_extensions)
                raise SpecItOutRuntimeError(
                    "local Postgres is missing required extensions: "
                    f"{missing}. Install a Postgres distribution that provides them "
                    "or point SPECITOUT_POSTGRES_BIN_DIR at one that does."
                )

            self._ensure_database(binaries["psql"], port, DEFAULT_DATABASE)
            self._ensure_compatibility_objects(binaries["psql"], port, DEFAULT_DATABASE)
            self._apply_migrations(binaries["psql"], port, DEFAULT_DATABASE, data_root)
            self._verify_schema_migrations(binaries["psql"], port, DEFAULT_DATABASE)
            self._verify_installed_extensions(binaries["psql"], port, DEFAULT_DATABASE)
        except SpecItOutRuntimeError:
            if server_action == "started":
                self._stop_server(binaries["pg_ctl"], cluster_dir)
            raise

        status = RuntimeStatus(
            state="ready",
            data_root=str(data_root),
            bootstrap_action=bootstrap_action,
            server_action=server_action,
            migrations="applied",
            extensions="verified",
            database=DEFAULT_DATABASE,
            port=port,
        )
        metadata_path.write_text(json.dumps(asdict(status), indent=2) + "\n")
        return status

    def _resolve_binaries(self) -> dict[str, str]:
        postgres_bin_dir = self._env.get("SPECITOUT_POSTGRES_BIN_DIR")
        binaries = {
            "postgres": self._resolve_binary("postgres", postgres_bin_dir),
            "initdb": self._resolve_binary("initdb", postgres_bin_dir),
            "pg_ctl": self._resolve_binary("pg_ctl", postgres_bin_dir),
            "psql": self._resolve_binary("psql", postgres_bin_dir),
        }
        missing = [name for name, path in binaries.items() if not path]
        if missing:
            names = ", ".join(sorted(missing))
            raise SpecItOutRuntimeError(
                f"missing required runtime binaries: {names}. "
                "Install them or configure SPECITOUT_POSTGRES_BIN_DIR."
            )
        return {name: str(path) for name, path in binaries.items()}

    def _resolve_binary(self, name: str, postgres_bin_dir: str | None) -> str | None:
        if postgres_bin_dir:
            candidate = Path(postgres_bin_dir) / name
            if candidate.is_file():
                return str(candidate)
            return None
        return shutil.which(name)

    def _resolve_data_root(self) -> Path:
        return resolve_app_data_root(self._env)

    def _load_metadata(self, metadata_path: Path) -> dict[str, object]:
        if not metadata_path.is_file():
            return {}
        try:
            return json.loads(metadata_path.read_text())
        except json.JSONDecodeError:
            return {}

    def _resolve_port(self, metadata: dict[str, object], cluster_dir: Path) -> int:
        override = self._env.get("SPECITOUT_POSTGRES_PORT")
        if override:
            return int(override)
        pid_port = self._read_postmaster_port(cluster_dir)
        if pid_port is not None:
            return pid_port
        metadata_port = metadata.get("port")
        if isinstance(metadata_port, int):
            return metadata_port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _read_postmaster_port(self, cluster_dir: Path) -> int | None:
        postmaster_pid = cluster_dir / "postmaster.pid"
        if not postmaster_pid.is_file():
            return None
        lines = postmaster_pid.read_text().splitlines()
        if len(lines) < 4:
            return None
        try:
            return int(lines[3].strip())
        except ValueError:
            return None

    def _server_ready(self, psql_binary: str, port: int) -> bool:
        try:
            self._run_psql(psql_binary, port, "postgres", "select 1")
        except SpecItOutRuntimeError:
            return False
        return True

    def _cluster_server_ready(
        self,
        pg_ctl_binary: str,
        psql_binary: str,
        cluster_dir: Path,
        port: int,
    ) -> bool:
        if not self._pg_ctl_reports_running(pg_ctl_binary, cluster_dir):
            return False
        cluster_port = self._read_postmaster_port(cluster_dir)
        if cluster_port is not None and cluster_port != port:
            return False
        return self._server_ready(psql_binary, cluster_port or port)

    def _pg_ctl_reports_running(self, pg_ctl_binary: str, cluster_dir: Path) -> bool:
        try:
            result = subprocess.run(
                [pg_ctl_binary, "-D", str(cluster_dir), "status"],
                cwd=self._command_cwd,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise SpecItOutRuntimeError(
                f"failed to inspect local Postgres runtime status: {exc}"
            ) from exc
        return result.returncode == 0

    def _wait_for_server(self, psql_binary: str, port: int) -> None:
        deadline = time.time() + 20
        while time.time() < deadline:
            if self._server_ready(psql_binary, port):
                return
            time.sleep(0.25)
        raise SpecItOutRuntimeError(
            f"local Postgres runtime did not become ready on 127.0.0.1:{port}."
        )

    def _missing_available_extensions(self, psql_binary: str, port: int) -> list[str]:
        query = (
            "select name "
            "from pg_available_extensions "
            "where name in ('pg_trgm', 'pgcrypto', 'vector') "
            "order by name;"
        )
        output = self._run_psql(psql_binary, port, "postgres", query)
        available = {line.strip() for line in output.splitlines() if line.strip()}
        return [name for name in REQUIRED_EXTENSIONS if name not in available]

    def _ensure_database(self, psql_binary: str, port: int, database: str) -> None:
        exists = self._run_psql(
            psql_binary,
            port,
            "postgres",
            f"select 1 from pg_database where datname = '{database}';",
        )
        if exists.strip() == "1":
            return
        self._run_psql(psql_binary, port, "postgres", f"create database {database};")

    def _ensure_compatibility_objects(self, psql_binary: str, port: int, database: str) -> None:
        sql = """
create schema if not exists extensions;
create schema if not exists storage;
create table if not exists storage.buckets (
  id text primary key,
  name text not null,
  public boolean not null default false
);
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role;
  end if;
end
$$;
"""
        self._run_psql(psql_binary, port, database, sql)

    def _apply_migrations(
        self,
        psql_binary: str,
        port: int,
        database: str,
        data_root: Path,
    ) -> None:
        migrations_dir = stage_runtime_migrations(data_root, self._env)
        apply_runtime_migrations(
            psql_binary=psql_binary,
            host="127.0.0.1",
            port=port,
            user="postgres",
            database=database,
            migrations_dir=migrations_dir,
            command_cwd=self._command_cwd,
        )

    def _verify_schema_migrations(self, psql_binary: str, port: int, database: str) -> None:
        output = self._run_psql(
            psql_binary,
            port,
            database,
            "select count(*) from specitout_runtime.schema_migrations;",
        )
        if int(output.strip() or "0") <= 0:
            raise SpecItOutRuntimeError("local migration bootstrap did not record any applied migrations.")

    def _verify_installed_extensions(self, psql_binary: str, port: int, database: str) -> None:
        output = self._run_psql(
            psql_binary,
            port,
            database,
            "select extname from pg_extension where extname in ('pg_trgm', 'pgcrypto', 'vector') order by extname;",
        )
        installed = {line.strip() for line in output.splitlines() if line.strip()}
        missing = [name for name in REQUIRED_EXTENSIONS if name not in installed]
        if missing:
            raise SpecItOutRuntimeError(
                "local migration bootstrap did not install required extensions: "
                + ", ".join(missing)
            )

    def _run_psql(self, psql_binary: str, port: int, database: str, sql: str) -> str:
        try:
            result = subprocess.run(
                [
                    psql_binary,
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(port),
                    "-U",
                    "postgres",
                    "-d",
                    database,
                    "-Atqc",
                    sql,
                ],
                cwd=self._command_cwd,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise SpecItOutRuntimeError(
                f"failed to run local Postgres command against {database}: {exc}"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise SpecItOutRuntimeError(
                f"failed to run local Postgres command against {database}: {detail or sql}"
            )
        return result.stdout

    def _run_command(self, argv: list[str], action: str) -> None:
        try:
            result = subprocess.run(
                argv,
                cwd=self._command_cwd,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise SpecItOutRuntimeError(f"failed to {action}: {exc}") from exc
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout).strip()
        raise SpecItOutRuntimeError(f"failed to {action}: {detail or 'unknown error'}")

    def _stop_server(self, pg_ctl_binary: str, cluster_dir: Path) -> None:
        subprocess.run(
            [pg_ctl_binary, "-D", str(cluster_dir), "stop", "-m", "fast"],
            cwd=self._command_cwd,
            capture_output=True,
            text=True,
        )
