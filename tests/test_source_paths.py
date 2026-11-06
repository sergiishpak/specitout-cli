from copy import deepcopy

from bubble_context_pack_internal.builder import ContextPackBuilder
from bubble_context_pack_internal.source_paths import (
    enrich_payload_source_paths,
    normalize_source_path,
)


def test_alias_tokens_become_export_paths_without_rewriting_names():
    assert normalize_source_path('%p3.page-key.%el.node.%wf.flow.actions.action') == (
        'pages.page-key.elements.node.workflows.flow.actions.action'
    )
    assert normalize_source_path('%ed.component-key.elements.child') == 'element_definitions.component-key.elements.child'
    assert normalize_source_path('pages.page-key.properties.%other') == 'pages.page-key.properties.%other'
    assert normalize_source_path('notes/%p3.page-key.md') == 'notes/%p3.page-key.md'


def test_existing_entity_metadata_anchors_root_key_and_nested_evidence():
    payload = {
        'entity': {
            'source_path': '%p3.page-id',
            'structural_json': {'source_domain': 'pages', 'source_key': 'page-key'},
            'raw_fragment_hash': 'keep-hash',
        },
        'edges': [{
            'from_source_path': '%p3.page-id',
            'evidence_path': '%p3.page-id.%el.child.properties.value',
        }],
        'evidence_links': [
            {'kind': 'entity_source_path', 'source_path': '%p3.page-id'},
            {'kind': 'source', 'path': '%p3.page-id.%el.child'},
            'entity_source_path:%p3.page-id',
            '%p3.page-id.%wf.flow',
        ],
    }
    original = deepcopy(payload)
    result = enrich_payload_source_paths(payload)
    assert result['entity']['source_path'] == 'pages.page-key'
    assert result['entity']['source_path_alias'] == '%p3.page-id'
    assert result['entity']['raw_fragment_hash'] == 'keep-hash'
    assert result['edges'][0]['evidence_path'] == 'pages.page-key.elements.child.properties.value'
    assert result['edges'][0]['from_source_path'] == 'pages.page-key'
    assert result['evidence_links'][0]['source_path'] == 'pages.page-key'
    assert result['evidence_links'][1]['path'] == 'pages.page-key.elements.child'
    assert result['evidence_links'][2] == 'entity_source_path:pages.page-key'
    assert result['evidence_links'][3] == 'pages.page-key.workflows.flow'
    assert payload == original
    assert enrich_payload_source_paths(result) == result


def test_response_content_and_overlay_paths_are_preserved():
    payload = {
        'source_path': '%ed.card',
        'normalized_payload': {'source_path': '%p3.this-is-source-data'},
        'evidence_links': [{'kind': 'overlay', 'path': 'docs/%p3.card.md'}],
        'description': 'A source mentions %p3.card',
    }
    result = enrich_payload_source_paths(payload)
    assert result['source_path'] == 'element_definitions.card'
    assert result['normalized_payload'] == payload['normalized_payload']
    assert result['evidence_links'] == payload['evidence_links']
    assert result['description'] == payload['description']


def test_formatted_evidence_strings_preserve_spacing_and_delimiters():
    original = {
        'entity': {'source_path': '%p3.page-id', 'source_domain': 'pages', 'source_key': 'page-key'},
        'evidence': [
            'entity_source_path: %p3.page-id; source: %p3.page-id',
            'edge_evidence_path: %p3.page-id.%el.child',
            'source:  %ed.card; edge_evidence_path:\t%p3.page-id.%wf.flow',
        ],
    }
    payload = deepcopy(original)
    result = enrich_payload_source_paths(payload)
    assert result['evidence'] == [
        'entity_source_path: pages.page-key; source: pages.page-key',
        'edge_evidence_path: pages.page-key.elements.child',
        'source:  element_definitions.card; edge_evidence_path:\tpages.page-key.workflows.flow',
    ]
    assert normalize_source_path('entity_source_path: %p3.page-id; source: %p3.page-id') == (
        'entity_source_path: pages.page-id; source: pages.page-id'
    )
    assert enrich_payload_source_paths(result) == result
    assert payload == original


def test_import_paths_use_export_keys_and_keep_virtual_nodes(tmp_path):
    data = {
        'pages': {
            'page-key': {'id': 'page-id', 'name': 'Synthetic page', 'elements': {
                'child': {'id': 'child', 'type': 'Text', 'name': 'Synthetic child'},
            }, 'workflows': {'flow': {'id': 'flow', 'type': 'ButtonClicked', 'actions': {
                'action': {'id': 'action', 'type': 'SetState'},
            }}}},
        },
        'element_definitions': {'card-key': {'id': 'card-id', 'name': 'Synthetic card'}},
        '_index': {'id_to_path': {
            'page-id': '%p3.page-id',
            'child': '%p3.page-id.%el.child',
            'flow': '%p3.page-id.%wf.flow',
            'action': '%p3.page-id.%wf.flow.actions.action',
            'card-id': '%ed.card-id',
        }},
    }
    builder = ContextPackBuilder(
        tmp_path / 'synthetic.json', tmp_path / 'pack', tmp_path,
        app_slug='synthetic', export_loader=lambda path: data,
    )
    builder.collect_entities()
    builder.register_virtual_nodes_from_index()
    entities = {item['source_id']: item for item in builder.entities}
    assert entities['page-id']['source_path'] == 'pages.page-key'
    assert entities['card-id']['source_path'] == 'element_definitions.card-key'
    assert entities['child']['source_path'] == 'pages.page-key.elements.child'
    assert entities['child']['entity_type'] == 'page_node'
    assert entities['flow']['source_path'] == 'pages.page-key.workflows.flow'
    assert entities['flow']['entity_type'] == 'ui_workflow'
    assert entities['action']['source_path'] == 'pages.page-key.workflows.flow.actions.action'
    assert entities['action']['entity_type'] == 'workflow_action'
    assert entities['child']['_raw'] == data['pages']['page-key']['elements']['child']
    assert data['_index']['id_to_path']['child'] == '%p3.page-id.%el.child'


def test_import_root_without_index_uses_key_not_id(tmp_path):
    builder = ContextPackBuilder(
        tmp_path / 'synthetic.json', tmp_path / 'pack', tmp_path,
        app_slug='synthetic', export_loader=lambda path: {
            'pages': {'named-key': {'id': 'different-id', 'name': 'Synthetic page'}},
        },
    )
    builder.collect_entities()
    assert builder.entities[0]['source_path'] == 'pages.named-key'
