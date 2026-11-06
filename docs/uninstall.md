# Stop, uninstall or remove data

The installed CLI, installed agent skill, private workspace, model cache and
OS-managed dependencies have separate lifetimes. Uninstalling the CLI preserves
your original exports and private workspace data.

## Stop one workspace’s runtime

Select the exact workspace and stop its database before changing its data:

```bash
specitout --project "/absolute/path/to/my-bubble-app" runtime stop --format json
```

Verify the command succeeded for the intended workspace. If it fails, resolve
the runtime error before deleting database files. Normal later database commands
can bootstrap it again; there is no separate background supervisor to remove.
Stopping alone retains all data.

## Uninstall the CLI

Use the installation provenance recorded during [setup](agent-setup.md). For an
installation created through `uv tool`, uninstall its package with:

```bash
uv tool uninstall specitout-cli
```

For another isolated installation method, remove that specific tool environment
through its own installer. Confirm which installation is active if more than one
`specitout` is on PATH. Removing a temporary source checkout is separate from
removing the installed tool.

CLI removal does not delete private workspaces or installed skills. Stop any
runtime you intend to stop before removing the CLI, while its scoped stop
command is still available. Reinstalling the CLI later can use the retained
workspace, subject to runtime/schema compatibility.

## Remove the installed agent skill

Find the host-specific skill path in the installation record. Remove only the
installed `specitout` skill directory and its bundled references, or use that
host’s supported skill-removal mechanism. Reload the host or start a new session
if it caches skills. Do not remove the host’s entire skill directory.

The skill and CLI are independent installations. Removing one does not remove
the other. Keep provenance until both removals are verified.

## Delete a selected private workspace

Workspace deletion is a separate, explicit request. Identify the exact absolute
path, verify its runtime has stopped, and review the folder’s contents before
removing it through the filesystem. Prefer a recoverable move to Trash when
available.

Deleting that folder removes its manifest, retained source copies in `exports/`,
local database/index state in `.specitout/`, default model cache, logs and any
reports stored there. The original source outside the workspace survives. Copy
out any source versions or requested reports you want to retain first.

Retained Bubble exports are the portable rebuild route. Raw Postgres files
depend on the server major version; do not assume that copying them to another
machine is a complete migration or backup strategy.

## Optional shared caches and system packages

The default model cache lives in each workspace’s `.specitout/models/` and leaves
with that workspace. An override such as `SPECITOUT_EMBEDDING_CACHE_DIR` can point
to a shared location. Review which workspaces or applications use that location
before separately requesting its deletion; clearing a cache may require another
model download later.

Do not automatically uninstall Python, Postgres, pgvector, uv or package-manager
state. They may serve other applications. System-package removal is a separate
maintenance decision, not part of uninstalling SpecItOut.
