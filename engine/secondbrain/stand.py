#!/usr/bin/env python3
"""stand.py - Stand-Block je Thema (`2ndbrain stand`, KONZEPT.md §4.3).

Das Event Log ist ein Protokoll, kein Stand: vor einem Meeting liest niemand
hundert Eintraege. Dieser Block steht direkt unter der H1 jeder Themen-Datei und
beantwortet "Wie ist der Stand?" in Sekunden:

    <!-- stand-auto:start -->
    > [!abstract] Stand TT.MM.JJJJ · 🟡 gelb
    > Drei bis fuenf Saetze: was jetzt gilt.            <- Modell, nur aus dem Log
    >
    > **Offen:** 5 Punkte (1 überfällig) · 2 Fragen · ...  <- Code
    > **Ampel:** Begruendung · **Nächster Termin:** [[...]]
    ...Live-Abfrage der offenen Punkte aus Meetings (Dataview)...
    <!-- stand-auto:end -->

Arbeitsteilung: Ampel (ampel.py), Zahlen, Termine rechnet Code - bei der Ampel
liegt das Modell daneben. Das Modell schreibt nur die Prosa, und nur neu, wenn
sich die Log-Eintraege geaendert haben (`stand_fingerprint`); die Fakten werden
bei jedem Lauf frisch berechnet. Nennt die Prosa ein Datum, das in keinem Eintrag
steht, wird sie verworfen (kein Erfinden); ohne Modell bleibt die alte Prosa stehen.
Ausserdem schreibt der Lauf die Radar-Felder ins Frontmatter des Themas (Ampel,
offene Punkte, naechster Termin, Beteiligte), nach denen die Cockpit-Ansichten sortieren.

    2ndbrain stand [--topic <slug>] [--force] [--no-llm] [--dry-run] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ampel as he
import aufgaben as tk
import vault_paths as vp

MARK_START = "<!-- stand-auto:start -->"
MARK_END = "<!-- stand-auto:end -->"
BLOCK_RE = re.compile(re.escape(MARK_START) + r".*?" + re.escape(MARK_END) + r"\n?", re.S)
MAX_EVENTS = 25
MAX_INPUT_CHARS = 7000
PROSE_KINDS = ("STATUS", "DECISION", "MILESTONE", "RISK", "DEADLINE")
_EVENT_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] \[([A-Z]+)\] (.*?)(?: \(→ \[\[[^\]]+\]\]\))?\s*$")
_ISO_IN_TEXT_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DE_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
HEALTH_LABEL = {"green": "🟢 grün", "yellow": "🟡 gelb", "red": "🔴 rot"}
PLACEHOLDER = "_Stand-Text folgt, sobald das lokale Modell erreichbar ist._"
EMPTY_TEXT = "_Noch keine Einträge im Event Log._"

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["stand", "fremde_eintraege"],
    "properties": {"stand": {"type": "string"},
                   "fremde_eintraege": {"type": "array", "items": {"type": "integer"}}},
}
SYSTEM_PROMPT = (
    "Du schreibst den aktuellen Stand eines Themas fuer einen IT-Manager, der im Meeting in "
    "wenigen Saetzen auskunftsfaehig sein muss. Nutze nur die Eintraege, erfinde nichts. "
    "Beschreibe, was JETZT gilt (Praesens), nicht die Chronik; neuere Eintraege ersetzen "
    "aeltere. Schwerpunkt: was ist live oder erreicht, was blockiert, was steht als Naechstes "
    "an, wer entscheidet - Definitions- und Modellierungsdetails nur, wenn sie das Thema "
    "selbst sind. Keine Aufgabenliste, keine Ampel-Bewertung. 3-5 kurze Saetze, Daten nur wie "
    "in den Eintraegen. fremde_eintraege: Nummern der Eintraege, die erkennbar ein anderes "
    "Thema betreffen - die ignorierst du fuer den Stand.")

TASK_QUERY = (
    "```dataview\n"
    "TASK\n"
    'FROM "active-meetings" OR "archive/meetings" OR "entities/projects" OR "entities/forums"\n'
    "WHERE !completed AND contains(outlinks, this.file.link) AND file.path != this.file.path\n"
    '  AND (meta(section).subpath = "Actions" OR meta(section).subpath = "Offene Punkte"\n'
    f'       OR {tk.ALTBESTAND_DV})\n'
    "GROUP BY file.link\n"
    "```"
)


# ------------------------------------------------------------------- Fakten

def _cap(events: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    out, size = [], 0
    for e in events[:MAX_EVENTS]:
        size += len(e[2]) + 30
        if size > MAX_INPUT_CHARS and out:
            break
        out.append(e)
    return out


def prose_events(text: str) -> list[tuple[str, str, str]]:
    """(datum, art, text) der Log-Eintraege fuer die Prosa: neueste zuerst,
    ohne Aufgaben, begrenzt auf MAX_EVENTS / MAX_INPUT_CHARS."""
    events = []
    for _, line in tk.section_lines(text, tk.EVENT_LOG_SECTION):
        m = _EVENT_RE.match(line.strip())
        if m and m.group(2) in PROSE_KINDS:
            events.append((m.group(1), m.group(2), " ".join(m.group(3).split())))
    events.sort(key=lambda e: e[0], reverse=True)
    out, size = [], 0
    for e in events[:MAX_EVENTS]:
        size += len(e[2]) + 30
        if size > MAX_INPUT_CHARS and out:
            break
        out.append(e)
    return out


def anlage_eintrag() -> str:
    """Text des Anlage-Eintrags aus der Themen-Vorlage ("Projekt angelegt"). Steht nur er im Log,
    gibt es noch nichts zu berichten - das Modell machte daraus "im Status STATUS"."""
    try:
        vorlage = (vp.TEMPLATES_DIR / "project.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in vorlage.splitlines():
        m = _EVENT_RE.match(line.strip().replace("{{date:YYYY-MM-DD}}", "2000-01-01"))
        if m:
            return " ".join(m.group(3).split())
    return ""


def last_movement(text: str) -> str:
    dates = [m.group(1) for _, l in tk.section_lines(text, tk.EVENT_LOG_SECTION)
             if (m := _EVENT_RE.match(l.strip()))]
    return max(dates) if dates else ""


def next_meetings(today: str, days: int = 30) -> dict[str, tuple[str, str, str]]:
    """{thema: (datum, notiz-stem, titel)} - naechster Termin je Thema ab heute.

    Termin-Notizen entstehen erst kurz vor dem Termin (bis zum naechsten
    Werktag, Review/Steering mit Vorlauf). Was weiter voraus liegt, kennt nur
    der Kalender - dann ohne Notiz (stem ""), Thema ueber die Reihe/den Titel."""
    import vorbereiten
    import themen as th
    out: dict[str, tuple[str, str, str]] = {}

    def take(topic: str, d: str, stem: str, title: str) -> None:
        if topic not in out or d < out[topic][0]:
            out[topic] = (d, stem, title)

    noted: set[tuple[str, str]] = set()
    root = vp.VAULT / tk.MEETINGS_SUBDIR
    for f in root.rglob("*.md") if root.is_dir() else []:
        fm = vp.read_frontmatter_head(f)
        d = str(fm.get("date") or "")[:10]
        if d < today:
            continue
        title = str(fm.get("title") or f.stem)
        noted.update((d, k) for k in th.note_keys(fm, f))
        if fm.get("skip_meeting") is True or str(fm.get("status") or "") == "entfallen":
            continue
        for topic in th.note_topics(fm):           # ein Termin kann mehrere Themen haben
            take(topic, d, f.stem, title)
    start = date.fromisoformat(today)
    window = {(start + timedelta(days=i)).isoformat() for i in range(days + 1)}
    projects, aliases = vorbereiten.load_projects(), vp.alias_map()
    for ev in vorbereiten.load_calendar_events(window):
        key = th.ag.series_key(ev["title"])
        if (ev["date"], key) in noted:
            continue                               # die Notiz gilt (Hand-Thema, entfallen)
        for topic in th.resolve(ev["title"], {}, key, projects, aliases)[0]:
            take(topic, ev["date"], "", ev["title"])
    return out


_RANK = {"red": 0, "yellow": 1, "green": 2}
_COLOR = {"red": "rot", "yellow": "gelb", "green": "grün"}


def _parent_slug(value) -> str:
    return str(value or "").strip().strip("'\"").removeprefix("[[").removesuffix("]]").split("|")[0].strip()


def facts(path: Path, open_tasks: list[tk.Task], meeting: tuple[str, str] | None,
          today: date, children: list[tuple[str, str]] | None = None) -> dict:
    health, reasons = he.assess(path, today, open_tasks)
    # Oberthema (Landkarte `parent`): die Ampel ist die schlechteste ihrer
    # Unterthemen - sonst stuende ein Dach ohne eigene Eintraege immer auf gruen.
    worse = sorted((c for c in children or [] if _RANK.get(c[1], 2) < _RANK.get(health, 2)),
                   key=lambda c: _RANK.get(c[1], 2))
    inherited = bool(worse) and health == "green"   # nur von unten - im Radar nicht doppelt
    if worse:
        via = "über Unterthemen: " + ", ".join(f"{n} ({_COLOR.get(h, h)})" for n, h in worse[:3])             + (" …" if len(worse) > 3 else "")
        reasons = [via] + (reasons if health != "green" else [])
        health = worse[0][1]
    text = path.read_text(encoding="utf-8")
    own = path.relative_to(vp.VAULT).as_posix()
    return {
        "health": health, "health_reasons": reasons, "health_inherited": inherited,
        "open": sum(1 for t in open_tasks if t.kind == tk.KIND_TASK),
        "overdue": sum(1 for t in open_tasks if t.overdue(today.isoformat())),
        "questions": sum(1 for t in open_tasks if t.kind == tk.KIND_QUESTION),
        # Punkte in anderen Dateien (Meetings, andere Themen) - nur dann hat die
        # Live-Abfrage im Block etwas zu zeigen.
        "elsewhere": sum(1 for t in open_tasks if t.path != own),
        "risks": he.recent_risks(text, today),
        "last_movement": last_movement(text),
        "next_meeting": meeting,
        # uebernommene Alt-Aufgaben, die der naechste Termin zum Klaeren vorlegt
        "altbestand": sum(1 for t in tk.tasks_in_text(text, "topic", stem=path.stem) if t.pruefen),
        # von Hand (optional): wer fuehrt/entscheidet - laesst sich nicht ableiten
        "verantwortlich": _person_link(vp.split_frontmatter(text)[0].get("verantwortlich")),
    }


def _person_link(value) -> str:
    v = str(value or "").strip()
    return v if not v or v.startswith("[[") else f"[[{v}]]"


# ------------------------------------------------------------------- Prosa

def fingerprint(events: list[tuple[str, str, str]]) -> str:
    raw = "\n".join("|".join(e) for e in events)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _dates_in(text: str) -> set[str]:
    out = {f"{y}-{m}-{d}" for y, m, d in _ISO_IN_TEXT_RE.findall(text)}
    out |= {f"{y}-{int(m):02d}-{int(d):02d}" for d, m, y in _DE_DATE_RE.findall(text)}
    return out


def validate_prose(prose: str, events: list[tuple[str, str, str]]) -> str | None:
    """Prosa oder None. Verworfen, wenn zu kurz/lang oder mit einem Datum,
    das in keinem Eintrag steht (weder als Eintragsdatum noch im Text)."""
    p = " ".join(str(prose or "").replace("<!--", "").replace("-->", "").split())
    if not (60 <= len(p) <= 1200):
        return None
    known = {e[0] for e in events} | set().union(*(_dates_in(e[2]) for e in events))
    if _dates_in(p) - known:
        return None
    return p


def write_prose(title: str, events: list[tuple[str, str, str]], llm_call) -> tuple[str | None, list[int]]:
    """(prosa|None, fremde_eintrag_nummern) - None, wenn Modell fehlt/versagt."""
    if not events or llm_call is None:
        return None, []
    lines = "\n".join(f"{i}. [{d}] [{k}] {t}" for i, (d, k, t) in enumerate(events, 1))
    user = f"Thema: {title}\nEintraege (neueste zuerst):\n{lines}"
    try:
        out, _ = llm_call([{"role": "system", "content": SYSTEM_PROMPT},
                           {"role": "user", "content": user}],
                          SCHEMA, max_tokens=700, task="stand")
    except Exception as e:
        print(f"[WARN] Stand '{title}': Modellfehler ({type(e).__name__}: {e})", file=sys.stderr)
        return None, []
    prose = validate_prose((out or {}).get("stand", ""), events)
    if prose is None:
        print(f"[WARN] Stand '{title}': Prosa verworfen (Laenge oder unbekanntes Datum)",
              file=sys.stderr)
    else:
        import schreibweisen
        prose = schreibweisen.vereinheitlichen(prose)[0]     # Namen wie auf ihren Seiten
    foreign = sorted({i for i in (out or {}).get("fremde_eintraege") or []
                      if isinstance(i, int) and 1 <= i <= len(events)})
    return prose, foreign


# ------------------------------------------------------------------- Block

def _de(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}" if len(iso) == 10 else iso


def render_block(f: dict, prose: str, today: date) -> str:
    head = f"> [!abstract] Stand {_de(today.isoformat())} · {HEALTH_LABEL.get(f['health'], f['health'])}"
    offen = f"**Offen:** {f['open']} Punkt(e)"
    if f["overdue"]:
        offen += f" ({f['overdue']} überfällig)"
    if f["questions"]:
        offen += f" · {f['questions']} Frage(n)"
    offen += f" · **Risiken (30 Tage):** {f['risks']}"
    if f["last_movement"]:
        offen += f" · **Zuletzt bewegt:** {_de(f['last_movement'])}"
    if f.get("altbestand"):
        offen += (f" · **Altbestand:** {f['altbestand']} ungeprüft — "
                  + ("Klärung im nächsten Termin" if f["next_meeting"]
                     else "Klärung im nächsten Termin zum Thema (noch keiner vorbereitet)"))
    ampel = f"**Ampel:** {'; '.join(f['health_reasons'])}"
    if f["next_meeting"]:
        d, stem, title = f["next_meeting"]
        plain = re.sub(r"[\[\]|]", "", title)          # nur im Kalender: noch keine Notiz
        ampel += (f" · **Nächster Termin:** [[{stem}|{_de(d)}]]" if stem
                  else f" · **Nächster Termin:** {_de(d)} {plain}")
    icon = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
    subline = ("**Unterthemen:** " + " · ".join(
        f"{icon.get(h, '⚪')} [[{sl}|{t}]] {o} offen" for sl, t, h, o in f["unterthemen"])
        if f.get("unterthemen") else "")
    # Wer: von Hand > laut Rolle (Personenseite) > berechnet (aktiv im Thema / darunter)
    people = [f"**Verantwortlich:** {f['verantwortlich']}"] if f.get("verantwortlich") else []
    if f.get("rollen"):
        people.append("**Rollen:** " + ", ".join(f["rollen"]))
    who = []
    if f.get("beteiligte"):
        who.append("**Beteiligt:** " + ", ".join(f["beteiligte"][:6]))
    if f.get("beteiligte_unterthemen"):
        who.append(("**in Unterthemen:** " if who else "**Beteiligt in Unterthemen:** ")
                   + ", ".join(f["beteiligte_unterthemen"][:6]))
    if who:
        people.append(" · ".join(who))
    lines = [MARK_START, head, *(f"> {l}" for l in prose.splitlines()), ">",
             f"> {offen}", f"> {ampel}", *([f"> {subline}"] if subline else []),
             *(f"> {l}" for l in people),
             "> _Automatisch aus Log und offenen Punkten (`2ndbrain stand`) — "
             "eigene Notizen außerhalb dieses Blocks._"]
    if f.get("elsewhere"):
        lines += ["", "**Offene Punkte aus Meetings und anderen Themen**", "", TASK_QUERY]
    lines.append(MARK_END)
    return "\n".join(lines) + "\n"


def existing_prose(text: str) -> str | None:
    """Prosa aus einem vorhandenen Block (zum Wiederverwenden ohne Modell)."""
    m = BLOCK_RE.search(text)
    if not m:
        return None
    out = []
    for line in m.group(0).splitlines()[2:]:
        if line.strip() == ">" or not line.startswith("> "):
            break
        out.append(line[2:])
    prose = "\n".join(out).strip()
    return prose if prose and prose != PLACEHOLDER else None


def apply_block(text: str, block: str) -> str:
    """Block ersetzen oder direkt unter die H1 setzen (sonst an den Body-Anfang)."""
    if MARK_START in text:
        return BLOCK_RE.sub(lambda _: block, text, count=1)
    fm, body = vp.split_frontmatter(text)
    lines = body.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines.insert(i + 1, "\n" + block)
            return vp.dump_frontmatter(fm, "".join(lines))
    return vp.dump_frontmatter(fm, "\n" + block + "\n" + body.lstrip("\n"))


# --------------------------------------------------------------------- Lauf

def update_topic(path: Path, open_tasks: list[tk.Task], meeting, today: date, llm_call,
                 *, force: bool = False, dry_run: bool = False,
                 involved: list[str] | None = None,
                 children: list[tuple[str, str]] | None = None,
                 sub: list[dict] | None = None,
                 involved_sub: list[str] | None = None,
                 roles: list[str] | None = None) -> dict:
    text = path.read_text(encoding="utf-8")
    fm, _ = vp.split_frontmatter(text)
    title = str(fm.get("title") or fm.get("name") or path.stem)
    events = prose_events(text)
    if len(events) == 1 and events[0][1] == "STATUS" and events[0][2] == anlage_eintrag():
        events = []                      # nur angelegt: noch nichts zu berichten
    if sub:
        # Bereich/Dach: was in den Unterthemen passiert, gehoert in seinen Stand. Sonst waere
        # ein Oberthema fast leer, obwohl dort gearbeitet wird - die Eintraege landen
        # meist beim spezifischeren Unterthema.
        kid_events = [(d, k, f"{s['title']}: {t}") for s in sub for d, k, t in s["events"][:6]]
        events = _cap(sorted(events + kid_events, key=lambda e: e[0], reverse=True))
    fp = fingerprint(events)
    report = {"slug": path.stem, "llm": False, "foreign": [], "changed": False}

    stored_fp = str(fm.get("stand_fingerprint") or "")
    prose = existing_prose(text)
    if not events:
        prose = EMPTY_TEXT
    elif force or prose is None or stored_fp != fp:
        new_prose, foreign = write_prose(title, events, llm_call)
        report["llm"] = new_prose is not None
        report["foreign"] = [{"nr": i, "datum": events[i - 1][0], "text": events[i - 1][2]}
                             for i in foreign]
        # Ohne (gueltige) neue Prosa bleibt die alte stehen; der Fingerabdruck
        # wird dann nicht gespeichert -> der naechste Lauf versucht es erneut.
        prose = new_prose or prose or PLACEHOLDER
    f = facts(path, open_tasks, meeting, today, children)
    f["beteiligte"] = involved or []
    f["beteiligte_unterthemen"] = involved_sub or []
    f["rollen"] = roles or []
    f["unterthemen"] = [(x["slug"], x["title"], x["health"], x["open"]) for x in sub or []]
    report.update(facts=f, prose=prose)
    import schreibweisen                # Namen wie auf ihren Seiten - auch Termintitel aus dem Kalender
    block = schreibweisen.vereinheitlichen(render_block(f, prose, today))[0]
    new_text = apply_block(text, block)
    store_fp = (report["llm"] or not events) and stored_fp != fp
    # Radar-Eigenschaften (00_Themen-Radar.base sortiert/filtert danach)
    radar = {"health": f["health"], "offene_punkte": f["open"], "ueberfaellig": f["overdue"],
             "fragen": f["questions"], "risiken_30t": f["risks"],
             "zuletzt_bewegt": f["last_movement"] or None,
             # fuer 01_Aufgaben ("Altbestand je Thema"), das Radar und "Heute"
             "ampel_grund": "; ".join(f["health_reasons"]) or None,
             # sortierbar: Text "health" sortiert Gelb vor Rot
             "ampel_rang": {"red": 0, "yellow": 1, "green": 2}.get(f["health"]),
             # Oberthema, dessen Ampel nur von Unterthemen kommt (Radar zeigt es nicht doppelt)
             "ampel_geerbt": True if f.get("health_inherited") else None,
             "altbestand": f.get("altbestand") or None,
             "naechster_termin": f["next_meeting"][0] if f["next_meeting"] else None,
             # berechnet (beteiligte.py) - nur "verantwortlich" pflegt man von Hand
             "beteiligte": f.get("beteiligte") or None,
             "beteiligte_unterthemen": f.get("beteiligte_unterthemen") or None,
             # Rolle auf der Personenseite nennt das Thema ("Product Ownerin Portal Nord")
             "rollen": f.get("rollen") or None}
    if store_fp:
        radar.update(stand_fingerprint=fp, stand_updated=today.isoformat())
    radar_changed = any(fm.get(k) != v for k, v in radar.items())
    report["changed"] = new_text != text or radar_changed
    if report["changed"] and not dry_run:
        if new_text != text:
            # Waehrend das Modell den Stand schrieb, kann die Datei sich geaendert haben (ein Haken im
            # Plugin, der Editor): der Block kommt in den aktuellen Text, alles andere bleibt, wie es ist.
            jetzt = path.read_text(encoding="utf-8")
            if jetzt != text:
                new_text = apply_block(jetzt, block)
            path.write_text(new_text, encoding="utf-8", newline="\n")
        if radar_changed:
            vp.update_frontmatter(path, radar)
    return report


def run(*, only: str | None = None, force: bool = False, dry_run: bool = False,
        llm_call=None, today: date | None = None) -> list[dict]:
    today = today or date.today()
    by_topic = tk.open_by_topic()
    meetings = next_meetings(today.isoformat())
    import beteiligte as bt
    involved = bt.compute(today)
    names = tk.Names()
    topics = list(vp.iter_projects())
    parent = {slug: _parent_slug(fm.get("parent")) for slug, _p, fm in topics}
    involved_sub = bt.subtree(involved, parent)
    roles = bt.role_holders(today)
    title = {slug: str(fm.get("title") or fm.get("name") or slug) for slug, _p, fm in topics}
    health = {slug: str(fm.get("health") or "green") for slug, _p, fm in topics}

    def depth(slug: str) -> int:
        d, cur = 0, parent.get(slug)
        while cur and d < 10:
            d, cur = d + 1, parent.get(cur)
        return d
    paths = {slug: p for slug, p, _fm in topics}
    opened = {slug: int(fm.get("offene_punkte") or 0) for slug, _p, fm in topics}
    total: dict[str, int] = {}
    reports = []
    for slug, path, _fm in sorted(topics, key=lambda t: -depth(t[0])):   # Unterthemen zuerst
        kid_slugs = [c for c, p in parent.items() if p == slug]
        kids = [(title[c], health[c]) for c in kid_slugs]
        if only and slug != only:
            continue
        # offen = das Unterthema samt allem darunter (ein Dach hat selbst meist 0)
        sub = [{"slug": c, "title": title[c], "health": health[c], "open": total.get(c, opened[c]),
                "events": prose_events(paths[c].read_text(encoding="utf-8"))} for c in kid_slugs]
        sub.sort(key=lambda x: ({"red": 0, "yellow": 1}.get(x["health"], 2), x["title"].lower()))
        r = update_topic(path, by_topic.get(slug, []), meetings.get(slug), today,
                         llm_call, force=force, dry_run=dry_run,
                         involved=bt.links(involved.get(slug, []), names), children=kids, sub=sub,
                         involved_sub=bt.links(involved_sub.get(slug, []), names),
                         roles=bt.role_links(roles.get(slug, []),
                                             [p for p, _ in involved.get(slug, []) + involved_sub.get(slug, [])],
                                             names))
        health[slug] = r["facts"]["health"]
        opened[slug] = r["facts"]["open"]
        total[slug] = opened[slug] + sum(total.get(c, opened[c]) for c in kid_slugs)
        reports.append(r)
    return reports


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stand-Block je Thema aktualisieren")
    ap.add_argument("--topic", help="nur dieses Thema (Slug)")
    ap.add_argument("--force", action="store_true", help="Prosa neu schreiben, auch ohne Aenderung")
    ap.add_argument("--no-llm", action="store_true", help="nur Fakten, Prosa bleibt")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    llm_call = None
    if not args.no_llm:
        import modell
        ok, reason = modell.available()
        if ok:
            llm_call = modell.complete_json
        else:
            print(f"[WARN] Modell nicht erreichbar ({reason}) - nur Fakten", file=sys.stderr)
    reports = run(only=args.topic, force=args.force, dry_run=args.dry_run, llm_call=llm_call)
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2, default=str))
        return 0
    changed = sum(1 for r in reports if r["changed"])
    written = sum(1 for r in reports if r["llm"])
    print(f"Stand: {len(reports)} Thema/Themen, {changed} aktualisiert, "
          f"{written} Stand-Text(e) neu geschrieben" + (" [DRY-RUN]" if args.dry_run else ""))
    foreign = [(r["slug"], x) for r in reports for x in r["foreign"]]
    if foreign:
        print(f"\nVermutlich falsch einsortiert ({len(foreign)}) - Kandidaten fuer die "
              "Themen-Zuordnung:")
        for slug, x in foreign[:15]:
            print(f"  {slug}: [{x['datum']}] {x['text'][:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
