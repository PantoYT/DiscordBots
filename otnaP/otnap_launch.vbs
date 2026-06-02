Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
python = dir & "\.venv\Scripts\python.exe"

Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """" & python & """ """ & dir & "\main.py"" >> """ & dir & "\otnap.log"" 2>&1", 0, False
