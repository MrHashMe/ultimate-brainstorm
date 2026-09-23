"""File-tree snapshots (KIT_SPEC 11.1). Owner: B4.

    before = fsnap.snapshot(root)
    ... run something ...
    after = fsnap.snapshot(root)
    d = fsnap.diff(before, after)          # {"added", "removed", "changed", "touched"}
    fsnap.assert_unchanged(self, before, after, ignore=["install.log"])

A snapshot maps each relative POSIX path to (sha256, mtime_ns). "changed" = content differs; "touched" = same
content, different mtime (a rewrite that changed nothing still counts as a modification for idempotency checks).
"""

import fnmatch
import hashlib
import os

DEFAULT_EXCLUDE = ("__pycache__", "*.pyc")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _excluded(rel, patterns):
    parts = rel.split("/")
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or any(fnmatch.fnmatch(p, pat) for p in parts):
            return True
    return False


def snapshot(root, exclude=DEFAULT_EXCLUDE):
    snap = {}
    if not os.path.isdir(root):
        return snap
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = [d for d in dirnames if not _excluded(rel_dir + d, exclude)]
        for name in filenames:
            rel = rel_dir + name
            if _excluded(rel, exclude):
                continue
            p = os.path.join(dirpath, name)
            try:
                snap[rel] = (_sha(p), os.stat(p).st_mtime_ns)
            except OSError:
                continue
    return snap


def diff(before, after):
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed, touched = [], []
    for rel in sorted(set(before) & set(after)):
        if before[rel][0] != after[rel][0]:
            changed.append(rel)
        elif before[rel][1] != after[rel][1]:
            touched.append(rel)
    return {"added": added, "removed": removed, "changed": changed, "touched": touched}


def filtered(d, ignore=()):
    return {k: [p for p in v if not _excluded(p, ignore)] for k, v in d.items()}


def assert_unchanged(tc, before, after, ignore=(), mtimes=True, msg=""):
    d = filtered(diff(before, after), ignore)
    if not mtimes:
        d["touched"] = []
    bad = {k: v for k, v in d.items() if v}
    tc.assertFalse(bad, "%s unexpected file-tree changes: %s" % (msg, bad))


def assert_only(tc, before, after, allowed, msg=""):
    """Every added/removed/changed/touched path matches one of the `allowed` glob patterns."""
    d = diff(before, after)
    stray = [p for k in d for p in d[k] if not any(fnmatch.fnmatch(p, a) for a in allowed)]
    tc.assertFalse(stray, "%s paths changed outside %s: %s" % (msg, list(allowed), stray[:20]))
