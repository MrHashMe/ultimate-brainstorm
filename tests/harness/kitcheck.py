"""Load tools/validate_kit.py and tools/ci.py as modules for tests (tools/ is not a package). Owner: B4."""

import importlib.util
import os

import paths

_MOD = {}


def _load(name, path):
    if name not in _MOD:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MOD[name] = mod
    return _MOD[name]


def load_validate_kit():
    return _load("validate_kit", paths.VALIDATE_KIT_PY)


def load_ci():
    return _load("ub_ci", os.path.join(paths.KIT, "tools", "ci.py"))
