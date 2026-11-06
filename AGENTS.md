# SpecItOut agent entry point

For **installation from this repository URL**, read [docs/agent-setup.md](docs/agent-setup.md) before running installation commands. Install the CLI and the complete `skills/specitout/` directory from the same resolved commit. Keep private application workspaces outside this source checkout; ask the user for their local Bubble export path after setup.

For **analyzing an export or existing workspace**, follow [skills/specitout/SKILL.md](skills/specitout/SKILL.md). It provides processing, recovery, evidence retrieval, and removal guidance that also travels with the installed skill.

For **source development**, inspect the relevant Python modules under `scripts/` and run `python -m pytest`. Native runtime checks need matching Postgres binaries and the `pg_trgm`, `pgcrypto`, and `vector` extensions. Do not add client exports, source excerpts, runtime databases, or private paths to this repository. Generate synthetic test inputs in temporary directories. Installation requests do not imply source modifications, publishing, or Git pushes.
