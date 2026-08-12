Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d ""E:\Pliki\Projects\DiscordBots\Fred"" && python main.py >> ""E:\Pliki\Projects\DiscordBots\Fred\fred.log"" 2>&1", 0, False
