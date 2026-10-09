"""
Pure logic for Vred — no Discord, no network, so it can be selftested.

    python logic.py      # runs the selftest
"""
from __future__ import annotations

from collections import defaultdict

# --------------------------------------------------------------------------- #
# Timetable changes
# --------------------------------------------------------------------------- #
# Hebe Change.Type: 1 = cancelled, 2 = substitution. schedule/withchanges also
# carries a Substitution object with the replacement subject/teacher/room and
# a human-readable effect ("Uczniowie zwolnieni do domu", "Złączenie grup").

CHANGE_CANCELLED = 1
CHANGE_SUBST = 2


def _name(obj, key="Name"):
    return (obj or {}).get(key) if obj else None


def lesson_view(l: dict) -> dict:
    """Effective lesson after applying the substitution, plus what changed."""
    ch = l.get("Change") or {}
    sub = l.get("Substitution") or {}
    ctype = ch.get("Type") or 0
    slot = sub.get("TimeSlot") or l.get("TimeSlot") or {}
    orig_subject = _name(l.get("Subject")) or "?"
    subject = _name(sub.get("Subject")) or orig_subject
    orig_teacher = _name(l.get("TeacherPrimary"), "DisplayName")
    teacher = _name(sub.get("TeacherPrimary"), "DisplayName") or orig_teacher
    room = _name(sub.get("Room"), "Code") or _name(l.get("Room"), "Code")
    notes = [sub.get(k) for k in ("TeacherAbsenceEffectName", "Reason", "PupilNote", "Description")]
    note = "; ".join(dict.fromkeys(n.strip() for n in notes if n and n.strip()))
    if ctype == CHANGE_CANCELLED:
        kind = "cancelled"
    elif ctype or sub:
        kind = "subst"
    else:
        kind = "normal"
    return {
        "pos": slot.get("Position", 99),
        "time": slot.get("Display") or "?",
        "subject": subject,
        "orig_subject": orig_subject,
        "teacher": teacher,
        "teacher_changed": bool(teacher and orig_teacher and teacher != orig_teacher),
        "room": room,
        "kind": kind,
        "note": note,
    }


def change_text(v: dict) -> str:
    """One-line description of what changed, '' for a normal lesson."""
    if v["kind"] == "cancelled":
        return f"❌ odwołane{f' ({v['note'].lower()})' if v['note'] else ''}"
    if v["kind"] != "subst":
        return ""
    parts = []
    if v["subject"] != v["orig_subject"]:
        parts.append(f"zamiast {v['orig_subject']}")
    if v["teacher_changed"]:
        parts.append(v["teacher"])
    if v["note"] and v["note"].lower() != "zastępstwo":
        parts.append(v["note"].lower())
    return "⚠️ zastępstwo" + (f" — {', '.join(parts)}" if parts else "")


# --------------------------------------------------------------------------- #
# Grades — weighted average, same convention as VulcanScope/export.py
# --------------------------------------------------------------------------- #
PLUS_MOD = 0.5
MINUS_MOD = -0.25


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def grade_points(g: dict):
    """(value, weight) for a 1-6 grade with +/- modifiers, else (None, None)."""
    v = _num(g.get("Value"))
    if v is None or v <= 0 or v > 6:
        return None, None
    w = _num((g.get("Column") or {}).get("Weight")) or 0
    if w <= 0:
        return None, None
    content = (g.get("Content") or "").strip()
    val = float(v)
    if content.endswith("+"):
        val += PLUS_MOD
    elif content.endswith("-"):
        val += MINUS_MOD
    return val, w


def weighted_avg(grades) -> float | None:
    num = den = 0.0
    for g in grades:
        val, w = grade_points(g)
        if val is None:
            continue
        num += val * w
        den += w
    return round(num / den, 2) if den else None


def grade_subject(g: dict) -> str:
    return ((g.get("Column") or {}).get("Subject") or {}).get("Name", "?")


def subject_averages(grades) -> dict[str, float | None]:
    by_subj: dict[str, list] = defaultdict(list)
    for g in grades:
        by_subj[grade_subject(g)].append(g)
    return {s: weighted_avg(gs) for s, gs in by_subj.items()}


def grade_changes(grades, seen: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Split grades into (new, modified) against {id: content} seen earlier."""
    new, modified = [], []
    for g in grades:
        gid = str(g.get("Id"))
        if gid not in seen:
            new.append(g)
        elif seen[gid] != (g.get("Content") or ""):
            modified.append(g)
    return new, modified


# --------------------------------------------------------------------------- #
# Exams — busy days
# --------------------------------------------------------------------------- #

def exam_date(exam: dict) -> str:
    """API moved from nested Deadline.Date to flat DeadlineAt — handle both."""
    return exam.get("DeadlineAt") or (exam.get("Deadline") or {}).get("Date") or ""


def exams_by_day(exams) -> dict[str, list]:
    days: dict[str, list] = defaultdict(list)
    for e in exams:
        d = exam_date(e)
        if d:
            days[d].append(e)
    return dict(sorted(days.items()))


def busy_days(exams, threshold: int = 2) -> dict[str, list]:
    return {d: es for d, es in exams_by_day(exams).items() if len(es) >= threshold}


# --------------------------------------------------------------------------- #
# Selftest
# --------------------------------------------------------------------------- #

def selftest() -> int:
    checks = 0

    def check(cond, msg):
        nonlocal checks
        checks += 1
        assert cond, msg

    base = {"TimeSlot": {"Position": 3, "Display": "09:40-10:25"},
            "Subject": {"Name": "Język polski"}, "Room": {"Code": "69"},
            "TeacherPrimary": {"DisplayName": "Marta O"}}

    v = lesson_view(base)
    check(v["kind"] == "normal" and change_text(v) == "", "normal lesson")

    subst = dict(base, Change={"Type": 2}, Substitution={
        "Subject": {"Name": "Matematyka"}, "TeacherPrimary": {"DisplayName": "Elżbieta K"},
        "TeacherAbsenceEffectName": "Zastępstwo", "Room": None, "TimeSlot": None})
    v = lesson_view(subst)
    check(v["subject"] == "Matematyka" and v["room"] == "69", "subst takes new subject, keeps room")
    check(change_text(v) == "⚠️ zastępstwo — zamiast Język polski, Elżbieta K", change_text(v))

    merge = dict(base, Change={"Type": 2}, Substitution={
        "Subject": {"Name": "Historia"}, "TeacherPrimary": {"DisplayName": "M B"},
        "TeacherAbsenceEffectName": "Złączenie grup"})
    check("złączenie grup" in change_text(lesson_view(merge)), "effect name shown")

    cancelled = dict(base, Change={"Type": 1}, Substitution={
        "TeacherAbsenceEffectName": "Uczniowie zwolnieni do domu", "Reason": None})
    v = lesson_view(cancelled)
    check(v["kind"] == "cancelled", "cancelled kind")
    check(change_text(v) == "❌ odwołane (uczniowie zwolnieni do domu)", change_text(v))

    # byPupil has Change but no Substitution — still flagged, no crash
    v = lesson_view(dict(base, Change={"Type": 2}))
    check(v["kind"] == "subst" and change_text(v) == "⚠️ zastępstwo", "subst without details")

    def g(i, content, value, weight=1.0, subj="Fizyka"):
        return {"Id": i, "Content": content, "Value": value,
                "Column": {"Weight": weight, "Subject": {"Name": subj}}}

    check(weighted_avg([g(1, "4+", 4.0)]) == 4.5, "plus modifier")
    check(weighted_avg([g(1, "5-", 5.0)]) == 4.75, "minus modifier")
    check(weighted_avg([g(1, "3", 3.0, 1), g(2, "6", 6.0, 2)]) == 5.0, "weights")
    check(weighted_avg([g(1, "np", None), g(2, "+", 0.0)]) is None, "non-numeric ignored")
    check(weighted_avg([g(1, "5", 5.0, 0)]) is None, "zero weight ignored")
    avgs = subject_averages([g(1, "5", 5.0), g(2, "3", 3.0, subj="Chemia")])
    check(avgs == {"Fizyka": 5.0, "Chemia": 3.0}, str(avgs))

    new, mod = grade_changes([g(1, "5", 5.0), g(2, "3", 3.0), g(3, "2", 2.0)],
                             {"1": "5", "2": "1"})
    check([x["Id"] for x in new] == [3] and [x["Id"] for x in mod] == [2], "grade diff")

    exams = [{"DeadlineAt": "2026-10-02"}, {"Deadline": {"Date": "2026-10-02"}},
             {"DeadlineAt": "2026-10-01"}, {}]
    check(list(busy_days(exams)) == ["2026-10-02"], "busy days")
    check(list(exams_by_day(exams)) == ["2026-10-01", "2026-10-02"], "sorted by day")

    print(f"selftest OK — {checks} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
