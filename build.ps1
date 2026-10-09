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
    if ($Pext) { $flags += @('-mbmi2', '-DPEXT') }
    & $compilerPath @flags @sources '-o' $outputPath
    if ($LASTEXITCODE -ne 0) { throw "Ama $Target build failed: $LASTEXITCODE" }
    Write-Output "Built $outputPath"
    # Observed-pose operation ABI, owned and rebuilt with this checkout.
    $operationPath = Join-Path (Split-Path $outputPath) 'operations.dll'
    $operationFlags = @('-std=c++20', '-O2', '-shared', '-static', '-s')
    if ($Target -in 'fever', 'fever_battle', 'bench_fever') { $operationFlags += '-DAMA_FEVER_OPERATION' }
    & $compilerPath @operationFlags (Join-Path $PSScriptRoot 'core/operation.cpp') '-o' $operationPath
    if ($LASTEXITCODE -ne 0) { throw "Ama operation library build failed: $LASTEXITCODE" }
    Write-Output "Built $operationPath"

} finally {
    $env:PATH = $savedPath
}
