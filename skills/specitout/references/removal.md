# Stop, uninstall, and retain private data

Treat runtime, tool installation, installed skill, workspace, and optional cache as separate resources. Read `.specitout-install.json` in the installed skill before choosing removal commands.

1. Stop the exact selected workspace and confirm success:

   ```sh
   specitout --project "/absolute/private/my-app" runtime stop --format json
   ```

   This stops its local database, not other workspaces. If stopping fails, resolve the reported scope/process problem before deleting files. A later database command bootstraps/restarts the runtime as needed; `project init` and passive `doctor` do not.

2. For a bootstrap-installed CLI, use `uv tool uninstall specitout-cli`. This removes the isolated tool environment and entry point. Private workspaces, originals, and staged exports remain. Do not uninstall Python, uv, or system Postgres as part of this operation.

3. Remove only the installed `specitout/` skill directory recorded by the bootstrap after checking its provenance and local edits. Preserve custom changes if present. Reload/restart the host if it still shows the removed skill. No global deletion command is necessary to analyze or stop an app.

Deleting data is a separate explicit user request. Identify the exact workspace; verify its manifest/application and that its runtime has stopped. Explain that deleting the workspace also deletes staged exports, derived graph, embeddings, cache, and database. Retain the user's original export unless its deletion was explicitly requested. Use the host's ordinary file-removal controls for the identified directory; do not infer authorization from “uninstall the CLI.”

For an explicitly configured shared embedding cache, inspect `SPECITOUT_EMBEDDING_CACHE_DIR` and other consumers before removing that exact cache on request. Do not remove broad Hugging Face, uv, Python, or Postgres directories. Keep installation checkouts separate from private workspaces so deleting a temporary checkout does not remove source evidence.
