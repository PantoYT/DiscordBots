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
        return f"❌ cancelled{f' ({v['note'].lower()})' if v['note'] else ''}"
    if v["kind"] != "subst":
        return ""
    parts = []
    if v["subject"] != v["orig_subject"]:
        parts.append(f"instead of {v['orig_subject']}")
    if v["teacher_changed"]:
        parts.append(v["teacher"])
    if v["note"] and v["note"].lower() != "zastępstwo":
        parts.append(v["note"].lower())
    return "⚠️ substitution" + (f" — {', '.join(parts)}" if parts else "")


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
    """The register's own label (Polish, e.g. 'nieobecność') when the entry needs attention."""
    p = l.get("PresenceType") or {}
    if p.get("Removed") or not (p.get("Absence") or p.get("Late")):
        return None
    return p.get("Name") or ("late" if p.get("Late") else "absence")


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
    """[(entry, 'proposed'|'final', value)] for entries that appeared or changed."""
    out = []
    for s in summary:
        old = seen.get(str(s.get("Id"))) or [None, None]
        for i, (key, label) in enumerate((("Entry_1", "proposed"), ("Entry_2", "final"))):
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


# --------------------------------------------------------------------------- #
# Exam context — lesson topics that tell the AI what "Unit 8" actually covers
# --------------------------------------------------------------------------- #
# The teacher's description is often a bare label ("Unit 8", "Tematy: 32-35"),
# so a web search guesses a textbook and invents the scope. lesson/byPupil has
# the real topics. Lessons after the last test in that subject are the scope.

NOISE_TOPIC = re.compile(r"(?i)odbył[ao]? się|wyjści|akademi|wycieczk|\bkin[oa]\b|rekolekc|apel\b|ewakuac")
TEST_TOPIC = re.compile(r"(?i)\b(test|sprawdzian|kartkówka|praca klasowa)\b")
RETAKE = re.compile(r"(?i)poprawa|poprawk")
_WORD = re.compile(r"\w{5,}")


def _topic(l: dict) -> str:
    return (l.get("Topic") or "").strip()


def _words(text: str) -> set[str]:
    # crude stem: first 5 letters, so "ESP32" ~ "ESP32", "pętle" ~ "pętla"
    return {w[:5].lower() for w in _WORD.findall(text or "")}


def exam_context(exam: dict, lessons, max_topics: int = 25) -> dict:
    """Lesson topics behind an exam.

    own   — topics of the exam's subject, from after the last test in it
            (unless the exam is a retake), oldest first, capped at max_topics.
    other — topics the same teacher gave in OTHER subjects in that window; a
            teacher with several vocational subjects mixes them, so they are
            included only when they share a word with the exam description or
            the subject has at most one topic of its own.
    """
    subj_id = (exam.get("Subject") or {}).get("Id")
    teacher_id = (exam.get("Creator") or {}).get("Id")
    deadline = exam.get("DeadlineAt") or (exam.get("Deadline") or {}).get("Date") or "9999"
    content = exam.get("Content") or ""

    usable = sorted((l for l in lessons
                     if (l.get("DayAt") or "") < deadline and _topic(l)
                     and not NOISE_TOPIC.search(_topic(l))),
                    key=lambda l: (l.get("DayAt") or "", l.get("LessonNumber") or 0))
    own = [l for l in usable if (l.get("Subject") or {}).get("Id") == subj_id]

    since = None
    marks = [i for i, l in enumerate(own) if TEST_TOPIC.search(_topic(l))]
    if RETAKE.search(content):
        # retake: the material is what came BEFORE the original test
        if marks:
            own = own[:marks[-1]]
    elif marks and marks[-1] < len(own) - 1:
        since = own[marks[-1]]["DayAt"]
        own = own[marks[-1] + 1:]
    dedup, seen_own = [], set()          # double lessons repeat the topic
    for l in own:
        k = _topic(l).rstrip(".").lower()
        if k not in seen_own:
            seen_own.add(k)
            dedup.append(l)
    own = dedup[-max_topics:]

    other, seen = [], {_topic(l).rstrip(".").lower() for l in own}
    if teacher_id is not None:
        want = _words(content)
        for l in usable:
            if ((l.get("Subject") or {}).get("Id") == subj_id
                    or (l.get("TeacherPrimary") or {}).get("Id") != teacher_id
                    or (since and l["DayAt"] <= since)
                    or TEST_TOPIC.search(_topic(l))):
                continue
            key = _topic(l).rstrip(".").lower()
            if key in seen:
                continue
            if len(own) < 2 or want & _words(_topic(l)):
                seen.add(key)
                other.append(l)
    return {"own": own, "other": other[-max_topics:], "since": since}


def context_prompt(ctx: dict) -> str:
    """Lesson topics as prompt text; '' when there is nothing to add."""
    def line(l, with_subject=False):
        d = l["DayAt"]
        subj = f" [{(l.get('Subject') or {}).get('Name', '?').strip()}]" if with_subject else ""
        return f"- {d[8:10]}.{d[5:7]}{subj}: {_topic(l)}"

    parts = []
    if ctx["own"]:
        head = "Lesson topics from the school register"
        head += " since the last test" if ctx["since"] else ""
        parts.append(head + " (oldest first):\n" + "\n".join(line(l) for l in ctx["own"]))
    if ctx["other"]:
        parts.append("Topics the same teacher gave in other subjects (they get mixed — "
                     "use only the ones that fit the scope):\n"
                     + "\n".join(line(l, True) for l in ctx["other"]))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Missed lessons — absences plus what is coming up in those subjects
# --------------------------------------------------------------------------- #

def _pos(l: dict) -> int:
    return (l.get("TimeSlot") or {}).get("Position") or l.get("LessonNumber") or 0


def missed_lessons(lessons, since: str = "", until: str = "9999") -> list[dict]:
    """Absences (not lateness) between since and until, inclusive, in order."""
    out = [l for l in lessons
           if (p := l.get("PresenceType") or {}).get("Absence") and not p.get("Removed")
           and since <= (l.get("DayAt") or "") <= until]
    return sorted(out, key=lambda l: (l.get("DayAt") or "", _pos(l)))


def missed_followups(missed, exams, homework, today: str) -> tuple[list, list]:
    """Upcoming exams and homework in the subjects that were missed."""
    subjects = {(l.get("Subject") or {}).get("Id") for l in missed}
    ex = sorted((e for e in exams if (e.get("Subject") or {}).get("Id") in subjects
                 and exam_date(e) >= today), key=exam_date)
    hw = sorted((h for h in homework if (h.get("Subject") or {}).get("Id") in subjects
                 and (h.get("DeadlineAt") or "")[:10] >= today), key=lambda h: h.get("DeadlineAt") or "")
    return ex, hw


# --------------------------------------------------------------------------- #
# Quiz — model output -> validated questions with shuffled options
# --------------------------------------------------------------------------- #
# gpt-oss puts the right answer first almost every time (seen 2026-11-11), so
# the options are shuffled here, deterministically per quiz.

LETTERS = "ABCD"


def parse_quiz(data, seed: str) -> list[dict]:
    import random
    out = []
    for i, q in enumerate((data or {}).get("questions") or []):
        if not isinstance(q, dict):
            continue
        text, opts, ans = q.get("q"), q.get("options"), q.get("answer")
        if not (isinstance(text, str) and text.strip() and isinstance(opts, list) and len(opts) == 4
                and all(isinstance(o, str) and o.strip() for o in opts)
                and len({o.strip().lower() for o in opts}) == 4
                and isinstance(ans, int) and not isinstance(ans, bool) and 0 <= ans < 4):
            continue
        order = list(range(4))
        random.Random(f"{seed}:{i}").shuffle(order)
        out.append({"q": text.strip()[:250], "options": [opts[k].strip()[:80] for k in order],
                    "answer": order.index(ans), "why": str(q.get("why") or "").strip()[:400]})
    return out


# --------------------------------------------------------------------------- #
# Grades on the edge — close to dropping or reaching the next final grade
# --------------------------------------------------------------------------- #

EDGE = 0.15


def grade_edges(by_subject: dict[str, list], edge: float = EDGE) -> dict[str, str]:
    """{subject: 'drop:F' | 'rise:F'} for subjects within `edge` of a final-grade
    threshold (F = current predicted final). Subjects not on an edge are left out."""
    out = {}
    for s, gs in by_subject.items():
        a = raw_avg(gs)
        if a is None:
            continue
        f = final_grade(a)
        if f >= 2 and a - (f - 1 + ROUND_UP_FROM) < edge:
            out[s] = f"drop:{f}"
        elif f <= 5 and (f + ROUND_UP_FROM) - a < edge:
            out[s] = f"rise:{f}"
    return out


def edge_alerts(edges: dict[str, str], seen: dict[str, str]) -> list[tuple[str, str]]:
    """Edges that are new since the last check (each state alerts once)."""
    return sorted((s, st) for s, st in edges.items() if seen.get(s) != st)


# --------------------------------------------------------------------------- #
# Timetable snapshot — what changed between the evening reminder and morning
# --------------------------------------------------------------------------- #

def plan_signature(lessons, day: str) -> dict[str, str]:
    """{position: 'Subject (room 12) change'} for one day's timetable."""
    sig: dict[str, list[str]] = defaultdict(list)
    for l in lessons:
        if (l.get("DateAt") or (l.get("Date") or {}).get("Date")) != day:
            continue
        v = lesson_view(l)
        room = f" (room {v['room']})" if v["room"] else ""
        change = change_text(v)
        sig[str(v["pos"])].append(f"{v['subject']}{room}{' ' + change if change else ''}")
    return {k: " / ".join(sorted(v)) for k, v in sig.items()}


def plan_diff(old: dict[str, str], new: dict[str, str]) -> list[str]:
    lines = []
    for pos in sorted(set(old) | set(new), key=lambda p: int(p) if p.lstrip("-").isdigit() else 99):
        a, b = old.get(pos), new.get(pos)
        if a == b:
            continue
        if b is None:
            lines.append(f"`{pos}.` ~~{a}~~ — no longer in the plan")
        elif a is None:
            lines.append(f"`{pos}.` **{b}** — added")
        else:
            lines.append(f"`{pos}.` {a} → **{b}**")
    return lines


# --------------------------------------------------------------------------- #
# Exam changes — moved date or rewritten scope of an exam already announced
# --------------------------------------------------------------------------- #

def exam_state(exams) -> dict[str, list]:
    return {str(e.get("Id")): [exam_date(e), (e.get("Content") or "").strip()] for e in exams}


def exam_changes(exams, seen: dict) -> list[tuple[dict, str, str]]:
    """[(exam, old_date, old_content)] for announced exams whose date or scope changed.
    seen[id] = None means 'announced before we stored details' — never an alert."""
    out = []
    for e in exams:
        old = seen.get(str(e.get("Id")))
        if isinstance(old, list) and old != [exam_date(e), (e.get("Content") or "").strip()]:
            out.append((e, old[0], old[1]))
    return out


# --------------------------------------------------------------------------- #
# Calendar — exams and homework as all-day events with reminders
# --------------------------------------------------------------------------- #

TASKS_SOURCE = "vred-tasks"
REMIND_DAY_BEFORE = 6 * 60          # all-day events start at 00:00 -> 18:00 the day before
REMIND_TWO_DAYS = 30 * 60           # 18:00 two days before


def _next_day(d: str) -> str:
    from datetime import date, timedelta
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def task_events(exams, homework) -> list[dict]:
    out = []
    for e in exams:
        d = exam_date(e)
        if not d or e.get("Id") is None:
            continue
        subject = (e.get("Subject") or {}).get("Name", "?").strip()
        out.append({
            "summary": f"{e.get('Type') or 'Sprawdzian'}: {subject}",
            "description": (e.get("Content") or "").strip(),
            "start": {"date": d}, "end": {"date": _next_day(d)},
            "colorId": "11",
            "reminders": {"useDefault": False, "overrides": [
                {"method": "popup", "minutes": REMIND_DAY_BEFORE},
                {"method": "popup", "minutes": REMIND_TWO_DAYS}]},
            "extendedProperties": {"private": {"vulcanscope_id": f"exam:{e['Id']}",
                                               "vulcanscope_source": TASKS_SOURCE}},
        })
    for h in homework:
        d = (h.get("DeadlineAt") or "")[:10]
        if not d or h.get("Id") is None:
            continue
        subject = (h.get("Subject") or {}).get("Name", "?").strip()
        out.append({
            "summary": f"Homework: {subject}",
            "description": html_to_text(h.get("Content"))[:2000],
            "start": {"date": d}, "end": {"date": _next_day(d)},
            "colorId": "5",
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": REMIND_DAY_BEFORE}]},
            "extendedProperties": {"private": {"vulcanscope_id": f"hw:{h['Id']}",
                                               "vulcanscope_source": TASKS_SOURCE}},
        })
    return out


def task_event_changed(prev: dict, body: dict) -> bool:
    return (prev.get("summary") != body["summary"]
            or (prev.get("description") or "") != body["description"]
            or (prev.get("start") or {}).get("date") != body["start"]["date"]
            or prev.get("colorId") != body["colorId"])


# --------------------------------------------------------------------------- #
# Heavy week — spread the revision over the days before each exam
# --------------------------------------------------------------------------- #

HEAVY_WEEK = 3


def study_plan(exams, start: str, days: int = 8) -> dict[str, list[tuple[str, dict]]]:
    """{day: [('first pass' | 'final review', exam)]} for exams in [start, start+days).
    Final review the day before; first pass on the least loaded of the 2-3 days before."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    end = (d0 + timedelta(days=days)).isoformat()
    plan: dict[str, list] = defaultdict(list)
    for e in sorted((e for e in exams if start < exam_date(e) < end), key=exam_date):
        d = date.fromisoformat(exam_date(e))
        plan[(d - timedelta(days=1)).isoformat()].append(("final review", e))
        cands = [(d - timedelta(days=k)).isoformat() for k in (3, 2) if d - timedelta(days=k) >= d0]
        if cands:
            day = min(cands, key=lambda c: (len(plan[c]), c))
            plan[day].append(("first pass", e))
    return {k: plan[k] for k in sorted(plan) if plan[k]}


# --------------------------------------------------------------------------- #
# Topic archive — every lesson topic kept locally, searchable after the API
# stops serving last year's periods
# --------------------------------------------------------------------------- #

_PL = str.maketrans("łŁ", "lL")


def fold(text: str) -> str:
    """Lowercase without diacritics, so 'zarzadzanie' finds 'zarządzanie'."""
    import unicodedata
    t = unicodedata.normalize("NFKD", (text or "").translate(_PL))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def archive_lessons(archive: dict, lessons) -> int:
    """Merge lesson/byPupil entries into {lesson_id: [day, subject, teacher, topic]}.
    Returns how many entries were added or changed. Lessons without a topic are skipped."""
    changed = 0
    for l in lessons:
        topic = _topic(l)
        if l.get("Id") is None or not topic:
            continue
        row = [l.get("DayAt") or "", ((l.get("Subject") or {}).get("Name") or "?").strip(),
               ((l.get("TeacherPrimary") or {}).get("DisplayName") or "").strip(), topic]
        if archive.get(str(l["Id"])) != row:
            archive[str(l["Id"])] = row
            changed += 1
    return changed


def find_topics(archive: dict, query: str, subject: str = "") -> list[list[str]]:
    """Rows whose topic contains every word of the query (diacritics ignored),
    optionally only in subjects containing `subject`; newest first."""
    words, subj = fold(query).split(), fold(subject)
    rows = [r for r in archive.values()
            if all(w in fold(r[3]) for w in words) and (not subj or subj in fold(r[1]))]
    return sorted(rows, key=lambda r: r[0], reverse=True)


# --------------------------------------------------------------------------- #
# Weekly digest — grades given since a day, with the average before and after
# --------------------------------------------------------------------------- #

def week_grades(grades, since: str) -> dict[str, dict]:
    """{subject: {'new': [grade, ...], 'before': avg, 'after': avg}} for grades created since `since`."""
    by_subj: dict[str, list] = defaultdict(list)
    for g in grades:
        by_subj[grade_subject(g)].append(g)
    out = {}
    for s, gs in by_subj.items():
        new = [g for g in gs if (g.get("CreatedAt") or "")[:10] >= since]
        if new:
            out[s] = {"new": sorted(new, key=lambda g: g.get("CreatedAt") or ""),
                      "before": weighted_avg([g for g in gs if g not in new]),
                      "after": weighted_avg(gs)}
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- #
# Timing jitter — no requests at :00 sharp or on an exact period
# --------------------------------------------------------------------------- #
# Every request is signed with the device key, so the register sees each one.
# A bot hitting it at 07:00:00 and every 60.0 minutes stands out; a phone does not.

def daily_time(day: str, name: str, hour: int, minute: int = 0, spread: int = 7) -> tuple[int, int]:
    """hour:minute moved by a per-day offset in [-spread, +spread] minutes. Seeded by
    day and task name, so it stays put all day (a restart does not re-roll it)."""
    import random
    total = hour * 60 + minute + random.Random(f"{day}:{name}").randint(-spread, spread)
    return divmod(max(0, min(total, 24 * 60 - 1)), 60)


def jittered(minutes: float, spread: float = 0.25, rng=None) -> float:
    """minutes × a random factor in [1 - spread, 1 + spread]."""
    import random
    return minutes * (rng or random).uniform(1 - spread, 1 + spread)


def lucky_slots(day: str, start: tuple[int, int] = (6, 0), end: tuple[int, int] = (8, 0),
                tries: int = 3) -> list[tuple[int, int]]:
    """`tries` random check times inside [start, end), at least 15 min apart, fixed per day."""
    import random
    rng = random.Random(f"{day}:lucky")
    lo, hi = start[0] * 60 + start[1], end[0] * 60 + end[1]
    step = (hi - lo) // tries
    return [divmod(lo + i * step + rng.randint(0, max(0, step - 15)), 60) for i in range(tries)]


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
    check(change_text(v) == "⚠️ substitution — instead of Język polski, Elżbieta K", change_text(v))

    merge = dict(base, Change={"Type": 2}, Substitution={
        "Subject": {"Name": "Historia"}, "TeacherPrimary": {"DisplayName": "M B"},
        "TeacherAbsenceEffectName": "Złączenie grup"})
    check("złączenie grup" in change_text(lesson_view(merge)), "effect name shown")

    cancelled = dict(base, Change={"Type": 1}, Substitution={
        "TeacherAbsenceEffectName": "Uczniowie zwolnieni do domu", "Reason": None})
    v = lesson_view(cancelled)
    check(v["kind"] == "cancelled", "cancelled kind")
    check(change_text(v) == "❌ cancelled (uczniowie zwolnieni do domu)", change_text(v))

    # byPupil has Change but no Substitution — still flagged, no crash
    v = lesson_view(dict(base, Change={"Type": 2}))
    check(v["kind"] == "subst" and change_text(v) == "⚠️ substitution", "subst without details")

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
    check(summary_changes(summ, {}) == [(summ[0], "proposed", "4")], "proposed appears")
    check(summary_changes(summ, summary_state(summ)) == [], "no change")
    summ2 = [{"Id": 9, "Entry_1": "4", "Entry_2": "5"}]
    check([c[1:] for c in summary_changes(summ2, summary_state(summ))] == [("final", "5")], "final appears")

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

    # exam context — shapes from lesson/byPupil and exam/byPupil (2026-11)
    def les(day, subj, teacher, topic, n=1):
        return {"DayAt": day, "LessonNumber": n, "Topic": topic,
                "Subject": {"Id": subj, "Name": f"S{subj}"}, "TeacherPrimary": {"Id": teacher}}
    eng = [les("2026-10-08", 1, 10, "Review 7.", 12), les("2026-10-08", 1, 10, "Test 7.", 13),
           les("2026-10-15", 1, 10, "Better societies."), les("2026-10-22", 1, 11, "Causative forms"),
           les("2026-10-29", 1, 10, "Conditionals."), les("2026-11-01", 1, 10, "Lekcja odbyła się na 3 godz."),
           les("2026-11-05", 1, 10, "Review 8."), les("2026-11-12", 1, 10, "Test 8."),
           les("2026-10-29", 2, 10, "Unreal Past in business")]
    exam = {"DeadlineAt": "2026-11-12", "Content": "Unit 8", "Subject": {"Id": 1}, "Creator": {"Id": 10}}
    ctx = exam_context(exam, eng)
    check([_topic(l) for l in ctx["own"]] == ["Better societies.", "Causative forms", "Conditionals.", "Review 8."],
          str([_topic(l) for l in ctx["own"]]))
    check(ctx["since"] == "2026-10-08", "cut after the last test, substitute teacher kept")
    check(ctx["other"] == [], "other subject not related to 'Unit 8' and own is long enough")
    retake = dict(exam, Content="Unit 7 - poprawa")
    check([_topic(l) for l in exam_context(retake, eng)["own"]] == ["Review 7."],
          "retake: only the material before the original test")
    dbl = [les("2026-10-01", 3, 30, "Skóra."), les("2026-10-01", 3, 30, "Skóra", 2)]
    check(len(exam_context({"DeadlineAt": "2026-11-01", "Subject": {"Id": 3}}, dbl)["own"]) == 1,
          "double lesson topic deduped")
    check("since the last test" in context_prompt(ctx) and "- 15.10: Better societies." in context_prompt(ctx),
          context_prompt(ctx))

    voc = [les("2026-10-02", 5, 20, "Magistrala I2C"), les("2026-10-02", 6, 20, "Przesyłanie wartości przez port szeregowy"),
           les("2026-10-16", 5, 20, "Budowa płytki ESP32."), les("2026-10-16", 6, 20, "Budowa płytki ESP32"),
           les("2026-10-23", 6, 20, "Operatory arytmetyczne"), les("2026-10-28", 7, 20, "Flexbox"),
           les("2026-10-28", 6, 21, "Programowanie ESP32 w MicroPython")]
    ex6 = {"DeadlineAt": "2026-11-13", "Content": "ESP32 i port szeregowy", "Subject": {"Id": 6}, "Creator": {"Id": 20}}
    ctx = exam_context(ex6, voc)
    check(len(ctx["own"]) == 4 and ctx["other"] == [],
          "duplicate ESP32 topic deduped, unrelated I2C/Flexbox left out: " + str([_topic(l) for l in ctx["other"]]))
    ex7 = {"DeadlineAt": "2026-11-13", "Content": "ESP32", "Subject": {"Id": 7}, "Creator": {"Id": 20}}
    ctx = exam_context(ex7, voc)
    check([_topic(l) for l in ctx["own"]] == ["Flexbox"], "own subject")
    check({_topic(l) for l in ctx["other"]} == {"Magistrala I2C", "Przesyłanie wartości przez port szeregowy",
                                               "Budowa płytki ESP32.", "Operatory arytmetyczne"},
          "few own topics -> teacher's other subjects, deduped, other teacher excluded")
    check("[S5]" in context_prompt(ctx), "other topics labelled with their subject")
    check(context_prompt(exam_context({"DeadlineAt": "2026-11-13", "Subject": {"Id": 99}}, voc)) == "",
          "unknown subject, no creator -> no context")

    # missed lessons
    def att(i, day, subj, absent, late=False, removed=False, pos=1):
        return {"Id": i, "DayAt": day, "TimeSlot": {"Position": pos}, "Subject": {"Id": subj},
                "PresenceType": {"Absence": absent, "Late": late, "Removed": removed, "Presence": not absent}}
    al = [att(1, "2026-11-03", 1, True, pos=3), att(2, "2026-11-03", 2, False, late=True),
          att(3, "2026-11-03", 3, True, pos=1), att(4, "2026-11-04", 1, True, removed=True),
          att(5, "2026-10-01", 4, True)]
    m = missed_lessons(al, "2026-11-01")
    check([l["Id"] for l in m] == [3, 1], "absences only, sorted by position, window and removed respected")
    ex, hw = missed_followups(m, [{"DeadlineAt": "2026-11-20", "Subject": {"Id": 1}},
                                  {"DeadlineAt": "2026-11-20", "Subject": {"Id": 4}},
                                  {"DeadlineAt": "2026-11-02", "Subject": {"Id": 3}}],
                              [{"DeadlineAt": "2026-11-15T00:00:00", "Subject": {"Id": 3}}], "2026-11-11")
    check(len(ex) == 1 and len(hw) == 1, "follow-ups: upcoming, only missed subjects")

    # quiz
    raw = {"questions": [
        {"q": "Tag for 'She is a doctor'?", "options": ["isn't she?", "doesn't she?", "aren't she?", "is she?"],
         "answer": 0, "why": "Same auxiliary."},
        {"q": "bad", "options": ["a", "b", "c"], "answer": 0},
        {"q": "dup", "options": ["a", "A", "b", "c"], "answer": 1},
        {"q": "range", "options": ["a", "b", "c", "d"], "answer": 4},
        {"q": "Second?", "options": ["w", "x", "y", "z"], "answer": 2}]}
    qs = parse_quiz(raw, "seed")
    check(len(qs) == 2, "invalid questions dropped")
    check(qs[0]["options"][qs[0]["answer"]] == "isn't she?" and qs[1]["options"][qs[1]["answer"]] == "y",
          "answer follows the shuffle")
    check(parse_quiz(raw, "seed") == qs, "shuffle is deterministic per seed")
    check(any(parse_quiz(raw, f"s{k}")[0]["answer"] != 0 for k in range(10)), "right answer not always A")
    check(parse_quiz(None, "x") == [] and parse_quiz({"questions": "x"}, "x") == [], "garbage tolerated")

    # grade edges — weights 1, raw averages straight from values
    def gr(*vals):
        return [{"Value": v, "Content": str(v), "Column": {"Weight": 1}} for v in vals]
    edges = grade_edges({"A": gr(4, 4, 3, 4), "B": gr(4, 4, 4, 4), "C": gr(5, 4, 5, 4), "D": gr(1, 1),
                         "E": gr(6, 6)})
    check(edges.get("A") == "drop:4", f"3.75 is on the 4 threshold: {edges}")
    check("B" not in edges and "D" not in edges and "E" not in edges, "4.00, 1.00 and 6.00 are not on an edge")
    check("C" not in edges, "4.50 -> final 4, 0.25 below 4.75: not an edge")
    near = grade_edges({"G": gr(*([5] * 13 + [4] * 7))})
    check(near.get("G") == "rise:4", f"4.65 is 0.10 below 4.75: {near}")
    check(edge_alerts({"A": "drop:4", "G": "rise:4"}, {"A": "drop:4"}) == [("G", "rise:4")], "alert once per state")

    # plan diff
    def pl(pos, subj, room="12", change=None, day="2026-11-12"):
        return {"DateAt": day, "TimeSlot": {"Position": pos, "Display": "x"}, "Subject": {"Name": subj},
                "Room": {"Code": room}, "Change": change}
    old = plan_signature([pl(1, "Fizyka"), pl(2, "Chemia"), pl(3, "WF"), pl(1, "X", day="2026-11-13")], "2026-11-12")
    new = plan_signature([pl(1, "Fizyka"), pl(2, "Chemia", change={"Type": 1}), pl(4, "Historia")], "2026-11-12")
    d = plan_diff(old, new)
    check(len(d) == 3 and d[0].startswith("`2.`") and "WF" in d[1] and "added" in d[2], str(d))
    check(plan_diff(old, old) == [], "no change -> no lines")

    # exam changes
    e1 = {"Id": 1, "DeadlineAt": "2026-11-20", "Content": "Unit 8"}
    e2 = {"Id": 2, "DeadlineAt": "2026-11-21", "Content": "skóra"}
    st = exam_state([e1, e2])
    check(exam_changes([e1, e2], st) == [], "unchanged")
    moved = dict(e1, DeadlineAt="2026-11-27")
    check(exam_changes([moved, e2], dict(st, **{"2": None})) == [(moved, "2026-11-20", "Unit 8")],
          "moved exam reported, legacy entry (None) silent")

    # calendar task events
    ev = task_events([{"Id": 7, "DeadlineAt": "2026-11-30", "Type": "Kartkówka", "Subject": {"Name": "Fizyka "},
                       "Content": "ruch"}],
                     [{"Id": 8, "DeadlineAt": "2026-12-31T00:00:00", "Subject": {"Name": "Matematyka"},
                       "Content": "<p>zad. 1</p>"}, {"Id": 9}])
    check(len(ev) == 2 and ev[0]["summary"] == "Kartkówka: Fizyka" and ev[0]["end"]["date"] == "2026-12-01",
          str(ev[0]))
    check(ev[1]["end"]["date"] == "2027-01-01" and ev[1]["description"] == "zad. 1"
          and ev[1]["extendedProperties"]["private"]["vulcanscope_id"] == "hw:8", str(ev[1]))
    check(not task_event_changed(dict(ev[0]), ev[0]) and task_event_changed(dict(ev[0], description="x"), ev[0]),
          "change detection")

    # heavy-week study plan, Sunday 2026-11-15
    wk = [{"DeadlineAt": "2026-11-17", "Subject": {"Name": "A"}}, {"DeadlineAt": "2026-11-17", "Subject": {"Name": "B"}},
          {"DeadlineAt": "2026-11-19", "Subject": {"Name": "C"}}, {"DeadlineAt": "2026-11-16", "Subject": {"Name": "D"}},
          {"DeadlineAt": "2026-11-30", "Subject": {"Name": "late"}}]
    sp = study_plan(wk, "2026-11-15")
    flat = {(d, kind, e["Subject"]["Name"]) for d, items in sp.items() for kind, e in items}
    check(("2026-11-15", "final review", "D") in flat and ("2026-11-16", "final review", "A") in flat
          and ("2026-11-18", "final review", "C") in flat, str(sorted(flat)))
    check(("2026-11-15", "first pass", "A") in flat and ("2026-11-15", "first pass", "B") in flat,
          "first pass of a Tuesday exam lands on Sunday (only day left)")
    check(any(d in ("2026-11-16", "2026-11-17") and kind == "first pass" and n == "C" for d, kind, n in flat),
          "first pass of C on the less loaded day")
    check(not any(n == "late" for _, _, n in flat), "outside the window")

    # topic archive and search
    check(fold("Zarządzanie bazą ŁÓDŹ") == "zarzadzanie baza lodz", fold("Zarządzanie bazą ŁÓDŹ"))
    arch = {}
    src = [{"Id": 1, "DayAt": "2026-10-05", "Topic": "Flexbox – kierunek i rozmieszczanie elementów.",
            "Subject": {"Name": "strony  i aplikacje internetowe"}, "TeacherPrimary": {"DisplayName": "P W"}},
           {"Id": 2, "DayAt": "2026-10-12", "Topic": "Budowa układu strony za pomocą Flexbox.",
            "Subject": {"Name": "strony  i aplikacje internetowe"}, "TeacherPrimary": {"DisplayName": "P W"}},
           {"Id": 3, "DayAt": "2026-10-13", "Topic": "Tworzenie układów (flexbox) w aplikacji",
            "Subject": {"Name": "tworzenie aplikacji mobilnych"}, "TeacherPrimary": {"DisplayName": "P W"}},
           {"Id": 4, "DayAt": "2026-10-14", "Topic": None, "Subject": {"Name": "x"}}]
    check(archive_lessons(arch, src) == 3 and archive_lessons(arch, src) == 0, "archive adds once, skips no topic")
    check(archive_lessons(arch, [dict(src[0], Topic="Flexbox – poprawiony temat")]) == 1, "changed topic updated")
    hits = find_topics(arch, "FLEXBOX")
    check([r[0] for r in hits] == ["2026-10-13", "2026-10-12", "2026-10-05"], "newest first, case-insensitive")
    check(len(find_topics(arch, "budowa ukladu")) == 1, "all words, diacritics ignored")
    check(len(find_topics(arch, "flexbox", "mobilnych")) == 1, "subject filter")

    # weekly grades
    wg = week_grades([{"Value": 3, "Content": "3", "CreatedAt": "2026-11-02T10:00:00", "Column": {"Weight": 1, "Subject": {"Name": "Fizyka"}}},
                      {"Value": 5, "Content": "5", "CreatedAt": "2026-11-10T10:00:00", "Column": {"Weight": 1, "Subject": {"Name": "Fizyka"}}},
                      {"Value": 4, "Content": "4", "CreatedAt": "2026-10-01T10:00:00", "Column": {"Weight": 1, "Subject": {"Name": "Chemia"}}}],
                     "2026-11-09")
    check(list(wg) == ["Fizyka"] and wg["Fizyka"]["before"] == 3.0 and wg["Fizyka"]["after"] == 4.0, str(wg))

    # timing jitter
    import random as _r
    t = daily_time("2026-11-12", "reminder", 19)
    check(t == daily_time("2026-11-12", "reminder", 19), "same day, same time")
    check((18, 53) <= t <= (19, 7), f"within ±7 min: {t}")
    days = {daily_time(f"2026-11-{d:02d}", "reminder", 19) for d in range(1, 29)}
    check(len(days) > 5, "varies between days")
    check(daily_time("2026-11-12", "x", 0, 0, 7) >= (0, 0), "clamped at midnight")
    rng = _r.Random(1)
    vals = [jittered(60, 0.25, rng) for _ in range(200)]
    check(45 <= min(vals) and max(vals) <= 75 and max(vals) - min(vals) > 20, "jitter spread")
    for d in range(1, 29):
        sl = lucky_slots(f"2026-11-{d:02d}")
        mins = [h * 60 + m for h, m in sl]
        check(len(sl) == 3 and (6, 0) <= sl[0] and sl[-1] < (8, 0)
              and all(b - a >= 15 for a, b in zip(mins, mins[1:])), f"lucky slots {sl}")

    print(f"selftest OK — {checks} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
