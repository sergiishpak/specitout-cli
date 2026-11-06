# Versions and releases

The package version in `pyproject.toml` is authoritative. `specitout --version`
reads the installed package metadata; it does not depend on a source checkout.
`uv.lock` and the corresponding `CHANGELOG.md` entry must agree with that version.
Repository publication and package-index releases are separate. Use a resolved
public Git commit for installation; these files do not imply a package-index release.

Use Semantic Versioning (`MAJOR.MINOR.PATCH`):

- Patch: compatible corrections and documentation fixes shipped with a release.
- Minor: compatible new commands/capabilities, including this onboarding work.
- Major: incompatible supported command, manifest, or output contract changes.

During 0.x development, describe any incompatible change explicitly in the
changelog; do not assume users can safely upgrade silently. Workspace manifest
schema versions and Postgres major versions are separate compatibility contracts.

For the next release:

1. Add user-visible changes under `## [Unreleased]` in `CHANGELOG.md`.
2. Choose the appropriate increment; update `[project].version` in
   `pyproject.toml`. Move only the Unreleased notes to a dated version entry and
   leave a fresh Unreleased section. Preserve earlier entries.
3. Run `uv lock` and `uv sync --extra dev`; run `uv run --extra dev pytest` and
   build a wheel. Verify `specitout --version` from an isolated wheel installation.
4. Run the native smoke test described in [usage.md](usage.md), validate skill
   discovery in the supported agent host, and record any unverified platforms.
5. Review the complete change, scan secrets/history and check the public-data
   policy before committing. Tag the reviewed commit `vX.Y.Z` and publish only
   when explicitly requested. Never tag unpublished work merely to make an
   installer example appear usable.

CLI and skill releases travel together: bootstrap resolves one full Git commit
for both. Record that commit in skill provenance and keep release notes linked
from the README. Updates are explicit; see [agent-setup.md](agent-setup.md).
The pinned commit freezes SpecItOut source, while dependency/model resolution is
separate. An installed CLI does not migrate raw database files between Postgres
major versions; retain private exports for rebuilding.
