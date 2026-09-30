#!/usr/bin/env python3
"""Build the release assets for the ultimate-brainstorm kit (KIT_SPEC 10.7). Python 3.9+, standard library only.

    python tools/release.py --version 2.0.0 [--owner <github-user>] --out dist/ [--notes FILE] [--no-acceptance]
                            [--json]

The live acceptance record comes first (KIT_SPEC 11.9): the build is refused (exit 3) while docs/ACCEPTANCE.md has a
check without a live result ("not yet verified live", "not tested" or empty; the "(unused)" items are exempt), a result
without its host and date, or fewer than 2 hosts with the Doctor check. --no-acceptance builds anyway; with --notes the
list of what is unverified is appended to that release-notes file, so the release says so. --notes also records a
complete acceptance.

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

Exit codes: 0 ok, 1 failure, 2 usage (bad version/owner, VERSION mismatch), 3 the acceptance record is incomplete.
"""

import argparse
import gzip
import hashlib
import importlib.util
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

# Files whose owner name is filled in the archive copy (10.7): manifests, targets.json and the docs.
OWNER_GLOBS = (
    re.compile(r"^\.claude-plugin/[^/]+\.json$"),
    re.compile(r"^\.codex-plugin/[^/]+\.json$"),
    re.compile(r"^\.agents/plugins/[^/]+\.json$"),
    re.compile(r"^\.kimi-plugin/[^/]+\.json$"),
    re.compile(r"^install/targets\.json$"),
    re.compile(r"^docs/[^/]+\.md$"),  # not docs/design/: the build spec discusses the placeholder itself
    re.compile(r"^README\.md$"),
)
DEFAULT_OWNER = "MrHashMe"
OWNER_RE = re.compile(r"\b(?:OWNER|%s)\b" % DEFAULT_OWNER)

ACCEPTANCE = "docs/ACCEPTANCE.md"
# Result cells that record no live check (docs/ACCEPTANCE.md, Procedure step 5)
NOT_VERIFIED = ("", "not yet verified live", "not tested")
MIN_HOSTS = 2


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


def markdown_tables(text):
    """[[{header: cell}, ...], ...]: the rows of every Markdown table in text (headers lower-cased)."""
    tables, header, rows = [], None, None
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("|"):
            header = rows = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if re.match(r"^\|[\s:|-]+\|$", nxt):
                header, rows = [c.lower() for c in cells], []
                tables.append(rows)
            continue
        if re.match(r"^[\s:-]*$", "".join(cells)):
            continue  # the separator line
        rows.append(dict(zip(header, cells + [""] * (len(header) - len(cells)))))
    return tables


def acceptance_gaps(kit):
    """What docs/ACCEPTANCE.md lacks before a release; [] when the record is complete. Every row of a table with a
    Result column (platform checks, unverified items; items marked "(unused)" are exempt) needs a live result plus its
    host and date, and at least MIN_HOSTS rows of the per-host table need a Doctor result (a cell outside
    NOT_VERIFIED)."""
    path = os.path.join(kit, *ACCEPTANCE.split("/"))
    if not os.path.isfile(path):
        return ["%s is missing" % ACCEPTANCE]
    gaps, hosts = [], []
    for rows in markdown_tables(read_text(path)):
        for row in rows:
            first = next(iter(row.values()), "")
            name = re.sub(r"`", "", first)
            m = re.match(r"^(U-\d+)\b", name)
            label = m.group(1) if m else name[:60]
            if "1 doctor" in row:
                if row["1 doctor"].lower() not in NOT_VERIFIED:  # "not tested" records no check either
                    hosts.append(first)
                continue
            if "result" not in row or "(unused)" in name:
                continue
            host = next((v for k, v in row.items() if k.startswith("host")), "")
            if row["result"].lower() in NOT_VERIFIED:
                gaps.append("%s: no live result" % label)
            elif not host or not row.get("date"):
                gaps.append("%s: the result has no host and date" % label)
    if len(hosts) < MIN_HOSTS:
        gaps.append("the per-host checks ran on %d host(s), not %d (Doctor column)" % (len(hosts), MIN_HOSTS))
    return gaps


def acceptance_notes(gaps):
    """The release-notes section that records the state of the live acceptance."""
    if not gaps:
        return "\n## Live acceptance\n\nEvery check in docs/ACCEPTANCE.md has a recorded live result.\n"
    return ("\n## Live acceptance\n\nThis release was built with `--no-acceptance`: %d check(s) of docs/ACCEPTANCE.md "
            "have no recorded live result. Where such an assumption is wrong, the fallback in KIT_SPEC section 15 "
            "is what you get.\n\n%s\n" % (len(gaps), "\n".join("- " + g for g in gaps)))


def runtime_paths(kit):
    with open(os.path.join(kit, "install", "targets.json"), "r", encoding="utf-8") as f:
        return json.load(f)["runtime_paths"]


def installer(kit):
    """The kit's own install/install.py as a module: the archive holds exactly the file set the installer stages."""
    path = os.path.join(kit, "install", "install.py")
    if not os.path.isfile(path):
        raise ReleaseError("the kit is incomplete: install/install.py is missing")
    spec = importlib.util.spec_from_file_location("ub_release_installer", path)
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # never leave __pycache__ in the kit being archived
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


def collect(kit):
    """{relpath (posix): abspath} of every runtime file: install.py's runtime_file_map (its exclusions, 10.4 item 1)."""
    return dict(sorted(installer(kit).runtime_file_map(kit, runtime_paths(kit)).items()))


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


def release(version, owner, out_dir, kit=KIT, no_acceptance=False, notes=None):
    if not re.match(r"^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$", version):
        raise ReleaseError("--version must look like 2.0.0 (no leading v)", 2)
    if not re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$", owner) or owner == "OWNER":
        raise ReleaseError("--owner must be a GitHub user or organization name", 2)
    file_version = read_text(os.path.join(kit, "VERSION")).strip()
    if file_version != version:
        raise ReleaseError("--version %s does not match VERSION (%s)" % (version, file_version), 2)
    gaps = acceptance_gaps(kit)
    if gaps and not no_acceptance:
        raise ReleaseError("%s is not filled in (%d gap(s): %s%s). Run the live checks and record them, or build with "
                           "--no-acceptance (with --notes, the release notes then list what is unverified)"
                           % (ACCEPTANCE, len(gaps), "; ".join(gaps[:3]), "; ..." if len(gaps) > 3 else ""), 3)
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
    if notes:
        with open(notes, "a", encoding="utf-8", newline="\n") as f:
            f.write(acceptance_notes(gaps))
    return {"version": version, "owner": owner, "out": out_dir.replace("\\", "/"), "files": len(entries),
            "assets": {n: {"sha256": sums[n], "bytes": os.path.getsize(os.path.join(out_dir, n))} for n in sorted(sums)},
            "owner_filled": sorted(rel for rel in files if needs_owner(rel)),
            "acceptance": {"complete": not gaps, "gaps": gaps}}


def main(argv=None):
    p = argparse.ArgumentParser(prog="release.py", description="Build ultimate-brainstorm release assets")
    p.add_argument("--version", required=True)
    p.add_argument("--owner", default=DEFAULT_OWNER)
    p.add_argument("--out", default="dist")
    p.add_argument("--notes", metavar="FILE", help="append the live acceptance state to this release-notes file")
    p.add_argument("--no-acceptance", dest="no_acceptance", action="store_true",
                   help="build although docs/ACCEPTANCE.md is incomplete (say so in the release notes: --notes)")
    p.add_argument("--json", action="store_true")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        result = release(args.version, args.owner, args.out, no_acceptance=args.no_acceptance, notes=args.notes)
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
    if result["acceptance"]["gaps"]:
        sys.stderr.write("release.py: built with --no-acceptance: %d check(s) in %s have no live result\n"
                         % (len(result["acceptance"]["gaps"]), ACCEPTANCE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
