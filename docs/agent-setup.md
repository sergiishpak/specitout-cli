# Install SpecItOut for an agent

Give an agent the repository URL and this request:

> Install SpecItOut and its analysis skill from this repository. Set up a private workspace for my Bubble application, then ask me for the local export path.

This guide installs a persistent isolated CLI and a complete, self-contained skill from **one immutable commit**. The wheel contains the CLI and SQL migrations; the separate skill copy includes every committed reference. The analysis workspace lives elsewhere and does not require Git.

Select a fetched commit containing this guide, the bootstrap script, the workspace CLI, and the skill together. Check the installed version and record the resolved commit rather than assuming that a branch name identifies a release. A commit pins SpecItOut source; dependency resolution and the embedding-model download are not a bit-for-bit environment lock.

## Inspect the machine and host

Read [the self-contained setup reference](../skills/specitout/references/setup.md) for platform prerequisites and provisioning boundaries. Target macOS/Linux as a non-root user; native Windows and WSL remain unvalidated. Inspect Python 3.11+, Git, uv, any current SpecItOut installation, and the host's supported skill directory before changing them. `uv tool install --force` replaces the existing tool installation.

The native runtime needs `postgres`, `initdb`, `pg_ctl`, and `psql` from the same Postgres installation/version, with `pg_trgm`, `pgcrypto`, and `vector` available there. Use `SPECITOUT_POSTGRES_BIN_DIR` if binaries are outside PATH. Install missing dependencies through supported platform tooling and existing authorization; there is no universal package-manager command. [Postgres platform downloads](https://www.postgresql.org/download/) and [pgvector installation](https://github.com/pgvector/pgvector#installation) explain the platform choices. A root-only container is a blocker because [initdb refuses root](https://www.postgresql.org/docs/current/app-initdb.html).

Identify the agent host and report the chosen skill path. [Codex supports `~/.agents/skills`](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills); this is the example below. Verify other hosts' documentation rather than guessing their paths. Report whether a reload/new session is needed and verify the skill appears; do not claim automatic discovery for every host.

## Resolve and review one commit

Clone the supplied public HTTPS URL into a fresh installation directory. The example uses the canonical repository; use the URL actually requested. These commands resolve the fetched revision once, then detach at it. For an explicit release/tag, resolve that fetched ref instead of HEAD. Do not put private exports into this checkout.

```sh
git clone -- https://github.com/Sergii-Shpak-072422/specitout-cli.git "/absolute/install/specitout-source"
git -C "/absolute/install/specitout-source" rev-parse HEAD
git -C "/absolute/install/specitout-source" checkout --detach FULL_COMMIT_SHA
```

Replace `FULL_COMMIT_SHA` with the full hash printed by Git, never a branch name. Read the pinned `AGENTS.md`, this guide, and bootstrap source before execution. For programmatic automation use subprocess argument arrays, including for URLs/paths; do not generate shell text by concatenating user input. Do not pipe remotely fetched text into a shell.

```sh
python3 "/absolute/install/specitout-source/scripts/bootstrap_specitout.py" \
  --checkout "/absolute/install/specitout-source" \
  --repo-url "https://github.com/Sergii-Shpak-072422/specitout-cli.git" \
  --revision FULL_COMMIT_SHA \
  --skill-dir "$HOME/.agents/skills" \
  --dry-run
```

Inspect the JSON plan, then run the same command without `--dry-run`. It checks that checkout HEAD and origin agree with the inputs, installs `git+HTTPS_URL@FULL_COMMIT_SHA` with `uv tool install --force`, and copies the skill from Git objects at that commit, not untracked or modified working files. Paths with spaces are supported. The script never reads an export, creates an application workspace, provisions Postgres, or starts a database. It writes JSON results to stdout and tool output to stderr.

The target `specitout/` directory gets `.specitout-install.json` with repository, commit, installer, and file hashes. An identical existing copy can be reused; a different revision, foreign skill, symlink, or local edits are refused before CLI installation. Updates are explicit: preserve/move the previous skill, choose a published commit, and repeat the pinned flow. There is no automatic overwrite or updater. If uv succeeds but the skill filesystem operation fails, report partial setup and retry after resolving the directory problem. A `.specitout-bootstrap.lock` prevents simultaneous installers; after interruption inspect the process and directory before removing a stale lock.

Check `uv tool list` and `specitout --version`. If the executable is missing from PATH, consult [uv's tool executable guidance](https://docs.astral.sh/uv/concepts/tools/#tool-executables) and update the current session appropriately. Confirm the skill's provenance revision equals the installation plan and check discovery in the named host. The tool and skill remain usable after the installation checkout is removed.

## Private workspace and first export

Choose one private workspace per application, outside the source checkout:

```sh
specitout project init "/absolute/private/my-app" --app my-app --format json
specitout --project "/absolute/private/my-app" doctor --format json
```

`project init` creates a versioned manifest and private directories, without initializing Postgres. `doctor` is passive: filesystem extension discovery is a hint, not a successful SQL extension check. Live bootstrap verifies extension availability and installed SQL when a database command runs. Resolve reported blockers; state any checks that remain unverified.

The workspace contains stable `exports/` evidence, `.specitout/` derived/runtime state and cache, and `specitout.toml` application scope. `--project` belongs before the command group; a matching ancestor manifest is also discovered from the working directory. A conflicting `SPECITOUT_DATA_ROOT` or explicit application slug is an error. Existing CLI users without a workspace retain their environment/global data-root behavior.

After setup, ask the user for the local Bubble export path. Explain local processing, the initial model download, measured progress, and hosted-chat data handling. Follow the installed skill's [processing reference](../skills/specitout/references/processing.md) for import, resume, verification, and activation. No real export is bundled or required to inspect this public repository.

For dependency tracing and question answering use the installed [investigation reference](../skills/specitout/references/investigation.md). For stopping/removing components use [removal](../skills/specitout/references/removal.md): tool uninstall preserves the private workspace; data deletion is a separate explicit request.
