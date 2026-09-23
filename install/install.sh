#!/bin/sh
# ultimate-brainstorm bootstrap installer (POSIX sh; also runs in Git Bash on Windows). KIT_SPEC 10.7.
#
# This file in the repository is a TEMPLATE. tools/release.py renders it (version, owner, SHA-256) into the
# install.sh release asset. Usage of the rendered file:
#   curl -fsSL https://github.com/@UB_OWNER@/ultimate-brainstorm/releases/download/v@UB_VERSION@/install.sh | sh -s -- install
#   inspect first:  curl -fsSL <url> | less
# Everything after `--` goes to install/install.py (plan is the default; install asks once, or add --yes).
#
# Environment:
#   UB_RELEASE_DIR=<dir>   copy the release archive from this folder instead of downloading it
#   UB_ALLOW_ROOT=1        allow running as root (refused otherwise; never use sudo)
#
# The script downloads one archive, checks its SHA-256 against the value embedded below, extracts it into a
# temporary folder, runs the Python installer from there and removes the temporary folder. It never edits PATH,
# shell rc files or anything outside the temporary folder itself.

UB_VERSION='@UB_VERSION@'
UB_OWNER='@UB_OWNER@'
UB_SHA256='@UB_SHA256_TGZ@'

ub_tmp=''

ub_cleanup() {
  if [ -n "$ub_tmp" ] && [ -d "$ub_tmp" ]; then
    rm -rf "$ub_tmp"
  fi
}

ub_find_python() {
  for ub_cand in python3 python "py -3"; do
    # $ub_cand is split on purpose ("py -3").
    # shellcheck disable=SC2086
    if $ub_cand -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      echo "$ub_cand"
      return 0
    fi
  done
  return 1
}

ub_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}' | sed 's/^\\//'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    # shellcheck disable=SC2086
    $UB_PY -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
  fi
}

main() {
  case "$UB_VERSION" in
    @*)
      echo "install.sh: this is the unrendered template; download install.sh from a release instead" >&2
      echo "            (or run: python install/install.py from a clone of the repository)." >&2
      return 1
      ;;
  esac

  ub_uid=$(id -u 2>/dev/null || echo 1)
  if [ "$ub_uid" = "0" ] && [ "${UB_ALLOW_ROOT:-}" != "1" ]; then
    echo "install.sh: refusing to run as root (never use sudo). Set UB_ALLOW_ROOT=1 to override." >&2
    return 1
  fi

  UB_PY=$(ub_find_python) || UB_PY=''
  if [ -z "$UB_PY" ]; then
    echo "install.sh: Python 3.9 or newer is required and was not found (tried python3, python, py -3)." >&2
    echo "  macOS:   brew install python" >&2
    echo "  Windows: winget install Python.Python.3.12" >&2
    echo "  Linux:   install python3 with your package manager" >&2
    return 1
  fi

  ub_name="ultimate-brainstorm-$UB_VERSION.tar.gz"
  ub_tmp=$(mktemp -d 2>/dev/null || mktemp -d -t ubinstall) || {
    echo "install.sh: cannot create a temporary folder" >&2
    return 1
  }
  trap ub_cleanup EXIT
  trap 'ub_cleanup; exit 130' INT TERM

  if [ -n "${UB_RELEASE_DIR:-}" ]; then
    if [ ! -f "$UB_RELEASE_DIR/$ub_name" ]; then
      echo "install.sh: $UB_RELEASE_DIR/$ub_name not found" >&2
      return 1
    fi
    cp "$UB_RELEASE_DIR/$ub_name" "$ub_tmp/$ub_name" || return 1
  else
    ub_url="https://github.com/$UB_OWNER/ultimate-brainstorm/releases/download/v$UB_VERSION/$ub_name"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL -o "$ub_tmp/$ub_name" "$ub_url" || { echo "install.sh: download failed: $ub_url" >&2; return 1; }
    elif command -v wget >/dev/null 2>&1; then
      wget -q -O "$ub_tmp/$ub_name" "$ub_url" || { echo "install.sh: download failed: $ub_url" >&2; return 1; }
    else
      echo "install.sh: curl or wget is required to download $ub_url" >&2
      return 1
    fi
  fi

  ub_got=$(ub_sha256 "$ub_tmp/$ub_name") || ub_got=''
  if [ "$ub_got" != "$UB_SHA256" ]; then
    echo "install.sh: SHA-256 mismatch for $ub_name; aborting before extraction." >&2
    echo "  expected $UB_SHA256" >&2
    echo "  got      ${ub_got:-nothing}" >&2
    return 1
  fi

  mkdir "$ub_tmp/kit" || return 1
  # shellcheck disable=SC2086
  $UB_PY -c '
import sys, tarfile
with tarfile.open(sys.argv[1], "r:gz") as tf:
    for m in tf.getmembers():
        n = m.name.replace("\\", "/")
        if n.startswith("/") or ".." in n.split("/") or (len(n) > 1 and n[1] == ":"):
            sys.exit("unsafe path in archive: " + m.name)
    if sys.version_info >= (3, 12):
        tf.extractall(sys.argv[2], filter="data")
    else:
        tf.extractall(sys.argv[2])
' "$ub_tmp/$ub_name" "$ub_tmp/kit" || { echo "install.sh: extraction failed" >&2; return 1; }

  ub_inst=''
  for ub_c in "$ub_tmp"/kit/*/install/install.py "$ub_tmp"/kit/install/install.py; do
    if [ -f "$ub_c" ]; then
      ub_inst=$ub_c
      break
    fi
  done
  if [ -z "$ub_inst" ]; then
    echo "install.sh: the archive holds no install/install.py" >&2
    return 1
  fi

  # Under `curl | sh` stdin is the script itself, so the installer reads its one question from the terminal.
  if [ -r /dev/tty ] && (exec </dev/tty) 2>/dev/null; then
    # shellcheck disable=SC2086
    $UB_PY "$ub_inst" "$@" </dev/tty
  else
    # shellcheck disable=SC2086
    $UB_PY "$ub_inst" "$@"
  fi
}

main "$@" || exit 1
