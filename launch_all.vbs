Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

Sub LaunchVbs(path)
    If fso.FileExists(path) Then
        WshShell.Run "wscript.exe """ & path & """", 0, False
        WScript.Sleep 1200
    End If
End Sub

' === Aktywne boty na PC: zadne ===
' (Vred od 2026-09-28, Fred i Qred od 2026-10-18 chodza na serwerze:
'  ~/vred, ~/fred, ~/qred, docker compose. NIE odpalac ich tutaj rownolegle —
'  druga instancja na tym samym tokenie dubluje posty i rozjezdza stan
'  (cytaty Qreda trafialy do dwoch roznych quotes.json).)
' LaunchVbs "E:\Pliki\Projects\DiscordBots\Fred\fred_launch.vbs"
' LaunchVbs "E:\Pliki\Projects\DiscordBots\Qred\qred_launch.vbs"
' LaunchVbs "E:\Pliki\Projects\DiscordBots\Vred\vred_launch.vbs"

' === Zaparkowane (odpięte od utrzymania 2026-07-24). Odkomentuj, by wrócić. ===
' LaunchVbs "E:\Pliki\Projects\DiscordBots\Tred\tred_launch.vbs"
' LaunchVbs "E:\Pliki\Projects\DiscordBots\Pred\pred_launch.vbs"
' LaunchVbs "E:\Pliki\Projects\DiscordBots\Rred\rred_launch.vbs"
' LaunchVbs "E:\Pliki\Projects\DiscordBots\Ared\ared_launch.vbs"
' LaunchVbs "E:\Pliki\Projects\DiscordBots\Mred\mred_launch.vbs"
' otnaP: od 2026-10-18 to Hermes Agent na serwerze (~/otnap) na tym samym tokenie.
' Stary otnap_launch.vbs NIE odpalac — dwie bramki na jednym tokenie sie bija.
' LaunchVbs "E:\Pliki\Projects\DiscordBots\otnaP\otnap_launch.vbs"
