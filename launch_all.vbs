Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

Sub LaunchVbs(path)
    If fso.FileExists(path) Then
        WshShell.Run "wscript.exe """ & path & """", 0, False
        WScript.Sleep 1200
    End If
End Sub

' Stare boty (własne lokalizacje)
LaunchVbs "E:\Pliki\Projects\DiscordBots\Fred\fred_launch.vbs"
LaunchVbs "E:\Pliki\Projects\DiscordBots\Qred\qred_launch.vbs"
LaunchVbs "E:\Pliki\Projects\DiscordBots\Tred\tred_launch.vbs"
LaunchVbs "E:\Pliki\Projects\DiscordBots\Vred\vred_launch.vbs"

' Nowe boty (DiscordBots\*)
LaunchVbs "E:\Pliki\Projects\DiscordBots\Pred\pred_launch.vbs"
LaunchVbs "E:\Pliki\Projects\DiscordBots\Rred\rred_launch.vbs"
LaunchVbs "E:\Pliki\Projects\DiscordBots\Ared\ared_launch.vbs"
LaunchVbs "E:\Pliki\Projects\DiscordBots\Mred\mred_launch.vbs"
LaunchVbs "E:\Pliki\Projects\DiscordBots\otnaP\otnap_launch.vbs"
