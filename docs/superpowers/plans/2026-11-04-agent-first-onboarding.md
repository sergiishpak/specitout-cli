# Agent-first onboarding implementation plan

> Execute with test-first changes and a final independent review. User approved the design and autonomous execution; no further design approvals required.

**Goal:** Installable CLI and skill with private workspaces, measurable processing, and human-readable architecture documentation.
**Architecture:** Shared Python CLI; one native Postgres/pgvector data root per workspace. Existing global roots remain compatible.
**Tech stack:** Python 3.11+, argparse, Postgres, pgvector, sentence-transformers, Markdown and SVG.
**Spec:** ../specs/2026-11-04-agent-first-onboarding-design.md

## Global constraints

No shipped Bubble exports. No publishing or push. Private-export acceptance deferred until the user supplies its path. CLI and skill must use the same revision. New local version 0.2.0; not a published release.

## Review focus

Workspace scope conflicts and wrong-root stop; JSON errors and progress mixing; interrupted/resumed embedding work; installed skill outside source checkout; unsafe source copying and concurrent writers.

## Tasks

- [x] 1. Workspace lifecycle: tests for init/discovery/schema/scope/root conflicts, private source staging, mutation lock. Implement workspace.py plus passive diagnostics and scoped stop. Verify isolated temporary projects, paths with spaces, two-root separation.
- [x] 2. CLI integration: test --project/--version, manifest app default, all command JSON and error output, stderr progress, malformed exports before backend writes. Integrate existing argparse/services and runtime. Fix resume false success with a failing-backend regression test.
- [x] 3. Bootstrap and self-contained skill: installation from one pinned Git revision, complete skill copy and provenance, safe collision behavior, prerequisites, processing/recovery, bounded evidence, removal. Validate skill plus isolated install route.
- [x] 4. Human docs and two SVG diagrams: processing stack/measurement versus retrieval-augmented answering. Replace illustrative export with test-generated inputs. Add changelog and semantic release process, --version and lockfile synchronization.
- [x] 5. Verification: unit suite, wheel/installed package, synthetic Postgres flow, visual inspection, independent review/fixes. Record limitations for private real-export test.

## Execution notes

User authorized all reversible implementation details. Reuse current checkout; no commit/push requested. Parallelize documentation and self-contained skill authoring while core workspace/CLI changes proceed; no overlapping code ownership. Final review covers all changes.

## Rulings and verification ledger

- Reused the authorized current checkout; no commit/push/release publication.
- Human and skill documentation were delegated as independent scopes; core CLI
  changes and integration remained with the primary agent.
- Private source publication uses a temporary file and atomic no-overwrite link,
  preserving retryability after interruption; owned directory/file symlinks are rejected.
- Readers may inspect an already-running runtime during a writer's lock without
  attempting bootstrap or migrations. New bootstrap waits until ownership is free.
- Activation requires verified `ready` at the backend lifecycle boundary.
- Resume requires ready state rather than interpreting absent counts as zero.
- Unexpected exceptions produce a sanitized error envelope, with details retained
  in the selected private runtime's diagnostics.
- Bootstrap integration tests exercise pinned Git object copies and provenance;
  public remote installation of the new code remains pending publication.
- Full native smoke uses generated structure and deterministic 384-dimensional
  vectors: it validates lifecycle and retrieval plumbing, not semantic relevance.

- Final evidence: 31 passing pytest tests, one normal opt-in skip; installed-wheel
  native smoke passed separately; uv uninstall retained workspace files. Skill
  validator, link/SVG checks and review follow-up passed. See docs/validation.md.
