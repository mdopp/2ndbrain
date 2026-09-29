#!/usr/bin/env python3
"""zerlegen.py - eine Eingangs-Notiz deterministisch in Bausteine zerlegen, bevor das Modell sie sieht.

Trennt, was ein Skript kann, von dem, was das Modell koennen muss:
  - Frontmatter, formatierte Abschnitte, Checkbox-Aufgaben, Datumsangaben:  Skript
  - Implizite Risiken/Beschluesse im Gespraechsfluss:                       Modell

  - `known_projects` aus `entities/projects/` - das Modell waehlt nur aus dieser Liste.
  - Abschnittserkennung mit Synonymen, englischen Varianten, Toleranz fuer Emoji/##-Tiefe.
  - Relative Fristen werden vorab nach ISO aufgeloest (`zeitangaben`, `resolved_dates`).
  - `known_aliases`, damit das Modell Kurzformen auf Slugs abbilden kann.

Besteht eine Notiz im Kern nur aus Beschluss-/Risiko-/Aufgabenlisten und nennt sie ein
Ziel-Thema (`themen:`), gilt sie als strukturiert und braucht kein Modell. Schreibt nichts;
genutzt von arbeitspaket.py und einarbeiten.py, die Abschnittserkennung auch von agenda.py.

    python zerlegen.py <notiz.md>      # Ergebnis als JSON ansehen
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import zeitangaben
import aufgaben as tk
import vault_paths as vp

# Synonyme pro logischem Abschnitt - die Notizen im Vault sind nicht uniform.
SECTION_SYNONYMS = {
    "decisions": ["entscheidungen", "beschluesse", "beschlüsse", "decisions", "entscheidung"],
    "risks": ["risiken / blocker", "risiken", "blocker", "risks", "risiken/blocker",
              "risiken und blocker", "issues"],
    "actions": ["offene aufgaben", "aufgaben", "action items", "actions", "todos", "to-dos",
                "naechste schritte", "nächste schritte", "next steps", "offene punkte",
                "follow-up-aufgaben", "follow-up tasks", "follow-ups", "follow up",
                "massnahmen", "maßnahmen"],
    "topics": ["besprochene themen", "themen", "agenda", "topics", "notizen", "inhalt",
               "dokumenten-inhalt", "meeting notes", "meeting-notizen", "status",
               "zusammenfassung", "summary", "protokoll"],
}

HEADING_RE = re.compile(r"^(#{2,4})\s*(.+?)\s*$", re.MULTILINE)
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# Mehr Fliesstext ausserhalb der Beschluss-/Risiko-/Aufgaben-Abschnitte heisst:
# die Notiz traegt Inhalt, den nur das LLM erfasst - kein Auto-Complete.
AUTO_MAX_REST_CHARS = 1500
# Frist-Angabe am Ende einer Aufgabe in Inbox-Notizen ("... bis Freitag").
_DEADLINE_TAIL_RE = re.compile(r"\s+(?:bis|→|->|due|deadline:?)\s+(?P<d>.+?)\s*$",
                               re.IGNORECASE)


def _normalize_heading(h: str) -> str:
    """'## 📌 Offene Aufgaben (Sprint 3)' -> 'offene aufgaben'."""
    h = re.sub(r"[^\w\s/äöüÄÖÜß-]", " ", h, flags=re.UNICODE)
    h = re.sub(r"\(.*?\)", " ", h)
    return " ".join(h.lower().split())


def find_sections(text: str) -> dict[str, list[str]]:
    """Alle Abschnitte nach logischer Kategorie sammeln (synonym-tolerant)."""
    matches = list(HEADING_RE.finditer(text))
    out: dict[str, list[str]] = {k: [] for k in SECTION_SYNONYMS}
    for i, m in enumerate(matches):
        norm = _normalize_heading(m.group(2))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end]
        for key, syns in SECTION_SYNONYMS.items():
            if any(norm == s or norm.startswith(s + " ") for s in syns):
                out[key].extend(_section_items(body))
                break
    return out


def _section_items(body: str) -> list[str]:
    """Ein Eintrag pro Aufzaehlungspunkt; umbrochene Folgezeilen gehoeren zum
    vorherigen Punkt (sonst wird aus jedem Zeilenumbruch ein eigenes Event)."""
    items: list[str] = []
    open_item = False
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            open_item = False
            continue
        if line.startswith("<!--"):
            continue
        if BULLET_RE.match(raw):
            items.append(BULLET_RE.sub("", raw, count=1).strip())
            open_item = True
        elif open_item and items:
            items[-1] = f"{items[-1]} {line}"
        else:
            items.append(line)
            open_item = True
    return [i for i in items if i]


def parse_action_items(lines: list[str], base: date) -> list[dict]:
    """Checkbox-Aufgaben deterministisch extrahieren (Parser: aufgaben.py), Frist nach ISO.

    Die Person kommt nur aus der Aufgaben-Syntax (kanonisches Format, Kurzform
    `Was — @wer — Datum` oder `@wer: Text`), nie aus dem ersten Wort: '[ ] Angebot pruefen'
    ist eine Aufgabe ohne Person, nicht owner 'Angebot', task 'pruefen'.
    """
    actions = []
    for line in lines:
        t = tk.parse_line(line if line.lstrip().startswith(("-", "*", "+")) else f"- {line}")
        if t is None or not t.text:
            continue
        owner, text = t.owner or t.owner_raw or "", t.text
        if not owner and text.startswith("@"):
            short = tk.from_short_text(text)      # "@owner: Text"
            owner, text = short.owner_raw or "", short.text
        due, raw_deadline = t.due, None
        if not due:
            m = _DEADLINE_TAIL_RE.search(text)
            if m:
                raw_deadline = m.group("d").strip()
                resolved = zeitangaben.resolve(raw_deadline, base)
                if resolved:
                    due, text = resolved.isoformat(), text[:m.start()].strip()
        if not text:
            continue
        actions.append({
            "owner": owner or "unassigned",
            "task": text,
            "deadline": due or "TBD",
            "deadline_raw": raw_deadline,
            "done": not t.is_open,
        })
    return actions


def clean_wikilinks(lst) -> list[str]:
    if not lst:
        return []
    if isinstance(lst, str):
        lst = [lst]
    return [re.sub(r"\[\[|\]\]", "", str(x)).split("|")[0].strip() for x in lst]


_CTX_CACHE: dict = {}


def load_vault_context() -> dict:
    """Whitelists + Aliasse, die das Modell braucht - aus dem echten Vault.

    Prozessweit gecacht (Epoch aus vault_paths): ein Lauf ueber mehrere
    Dateien laese alle Entity- und Themen-Dateien sonst pro Datei neu.
    """
    epoch = vp.cache_epoch()
    if _CTX_CACHE.get("epoch") == epoch:
        return _CTX_CACHE["ctx"]
    known_projects = {}
    # Themen-Dateien parallel lesen (jeder Datei-Open hat Latenz) statt iter_projects seriell.
    pfiles = ([f for f in sorted(vp.PROJECTS_DIR.glob("*.md")) if f.is_file()]
              if vp.PROJECTS_DIR.is_dir() else [])
    for path, text in vp._read_many(pfiles):
        if text is None:
            continue
        slug, fm = path.stem, vp.split_frontmatter(text)[0]
        known_projects[slug] = {
            "title": fm.get("name") or fm.get("title") or slug,
            "aliases": clean_wikilinks(fm.get("aliases")),
            "status": fm.get("status", ""),
            "lead": clean_wikilinks([fm.get("lead") or fm.get("responsibility")])[0]
                    if (fm.get("lead") or fm.get("responsibility")) else "",
            "systems": clean_wikilinks(fm.get("systems")),
            "target_date": str(fm.get("target_date", "")),
        }
    slugs = vp.known_slugs()  # nutzt den Prozess-/Disk-Cache statt 4x glob+stat
    ctx = {
        "known_projects": known_projects,
        "known_entity_slugs": {c: slugs.get(c, [])
                               for c in ("people", "teams", "companies", "systems")},
        "known_aliases": vp.alias_map(),
    }
    _CTX_CACHE.update(epoch=epoch, ctx=ctx)
    return ctx


def parse_meeting(filepath: str, vault_dir: str | None = None) -> dict:
    text = Path(filepath).read_text(encoding="utf-8")
    fm, body = vp.split_frontmatter(text)

    raw_date = fm.get("date")
    meeting_date = None
    if raw_date:
        try:
            meeting_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            meeting_date = None
    if meeting_date is None:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", Path(filepath).name)
        meeting_date = date.fromisoformat(m.group(1)) if m else date.today()

    sections = find_sections(text)
    action_items = parse_action_items(sections["actions"], meeting_date)

    teilnehmer = clean_wikilinks(fm.get("teilnehmer") or fm.get("participants"))
    projekte = vp.note_themen(fm)

    # Deterministisch nur, wenn die Notiz im Kern aus Beschluss-/Risiko-/
    # Aufgabenlisten besteht UND ein Zielprojekt hat - sonst ginge der
    # restliche Inhalt ungesehen ins Archiv.
    structured_chars = sum(len(x) for k in ("decisions", "risks", "actions")
                           for x in sections[k])
    rest_chars = len(body.strip()) - structured_chars
    is_structured = bool((sections["decisions"] or sections["risks"] or action_items)
                         and projekte and rest_chars <= AUTO_MAX_REST_CHARS)

    deterministic_events: dict[str, list[str]] = {}
    if is_structured:
        # Aufgaben gehen als `action_items` weiter (-> Offene Punkte), nicht
        # zusaetzlich als [ACTION]-Event ins Log (KONZEPT §4.1).
        events = ([f"[DECISION] {e}" for e in sections["decisions"]]
                  + [f"[RISK] {r}" for r in sections["risks"]])
        for slug in projekte:
            deterministic_events[slug] = list(events)
        for a in action_items:
            a["project"] = projekte[0] if projekte else None

    topics = sections["topics"]
    meeting_text = "\n".join(topics) if topics else body.strip()

    ctx = load_vault_context()
    return {
        "is_structured": is_structured,
        "needs_semantic_extraction": not is_structured,
        "deterministic": {
            "meeting_date": meeting_date.isoformat(),
            "teilnehmer": teilnehmer,
            "projekte": projekte,
            "events_by_project": deterministic_events,
            "action_items": action_items,
        },
        "for_llm": {
            "meeting_date": meeting_date.isoformat(),
            "meeting_text": meeting_text,
            "resolved_dates": zeitangaben.find_all(meeting_text, meeting_date),
            **ctx,
        },
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python zerlegen.py <meeting.md>", file=sys.stderr)
        sys.exit(1)
    json.dump(parse_meeting(sys.argv[1]), sys.stdout, indent=2, ensure_ascii=False, default=str)
