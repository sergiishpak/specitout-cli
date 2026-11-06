"""Translate Bubble's index aliases into paths in the original JSON export."""

import re

ROOT_ALIASES = {'%p3': 'pages', '%ed': 'element_definitions'}
COLLECTION_ALIASES = {'%wf': 'workflows', '%el': 'elements'}
EVIDENCE_PREFIXES = ('entity_source_path:', 'edge_evidence_path:', 'source:')
EVIDENCE_PATH_PATTERN = re.compile(r'((?:entity_source_path|edge_evidence_path|source):[ \t]*)([^\s;|,]+)')


def normalize_source_path(path, *, source_domain=None, source_key=None, root_aliases=None):
    if not isinstance(path, str):
        return path
    if path.startswith(EVIDENCE_PREFIXES):
        return EVIDENCE_PATH_PATTERN.sub(
            lambda match: match[1] + normalize_source_path(match[2], root_aliases=root_aliases),
            path,
        )
    value = path
    for alias, canonical in sorted((root_aliases or {}).items(), key=lambda item: len(item[0]), reverse=True):
        if value == alias or value.startswith(alias + '.'):
            value = canonical + value[len(alias):]
            break
    tokens = value.split('.')
    root = ROOT_ALIASES.get(tokens[0], tokens[0])
    if root not in {'pages', 'element_definitions', 'api', 'mobile_views'}:
        return value
    tokens[0] = root
    if root == source_domain and source_key is not None and len(tokens) == 2:
        tokens[1] = str(source_key)
    tokens = [COLLECTION_ALIASES.get(token, token) for token in tokens]
    return '.'.join(tokens)


def canonical_index_paths(data):
    """Use actual root dictionary keys even when index paths contain source IDs."""
    index = data.get('_index', {}).get('id_to_path', {})
    aliases = {}
    for alias, domain in ROOT_ALIASES.items():
        for key, raw in data.get(domain, {}).items():
            if not isinstance(raw, dict):
                continue
            source_id = str(raw.get('id') or key)
            canonical = f'{domain}.{key}'
            aliases[f'{alias}.{source_id}'] = canonical
            indexed_path = index.get(source_id)
            if isinstance(indexed_path, str) and len(indexed_path.split('.')) == 2:
                aliases[indexed_path] = canonical
    return {source_id: normalize_source_path(path, root_aliases=aliases) for source_id, path in index.items()}


def enrich_payload_source_paths(payload, *, root_aliases=None):
    """Return corrected retrieval evidence without modifying indexed data or content."""
    aliases = dict(root_aliases or {})

    def collect(value):
        if isinstance(value, list):
            for child in value:
                collect(child)
        elif isinstance(value, dict):
            metadata = value.get('structural_json')
            if not isinstance(metadata, dict):
                metadata = value
            domain, key = metadata.get('source_domain'), metadata.get('source_key')
            path = value.get('source_path') or metadata.get('source_path')
            if domain in ROOT_ALIASES.values() and key is not None and isinstance(path, str):
                if len(path.split('.')) == 2:
                    aliases[path] = f'{domain}.{key}'
            for name, child in value.items():
                if name not in {'normalized_payload', '_raw', 'raw_fragment', 'source_excerpt'}:
                    collect(child)

    def enrich(value):
        if isinstance(value, list):
            return [enrich(child) for child in value]
        if not isinstance(value, dict):
            if isinstance(value, str) and value.startswith((*EVIDENCE_PREFIXES, '%p3.', '%ed.')):
                return normalize_source_path(value, root_aliases=aliases)
            return value
        result = {}
        originals = {}
        for name, child in value.items():
            if name.endswith('_alias') or name in {'normalized_payload', '_raw', 'raw_fragment', 'source_excerpt'}:
                result[name] = child
                continue
            is_path = (
                name in {'source_path', 'evidence_path'}
                or name.endswith('_source_path')
                or (name == 'path' and value.get('kind') == 'source')
            )
            if is_path:
                result[name] = normalize_source_path(child, root_aliases=aliases)
                if result[name] != child:
                    originals[f'{name}_alias'] = child
            else:
                result[name] = enrich(child)
        for name, original in originals.items():
            result.setdefault(name, original)
        return result

    collect(payload)
    return enrich(payload)
