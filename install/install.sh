#!/bin/sh
# ultimate-brainstorm bootstrap installer (POSIX sh; also runs in Git Bash on Windows). KIT_SPEC 10.7.
#
# This file in the repository is a TEMPLATE. tools/release.py renders it (version, owner, SHA-256) into the
# install.sh release asset. Usage of the rendered file:
#   curl -fsSL https://github.com/@UB_OWNER@/ultimate-brainstorm/releases/download/v@UB_VERSION@/install.sh | sh -s -- install
#   inspect first (one download, so what you read is what runs):
#     curl -fsSLO <url>
#     gh attestation verify install.sh --repo @UB_OWNER@/ultimate-brainstorm \
#       --signer-workflow @UB_OWNER@/ultimate-brainstorm/.github/workflows/release.yml --source-ref refs/tags/v@UB_VERSION@
#     less install.sh; sh install.sh install
# Everything after `--` goes to install/install.py (plan is the default; install asks once, or add --yes).
# --require-attestation fails when the archive's build provenance cannot be checked (no signed-in gh).
#
# Environment:
#   UB_RELEASE_DIR=<dir>   copy the release archive from this folder instead of downloading it
#   UB_ALLOW_ROOT=1        allow running as root (refused otherwise; never use sudo)
#
# The script downloads one archive, checks its SHA-256 against the value embedded below and, with a signed-in GitHub
# CLI, its build attestation, extracts it into a temporary folder, runs the Python installer from there and removes
# the temporary folder. It never edits PATH, shell rc files or anything outside the temporary folder itself.

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

# Provenance [U-52]: the archive's hash comes from the same release as the archive, so with a signed-in GitHub CLI
# the archive must also carry a build attestation from this repository's release workflow for the tag v$UB_VERSION
# (a run of any other workflow in the repository can attest too). gh is asked about github.com only: the sign-in of
# the account verify uses (a bare `gh auth status` fails when any account on any host has a problem), and verify is
# pinned there, so GH_HOST cannot send it elsewhere. Prints why the check could not run (nothing when it passed);
# returns 1 when it ran and failed, printing gh's last line.
ub_provenance() {
  ub_repo="$UB_OWNER/ultimate-brainstorm"
  if [ -n "${UB_RELEASE_DIR:-}" ]; then
    echo "local release assets from UB_RELEASE_DIR"
    return 0
  fi
  if ! command -v gh >/dev/null 2>&1; then
    echo "the GitHub CLI gh is not installed"
    return 0
  fi
  if ! gh attestation --help >/dev/null 2>&1 || ! gh auth status --active --hostname github.com >/dev/null 2>&1; then
    echo "gh is not signed in, or has no attestation command"
    return 0
  fi
  if ub_out=$(gh attestation verify "$1" --repo "$ub_repo" \
      --signer-workflow "$ub_repo/.github/workflows/release.yml" --source-ref "refs/tags/v$UB_VERSION" \
      --hostname github.com 2>&1); then
    return 0
  fi
  ub_nl='
'
  ub_last=${ub_out##*$ub_nl}
  # Read only gh's own words: a refusal quotes the certificate's identity (workflow path, ref), which its minter chose.
  ub_own=$(printf '%s\n' "$ub_out" | sed -e 's/\\.//g' -e 's/"[^"]*"/""/g')
  case "$ub_own" in
    *"unknown flag"*|*"unknown shorthand flag"*)
      echo "this gh has no --signer-workflow / --source-ref / --hostname: update the GitHub CLI"
      return 0
      ;;
  esac
  # gh fails so, before it reads any attestation, when it cannot load its Sigstore trust root (the TUF repository is
  # out of reach, for example behind a proxy that blocks it): the check could not run, not a verdict.
  if printf '%s\n' "$ub_own" | grep -Eiq \
      '^[[:space:]]*(Error:[[:space:]]*)?error creating Sigstore verifier([^[:alnum:]_]|$)'; then
    echo "gh could not build its Sigstore verifier: is the Sigstore TUF repository (tuf-repo-cdn.sigstore.dev)" \
      "reachable from here? gh: $ub_last"
    return 0
  fi
  echo "$ub_last"
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

  # Provenance (ub_provenance above). --require-attestation (passed on to install.py as well) makes a missing check an
  # error.
  ub_req=''
  for ub_a in "$@"; do
    if [ "$ub_a" = "--require-attestation" ]; then ub_req=1; fi
  done
  ub_manual="gh attestation verify $ub_name --repo $UB_OWNER/ultimate-brainstorm --signer-workflow"
  ub_manual="$ub_manual $UB_OWNER/ultimate-brainstorm/.github/workflows/release.yml --source-ref refs/tags/v$UB_VERSION"
  ub_manual="$ub_manual --hostname github.com"
  if ! ub_why=$(ub_provenance "$ub_tmp/$ub_name"); then
    echo "install.sh: provenance check failed for $ub_name: gh attestation verify did not confirm that it was built" \
      "by $UB_OWNER/ultimate-brainstorm's .github/workflows/release.yml for the tag v$UB_VERSION (gh: $ub_why)." \
      "Do not install this archive. If gh could not reach GitHub or Sigstore, run the command again; if they stay" \
      "out of reach, run the check by hand where gh reaches them ($ub_manual) and install that checked archive's" \
      "extracted folder with 'install.py update --source DIR'." >&2
    return 1
  fi
  if [ -n "$ub_why" ]; then
    if [ -n "$ub_req" ]; then
      echo "install.sh: --require-attestation: the provenance of $ub_name was not checked ($ub_why)." >&2
      return 1
    fi
    echo "install.sh: note: provenance not checked ($ub_why); check it by hand: $ub_manual" >&2
  fi

  mkdir "$ub_tmp/kit" || return 1
  # The same member filter as install.py _safe_extract: unsafe names abort; links and devices are dropped.
  # shellcheck disable=SC2086
  $UB_PY -c '
import sys, tarfile
with tarfile.open(sys.argv[1], "r:gz") as tf:
    members = []
    for m in tf.getmembers():
        n = m.name.replace("\\", "/")
        if n.startswith("/") or ".." in n.split("/") or (len(n) > 1 and n[1] == ":"):
            sys.exit("unsafe path in archive: " + m.name)
        if not (m.issym() or m.islnk() or m.isdev()):
            members.append(m)
    if hasattr(tarfile, "data_filter"):
        tf.extractall(sys.argv[2], members=members, filter="data")
    else:
        tf.extractall(sys.argv[2], members=members)
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

# install.py's exit code (0-5, KIT_SPEC 4.14) is the shim's; the shim's own failures return 1
main "$@"
exit $?
