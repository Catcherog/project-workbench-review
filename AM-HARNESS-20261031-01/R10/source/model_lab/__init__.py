"""Frozen, evidence preserving AM model comparison. Never activates production."""

from .core import LabError, freeze_manifest, validate_manifest

__version__ = "1.0.0"
__all__ = ["LabError", "freeze_manifest", "validate_manifest"]
