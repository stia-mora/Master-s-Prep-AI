param(
    [string]$InputRoot = ".\test data",
    [string]$OutputRoot = ".\mineru_markdown",
    [int]$ChunkPages = 20,
    [string]$Backend = "hybrid-auto-engine",
    [string]$Method = "auto",
    [string]$Lang = "ch",
    [string]$Engine = "auto",
    [string]$PythonExe = "",
    [switch]$Force,
    [switch]$DryRun,
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $scriptDir "batch_mineru_pdf_to_md.py"

$scriptArgs = @(
    $scriptPath,
    "--input-root", $InputRoot,
    "--output-root", $OutputRoot,
    "--chunk-pages", $ChunkPages,
    "--backend", $Backend,
    "--method", $Method,
    "--lang", $Lang,
    "--engine", $Engine
)

if ($Force) {
    $scriptArgs += "--force"
}
if ($DryRun) {
    $scriptArgs += "--dry-run"
}
if ($Limit -gt 0) {
    $scriptArgs += @("--limit", $Limit)
}

if ($PythonExe) {
    & $PythonExe @scriptArgs
    exit $LASTEXITCODE
}

$condaCommand = Get-Command conda -ErrorAction SilentlyContinue
if ($condaCommand) {
    $envList = conda env list 2>$null | Out-String
    if ($envList -match "(?m)^\s*data_pipeline\s+") {
        conda run --no-capture-output -n data_pipeline python @scriptArgs
        exit $LASTEXITCODE
    }
}

$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path -LiteralPath $bundledPython) {
    & $bundledPython @scriptArgs
    exit $LASTEXITCODE
}

python @scriptArgs
exit $LASTEXITCODE
