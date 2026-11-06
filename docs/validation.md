# Onboarding validation

Local validation for the 0.2.0 working tree on 2026-11-04, macOS/Python 3.12.
This is not a published release or a real-application performance benchmark.

## Verified

- Pytest: 31 passed, one opt-in native test skipped in the ordinary suite.
- The native test was then run separately from an isolated, installed wheel's
  Python environment. It passed: temporary private workspace, generated source,
  import, bounded indexing, verified readiness, activation, search, entity,
  usage, bounded bundle, read-only runtime inspection, and stop.
- Native test vectors are deterministic 384-dimensional synthetic vectors.
  This verifies database/index/retrieval plumbing, not semantic relevance.
- Built a 0.2.0 wheel and installed it with actual runtime dependencies using
  `uv tool install` in temporary tool/bin directories. Outside the checkout,
  `--version`, help and packaged SQL resources worked.
- Uninstall removed that isolated executable and preserved workspace files.
- Nine offline bootstrap tests exercised a committed temporary Git source,
  explicit revision, full skill copying/provenance, repeat installation,
  conflict refusal, lock behavior, dry-run and failure paths.
- Skill frontmatter validator passed. Relative Markdown links resolve, both SVGs
  parse and were visually inspected, Python compilation and diff whitespace
  checks passed.
- Independent review findings were fixed with regression tests: interrupted
  source copies, symlink routing, incomplete activation, registry validation,
  initialization scope and monitoring during processing. Focused follow-up
  reported no remaining material bugs.

## Private real-export run — 2026-11-06

An isolated installation of the local 0.2.0 wheel was tested with one privately
held real export on macOS. Native database bootstrap, import, complete local
model embeddings, verified readiness, activation, exact/semantic retrieval,
canonical entities, usage, bounded paths/bundles and stop/restart succeeded.
Application indexing and retrieval ran with the prepared model in offline mode.
The original source was preserved. Dataset details, timings and all derived
artifacts remain outside this repository.

Semantic retrieval produced relevant investigation candidates, which were then
checked through canonical structure and source fragments. This is a qualitative
sample, not a general relevance benchmark or proof of live behavior.

The baseline run exposed these onboarding gaps (addressed by the 0.2.1 follow-up below):

- Long stages need more granular progress feedback.
- Some source locators contain Bubble index aliases rather than literal JSON
  paths; source-domain/source-key metadata and fragment hashes permit checking.
- Ready-state next actions use `query entity --key` although the command requires
  `--entity`; this was an outstanding command-hint defect in 0.2.0.
- Default-version entity retrieval can omit the resolved version label. Continue
  using explicit versions for multi-step investigations.
- Search can repeat canonical entities and rank deprecated-looking names highly.
  Candidate relevance still needs source and usage checks.

No CLI behavior was changed during this baseline acceptance run.

## Onboarding fixes — 0.2.1

Completed locally on 2026-11-07, using the unpublished working tree.

The patch corrects the command hints, pinned version metadata, canonical result
deduplication and source-locator aliases exposed by the baseline. Original
aliases and source hashes remain available. Name-only deprecation markers are
explicit hints rather than assertions of inactivity; exact and explicitly legacy
searches keep those candidates available.

Processing now reports elapsed heartbeats, graph substeps and actual write
counters, with transaction validation separate from committed work. Stage
fractions are labelled as stage progress rather than total work. A complete
index is verified and returned unchanged by `index resume`; inconsistent ready
counters are rejected rather than silently resetting vectors. Explicit
`index rebuild` retains its intentional rebuild behavior.

Verification:

- Ordinary suite: 98 passed, one opt-in native smoke skipped. The native
  synthetic smoke passed separately.
- Synthetic regressions cover new imports, aliased paths, reporter cleanup,
  delayed/failed database commits and cold library/model loading.
- An isolated installation of the 0.2.1 wheel passed nine preserved-index
  command cases: ready resume, default-version entity, ordinary and explicitly
  legacy search, canonical deduplication, usage, paths, bundle and status hints.
  A generated follow-up command was also executed successfully.
- The first semantic query emitted immediate and periodic stderr feedback
  during cold library/model loading; its stdout remained parseable JSON.
- Before/after database fingerprints and embedding timestamps matched exactly.
  No private reimport or embedding rebuild was needed. Installed Python/SQL
  files and the complete copied skill matched the tested source tree.
- The app-owned database was stopped; the private source and index were
  preserved. Detailed inputs, measurements and query results remain private.
- Independent follow-up review found no remaining material issues in the
  reviewed onboarding, retrieval, progress and command-hint changes.

The isolated patch installation used the prepared dependency cache and baseline
dependency constraints. It does not establish installation from an empty cache
or from the current public repository URL.

Full-index compute cost has not been removed: root-first indexing is a separate
future optimization, and no faster end-to-end processing claim is made here.

## Acceptance still required

- Additional private exports and `.bubble` files: parser coverage, source-locator
  handling, interruption recovery and retrieval relevance beyond this sample.
  Keep detailed logs and client-derived artifacts outside this repository.
- A fresh external agent session discovering and using the installed skill.
- Public remote bootstrap against the commit containing these changes, after
  publication. The current remote HEAD must not be assumed to include them.
- Linux runtime validation and the newly added GitHub CI jobs have not run as
  part of this local session. Native Windows/WSL are not validated targets.

The public repository contains no Bubble export JSON files. Synthetic input for
checks is generated within temporary test directories. The private acceptance
run does not add its source data, measurements or query results to this tree.
