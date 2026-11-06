"""Opt-in native-runtime integration; deterministic vectors test plumbing, not model quality."""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from specitout.app import main
from specitout.backend import PostgresLocalBackend
from specitout.runtime import AppOwnedPostgresRuntime
from specitout.workspace import select_project


@unittest.skipUnless(os.environ.get('SPECITOUT_TEST_POSTGRES') == '1', 'set SPECITOUT_TEST_POSTGRES=1 for a native Postgres/pgvector smoke test')
class NativeRuntimeSmokeTest(unittest.TestCase):
    def test_private_workspace_import_index_retrieve_and_stop(self):
        class UnavailableSocketDefaultRuntime(AppOwnedPostgresRuntime):
            def _run_command(self, argv, action):
                super()._run_command(argv, action)
                if Path(argv[0]).name == 'initdb':
                    cluster = Path(argv[argv.index('-D') + 1])
                    # Simulate a distro socket default unavailable to this user.
                    with (cluster / 'postgresql.conf').open('a') as config:
                        config.write("\nunix_socket_directories = '/dev/null/specitout-sockets'\n")

        class DeterministicEmbeddings:
            model_name = 'synthetic-test-vector'
            dimensions = 384
            batch_size = 2
            def embed_documents(self, texts):
                return [[1.0] + [0.0] * 383 for _ in texts]
            def embed_query(self, text):
                return self.embed_documents([text])[0]

        def backend():
            return PostgresLocalBackend(runtime_status=UnavailableSocketDefaultRuntime().ensure_ready(), embedding_provider_factory=DeterministicEmbeddings)

        with tempfile.TemporaryDirectory(prefix='specitout smoke ') as td:
            project = Path(td) / 'private app'
            source = Path(td) / 'synthetic.json'
            source.write_text(json.dumps({'pages': {'dispatch-key': {'id': 'dispatch', 'name': 'Dispatch board', 'type': 'Page'}}, 'user_types': {'work_order': {'name': 'WorkOrder', 'fields': {}}}, '_index': {'id_to_path': {'dispatch': '%p3.dispatch-key'}}}))
            def call(args):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main(['--project', str(project), *args, '--format', 'json'], backend_factory=backend)
                self.assertEqual(0, code, out.getvalue() + err.getvalue())
                return json.loads(out.getvalue()), err.getvalue()
            # Init has no --project because the manifest doesn't exist yet.
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(['project', 'init', str(project), '--app', 'smoke']))
            try:
                result, progress = call(['import', 'add', '--version', 'v1', '--export', str(source)])
                self.assertIn('elapsed=', progress)
                staged = Path(result['data']['source_export_path'])
                self.assertEqual(source.read_bytes(), staged.read_bytes())
                result, progress = call(['index', 'resume', '--version', 'v1', '--initial-limit', '2', '--min-limit', '1', '--max-passes', '10', '--sleep-seconds', '0'])
                self.assertEqual('ready', result['data']['state'])
                self.assertIn('embedded=', progress)
                # Monitoring must use the running runtime without bootstrap/migration writes.
                from specitout.workspace import READ_ONLY_RUNTIME, operation_lock
                token = READ_ONLY_RUNTIME.set(True)
                try:
                    with select_project(str(project)):
                        status = AppOwnedPostgresRuntime().ensure_ready()
                        self.assertEqual('previously-applied', status.migrations)
                finally:
                    READ_ONLY_RUNTIME.reset(token)
                call(['import', 'activate', '--version', 'v1'])
                result, _ = call(['query', 'search', '--query', 'Dispatch'])
                self.assertTrue(result['data']['results'])
                key = 'page:dispatch-board--dispatch-05b145cfb6'
                result, _ = call(['query', 'entity', '--entity', key])
                self.assertTrue(result['data']['evidence'])
                self.assertEqual('pages.dispatch-key', result['data']['entity']['source_path'])
                self.assertEqual('v1', result['scope']['version_label'])
                call(['query', 'usage', '--entity', key])
                result, _ = call(['bundle', 'build', '--entity', key, '--entity-limit', '3'])
                self.assertTrue(result['data']['entities'])
                self.assertLessEqual(len(result['data']['entities']), 3)
                result, _ = call(['index', 'resume', '--version', 'v1', '--max-passes', '1'])
                self.assertEqual(0, result['data']['passes'])
                result, _ = call(['runtime', 'stop'])
                self.assertEqual('stopped', result['data']['state'])
                self.assertTrue(source.is_file())
                self.assertTrue(staged.is_file())
            finally:
                with select_project(str(project)):
                    AppOwnedPostgresRuntime().stop()
