#!/usr/bin/env python3
"""aufgaben.py - Offene Punkte: Format, Parser, Renderer, Index (KONZEPT.md §4.1).

Einziger Ort der Engine, der die Aufgaben-Syntax kennt - jedes Werkzeug liest und
schreibt Punkte ueber dieses Modul, damit "Was ist offen, wen frage ich was?" ueberall
gleich beantwortet wird. Das Plugin liest mit einer Uebertragung
(plugin/src/core/aufgaben.ts), die dasselbe liefern muss.

Kanonisches Format (eine Person, eine Taetigkeit je Zeile):

    - [ ] Text — [[owner|Name]] · [[thema|Titel]] 📅 2026-10-03 ➕ 2026-09-14 (→ [[quelle]])
    - [ ] ❓ Frage? — an [[person|Name]] · [[thema|Titel]] ➕ 2026-08-03
    - [ ] Text — Max (?) · [[thema|Titel]]        Person unaufgeloest -> Rueckfrage
    - [x] Text — [[owner|Name]] ➕ 2026-09-14 ✅ 2026-09-30

    📅 Frist (nur wenn genannt) · ➕ Entstehung (Datum der Quelle) · ✅ erledigt
    [x] erledigt · [-] verworfen · jedes andere Zeichen gilt als offen

Kurzform zum Eintippen (so schlaegt es die Termin-Notiz vor), Datum = Frist:

    - [ ] Was — @wer — 2026-10-01

Gelesen wird nur in den zustaendigen Abschnitten: `## Actions` in Termin-
Notizen, `## Offene Punkte` in Themen-Dateien. In `## Vorbereitung` stehen
Playbook-Checklisten mit '—' im Text - die sind keine Aufgaben, `[ACTION]`-Zeilen
im Event Log auch nicht.

Uebernommene Alt-Aufgaben, die noch niemand geprueft hat, stehen am Ende von
`## Offene Punkte` im Unterabschnitt `### Altbestand – im nächsten Termin prüfen`
(Task.pruefen, Uebergang). Der naechste Termin zum Thema legt sie vor; nach seiner
Nachbereitung loest `altbestand.py` den Unterabschnitt auf.

    2ndbrain aufgaben [--open] [--owner SLUG] [--topic SLUG] [--json | --summary]
    2ndbrain aufgaben --done PFAD --line N [--text TEXT]      # einen Punkt abhaken
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

KIND_TASK, KIND_QUESTION = "aufgabe", "frage"
QUESTION_MARK = "❓"
DUE, CREATED, DONE = "📅", "➕", "✅"
SEP_META = " — "
SEP_TOPIC = " · "
UNRESOLVED = "(?)"

MEETING_SECTION = "## Actions"
TOPIC_SECTION = "## Offene Punkte"
EVENT_LOG_SECTION = "## Event Log"
DESCRIPTION_SECTION = "## Beschreibung"
MEETINGS_SUBDIR = "active-meetings"
ALTBESTAND_TITLE = "Altbestand – im nächsten Termin prüfen"
ALTBESTAND_HEADING = f"### {ALTBESTAND_TITLE}"
# Dataview normalisiert Abschnittsnamen in Links: alles ausser Buchstaben, Ziffern, "_"
# und "-" wird zu Leerzeichen ("Altbestand – im ..." -> "Altbestand im ..."). Ein Vergleich
# auf den exakten Titel trifft deshalb nie - Abfragen pruefen nur das Stichwort.
ALTBESTAND_DV = 'contains(meta(section).subpath, "Altbestand")'
ALTBESTAND_INTRO = ("_Übernommen aus den alten Aufgaben-Zeilen im Event Log ({date}). Der "
                    "nächste Termin zum Thema legt sie zum Klären vor; nach seiner "
                    "Nachbereitung gilt der Rest als geprüft._")
_ALTBESTAND_INTRO_START = ALTBESTAND_INTRO.split("(")[0]
NOTE_PREFIX = "    - "                     # Unterpunkt einer Aufgabe (Beleg, Hinweis)
HINT_PREFIX = NOTE_PREFIX + "Hinweis:"     # Pruef-Hinweis - entfaellt nach der Pruefung

_CHECKBOX_RE = re.compile(r"^[ \t]*- \[(?P<status>[^\]])\] (?P<body>.*?)\s*$")
_SOURCE_RE = re.compile(r"\s*\(→ \[\[(?P<src>[^\]|#]+)(?:[|#][^\]]*)?\]\]\)")
_DATE_TOKEN_RE = re.compile(r"\s*(?P<emoji>📅|➕|✅)️?\s*(?P<date>\d{4}-\d{2}-\d{2})")
_LINK_RE = re.compile(r"^\[\[(?P<target>[^\]|#]+)(?:#[^\]|]*)?(?:\|(?P<alias>[^\]]*))?\]\]$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHORT_DUE_RE = re.compile(r"\s*->\s*Deadline:\s*(?P<due>\S+)\s*$")
_EMPTY_DATE = {"", "—", "-", "TBD", "tbd"}


@dataclass
class Task:
    status: str                      # " " offen, "x" erledigt, "-" verworfen
    text: str                        # Taetigkeit ohne Metadaten und ohne ❓
    kind: str = KIND_TASK            # aufgabe | frage
    owner: str | None = None         # Personen-Slug (nur exakt aufgeloest)
    owner_raw: str | None = None     # wie notiert, solange nicht aufgeloest
    topics: list[str] = field(default_factory=list)
    due: str | None = None
    created: str | None = None
    done: str | None = None
    source: str | None = None        # Quellen-Stem aus (→ [[...]])
    fmt: str = "neu"                 # neu | kurz | frei
    path: str | None = None          # relativ zum Vault (nur im Index)
    line: int | None = None          # 0-basiert (nur im Index)
    pruefen: bool = False            # steht im Altbestand, noch ungeprueft
    notes: list[str] = field(default_factory=list)   # Unterpunkte (nur beim Schreiben)

    @property
    def is_open(self) -> bool:
        return self.status not in ("x", "X", "-")

    def overdue(self, today: str | None = None) -> bool:
        return self.is_open and bool(self.due) and self.due < (today or date.today().isoformat())


# ------------------------------------------------------------------ Parser

def _iso_or_none(value: str | None) -> str | None:
    v = (value or "").strip()
    return v if _ISO_RE.match(v) else None


def _extract_meta(body: str) -> tuple[str, str | None, dict[str, str]]:
    """Quelle `(→ [[x]])` und Datums-Emojis aus dem Zeilenrest loesen."""
    src = None
    m = _SOURCE_RE.search(body)
    if m:
        src = m.group("src").strip()
        body = body[:m.start()] + body[m.end():]
    dates: dict[str, str] = {}

    def grab(mm: re.Match) -> str:
        dates.setdefault(mm.group("emoji"), mm.group("date"))
        return ""
    body = _DATE_TOKEN_RE.sub(grab, body)
    return body.strip(), src, dates


def _link(part: str) -> str | None:
    m = _LINK_RE.match(part.strip())
    return m.group("target").strip() if m else None


def _looks_like_meta(seg: str) -> bool:
    s = seg.strip()
    return (s == "?" or s.startswith(("[[", "an [[", "@")) or s.endswith(UNRESOLVED)
            or SEP_TOPIC.strip() in s and "[[" in s)


def _parse_owner_part(part: str, task: Task) -> None:
    p = part.strip()
    if p.startswith("an "):
        p = p[3:].strip()
    if not p or p == "?":
        return
    target = _link(p)
    if target:
        task.owner = target
    elif p.endswith(UNRESOLVED):
        task.owner_raw = p[: -len(UNRESOLVED)].strip() or None
    else:
        task.owner_raw = p.lstrip("@").strip() or None


def _parse_checkbox(status: str, body: str) -> Task:
    body, src, dates = _extract_meta(body)
    task = Task(status=status, text=body, source=src,
                due=_iso_or_none(dates.get(DUE)), created=_iso_or_none(dates.get(CREATED)),
                done=_iso_or_none(dates.get(DONE)), fmt="frei")
    segs = body.split(SEP_META)
    if (len(segs) >= 3 and segs[-2].strip().startswith("@")
            and (segs[-1].strip() in _EMPTY_DATE or _ISO_RE.match(segs[-1].strip()))):
        # Kurzform zum Eintippen: "Was — @wer — Datum" (Datum = Frist)
        task.text = SEP_META.join(segs[:-2]).strip()
        task.owner_raw = segs[-2].strip().lstrip("@").strip() or None
        task.due = task.due or _iso_or_none(segs[-1])
        task.fmt = "kurz"
    elif len(segs) >= 2 and _looks_like_meta(segs[-1]):
        task.text = SEP_META.join(segs[:-1]).strip()
        parts = segs[-1].split(SEP_TOPIC)
        _parse_owner_part(parts[0], task)
        task.topics = [t for t in (_link(p) for p in parts[1:]) if t]
        task.fmt = "neu"
    if task.text.startswith(QUESTION_MARK):
        task.kind = KIND_QUESTION
        task.text = task.text[len(QUESTION_MARK):].strip()
    return task


def parse_line(line: str) -> Task | None:
    """Eine Zeile als Aufgabe lesen - None, wenn sie keine ist."""
    m = _CHECKBOX_RE.match(line)
    if m:
        return _parse_checkbox(m.group("status"), m.group("body"))
    return None


def short_text(task: Task) -> str:
    """Kurzform fuer Agenda und Briefing: `@owner: Text -> Deadline: YYYY-MM-DD` -
    ohne Links, Emojis und Entstehungsdatum (das sonst als Frist gelesen wuerde)."""
    who = task.owner or task.owner_raw
    text = " ".join(task.text.split())
    if task.kind == KIND_QUESTION:
        text = f"{QUESTION_MARK} {text}"
    out = f"@{who}: {text}" if who else text
    return out + (f" -> Deadline: {task.due}" if task.due else "")


_SHORT_OWNER_RE = re.compile(r"^@(?P<owner>[^:—]+?)\s*(?::|—)\s+(?P<rest>.*)$")


def from_short_text(text: str) -> Task:
    """Kurzform zurueck in einen Punkt - Gegenstueck zu `short_text()`, auch fuer die
    `[ACTION]`-Ereignisse des Modells und "Follow-up tasks"-Bloecke (`agenda`):
    `@Owner: Text -> Deadline: D`, `@Owner — Titel: Text` oder reiner Text."""
    s = " ".join(str(text).split())
    due = None
    m = _SHORT_DUE_RE.search(s)
    if m:
        due = _iso_or_none(m.group("due"))
        s = s[:m.start()].strip()
    owner_raw = None
    m = _SHORT_OWNER_RE.match(s)
    if m:
        owner_raw, s = m.group("owner").strip(), m.group("rest").strip()
    kind = KIND_TASK
    if s.startswith(QUESTION_MARK):
        kind, s = KIND_QUESTION, s[len(QUESTION_MARK):].strip()
    return Task(status=" ", text=s, kind=kind, owner_raw=owner_raw, due=due, fmt="frei")


def key(task_or_text: Task | str) -> str:
    """Vergleichsschluessel fuer Dubletten: Text ohne Metadaten, Satzzeichen
    und Gross/Kleinschreibung - unabhaengig vom Status."""
    text = task_or_text.text if isinstance(task_or_text, Task) else str(task_or_text)
    text = text.replace(QUESTION_MARK, " ")
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


# ---------------------------------------------------------------- Renderer

class Names:
    """Anzeigenamen fuer Links (`[[slug|Name]]`) aus dem Frontmatter, gecacht."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], str | None] = {}

    def _lookup(self, category: str, slug: str) -> str | None:
        k = (category, slug)
        if k not in self._cache:
            fm = vp.read_frontmatter(vp.CATEGORY_DIRS[category] / f"{slug}.md")
            self._cache[k] = str(fm.get("name") or fm.get("title") or "").strip() or None
        return self._cache[k]

    def person(self, slug: str) -> str | None:
        return self._lookup("people", slug)

    def topic(self, slug: str) -> str | None:
        for cat in ("projects", "forums", "systems", "companies", "contexts"):
            name = self._lookup(cat, slug)
            if name:
                return name
        return None


def _wikilink(slug: str, name: str | None) -> str:
    return f"[[{slug}|{name}]]" if name and name != slug else f"[[{slug}]]"


def render(task: Task, names: Names | None = None) -> str:
    """Kanonische Zeile (KONZEPT.md §4.1)."""
    text = " ".join(task.text.split())
    if task.kind == KIND_QUESTION:
        text = f"{QUESTION_MARK} {text}"
    if task.owner:
        owner = _wikilink(task.owner, names.person(task.owner) if names else None)
    elif task.owner_raw:
        owner = f"{task.owner_raw} {UNRESOLVED}"
    else:
        owner = ""
    if owner and task.kind == KIND_QUESTION:
        owner = f"an {owner}"
    topics = [_wikilink(t, names.topic(t) if names else None) for t in task.topics]
    meta = ""
    if owner or topics:
        meta = SEP_META + (owner or "?") + "".join(SEP_TOPIC + t for t in topics)
    dates = "".join(f" {emoji} {value}" for emoji, value in
                    ((DUE, task.due), (CREATED, task.created), (DONE, task.done)) if value)
    src = f" (→ [[{task.source}]])" if task.source else ""
    status = task.status if task.status in (" ", "x", "-") else " "
    return f"- [{status}] {text}{meta}{dates}{src}"


# ----------------------------------------------------------------- Schreiben

def append_to_section(text: str, heading: str, new: list[Task], names: Names | None = None,
                      *, insert_before: tuple[str, ...] = (DESCRIPTION_SECTION, EVENT_LOG_SECTION),
                      known: set[str] | None = None) -> tuple[str, int]:
    """Punkte append-only unter `heading` schreiben. (neuer_text, anzahl_neu)

    Dubletten (gleicher `key`, egal ob offen/erledigt, Voll- oder Kurzform)
    werden uebersprungen; bestehende
    Zeilen werden nie veraendert. Fehlt der Abschnitt, entsteht er vor dem
    ersten vorhandenen `insert_before`-Abschnitt (in einer Themen-Datei also
    direkt unter dem Stand-Block), sonst am Dateiende. `known`: weitere
    Schluessel, die als vorhanden gelten (das Archiv des Themas, `verdichten.py`).
    """
    lines = text.split("\n")
    existing = {key(t) for t in (parse_line(l) for l in lines) if t is not None} | (known or set())
    to_add: list[str] = []
    for t in new:
        k = key(t)
        if k and k not in existing:
            existing.add(k)
            to_add.append(render(t, names))
    if not to_add:
        return text, 0

    idx = next((i for i, l in enumerate(lines) if l.strip() == heading), None)
    if idx is None:
        at = next((i for i, l in enumerate(lines) if l.strip() in insert_before), None)
        if at is None:
            return text.rstrip("\n") + "\n\n" + "\n".join([heading, *to_add]) + "\n", len(to_add)
        block = [heading, *to_add, ""]
        if at > 0 and lines[at - 1].strip():
            block.insert(0, "")
        lines[at:at] = block
        return "\n".join(lines), len(to_add)

    end = next((j for j in range(idx + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    # Unterabschnitte (Altbestand) bleiben unten: neue Punkte kommen davor
    stop = next((j for j in range(idx + 1, end) if lines[j].startswith("### ")), end)
    last = max([idx] + [j for j in range(idx + 1, stop) if lines[j].strip()])
    lines[last + 1:last + 1] = to_add
    after = last + 1 + len(to_add)
    if after < len(lines) and lines[after].startswith(("## ", "### ")):
        lines.insert(after, "")
    return "\n".join(lines), len(to_add)


_SOURCE_TAIL_RE = re.compile(r"(\s*\(→ \[\[[^\]]*\]\]\))?\s*$")


def dissolve_altbestand(text: str, done_date: str, owner: str | None = None) -> tuple[str, dict]:
    """Altbestand gilt als geprueft: Unterabschnitt aufloesen - seine Punkte
    bleiben als normale Punkte in `## Offene Punkte`. Ohne ✅ abgehakte Punkte
    bekommen `done_date`, Pruef-Hinweise entfallen, Belege bleiben. Mit `owner`
    (Jourfix) nur die Punkte dieser Person; der Rest bleibt im Altbestand.
    (neuer_text, {"offen", "erledigt", "verworfen"}) - unveraendert ohne Abschnitt."""
    counts = {"offen": 0, "erledigt": 0, "verworfen": 0}
    lines = text.split("\n")
    idx = next((i for i, l in enumerate(lines) if l.strip() == TOPIC_SECTION), None)
    if idx is None:
        return text, counts
    end = next((j for j in range(idx + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    sub = next((j for j in range(idx + 1, end) if lines[j].strip() == ALTBESTAND_HEADING), None)
    if sub is None:
        return text, counts
    stop = next((j for j in range(sub + 1, end) if lines[j].startswith("### ")), end)
    # Punkte samt Unterpunkten; mit `owner` wandern nur dessen Punkte (Jourfix)
    intro: list[str] = []
    items: list[tuple[bool, list[str]]] = []
    for line in lines[sub + 1:stop]:
        if _CHECKBOX_RE.match(line) and not line.startswith((" ", "\t")):
            t = parse_line(line)
            move = owner is None or (t is not None and t.owner == owner)
            if move:
                status = t.status if t is not None else " "
                if status in ("x", "X"):
                    counts["erledigt"] += 1
                    if t is not None and not t.done:
                        line = _SOURCE_TAIL_RE.sub(
                            lambda mm: f" {DONE} {done_date}" + (mm.group(1) or ""), line, count=1)
                elif status == "-":
                    counts["verworfen"] += 1
                else:
                    counts["offen"] += 1
            items.append((move, [line]))
        elif line.startswith(_ALTBESTAND_INTRO_START) and not items:
            intro.append(line)
        elif line.strip():
            if items:
                items[-1][1].append(line)
    moved = [l for mv, ls in items if mv for l in ls if not l.startswith(HINT_PREFIX)]
    kept = [l for mv, ls in items if not mv for l in ls]
    if not moved:
        return text, counts
    new_block = moved
    if kept:                              # der Rest bleibt im Altbestand
        new_block += ["", ALTBESTAND_HEADING, "", *intro, *([""] if intro else []), *kept]
    # Direkt an die Liste darueber anschliessen (keine Leerzeile dazwischen)
    before = sub
    while before > idx + 1 and not lines[before - 1].strip():
        before -= 1
    if stop < len(lines):
        new_block.append("")             # Leerzeile vor der naechsten Ueberschrift
    lines[before:stop] = new_block
    out = "\n".join(lines)
    if text.endswith("\n") and not out.endswith("\n"):
        out += "\n"
    return out, counts


# ------------------------------------------------------------------- Index

def section_lines(text: str, heading: str):
    """(zeilennummer, zeile) aller Zeilen unter `heading` bis zur naechsten H2."""
    lines = text.splitlines()
    inside = False
    for i, line in enumerate(lines):
        if line.startswith("## "):
            inside = line.strip() == heading
            continue
        if inside:
            yield i, line


def meeting_roots() -> tuple[Path, Path]:
    """Wo Termin-Notizen liegen: aktive und archivierte. Eine Notiz wandert nach dem
    Einarbeiten ins Archiv - ihre Punkte bleiben dort und bleiben sichtbar."""
    return vp.VAULT / MEETINGS_SUBDIR, vp.MEETINGS_DIR


def _sources():
    """(pfad, art) aller Dateien, in denen Aufgaben leben duerfen."""
    for meetings in meeting_roots():
        if meetings.is_dir():
            for f in sorted(meetings.rglob("*.md")):
                yield f, "meeting"
    for d in (vp.PROJECTS_DIR, vp.FORUMS_DIR):
        if d.is_dir():
            for f in sorted(d.glob("*.md")):
                yield f, "topic"


def tasks_in_text(text: str, kind: str, *, stem: str = "") -> list[Task]:
    """Aufgaben einer Datei. `kind` = meeting | topic."""
    fm, _ = vp.split_frontmatter(text)
    heading = MEETING_SECTION if kind == "meeting" else TOPIC_SECTION
    default_topics: list[str] = []
    if kind == "topic" and stem:
        default_topics = [stem]
    elif kind == "meeting" and vp.note_themen(fm):
        default_topics = vp.note_themen(fm)[:1]
    meeting_date = str(fm.get("date") or "")[:10] if kind == "meeting" else ""

    out = []
    sub = ""
    for lineno, line in section_lines(text, heading):
        if line.startswith("### "):
            sub = line.strip()
            continue
        t = parse_line(line)
        if t is None:
            continue
        t.line = lineno
        t.pruefen = heading == TOPIC_SECTION and sub == ALTBESTAND_HEADING
        if not t.topics:
            t.topics = list(default_topics)
        if not t.created and _ISO_RE.match(meeting_date):
            t.created = meeting_date
        out.append(t)
    return out


def scan() -> list[Task]:
    """Alle Aufgaben im Vault. `@slug` aus der Kurzform wird nur bei exaktem
    Personen-Slug aufgeloest - ein Vorname wird nie geraten."""
    people = set(vp.entity_slugs("people"))
    out: list[Task] = []
    for path, kind in _sources():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for t in tasks_in_text(text, kind, stem=path.stem):
            t.path = path.relative_to(vp.VAULT).as_posix()
            if not t.owner and t.owner_raw and t.owner_raw in people:
                t.owner, t.owner_raw = t.owner_raw, None
            out.append(t)
    return out


def open_by_topic(tasks: list[Task] | None = None) -> dict[str, list[Task]]:
    """Offene Punkte je Thema (ein Vault-Scan fuer alle Themen)."""
    out: dict[str, list[Task]] = {}
    for t in scan() if tasks is None else tasks:
        if t.is_open:
            for topic in t.topics:
                out.setdefault(topic, []).append(t)
    return out


def filter_tasks(tasks: list[Task], *, open_only: bool = False, owner: str | None = None,
                 topic: str | None = None) -> list[Task]:
    out = tasks
    if open_only:
        out = [t for t in out if t.is_open]
    if owner:
        out = [t for t in out if t.owner == owner]
    if topic:
        out = [t for t in out if topic in t.topics]
    return out


def summary(tasks: list[Task], today: str | None = None) -> dict:
    """Zahlen je Thema: offen, ueberfaellig, Fragen, ohne Person."""
    per: dict[str, dict] = {}
    for t in tasks:
        if not t.is_open:
            continue
        for topic in t.topics or ["(ohne Thema)"]:
            s = per.setdefault(topic, {"offen": 0, "ueberfaellig": 0, "fragen": 0, "ohne_person": 0})
            s["offen"] += 1
            s["ueberfaellig"] += t.overdue(today)
            s["fragen"] += t.kind == KIND_QUESTION
            s["ohne_person"] += not t.owner
    return per


_CHECKBOX_STATUS_RE = re.compile(r"^(\s*- \[)[^\]](\] )")


def complete(path: Path, line: int, text: str | None = None, today: str | None = None) -> dict:
    """Punkt abhaken: [x] und ✅ heute - nur, wenn die Zeile noch der erwartete
    Punkt ist (`text`: Punkt-Text, verglichen ueber `key`). Das Plugin hakt mit
    derselben Logik selbst ab (`completeInText` in plugin/src/core/aufgaben.ts)."""
    lines = path.read_text(encoding="utf-8").split("\n")
    if not 0 <= line < len(lines):
        return {"ok": False, "grund": "Zeile nicht gefunden – bitte neu laden."}
    t = parse_line(lines[line])
    if t is None or (text is not None and key(t) != key(text)):
        return {"ok": False, "grund": "Die Stelle hat sich geändert – bitte neu laden."}
    if not t.is_open:
        return {"ok": True, "aktion": "schon erledigt"}
    new = _CHECKBOX_STATUS_RE.sub(r"\g<1>x\g<2>", lines[line], count=1)
    if not t.done:
        day = today or date.today().isoformat()
        new = _SOURCE_TAIL_RE.sub(lambda m: f" {DONE} {day}" + (m.group(1) or ""), new, count=1)
    lines[line] = new
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return {"ok": True, "aktion": "erledigt"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offene Punkte im Vault auflisten")
    ap.add_argument("--open", action="store_true", help="nur offene")
    ap.add_argument("--owner", help="Personen-Slug")
    ap.add_argument("--topic", help="Themen-Slug")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--summary", action="store_true", help="Zahlen je Thema")
    ap.add_argument("--done", metavar="PFAD", help="Punkt abhaken: Datei (relativ zum Vault) ...")
    ap.add_argument("--line", type=int, help="... und Zeile (0-basiert, wie im JSON)")
    ap.add_argument("--text", help="... und Punkt-Text (Schutz gegen verschobene Zeilen)")
    args = ap.parse_args(argv)

    if args.done:
        path = (vp.VAULT / args.done).resolve()
        allowed = (*meeting_roots(), vp.PROJECTS_DIR, vp.FORUMS_DIR)
        if args.line is None or path.suffix != ".md" or not path.is_file() \
                or not any(path.is_relative_to(d.resolve()) for d in allowed):
            out = {"ok": False, "grund": "Kein Punkt in einer Termin- oder Themen-Datei."}
        else:
            import auto   # dieselbe Sperre wie die Automatik (die schreibt Themen-Dateien)
            if not auto.acquire_lock():
                out = {"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."}
            else:
                try:
                    out = complete(path, args.line, args.text)
                finally:
                    auto.release_lock()
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1

    tasks = filter_tasks(scan(), open_only=args.open, owner=args.owner, topic=args.topic)
    if args.summary:
        print(json.dumps(summary(tasks), ensure_ascii=False, indent=2))
        return 0
    if args.json:
        print(json.dumps([asdict(t) for t in tasks], ensure_ascii=False, indent=2))
        return 0
    for t in tasks:
        who = t.owner or (f"{t.owner_raw}?" if t.owner_raw else "—")
        flags = " ❓" if t.kind == KIND_QUESTION else ""
        print(f"[{t.status}]{flags} {t.text[:90]}  | {who} | {', '.join(t.topics) or '—'}"
              f"{' | 📅 ' + t.due if t.due else ''}  ({t.path}:{(t.line or 0) + 1})")
    print(f"\n{len(tasks)} Punkt(e)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
