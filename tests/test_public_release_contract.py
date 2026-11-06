from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PublicReleaseContractTest(unittest.TestCase):
    def test_repository_has_a_safe_evaluation_surface(self) -> None:
        expected_paths = (
            REPO_ROOT / "README.md",
            REPO_ROOT / "PUBLIC_DATA_POLICY.md",
            REPO_ROOT / ".gitignore",
        )

        self.assertEqual([], [str(path) for path in expected_paths if not path.is_file()])

    def test_gitignore_blocks_generated_and_private_working_data(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text()

        for ignored_path in (".env", ".local/", "tmp/", "output/", ".serena/", "__pycache__/"):
            self.assertIn(ignored_path, gitignore)
        self.assertIn("/runtime/", gitignore)
        self.assertNotIn("\nruntime/\n", gitignore)


if __name__ == "__main__":
    unittest.main()
