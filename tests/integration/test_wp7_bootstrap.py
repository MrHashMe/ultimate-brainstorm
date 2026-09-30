"""install.sh extracts with the same member filter as install.py _safe_extract (audit prune: one member filter).
Owner: WP7.

The shim's inline extractor used to keep link members on Python 3.9-3.11 (it applied filter="data" only on 3.12+).
"""

import io
import os
import re
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harness"))
import paths  # noqa: E402


def shim_extractor():
    """The Python program install.sh runs to extract the archive (the single-quoted -c argument)."""
    with open(paths.INSTALL_SH, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"\$UB_PY -c '\n(.*?)\n' \"\$ub_tmp/\$ub_name\" \"\$ub_tmp/kit\"", text, re.S)
    if not m:
        raise AssertionError("install.sh has no inline extractor")
    return m.group(1)


def archive(path, extra):
    with tarfile.open(path, "w:gz") as tf:
        data = b"2.0.3\n"
        info = tarfile.TarInfo("kit/VERSION")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
        for member in extra:
            tf.addfile(member)


def link(name, target, kind=tarfile.SYMTYPE):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = target
    return info


class ShimExtractor(unittest.TestCase):
    def run_extractor(self, tgz, dest):
        return paths.run([sys.executable, "-c", shim_extractor(), tgz, dest], timeout=60)

    def test_links_are_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            tgz = os.path.join(d, "a.tar.gz")
            archive(tgz, [link("kit/sym.txt", "VERSION"), link("kit/hard.txt", "kit/VERSION", tarfile.LNKTYPE)])
            dest = os.path.join(d, "out")
            os.makedirs(dest)
            proc = self.run_extractor(tgz, dest)
            self.assertEqual(proc.returncode, 0, paths.describe(proc))
            self.assertTrue(os.path.isfile(os.path.join(dest, "kit", "VERSION")))
            for name in ("sym.txt", "hard.txt"):
                self.assertFalse(os.path.lexists(os.path.join(dest, "kit", name)), "%s must not be extracted" % name)

    def test_unsafe_names_abort(self):
        for bad in ("../evil.txt", "/abs.txt", "C:/drive.txt"):
            with tempfile.TemporaryDirectory() as d:
                tgz = os.path.join(d, "a.tar.gz")
                info = tarfile.TarInfo(bad)
                info.size = 1
                with tarfile.open(tgz, "w:gz") as tf:
                    tf.addfile(info, io.BytesIO(b"x"))
                dest = os.path.join(d, "out")
                os.makedirs(dest)
                proc = self.run_extractor(tgz, dest)
                self.assertNotEqual(proc.returncode, 0, bad)
                self.assertIn("unsafe path", proc.err, bad)

    def test_same_members_as_install_py(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ub_install_wp7_extract", paths.INSTALL_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as d:
            tgz = os.path.join(d, "a.tar.gz")
            archive(tgz, [link("kit/sym.txt", "VERSION"), link("kit/hard.txt", "kit/VERSION", tarfile.LNKTYPE)])
            a, b = os.path.join(d, "shim"), os.path.join(d, "py")
            os.makedirs(a)
            self.assertEqual(self.run_extractor(tgz, a).returncode, 0)
            mod._safe_extract(tgz, b)

            def tree(root):
                return sorted(os.path.relpath(os.path.join(dp, n), root).replace("\\", "/")
                              for dp, _dn, fn in os.walk(root) for n in fn)
            self.assertEqual(tree(a), tree(b))


if __name__ == "__main__":
    unittest.main()
