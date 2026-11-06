# Using a private workspace

The [agent setup guide](agent-setup.md) is the installation entry point. It
installs the CLI and complete skill from one repository revision, records
provenance and checks platform dependencies. You can then use the agent or run
the commands below yourself.

These examples describe the unreleased 0.2.1 interface. Paths, app slug, export
version and entity identifiers below are placeholders. Keep private exports
outside the public source checkout.

## Create and inspect the workspace

```bash
specitout --version
specitout project init "$HOME/Private Apps/my-bubble-app" --app my-app
specitout --project "$HOME/Private Apps/my-bubble-app" doctor --format json
```

Place the global `--project` option before the command group. Alternatively,
run commands from the workspace or a child folder; the nearest `specitout.toml`
selects the workspace. The manifest supplies `--app` when omitted. An explicitly
conflicting `--app` fails rather than crossing application scopes.

`doctor` is passive. It inspects platform, paths, discovered binaries and cache
state without starting or connecting to the database or downloading a model.
A passive report may leave extension availability or model usability unknown;
that is not verified runtime readiness. Use import/index status for the runtime
and processing state; those commands can bootstrap the local runtime.

Initialization creates a private working folder with `exports/`, `.specitout/`
and `reports/`; it does not initialize Git. Use a different folder per Bubble app
and retain multiple versions of that app inside its workspace.

## Import, index and activate

```bash
specitout --project "$HOME/Private Apps/my-bubble-app" import add \
  --version export-2026-11-04 --export "/absolute/path/to/my-export.json" --format json

specitout --project "$HOME/Private Apps/my-bubble-app" import status \
  --version export-2026-11-04 --format json

SPECITOUT_EMBEDDING_DEVICE=cpu specitout --project "$HOME/Private Apps/my-bubble-app" index resume \
  --version export-2026-11-04 --format json

specitout --project "$HOME/Private Apps/my-bubble-app" import status \
  --version export-2026-11-04 --format json

specitout --project "$HOME/Private Apps/my-bubble-app" import activate \
  --version export-2026-11-04 --format json
```

`import add` validates the basic source shape, preserves a stable source copy
inside `exports/` and registers/processes the export. It retains the original,
reuses an identical stored copy, and does not overwrite a different export.
Do not use a filename or successful registration as proof of readiness.

The model cache may need an initial download. That setup time is separate from
embedding computation for the export. The example pins CPU inference explicitly;
omit the environment override to let the provider select a device. See the
[processing explanation](architecture.md) for the stack and data boundary.

Progress goes to stderr and command results go to stdout. JSON output is for
agents and scripts; preserve stderr when displaying human progress. Report
measured stages, elapsed time and counts where supplied. There is no measured
processing-time promise or trustworthy percentage unless the command provides
a known total.

`index resume` performs bounded embedding work and checks readiness. Inspect its
result and the selected export’s status. Activate only when readiness is
verified. Activation is a separate step; an interrupted or partially indexed
export must not be described as complete.

For one bounded rebuild pass, use `index rebuild --version VERSION --limit 256`.
`index resume` has `--initial-limit`, `--min-limit`, `--max-passes` and
`--stuck-pass-threshold` controls. The normal agent flow uses the defaults before
changing batch controls to address a measured problem.

## Investigate the export

The following commands assume the export is ready and active. Add
`--version VERSION` to investigate a specific stored version explicitly. Copy
canonical identifiers from actual query results; the examples below use
synthetic placeholders.

```bash
specitout --project "$HOME/Private Apps/my-bubble-app" query search \
  --query "order approval" --limit 5 --format json

specitout --project "$HOME/Private Apps/my-bubble-app" query entity \
  --entity "ENTITY_KEY_FROM_SEARCH" --format json

specitout --project "$HOME/Private Apps/my-bubble-app" query usage \
  --entity "ENTITY_KEY_FROM_SEARCH" --direction inbound --limit 20 --format json

specitout --project "$HOME/Private Apps/my-bubble-app" query paths \
  --from "FIRST_ENTITY_KEY" --to "SECOND_ENTITY_KEY" --max-hops 3 --max-paths 3 --format json

specitout --project "$HOME/Private Apps/my-bubble-app" bundle build \
  --entity "ENTITY_KEY_FROM_SEARCH" --max-hops 1 --entity-limit 20 --edge-limit 30 --format json
```

Start with a narrow anchor. Inspect the canonical entity and its source
references, then follow the relevant relationships. Usage accepts `inbound`,
`outbound` or `bidirectional`; `--relation` narrows it to a relationship type.
Paths and bundles are bounded, so widening limits should answer a concrete gap.

Search uses exact, lexical and semantic evidence where available. `--mode deep`
can widen search/bundle retrieval beyond the default `root` mode. Read any
reported degraded semantic mode and bundle truncation. No matches in an
incomplete index are not proof that a behavior is absent.

The agent should cite source paths and identifiers from the selected version,
separate structural observations from inferred purpose, and state unresolved
references or coverage gaps. It may inspect partial entity/bundle results before
full indexing, but must label those limits. The CLI does not call a chat LLM or
edit the live application; the surrounding agent controls any LLM exposure.

## Recover after interruption

Check the export’s `import status` and `index status` before restarting work. For
incomplete embeddings, run `index resume` against the same version. For a failed
import, use `import retry --version VERSION --format json`; supply `--export`
only when deliberately selecting the retained source for retry. Keep source
files until their imports and evidence have been verified.

Mutating commands are serialized per workspace. If another process holds the
workspace lock, inspect running processes before retrying.
Do not delete locks or database files to force two writers through. If recovery
fails, retain diagnostics in the private workspace and let the agent investigate
the actual error before rebuilding or deleting anything.

A model cache directory merely existing does not prove that all model files are
usable. A database process running does not prove an export is ready. Recheck
actual processing state after resolving dependency, download or permission
errors.

## Stop the runtime

```bash
specitout --project "$HOME/Private Apps/my-bubble-app" runtime stop --format json
```

Stop targets the selected workspace. Later database-backed work uses the existing
bootstrap to start it again. Stopping preserves exports, indexes, reports and the
installed CLI. For uninstalling the CLI or deleting data, use the separate
[removal procedures](uninstall.md).

## Development checks

Install development tools with `uv sync --extra dev`, then run
`uv run --extra dev pytest`. For a native integration test on a machine with
Postgres and pgvector, run:

```sh
SPECITOUT_TEST_POSTGRES=1 uv run --extra dev pytest tests/test_postgres_smoke.py -q
```

This creates a temporary private workspace, imports generated synthetic structure,
indexes with deterministic test vectors, activates, retrieves evidence, and stops
its database. It tests storage/retrieval plumbing, not embedding relevance or
real-export compatibility. The test cleans up its temporary workspace. A separate
user-supplied export test is needed for acceptance; keep those files and logs out
of this repository. CI runs unit/bootstrap tests and isolated wheel checks; the
native-runtime test is opt-in.

## Progress and already-complete indexes

Slow processing stages emit elapsed stderr heartbeats every ten seconds, including
when a database transaction is validating before commit. Row/document counters
name their units; a batch marked `uncommitted` is not saved work yet. A successful
commit is reported only after database validation returns. `stage_progress` is a
fraction of stages, not an estimate of total work or remaining time.

Use `index resume` for existing work. If the selected version is verified ready
and every document is embedded, it returns with `passes: 0` and retains the index.
`index rebuild` intentionally regenerates search documents; use it only when you
want that rebuild, rather than as a routine readiness check.

Search returns unique canonical entities from at most 25 candidate documents,
merging their evidence. A limit shortfall at that cap is reported. Leading
`DEPR?`, `Deprecated` or `Obsolete` name markers are discovery hints, not evidence
of runtime inactivity. Explicit deprecated searches and exact names/keys remain
available. Resolved export IDs and version labels accompany retrieval results,
including when you select the active version implicitly.

Source locators use canonical export paths; responses retain original aliases in
`*_alias` metadata. This applies to existing indexes as well as new imports.
Source payloads and fragment hashes remain unchanged. Always verify evidence and
inspect bounds before treating a result as complete.
