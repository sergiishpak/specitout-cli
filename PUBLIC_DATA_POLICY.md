# Public-data policy

This repository is a public technical demonstration. It must never become a
storage location for a client's Bubble export, database extract, generated
knowledge pack, credentials, internal notes, screenshots, or operational data.

## Allowed

- Generic source code, migration code, and tests.
- Documentation that describes architecture, decisions, limitations, and
  reproducible commands without referring to a real client or export.
- Fictional examples created specifically for this repository.

## Prohibited

- Real exports, including partially redacted exports and their derived schema,
  workflow, privacy, search, embedding, or evidence artifacts.
- API keys, tokens, connection strings, credentials, and `.env` files.
- Names, identifiers, URLs, paths, screenshots, comments, or records that can
  identify a client, product, employee, customer, or internal workflow.
- Agent memories, temporary diagnostics, local runtime databases, and generated
  query results.

## Contribution rule

Use a client export only from an ignored local directory. Before any commit,
run the publication checks described in the README. A contribution that cannot
be demonstrated with synthetic input does not belong in this repository.
