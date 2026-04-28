"""Pythonアプリの配布ツールチェーン。ビルド・署名・差分配布・自動更新を一貫して扱う。"""

__version__ = "0.1.0"

from .bundle import BuildResult, BundleConfig, build
from .errors import ConfigError, HakobuError, UpdateError, VerificationError
from .manifest import Artifact, Manifest, Patch, Release
from .repo import Repository
from .update import Source, State, UpdatePlan, Updater

__all__ = [
    "Artifact",
    "BuildResult",
    "BundleConfig",
    "ConfigError",
    "HakobuError",
    "Manifest",
    "Patch",
    "Release",
    "Repository",
    "Source",
    "State",
    "UpdateError",
    "UpdatePlan",
    "Updater",
    "VerificationError",
    "__version__",
    "build",
]
