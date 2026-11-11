<#
.SYNOPSIS
Assembla "Forensic Tools Portable" per Windows 11 (x64) in dist_win11\Forensic Tools Portable\.

.DESCRIPTION
Scarica automaticamente (e mette in cache in %USERPROFILE%\.ft-build-win):
  1. Python 3.11 Windows x64 standalone (python-build-standalone) + pip install -r requirements.txt
  2. micromamba win-64 + pacchetti conda-forge (tesseract, ghostscript, pango) estratti con bundle_tools.py
  3. Ollama Windows x64 (ollama-windows-amd64.zip)
  4. Compila "Forensic Tools.exe" (MSVC cl.exe, MinGW gcc, oppure csc.exe integrato in Windows)
  5. Copia il codice app/, i modelli da ..\models (o scarica con -PullModels) e opzionalmente genera lo .zip.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\build\build_portable.ps1
  powershell -ExecutionPolicy Bypass -File .\build\build_portable.ps1 -Zip
  powershell -ExecutionPolicy Bypass -File .\build\build_portable.ps1 -PullModels -Zip
#>
param(
    [switch]$Zip,
    [switch]$PullModels,
    [switch]$PrepareDevOnly,
    [switch]$SkipModels
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$WinRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RepoRoot = Split-Path -Parent $WinRoot
$BuildCache = Join-Path $env:USERPROFILE ".ft-build-win"
$PyRoot = Join-Path $BuildCache "py-win64"
$PyDir = Join-Path $PyRoot "python"
$PyExe = Join-Path $PyDir "python.exe"
$MambaRoot = Join-Path $BuildCache "mamba"
$MambaExe = Join-Path $BuildCache "micromamba.exe"
$CondaEnv = Join-Path $BuildCache "conda-win64"
$ToolsDir = Join-Path $BuildCache "tools-win64"
$OllamaDir = Join-Path $BuildCache "ollama-win64"

$OutBase = Join-Path $WinRoot "dist_win11"
$AppDist = Join-Path $OutBase "Forensic Tools Portable"

New-Item -ItemType Directory -Force -Path $BuildCache | Out-Null

function Step($msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}

# ── 1. Python 3.11 standalone (astral-sh/python-build-standalone) ─────────────
if (-not (Test-Path $PyExe)) {
    Step "Download Python 3.11 Windows x64 standalone"
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" -Headers @{ "User-Agent" = "ForensicToolsBuilder" }
    $asset = $rel.assets | Where-Object {
        $_.name -match "^cpython-3\.11\.\d+\+\d+-x86_64-pc-windows-msvc-install_only\.tar\.gz$"
    } | Select-Object -First 1
    if (-not $asset) {
        $asset = $rel.assets | Where-Object {
            $_.name -match "^cpython-3\.11\..*x86_64-pc-windows-msvc-shared-install_only\.tar\.gz$"
        } | Select-Object -First 1
    }
    if (-not $asset) {
        throw "Asset Python 3.11 Windows x64 non trovato nell'ultima release di python-build-standalone."
    }
    $tarPath = Join-Path $BuildCache $asset.name
    Write-Host "Scarico $($asset.name)..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tarPath
    New-Item -ItemType Directory -Force -Path $PyRoot | Out-Null
    tar -xf $tarPath -C $PyRoot
    Remove-Item $tarPath -Force
}

Step "Installazione/aggiornamento dipendenze Python (requirements.txt)"
& $PyExe -m pip install --upgrade pip
& $PyExe -m pip install -r (Join-Path $WinRoot "requirements.txt")

# ── 2. Micromamba + Tesseract / Ghostscript / Pango (conda-forge win-64) ──────
if (-not (Test-Path $MambaExe)) {
    Step "Download micromamba win-64"
    $mambaTar = Join-Path $BuildCache "micromamba.tar.bz2"
    Invoke-WebRequest -Uri "https://micro.mamba.pm/api/micromamba/win-64/latest" -OutFile $mambaTar
    $mambaTmp = Join-Path $BuildCache "mamba_tmp"
    New-Item -ItemType Directory -Force -Path $mambaTmp | Out-Null
    tar -xf $mambaTar -C $mambaTmp
    Copy-Item (Join-Path $mambaTmp "Library\bin\micromamba.exe") $MambaExe -Force
    Remove-Item $mambaTmp, $mambaTar -Recurse -Force
}

if (-not (Test-Path (Join-Path $CondaEnv "Library\bin\tesseract.exe"))) {
    Step "Creazione ambiente conda-forge win-64 (tesseract, ghostscript, pango)"
    & $MambaExe create -y -r $MambaRoot -p $CondaEnv --platform win-64 -c conda-forge tesseract ghostscript pango
}

if (-not (Test-Path (Join-Path $ToolsDir "bin\tesseract.exe"))) {
    Step "Estrazione binari, DLL Pango e tessdata_best"
    & $PyExe (Join-Path $WinRoot "build\bundle_tools.py") $CondaEnv $ToolsDir
}

if ($PrepareDevOnly) {
    Write-Host "`nAmbiente di sviluppo pronto in $BuildCache" -ForegroundColor Green
    exit 0
}

# ── 3. Ollama Windows x64 ─────────────────────────────────────────────────────
if (-not (Test-Path (Join-Path $OllamaDir "ollama.exe"))) {
    Step "Download Ollama Windows x64"
    $ollamaZip = Join-Path $BuildCache "ollama-windows-amd64.zip"
    Invoke-WebRequest -Uri "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip" -OutFile $ollamaZip
    New-Item -ItemType Directory -Force -Path $OllamaDir | Out-Null
    Expand-Archive -Path $ollamaZip -DestinationPath $OllamaDir -Force
    Remove-Item $ollamaZip -Force
}

# ── 4. Assemblaggio cartella portable ─────────────────────────────────────────
Step "Assemblaggio $AppDist"
if (Test-Path $AppDist) {
    Remove-Item $AppDist -Recurse -Force
}
New-Item -ItemType Directory -Force -Path `
    $AppDist,
    (Join-Path $AppDist "app"),
    (Join-Path $AppDist "runtime\python"),
    (Join-Path $AppDist "runtime\tools"),
    (Join-Path $AppDist "ollama"),
    (Join-Path $AppDist "data") | Out-Null

Step "Copia codice app"
$appDst = Join-Path $AppDist "app"
Copy-Item (Join-Path $WinRoot "main.py") $appDst
foreach ($folder in @("server", "core", "forensic", "ui")) {
    robocopy (Join-Path $WinRoot $folder) (Join-Path $appDst $folder) /E /XD __pycache__ /XF *.pyc | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy fallito per $folder ($LASTEXITCODE)" }
}

Step "Copia runtime Python 3.11"
robocopy $PyDir (Join-Path $AppDist "runtime\python") /E /XD __pycache__ test tests idlelib tkinter turtledemo /XF *.pyc | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy fallito per python ($LASTEXITCODE)" }

Step "Precompilazione bytecode Python"
$distPy = Join-Path $AppDist "runtime\python\python.exe"
& $distPy -m compileall -q (Join-Path $AppDist "runtime\python\Lib") $appDst

Step "Copia strumenti (Tesseract, Ghostscript, Pango)"
robocopy $ToolsDir (Join-Path $AppDist "runtime\tools") /E | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy fallito per tools ($LASTEXITCODE)" }

Step "Copia motore Ollama"
robocopy $OllamaDir (Join-Path $AppDist "ollama") /E | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy fallito per ollama ($LASTEXITCODE)" }

# ── 5. Compilazione launcher GUI "Forensic Tools.exe" ─────────────────────────
Step "Compilazione launcher nativo Windows (Forensic Tools.exe)"
$ExeOut = Join-Path $AppDist "Forensic Tools.exe"
$BuildDir = Join-Path $WinRoot "build"
$LauncherC = Join-Path $BuildDir "launcher.c"
$AppRc = Join-Path $BuildDir "app.rc"
$IcoPath = Join-Path $BuildDir "AppIcon.ico"

Push-Location $BuildDir
try {
    $cl = Get-Command cl.exe -ErrorAction SilentlyContinue
    $gcc = Get-Command gcc.exe -ErrorAction SilentlyContinue
    $csc = Get-ChildItem "$env:WINDIR\Microsoft.NET\Framework64\v4*\csc.exe" -ErrorAction SilentlyContinue | Select-Object -First 1

    if ($cl) {
        rc.exe /nologo /fo app.res $AppRc
        & $cl.Source /nologo /O2 /UNICODE /D_UNICODE $LauncherC app.res /link /SUBSYSTEM:WINDOWS shell32.lib user32.lib /OUT:$ExeOut
        Remove-Item app.res, launcher.obj -ErrorAction SilentlyContinue
    }
    elseif ($gcc) {
        $windres = Get-Command windres.exe -ErrorAction SilentlyContinue
        if ($windres) {
            & $windres.Source $AppRc -O coff -o app.res
            & $gcc.Source -O2 -municode -mwindows $LauncherC app.res -o $ExeOut -lshell32 -luser32
            Remove-Item app.res -ErrorAction SilentlyContinue
        }
        else {
            & $gcc.Source -O2 -municode -mwindows $LauncherC -o $ExeOut -lshell32 -luser32
        }
    }
    elseif ($csc) {
        Write-Host "Compilatore C non trovato: uso csc.exe (.NET Framework integrato) con LauncherFallback.cs" -ForegroundColor Yellow
        $LauncherCs = Join-Path $BuildDir "LauncherFallback.cs"
        & $csc.FullName /nologo /target:winexe /platform:x64 /optimize+ /win32icon:$IcoPath /out:$ExeOut $LauncherCs
    }
    else {
        throw "Nessun compilatore trovato (cl.exe, gcc.exe o csc.exe)."
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path $ExeOut)) {
    throw "Compilazione di Forensic Tools.exe fallita."
}

# ── 6. Modelli IA ─────────────────────────────────────────────────────────────
$ModelsDst = Join-Path $AppDist "models"
$LocalModels = Join-Path $WinRoot "models"
$ParentModels = Join-Path $RepoRoot "models"

if (-not $SkipModels) {
    if (Test-Path (Join-Path $LocalModels "manifests")) {
        Step "Copia modelli da win11\models"
        robocopy $LocalModels $ModelsDst /E | Out-Null
    }
    elseif (Test-Path (Join-Path $ParentModels "manifests")) {
        Step "Copia modelli dal repository principale (..\models)"
        robocopy $ParentModels $ModelsDst /E | Out-Null
    }
    elseif ($PullModels) {
        Step "Download modelli Ollama (qwen2.5:14b, qwen2.5:7b, llama3.2:3b, embeddinggemma)"
        New-Item -ItemType Directory -Force -Path $ModelsDst | Out-Null
        $ollamaExe = Join-Path $AppDist "ollama\ollama.exe"
        $env:OLLAMA_MODELS = $ModelsDst
        $env:OLLAMA_HOST = "127.0.0.1:11439"
        $srv = Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden -PassThru
        Start-Sleep -Seconds 3
        try {
            foreach ($m in @("qwen2.5:7b", "llama3.2:3b", "embeddinggemma", "qwen2.5:14b")) {
                Write-Host "Pull $m..."
                & $ollamaExe pull $m
            }
        }
        finally {
            Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue
        }
    }
    else {
        New-Item -ItemType Directory -Force -Path $ModelsDst | Out-Null
        Write-Warning "Cartella models\ non trovata: copia manualmente 'models\' dentro '$AppDist\models' oppure riesegui con -PullModels."
    }
}

$sizeMB = [math]::Round(((Get-ChildItem $AppDist -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host "`nPacchetto portable pronto: $AppDist ($sizeMB MB)" -ForegroundColor Green

if ($Zip) {
    Step "Creazione archivio zip portable"
    $zipPath = Join-Path $OutBase "Forensic_Tools_Win11_Portable.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path $AppDist -DestinationPath $zipPath -CompressionLevel Optimal
    Write-Host "Archivio creato: $zipPath" -ForegroundColor Green
}
