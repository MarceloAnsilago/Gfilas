$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
Set-Location $root

$sourceExe = Join-Path $root 'dist\Painel.exe'
$sourceConfig = Join-Path $root 'dist\painel_config.json'
$portableDir = Join-Path $root 'PainelPortatil'

if (-not (Test-Path $sourceExe)) {
    throw "Nao encontrei $sourceExe. Rode build_painel_exe.bat primeiro."
}

if (-not (Test-Path $sourceConfig)) {
    throw "Nao encontrei $sourceConfig."
}

if (-not (Test-Path $portableDir)) {
    New-Item -ItemType Directory -Path $portableDir | Out-Null
}

Copy-Item -Force $sourceExe (Join-Path $portableDir 'Painel.exe')
Copy-Item -Force $sourceConfig (Join-Path $portableDir 'painel_config.json')

$launcher = @'
@echo off
cd /d "%~dp0"
start "" "%~dp0Painel.exe"
'@
Set-Content -Path (Join-Path $portableDir 'Iniciar Painel.bat') -Value $launcher -Encoding ASCII

$shortcutScript = @'
$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop 'Painel.exe.lnk'))
$link.TargetPath = Join-Path $PSScriptRoot 'Iniciar Painel.bat'
$link.WorkingDirectory = $PSScriptRoot
$link.IconLocation = Join-Path $PSScriptRoot 'Painel.exe'
$link.Save()
Write-Host 'Atalho criado na area de trabalho.'
'@
Set-Content -Path (Join-Path $portableDir 'Criar_atalho_desktop.ps1') -Value $shortcutScript -Encoding ASCII

$shortcutBat = @'
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Criar_atalho_desktop.ps1"
pause
'@
Set-Content -Path (Join-Path $portableDir 'Criar_atalho_desktop.bat') -Value $shortcutBat -Encoding ASCII

Write-Host "Pasta portatil criada em: $portableDir"
Write-Host "Copie essa pasta para o pendrive."
