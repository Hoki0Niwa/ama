# Builds the Fever engines for this machine's CPU: build.ps1's sources and outputs for the targets
# fever_battle and fever, compiled with -O3 -flto -march=native and PEXT (BMI2) instead of -O2 -msse4.1.
# The replies are the same; the searches take about 1/1.6 to 1/1.8 of the time (measured in PPFAI,
# doc/STAGE2.md "Amaのビルド条件による高速化"). The executables run on this CPU only: build them again on
# another machine. The operation library is built as build.ps1 builds it. Tsu targets are not touched.
param(
    [string]$Compiler = 'C:\msys64\mingw64\bin\g++.exe',
    [ValidateSet('fever_battle', 'fever')]
    [string[]]$Target = @('fever_battle', 'fever')
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$compilerPath = (Get-Command $Compiler -ErrorAction Stop).Source
$flags = @('-std=c++20', '-O3', '-flto=auto', '-march=native', '-mbmi2', '-DPEXT', '-DNDEBUG', '-static', '-s')
$savedPath = $env:PATH
try {
    $env:PATH = (Split-Path $compilerPath) + ';' + $env:PATH
    foreach ($name in $Target) {
        $outputPath = Join-Path $root "bin/$name/$name.exe"
        New-Item -ItemType Directory -Force (Split-Path $outputPath) | Out-Null
        # The source sets of build.ps1 for these targets
        $sources = @('core', 'ai', 'ai/search', 'ai/search/beam', 'ai/search/dfs', $name) |
            ForEach-Object { Get-ChildItem (Join-Path $root "$_/*.cpp") } | ForEach-Object FullName
        if ($name -eq 'fever_battle') {
            $sources += Get-ChildItem (Join-Path $root 'fever/*.cpp') | Where-Object Name -ne 'main.cpp' | ForEach-Object FullName
        }
        & $compilerPath @flags @sources '-o' $outputPath
        if ($LASTEXITCODE -ne 0) { throw "native $name build failed: $LASTEXITCODE" }
        Write-Output "Built $outputPath (native)"
        $operationPath = Join-Path (Split-Path $outputPath) 'operations.dll'
        $operationFlags = @('-std=c++20', '-O2', '-shared', '-static', '-s', '-DAMA_FEVER_OPERATION', '-msse4.1')
        $operationSources = @(Get-ChildItem (Join-Path $root 'core/*.cpp') | ForEach-Object FullName) +
            @('fever/control.cpp', 'fever/control_moves.cpp' | ForEach-Object { Join-Path $root $_ })
        & $compilerPath @operationFlags @operationSources '-o' $operationPath
        if ($LASTEXITCODE -ne 0) { throw "operation library build failed: $LASTEXITCODE" }
        Write-Output "Built $operationPath"
    }
} finally {
    $env:PATH = $savedPath
}
