# ultimate-brainstorm bootstrap installer (Windows PowerShell 5.1 or newer). KIT_SPEC 10.7.
#
# This file in the repository is a TEMPLATE. tools/release.py renders it (version, owner, SHA-256) into the
# install.ps1 release asset. Usage of the rendered file:
#   & ([scriptblock]::Create((irm https://github.com/@UB_OWNER@/ultimate-brainstorm/releases/download/v@UB_VERSION@/install.ps1))) install
#   inspect first:  irm <url> | more
# Arguments go to install/install.py (plan is the default; install asks once, or add --yes).
#
# Environment:
#   UB_RELEASE_DIR = a folder holding the release .zip (copied instead of downloaded)
#
# The script downloads one archive, checks its SHA-256 against the value embedded below, extracts it into a
# temporary folder, runs the Python installer from there and removes the temporary folder. It never edits PATH,
# profiles or anything outside that temporary folder.

function Main {
    param([string[]]$Rest)

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
    if ($Rest) { $argList = @($Rest) }

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

        & $py @pyArgs $inst.FullName @argList
        $code = $LASTEXITCODE
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
