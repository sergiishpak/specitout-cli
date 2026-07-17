from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPyWithoutStaleSpecItOutResources(build_py):
    def run(self) -> None:
        shutil.rmtree(Path(self.build_lib) / "specitout" / "resources", ignore_errors=True)
        super().run()


setup(cmdclass={"build_py": BuildPyWithoutStaleSpecItOutResources})
