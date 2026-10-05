param(
    [string]$Compiler = 'C:\msys64\mingw64\bin\g++.exe',
    [ValidateSet('pvp', 'bench', 'puyop', 'test', 'tuner', 'speed-bench', 'fever', 'bench_fever', 'fever_battle')]
    [string]$Target = 'pvp',
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
    $sourceDirs = @('core', 'ai', 'ai/search', 'ai/search/beam', 'ai/search/dfs')
    # The battle worker links the existing evaluator without changing its source.
    if ($Target -eq 'fever_battle') { $sourceDirs = @('core') }
    if ($Target -ne 'speed-bench') { $sourceDirs += $Target }
    $sources = $sourceDirs |
        ForEach-Object { Get-ChildItem (Join-Path $PSScriptRoot "$_/*.cpp") } |
        ForEach-Object FullName
    if ($Target -eq 'fever_battle') {
        $sources += @('eval.cpp', 'quiet.cpp', 'form.cpp') |
            ForEach-Object { Join-Path $PSScriptRoot "ai/search/beam/$_" }
    }
    if ($Target -eq 'speed-bench') { $sources += Join-Path $PSScriptRoot 'test/speed_bench.cc' }
    # bench_fever shares the fever engine's search, without its main
    if ($Target -eq 'bench_fever') {
        $sources += Get-ChildItem (Join-Path $PSScriptRoot 'fever/*.cpp') |
            Where-Object Name -ne 'main.cpp' | ForEach-Object FullName
    }
    $flags = @('-std=c++20', '-O2', '-msse4.1', '-DNDEBUG', '-static', '-s')
    if ($Pext) { $flags += @('-mbmi2', '-DPEXT') }
    & $compilerPath @flags @sources '-o' $outputPath
    if ($LASTEXITCODE -ne 0) { throw "Ama $Target build failed: $LASTEXITCODE" }
    Write-Output "Built $outputPath"
} finally {
    $env:PATH = $savedPath
}
