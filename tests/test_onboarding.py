from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from specitout.app import main
from specitout.index_resume import resume_index
from specitout.runtime_errors import SpecItOutRuntimeError


class OnboardingTest(unittest.TestCase):
    def call(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_project_init_discovery_and_scope_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / 'my app'
            code, out, err = self.call(['project', 'init', str(project), '--app', 'demo', '--format', 'json'])
            self.assertEqual(0, code, err)
            self.assertTrue((project / 'specitout.toml').is_file())
            from specitout.workspace import discover_project
            nested = project / 'reports' / 'nested'
            nested.mkdir()
            self.assertEqual('demo', discover_project(nested).app_slug)
            code, out, err = self.call(['--project', str(project), 'query', 'entity', '--app', 'other', '--entity', 'x', '--format', 'json'])
            self.assertEqual(1, code)
            self.assertEqual('error', json.loads(out)['status'])
            self.assertIn('scope', json.loads(out)['error'].lower())

    def test_project_conflicting_root_and_unsupported_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / 'app'
            self.assertEqual(0, self.call(['project', 'init', str(project), '--app', 'demo'])[0])
            with patch.dict(os.environ, {'SPECITOUT_DATA_ROOT': str(Path(td) / 'wrong')}):
                code, out, _ = self.call(['--project', str(project), 'doctor', '--format', 'json'])
                self.assertEqual(1, code)
                self.assertIn('SPECITOUT_DATA_ROOT', json.loads(out)['error'])
            (project / 'specitout.toml').write_text('schema_version = 999\napp_slug = "demo"\n')
            self.assertEqual(1, self.call(['--project', str(project), 'doctor', '--format', 'json'])[0])

    def test_doctor_does_not_bootstrap_database(self):
        with tempfile.TemporaryDirectory() as td:
            self.call(['project', 'init', td, '--app', 'demo'])
            code, out, _ = self.call(['--project', td, 'doctor', '--format', 'json'])
            self.assertIn(code, (0, 2))
            self.assertEqual('doctor', json.loads(out)['command'])
            self.assertFalse((Path(td) / '.specitout' / 'postgres').exists())

    def test_json_validation_error_has_no_text_on_stdout(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'SPECITOUT_DATA_ROOT': td}):
            code, out, err = self.call(['query', 'search', '--app', 'demo', '--query', 'x', '--limit', '0', '--format', 'json'])
        self.assertEqual(1, code)
        self.assertEqual('error', json.loads(out)['status'])
        self.assertEqual('', err)
        self.assertIn('--limit', json.loads(out)['error'])

    def test_workspace_source_copy_and_reuse_without_overwrite(self):
        from specitout.workspace import init_project, stage_export
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = init_project(root / 'workspace', 'demo')
            source = root / 'original.json'
            source.write_text('{"pages":{"p":{"name":"Demo"}}}')
            staged = stage_export(project, source, 'v1')
            self.assertNotEqual(source, staged)
            self.assertEqual(source.read_bytes(), staged.read_bytes())
            self.assertEqual(staged, stage_export(project, source, 'v1'))
            source.write_text('{"pages":{"p":{"name":"Changed"}}}')
            with self.assertRaises(SpecItOutRuntimeError):
                stage_export(project, source, 'v1')
            self.assertIn('Demo', staged.read_text())

    def test_bad_export_rejected_before_backend_creation(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'bad.json'
            path.write_text('{"pages": []}')
            def backend():
                self.fail('invalid export reached database creation')
            with patch.dict(os.environ, {'SPECITOUT_DATA_ROOT': str(Path(td) / 'runtime')}), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main(['import', 'add', '--app', 'demo', '--version', 'v1', '--export', str(path)], backend_factory=backend)
            self.assertEqual(1, code)

    def test_resume_failure_without_counters_is_not_ready(self):
        class Broken:
            def rebuild_index(self, **kwargs):
                raise SpecItOutRuntimeError('model unavailable')
        result = resume_index(Broken(), app_slug='demo', version_label='v1', initial_limit=16, min_limit=16, max_passes=2, stuck_pass_threshold=1, sleep_seconds=0)
        self.assertNotEqual('ready', result['state'])
        self.assertEqual('model unavailable', result['last_error'])

    def test_resume_stale_zero_does_not_override_failure(self):
        class Broken:
            def rebuild_index(self, **kwargs):
                return {'readiness_status':'embedding_pending', 'stats':{'remaining_documents':0}}
        result = resume_index(Broken(), app_slug='demo', version_label='v1', initial_limit=16, min_limit=16, max_passes=1, stuck_pass_threshold=1, sleep_seconds=0)
        self.assertNotEqual('ready', result['state'])


if __name__ == '__main__':
    unittest.main()

class WorkspaceBoundaryTest(unittest.TestCase):
    def test_lock_blocks_another_process_and_releases_after_exit(self):
        import subprocess
        import sys
        from specitout.workspace import operation_lock
        with tempfile.TemporaryDirectory() as td:
            script = 'from pathlib import Path; from specitout.workspace import operation_lock;\nwith operation_lock(Path(__import__("sys").argv[1])): print("acquired")'
            with operation_lock(Path(td)):
                result = subprocess.run([sys.executable, '-c', script, td], capture_output=True, text=True)
                self.assertNotEqual(0, result.returncode)
                self.assertIn('another command', result.stderr)
            result = subprocess.run([sys.executable, '-c', script, td], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_missing_project_app_reaches_backend_with_manifest_scope(self):
        from specitout.workspace import init_project
        with tempfile.TemporaryDirectory() as td:
            init_project(td, 'demo')
            class Backend:
                def get_application(self, *, app_slug):
                    if app_slug != 'demo':
                        raise AssertionError(app_slug)
                    return {"slug":"demo", "display_name":"Demo", "active_export_version":None}
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(['--project', td, 'app', 'show', '--format', 'json'], backend_factory=Backend)
            self.assertEqual(0, code)
            self.assertEqual('demo', json.loads(out.getvalue())['scope']['app_slug'])

    def test_uninitialized_stop_preserves_sources_and_does_not_bootstrap(self):
        from specitout.workspace import init_project
        with tempfile.TemporaryDirectory() as td:
            init_project(td, 'demo')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(['--project', td, 'runtime', 'stop', '--format', 'json'])
            self.assertEqual(0, code)
            self.assertEqual('not_initialized', json.loads(out.getvalue())['data']['state'])
            self.assertFalse((Path(td) / '.specitout' / 'postgres').exists())

    def test_global_json_format_is_preserved_for_lifecycle_command(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(out):
            code = main(['--format', 'json', 'project', 'init', td, '--app', 'demo'])
        self.assertEqual(0, code)
        self.assertEqual('project init', json.loads(out.getvalue())['command'])

class RecoveryBoundaryTest(unittest.TestCase):
    def test_interrupted_copy_is_removed_and_same_version_can_retry(self):
        from specitout.workspace import init_project, stage_export
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = init_project(root / 'app', 'demo')
            source = root / 'source.json'
            source.write_text('{"pages":{"p":{"name":"Demo"}}}')
            def interrupted(src, dst):
                dst.write(b'{"pag')
                raise KeyboardInterrupt()
            with patch('specitout.workspace.shutil.copyfileobj', interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    stage_export(project, source, 'v1')
            self.assertFalse((project.root / 'exports' / 'v1.json').exists())
            self.assertEqual(source.read_bytes(), stage_export(project, source, 'v1').read_bytes())

    def test_activation_rejects_partial_embeddings_before_transaction(self):
        from specitout.backend_lifecycle import activate_import
        def fetch_one(query, params):
            if 'specitout.apps' in query:
                return {'id':'app', 'slug':'demo'}
            return {'id':'export', 'version_label':'v1', 'readiness_status':'embedding_pending'}
        def connect():
            self.fail('incomplete export reached activation transaction')
        with self.assertRaises(SpecItOutRuntimeError):
            activate_import(connect=connect, fetch_one=fetch_one, app_slug='demo', version_label='v1')

class WorkspaceIsolationTest(unittest.TestCase):
    def test_owned_symlink_cannot_route_sources_outside_workspace(self):
        from specitout.workspace import init_project
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / 'app'
            project.mkdir()
            external = root / 'external'
            external.mkdir()
            (project / 'exports').symlink_to(external, target_is_directory=True)
            with self.assertRaises(SpecItOutRuntimeError):
                init_project(project, 'demo')

    def test_existing_evidence_symlink_is_not_reused(self):
        from specitout.workspace import init_project, stage_export
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = init_project(root / 'app', 'demo')
            source = root / 'original.json'
            source.write_text('{"pages":{}}')
            (project.root / 'exports' / 'v1.json').symlink_to(source)
            with self.assertRaises(SpecItOutRuntimeError):
                stage_export(project, source, 'v1')

    def test_status_can_read_while_mutation_lock_is_held(self):
        from specitout.workspace import init_project, operation_lock
        with tempfile.TemporaryDirectory() as td:
            project = init_project(td, 'demo')
            class Backend:
                def import_status(self, **kwargs):
                    return {'status':'ok', 'command':'import status', 'scope':{'app_slug':'demo','version_label':'v1'}, 'data':{'state':'embedding_pending', 'app':{'slug':'demo'}, 'export':{'id':'export','version_label':'v1','readiness_status':'embedding_pending','lifecycle_status':'candidate'}, 'active_export':None, 'pipeline_run':None, 'embedding_stats':{'total_documents':6,'embedded_documents':2,'remaining_documents':4}}, 'warnings':[], 'degraded':False, 'next_actions':[]}
            # A subprocess owns the actual OS lock, so nested same-context lock reuse cannot hide contention.
            import subprocess, sys
            child = subprocess.Popen([sys.executable, '-c', 'from pathlib import Path; from specitout.workspace import operation_lock; import sys;\nwith operation_lock(Path(sys.argv[1])):\n print("locked", flush=True); sys.stdin.readline()', str(project.data_root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual('locked', child.stdout.readline().strip())
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = main(['--project', td, 'import', 'status', '--version', 'v1', '--format', 'json'], backend_factory=Backend)
                self.assertEqual(0, code, out.getvalue())
            finally:
                child.communicate('\n', timeout=5)

class ExportValidationTest(unittest.TestCase):
    def test_registry_array_is_rejected_before_backend_creation(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "malformed.json"
            source.write_text('{"pages":{},"styles":[]}')
            def backend():
                self.fail("malformed registry reached database")
            out = io.StringIO()
            with patch.dict(os.environ, {"SPECITOUT_DATA_ROOT": str(Path(td) / "runtime")}), contextlib.redirect_stdout(out):
                code = main(["import", "add", "--app", "demo", "--version", "v1", "--export", str(source), "--format", "json"], backend_factory=backend)
            self.assertEqual(1, code)
            self.assertEqual("error", json.loads(out.getvalue())["status"])

class ErrorEnvelopeTest(unittest.TestCase):
    def test_unexpected_backend_error_is_structured_without_private_contents(self):
        class Backend:
            def get_application(self, **kwargs):
                raise AttributeError('private export fragment')
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'SPECITOUT_DATA_ROOT': td}):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(['app', 'show', '--app', 'demo', '--format', 'json'], backend_factory=Backend)
            self.assertEqual(1, code)
            self.assertEqual('error', json.loads(out.getvalue())['status'])
            self.assertNotIn('private export fragment', out.getvalue() + err.getvalue())
