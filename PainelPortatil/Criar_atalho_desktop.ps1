$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path $desktop 'Painel.exe.lnk'))
$link.TargetPath = Join-Path $PSScriptRoot 'Iniciar Painel.bat'
$link.WorkingDirectory = $PSScriptRoot
$link.IconLocation = Join-Path $PSScriptRoot 'Painel.exe'
$link.Save()
Write-Host 'Atalho criado na area de trabalho.'
