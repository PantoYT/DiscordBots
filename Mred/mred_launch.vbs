Set fso = CreateObject("Scripting.FileSystemObject")

dir = fso.GetParentFolderName(WScript.ScriptFullName)
python = dir & "\.venv\Scripts\python.exe"

Set WshShell = CreateObject("WScript.Shell")

cmd = "cmd.exe /c """ & _
      """" & python & """ """ & dir & "\main.py"" >> """ & dir & "\mred.log"" 2>&1" & _
      """"

WshShell.Run cmd, 0, False