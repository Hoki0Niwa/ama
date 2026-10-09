param(
    [string]$Compiler = 'C:\msys64\mingw64\bin\g++.exe',
    [ValidateSet('pvp', 'bench', 'puyop', 'test', 'tuner')]
    [string]$Target = 'pvp',
    [string]$Output = ''
)
$ErrorActionPreference = 'Stop'
$compilerPath = (Get-Command $Compiler -ErrorAction Stop).Source
$savedPath = $env:PATH
try {
    $env:PATH = (Split-Path $compilerPath) + ';' + $env:PATH
    if (-not $Output) { $Output = "bin/$Target/$Target.exe" }
    $outputPath = Join-Path $PSScriptRoot $Output
    New-Item -ItemType Directory -Force (Split-Path $outputPath) | Out-Null
    $sources = @('core', 'ai', 'ai/search', 'ai/search/beam', 'ai/search/dfs', $Target) |
        ForEach-Object { Get-ChildItem (Join-Path $PSScriptRoot "$_/*.cpp") } |
        ForEach-Object FullName
    & $compilerPath '-std=c++20' '-O2' '-msse4.1' '-DNDEBUG' '-static' '-s' @sources '-o' $outputPath
    if ($LASTEXITCODE -ne 0) { throw "Ama $Target build failed: $LASTEXITCODE" }
    Write-Output "Built $outputPath"
    # Observed-pose operation ABI, owned and rebuilt with this checkout.
    $operationPath = Join-Path (Split-Path $outputPath) 'operations.dll'
    & $compilerPath '-std=c++20' '-O2' '-shared' '-static' '-s' (Join-Path $PSScriptRoot 'core/operation.cpp') '-o' $operationPath
    if ($LASTEXITCODE -ne 0) { throw "Ama operation library build failed: $LASTEXITCODE" }
    Write-Output "Built $operationPath"

} finally {
    $env:PATH = $savedPath
}
