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

## Public URL installation — 2026-11-07

The documented bootstrap was tested against public commit
[`ed30cb75f0208fa83fa3a839f87675c5a77a4292`](https://github.com/sergiishpak/specitout-cli/commit/ed30cb75f0208fa83fa3a839f87675c5a77a4292),
with Git credentials disabled and separate, initially empty tool, package-cache,
skill and model-cache directories. The test ran outside the development checkout.
This closes the public-bootstrap gap recorded in the earlier local-wheel tests.

Verified on macOS with uv 0.11.3 and Python 3.12.13:

- Anonymous public clone, immutable revision selection, dry run and normal
  `uv tool install` from the public Git URL succeeded. No local wheel,
  dependency constraints or existing package cache was supplied.
- The CLI reported 0.2.1. Its installed VCS metadata and all five copied skill
  files matched the same commit; packaged SQL was present.
- A new workspace outside the clone initialized without Git or a running
  database. Passive diagnostics found the native prerequisites.
- A generated JSON-shaped `.bubble` export was imported, hash-verified and
  processed in a new native Postgres/pgvector runtime. The real local embedding
  model downloaded into an empty cache; all ten synthetic search documents
  received embeddings and the version became ready and active.
- Search used semantic retrieval without degradation. Entity, inbound usage,
  paths and bounded bundles returned source evidence, including the generated
  approval-to-notification workflow relationship. Ready resume took zero passes.
- Cold loading emitted immediate and periodic stderr feedback; stdout remained
  valid JSON. The synthetic test is not an application performance benchmark.
- Repeating the same pinned bootstrap reused the identical skill. The CLI and
  copied references worked after the installation checkout was moved away.
- The test database was stopped. Uninstalling the isolated CLI removed its
  executable and preserved the workspace, staged source, original synthetic
  export and skill. Existing private acceptance workspaces were untouched.

Python, uv and matching Postgres/extension binaries were already installed on
this Mac. This is not a clean operating-system provisioning test. The skill was
installed into an isolated test directory and used directly; discovery in a new
agent-host session remains unverified.

The [GitHub Checks run](https://github.com/sergiishpak/specitout-cli/actions/runs/42309579692)
also passed both Ubuntu Python 3.11 and 3.12 jobs: ordinary tests, package build,
and installed-wheel checks outside the checkout. Those jobs do not exercise the
native Linux Postgres runtime.

## Acceptance still required

- Additional private exports and `.bubble` files: parser coverage, source-locator
  handling, interruption recovery and retrieval relevance beyond this sample.
  Keep detailed logs and client-derived artifacts outside this repository.
- A fresh external agent session discovering and using the installed skill.
- Provisioning native prerequisites on a clean operating system and native
  Linux runtime validation. Native Windows/WSL are not validated targets.

The public repository contains no Bubble export JSON files. Synthetic input for
checks is generated within temporary test directories. The private acceptance
run does not add its source data, measurements or query results to this tree.
