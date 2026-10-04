param(
    [string]$Compiler = 'C:\msys64\mingw64\bin\g++.exe',
    [ValidateSet('puyop', 'test', 'tuner', 'speed-bench')]
    [string]$Target = 'puyop',
    [string]$Output = '',
    [switch]$Pext
)
$ErrorActionPreference = 'Stop'
$compilerPath = (Get-Command $Compiler -ErrorAction Stop).Source
$savedPath = $env:PATH
try {
    $env:PATH = (Split-Path $compilerPath) + ';' + $env:PATH
    if (-not $Output) { $Output = "bin/$Target/$Target.exe" }
    $outputPath = Join-Path $PSScriptRoot $Output
    New-Item -ItemType Directory -Force (Split-Path $outputPath) | Out-Null
    $sources = @('core', 'ai', 'ai/search', 'ai/search/beam', 'ai/search/dfs') |
        ForEach-Object { Get-ChildItem (Join-Path $PSScriptRoot "$_/*.cpp") } |
        ForEach-Object FullName
    $main = if ($Target -eq 'speed-bench') { 'test/speed_bench.cc' } else { "$Target/main.cpp" }
    $flags = @('-std=c++20', '-O2', '-msse4.1', '-DNDEBUG', '-static', '-s')
    if ($Pext) { $flags += @('-mbmi2', '-DPEXT') }
    & $compilerPath @flags @sources (Join-Path $PSScriptRoot $main) '-o' $outputPath
    if ($LASTEXITCODE -ne 0) { throw "Ama $Target build failed: $LASTEXITCODE" }
    Write-Output "Built $outputPath"
} finally {
    $env:PATH = $savedPath
}
