# SpecItOut CLI

SpecItOut is a local-first Python CLI and ingestion pipeline for making a
complex Bubble application export inspectable by a developer or coding agent.
It turns structural application information into explicit entities,
relationships, source evidence, search documents, and bounded context bundles.

The point is not to paste a huge export into an LLM context window. The point
is to let a question retrieve the relevant structural evidence: an exact
identifier, lexical matches, semantic matches, connected entities, and the
source fragments that support an answer.

## What this repository demonstrates

- Export-oriented analysis rather than manual page-by-page reconstruction.
- A normalized application model with entities, edges, source evidence, and
  explicit relationship traversal.
- Exact, lexical, and semantic retrieval as complementary tools, rather than a
  vector-only system.
- Bounded context bundles so an agent receives relevant evidence instead of an
  uncontrolled export dump.
- A local, app-owned Postgres runtime and CLI surface suitable for agent tools
  or human investigation.

This is a technical demonstration of the approach and implementation. It is
not a hosted service, a guarantee that every Bubble export imports without
adaptation, or a claim that autonomous agents should modify application truth.

## Architecture

```text
Bubble export
    -> source bundle and normalization
    -> entities + relationships + source evidence
    -> Postgres / pgvector search surfaces
    -> exact, lexical, semantic, and bounded graph retrieval
    -> CLI response for a human or coding agent
```

The source evidence remains important. Semantic search helps locate relevant
material; it does not replace the application's actual structure or invent a
business rule.

## Local use

Requirements: Python 3.11+, Postgres with pgvector, and `uv`.

```bash
uv sync
uv run specitout --help
```

The runtime is local and expects a controlled Postgres environment. See the
CLI help and runtime migration files for the commands and schema ownership.
Use your own export from an ignored local path; do not commit it.

`examples/fictional-operations-app.json` is intentionally fictional and small.
It exists to show the kind of domain complexity the model preserves—roles,
workflow rules, states, relationships, and conditional UI—not to represent a
complete Bubble export.

## Agent use

An agent should use this system to investigate evidence, not to silently write
company facts. A good request is narrow: identify the workflows that write a
field, trace a page to a backend action, or assemble a bounded context bundle
for a migration task. Important conclusions should retain source references and
remain reviewable by a human.

## Publication and data boundary

This repository contains no client exports or derived client artifacts. The
rules are in [PUBLIC_DATA_POLICY.md](PUBLIC_DATA_POLICY.md).

Before publishing any update, run:

```bash
git grep -n -i -E 'AIza[0-9A-Za-z_-]{35}|sk-(proj-)?[A-Za-z0-9_-]{20,}'
git fsck --full
python -m unittest discover -s tests -v
```

Run a dedicated secret scanner in CI as well. The local checks complement; they
do not replace, an all-history secret scan before a release.
