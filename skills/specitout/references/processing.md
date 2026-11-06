# Import, measured processing, and recovery

Use one explicit workspace and export version throughout. Examples use synthetic labels; replace paths and labels with the user's selected scope. Preserve shell quoting, or use subprocess argument arrays in automation.

Before processing, explain the stages: validate/fingerprint and copy export; parse/normalize; build canonical graph and source evidence; build search documents; download/load the local embedding model; compute embeddings; verify readiness; activate the version. The first model download needs network/cache space and is separate from embedding work. Avoid promising a total duration.

## Import a user-supplied file

```sh
specitout --project "/absolute/private/my-app" import add --version v1 --export "/absolute/user-supplied/export.json" --format json
specitout --project "/absolute/private/my-app" import status --version v1 --format json
specitout --project "/absolute/private/my-app" index status --version v1 --format json
```

The workspace manifest supplies the app. An explicit conflicting `--app` is an error. The CLI validates basic export shape before database writes, stages a hash-verified stable copy under workspace `exports/`, reuses identical content, and refuses to overwrite different content. Keep the original file. Use the staged source for evidence and retries; do not manually overwrite versioned files. Report malformed/unsupported input without dumping client JSON into diagnostics.

Slow stages emit ten-second elapsed stderr heartbeats. Row/document batches are explicitly uncommitted until database validation and commit succeeds. Stage fractions are stage progress, not overall work percentages or ETAs. Progress belongs on stderr; stdout contains the JSON command result. Observe both the exit code and result status/readiness. During long work, tell the user the current stage, elapsed time, measured completed/remaining counts if present, and whether work can resume. Mark unavailable measurements as unknown. A quiet model download or first model load is not a measured percentage. Keep detailed logs private.

## Resume and verify

```sh
specitout --project "/absolute/private/my-app" index resume --version v1 --initial-limit 256 --max-passes 20 --format json
specitout --project "/absolute/private/my-app" import status --version v1 --format json
specitout --project "/absolute/private/my-app" index status --version v1 --format json
```

Resume runs bounded batches. A verified complete index returns `passes: 0` without rebuilding search documents or recomputing vectors; use `index rebuild` only when a rebuild is intended. A pass limit or interruption can leave useful saved progress; inspect status, then resume the same version. On memory pressure lower `--initial-limit` (and, if needed, `--min-limit`); do not delete the database or register a second version merely to retry embeddings. A failed batch or absent counters is not proof of zero remaining work. If parsing/ingestion failed, inspect the error and use `import retry --version v1 --format json`, optionally with an explicitly supplied replacement `--export PATH` when appropriate. Read `specitout import retry --help` before changing its source.

Only announce full completion when database-backed status reports verified readiness and no required embedding work remains. Partial graph/entity/bundle investigation may be useful beforehand; explicitly label incomplete semantic coverage. Do not silently activate an incomplete version.

```sh
specitout --project "/absolute/private/my-app" import activate --version v1 --format json
specitout --project "/absolute/private/my-app" import status --version v1 --format json
```

Confirm the requested version is active after activation. A failed command is a recovery point, never a success announcement. Stop if the selected application/version differs from the intended scope. See [investigation.md](investigation.md) for retrieval once enough evidence is available.
