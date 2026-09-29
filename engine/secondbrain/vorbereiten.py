#!/usr/bin/env python3
"""vorbereiten.py - Termin-Notizen fuer die naechsten Termine anlegen und vorbereiten.

Fenster: heute bis einschliesslich naechster Werktag; Termine, deren Playbook mehr
Vorlauf verlangt (`vorbereitung_vorlauf`), kommen entsprechend frueher dazu. Laeuft
in der Automatik (Schritt `vorbereiten`, stuendlich) und von Hand; jeder weitere
Lauf **aktualisiert** statt zu duplizieren. Deterministisch, kein Modell.

    2ndbrain vorbereiten                 # heute bis naechster Werktag
    2ndbrain vorbereiten --today         # nur heute
    2ndbrain vorbereiten --days 5        # groesseres Fenster
    2ndbrain vorbereiten --date YYYY-MM-DD   # Fenster ab diesem Tag
    2ndbrain vorbereiten --dry-run
    2ndbrain vorbereiten --json

Was der Lauf tut, pro Termin im Fenster:
  1. Termin finden (Kalender-Export und/oder vorhandene Meeting-Dateien)
  2. Meeting-Datei in `active-meetings/` sicherstellen (dort arbeitet das Obsidian-Plugin;
     flach - der Ordner ist ein Arbeitsplatz fuer wenige Wochen, der Dateiname sortiert)
  3. Themen und Forum zuordnen - nur Sicheres (themen.py), sonst bleibt es ein Vorschlag
  4. Vorgaenger derselben Reihe suchen
  5. `## Agenda` schreiben - manuelle Aenderungen bleiben erhalten (agenda.py)
  6. `## Vorbereitung` mit Fakten fuellen: Themenstand, Briefing (briefing.py),
     Altbestand, Playbook-Leitfaden, Vorgaenger, Teilnehmer
  7. Frontmatter aktualisieren (Typ, Variante, Themen, Status)

Protokolle bereits gelaufener Termine im Eingang bereitet der Lauf nicht vor - die
arbeitet `2ndbrain einarbeiten` ein.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agenda as ag
import altbestand as ab
import briefing as bf
import reihen as fo
import playbook as pb
import personen_namen as pn
import aufgaben as tk
import themen as th
import vault_paths as vp

ACTIVE_DIR = vp.VAULT / "active-meetings"
CALENDAR_DIR = vp.SOURCES_DIR / "calendar"
PREP_HEADING = "## Vorbereitung"


def ag_free(lines):
    """Zeilen unveraendert uebernehmen (nur zur Lesbarkeit oben)."""
    return list(lines)
# Ab dieser Prosa-Laenge gilt eine Datei als *dokumentiert* (schon gelaufen),
# nicht als vorzubereitender Termin.
STUB_MAX_PROSE = 400

# Abgelehnte und abgesagte Termine gehoeren nicht in die Vorbereitung: Outlook stellt den
# Teilnahmestatus vor den Titel, andere Kalender setzen `status` (kalender.py).
SKIP_SUMMARY_PREFIXES = ("declined:", "canceled:", "cancelled:", "abgelehnt:",
                         "abgesagt:", "abgesagt -", "storniert:")
NOTES_HEADING = "## Meine Notizen"
# Private Eintraege und Abwesenheit - keine Termine zum Vor- oder Nachbereiten
PRIVATE_RE = re.compile(r"\b(urlaub|arzt\w*|privat\w*|ooo|out of office|abwesen\w*|krank\w*|feiertag\w*)\b")
# Bewerbungsgespraeche ("Interview Team Nord: <Name>"): nichts vorzubereiten, und
# keine Reihe - der Titel traegt den Namen des Bewerbers. "Interview" nur als
# einzelnes Wort ("Stakeholder-Interviews" zur Anforderungsaufnahme nicht).
INTERVIEW_RE = re.compile(r"\b(interview|vorstellungsgespr\w*|bewerbungsgespr\w*|bewerber\w*)\b")


def no_prep_reason(title: str) -> str:
    """Warum ein Kalendertermin keine Termin-Notiz bekommt ("" = er bekommt eine)."""
    t = title.lower()
    if PRIVATE_RE.search(t):
        return "privat/Abwesenheit"
    if INTERVIEW_RE.search(t):
        return "Bewerbungsgespräch"
    return ""


# --------------------------------------------------------------- Termine finden

def _iso(value, fallback_name: str = "") -> str:
    s = str(value or "")[:10]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", fallback_name)
    return m.group(1) if m else ""


def load_calendar_events(window: set[str]) -> list[dict]:
    """Termine aus dem Kalender-Export.

    Bevorzugt den JSON-Sidecar (`events.json`, von kalender.py --json).
    Der Markdown-Export ist nur menschenlesbar (`- **MM-DD HH:MM** Titel`, ohne
    Jahr) - er wird als Notloesung geparst, mit dem Jahr aus dem Dateinamen.
    """
    events: list[dict] = []
    if not CALENDAR_DIR.is_dir():
        return events

    sidecar = CALENDAR_DIR / "events.json"
    if sidecar.is_file():
        try:
            seen_titles = set()
            for ev in json.loads(sidecar.read_text(encoding="utf-8")):
                d = _iso(ev.get("date_iso") or ev.get("date"))
                if d not in window:
                    continue
                title = str(ev.get("summary") or ev.get("title", "")).strip()
                if (not title or title.lower().startswith(SKIP_SUMMARY_PREFIXES)
                        or ev.get("status") in ("abgesagt", "abgelehnt")):
                    continue
                # Skip: Blocker-Platzhalter (noch keine echten Termine), Pausen,
                # Privates/Abwesenheit und Bewerbungsgespraeche - "Urlaub" und
                # "Arzttermin" wuerden sonst Termin-Notizen und landeten in
                # "Notizen fehlen"/"Ohne Thema" (`no_prep_reason`).
                lower_title = title.lower()
                if no_prep_reason(title):
                    continue
                if (ev.get("all_day") is True or
                    lower_title.startswith("blocker") or
                    lower_title.startswith("blocker:") or
                    re.search(r"^mittags?pause$", lower_title) or
                    lower_title.startswith("mittag:") or
                    re.search(r"\blunch\b", lower_title)):
                    continue
                # Serientermine liefert Outlook teils doppelt
                key = (d, ev.get("time", ""), title.lower())
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                # Blocker sind oben schon aussortiert - das Feld bleibt False
                is_blocker = False
                events.append({"date": d, "time": ev.get("time", ""),
                               "title": title,
                               "location": ev.get("location", ""),
                               "source": "calendar",
                               "blocker": is_blocker,
                               "outlook_uid": ev.get("outlook_uid", "")})
            return events
        except (json.JSONDecodeError, OSError, TypeError) as e:
            print(f"[WARN] events.json nicht lesbar: {e}", file=sys.stderr)

    for f in sorted(CALENDAR_DIR.glob("*.md")):
        year = (re.match(r"^(\d{4})", f.name) or [None, str(date.today().year)])[1]
        for m in re.finditer(r"^\s*-\s+\*\*(\d{2})-(\d{2})\s*(\d{2}:\d{2})?\s*\*\*\s*(.+?)\s*$",
                             f.read_text(encoding="utf-8"), re.MULTILINE):
            mm, dd, tt, title = m.groups()
            d = f"{year}-{mm}-{dd}"
            if (d in window and not title.lower().startswith(SKIP_SUMMARY_PREFIXES)
                    and not no_prep_reason(title)):
                events.append({"date": d, "time": tt or "", "title": title.strip(),
                               "location": "", "source": "calendar-md",
                               "outlook_uid": ""})
    return events


def load_meeting_files() -> list[dict]:
    """Alle Meeting-Dateien mit Datum - Vault-Wurzel, active-meetings, Archiv."""
    out = []
    seen: set[Path] = set()
    roots = [
        (vp.VAULT.glob("*.md"), "inbox"),
        (ACTIVE_DIR.rglob("*.md"), "active"),
        (vp.MEETINGS_DIR.rglob("*.md"), "archive"),
    ]
    for it, origin in roots:
        for f in it:
            if not f.is_file() or f.resolve() in seen:
                continue
            if f.name.startswith((".", "0", "README", "MEMORY")) and origin == "inbox":
                continue
            seen.add(f.resolve())
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            fm, _ = vp.split_frontmatter(text)
            d = _iso(fm.get("date"), f.name)
            if not d:
                continue
            title = (fm.get("title") or ""
                     or (re.search(r"^#\s+(.+)$", text, re.MULTILINE) or [None, f.stem])[1])
            _, body = vp.split_frontmatter(text)
            prose = "\n".join(l for l in body.splitlines()
                               if l.strip() and not l.lstrip().startswith(("#", ">", "<!--")))
            out.append({
                "path": f, "origin": origin, "date": d,
                "is_stub": len(prose.strip()) < STUB_MAX_PROSE,
                "title": str(title).strip(),
                "time": str(fm.get("meeting_time") or fm.get("time") or ""),
                "series": fm.get("series") or ag.series_key(str(title)),
                # Typ wird jedes Mal neu bestimmt - sonst friert ein Altwert ein
                # (z.B. 'other' aus einem Lauf vor einer Regelverbesserung).
                # `meeting_type_locked: true` im Frontmatter haelt eine Handkorrektur.
                "type": (fm.get("meeting_type") if fm.get("meeting_type_locked") is True
                         else ag.detect_meeting_type(str(title))),
                "participants": fm.get("teilnehmer") or fm.get("participants") or [],
                "project": (vp.note_themen(fm) or [""])[0],
                "content": text,
            })
    return out


# ------------------------------------------------------------- Projektzuordnung

STEM_MIN = 5


def _keywords(text: str, original: str = "") -> set[str]:
    """Schlagwoerter. Akronyme (2-3 Zeichen) bleiben drin, wenn sie im Original
    gross geschrieben sind - sonst fielen 'AI', 'UK', 'ERP' weg."""
    out = {w for w in ag.normalize_title(text).split() if len(w) > 3}
    src = original or text
    # Akronyme (im Original gross) mitnehmen: 'AI', 'UK', 'ERP', 'CRM'
    for m in re.findall(r"\b([A-Z][A-Z0-9]{1,4})\b", src):
        out.add(m.lower())
    return out


def _token_match(a: str, b: str) -> bool:
    """Exakt oder gemeinsamer Wortstamm ('dispatcher' ~ 'dispatch')."""
    if a == b:
        return True
    if len(a) >= STEM_MIN and len(b) >= STEM_MIN:
        return a.startswith(b[:STEM_MIN]) or b.startswith(a[:STEM_MIN])
    return False


def _overlap(t1: set[str], t2: set[str]) -> set[str]:
    return {a for a in t1 if any(_token_match(a, b) for b in t2)}


def _curated_tokens(values) -> set[str]:
    """Kuratierte Schlagwoerter **ohne** Laengenfilter.

    `keywords: [erp, crm, lager]` steht im YAML klein geschrieben - der
    Akronym-Zweig von `_keywords()` greift dort nicht, und der Filter `len > 3`
    wirft 3-Zeichen-Begriffe wie 'erp' und 'crm' weg. Kuratierte Angaben sind
    eine ausdrueckliche Aussage und werden daher unveraendert uebernommen.
    """
    out: set[str] = set()
    for v in values or []:
        norm = ag.normalize_title(str(v))
        for w in norm.split():
            if len(w) >= 2:
                out.add(w)
        if norm and " " in norm:
            out.add(norm)          # auch die ganze Phrase ("portal nord")
    return out


def project_tokens(proj: dict, *, curated_only: bool = False) -> set[str]:
    """Schlagwoerter eines Projekts. `curated_only` = nur das `keywords`-Feld."""
    out = _curated_tokens(proj.get("keywords"))
    if curated_only:
        return out
    for c in [proj.get("name", ""), proj.get("slug", ""),
              *(proj.get("aliases") or []), *(proj.get("tags") or [])]:
        out |= _keywords(str(c), str(c))
    return out


def project_candidates(title: str, projects: dict[str, dict], limit: int = 3) -> list[dict]:
    """Themen-Vorschlaege fuer einen Termin ohne Thema (Schlagwort-Ueberlappung)."""
    tokens = _keywords(title, title)
    out = []
    for slug, proj in projects.items():
        ov = _overlap(tokens, project_tokens(proj))
        if ov:
            out.append({"slug": slug, "name": proj["name"], "why": ", ".join(sorted(ov))})
    out.sort(key=lambda c: -len(c["why"]))
    return out[:limit]


def resolve_forum(ev: dict) -> tuple[str, str]:
    """Forum des Termins bestimmen. (slug, herkunft)

    1. `forum:` im Frontmatter (Hand/Frontend)
    2. Forum-Entity zum abgeleiteten Reihen-Slug
    3. leer - dann steht im Vorbereitungstext, wie man es anlegt
    """
    fm = vp.read_frontmatter(ev["path"]) if ev.get("path") and Path(ev["path"]).is_file() else {}
    if fm.get("forum") and fo.exists(str(fm["forum"])):
        return str(fm["forum"]), "im Frontmatter hinterlegt"
    key = fo.forum_key(ev.get("title", ""))
    if key and fo.exists(key):
        return key, "über den Titel erkannt"
    return "", ""


def resolve_project(ev: dict, projects: dict[str, dict], aliases: dict[str, str],
                    all_meetings: list[dict] | None = None) -> tuple[dict | None, str]:
    """Thema des Termins nach den Regeln in themen.py. (erstes Thema, herkunft)

    1. von Hand (`themen_von_hand`)        2. fuer die Reihe bestaetigt (Forum)
    3. Name/Alias eines Themas woertlich im Titel
    Sonst nichts - Schlagwoerter und Aehnlichkeiten sind nur Vorschlaege (im
    Plugin "Thema wählen"). Die *automatische* Zuordnung frueherer Termine wird
    bewusst nicht geerbt - ein Fehler pflanzte sich sonst von Termin zu Termin fort.
    Alle Themen des Termins stehen danach in `ev["themen"]`.
    """
    fm = vp.read_frontmatter(ev["path"]) if ev.get("path") and Path(ev["path"]).is_file() else {}
    key = ev.get("series") or ag.series_key(ev["title"])
    slugs, why = th.resolve(ev["title"], fm, key, projects, aliases)
    ev["themen"] = slugs
    return (projects[slugs[0]], why) if slugs else (None, "")


def _open_actions(tasks: list, today: str, limit: int = 5) -> list[str]:
    """Offene Punkte eines Themas als Kurzform: ueberfaellige zuerst, dann nach
    Frist; ohne Frist die neuesten zuerst (zwei stabile Sortierungen). Ungepruefter
    Altbestand fehlt hier - den legt der eigene Block vor."""
    ranked = sorted((t for t in tasks if not t.pruefen), key=lambda t: t.created or "",
                    reverse=True)
    ranked.sort(key=lambda t: (not t.overdue(today), t.due or "9999-99-99"))
    return [tk.short_text(t) for t in ranked[:limit]]


def load_projects() -> dict[str, dict]:
    out = {}
    today = date.today().isoformat()
    tasks_by_topic = tk.open_by_topic()
    for slug, path, fm in vp.iter_projects():
        text = path.read_text(encoding="utf-8")
        aliases = fm.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        tags = fm.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        kw = fm.get("keywords") or []
        if isinstance(kw, str):
            kw = [kw]
        out[slug] = {
            "slug": slug,
            "name": fm.get("name") or fm.get("title") or slug,
            "aliases": [str(a) for a in aliases],
            "tags": [str(t) for t in tags],
            "keywords": [str(k) for k in kw],
            "health": fm.get("health", ""),
            "target_date": str(fm.get("target_date", "")),
            "open_risks": [m.group(1).strip()
                           for m in re.finditer(r"\[RISK\]\s*(.+)", text)][:5],
            # vault-weit ueber aufgaben.py - nicht nur aus der eigenen Datei
            "open_actions": _open_actions(tasks_by_topic.get(slug, []), today),
            "path": path,
            "altbestand": ab.counts(alt, today) if (alt := ab.items(text, slug)) else None,
            # berechnet von stand.py (beteiligte.py) - fuer Themen-Vorschlaege per Teilnehmer
            "beteiligte": fm.get("beteiligte") or [],
            # fuer den Themen-Stand (frage.py, "wer kuemmert sich um ..."): Rollen, Beteiligte darunter
            "beteiligte_unterthemen": fm.get("beteiligte_unterthemen") or [],
            "rollen": fm.get("rollen") or [],
            "verantwortlich": str(fm.get("verantwortlich") or ""),
            # Landkarte: Oberthema (fuer "Unterthema schlaegt Dach" bei der Zuordnung)
            "parent": str(fm.get("parent") or "").strip("'\" ").removeprefix("[[").removesuffix("]]").split("|")[0],
        }
    return out


# ---------------------------------------------------------------- Datei anlegen

# Einheitliches Skelett (README in entities/meeting-playbooks/): gilt fuer
# NEU angelegte Notizen - vorhandene baut die Vorbereitung nicht um. Entscheidungen
# und Actions sind ueber alle Typen exakt gleich, das traegt Auswertung
# und Dashboard - deshalb hier woertlich, nicht ueber ein Format-Argument.
STUB_BODY_HEAD = """
## Ziel

<!-- Ein Satz: Was soll nach diesem Termin entschieden, geklärt oder anders sein? -->

{PREP_HEADING}

_(wird vom Prep-Lauf gefüllt)_

{AGENDA_HEADING}

"""

STUB_TAIL = """{NOTES_HEADING}

<!-- Mitschrift, Teams-Zusammenfassung oder Transkript hier einfügen -->

## Entscheidungen

<!-- - [E] Was — Wer — YYYY-MM-DD -->

## Actions

<!-- - [ ] Was — @wer — YYYY-MM-DD -->

## Parkplatz

## Verweise
"""


def _stub_frontmatter(ev: dict, view: dict, variante: str) -> dict:
    """Frontmatter einer neuen Meeting-Notiz.

    Wird ueber yaml.safe_dump geschrieben (`vp.dump_frontmatter`), nicht per
    Text-Schablone: ein Titel mit ':' (\"RE: Angebot ...\") zerbraeche sonst das
    YAML - und damit still alle Felder der Notiz.
    """
    mtype = view.get("meeting_type") or "other"
    fm = {
        "type": "meeting",
        "title": str(ev["title"]),
        "date": str(ev["date"]),
        "meeting_time": str(ev.get("time", "")),
        "series": ev.get("series") or ag.series_key(ev["title"]),
        "meeting_type": mtype,
    }
    if variante:
        fm["variante"] = variante
    fm["entscheidung_erforderlich"] = view.get("entscheidung_erforderlich") or "offen"
    # UID aus dem Kalender: Schluessel, ueber den die Vorbereitung ihre Notiz wiederfindet
    if ev.get("outlook_uid"):
        fm["outlook_uid"] = str(ev["outlook_uid"])
    fm.update({"status": "vorbereitet", "processed": False, "source": "prep",
               "tags": ["meeting"]})
    return fm


def _render_stub(ev: dict, view: dict, variante: str) -> str:
    """Neue Meeting-Notiz nach dem Einheitlichen Skelett rendern.

    Kernteil-Abschnitte kommen 1:1 aus dem Playbook (`view["kernteil"]`) - je
    ein leerer H2 zwischen `## Agenda` und `## Meine Notizen`.
    """
    kernteil_block = "".join(f"## {k}\n\n" for k in (view.get("kernteil") or []))
    body = (STUB_BODY_HEAD.format(PREP_HEADING=PREP_HEADING,
                                  AGENDA_HEADING=ag.AGENDA_HEADING)
            + kernteil_block + STUB_TAIL.format(NOTES_HEADING=NOTES_HEADING))
    return vp.dump_frontmatter(_stub_frontmatter(ev, view, variante), body)


def target_path(ev: dict) -> Path:
    typ = (ev.get("type") or ag.detect_meeting_type(ev["title"]))[:16]
    # Format: `2026-09-22 - checkin - Weekly Portal Nord.md`
    title_clean = ev["title"].strip()
    # Max 80 Zeichen insgesamt (date + typ + title)
    available = 80 - len(ev["date"]) - 3 - len(typ) - 3
    title_part = title_clean[:max(1, available)]
    # Entferne Sonderzeichen, aber behalte Buchstaben/Zahlen/Leerzeichen
    slug = f"{ev['date']} - {typ} - {title_part}"
    slug = re.sub(r"[^a-zA-Z0-9\-\säöüÄÖÜß]+", "", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    return ACTIVE_DIR / f"{slug}.md"


def ensure_file(ev: dict, project: dict | None, dry_run: bool, previous: dict | None = None) -> tuple[Path, str]:
    """Datei im active-meetings-Baum sicherstellen. (pfad, 'created'|'moved'|'exists')"""
    existing: Path | None = ev.get("path")
    if existing and existing.is_file():
        if existing.parent.is_relative_to(ACTIVE_DIR) if hasattr(Path, "is_relative_to") else str(existing).startswith(str(ACTIVE_DIR)):
            return existing, "exists"
        dest = target_path(ev)
        if dry_run:
            return existing, "would-move"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            return existing, "exists"
        existing.rename(dest)
        return dest, "moved"

    dest = target_path(ev)
    if dest.is_file():
        return dest, "exists"
    if dry_run:
        return dest, "would-create"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Typ + Variante frisch bestimmen (nicht aus ev["type"] uebernehmen: das kann
    # noch der Wert vor `meeting_type_locked` sein). Teilnehmer, falls schon
    # bekannt, gehen in `resolve_direction` ein - sonst zaehlt der Titel.
    typ, variante = pb.detect(ev["title"], ev.get("participants"))
    dest.write_text(_render_stub(ev, pb.view(typ, variante), variante), encoding="utf-8", newline="\n")
    return dest, "created"


# ------------------------------------------------------------ Vorbereitungstext

def meeting_partner(ev: dict, project: dict | None) -> str:
    """Wen spreche ich an? Fuer die Spaltenueberschrift "Frage an X"."""
    parts = ev.get("participants") or []
    if isinstance(parts, str):
        parts = [parts]
    parts = [re.sub(r"\[\[|\]\]", "", str(p)).split("|")[0].strip() for p in parts]
    parts = [p for p in parts if p]
    if len(parts) == 1:
        return parts[0].split("-")[0].title()
    # Aus dem Titel: "Jourfix - Max Muster" -> Max
    names = {s.split("-")[0] for s in vp.entity_slugs("people") if len(s.split("-")[0]) > 2}
    for w in ag.normalize_title(ev.get("title", "")).split():
        if w in names:
            return w.title()
    return ""


def extract_participants(ev: dict) -> list[str]:
    """Teilnehmer aus Event oder Titel extrahieren.

    Drei Quellen, absteigend:
    1. Attendees aus dem Kalender (wenn vorhanden)
    2. Namen aus dem Titel (nach dem Bindestrich, z.B. "Checkin - Anna")
    3. Leere Liste (wenn nichts gefunden)
    """
    # 1. Attendees aus dem Kalender
    attendees = ev.get("attendees") or ev.get("participants") or []
    if isinstance(attendees, list):
        # Kalender liefert {"name", "email"}, eine Termin-Notiz `teilnehmer:` als Text
        # ("[[slug|Name]]", "Name", leer "[[]]" aus der Vorlage).
        names = [a.get("name") or a.get("email", "") if isinstance(a, dict)
                 else str(a or "").strip().strip("[]").split("|")[-1].strip() for a in attendees]
        names = [n for n in names if n and "mailto:" not in n]
        if names:
            return names
    
    # 2. Namen aus dem Titel (nach dem letzten Bindestrich)
    #    Achtung: Titel koennen mehrere " - " haben, z.B.
    #    "Portal Nord - Lager - Versandlabels fuer Retouren einarbeiten"
    #    -> kein Name, sondern Projekt-Komponente + Aufgabe.
    #    Heuristik: extrahierte Segmente > 25 Zeichen sind keine Namen.
    title = ev.get("title", "")
    if " - " in title:
        parts = title.split(" - ")
        # Letztes Segment nach dem letzten Bindestrich
        after = parts[-1].strip()
        if after:
            # Nach Komma, "und", Bindestrich trennen
            raw_names = [n.strip() for n in re.split(r",|\s+und\s+|\s+-\s+", after) if n.strip()]
            # Filter: echte Namen sind kurz (< 25 Zeichen), kein Satzfragment
            names = [n for n in raw_names if len(n) <= 25]
            if names:
                return names
    
    return []


_LEADING_INT_RE = re.compile(r"(\d+)")


def _dauer_minutes(dauer) -> int | None:
    """Erste Zahl aus dem `dauer`-Freitext ("45–60 Min" -> 45) als Minutenbasis.

    Es gibt keine echte Kalenderdauer im Event (`kalender.py` liefert
    nur Start, kein Ende) - die Playbook-Angabe ist die einzige Grundlage fuer
    die Minutenspalte der Blocktabelle. Ohne Zahl bleibt es bei Prozent.
    """
    m = _LEADING_INT_RE.search(str(dauer or ""))
    return int(m.group(1)) if m else None


def _vorlauf_days(value) -> int:
    """`vorbereitung_vorlauf` ("14 Tage") als Zahl, Rueckfall 1 Tag."""
    m = _LEADING_INT_RE.search(str(value or ""))
    return int(m.group(1)) if m else 1


def _max_vorlauf_days() -> int:
    """Groesster Vorlauf ueber alle Playbooks (Basis + Varianten).

    Bestimmt, wie weit das Kalenderfenster fuer die Vorlauf-Regel
    zusaetzlich zum normalen Tagesfenster gescannt werden muss - ein Quarterly
    mit 14 Tagen Vorlauf soll rechtzeitig sichtbar werden, ohne dass jeder
    Vorbereitungs-Lauf pauschal drei Wochen Kalender laedt.
    """
    best = 1
    for entry in pb.all_playbooks():
        best = max(best, _vorlauf_days(entry.get("vorbereitung_vorlauf")))
        for v in (entry.get("varianten") or {}).values():
            if v.get("vorbereitung_vorlauf"):
                best = max(best, _vorlauf_days(v["vorbereitung_vorlauf"]))
    return best


def next_workday(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def window_days(today: date) -> int:
    """Tagesfenster der Automatik: heute bis einschliesslich naechster Werktag.
    Freitags also bis Montag - sonst entstuenden Montagstermine erst am
    Wochenende und waeren am Freitag nicht vorzubereiten."""
    return (next_workday(today) - today).days + 1


def prep_start(event_day: date, vorlauf: int) -> date:
    """Ab wann die Notiz fuer `event_day` angelegt wird: Vorlauf-Tage vorher
    (mind. 1); faellt das aufs Wochenende, schon am Freitag davor - fuer einen
    Montag also freitags, fuer ein Review am Dienstag (3 Tage) auch."""
    start = event_day - timedelta(days=max(1, vorlauf))
    while start.weekday() >= 5:
        start -= timedelta(days=1)
    return start


def due_for_prep(event_day: date, vorlauf: int, today: date) -> bool:
    """Legt die Vorbereitung am Tag `today` die Notiz fuer `event_day` an? Das
    Tagesfenster (`window_days`) ist der Sonderfall dieser Regel fuer einen Tag Vorlauf."""
    return prep_start(event_day, vorlauf) <= today <= event_day


def build_prep(ev: dict, previous: dict | None, project: dict | None,
               project_source: str = "", topics: list[dict] | None = None, forum_slug: str = "",
               forum_source: str = "", more: list[dict] | None = None,
               projects: dict[str, dict] | None = None) -> str:
    """Vorbereitungstext: Playbook-Leitfaden, Projektstand, Vorgaenger.

    Der Typ-Leitfaden (Ziel, Blocktabelle, Leitfragen, Risiko-Fokus) kommt aus
    `entities/meeting-playbooks/` (siehe `playbook.py`) und ist dort
    bearbeitbar. Genau das ist der Teil, der den Termin vorbereitet - nicht
    die Terminliste.
    """
    typ = ev.get("type") or ag.detect_meeting_type(ev["title"])
    # Variante wird IMMER neu bestimmt, auch wenn der Typ per
    # `meeting_type_locked` von Hand gesetzt wurde.
    variante = pb.variant_for(typ, ev.get("title", ""), ev.get("participants"))
    view = pb.view(typ, variante)

    lines = [PREP_HEADING, ""]

    # --- Projekt ---
    if project:
        health = str(project.get("health", "")).lower()
        emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(health, "")
        head = f"**Projekt:** [[{project['slug']}]]"
        if health:
            head += f" {emoji}{health}"
        if project.get("target_date"):
            head += f" — Ziel {project['target_date']}"
        lines.append(head)
        # Ohne Briefing die Rohliste zeigen; mit Briefing waere es eine Doppelung.
        if not topics:
            if project.get("open_risks"):
                lines += ["", "**Offene Risiken im Projekt:**"] + [f"- {r}" for r in project["open_risks"]]
            if project.get("open_actions"):
                lines += ["", "**Offene Actions im Projekt:**"] + [f"- {a}" for a in project["open_actions"]]
    else:
        lines.append("**Projekt:** _nicht zugeordnet_ – im Plugin „Thema wählen“")
    if more:
        emo = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
        lines.append("**Weitere Themen:** " + ", ".join(
            f"[[{p['slug']}|{p['name']}]] {emo.get(str(p.get('health', '')).lower(), '')}".rstrip()
            for p in more))

    # --- Forum / Gremium ---
    if forum_slug:
        ffm = fo.read(forum_slug)
        bits = [f"**Forum:** [[{forum_slug}]]"]
        if ffm.get("kind"):
            bits.append(str(ffm["kind"]))
        if ffm.get("maturity"):
            bits.append(f"Reifegrad {ffm['maturity']}")
        lines += ["", " — ".join(bits)]
        dev = fo.development_items(forum_slug)
        if dev:
            lines += ["", "**Entwicklung dieses Formats:**"] + [f"- {d}" for d in dev[:4]]

    # --- Jourfix/1:1: die Person statt eines Themas ---
    for pl in _person_sections(ev, projects or {}):
        lines += [""] + pl

    # --- Altbestand: uebernommene Alt-Aufgaben im Termin klaeren ---
    for slug, path, counts, title in _altbestand_for(project, forum_slug, more):
        lines += [""] + ab.prep_block(slug, path, counts, title)
    # --- Priorisiertes Briefing ---
    if topics:
        crit = sum(1 for t in topics if t["priority"] == bf.PRIO_CRITICAL)
        lines += ["", f"### Offene Themen ({len(topics)}, davon {crit} kritisch)"]
        lines += ag_free(bf.render_briefing(topics, partner=meeting_partner(ev, project)))
    elif project:
        lines.append("_Keine offenen Themen._")

    # --- Playbook: Blocktabelle, Checkliste ---
    lines += ["", f"**Playbook:** {view['label']}"
              + (f" — Variante **{variante}**" if variante else "")]

    blocks = view.get("blocks") or []
    if blocks:
        total_min = _dauer_minutes(view.get("dauer"))
        lines += ["", "| Block | Anteil | Inhalt |", "|---|---|---|"]
        for b in blocks:
            anteil = b.get("anteil", 0)
            cell = f"{anteil}%"
            if total_min:
                cell += f" (~{round(total_min * anteil / 100)} Min)"
            lines.append(f"| {b.get('block', '')} | {cell} | {b.get('inhalt', '')} |")

    if view.get("checklist"):
        lines += ["", "**Checkliste:**"] + [f"- [ ] {c}" for c in view["checklist"]]
    if view.get("abbruch"):
        lines += ["", f"**Abbruch:** {view['abbruch']}"]

    # --- Vorgaenger ---
    lines.append("")
    if previous:
        items = ag.extract_open_items(previous.get("content", ""))
        counts = ", ".join(f"{len(items[k])} {lbl}" for lbl, k in
                           (("Follow-ups", "actions"), ("Risiken", "risks"),
                            ("Beschlüsse", "decisions")) if items[k]) or "keine offenen Punkte"
        match = previous.get("_match", "series")
        how = ("gleiche Reihe" if match == "series"
               else f"über Titelähnlichkeit {match.split(':')[1]} — bitte kurz prüfen")
        # Offene Punkte des Vorgaengers stehen im Briefing, nie in der Agenda
        # (die Agenda gehoert dem Benutzer).
        wohin = "im Briefing oben" if topics else "nicht im Briefing"
        lines.append(f"**Vorheriger Termin der Reihe:** [[{previous['path'].stem}]] "
                     f"({previous['date']}, {how}) — {counts}"
                     + (f", {wohin}" if counts != "keine offenen Punkte" else ""))
    else:
        lines.append(f"**Reihe:** `{ev.get('series')}` — kein Vorgänger gefunden "
                     f"(erster Termin oder abweichender Titel).")

    parts = ev.get("participants") or []
    if isinstance(parts, str):
        parts = [parts]
    if parts:
        lines += ["", "**Teilnehmer:** " + ", ".join(
            f"[[{re.sub(r'\[\[|\]\]', '', str(x))}]]" for x in parts)]

    lines.append("")
    return "\n".join(lines) + "\n"


def _person_sections(ev: dict, projects: dict[str, dict]) -> list[list[str]]:
    """Jourfix/1:1 mit ein bis zwei Personen: je Person ihre Themen (wo sie
    beteiligt ist), Zusagen, Fragen und Altbestand - der Termin braucht kein Thema."""
    typ = ev.get("type") or ag.detect_meeting_type(ev.get("title", ""))
    if not th.is_person_meeting(ev.get("title", ""), typ):
        return []
    import beteiligte as bt
    fm = vp.read_frontmatter(ev["path"]) if ev.get("path") and Path(ev["path"]).is_file() else {}
    if ev.get("participants") and not fm.get("key_persons"):
        fm = {**fm, "key_persons": list(ev["participants"])}
    key = ev.get("series") or ag.series_key(ev.get("title", ""))
    others, _ = th.resolve_persons(ev.get("title", ""), fm, key, vp.alias_map(), bt.me())
    if not others:
        return [["### Personen-Termin", "",
                 "_Mit wem? Im Plugin „Mit wem?“ einmal für die Reihe festlegen – dann stehen hier "
                 "die Themen, Zusagen und der Altbestand der Person._"]]
    rank = {"red": 0, "yellow": 1, "green": 2}
    person_names = tk.Names()
    out = []
    for person in others:
        topics = sorted(((slug, str(p.get("name") or slug), str(p.get("health") or ""))
                         for slug, p in projects.items()
                         if person in {th._slug(b) for b in p.get("beteiligte") or []}),
                        key=lambda x: (rank.get(x[2], 3), x[1]))[:8]
        out.append(ab.person_block(person, person_names.person(person) or person, topics))
    return out


def _altbestand_for(project: dict | None, forum_slug: str = "", more: list[dict] | None = None):
    """(slug, pfad, zaehler, titel) fuer alle Themen und das Forum des Termins mit Altbestand."""
    for p in [project, *(more or [])]:
        if p and p.get("altbestand"):
            yield p["slug"], p["path"], p["altbestand"], str(p.get("name") or "")
    fpath = ab.topic_path(forum_slug) if forum_slug else None
    if fpath is not None and (not project or forum_slug != project.get("slug")):
        its = ab.items(fpath.read_text(encoding="utf-8"), forum_slug)
        if its:
            fm = vp.read_frontmatter(fpath)
            yield forum_slug, fpath, ab.counts(its), str(fm.get("name") or fm.get("title") or "")


def apply_prep(path: Path, prep_text: str, dry_run: bool) -> str:
    """Vorbereitung schreiben (Sektion ersetzen oder vor `## Meine Notizen` anlegen)."""
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(PREP_HEADING)}\s*$", text, re.MULTILINE)
    if m:
        nxt = re.search(r"^##\s+\S", text[m.end():], re.MULTILINE)
        end = m.end() + nxt.start() if nxt else len(text)
        new_text = text[:m.start()] + prep_text + text[end:]
        action = "updated"
    else:
        anchor = re.search(rf"^{re.escape(NOTES_HEADING)}\s*$", text, re.MULTILINE)
        if anchor:
            new_text = text[:anchor.start()] + prep_text + "\n" + text[anchor.start():]
        else:
            new_text = text.rstrip() + "\n\n" + prep_text
        action = "created"
    if new_text == text:
        return "unchanged"
    if not dry_run:
        path.write_text(new_text, encoding="utf-8", newline="\n")
    return action


# ---------------------------------------------------------------------- Lauf

def run(days: int | None = None, dry_run: bool = False, as_json: bool = False,
        start_date: date = None) -> dict:
    today = start_date or date.today()
    if days is None:
        days = window_days(today)
    window = {(today + timedelta(days=i)).isoformat() for i in range(days)}

    all_meetings = load_meeting_files()
    projects = load_projects()
    aliases = vp.alias_map()

    # Quellenregel (wichtig): "Was habe ich heute?" beantwortet der **Kalender**.
    # Dateien im Eingang mit echtem Inhalt sind Protokolle bereits gelaufener Termine -
    # die gehoeren ins Einarbeiten, nicht in die Vorbereitung. Sie werden uebersprungen
    # statt nach active-meetings verschoben.
    candidates = [m for m in all_meetings if m["date"] in window]
    in_window, skipped = [], []
    for m in candidates:
        if m["origin"] == "active" or m.get("is_stub"):
            in_window.append(m)
        else:
            skipped.append(m)
    have = {(m["date"], ag.series_key(m["title"])) for m in in_window + skipped}
    for ev in load_calendar_events(window):
        key = (ev["date"], ag.series_key(ev["title"]))
        if key not in have:
            ev["series"] = ag.series_key(ev["title"])
            ev["type"] = ag.detect_meeting_type(ev["title"])
            ev["participants"] = []
            ev["path"] = None
            ev["content"] = ""
            in_window.append(ev)
            have.add(key)

    # Vorlauf-Regel: ein Termin wird nicht nur im Tagesfenster aufgemacht,
    # sondern sobald `datum - vorbereitung_vorlauf <= heute` - sonst waere ein
    # Quarterly (14 Tage Vorlauf) erst am Vortag sichtbar, wenn die Vorbereitung
    # laengst haette anlaufen muessen. Das normale Fenster bleibt unveraendert;
    # hier kommen nur Termine **zusaetzlich** dazu, die ausserhalb davon liegen.
    horizon = _max_vorlauf_days() + 2         # + Wochenende: Beginn Sa/So -> Freitag
    if horizon > days:
        extended = {(today + timedelta(days=i)).isoformat() for i in range(horizon + 1)}
        for ev in load_calendar_events(extended - window):
            key = (ev["date"], ag.series_key(ev["title"]))
            if key in have:
                continue
            typ, variante = pb.detect(ev["title"])
            vorlauf = _vorlauf_days(pb.view(typ, variante).get("vorbereitung_vorlauf"))
            if not due_for_prep(date.fromisoformat(ev["date"]), vorlauf, today):
                continue
            ev["series"] = ag.series_key(ev["title"])
            ev["type"] = typ
            ev["participants"] = []
            ev["path"] = None
            ev["content"] = ""
            ev["vorlauf"] = True
            in_window.append(ev)
            have.add(key)

    in_window.sort(key=lambda m: (m["date"], m.get("time") or "99:99", m["title"]))

    results = []
    for ev in in_window:
        # Vorgaenger zuerst - Agenda und Vorbereitung brauchen ihn
        previous = ag.find_previous(ev, all_meetings)
        
        path, file_action = ensure_file(ev, None, dry_run, previous)
        ev["path"] = path
        project, project_source = resolve_project(ev, projects, aliases, all_meetings)
        forum_slug, forum_source = resolve_forum(ev)
        # Forum kann ein Projekt vorgeben (reports_on / project)
        if not project and forum_slug:
            ft = [t for t in th.series_topics(forum_slug) if t in projects]
            if ft:
                project, project_source = projects[ft[0]], f"Forum-Vorgabe ({forum_slug})"
                ev["themen"] = ft
        more = [projects[s] for s in (ev.get("themen") or [])[1:] if s in projects]

        items = ag.build_agenda(ev, previous, project)

        if dry_run:
            agenda_action = "would-write"
            prep_action = "would-write"
        else:
            agenda_action = ag.apply_agenda(path, items)
            # Teilnehmer aus Kalender als key_persons ins Frontmatter
            # Bestehende Teilnehmer-Tabelle aus Markdown loeschen (immer!)
            participants = extract_participants(ev)
            if not dry_run:
                text = path.read_text(encoding="utf-8")
                original = text
                m = re.search(rf"^{re.escape('## Teilnehmer')}\s*$", text, re.MULTILINE)
                if m:
                    nxt = re.search(r"^##\s+\S", text[m.end():], re.MULTILINE)
                    end = m.end() + nxt.start() if nxt else len(text)
                    text = text[:m.start()] + text[end:]
                if text != original:
                    path.write_text(text, encoding="utf-8", newline="\n")
                # key_persons normalisieren und deduplizieren
                # Wenn keine Teilnehmer, aber falscher Wert im Frontmatter (z.B.
                # Titel-fragment), loeschen wir ihn, damit der User ihn neu setzen
                # kann — sonst bleibt der Irrtum stehen.
                people_dir = vp.ENTITIES_DIR / "people"
                existing_kp = fm.get("key_persons", []) if (fm := vp.read_frontmatter(path)) else []
                if isinstance(existing_kp, str):
                    existing_kp = [existing_kp]
                if participants:
                    known_persons = []
                    if people_dir.is_dir():
                        for f in people_dir.glob("*.md"):
                            try:
                                content = f.read_text(encoding="utf-8")
                                fm = vp.read_frontmatter(f)
                                name = fm.get("name") or fm.get("given_name") or f.stem
                                known_persons.append(str(name))
                            except OSError:
                                continue
                    cleaned = pn.deduplicate_names(participants, known_persons, people_dir)
                    if cleaned:
                        vp.update_frontmatter(path, {"key_persons": cleaned})
                elif existing_kp:
                    # Kein Teilnehmer, aber Frontmatter hat noch einen Wert →
                    # loeschen (der User soll ihn von Hand setzen koennen)
                    vp.update_frontmatter(path, {"key_persons": []})
            
            topics = bf.build_topics(ev, all_meetings, project, forum_slug=forum_slug)
            import schreibweisen        # Namen wie auf ihren Seiten - auch aus Kalender und frueheren Terminen
            prep_action = apply_prep(
                path, schreibweisen.vereinheitlichen(build_prep(ev, previous, project, project_source, topics,
                                                                forum_slug, forum_source, more=more,
                                                                projects=projects))[0],
                dry_run)
            # Vollstaendiges Frontmatter upserten. Dateien ohne Frontmatter
            # bekommen sonst nur Status-Keys und verlieren type/date/title fuer
            # alle nachgelagerten Werkzeuge.
            existing = vp.read_frontmatter(path)
            meeting_type = (existing.get("meeting_type")
                            if existing.get("meeting_type_locked") is True
                            else (ev.get("type") or ag.detect_meeting_type(ev["title"])))
            # Variante immer neu bestimmen - auch bei gesperrtem Typ.
            variante = pb.variant_for(meeting_type, ev["title"], ev.get("participants"))
            pb_view = pb.view(meeting_type, variante)
            updates = {
                "type": existing.get("type") or "meeting",
                "title": existing.get("title") or ev["title"],
                "date": ev["date"],
                "series": ev.get("series") or ag.series_key(ev["title"]),
                "meeting_type": meeting_type,
            }
            # Blocker-Kennzeichnung aus dem Kalender
            if ev.get("blocker"):
                updates["blocker"] = True
            if variante:
                updates["variante"] = variante
            if pb_view.get("entscheidung_erforderlich"):
                updates["entscheidung_erforderlich"] = pb_view.get("entscheidung_erforderlich")
            else:
                updates["entscheidung_erforderlich"] = "offen"
            # Status "vorbereitet" - ein spaeterer Zustand (nachbereitet, entfallen)
            # wird nie zurueckgesetzt: der stuendliche Lauf machte sonst aus
            # "entfallen" wieder "vorbereitet".
            if str(existing.get("status") or "") not in ("nachbereitet", "entfallen"):
                updates["status"] = "vorbereitet"
            updates["prepared_at"] = datetime.now().isoformat(timespec="seconds")
            if forum_slug:
                updates["forum"] = forum_slug
            if ev.get("time"):
                updates["meeting_time"] = ev["time"]
            # Themen jedes Mal neu (leer entfernt eine ueberholte automatische
            # Zuordnung); von Hand gesetzte liefert resolve_project unveraendert.
            themen = ev.get("themen") or ([project["slug"]] if project else [])
            updates["themen"] = themen or None
            if ev.get("outlook_uid"):
                updates["outlook_uid"] = ev["outlook_uid"]
            vp.update_frontmatter(path, updates)

        results.append({
            "date": ev["date"], "time": ev.get("time", ""), "title": ev["title"],
            "path": str(path.relative_to(vp.VAULT)) if path else None,
            "series": ev.get("series"), "project": (project or {}).get("slug"),
            "project_source": project_source,
            "type": ev.get("type") or ag.detect_meeting_type(ev["title"]),
            "forum": forum_slug or None,
            "candidates": [] if project else [c["slug"] for c in project_candidates(ev["title"], projects)],
            "previous": previous["date"] + " " + previous["title"] if previous else None,
            "agenda_items": len(items),
            "topics": len(bf.build_topics(ev, all_meetings, project)),
            "file": file_action, "agenda": agenda_action, "prep": prep_action,
            "vorlauf": bool(ev.get("vorlauf")),
        })

    summary = {
        "today": today.isoformat(),
        "window": sorted(window),
        "meetings": len(results),
        "skipped_documented": [{"date": m["date"], "title": m["title"],
                                "path": str(m["path"].relative_to(vp.VAULT))}
                               for m in skipped],
        "dry_run": dry_run,
        "results": results,
    }

    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    print(f"Vorbereitung {today} — Fenster {sorted(window)[0]} .. {sorted(window)[-1]}"
          + ("  [DRY-RUN]" if dry_run else ""))
    if skipped:
        print(f"\n{len(skipped)} bereits dokumentierte(s) Protokoll(e) im Fenster - uebersprungen:")
        for m in skipped:
            print(f"  - {m['date']}  {m['title'][:56]}")
        print("  (die arbeitet das Einarbeiten ein: 2ndbrain einarbeiten)")
    if not results:
        print("\nKeine vorzubereitenden Termine im Fenster.")
        print("  Kalender holen:  2ndbrain einlesen --source calendar")
        print("  Oder Termin-Notiz mit 'date:' im Frontmatter anlegen.")
        return summary
    print()
    for r in results:
        tag = "  (Vorlauf)" if r.get("vorlauf") else ""
        print(f"  {r['date']} {r['time'] or '     '}  {r['title'][:52]}{tag}")
        print(f"      Datei   {r['file']:12} {r['path']}")
        print(f"      Agenda  {r['agenda']:12} {r['agenda_items']} Punkte"
              + (f"  | Reihe: {r['series']}" if r['series'] else ""))
        proj = r['project'] or ('– (Vorschlag: ' + ', '.join(r['candidates']) + ')'
                                if r.get('candidates') else '–')
        print(f"      Vorber. {r['prep']:12} Typ: {r['type']:10} Thema: {proj}")
        print(f"      {'':14}Forum: {r.get('forum') or '–':30} "
              f"Briefing: {r.get('topics', 0)} Themen")
        print(f"      {'':14}Vorgänger: "
              + (r['previous'][:52] if r['previous'] else 'keiner'))
    print(f"\n{len(results)} Termin(e) vorbereitet. Erneut ausfuehren = aktualisieren.")
    return summary


def main() -> int:
    args = sys.argv[1:]
    days = 1 if "--today" in args else None
    start_date = None
    if "--days" in args:
        i = args.index("--days")
        if i + 1 < len(args):
            days = max(1, int(args[i + 1]))
    # --date YYYY-MM-DD: historisches Fenster (statt heute)
    if "--date" in args:
        i = args.index("--date")
        if i + 1 < len(args):
            import datetime as _dt
            start_date = _dt.date.fromisoformat(args[i + 1])
    if days is None:                 # Standard: heute bis naechster Werktag
        days = window_days(start_date or date.today())
    run(days=days, dry_run="--dry-run" in args, as_json="--json" in args, start_date=start_date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
