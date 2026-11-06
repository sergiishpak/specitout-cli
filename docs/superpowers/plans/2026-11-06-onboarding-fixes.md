# Onboarding fixes and preserved-index retest

User authorized implementation and routine decisions without further approvals.

## Completion requirements

- Command hints use supported arguments, known scope, and readiness-appropriate next steps.
- Source locators resolve aliases for new imports and existing-index responses while preserving source hashes and original provenance.
- Search deduplicates canonical entities, retains evidence, fills requested limits within a documented bound, and makes deprecated-name hints explicit without claiming runtime inactivity or hiding explicit legacy searches.
- Every retrieval command pins and reports the resolved version, including active defaults; partial-index retrieval avoids unnecessary model work.
- Long graph/document/commit stages emit truthful stderr heartbeats and observable counters; reporters stop on success/error/interruption. A verified ready resume preserves existing documents and vectors.
- Test synthetic regressions and installed wheel; use the existing private index to compare scope, source paths, semantic results, next actions and vector fingerprints before/after. No private data enters this tree.
- Update changelog/version and human/agent guidance. No commit, push, or publication requested.

## Execution

- [x] Root: command hints and CLI reporter cleanup, baseline private index fingerprint.
- [x] Source-locator workstream: shared normalization plus new-import and legacy-payload tests.
- [x] Retrieval workstream: dedup/ranking hints, pinned version metadata and model readiness guard.
- [x] Progress workstream: lifecycle heartbeat, granular counters, truthful stage transitions and ready resume no-op.
- [x] Integration: full suite, native synthetic flow, independent review, installed-wheel preserved-index tests and final stop.
- [x] Release notes: patch version 0.2.1, lockfile and changelog consistency, public-safe validation update, private test report.

## Evidence ledger

Initial inspection confirmed unsupported `--key` in status actions, unfilled action placeholders, retrieval scope resolution falling back to None for active default, and heartbeat-free reporter. Prior acceptance artifacts locate the private test index; current state will be verified before use. The earlier acceptance turn is progress (real import/index/evidence and persisted reports), not a pending live process.

Completed 2026-11-07. Ordinary suite: 98 passed, one opt-in native smoke
skipped; native synthetic smoke passed separately. Independent review findings
were fixed and the focused follow-up reported no remaining material issues.
The final isolated 0.2.1 wheel passed all nine private preserved-index cases,
including a generated command and observed cold-load heartbeats. Installed
Python/SQL files and the complete skill copy match source. Before/after vector
fingerprints and timestamps are identical, and the app-owned database is
stopped. Detailed proof and the final report are stored only in the private
acceptance workspace. No publication or Git push was performed.
