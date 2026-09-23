"""Regenerate tests/golden/bs/** from the v1 bs.py copy (tests/fixtures/bs/v1/bs_v1.py).

Run once, review the diff, commit. The goldens are the v1 contract: test_bs_legacy.py requires the kit bs.py to
reproduce them byte for byte on runs without run.json.

    python tests/fixtures/bs/make_goldens.py [scenario ...]
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import legacy_scenarios as ls  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.dirname(HERE)), "golden", "bs")


def main(names):
    names = names or [s[0] for s in ls.SCENARIOS]
    for name in names:
        tmp = tempfile.mkdtemp(prefix="ub-golden-")
        try:
            outputs, transcript = ls.run_scenario(ls.V1_BS, tmp, name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        dest = os.path.join(GOLDEN, name)
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest)
        for rel, data in outputs.items():
            p = os.path.join(dest, "files", *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
        with open(os.path.join(dest, "stdout.txt"), "wb") as f:
            f.write(transcript.encode("utf-8"))
        print("%s: %d files" % (name, len(outputs)))


if __name__ == "__main__":
    main(sys.argv[1:])
