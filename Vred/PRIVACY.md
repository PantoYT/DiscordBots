Privacy Policy for Vred - Vulcan Recurrent Education Dump

Vred is a self-hosted bot. It reads data from the bot owner's own eduVULCAN
account through the unofficial eduVULCAN Hebe mobile API. All school data it
shows belongs to that account.

What Vred reads from eduVULCAN:
- Timetable, substitutions and cancelled lessons
- Exams and their topics
- Grades, grade averages, proposed and final grades
- Homework, lesson topics and attendance (present / absent / late)
- Notes (uwagi i pochwały)
- Messages received in the eduVULCAN message box (subject, sender, content,
  date). Reading them does not mark them as read in eduVULCAN.

Where that data goes:
- Timetable, exams, homework and lesson topics are posted to the configured channels of the Discord
  server Vred is in, so every member of that server can see them.
- Grades, attendance, notes and messages are private: they are sent only as
  direct messages to the bot owner, and the /srednie, /frekwencja and
  /wiadomosci commands work only for the owner and reply ephemerally. Messages can contain personal data of teachers
  and other people (names, school matters); keep the owner's DMs private.
- Everything Vred posts passes through Discord and is subject to Discord's
  own privacy policy.
- If Google Calendar sync is configured, the timetable is written to the
  owner's Google Calendar and is subject to Google's privacy policy.
- Vred does not sell or share data with anyone else.

What Vred stores on the host machine:
- Secrets: credentials.json (eduVULCAN device key), .env (Discord token),
  google_calendar_token.json. Treat them like passwords.
- State used to avoid duplicate alerts: seen_exams.json, seen_grades.json
  (grade IDs and values), seen_messages.json (message IDs only, no content),
  seen_school.json (homework and note IDs, attendance status IDs of the last
  14 days, proposed/final grade values),
  reminder_state.json, schedule_message.json.
- Discord user IDs are used only to answer commands and check the owner.

These files never leave the host and are never committed to the repository.
Deleting them removes everything Vred keeps.

By using Vred, you consent to this Privacy Policy.
