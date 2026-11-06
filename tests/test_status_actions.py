import shlex
import unittest
from specitout.app import build_parser
from specitout.status_actions import status_next_actions


class StatusActionsTest(unittest.TestCase):
    def test_ready_entity_hint_uses_supported_flag_and_known_scope(self):
        actions = status_next_actions(readiness_state='ready', is_active=False, degraded=False, app_slug='demo', version_label='release 1')
        entity = next(x for x in actions if x.startswith('query entity'))
        self.assertIn('--entity', entity)
        self.assertNotIn('--key', entity)
        args = build_parser().parse_args(shlex.split(entity.replace('<entity-key>', 'entity:demo')))
        self.assertEqual('demo', args.app_slug)
        self.assertEqual('release 1', args.version_label)
        self.assertEqual('entity:demo', args.entity_lookup)

    def test_partial_versions_recommend_resume_not_activation(self):
        for state in ('registered','ingesting','searchable','embedding_pending','degraded','failed'):
            actions = status_next_actions(readiness_state=state, is_active=False, degraded=state in {'failed','degraded'}, app_slug='demo', version_label='v1')
            self.assertFalse(any(x.startswith('import activate') for x in actions), actions)
            self.assertTrue(any(x.startswith('index resume' if state in {'ingesting','searchable','embedding_pending','degraded'} else 'import retry') for x in actions), actions)
            self.assertTrue(all('<app-slug>' not in x and '<version>' not in x for x in actions))


class BoundActionTest(unittest.TestCase):
    def test_workspace_and_quoted_scope_are_preserved_in_actual_parser(self):
        from pathlib import Path
        from specitout.workspace import Workspace
        from specitout.status_actions import resolve_action_hints
        envelope = {'scope': {'app_slug': 'demo', 'version_label': 'release 1'},
                    'next_actions': ["query entity --app '<app-slug>' --version '<version>' --entity '<entity-key>'"]}
        result = resolve_action_hints(envelope, Workspace(Path('/tmp/private app'), 'demo'))
        args = build_parser().parse_args(shlex.split(result['next_actions'][0]))
        self.assertEqual('/tmp/private app', args.project)
        self.assertEqual('release 1', args.version_label)
        self.assertEqual('<entity-key>', args.entity_lookup)

    def test_running_import_offers_monitoring_not_competing_work(self):
        actions = status_next_actions(readiness_state='ingesting', is_active=False,
                                      degraded=False, app_slug='demo', version_label='v1', pipeline_status='running')
        self.assertEqual(1, len(actions))
        args = build_parser().parse_args(shlex.split(actions[0]))
        self.assertEqual('status', args.import_command)


    def test_followup_queries_pin_current_version_and_have_required_query_input(self):
        from specitout.status_actions import resolve_action_hints
        envelope = {'scope': {'app_slug': 'demo', 'version_label': 'v1'},
                    'next_actions': ['query search --app <app-slug>']}
        action = resolve_action_hints(envelope)['next_actions'][0]
        args = build_parser().parse_args(shlex.split(action))
        self.assertEqual('v1', args.version_label)
        self.assertEqual('<query-text>', args.query_text)


    def test_new_import_does_not_reuse_current_version_automatically(self):
        from specitout.status_actions import resolve_action_hints
        envelope = {'scope': {'app_slug': 'demo', 'version_label': 'v1'},
                    'next_actions': ['import add --app <app-slug> --version <version> --export <path>']}
        args = build_parser().parse_args(shlex.split(resolve_action_hints(envelope)['next_actions'][0]))
        self.assertEqual('demo', args.app_slug)
        self.assertEqual('<version>', args.version_label)


def test_successful_import_hints_preserve_quoted_version(tmp_path):
    import json
    from specitout.services import ImportService
    source = tmp_path / 'synthetic.json'
    source.write_text(json.dumps({'pages': {}}))
    version = "Bob's release"
    export = {'id': 'export', 'version_label': version, 'readiness_status': 'ready', 'is_active': True}
    class Backend:
        def register_import(self, **kwargs):
            return {'created': False, 'app': {'slug': 'demo'}, 'export': export, 'active_export': export}
        def import_status(self, **kwargs):
            return {'data': {'export': export, 'pipeline_run': None}}
    envelope = ImportService(Backend).add(app_slug='demo', version_label=version,
        export_path=str(source), display_name=None, source_system='bubble', external_app_id=None)
    from specitout.status_actions import resolve_action_hints
    for action in resolve_action_hints(envelope)['next_actions']:
        args = build_parser().parse_args(shlex.split(action))
        assert args.version_label == version
