# Retrieve bounded evidence and answer

Check import/index readiness for the intended workspace/version first. Querying may start the local runtime. Always pass the explicit version during a multi-step investigation so activation changes cannot mix snapshots.

## Find anchors, then verify relationships

```sh
specitout --project "/absolute/private/my-app" query search --version v1 --query "Order status" --limit 5 --format json
specitout --project "/absolute/private/my-app" query entity --version v1 --entity "ENTITY_KEY" --format json
specitout --project "/absolute/private/my-app" query usage --version v1 --entity "ENTITY_KEY" --direction inbound --limit 20 --format json
specitout --project "/absolute/private/my-app" query usage --version v1 --entity "ENTITY_KEY" --direction outbound --limit 20 --format json
```

Use returned canonical identifiers in subsequent calls. Exact identifiers and lexical matches often suffice; semantic matches help find candidates when names differ. A search hit is an anchor, not proof of a relationship or business intent. Check canonical entity details and graph edges. When a root search misses necessary nested surfaces, try `--mode deep` and explain why scope expanded.

Search can take time while the embedding library loads. If the execution tool
returns a running session, wait/poll until the command exits and its JSON result
is available before issuing a dependent lookup. Empty output from a running
command is not an empty search result.

Copy `data.results[].entity_key` verbatim into `--entity`, `--from` and `--to`.
A raw Bubble ID or an invented `workflow:ID` string is not a canonical key. If a
lookup fails, return to search and copy its key rather than guessing another
format. Ordinary investigation uses the CLI; direct SQL is unnecessary for
resolving names or tracing relationships.

```sh
specitout --project "/absolute/private/my-app" query paths --version v1 --from "ENTITY_A" --to "ENTITY_B" --max-hops 3 --max-paths 3 --format json
specitout --project "/absolute/private/my-app" bundle build --version v1 --entity "ENTITY_KEY" --max-hops 1 --entity-limit 20 --edge-limit 30 --format json
```

Read returned evidence, source locators, unresolved references, degradation indicators, and truncation/limit metadata where provided. Widen one bound deliberately when the current result cannot answer the question. Never describe a bounded empty path result as proof that no connection exists.

## Question families and limits

| Question | Retrieval approach | Answer boundary |
| --- | --- | --- |
| What writes this field? | Field anchor, inbound usage, candidate workflow/action entities and source evidence | Describe observed write candidates; dynamic/unresolved expressions can prevent completeness. |
| What depends on this workflow? | Canonical workflow, inbound usage; bounded paths for indirect dependencies | Label graph direction, depth, and omitted/unresolved surfaces. |
| Which pages use this component? | Component anchor, inbound usage, page/entity evidence | Distinguish direct references and inferred transitive use. |
| How are two entities connected? | Canonical anchors and bounded `query paths` | Report returned paths and traversal bounds. |
| What matters for a proposed migration? | Search anchors, graph neighborhoods, source-backed bundle | Present evidenced dependencies and unknowns; do not guarantee migration safety. |

These are investigation recipes over available CLI surfaces, not claims of exhaustive write analysis or complete Bubble semantics. Report incomplete embeddings/degraded retrieval; absence in a partial index is weak evidence. Exact/graph inspection can remain useful while vectors are unavailable.

Answers should identify application/version, a direct conclusion, supporting entity keys/source locators, and the limitations that change the conclusion. Distinguish observed export structure from inferred business meaning. Export state does not prove live production behavior, actual users/traffic, external API behavior, runtime timing, access correctness, or a safe deployment. Unsupported surfaces require source review or explicitly authorized validation outside this tool. Never fabricate source locations or cite vector similarity as source evidence.

## Provenance and candidate hints

Every retrieval response identifies the resolved version and export ID. Continue
passing the explicit version during a multi-command investigation. Source paths
are normalized for both new and existing indexes; `*_alias` metadata preserves
original index aliases. Source fragments and hashes are unchanged.

Search deduplicates canonical entities and merges evidence from their matching
documents, with a bounded 25-document candidate pool. Inspect warnings when that
cap prevents filling the requested number of unique entities; refine the query.
Leading deprecation-name markers are deprioritized in ordinary discovery and
exposed as `name_hints`. A question mark is uncertain, and names alone never prove
runtime inactivity. Exact names/keys or an explicit request for deprecated
workflows retain those candidates. Scores are original retrieval scores; name
hints explain discovery order rather than recalibrating the scores.
