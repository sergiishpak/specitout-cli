"""Offline bootstrap integration tests; no tool or skill reaches the user's home."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap_specitout.py"
REPO_URL = "https://example.com/team/specitout.git"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def install_fixture(tmp_path):
    repo = tmp_path / "source checkout"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "remote", "add", "origin", REPO_URL)
    skill = repo / "skills" / "specitout"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: specitout\ndescription: Analyze exports.\n---\n")
    (skill / "references" / "investigate.md").write_text("Fixture reference\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture")
    revision = git(repo, "rev-parse", "HEAD")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text("#!/usr/bin/env python3\nimport json, os, sys\nfrom pathlib import Path\nPath(os.environ['FAKE_UV_LOG']).write_text(json.dumps(sys.argv[1:]))\nsys.exit(int(os.environ.get('FAKE_UV_EXIT', '0')))\n")
    uv.chmod(0o755)
    log = tmp_path / "uv-call.json"
    env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ['PATH'], FAKE_UV_LOG=str(log))
    destination = tmp_path / "host skills"

    def run(*extra, revision_override=None, repo_override=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--checkout", str(repo), "--repo-url", repo_override or REPO_URL,
             "--revision", revision_override or revision, "--skill-dir", str(destination), *extra],
            env=env, text=True, capture_output=True,
        )
    return repo, skill, revision, destination, log, env, run


def test_dry_run_has_no_side_effects(install_fixture):
    repo, skill, revision, destination, log, env, run = install_fixture
    result = run("--dry-run")
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan['revision'] == revision
    assert plan['cli_command'] == ['uv', 'tool', 'install', '--force', 'git+' + REPO_URL + '@' + revision]
    assert not destination.exists()
    assert not log.exists()


def test_installs_complete_pinned_skill_and_cli_with_provenance(install_fixture):
    repo, skill, revision, destination, log, env, run = install_fixture
    # An untracked file must not travel with the committed skill.
    (skill / "private.txt").write_text("not distributable")
    result = run()
    assert result.returncode == 0, result.stderr
    installed = destination / "specitout"
    assert (installed / 'references' / 'investigate.md').read_bytes() == (skill / 'references' / 'investigate.md').read_bytes()
    assert not (installed / 'private.txt').exists()
    provenance = json.loads((installed / '.specitout-install.json').read_text())
    assert provenance['repository'] == REPO_URL
    assert provenance['revision'] == revision
    assert json.loads(log.read_text()) == ['tool', 'install', '--force', 'git+' + REPO_URL + '@' + revision]
    shutil.rmtree(repo)
    assert (installed / 'references' / 'investigate.md').is_file()


def test_modified_or_foreign_skill_refuses_before_uv(install_fixture):
    repo, skill, revision, destination, log, env, run = install_fixture
    assert run().returncode == 0
    log.unlink()
    target = destination / 'specitout' / 'SKILL.md'
    target.write_text('User edits')
    result = run()
    assert result.returncode != 0
    assert 'existing skill' in result.stderr.lower()
    assert target.read_text() == 'User edits'
    assert not log.exists()


def test_identical_reinstall_is_allowed_but_added_files_are_preserved(install_fixture):
    repo, skill, revision, destination, log, env, run = install_fixture
    assert run().returncode == 0
    assert run().returncode == 0
    log.unlink()
    (destination / 'specitout' / 'notes.md').write_text('User notes')
    assert run().returncode != 0
    assert not log.exists()
    assert (destination / 'specitout' / 'notes.md').read_text() == 'User notes'


def test_bad_pin_or_repo_rejected_before_changes(install_fixture):
    repo, skill, revision, destination, log, env, run = install_fixture
    assert run(revision_override='main').returncode != 0
    assert run(revision_override='0' * 40).returncode != 0
    assert run(repo_override='https://example.com/other.git').returncode != 0
    assert run(repo_override='https://example.com/repo.git;touch owned').returncode != 0
    assert not destination.exists()
    assert not log.exists()


def test_failed_cli_install_does_not_install_skill(install_fixture):
    repo, skill, revision, destination, log, env, run = install_fixture
    env['FAKE_UV_EXIT'] = '7'
    result = run()
    assert result.returncode != 0
    assert not (destination / 'specitout').exists()


def test_symlink_skill_and_destination_rejected(install_fixture, tmp_path):
    repo, skill, revision, destination, log, env, run = install_fixture
    destination.mkdir()
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (destination / 'specitout').symlink_to(elsewhere, target_is_directory=True)
    assert run().returncode != 0
    assert not log.exists()
    (destination / 'specitout').unlink()
    (skill / 'external').symlink_to(elsewhere, target_is_directory=True)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'symlink')
    assert run(revision_override=git(repo, 'rev-parse', 'HEAD')).returncode != 0
    assert not log.exists()


def test_upgrade_refuses_existing_revision_before_cli_change(install_fixture):
    repo, skill, revision, destination, log, env, run = install_fixture
    assert run().returncode == 0
    log.unlink()
    (skill / 'references' / 'investigate.md').write_text('New revision\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'update skill')
    result = run(revision_override=git(repo, 'rev-parse', 'HEAD'))
    assert result.returncode != 0
    assert not log.exists()
    assert (destination / 'specitout' / 'references' / 'investigate.md').read_text() == 'Fixture reference\n'


def test_bootstrap_lock_prevents_competing_tool_install(install_fixture):
    repo, skill, revision, destination, log, env, run = install_fixture
    destination.mkdir()
    (destination / '.specitout-bootstrap.lock').mkdir()
    result = run()
    assert result.returncode != 0
    assert 'running' in result.stderr
    assert not log.exists()
    assert not (destination / 'specitout').exists()
