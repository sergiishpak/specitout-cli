"""Guard coordinated release metadata used by installers and the CLI."""
from pathlib import Path
import contextlib
import importlib.metadata
import io
import tomllib
import unittest

from specitout.app import main


class ReleaseVersionTest(unittest.TestCase):
    def test_installed_cli_version_matches_project_and_lock(self):
        root = Path(__file__).resolve().parents[1]
        version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
        lock = tomllib.loads((root / 'uv.lock').read_text())
        package = next(item for item in lock['package'] if item['name'] == 'specitout-cli')
        self.assertEqual(version, package['version'])
        self.assertEqual(version, importlib.metadata.version('specitout-cli'))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, main(['--version']))
        self.assertEqual(version, out.getvalue().strip())
        self.assertIn(f'## [{version}]', (root / 'CHANGELOG.md').read_text())
