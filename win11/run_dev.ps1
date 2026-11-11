# Avvio in sviluppo di Forensic Tools (Windows 11)
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildDir = Join-Path $env:USERPROFILE ".ft-build-win"
$PyExe = Join-Path $BuildDir "py-win64\python\python.exe"
$ToolsBin = Join-Path $BuildDir "tools-win64\bin"

if (-not (Test-Path $PyExe)) {
    Write-Error "Runtime Python dev non trovato in $PyExe. Esegui prima build\build_portable.ps1 -PrepareDevOnly"
    exit 1
}

if (Test-Path $ToolsBin) {
    $env:PATH = "$ToolsBin;$env:PATH"
    $env:WEASYPRINT_DLL_DIRECTORIES = $ToolsBin
}

& $PyExe (Join-Path $Dir "main.py") @args
