"""Sandboxed loader for strategy files (LLM-generated or user-edited).

Wraps importlib.util.spec_from_file_location with a restricted namespace.
Catches SyntaxError, ImportError, and any other exception at import time
and returns a structured result instead of raising.
"""
import importlib.util
import sys
import traceback
from dataclasses import dataclass
from types import ModuleType
from typing import Optional


@dataclass
class SafeImportResult:
    """Result of safe_import_strategy."""
    module: Optional[ModuleType]
    error: Optional[str] = None
    traceback: Optional[str] = None
    path: str = ""


def safe_import_strategy(path: str) -> SafeImportResult:
    """Load a Python file in a fresh module namespace. Never raises.

    Returns SafeImportResult with module set on success, or error+traceback
    set on failure. The module's name is derived from the file path so that
    re-imports of the same path return a fresh module (sys.modules is checked
    and the old entry is removed first).
    """
    if not path or not isinstance(path, str):
        return SafeImportResult(module=None, error="path must be a non-empty string", path=str(path))

    # Remove any cached version of this module so we get a fresh load
    module_name = f"_safe_strategy_{abs(hash(path))}"
    sys.modules.pop(module_name, None)

    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
    except Exception as e:
        return SafeImportResult(
            module=None,
            error=f"Failed to create spec: {type(e).__name__}: {e}",
            traceback=traceback.format_exc(),
            path=path,
        )

    if spec is None or spec.loader is None:
        return SafeImportResult(
            module=None,
            error=f"Could not create import spec for {path}",
            path=path,
        )

    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except SyntaxError as e:
        sys.modules.pop(module_name, None)
        return SafeImportResult(
            module=None,
            error=f"SyntaxError: {e.msg} at line {e.lineno}",
            traceback=traceback.format_exc(),
            path=path,
        )
    except ImportError as e:
        sys.modules.pop(module_name, None)
        return SafeImportResult(
            module=None,
            error=f"ImportError: {e}",
            traceback=traceback.format_exc(),
            path=path,
        )
    except Exception as e:
        sys.modules.pop(module_name, None)
        return SafeImportResult(
            module=None,
            error=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc(),
            path=path,
        )

    return SafeImportResult(module=module, path=path)
