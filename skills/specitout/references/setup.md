# Setup from an installed skill

The skill is self-contained. Ordinary analysis does not require retaining or working inside the source checkout. Installation provenance is in the adjacent `.specitout-install.json`: repository URL, immutable commit, installer, and hashes of the copied files. Match its revision when reinstalling the CLI. A Python wheel alone does not include this skill directory.

## Inspect before provisioning

Target macOS or Linux as a non-root user. Native Windows and WSL are unvalidated. Stop with a clear blocker in a root-only environment: Postgres `initdb` refuses root. Docker and hosted databases are outside this runtime's current setup path.

Inspect Python 3.11+, Git, `uv`, an existing `specitout --version` / `uv tool list`, and the actual agent host. Use that host's documented skill directory. Codex supports the user directory `~/.agents/skills`; reload/restart if discovery does not update. Other hosts need their own verified path; do not assume they scan the same directory. Report the selected host and path.

Inspect native `postgres`, `initdb`, `pg_ctl`, and `psql` from the same Postgres installation/version. `pg_trgm`, `pgcrypto`, and pgvector's SQL extension `vector` must be available to that installation. Use `SPECITOUT_POSTGRES_BIN_DIR` for an explicit binary directory. Do not mix a system server with another installation's extension files. Provision through the platform's supported tooling under the host's authorization rules. Missing privileges are a blocker; do not claim one package command works everywhere.

Primary dependency references:

- [uv installation](https://docs.astral.sh/uv/getting-started/installation/) and [isolated tool installations](https://docs.astral.sh/uv/concepts/tools/).
- [PostgreSQL platform downloads](https://www.postgresql.org/download/) and [initdb user requirements](https://www.postgresql.org/docs/current/app-initdb.html).
- [pgvector installation](https://github.com/pgvector/pgvector#installation); use the Postgres installation's matching `pg_config` when building.
- [Codex skill discovery](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).

## Ubuntu 24.04 prerequisites

This recipe was exercised on a fresh isolated Ubuntu 24.04 aarch64 machine as
part of acceptance testing. Its base image already included Python 3.12; Git,
uv, Postgres and pgvector were absent. Inspect the host first and install only
missing components. Package availability on other distributions is separate.

With authorization to provision system packages, use APT for matching binaries
and extensions:

```sh
sudo apt-get update
sudo apt-get install -y --no-install-recommends git ca-certificates python3 python3-venv postgresql-16 postgresql-contrib-16 postgresql-16-pgvector
export SPECITOUT_POSTGRES_BIN_DIR=/usr/lib/postgresql/16/bin
```

Keep this environment variable set for CLI commands on that installation.
The app creates its own database cluster as the normal user and connects over
localhost TCP; it does not need the package's default server or a writable shared
Unix-socket directory. Run the CLI as that normal user, not through `sudo`.

If uv is missing, its supported PyPI installation can use a dedicated venv,
without changing the distribution-managed Python environment. Choose an unused
venv directory and preserve any existing uv executable; the following example
assumes both destinations are absent:

```sh
python3 -m venv "$HOME/.local/share/uv-bootstrap"
"$HOME/.local/share/uv-bootstrap/bin/python" -m pip install uv
mkdir -p "$HOME/.local/bin"
ln -s "$HOME/.local/share/uv-bootstrap/bin/uv" "$HOME/.local/bin/uv"
export PATH="$HOME/.local/bin:$PATH"
```

Check `python3 --version`, `uv --version`, the four Postgres binaries and the
three extension control files. Then use the pinned bootstrap below, initialize
a private workspace and run `doctor`; only a successful runtime bootstrap
verifies that the extensions actually load. Model download and native embedding
execution are separate from installing these prerequisites.

## Pinned reinstall or update

Clone the recorded public HTTPS repository into an installation checkout, resolve the desired published revision to a full commit SHA, and check out that SHA. Read its `docs/agent-setup.md`, then invoke its `scripts/bootstrap_specitout.py` with explicit `--checkout`, `--repo-url`, `--revision`, and `--skill-dir` arguments. Inspect `--dry-run` first. Never execute interpolated repository text through a shell; use argument arrays when automating.

The bootstrap installs the CLI with `uv tool install --force git+HTTPS_URL@FULL_SHA` and copies committed skill files from that exact revision. An identical skill may be reused. A modified skill or different revision is refused before tool installation. For an explicit upgrade, preserve or move the old skill first, then install the chosen revision; no automatic overwrite or background updates. `--force` replaces the existing uv tool installation, so identify any existing installation before proceeding.

## Create the private workspace

Choose a private directory outside the CLI source checkout, one per application. Git is not required there. Substitute the agreed absolute path and application slug:

```sh
specitout project init "/absolute/private/my-app" --app my-app --format json
specitout --project "/absolute/private/my-app" doctor --format json
```

Initialization creates a manifest and directories, without a database. The workspace owns `exports/`, `.specitout/` runtime/derived data, and its embedding cache. Keep client data there; no export belongs in the public repository. `SPECITOUT_DATA_ROOT` must agree with the selected workspace; remove a conflicting override instead of pointing at another app. Advanced users may explicitly override `SPECITOUT_EMBEDDING_CACHE_DIR` and should record that separate cache path.

`doctor` checks platform, paths, binaries, discoverable extension files, and cache hints passively. It does not connect, initialize Postgres, load the embedding model, or prove extension SQL works. Runtime bootstrap during import/status performs live SQL checks. Report passive failures and outstanding runtime checks accurately, then ask the user for the local export path. Continue with [processing.md](processing.md).
