#!/usr/bin/env python3
"""agenda.py - `## Agenda` einer Termin-Notiz als bearbeitbare Markdown-Sektion, mit Reihen-Nachnutzung.

Kernstuecke:
  - `series_key()`    Reihen-Erkennung: Datum/Version aus dem Titel entfernen,
                      damit "2026-07-16 Jourfix Nord" und "2026-08-20 Jourfix Nord"
                      dieselbe Reihe sind. Mitverglichene Datumsziffern wuerden
                      die Aehnlichkeit verwaessern.
  - `build_agenda()`  Baut die Agenda aus Punkten als Text, nicht als Zaehler:
                      Standard-Agenda der Reihe, Agenda des Vorgaengers, sonst
                      offene Punkte des Themas.
  - `apply_agenda()`  Schreibt `## Agenda` in den **Body** (inline bearbeitbar),
                      nicht ins Frontmatter. Manuelle Aenderungen werden erkannt
                      und nicht ueberschrieben: ein Fingerabdruck des zuletzt
                      Generierten steht in `agenda_fingerprint`; weicht die Sektion
                      davon ab, gehoert sie dem Benutzer und es werden nur neue
                      Punkte angehaengt.
  - `extract_open_items()`  offene Actions, Risiken, Beschluesse einer Notiz als Text
                      (fuer das Briefing und den Rueckfall der Nachbereitung).

Die Agenda schreibt vorbereiten.py; `series_key()`/`normalize_title()` nutzen viele
Module. Projektstand und Playbook-Leitfaden stehen in `## Vorbereitung`, offene
Punkte des Vorgaengers im Briefing (briefing.py).
"""
from __future__ import annotations

import hashlib
import re
import sys
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import abschnitte as ms
import vault_paths as vp

AGENDA_HEADING = "## Agenda"
# Punkte, die *Fakten* beisteuern (aus Vorgaenger/Projekt). Nur diese werden an
# eine vom Benutzer bearbeitete Agenda angehaengt - Geruestpunkte wie
# "**Kontext:**" wuerden sonst nach jedem Umformulieren erneut auftauchen.
INFORMATIONAL_PREFIXES = ("**Follow-up", "**Risiko", "**Beschluss prüfen",
                          "**Offenes Risiko", "**Projekt:")
PREP_HEADING = "## Vorbereitung"
# Reihen-Konfiguration (Standard-Agenda, Entwicklung) liegt in der Forum-Datei
# der Reihe (entities/forums/, reihen.py).

# Rauschen, das keine Reihe unterscheidet
_DATE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b", r"\b\d{2}\.\d{2}\.\d{4}\b", r"\b\d{1,2}\.\d{1,2}\.\b",
    r"\b\d{4}\d{2}\d{2}\b", r"\bkw\s*\d{1,2}\b", r"\bq[1-4]\b",
    r"\b(?:v|rev)\.?\s*\d+(?:\.\d+)*\b", r"\b\d{1,2}:\d{2}\b",
]
_MONTHS_DE = ("januar februar maerz märz april mai juni juli august september "
              "oktober november dezember").split()
_STOPWORDS = {"der", "die", "das", "und", "mit", "zum", "zur", "fuer", "für", "von",
              "neu", "update", "call", "termin", "meeting", "transcript", "copy", "kopie"}

# Typ-Erkennung und Typ-Leitfaeden liegen in `entities/meeting-playbooks/`
# (Leser: `playbook.py`); Feinheiten laufen ueber Varianten.


# ------------------------------------------------------------------ Reihen

def normalize_title(title: str) -> str:
    t = str(title or "").lower()
    for pat in _DATE_PATTERNS:
        t = re.sub(pat, " ", t)
    for m in _MONTHS_DE:
        t = re.sub(rf"\b{m}\b", " ", t)
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    words = [w for w in t.split() if w not in _STOPWORDS and not w.isdigit() and len(w) > 1]
    return " ".join(words)


def series_key(title: str) -> str:
    """Stabiler Slug fuer die Meeting-Reihe."""
    n = normalize_title(title)
    return re.sub(r"\s+", "-", n).strip("-") or "einzeltermin"


def similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def detect_meeting_type(title: str) -> str:
    """Delegiert an `playbook.detect()` - lokaler Import, siehe Modul-Docstring."""
    import playbook
    return playbook.detect(title)[0]


# An Kalendertiteln bestimmt: verwandte, aber verschiedene Reihen ("Team Nord
# Architektur Board" ~ "Team Nord Overview": 0.58) muessen darunter bleiben,
# schwache echte Treffer ("Abstimmung zum Nord Portfolio WS" ~ "Monthly Nord
# Portfolio": 0.64) darueber.
SERIES_MIN_SIMILARITY = 0.62


def find_previous(meeting: dict, all_meetings: list[dict], *,
                  min_sim: float = SERIES_MIN_SIMILARITY) -> dict | None:
    """Letztes Meeting derselben Reihe vor diesem Termin.

    Setzt `_match` auf dem Ergebnis: 'series' bei identischem Reihen-Slug,
    sonst 'similarity:<wert>' - damit im Vorbereitungstext sichtbar ist, wie
    belastbar die Zuordnung war.
    """
    key = meeting.get("series") or series_key(meeting.get("title", ""))
    mdate = str(meeting.get("date", ""))
    best, best_score = None, 0.0
    for other in all_meetings:
        if other.get("path") == meeting.get("path"):
            continue
        odate = str(other.get("date", ""))
        if not odate or (mdate and odate >= mdate):
            continue
        same_series = (other.get("series") or series_key(other.get("title", ""))) == key
        score = 1.0 if same_series else similarity(meeting.get("title", ""), other.get("title", ""))
        if score < min_sim:
            continue
        # Bei gleicher Guete das juengste nehmen
        if score > best_score or (score == best_score and best and odate > str(best.get("date", ""))):
            best, best_score = other, score
    if best is not None:
        best = dict(best)
        best["_match"] = "series" if best_score >= 1.0 else f"similarity:{best_score:.2f}"
    return best


# ------------------------------------------------------ Offene Punkte lesen

# Freitext-Format in Notizen: "Follow-up tasks:" gefolgt von
# "- **Titel:** Beschreibung (Owner)".
_FOLLOWUP_HEADINGS = ("Follow-up tasks:", "Follow-up-Aufgaben:", "Follow-up-Aufgaben",
                      "Follow-ups:", "Offene Aufgaben:", "Action Items:")
_BULLET_BOLD_RE = re.compile(r"^\s*[-*+]\s+\*\*(.+?):?\*\*\s*(.*)$")
_OWNER_RE = re.compile(r"\(([^()]{2,40})\)\s*$")


def _parse_followup_block(content: str) -> list[str]:
    """Aufgaben aus einem 'Follow-up tasks:'-Block als lesbare Zeilen."""
    out: list[str] = []
    for heading in _FOLLOWUP_HEADINGS:
        idx = content.find(heading)
        if idx == -1:
            continue
        block = content[idx + len(heading):]
        # Block endet an der naechsten Ueberschrift oder nach einer Leerzeilen-Doppelung
        stop = re.search(r"\n\s*(?:#{1,6}\s|\n[A-ZÄÖÜ][^\n]{0,60}:\s*\n)", block)
        if stop:
            block = block[:stop.start()]
        for line in block.splitlines():
            m = _BULLET_BOLD_RE.match(line)
            if m:
                title, rest = m.group(1).strip(), m.group(2).strip()
                owner = ""
                mo = _OWNER_RE.search(rest)
                if mo:
                    owner = mo.group(1).strip()
                    rest = rest[:mo.start()].strip()
                item = f"{title}: {rest}" if rest else title
                if owner:
                    item = f"@{owner} — {item}"
                if item and item not in out:
                    out.append(item)
            elif re.match(r"^\s*[-*+]\s+\S", line):
                item = re.sub(r"^\s*[-*+]\s+", "", line).strip()
                if item.startswith("!["):      # eingebettete Bilder ueberspringen
                    continue
                if item and item not in out:
                    out.append(item)
        if out:
            break
    return out


def extract_open_items(content: str) -> dict[str, list[str]]:
    """Offene Actions, Risiken und Beschluesse als **Text**, nicht als Zaehler.

    Erledigte Checkboxen (`[x]`) werden uebersprungen - sie gehoeren nicht in die
    Agenda des Folgetermins.
    """
    actions, risks, decisions = [], [], []

    for item in _parse_followup_block(content):
        if item not in actions:
            actions.append(item)

    for m in re.finditer(r"\[ACTION\]\s*(.+)", content):
        line = m.group(1).strip()
        if line and line not in actions:
            actions.append(line)
    for m in re.finditer(r"\[RISK\]\s*(.+)", content):
        line = m.group(1).strip()
        if line and line not in risks:
            risks.append(line)
    for m in re.finditer(r"\[DECISION\]\s*(.+)", content):
        line = m.group(1).strip()
        if line and line not in decisions:
            decisions.append(line)

    # Offene Checkboxen aus Aufgaben-Abschnitten
    try:
        from zerlegen import find_sections
        sections = find_sections(content)
    except Exception:
        sections = {}
    # Checkboxen ueber aufgaben.py lesen (einziger Parser, KONZEPT §4.1) und als
    # Kurzform weitergeben - sonst landen Links und ➕-Datum im Briefing-Label
    # und das Entstehungsdatum wird als Frist gelesen.
    for line in sections.get("actions", []):
        t = tk.parse_line(line if line.startswith(("-", "*", "+")) else f"- {line}")
        if t is None or not t.is_open:
            continue
        task = tk.short_text(t)
        if task and task not in actions:
            actions.append(task)
    for line in sections.get("risks", []):
        if line and line not in risks:
            risks.append(line)
    for line in sections.get("decisions", []):
        if line and line not in decisions:
            decisions.append(line)

    return {
        "actions": actions[:8],
        "risks": risks[:5],
        "decisions": decisions[:5],
    }


# ---------------------------------------------------------- Reihen-Vorlage

def read_series_template(key: str) -> list[str]:
    """`## Standard-Agenda` des Forums."""
    import reihen
    return reihen.standard_agenda(key)


# -------------------------------------------------------------- Agenda bauen

def build_agenda(meeting: dict, previous: dict | None, project: dict | None) -> list[str]:
    """Agenda-Punkte ohne Nummern - die Nummerierung macht Markdown."""
    typ = meeting.get("type") or detect_meeting_type(meeting.get("title", ""))
    items: list[str] = []

    # 1. Standard-Agenda der Reihe (Forum) hat Vorrang
    key = meeting.get("series") or series_key(meeting.get("title", ""))
    items.extend(read_series_template(key))

    # Was an der Gruppe selbst entwickelt werden soll - gehoert auf die Agenda
    # des Formats, nicht in ein Projekt.
    try:
        import reihen as _forum
        for d in _forum.development_items(key)[:3]:
            items.append(f"**Entwicklung des Formats:** {d}")
    except Exception:
        pass

    # 2. Agenda aus dem Vorgaenger derselben Reihe (komplett, nicht nur offene Punkte)
    if previous:
        prev_agenda = read_agenda_items(previous.get("content", ""))
        if prev_agenda:
            # Alle Agenda-Punkte aus dem Vorgaenger uebernehmen
            for item in prev_agenda:
                if item.lower() not in [i.lower() for i in items]:
                    items.append(f"[Vorgaenger] {item}")

    # Projektstand und Playbook-Leitfaden stehen in `## Vorbereitung`
    # (vorbereiten.build_prep) - hier nur, was als Agenda-Punkt taugt.

    # 3. Sonst: Einladungstext aus dem Kalender als Grundlage (max. 3 Absaetze)
    if not items:
        description = meeting.get("description", "")
        if description and len(description) > 100:
            # Absaetze trennen, Begruessung, Signatur und Einwahltext auslassen
            paragraphs = [p.strip() for p in description.replace("\r\n", "\n").split("\n\n") if p.strip()]
            for p in paragraphs[:3]:
                lower = p.lower()
                # Begruessung
                if lower.startswith(("hallo", "liebe", "sehr geehrte", "dear", "hi", "hallo zusammen")):
                    continue
                # Signatur
                if lower.startswith(("viele grüße", "gruss", "best regards", "kind regards", "grüßen")):
                    continue
                # Einwahl-/Kalendertext (Teams, Outlook)
                if "microsoft" in lower or "teams" in lower or "calendar" in lower:
                    continue
                if len(p) > 10:
                    # auf 80 Zeichen kuerzen
                    if len(p) > 80:
                        p = p[:77] + "..."
                    items.append(f"**Thema:** {p}")
        # Nur ein Punkt (vom Titel): zwei Ergaenzungspunkte je nach Art des Termins
        elif len(items) == 1 and title:
            title_lower = title.lower()
            if any(kw in title_lower for kw in ["checkin", "stand", "status", "weekly", "wöchentlich"]):
                items.extend([
                    "**Thema:** Stand zu allen Projekten", 
                    "**Thema:** Offene Punkte & Blockaden besprechen"
                ])
            elif any(kw in title_lower for kw in ["abstimmung", "decision", "entscheidung"]):
                items.extend([
                    "**Thema:** Optionen vorstellen",
                    "**Thema:** Entscheidung & nächste Schritte"
                ])
            elif any(kw in title_lower for kw in ["review", "test", "prüfung"]):
                items.extend([
                    "**Thema:** Ergebnisse präsentieren",
                    "**Thema:** Feedback & Verbesserungen"
                ])
            elif any(kw in title_lower for kw in ["brainstorm", "idee", "planung"]):
                items.extend([
                    "**Thema:** Ideen sammeln",
                    "**Thema:** Priorisierung & nächste Schritte"
                ])
            else:
                items.extend([
                    "**Thema:** Aktuelle Situation analysieren",
                    "**Thema:** Optionen diskutieren & nächste Schritte planen"
                ])
            # erstes Wort gross schreiben
            for i, item in enumerate(items):
                if i > 0 and item.startswith("**Thema:**"):
                    text = item.split("**Thema:**")[1].strip()
                    if text:
                        items[i] = f"**Thema:** {text[0].upper()}{text[1:]}"
    
    # 4. Immer noch leer und ein Thema zugeordnet: dessen offene Risiken und Aufgaben
    if not items and project:
        risks = project.get("open_risks", [])
        actions = project.get("open_actions", [])
        decisions = project.get("open_decisions", [])
        
        for r in (risks or []):
            if r not in items:
                items.append(f"**Risiko:** {r}")
        for a in (actions or []):
            if a not in items:
                items.append(f"**Action:** {a}")
        for d in (decisions or []):
            if d not in items:
                items.append(f"**Beschluss prüfen:** {d}")

    # Sonst bleibt die Agenda leer - der Benutzer fuellt sie selbst.

    # Duplikate raus, Reihenfolge erhalten
    seen, out = set(), []
    for i in items:
        k = i.lower()
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out


# --------------------------------------------------- Sektion lesen/schreiben

def read_agenda_items(text: str) -> list[str]:
    b = ms.section_span(text, AGENDA_HEADING)
    if not b:
        return []
    block = text[b[0]:b[1]]
    items = []
    for line in block.splitlines()[1:]:
        s = line.strip()
        if not s:
            continue
        if s.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+[.)]\s", s):
            item = re.sub(r"^(?:[-*+]|\d+[.)])\s*(?:\[[ xX]\]\s*)?", "", s).strip()
            if item:
                items.append(item)
        # Auch Absaetze erkennen (keine Listenpunkte) - das sind manuelle Eintraege
        elif len(s) > 10:
            items.append(s)
    return items


def agenda_fingerprint(items: list[str]) -> str:
    """Kurzer Hash der generierten Agenda (Frontmatter `agenda_fingerprint`).

    Fuer die Erkennung "hat der Benutzer editiert?" reicht er; die ganze Liste
    im Frontmatter wuerde es aufblaehen und den Body doppeln.
    """
    canonical = "\n".join(i.strip() for i in items)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _render_section(items: list[str]) -> str:
    body = "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1)) if items else "_(noch leer)_"
    return f"{AGENDA_HEADING}\n\n{body}\n"


def apply_agenda(path: Path, items: list[str]) -> str:
    """Agenda in den Body schreiben. Gibt zurueck was passiert ist.

    'created'   Sektion neu angelegt
    'updated'   Sektion war unveraendert generiert -> komplett neu gebaut
    'appended'  Benutzer hat editiert -> nur neue Punkte angehaengt
    'unchanged' nichts zu tun
    """
    text = path.read_text(encoding="utf-8")
    fm, body = vp.split_frontmatter(text)
    last_fp = str(fm.get("agenda_fingerprint") or "")
    current = read_agenda_items(text)

    # Editiert = Sektion weicht vom letzten Generat ab ODER war schon mal editiert.
    # Das Flag ist **sticky**: es darf nie zurueckfallen. Sonst passiert Folgendes -
    # Lauf A erkennt den Edit, zieht den Fingerprint nach, Lauf B sieht keinen
    # Unterschied mehr und generiert die Agenda des Benutzers weg.
    was_edited = fm.get("agenda_user_edited") is True
    user_edited = was_edited or (bool(current) and agenda_fingerprint(current) != last_fp)

    if user_edited:
        existing = {c.lower() for c in current}
        new_items = [i for i in items
                     if i.startswith(INFORMATIONAL_PREFIXES) and i.lower() not in existing]
        if not new_items:
            vp.update_frontmatter(path, {"agenda_items": len(current),
                                         "agenda_user_edited": True})
            return "unchanged"
        final = current + new_items
        action = "appended"
    else:
        final = items
        if current and agenda_fingerprint(current) == agenda_fingerprint(final):
            return "unchanged"
        action = "updated" if current else "created"

    section = _render_section(final)
    b = ms.section_span(text, AGENDA_HEADING)
    if b:
        new_text = text[:b[0]] + section + ("\n" if not text[b[1]:].startswith("\n") else "") + text[b[1]:]
    else:
        # Vor '## Vorbereitung' einfuegen, sonst nach dem ersten H1, sonst anhaengen
        anchor = ms.section_span(text, PREP_HEADING)
        if anchor:
            new_text = text[:anchor[0]] + section + "\n" + text[anchor[0]:]
        else:
            h1 = re.search(r"^#\s+.+$", text, re.MULTILINE)
            if h1:
                new_text = text[:h1.end()] + "\n\n" + section + text[h1.end():]
            else:
                new_text = text.rstrip() + "\n\n" + section

    path.write_text(new_text, encoding="utf-8", newline="\n")
    vp.update_frontmatter(path, {
        "agenda_fingerprint": agenda_fingerprint(final),
        "agenda_items": len(final),
        **({"agenda_user_edited": True} if user_edited else {}),
        "agenda_updated": date.today().isoformat(),
        "series": fm.get("series") or series_key(fm.get("title", "") or path.stem),
    })
    return action


if __name__ == "__main__":
    for t in sys.argv[1:] or ["2026-07-16 --- Jourfix --- Nord Themen Anna und Max",
                              "2026-08-20 Jourfix Nord Themen", "Workshop Portal Days 2026-09-03"]:
        print(f"{t!r}\n   series={series_key(t)!r}  type={detect_meeting_type(t)}")
