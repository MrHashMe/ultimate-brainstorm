#!/usr/bin/env python3
"""Build the release assets for the ultimate-brainstorm kit (KIT_SPEC 10.7). Python 3.9+, standard library only.

    python tools/release.py --version 2.0.0 [--owner <github-user>] --out dist/ [--json]

Writes into --out:
    ultimate-brainstorm-<ver>.tar.gz   runtime_paths (install/targets.json) under ultimate-brainstorm-<ver>/
    ultimate-brainstorm-<ver>.zip      the same tree
    install.sh                         install/install.sh rendered with version, owner and the .tar.gz SHA-256 (LF)
    install.ps1                        install/install.ps1 rendered with version, owner and the .zip SHA-256 (CRLF)
    SHA256SUMS                         "<sha256>  <name>" for the four files above

The repository names its GitHub owner (DEFAULT_OWNER, "MrHashMe") in the manifests, install/targets.json and the
docs. When --owner differs (a fork), that name, and any leftover OWNER placeholder, is replaced in the ARCHIVE COPY
only; the repository is never modified. Archives are reproducible: sorted entries, fixed timestamps (SOURCE_DATE_EPOCH, default
1980-01-01), normalized owners and modes.

Exit codes: 0 ok, 1 failure, 2 usage (bad version/owner, VERSION mismatch).
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import time
import zipfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "ultimate-brainstorm"

EXCLUDE_ANYWHERE = {"__pycache__", ".git", ".build"}
EXCLUDE_TOP = {"tests", "tools", ".github", "dist"}
EXCLUDE_SUFFIX = (".pyc", ".pyo")
MARKER = ".ub-owned"

# Files whose owner name is filled in the archive copy (10.7): manifests, targets.json and the docs.
OWNER_GLOBS = (
    re.compile(r"^\.claude-plugin/[^/]+\.json$"),
    re.compile(r"^\.codex-plugin/[^/]+\.json$"),
    re.compile(r"^\.agents/plugins/[^/]+\.json$"),
    re.compile(r"^\.kimi-plugin/[^/]+\.json$"),
    re.compile(r"^bundles/.+/plugin\.json$"),
    re.compile(r"^install/targets\.json$"),
    re.compile(r"^docs/[^/]+\.md$"),  # not docs/design/: the build spec discusses the placeholder itself
    re.compile(r"^README\.md$"),
)
DEFAULT_OWNER = "MrHashMe"
OWNER_RE = re.compile(r"\b(?:OWNER|%s)\b" % DEFAULT_OWNER)


class ReleaseError(Exception):
    def __init__(self, message, code=1):
        Exception.__init__(self, message)
        self.code = code


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def runtime_paths(kit):
    with open(os.path.join(kit, "install", "targets.json"), "r", encoding="utf-8") as f:
        return json.load(f)["runtime_paths"]


def collect(kit):
    """{relpath (posix): abspath} of every runtime file, with the installer's exclusions (10.4 item 1)."""
    files = {}
    for rp in runtime_paths(kit):
        full = os.path.join(kit, *rp.split("/"))
        if os.path.isfile(full):
            files[rp] = full
            continue
        if not os.path.isdir(full):
            continue
        for dirpath, dirnames, filenames in os.walk(full):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_ANYWHERE
                                 and not os.path.islink(os.path.join(dirpath, d)))
            for name in sorted(filenames):
                if name == MARKER or name.endswith(EXCLUDE_SUFFIX):
                    continue
                p = os.path.join(dirpath, name)
                if os.path.islink(p):
                    continue
                rel = os.path.relpath(p, kit).replace("\\", "/")
                if rel.split("/")[0] in EXCLUDE_TOP:
                    continue
                files[rel] = p
    return dict(sorted(files.items()))


def needs_owner(rel):
    return any(rx.match(rel) for rx in OWNER_GLOBS)


def file_bytes(rel, path, owner):
    with open(path, "rb") as f:
        data = f.read()
    if owner and needs_owner(rel):
        text = data.decode("utf-8")
        new = OWNER_RE.sub(owner, text)
        if rel.endswith(".json") and new != text:
            json.loads(new)  # must stay valid JSON
        data = new.encode("utf-8")
    return data


def file_mode(rel, data):
    return 0o755 if rel.endswith(".sh") or data.startswith(b"#!") else 0o644


def build_tar(entries, top, epoch):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tf:
        dirs = set()
        for rel in entries:
            parts = rel.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        items = [(d, None) for d in dirs] + [(rel, entries[rel]) for rel in entries]
        for rel, data in sorted(items, key=lambda x: x[0]):
            info = tarfile.TarInfo(top + "/" + rel)
            info.mtime = epoch
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if data is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tf.addfile(info)
            else:
                info.size = len(data)
                info.mode = file_mode(rel, data)
                tf.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=epoch, compresslevel=9) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def build_zip(entries, top, epoch):
    dt = time.gmtime(max(epoch, 315532800))[:6]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(entries):
            data = entries[rel]
            info = zipfile.ZipInfo(top + "/" + rel, date_time=dt)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100000 | file_mode(rel, data)) << 16
            info.create_system = 3
            zf.writestr(info, data)
    return out.getvalue()


def render_shim(template_path, values, newline):
    text = read_text(template_path).replace("\r\n", "\n")
    for key, value in values.items():
        text = text.replace("@%s@" % key, value)
    left = re.findall(r"@UB_[A-Z0-9_]+@", text)
    if left:
        raise ReleaseError("unrendered placeholders in %s: %s" % (template_path, ", ".join(sorted(set(left)))))
    return text.replace("\n", newline).encode("ascii")


def write_bytes(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def release(version, owner, out_dir, kit=KIT):
    if not re.match(r"^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$", version):
        raise ReleaseError("--version must look like 2.0.0 (no leading v)", 2)
    if not re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$", owner) or owner == "OWNER":
        raise ReleaseError("--owner must be a GitHub user or organization name", 2)
    file_version = read_text(os.path.join(kit, "VERSION")).strip()
    if file_version != version:
        raise ReleaseError("--version %s does not match VERSION (%s)" % (version, file_version), 2)
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or 315532800)
    top = "%s-%s" % (NAME, version)
    files = collect(kit)
    if not files:
        raise ReleaseError("no runtime files found under %s" % kit)
    for need in ("install/install.py", "install/targets.json", "skills/%s/SKILL.md" % NAME):
        if need not in files:
            raise ReleaseError("the kit is incomplete: %s is missing" % need)
    entries = {rel: file_bytes(rel, p, owner) for rel, p in files.items()}
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    tgz_name = "%s.tar.gz" % top
    zip_name = "%s.zip" % top
    tgz = build_tar(entries, top, epoch)
    zdata = build_zip(entries, top, epoch)
    write_bytes(os.path.join(out_dir, tgz_name), tgz)
    write_bytes(os.path.join(out_dir, zip_name), zdata)
    values = {"UB_VERSION": version, "UB_OWNER": owner, "UB_SHA256_TGZ": sha256_bytes(tgz),
              "UB_SHA256_ZIP": sha256_bytes(zdata)}
    sh = render_shim(os.path.join(kit, "install", "install.sh"), values, "\n")
    ps = render_shim(os.path.join(kit, "install", "install.ps1"), values, "\r\n")
    write_bytes(os.path.join(out_dir, "install.sh"), sh)
    try:
        os.chmod(os.path.join(out_dir, "install.sh"), 0o755)
    except OSError:
        pass
    write_bytes(os.path.join(out_dir, "install.ps1"), ps)
    sums = {tgz_name: sha256_bytes(tgz), zip_name: sha256_bytes(zdata), "install.sh": sha256_bytes(sh),
            "install.ps1": sha256_bytes(ps)}
    lines = "".join("%s  %s\n" % (sums[n], n) for n in sorted(sums))
    write_bytes(os.path.join(out_dir, "SHA256SUMS"), lines.encode("ascii"))
    return {"version": version, "owner": owner, "out": out_dir.replace("\\", "/"), "files": len(entries),
            "assets": {n: {"sha256": sums[n], "bytes": os.path.getsize(os.path.join(out_dir, n))} for n in sorted(sums)},
            "owner_filled": sorted(rel for rel in files if needs_owner(rel))}


def main(argv=None):
    p = argparse.ArgumentParser(prog="release.py", description="Build ultimate-brainstorm release assets")
    p.add_argument("--version", required=True)
    p.add_argument("--owner", default=DEFAULT_OWNER)
    p.add_argument("--out", default="dist")
    p.add_argument("--json", action="store_true")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        result = release(args.version, args.owner, args.out)
    except ReleaseError as exc:
        sys.stderr.write("release.py: %s\n" % exc)
        return exc.code
    except (OSError, ValueError) as exc:
        sys.stderr.write("release.py: %s\n" % exc)
        return 1
    if args.json:
        sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
    else:
        sys.stdout.write("ultimate-brainstorm %s release assets in %s (%d files archived)\n"
                         % (result["version"], result["out"], result["files"]))
        for n, a in result["assets"].items():
            sys.stdout.write("  %s  %s (%d bytes)\n" % (a["sha256"], n, a["bytes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
