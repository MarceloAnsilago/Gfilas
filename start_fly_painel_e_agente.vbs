Set shell = CreateObject("WScript.Shell")
basePath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

shell.Run "cmd /c """ & basePath & "\start_fly_painel_e_agente.bat""", 0, False
