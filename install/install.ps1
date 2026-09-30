# ultimate-brainstorm bootstrap installer (Windows PowerShell 5.1 or newer). KIT_SPEC 10.7.
#
# This file in the repository is a TEMPLATE. tools/release.py renders it (version, owner, SHA-256) into the
# install.ps1 release asset. Usage of the rendered file:
#   & ([scriptblock]::Create((irm https://github.com/@UB_OWNER@/ultimate-brainstorm/releases/download/v@UB_VERSION@/install.ps1))) install
#   inspect first (one download, so what you read is what runs):
#     irm <url> -OutFile install.ps1
#     gh attestation verify install.ps1 --repo @UB_OWNER@/ultimate-brainstorm `
#       --signer-workflow @UB_OWNER@/ultimate-brainstorm/.github/workflows/release.yml --source-ref refs/tags/v@UB_VERSION@
#     notepad install.ps1; powershell -ExecutionPolicy Bypass -File install.ps1 install
# Arguments go to install/install.py (plan is the default; install asks once, or add --yes).
# --require-attestation fails when the archive's build provenance cannot be checked (no signed-in gh).
#
# Environment:
#   UB_RELEASE_DIR = a folder holding the release .zip (copied instead of downloaded)
#
# The script downloads one archive, checks its SHA-256 against the value embedded below and, with a signed-in GitHub
# CLI, its build attestation, extracts it into a temporary folder, runs the Python installer from there and removes the
# temporary folder. It never edits PATH, profiles or anything outside that temporary folder.

# Provenance [U-52]: the archive's hash comes from the same release as the archive, so with a signed-in GitHub CLI the
# archive must also carry a build attestation from this repository's release workflow for the tag v<version> (a run of
# any other workflow in the repository can attest too). gh is asked about github.com only: the sign-in of the account
# verify uses (a bare `gh auth status` fails when any account on any host has a problem), and verify is pinned there,
# so GH_HOST cannot send it elsewhere. Returns why the check could not run ($null when it passed); throws when it ran
# and failed.
function Test-UbProvenance {
    param([string]$Archive, [string]$Owner, [string]$Version)

    $repo = "$Owner/ultimate-brainstorm"
    if ($env:UB_RELEASE_DIR) { return 'local release assets from UB_RELEASE_DIR' }
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { return 'the GitHub CLI gh is not installed' }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'  # gh writes to stderr; under 'Stop' PowerShell 5.1 would throw on it
    try {
        & gh attestation --help *> $null
        if ($LASTEXITCODE -ne 0) { return 'gh is not signed in, or has no attestation command' }
        & gh auth status --active --hostname github.com *> $null
        if ($LASTEXITCODE -ne 0) { return 'gh is not signed in, or has no attestation command' }
        $lines = @(& gh attestation verify $Archive --repo $repo --signer-workflow "$repo/.github/workflows/release.yml" `
                --source-ref "refs/tags/v$Version" --hostname github.com 2>&1 | ForEach-Object { "$_" })
        $rc = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    if ($rc -eq 0) { return $null }
    # Read only gh's own words: a refusal quotes the certificate's identity (workflow path, ref), which its minter chose.
    $own = ($lines -join "`n") -replace '\\.', '' -replace '"[^"]*"', '""'
    if ($own -match 'unknown (shorthand )?flag') {
        return 'this gh has no --signer-workflow / --source-ref / --hostname: update the GitHub CLI'
    }
    $last = @($lines | Where-Object { $_.Trim() }) | Select-Object -Last 1
    # gh fails so, before it reads any attestation, when it cannot load its Sigstore trust root (the TUF repository is
    # out of reach, for example behind a proxy that blocks it): the check could not run, not a verdict.
    if ($own -match '(?m)^\s*(Error:\s*)?error creating Sigstore verifier\b') {
        return ('gh could not build its Sigstore verifier: is the Sigstore TUF repository ' +
            "(tuf-repo-cdn.sigstore.dev) reachable from here? gh: $last")
    }
    $name = Split-Path -Leaf $Archive
    throw ("install.ps1: provenance check failed for ${name}: gh attestation verify did not confirm that it was " +
        "built by $repo's .github/workflows/release.yml for the tag v$Version (gh: $last). Do not install this " +
        'archive. If gh could not reach GitHub or Sigstore, run the command again; if they stay out of reach, run ' +
        "the check by hand where gh reaches them (gh attestation verify $name --repo $repo --signer-workflow " +
        "$repo/.github/workflows/release.yml --source-ref refs/tags/v$Version --hostname github.com) and install " +
        "that checked archive's extracted folder with 'install.py update --source DIR'.")
}

function Main {
    param([object[]]$Rest)

    # Every error stops the script. Without this, a statement-terminating error (a cmdlet that cannot load, e.g.
    # Get-FileHash under a PSModulePath inherited from PowerShell 7) skips the rest of the try block, and
    # 'powershell -File' then exits 0 without having checked the hash or installed anything.
    $ErrorActionPreference = 'Stop'

    $UbVersion = '@UB_VERSION@'
    $UbOwner = '@UB_OWNER@'
    $UbSha256 = '@UB_SHA256_ZIP@'

    if ($UbVersion.StartsWith('@')) {
        throw 'install.ps1: this is the unrendered template; download install.ps1 from a release instead (or run py -3 install\install.py from a clone).'
    }
    # 10.4 item 8: never elevated (an elevated shell may belong to another account and would install there)
    $principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -and $env:UB_ALLOW_ROOT -ne '1') {
        throw 'install.ps1: refusing to run elevated; open a normal PowerShell (or set UB_ALLOW_ROOT=1)'
    }
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch {
        Write-Verbose 'TLS 1.2 could not be enabled explicitly'
    }

    $argList = @()
    if ($Rest) {
        # PowerShell parses an unquoted a,b as an array: pass it on as the comma list that was typed.
        $argList = @($Rest | ForEach-Object {
            if ($_ -is [System.Array]) { @($_ | ForEach-Object { "$_" }) -join ',' } else { "$_" }
        })
    }

    $name = "ultimate-brainstorm-$UbVersion.zip"
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('ub-install-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp -ErrorAction Stop | Out-Null
    $code = 0
    try {
        $archive = Join-Path $tmp $name
        if ($env:UB_RELEASE_DIR) {
            $src = Join-Path $env:UB_RELEASE_DIR $name
            if (-not (Test-Path -LiteralPath $src)) { throw "install.ps1: $src not found" }
            Copy-Item -LiteralPath $src -Destination $archive -ErrorAction Stop
        } else {
            $url = "https://github.com/$UbOwner/ultimate-brainstorm/releases/download/v$UbVersion/$name"
            Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing -ErrorAction Stop
        }

        $got = (Get-FileHash -LiteralPath $archive -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
        if ($got -ne $UbSha256.ToLowerInvariant()) {
            throw "install.ps1: SHA-256 mismatch for $name; aborting before extraction. Expected $UbSha256, got $got."
        }

        # Provenance (Test-UbProvenance above); --require-attestation makes a missing check an error.
        $repo = "$UbOwner/ultimate-brainstorm"
        $why = Test-UbProvenance -Archive $archive -Owner $UbOwner -Version $UbVersion
        if ($why) {
            if ($argList -contains '--require-attestation') {
                throw "install.ps1: --require-attestation: the provenance of $name was not checked ($why)."
            }
            Write-Warning ("provenance not checked ($why); check it by hand: gh attestation verify $name --repo $repo " +
                "--signer-workflow $repo/.github/workflows/release.yml --source-ref refs/tags/v$UbVersion " +
                "--hostname github.com")
        }

        $dest = Join-Path $tmp 'kit'
        Expand-Archive -LiteralPath $archive -DestinationPath $dest -Force -ErrorAction Stop
        $inst = Get-ChildItem -LiteralPath $dest -Recurse -Filter 'install.py' -ErrorAction Stop |
            Where-Object { $_.Directory.Name -eq 'install' } | Select-Object -First 1
        if (-not $inst) { throw 'install.ps1: the archive holds no install\install.py' }

        $check = 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'
        $py = $null
        $pyArgs = @()
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -c $check | Out-Null
            if ($LASTEXITCODE -eq 0) { $py = 'py'; $pyArgs = @('-3') }
        }
        if (-not $py) {
            $cands = @(Get-Command python -All -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*WindowsApps*' })
            foreach ($c in $cands) {
                & $c.Source -c $check | Out-Null
                if ($LASTEXITCODE -eq 0) { $py = $c.Source; break }
            }
        }
        if (-not $py) {
            throw 'install.ps1: Python 3.9 or newer is required. Install it with: winget install Python.Python.3.12, then open a new PowerShell and re-run.'
        }

        # install.py writes its plan, questions and errors to stderr: under 'Stop' a caller's 2>&1 would turn them
        # into a terminating error, so it runs with 'Continue' locally (as the gh calls in Test-UbProvenance).
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & $py @pyArgs $inst.FullName @argList
            $code = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prevEap
        }
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }

    if ($code -ne 0) {
        if ($PSCommandPath) { exit $code }
        $global:LASTEXITCODE = $code
        Write-Warning "install.py exited with code $code"
    }
}

Main $args
