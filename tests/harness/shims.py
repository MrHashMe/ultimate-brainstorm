"""Install the fake CLIs into a temporary bin folder (KIT_SPEC 4.18, 11.2). Owner: B4.

POSIX: an executable `/bin/sh` wrapper per tool (a shebang script) that execs "$UB_FAKE_PY" /abs/fakecli.py <tool> "$@"
(no external commands, since the tests' PATH has no coreutils on CI runners).
Windows: `<tool>.cmd` = `@"%UB_FAKE_PY%" "%~dp0fakecli.py" <tool> %*` (CRLF), so the real `.cmd` quoting path runs.

fakecli.py is copied next to the shims together with `_kit_path.txt`, which tells the copy where the kit lives (for
`ublib.stubs`).
"""

import os
import shutil
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_TOOLS = ("claude", "codex", "kimi", "npx")


def cmd_text(tool):
    return '@"%%UB_FAKE_PY%%" "%%~dp0fakecli.py" %s %%*\r\n' % tool


def _sh_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def sh_text(tool, fakecli):
    """The POSIX shim, with the absolute path of fakecli.py baked in. It needs nothing from PATH: the tests' PATH is
    only the temp bin folder and Python's folder, which on CI runners (hostedtoolcache, venvs, python.org framework
    builds) holds no coreutils such as `dirname`."""
    return ('#!/bin/sh\n'
            '# fake %s for ultimate-brainstorm tests (tests/harness/shims.py)\n'
            'exec "${UB_FAKE_PY:-python3}" %s %s "$@"\n') % (tool, _sh_quote(fakecli), tool)


def install_fakes(bin_dir, tools=DEFAULT_TOOLS, windows=None):
    """Create the shims; returns {tool: shim path}. windows=None means "this OS"."""
    windows = (os.name == "nt") if windows is None else windows
    os.makedirs(bin_dir, exist_ok=True)
    shutil.copyfile(os.path.join(HERE, "fakecli.py"), os.path.join(bin_dir, "fakecli.py"))
    with open(os.path.join(bin_dir, "_kit_path.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(KIT + "\n")
    made = {}
    for tool in tools:
        if windows:
            path = os.path.join(bin_dir, tool + ".cmd")
            with open(path, "w", encoding="ascii", newline="") as f:
                f.write(cmd_text(tool))
        else:
            path = os.path.join(bin_dir, tool)
            with open(path, "w", encoding="ascii", newline="\n") as f:
                f.write(sh_text(tool, os.path.join(os.path.abspath(bin_dir), "fakecli.py")))
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        made[tool] = path
    return made


def remove_fake(bin_dir, tool):
    for name in (tool, tool + ".cmd"):
        p = os.path.join(bin_dir, name)
        if os.path.exists(p):
            os.remove(p)


def python_dir():
    return os.path.dirname(os.path.abspath(sys.executable))
