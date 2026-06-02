Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
python = dir & "\.venv\Scripts\python.exe"

Set WshShell = CreateObject("WScript.Shell")

cmd = "cmd.exe /c """"" & python & _
      """ """ & dir & "\main.py"" >> """ & _
      dir & "\pred.log"" 2>&1"""

WshShell.Run cmd, 0, False