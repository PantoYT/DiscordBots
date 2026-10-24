"""
Pure logic for Vred — no Discord, no network, so it can be selftested.

    python logic.py      # runs the selftest
"""
from __future__ import annotations

import html
import re
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


ROUND_UP_FROM = 0.75   # x.75 rounds up to x+1, e.g. 3.75 -> 4
RAISE_MAX = 5          # a fixed grade tops out at 5 (5+ at most); a 6 is not a realistic fix


def raw_avg(grades) -> float | None:
    """weighted_avg without rounding, so 3.749 does not pass the 3.75 threshold."""
    num = den = 0.0
    for g in grades:
        val, w = grade_points(g)
        if val is not None:
            num += val * w
            den += w
    return num / den if den else None


def final_grade(avg: float) -> int:
    """Predicted final grade: x.75 and above rounds up."""
    whole = int(avg)
    return min(6, whole + (1 if avg - whole >= ROUND_UP_FROM - 1e-9 else 0))


def grades_to_raise(grades, threshold: float) -> list[dict] | None:
    """Fewest grades to raise by one step (only those below RAISE_MAX) so the weighted
    average reaches `threshold`. [] when already there, None when out of reach.
    Every raise adds exactly one point times the weight, so taking the heaviest
    grades first gives the smallest count; on a tie the lowest grade goes first."""
    pts = [(g, *grade_points(g)) for g in grades]
    pts = [(g, v, w) for g, v, w in pts if v is not None]
    den = sum(w for _, _, w in pts)
    if not den:
        return None
    missing = threshold * den - sum(v * w for _, v, w in pts) - 1e-9
    picked = []
    for g, v, w in sorted(pts, key=lambda p: (-p[2], p[1])):
        if missing <= 0:
            break
        if int(g["Value"]) >= RAISE_MAX:
            continue
        picked.append(g)
        missing -= w
    return picked if missing <= 0 else None


def overall_plan(by_subject: dict[str, list], cel: float) -> dict:
    """Cheapest way (fewest fixed grades) to lift the mean of predicted final grades
    to `cel`. A subject may climb more than one final grade if that is cheaper.
    Returns finals, current mean, steps {subject: (new_final, grades)} and
    `best` (highest mean reachable) when the target is out of reach."""
    finals = {s: final_grade(a) for s, gs in by_subject.items() if (a := raw_avg(gs)) is not None}
    n = len(finals)
    if not n:
        return {"finals": {}, "current": None, "steps": {}, "reachable": False, "best": None}
    total = sum(finals.values())
    need = max(0, -int(-(cel * n - total - 1e-9) // 1))       # ceil
    # options per subject: k bumps -> (cost, grades), k = 0 always free
    options = {}
    for s, f in finals.items():
        opts = {0: (0, [])}
        for k in range(1, 7 - f):
            pick = grades_to_raise(by_subject[s], f + k - (1 - ROUND_UP_FROM))
            if pick is None:
                break
            opts[k] = (len(pick), pick)
        options[s] = opts
    # knapsack: dp[b] = (cost, {subject: k}) for b bumps, b capped at `need`
    dp = {0: (0, {})}
    for s, opts in options.items():
        nxt = dict(dp)
        for b, (cost, chosen) in dp.items():
            for k, (c, _) in opts.items():
                if k == 0:
                    continue
                nb = min(need, b + k)
                if nb not in nxt or cost + c < nxt[nb][0]:
                    nxt[nb] = (cost + c, dict(chosen, **{s: k}))
        dp = nxt
    if need in dp:
        steps = {s: (finals[s] + k, options[s][k][1]) for s, k in dp[need][1].items()}
        return {"finals": finals, "current": total / n, "steps": steps, "reachable": True, "best": None}
    best = total + sum(max(o) for o in options.values())
    return {"finals": finals, "current": total / n, "steps": {}, "reachable": False, "best": best / n}


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
# Messages — Content is HTML (p, br, strong, em, ul/li)
# --------------------------------------------------------------------------- #

def html_to_text(content: str) -> str:
    """Message HTML -> Discord markdown."""
    s = content or ""
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>|</div\s*>|</ul\s*>|</ol\s*>", "\n\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    s = re.sub(r"(?i)</li\s*>", "\n", s)
    s = re.sub(r"(?i)</?(strong|b)\b[^>]*>", "**", s)
    s = re.sub(r"(?i)</?(em|i)\b[^>]*>", "*", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def new_by_id(items, seen: set[str]) -> list[dict]:
    """Homework / notes not seen before (by Id)."""
    return [x for x in items if str(x.get("Id")) not in seen]


# --------------------------------------------------------------------------- #
# Attendance — lesson/byPupil PresenceType carries boolean flags
# --------------------------------------------------------------------------- #

def presence_issue(l: dict) -> str | None:
    """'nieobecność' / 'spóźnienie' style label when the entry needs attention."""
    p = l.get("PresenceType") or {}
    if p.get("Removed") or not (p.get("Absence") or p.get("Late")):
        return None
    return p.get("Name") or ("spóźnienie" if p.get("Late") else "nieobecność")


def attendance_changes(lessons, seen: dict[str, int]) -> list[dict]:
    """Lessons whose PresenceType became an absence/late since last check."""
    out = []
    for l in lessons:
        pid = (l.get("PresenceType") or {}).get("Id")
        if pid is None or seen.get(str(l.get("Id"))) == pid:
            continue
        if presence_issue(l):
            out.append(l)
    return out


def attendance_stats(lessons) -> dict[str, tuple[int, int]]:
    """{subject: (present, counted)}; '' key = all subjects together.
    Counted = entries marked present or absent; 'lekcja się nie odbyła' etc. are neither."""
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for l in lessons:
        p = l.get("PresenceType") or {}
        if p.get("Removed") or not l.get("CalculatePresence", True):
            continue
        if not (p.get("Presence") or p.get("Absence")):
            continue
        subj = (l.get("Subject") or {}).get("Name", "?")
        for key in (subj, ""):
            stats[key][1] += 1
            if p.get("Presence"):
                stats[key][0] += 1
    return {k: (v[0], v[1]) for k, v in stats.items()}


# --------------------------------------------------------------------------- #
# Proposed / final grades — grade/summary: Entry_1 = proposed, Entry_2 = final
# --------------------------------------------------------------------------- #

def summary_changes(summary, seen: dict[str, list]) -> list[tuple[dict, str, str]]:
    """[(entry, 'proponowana'|'końcowa', value)] for entries that appeared or changed."""
    out = []
    for s in summary:
        old = seen.get(str(s.get("Id"))) or [None, None]
        for i, (key, label) in enumerate((("Entry_1", "proponowana"), ("Entry_2", "końcowa"))):
            val = s.get(key)
            if val and val != old[i]:
                out.append((s, label, val))
    return out


def summary_state(summary) -> dict[str, list]:
    return {str(s.get("Id")): [s.get("Entry_1"), s.get("Entry_2")] for s in summary}


# --------------------------------------------------------------------------- #
# AI answers — Groq browser_search: 【k†Lx-Ly】 points at executed_tools[k]
# --------------------------------------------------------------------------- #

def _tool_url(t: dict) -> str | None:
    res = ((t.get("search_results") or {}).get("results") or [])
    if res and res[0].get("url"):
        return res[0]["url"]
    m = re.search(r"URL: (\S+)", t.get("output") or "")
    return m.group(1) if m else None


def cite_sources(content: str, tools: list) -> tuple[str, list[tuple[str, str]]]:
    """Replace 【k†…】 with [n] and return the opened pages as numbered sources.
    Pages opened but never cited are still listed — the answer was built on them."""
    sources: list[tuple[str, str]] = []
    number: dict[int, int] = {}
    for i, t in enumerate(tools):
        if t.get("type") != "browser.open":
            continue
        url = _tool_url(t)
        if not url:
            continue
        if url not in [u for _, u in sources]:
            title = (((t.get("search_results") or {}).get("results") or [{}])[0].get("title") or url)
            sources.append((re.sub(r"\s+-\s+viewing lines.*$", "", title).strip(), url))
        number[i] = [u for _, u in sources].index(url) + 1

    def repl(m):
        n = number.get(int(m.group(1)))
        return f"[{n}]" if n else ""

    text = re.sub(r"【(\d+)†[^】]*】", repl, content or "")
    text = re.sub(r"(\[\d+\])(?:\1)+", r"\1", text)
    return text.strip(), sources


def tables_to_lists(text: str) -> str:
    """Discord nie renderuje tabel Markdowna ani <br> — wiersz tabeli -> punkt listy."""
    out, header = [], None
    for line in (text or "").split("\n"):
        st = line.strip()
        if not (st.startswith("|") and st.endswith("|") and st.count("|") >= 3):
            header = None
            out.append(line)
            continue
        cells = [c.strip() for c in st.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        if header is None:
            header = cells
            continue
        cells = [re.sub(r"(?i)<br\s*/?>", "; ", c) for c in cells]
        cells = [c for c in cells if c and not re.fullmatch(r"\d+|\[\d+\]", c)] or cells
        out.append("• " + " — ".join(cells))
    return re.sub(r"(?i)<br\s*/?>", "\n", "\n".join(out))


def new_messages(messages, seen: set[str]) -> list[dict]:
    """Unseen, not withdrawn, oldest first."""
    fresh = [m for m in messages
             if str(m.get("Id")) not in seen and not m.get("Withdrawn")]
    return sorted(fresh, key=lambda m: m.get("SentAt") or "")


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
    check(final_grade(3.75) == 4 and final_grade(3.74) == 3 and final_grade(5.9) == 6, "x.75 rounding")
    check(raw_avg([g(1, "4", 4.0), g(2, "3", 3.0, 2)]) == 10 / 3, "raw avg")
    check(grades_to_raise([g(1, "4", 4.0)], 3.75) == [], "already there")
    two = g(4, "2", 2.0, 2)
    four = [g(1, "3", 3.0), g(2, "3", 3.0), g(3, "3", 3.0), two]
    check(grades_to_raise(four, 3.0) == [two], "heaviest first")
    check(len(grades_to_raise(four, 3.5)) == 4, "needs all four")
    check(grades_to_raise(four, 3.75) is None, "max gain 5 < 5.75 missing")
    check(grades_to_raise([g(1, "5", 5.0), g(2, "5", 5.0)], 5.25) is None, "no raising to 6")
    check(len(grades_to_raise([g(1, "4+", 4.0), g(2, "4", 4.0)], 4.75)) == 1, "4+ -> 5+ allowed")
    low = g(2, "3", 3.0)
    check(grades_to_raise([g(1, "4", 4.0), low], 4.0) == [low], "lower grade on a tie")
    check(grades_to_raise([g(1, "np", None)], 3.75) is None, "no numeric grades")

    subj = {"A": [g(1, "5", 5.0)], "B": [g(2, "4", 4.0)],
            "C": [g(3, "3", 3.0), g(4, "4", 4.0)], "D": [g(5, "4", 4.0), g(6, "4", 4.0)]}
    plan = overall_plan(subj, 4.5)       # finals 5,4,3,4 = 4.0; needs two bumps
    check(plan["finals"] == {"A": 5, "B": 4, "C": 3, "D": 4} and plan["current"] == 4.0, str(plan))
    check(plan["reachable"] and sum(len(v[1]) for v in plan["steps"].values()) == 2, str(plan["steps"]))
    check("C" in plan["steps"] and plan["steps"]["C"][0] == 4, "cheapest: one fix in C, one in B")
    check(overall_plan(subj, 4.0)["steps"] == {}, "target met")
    out = overall_plan(subj, 5.5)
    check(not out["reachable"] and out["best"] == 4.75, str(out))  # A stays 5, C only to 4
    avgs = subject_averages([g(1, "5", 5.0), g(2, "3", 3.0, subj="Chemia")])
    check(avgs == {"Fizyka": 5.0, "Chemia": 3.0}, str(avgs))

    new, mod = grade_changes([g(1, "5", 5.0), g(2, "3", 3.0), g(3, "2", 2.0)],
                             {"1": "5", "2": "1"})
    check([x["Id"] for x in new] == [3] and [x["Id"] for x in mod] == [2], "grade diff")

    exams = [{"DeadlineAt": "2026-10-02"}, {"Deadline": {"Date": "2026-10-02"}},
             {"DeadlineAt": "2026-10-01"}, {}]
    check(list(busy_days(exams)) == ["2026-10-02"], "busy days")
    check(list(exams_by_day(exams)) == ["2026-10-01", "2026-10-02"], "sorted by day")

    t = html_to_text("<p>Dzień dobry,<br>jutro <strong>wycieczka</strong>&nbsp;&amp; zbiórka</p>"
                     "<ul><li>plecak</li><li><em>woda</em></li></ul><p></p>")
    check(t == "Dzień dobry,\njutro **wycieczka** & zbiórka\n\n• plecak\n• *woda*", repr(t))
    check(html_to_text(None) == "", "empty content")

    msgs = [{"Id": "b", "SentAt": "2026-10-19T12:00"}, {"Id": "a", "SentAt": "2026-10-01T08:00"},
            {"Id": "c", "SentAt": "2026-10-02T08:00", "Withdrawn": True}, {"Id": "d", "SentAt": "2026-09-01"}]
    check([m["Id"] for m in new_messages(msgs, {"d"})] == ["a", "b"], "new messages, withdrawn skipped")

    check([x["Id"] for x in new_by_id([{"Id": 1}, {"Id": 2}], {"1"})] == [2], "new by id")

    def les(i, name, subj="Fizyka", **flags):
        pt = None if name is None else dict({"Id": hash(name) % 100, "Name": name}, **flags)
        return {"Id": i, "PresenceType": pt, "Subject": {"Name": subj}, "CalculatePresence": True}

    present = les(1, "obecność", Presence=True)
    absent  = les(2, "nieobecność", Absence=True)
    late    = les(3, "spóźnienie", Presence=True, Late=True)
    trip    = les(4, "wyjście szkolne", Presence=True)
    noclass = les(5, "lekcja się nie odbyła")
    empty   = les(6, None)
    check(presence_issue(absent) == "nieobecność" and presence_issue(late) == "spóźnienie", "issues")
    check(presence_issue(present) is None and presence_issue(empty) is None, "no issue")
    ls = [present, absent, late, trip, noclass, empty, les(7, "obecność", "Chemia", Presence=True)]
    st = attendance_stats(ls)
    check(st[""] == (4, 5) and st["Fizyka"] == (3, 4) and st["Chemia"] == (1, 1), str(st))
    ch = attendance_changes(ls, {"3": late["PresenceType"]["Id"]})
    check([l["Id"] for l in ch] == [2], "only new absence flagged")

    summ = [{"Id": 9, "Entry_1": "4", "Entry_2": None}, {"Id": 8, "Entry_1": None, "Entry_2": None}]
    check(summary_changes(summ, {}) == [(summ[0], "proponowana", "4")], "proposed appears")
    check(summary_changes(summ, summary_state(summ)) == [], "no change")
    summ2 = [{"Id": 9, "Entry_1": "4", "Entry_2": "5"}]
    check([c[1:] for c in summary_changes(summ2, summary_state(summ))] == [("końcowa", "5")], "final appears")

    tools = [{"type": "browser_search", "output": "URL: https://exa.ai/search?q=x"},
             {"type": "browser.open", "search_results": {"results": [
                 {"title": "www.matemaks.pl - viewing lines [0 - 193] of 193", "url": "https://matemaks.pl/a"}]}},
             {"type": "browser.open", "output": "L1: URL: https://cke.edu.pl/b\nL2: x"},
             {"type": "browser.open", "search_results": {"results": [{"title": "dup", "url": "https://matemaks.pl/a"}]}}]
    text, src = cite_sources("Wzór【1†L6-L8】【1†L9】. Wierzchołek【2†L6】【3†L1】【0†L2】.", tools)
    check(text == "Wzór[1]. Wierzchołek[2][1].", repr(text))
    check(src == [("www.matemaks.pl", "https://matemaks.pl/a"), ("https://cke.edu.pl/b", "https://cke.edu.pl/b")], str(src))

    tbl = "Wstęp\n| # | Pojęcie | Opis |\n|---|:---|---|\n| 1 | **Integracja** | łączenie<br>państw [1] |\n| 2 | UE | 27 państw |\nKoniec"
    check(tables_to_lists(tbl) == "Wstęp\n• **Integracja** — łączenie; państw [1]\n• UE — 27 państw\nKoniec", repr(tables_to_lists(tbl)))
    check(tables_to_lists("a | b") == "a | b", "pipe in prose untouched")

    print(f"selftest OK — {checks} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
