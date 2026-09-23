"""ublib: shared runtime library for the ultimate-brainstorm kit (Python 3.9+, standard library only).

Modules (see KIT_SPEC.md section 4.8 for the frozen signatures):
    textio       tolerant reads, atomic writes, JSON extraction, hashing
    schema_lite  JSON-schema subset validator
    validate     output contracts (section 4.5)
    filesproto   FILE protocol parse + path guards (section 4.6)
    proc         process runner: argv, cwd, env, stdin, timeout, tree kill (the single test seam)
    redact       secret redaction for logs and meta

This package import stays light on purpose: it imports no submodule, so `import ublib.textio` never pulls in the
process or backend code.
"""

import os

KIT_VERSION = "2.0.0"
__version__ = KIT_VERSION

# ublib/ -> scripts/ -> SK (skills/ultimate-brainstorm)
UBLIB_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(UBLIB_DIR)
SK_DIR = os.path.dirname(SCRIPTS_DIR)

__all__ = ["KIT_VERSION", "UBLIB_DIR", "SCRIPTS_DIR", "SK_DIR"]
