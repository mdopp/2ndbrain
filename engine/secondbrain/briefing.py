#!/usr/bin/env python3
"""briefing.py - Priorisiertes Themen-Briefing fuer einen Termin.

Erzeugt aus der **gesamten Historie einer Meeting-Reihe**, dem Gremium und dem
Thema des Termins eine nach Dringlichkeit sortierte Themenliste: was ist offen,
seit wann, wie oft schon vertagt, wer haengt dran - und welche Frage gehoert
deshalb gestellt.

Deterministisch: Themen sammeln, ueber Termine hinweg zusammenfuehren,
Alter/Wiederholung/Ueberfaelligkeit messen, priorisieren und eine Frage bilden -
die Einstufung bleibt nachvollziehbar.

Ein Thema wird KRITISCH, wenn eine Frist verstrichen ist, es in mehreren
Terminen derselben Reihe unveraendert wieder auftauchte, es als Risiko markiert
ist, oder das Projekt auf rot steht. Das ist der Unterschied zwischen
"hier sind 8 Follow-ups" und "das laeuft seit drei Wochen ohne Freigabe".

Ausnahme: Ein Risiko, das seit RISK_WINDOW_DAYS (30) nicht mehr erwaehnt
wurde, ist nur noch INFO ("seit X Tagen nicht mehr erwaehnt"). Risiken werden
im Vault nie explizit geschlossen; die Ampel (ampel.py) zaehlt sie nach
30 Tagen nicht mehr - das Briefing darf sie dann nicht als kritisch eskalieren.

Kein eigener Befehl: vorbereiten.py schreibt das Briefing in `## Vorbereitung`
(`build_topics()`, `render_briefing()`); `python briefing.py [pfad-teil]` zeigt die
Einstufung im Terminal.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agenda as ag
import reihen as fo
import aufgaben as tk
import vault_paths as vp
from ampel import RISK_WINDOW_DAYS

TOPIC_SIMILARITY = 0.78
# Fuer die **Historie** einer Reihe ist die Schwelle aus agenda.py (0.62) zu
# locker: zu "Checkin Lager / Versand" zoege sie "Checkin - Retouren" (0.65) und
# "Checkin - Lieferant" (0.68) mit herein und mischte fremde Reihen.
HISTORY_MIN_SIMILARITY = 0.80
CRITICAL_REPEATS = 2
IMPORTANT_AGE_DAYS = 7
# Viele Punkte tragen keine Frist (freie "Follow-up tasks:"-Bloecke meist nicht),
# und [RISK] ist selten. Damit ist das **Alter** das belastbarste Signal: ein Punkt,
# der seit einem Monat offen ist, ist kein Info-Thema.
CRITICAL_AGE_DAYS = 28
DEADLINE_SOON_DAYS = 14
MAX_TOPICS = 13
# Die Stufen werden **relativ** vergeben, nicht ueber absolute Schwellen. Sonst
# ist bei alten Punkten alles "kritisch": 13 rote Themen sind so unbrauchbar wie
# keine. Obergrenzen wie in einem lesbaren Briefing.
MAX_CRITICAL = 3
MAX_IMPORTANT = 6

PRIO_CRITICAL, PRIO_IMPORTANT, PRIO_INFO = "kritisch", "wichtig", "info"
PRIO_LABEL = {
    PRIO_CRITICAL: "🔴 KRITISCH",
    PRIO_IMPORTANT: "🟡 WICHTIG",
    PRIO_INFO: "🟢 INFO",
}

_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DEADLINE = re.compile(r"Deadline:\s*(\d{4}-\d{2}-\d{2})")
_WIKILINK = re.compile(r"\[\[[^\]]*\]\]")


def _deadline_in(text: str) -> str:
    """Frist eines Punkts. Datumsangaben in Wikilinks zaehlen nicht: jedes Event
    endet mit `(→ [[JJJJ-MM-TT-quelle]])` - als Frist gelesen, stuende fast jedes
    Thema sofort auf "Frist verstrichen"."""
    m = _DEADLINE.search(text)
    if m:
        return m.group(1)
    m = _ISO.search(_WIKILINK.sub("", text))
    return m.group(1) if m else ""


# Owner bis zum ersten Doppelpunkt oder Gedankenstrich - der Trenner muss von
# Leerraum gefolgt sein. Sonst frisst sich der Owner ueber jeden Bindestrich
# hinweg: aus "@Anna: Bereitstellung einer Kunden-zu-Rechnungsempfaenger-Liste: ..."
# wuerde owner="Anna: Bereitstellung einer Kunden" und label="zu-Rechnungsempfaenger-Liste".
_OWNER_PREFIX = re.compile(r"^@([^:—\n]{2,40}?)\s*(?:—|:)\s+(.*)$")
_LABEL_SPLIT = re.compile(r"^(.{3,70}?):\s+(.*)$", re.DOTALL)
# Serien, die keine Meetings sind
_NOT_A_MEETING = re.compile(r"^pasted[- ]image|^screenshot|^bild\b", re.IGNORECASE)


# ------------------------------------------------------------ Historie

def series_history(meeting: dict, all_meetings: list[dict]) -> list[dict]:
    """Alle frueheren Termine derselben Reihe, aeltester zuerst."""
    key = meeting.get("series") or ag.series_key(meeting.get("title", ""))
    mdate = str(meeting.get("date", ""))
    out = []
    for other in all_meetings:
        if other.get("path") == meeting.get("path"):
            continue
        if _NOT_A_MEETING.match(str(other.get("title", ""))):
            continue
        odate = str(other.get("date", ""))
        if not odate or (mdate and odate >= mdate):
            continue
        okey = other.get("series") or ag.series_key(other.get("title", ""))
        if okey == key or ag.similarity(meeting.get("title", ""),
                                        other.get("title", "")) >= HISTORY_MIN_SIMILARITY:
            out.append(other)
    out.sort(key=lambda m: str(m.get("date", "")))
    return out


# ------------------------------------------------------------ Themen

def _split_item(text: str) -> tuple[str, str, str]:
    """'@Owner — Titel: Beschreibung' -> (owner, label, context)."""
    owner = ""
    rest = text.strip()
    m = _OWNER_PREFIX.match(rest)
    if m:
        owner, rest = m.group(1).strip(), m.group(2).strip()
    m = _LABEL_SPLIT.match(rest)
    if m:
        label, context = m.group(1).strip(), m.group(2).strip()
    else:
        label, context = (rest[:70].rstrip(" .,;:") or rest), rest
    return owner, label, context


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).lower()).strip()


def collect_topics(history: list[dict], *, today: date | None = None) -> list[dict]:
    """Offene Punkte aller Vorgaenger zu Themen zusammenfuehren.

    Gleiche Sache in mehreren Terminen = ein Thema mit `times_seen > 1`. Genau
    daran haengt die Einstufung als kritisch.
    """
    today = today or date.today()
    topics: list[dict] = []

    for m in history:
        items = ag.extract_open_items(m.get("content", ""))
        mdate = str(m.get("date", ""))
        for kind, key in (("action", "actions"), ("risk", "risks"), ("decision", "decisions")):
            for raw in items[key]:
                owner, label, context = _split_item(raw)
                nlabel = _norm(label)
                if not nlabel:
                    continue
                hit = None
                for t in topics:
                    if t["kind"] != kind:
                        continue
                    if SequenceMatcher(None, nlabel, t["_norm"]).ratio() >= TOPIC_SIMILARITY:
                        hit = t
                        break
                deadline = _deadline_in(raw)
                if hit:
                    hit["times_seen"] += 1
                    hit["last_seen"] = max(hit["last_seen"], mdate)
                    hit["seen_in"].append(mdate)
                    if len(context) > len(hit["context"]):
                        hit["context"] = context
                    if owner and owner not in hit["owners"]:
                        hit["owners"].append(owner)
                    if deadline and (not hit["deadline"] or deadline < hit["deadline"]):
                        hit["deadline"] = deadline
                else:
                    topics.append({
                        "kind": kind, "label": label, "_norm": nlabel,
                        "context": context, "owners": [owner] if owner else [],
                        "first_seen": mdate, "last_seen": mdate, "seen_in": [mdate],
                        "times_seen": 1, "deadline": deadline,
                        "source": m.get("title", ""),
                    })

    for t in topics:
        t["age_days"] = _age(t["first_seen"], today)
        t["overdue"] = bool(t["deadline"] and t["deadline"] < today.isoformat())
        _mark_silence(t, today)
        t.pop("_norm", None)
    return topics


def _age(iso: str, today: date) -> int:
    try:
        return (today - date.fromisoformat(iso[:10])).days
    except (ValueError, TypeError):
        return 0


def _mark_silence(topic: dict, today: date) -> None:
    """Wie lange ein Thema nicht mehr erwaehnt wurde; Risiken ueber dem Fenster sind `stale`."""
    topic["silent_days"] = _age(topic.get("last_seen") or "", today)
    topic["stale"] = topic["kind"] == "risk" and topic["silent_days"] > RISK_WINDOW_DAYS


# ------------------------------------------------ Themen aus dem Projekt

_EVENT_RE = re.compile(
    r"^\s*-\s*\[(\d{4}-\d{2}-\d{2})\]\s*\[(ACTION|RISK|DECISION|STATUS|MILESTONE|DEADLINE)\]\s*(.*)$",
    re.MULTILINE)
_KIND_BY_TAG = {"RISK": "risk", "DECISION": "decision"}   # Aufgaben kommen aus aufgaben.py


def _topics_from_events(text: str, source: str, *, today: date) -> list[dict]:
    """Risiken und Entscheidungen aus einem `## Event Log` zu Themen zusammenfuehren
    (Aufgaben kommen ueber `_topics_from_tasks`)."""
    topics: list[dict] = []
    for mdate, tag, rest in _EVENT_RE.findall(text):
        kind = _KIND_BY_TAG.get(tag)
        if not kind:
            continue
        owner, label, context = _split_item(rest)
        nlabel = _norm(label)
        if not nlabel:
            continue
        hit = None
        for t in topics:
            if t["kind"] == kind and SequenceMatcher(None, nlabel, t["_norm"]).ratio() >= TOPIC_SIMILARITY:
                hit = t
                break
        deadline = _deadline_in(rest)
        if hit:
            hit["times_seen"] += 1
            hit["seen_in"].append(mdate)
            hit["first_seen"] = min(hit["first_seen"], mdate)
            hit["last_seen"] = max(hit["last_seen"], mdate)
            if owner and owner not in hit["owners"]:
                hit["owners"].append(owner)
        else:
            topics.append({
                "kind": kind, "label": label, "_norm": nlabel, "context": context,
                "owners": [owner] if owner else [], "first_seen": mdate,
                "last_seen": mdate, "seen_in": [mdate], "times_seen": 1,
                "deadline": deadline, "source": source, "from_project": True,
            })
    for t in topics:
        t["age_days"] = _age(t["first_seen"], today)
        t["overdue"] = bool(t["deadline"] and t["deadline"] < today.isoformat())
        _mark_silence(t, today)
        t.pop("_norm", None)
    return topics


# Prozess-Cache: ein Vault-Scan pro Vorbereitungs-Lauf, nicht einer pro Termin.
_OPEN_TASKS: dict[str, list[tk.Task]] | None = None


def _open_tasks_for(topic_slug: str) -> list[tk.Task]:
    """Offene Punkte des Themas - ohne ungeprueften Altbestand: den legt die
    Vorbereitung in einem eigenen Block zum Klaeren vor (altbestand.py)."""
    global _OPEN_TASKS
    if _OPEN_TASKS is None:
        _OPEN_TASKS = tk.open_by_topic()
    return [t for t in _OPEN_TASKS.get(topic_slug, []) if not t.pruefen]


def _topics_from_tasks(open_tasks: list[tk.Task], source: str, *, today: date) -> list[dict]:
    """Offene Punkte (aufgaben.py) als Briefing-Themen - vault-weit, also auch aus
    Meeting-Notizen anderer Reihen und aus `## Offene Punkte`. Fragen (❓)
    werden eigene Themen: die Frage selbst ist dann die Ausgangsfrage."""
    topics: list[dict] = []
    seen: set[str] = set()
    for t in open_tasks:
        k = tk.key(t)
        if not k or k in seen or not t.is_open:
            continue
        seen.add(k)
        owner = t.owner or t.owner_raw or ""
        _, label, context = _split_item(t.text)
        created = t.created or ""
        topics.append({
            "kind": "question" if t.kind == tk.KIND_QUESTION else "action",
            "label": label, "context": context, "owners": [owner] if owner else [],
            "first_seen": created, "last_seen": created,
            "seen_in": [created] if created else [], "times_seen": 1,
            "deadline": t.due or "", "source": source, "from_project": True,
        })
    for tp in topics:
        tp["age_days"] = _age(tp["first_seen"], today)
        tp["overdue"] = bool(tp["deadline"] and tp["deadline"] < today.isoformat())
        _mark_silence(tp, today)
    return topics


def forum_topics(forum_slug: str, *, today: date | None = None) -> list[dict]:
    """Beschluesse/Risiken **des Gremiums** plus dessen Entwicklungspunkte.

    Eigene Achse (reihen.py): was in einem Board offen ist, gehoert nicht dem
    Projekt, ueber das dort berichtet wurde.
    """
    today = today or date.today()
    if not forum_slug:
        return []
    path = vp.forum_path(forum_slug)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    topics = _topics_from_events(text, f"Forum {forum_slug}", today=today)
    topics += _topics_from_tasks(_open_tasks_for(forum_slug), f"Forum {forum_slug}",
                                 today=today)
    for t in topics:
        t["scope"] = "forum"

    # `## Entwicklung` als eigene Themen - ohne Datum, daher niedrige Dringlichkeit
    for d in fo.development_items(forum_slug):
        _, label, context = _split_item(d)
        topics.append({
            "kind": "decision", "label": label, "context": context, "owners": [],
            "first_seen": "", "last_seen": "", "seen_in": [], "times_seen": 1,
            "deadline": "", "age_days": 0, "overdue": False,
            "source": f"Entwicklung {forum_slug}", "scope": "forum-development",
        })
    return topics


def project_topics(project: dict | None, *, today: date | None = None) -> list[dict]:
    """Offene Punkte des Projekts: Risiken/Beschluesse aus dem `## Event Log`,
    Aufgaben und Fragen ueber aufgaben.py (vault-weit).

    Der wichtigere Themenlieferant: ein Termin gehoert zu einem Projekt, und die
    offenen Punkte des Projekts sind relevant - auch wenn sie aus einem Termin
    mit anderem Titel stammen. Reihenhistorie allein greift zu kurz, weil
    Kalendertitel und Protokolltitel selten identisch sind.
    """
    today = today or date.today()
    if not project:
        return []
    path = vp.project_path(project.get("slug", ""))
    if not path.is_file():
        return []
    source = f"Projekt {project['slug']}"
    topics = _topics_from_events(path.read_text(encoding="utf-8"), source, today=today)
    topics += _topics_from_tasks(_open_tasks_for(project["slug"]), source, today=today)
    for t in topics:
        t["scope"] = "project"
    return topics


# ------------------------------------------------------------ Priorisierung

def classify(topic: dict, project: dict | None, *, today: date | None = None) -> tuple[str, str]:
    """(prioritaet, begruendung) - regelbasiert, damit nachvollziehbar."""
    today = today or date.today()
    health = str((project or {}).get("health", "")).lower()
    reasons = []

    if topic.get("stale"):
        return PRIO_INFO, (f"seit {topic['silent_days']} Tagen nicht mehr erwähnt "
                           f"(zuletzt {topic['last_seen']}, erstmals {topic['first_seen']})")

    if topic["overdue"]:
        reasons.append(f"Frist {topic['deadline']} verstrichen")
    if topic["times_seen"] >= CRITICAL_REPEATS:
        reasons.append(f"{topic['times_seen']}× vertagt seit {topic['first_seen']}")
    if topic["age_days"] >= CRITICAL_AGE_DAYS:
        reasons.append(f"seit {topic['age_days']} Tagen offen ({topic['first_seen']})")
    if topic["kind"] == "risk":
        reasons.append("als Risiko erfasst")
    if health == "red":
        reasons.append("Projekt auf rot")
    if reasons:
        return PRIO_CRITICAL, "; ".join(reasons)

    if topic["deadline"]:
        d = _age(topic["deadline"], today)
        if -DEADLINE_SOON_DAYS <= d <= 0:
            reasons.append(f"Frist {topic['deadline']} in {abs(d)} Tagen")
    if topic["age_days"] >= IMPORTANT_AGE_DAYS:
        reasons.append(f"offen seit {topic['age_days']} Tagen")
    if topic["kind"] == "decision":
        reasons.append("Beschluss - Umsetzung prüfen")
    if topic["kind"] == "question":
        reasons.append("offene Frage")
    if health == "yellow":
        reasons.append("Projekt auf gelb")
    if reasons:
        return PRIO_IMPORTANT, "; ".join(reasons)

    return PRIO_INFO, f"offen seit {topic['age_days']} Tagen" if topic["age_days"] else "neu"


def default_question(topic: dict) -> str:
    """Die Frage, die zum Thema im Termin gestellt gehoert."""
    who = topic["owners"][0].lstrip("@") if topic["owners"] else ""
    label = topic["label"].rstrip(".")
    if topic.get("stale"):
        return f"„{label}“ wurde seit {topic['silent_days']} Tagen nicht mehr erwähnt — ist das Risiko erledigt?"
    if topic["kind"] == "question":
        q = " ".join(str(topic.get("context") or label).split()).rstrip(".")
        return q if q.endswith("?") else f"{q}?"
    if topic["kind"] == "risk":
        return f"Ist „{label}“ noch offen — und was unternehmen wir konkret?"
    if topic["kind"] == "decision":
        return f"Gilt „{label}“ noch, und ist es umgesetzt?"
    if topic["overdue"]:
        return f"„{label}“ ist über die Frist — was blockiert, und welches Datum gilt jetzt?"
    if topic["times_seen"] >= CRITICAL_REPEATS:
        return (f"„{label}“ steht zum {topic['times_seen']}. Mal auf der Agenda — "
                f"was hält auf?")
    return f"Wie steht es um „{label}“?" + (f" ({who})" if who else "")


# ------------------------------------------------------------ Rendern

def urgency(topic: dict, project: dict | None) -> float:
    """Dringlichkeitswert fuer die Rangfolge. Reine Rechnung, nachvollziehbar."""
    health = str((project or {}).get("health", "")).lower()
    if topic.get("stale"):
        # unter der Schwelle fuer "wichtig" (10): erscheint nur als INFO, wenn Platz ist
        return 5.0
    score = 0.0
    if topic["overdue"]:
        score += 100
    if topic["kind"] == "risk":
        score += 60
    elif topic["kind"] == "decision":
        score += 15
    elif topic["kind"] == "question":
        score += 10
    score += 25 * max(0, topic["times_seen"] - 1)
    score += min(40.0, topic["age_days"] * 0.6)
    if topic.get("deadline") and not topic["overdue"]:
        score += 20
    score += {"red": 30, "yellow": 10}.get(health, 0)
    # Gremienbeschluesse sind verbindlicher als Projektdetails; Entwicklung des
    # Formats ist wichtig, aber nie dringend.
    score += {"forum": 15, "forum-development": -20}.get(topic.get("scope", ""), 0)
    return score


def assign_tiers(topics: list[dict], project: dict | None) -> list[dict]:
    """Nach Dringlichkeit sortieren und die Stufen nach Rang vergeben."""
    for t in topics:
        t["score"] = urgency(t, project)
    topics.sort(key=lambda t: (-t["score"], t["first_seen"]))
    for i, t in enumerate(topics):
        if i < MAX_CRITICAL and t["score"] >= 25:
            t["priority"] = PRIO_CRITICAL
        elif i < MAX_CRITICAL + MAX_IMPORTANT and t["score"] >= 10:
            t["priority"] = PRIO_IMPORTANT
        else:
            t["priority"] = PRIO_INFO
    return topics


def build_topics(meeting: dict, all_meetings: list[dict], project: dict | None,
                 *, today: date | None = None, forum_slug: str = "") -> list[dict]:
    history = series_history(meeting, all_meetings)
    topics = collect_topics(history, today=today)
    for t in topics:
        t.setdefault("scope", "series")

    known = [_norm(t["label"]) for t in topics]

    # Forum-Themen zuerst: Gremienbeschluesse haben Vorrang vor Projektdetails
    fslug = forum_slug or meeting.get("forum") or meeting.get("series") or ""
    for ft in forum_topics(fslug, today=today):
        nft = _norm(ft["label"])
        if any(SequenceMatcher(None, nft, k).ratio() >= TOPIC_SIMILARITY for k in known):
            continue
        topics.append(ft)
        known.append(nft)

    # Projekt-Themen dazu, ohne Doppelungen
    for pt in project_topics(project, today=today):
        npt = _norm(pt["label"])
        if any(SequenceMatcher(None, npt, k).ratio() >= TOPIC_SIMILARITY for k in known):
            continue
        topics.append(pt)
        known.append(npt)
    for t in topics:
        # `classify` liefert die **Begruendung** (Frist, Wiederholung, Alter);
        # die Stufe selbst kommt aus der Rangvergabe darunter.
        _, t["why"] = classify(t, project, today=today)
        t["question"] = default_question(t)
    topics = assign_tiers(topics, project)
    return topics[:MAX_TOPICS]


def _cell(text: str, limit: int = 240) -> str:
    t = " ".join(str(text or "").split())
    if len(t) > limit:
        t = t[:limit - 1].rstrip() + "…"
    return t.replace("|", "\\|")


def render_briefing(topics: list[dict], *, partner: str = "") -> list[str]:
    """Markdown: pro Prioritaetsstufe eine Tabelle Thema | Kontext | Frage."""
    if not topics:
        return []
    an = f" an {partner}" if partner else ""
    out: list[str] = []
    n = 0
    for prio in (PRIO_CRITICAL, PRIO_IMPORTANT, PRIO_INFO):
        group = [t for t in topics if t["priority"] == prio]
        if not group:
            continue
        out += ["", f"### {PRIO_LABEL[prio]}", "",
                f"| # | Thema | Kontext | Frage{an} |",
                "|---|---|---|---|"]
        for t in group:
            n += 1
            owners = ", ".join(f"@{o.lstrip('@')}" for o in t["owners"][:2])
            ctx = _cell(t["context"])
            scope_tag = {"forum": "Gremium", "forum-development": "Entwicklung des Formats",
                         "project": "Projekt", "series": "Reihe"}.get(t.get("scope", ""), "")
            meta = f"_{t['why']}_"
            if scope_tag:
                meta += f" · {scope_tag}"
            if owners:
                meta += f" · {owners}"
            out.append(f"| {n} | **{_cell(t['label'], 70)}** | {ctx}<br>{meta} "
                       f"| {_cell(t['question'], 160)} |")
    return out


if __name__ == "__main__":
    import vorbereiten
    all_m = vorbereiten.load_meeting_files()
    projects = vorbereiten.load_projects()
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    for m in all_m:
        if target and target not in str(m["path"]):
            continue
        pr = projects.get(m.get("project"))
        tp = build_topics(m, all_m, pr)
        if not tp:
            continue
        print(f"\n=== {m['date']} {m['title'][:56]} ({len(tp)} Themen) ===")
        for t in tp:
            print(f"  {PRIO_LABEL[t['priority']]:12} {t['label'][:52]:54} {t['why'][:44]}")
        if target:
            print("\n".join(render_briefing(tp)))
