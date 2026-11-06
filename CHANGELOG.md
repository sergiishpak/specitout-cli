# Changelog

Versions use Semantic Versioning. Entries describe repository versions; publication is tracked separately by Git tags/releases.

## [Unreleased]


## [0.2.2] - 2026-11-07
### Fixed
- Start the app-owned Postgres runtime on Linux without requiring write access
  to the distribution's shared Unix-socket directory. CLI connections remain on
  localhost TCP.

### Validation
- Add native Ubuntu CI coverage with matching Postgres/pgvector packages and an
  unavailable socket-default regression.
- Verify installation of missing native prerequisites in an isolated Ubuntu
  environment and implicit skill discovery/use in a fresh Codex CLI session.
- Clarify search completion and canonical-key handling in the installed skill
  after observing an avoidable identifier-guessing detour in a follow-up session.

## [0.2.1] - 2026-11-06
### Fixed
- Return supported, workspace-bound next commands with the selected version and readiness-appropriate recovery steps.
- Resolve Bubble index aliases in source locators while preserving original aliases and content hashes; existing indexes can be queried without reimporting.
- Pin retrieval to one export and include resolved version/export identifiers even when the active version is selected implicitly.
- Deduplicate canonical search results and merge their evidence; leading deprecation-name hints no longer dominate ordinary discovery, while exact and explicitly legacy searches remain available.
- Avoid loading the local embedding model when semantic retrieval is unavailable.
- Resume a verified complete index without replacing documents or recomputing vectors.

### Improved
- Add elapsed stderr heartbeats, graph substeps, row/document batch counters, cold model/library loading feedback and explicit transaction validation/commit feedback.
- Distinguish stage progress from total work; stop progress reporters on completion, errors and interruption.

### Documentation
- Record private real-export acceptance and preserved-index regression coverage;
  keep all dataset-specific inputs, measurements and derived outputs private.
- Verify public-URL bootstrap with empty package/model caches, matching CLI/skill
  provenance, real synthetic embeddings and workspace-preserving uninstall.

## [0.2.0] - 2026-11-04
### Added
- Private application workspaces, workspace discovery and application scope checks.
- Passive setup diagnostics, scoped runtime stop, and stable private source copies.
- A distributable agent skill and revision-pinned CLI/skill bootstrap with provenance.
- Separate illustrations of local export processing and retrieval-augmented answering.
- JSON lifecycle results/errors, elapsed processing feedback and explicit model-load feedback.

### Fixed
- Interrupted indexing no longer reports success when readiness has not been verified.
- Processing progress is sent to stderr so JSON results remain parseable.

### Changed
- Removed the illustrative export file; users supply exports privately.
- Unfinished task, license and trial commands are hidden from the public CLI.
- Activation now requires fully ready indexing; partial versions remain inspectable.

## [0.1.0]

Initial repository version: local Bubble ingestion, Postgres/pgvector runtime,
structural retrieval and evidence bundles. Historical publication date not established.
