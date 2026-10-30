param(
    [string]$Compiler = 'C:\msys64\mingw64\bin\g++.exe',
    [ValidateSet('pvp', 'bench', 'puyop', 'test', 'tuner', 'speed-bench', 'fever', 'bench_fever', 'fever_battle')]
    [string]$Target = 'pvp',
    [string]$Output = '',
    [switch]$Pext,
    [switch]$NoPext
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
    if ($Target -ne 'speed-bench') { $sourceDirs += $Target }
    $sources = $sourceDirs |
        ForEach-Object { Get-ChildItem (Join-Path $PSScriptRoot "$_/*.cpp") } |
        ForEach-Object FullName
    if ($Target -eq 'speed-bench') { $sources += Join-Path $PSScriptRoot 'test/speed_bench.cc' }
    # bench_fever and the battle worker share the fever engine's search and builder, without its main
    if ($Target -in 'bench_fever', 'fever_battle') {
        $sources += Get-ChildItem (Join-Path $PSScriptRoot 'fever/*.cpp') |
            Where-Object Name -ne 'main.cpp' | ForEach-Object FullName
    }
    $flags = @('-std=c++20', '-O2', '-msse4.1', '-DNDEBUG', '-static', '-s')
    # The Fever engines use PEXT (BMI2) unless -NoPext: the same results, about a tenth quicker.
    if ($Pext -or (($Target -in 'fever', 'bench_fever', 'fever_battle') -and -not $NoPext)) { $flags += @('-mbmi2', '-DPEXT') }
    & $compilerPath @flags @sources '-o' $outputPath
    if ($LASTEXITCODE -ne 0) { throw "Ama $Target build failed: $LASTEXITCODE" }
    Write-Output "Built $outputPath"
    # Observed-pose operation ABI, owned and rebuilt with this checkout.
    $operationPath = Join-Path (Split-Path $outputPath) 'operations.dll'
    $operationFlags = @('-std=c++20', '-O2', '-shared', '-static', '-s')
    $operationSources = @(Join-Path $PSScriptRoot 'core/operation.cpp')
    if ($Target -in 'fever', 'fever_battle', 'bench_fever') {
        $operationFlags += @('-DAMA_FEVER_OPERATION', '-msse4.1')
        # Fever adds the triple programs of the game's ported controller (fever/control_moves.cpp), which
        # need the core's board and piece code.
        $operationSources = @(Get-ChildItem (Join-Path $PSScriptRoot 'core/*.cpp') | ForEach-Object FullName) +
            @('fever/control.cpp', 'fever/control_moves.cpp' | ForEach-Object { Join-Path $PSScriptRoot $_ })
    }
    & $compilerPath @operationFlags @operationSources '-o' $operationPath
    if ($LASTEXITCODE -ne 0) { throw "Ama operation library build failed: $LASTEXITCODE" }
    Write-Output "Built $operationPath"

} finally {
    $env:PATH = $savedPath
}
