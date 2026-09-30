#!/usr/bin/env python3
"""nachbereiten.py - Nachbereitung: Termin-Notiz auswerten, Entscheidungen und Risiken ins Themen-Log.

    2ndbrain nachbereiten                  # alle faelligen Notizen
    2ndbrain nachbereiten --path <datei>
    2ndbrain nachbereiten --dry-run | --json | --since YYYY-MM-DD

Die Automatik (auto.py, Schritte `nachbereiten` und `themenlog`) und das Plugin (Knopf
"Nachbereiten", Vormerkung am Handy) nutzen dieselben Funktionen; die Automatik wartet
ohne Modell, statt den Rueckfall zu nehmen.

Ablauf je Notiz unter `active-meetings/**.md`:
  1. Material aus `## Meine Notizen`/`## Transkript`/`## Teams-Zusammenfassung`/
     `## Mitschrift` sammeln (alle vorhandenen, HTML-Kommentare/Platzhalter raus).
  2. SHA256 ueber das Material gegen `wrapup_fingerprint` im Frontmatter -
     stimmt er, wird uebersprungen ("unveraendert"). Das ist die Stelle, an der
     ein zweiter Lauf nichts verdoppelt.
  3. Playbook laden (Frontmatter `meeting_type` + `variante`, sonst
     `playbook.detect()`).
  4. `nachbereiten_modell.extract()` - oder, wenn das Modell nicht erreichbar ist, die
     deterministische Notloesung aus `agenda.extract_open_items()` (Vault bleibt
     offline benutzbar, Exit bleibt 0). Daten des Modells prueft `daten_pruefen()`
     gegen den Text.
  5. Ergebnis append-only und dedupliziert zurueckschreiben; bestehende Zeilen
     werden nie entfernt oder umformuliert. Nur Transkript oder Teams-Zusammenfassung
     und noch kein Protokoll: `protokoll.py` schreibt `## Protokoll` nach der Vorlage.
  6. Frontmatter aktualisieren (`status`, `wrapped_at`, `wrapup_fingerprint`, Zahlen,
     `nachbereitet_von: modell|notbehelf`).
  7. Nur Nachbereitungen durch das Modell: Entscheidungen und Risiken ins Event Log
     der Themen (`sync_to_logs`, mit der Notiz als Quelle), danach `eingearbeitet:`.
     Aufgaben bleiben in der Notiz.
  8. Danach archiviert der Automatik-Schritt `archivieren` die Notiz (archivieren.py).

Jede Nachbereitung laesst sich zuruecknehmen (`undo()`, `2ndbrain nacherfassen --undo`) -
auch aus dem Archiv: die Notiz kommt dabei zurueck nach active-meetings/.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agenda as ag
import modell
import nachbereiten_modell
import aufgaben as tk
import abschnitte as ms
import vault_paths as vp
import protokoll
import zeitangaben

ACTIVE_DIR = vp.VAULT / "active-meetings"
MATERIAL_HEADINGS = ("## Meine Notizen", "## Transkript", "## Teams-Zusammenfassung",
                     "## Mitschrift")
MIN_PROSE_CHARS = 200

# Feste Reihenfolge des Einheits-Skeletts (siehe entities/meeting-playbooks/README.md
# "Einheitliches Skelett"). Der Kernteil variiert je Playbook und wird dazwischen
# eingefuegt. Nur fuer Sektionen genutzt, die tatsaechlich fehlen - vorhandene
# Notizen behalten ihre Struktur, es wird nur das Fehlende angelegt.
_HEAD = ["## Ziel", "## Vorbereitung", "## Agenda"]
_TAIL = ["## Meine Notizen", "## Entscheidungen", "## Actions", "## Parkplatz", "## Verweise"]

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"^_\(.*\)_$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------- Material

def find_material(text: str) -> str:
    """Prosa aus allen vorhandenen Notiz-/Transkript-Abschnitten, kombiniert.

    HTML-Kommentare und Platzhalter wie "_(wird vom Prep-Lauf gefuellt)_"
    werden herausgefiltert - sonst zaehlt ein leeres Geruest als Material."""
    parts = []
    for heading in MATERIAL_HEADINGS:
        body = _COMMENT_RE.sub("", ms.section_text(text, heading))
        lines = [l for l in body.splitlines()
                 if l.strip() and not _PLACEHOLDER_RE.match(l.strip())]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            parts.append(cleaned)
    return "\n\n".join(parts).strip()


def fingerprint(material: str) -> str:
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# --------------------------------------------------------------- Playbook

def _load_playbook_view(fm: dict, title: str) -> dict:
    """Playbook-Sicht der Notiz: `meeting_type`/`variante` aus dem Frontmatter, sonst
    `playbook.detect()`. Scheitert das Playbook (Import- oder Lesefehler), gibt es eine
    minimale, aber nutzbare Sicht - die Nachbereitung bricht daran nicht ab."""
    try:
        import playbook as pb
    except Exception:
        pb = None

    typ = fm.get("meeting_type") or ""
    variante = str(fm.get("variante") or "")
    if pb is not None:
        try:
            if not typ:
                typ, variante = pb.detect(title)
            return pb.view(typ, variante)
        except Exception:
            pass

    return {"meeting_type": typ or "other", "variante": variante, "label": typ or "other",
            "kernteil": [], "nachbereitung": ["Entscheidungen mit Wer und Datum",
                                              "Actions mit Wer und Frist"],
            "blocks": [], "leitfrage": "", "framing": []}


# --------------------------------------------------------- deterministischer Fallback

def _deterministic_extract(text: str) -> dict:
    """Ohne Modell: nur, was bereits als Text vorliegt - nichts wird generiert.
    Reine Notloesung, damit der Vault ohne LLM benutzbar bleibt."""
    items = ag.extract_open_items(text)
    entscheidungen = [{"was": d, "wer": "", "datum": ""} for d in items.get("decisions", [])]
    actions = []
    for a in items.get("actions", []):
        t = tk.from_short_text(a)  # "@Owner — Titel: Text" / "-> Deadline: D"
        actions.append({"was": t.text, "wer": t.owner_raw or "", "bis": t.due or "",
                        "frage": t.kind == tk.KIND_QUESTION})
    return {"ziel": "", "entscheidungen": entscheidungen, "actions": actions,
            "kernteil": [], "parkplatz": items.get("risks", []), "offene_fragen": []}


# Frist je Aufgabe: Ein Tag ist nur fuer die Aufgabe belegt, bei der er im Material steht. Gegen
# das ganze Material geprueft, galt "in dieser Woche" (bei einer Aufgabe) als Beleg fuer jede Frist
# dieser Woche - so kam eine erfundene Frist der Pruefstufe durch (Befund 29.09.2026).
_SATZ_RE = re.compile(r"(?<=[^\W\d_][.!?])\s+|(?<=[)\]][.!?])\s+")    # nicht nach "29.09."
_WORT_RE = re.compile(r"[^\W\d_]{4,}")
_FUELLWOERTER = frozenset(
    "dass noch wird werden wurde wurden sollen soll sollte eine einen einer eines einem sich nach "
    "ueber über wenn auch ihre ihren seine seinen sein sind haben kann koennen können muss muessen "
    "müssen will wollen dann damit dieser diese dieses sowie beziehungsweise zwischen durch gegen "
    "ohne unter weitere weiteren alle allen jede jeden mehr sehr hier dort this that with from have "
    "been were they their which should would could into also about there these those what when".split())
STELLE_MIN_WOERTER = 2       # so viele Woerter der Aufgabe muessen in einem Satz des Materials stehen
STELLE_MIN_ANTEIL = 0.3      # ... und mindestens dieser Anteil ihrer Woerter
STELLE_NAH = 0.75            # Saetze mit so viel der besten Uebereinstimmung gehoeren mit zur Stelle


def _woerter(text: str) -> set[str]:
    """Inhaltswoerter, auf 6 Zeichen gekuerzt ("Replikation" = "Replikationsunterstuetzung")."""
    return {w.casefold()[:6] for w in _WORT_RE.findall(text or "") if w.casefold() not in _FUELLWOERTER}


def fundstelle(was: str, material: str) -> str:
    """Die Saetze des Materials, von denen eine Aufgabe handelt - "" ohne klare Stelle (dann
    gilt das ganze Material, z. B. wenn das Modell uebersetzt oder stark umformuliert hat)."""
    ziel = _woerter(was)
    if len(ziel) < STELLE_MIN_WOERTER:
        return ""
    saetze = [s for zeile in (material or "").splitlines() for s in _SATZ_RE.split(zeile) if s.strip()]
    wertung = [(len(ziel & _woerter(s)), s) for s in saetze]
    beste = max((n for n, _ in wertung), default=0)
    if beste < max(STELLE_MIN_WOERTER, STELLE_MIN_ANTEIL * len(ziel)):
        return ""
    return "\n".join(s for n, s in wertung if n >= STELLE_NAH * beste)


def daten_pruefen(result: dict, material: str, termin: str) -> dict:
    """Daten des Modells gegen den Text pruefen - das Modell kennt das Jahr des Termins nicht
    und liest auch mal "may" als Mai. Eine Frist bleibt, wenn die Stelle des Materials, von der
    die Aufgabe handelt (`fundstelle`, ohne klare Stelle das ganze Material), sie belegt. Sonst
    rechnet die Engine sie aus, wenn der Punkt selbst sie nennt ("bis Ende der Woche"); sonst
    gilt bei gleichem Tag und Monat das Jahr aus dem Text; sonst entfaellt sie. Eine
    Entscheidung traegt hoechstens das Termindatum (wann entschieden wurde, nicht ein Datum
    aus dem Inhalt)."""
    try:
        base = date.fromisoformat(str(termin or "")[:10])
    except ValueError:
        return result
    ganz = zeitangaben.belegte_daten(material, base)
    for a in result.get("actions") or []:
        bis = str(a.get("bis") or "")
        if not bis:
            continue
        stelle = fundstelle(str(a.get("was") or ""), material)
        belegt = zeitangaben.belegte_daten(stelle, base) if stelle else ganz
        if zeitangaben.pruefe_datum(bis, belegt) == bis:
            continue
        eigene = zeitangaben.find_all(str(a.get("was") or ""), base)
        a["bis"] = eigene[0]["resolved"] if eigene else zeitangaben.pruefe_datum(bis, belegt)
    for e in result.get("entscheidungen") or []:
        if e.get("datum") and e["datum"] != base.isoformat():
            e["datum"] = base.isoformat()
    return result


# ------------------------------------------------------------ Rendering

def _render_decision(e: dict) -> str:
    was = " ".join(str(e.get("was", "")).split())
    wer = " ".join(str(e.get("wer", "")).split()) or "?"   # wie bei Punkten: ? = unbekannt
    datum = str(e.get("datum") or "").strip()
    # Fehlendes Datum entfaellt samt Trenner - kein leeres "— —" in der Notiz.
    return f"- [E] {was} — {wer}" + (f" — {datum}" if datum else "")


# Kein Personenname, sondern eine Gruppe - wird nicht als Rueckfrage gefuehrt.
_GENERIC_OWNERS = {"the team", "team", "das team", "alle", "all", "everyone", "wir", "we",
                   "tbd", "n/a", "-", "—", "?", "unassigned", "unbekannt"}


REIHE_TERMINE = 8        # so viele fruehere Termine der Reihe zaehlen fuer den Personen-Kontext


def _person_context(fm: dict, path: Path | None = None) -> set[str]:
    """Personen des Termins, seiner Themen und seiner Reihe als Slugs - der Kontext, in dem
    ein mehrdeutiger Vorname eindeutig werden darf: Teilnehmer und key_persons; in den Themen
    verlinkte oder mit @ genannte Personen; aus den letzten Terminen der Reihe deren Teilnehmer
    und wer dort Punkte hatte; `mit` der Reihe. Bleibt ein Vorname mehrdeutig: Rueckfrage."""
    people = set(vp.entity_slugs("people"))
    if not people:
        return set()
    aliases = vp.alias_map()

    def slugs(names) -> set[str]:
        out = set()
        for name in [names] if isinstance(names, str) else list(names or []):
            s = str(name).strip().strip("[]").split("|")[0].strip()
            slug = s if s in people else aliases.get(s.lower())
            if slug in people:
                out.add(slug)
        return out

    import aufloesen as rent
    ctx = slugs(list(fm.get("teilnehmer") or []) + list(fm.get("key_persons") or []))
    ctx |= rent.personen_in(vp.project_path(t) for t in vp.note_themen(fm))
    key = str(fm.get("series") or "") or ag.series_key(str(fm.get("title") or (path.stem if path else "")))
    if key:
        import themen as th
        ctx |= slugs(th.series_persons(key))
        frueher = sorted(th._series_notes(key, exclude=path),
                         key=lambda x: str(x[1].get("date") or ""))[-REIHE_TERMINE:]
        for f, ffm in frueher:
            ctx |= slugs(ffm.get("teilnehmer"))
            try:
                tasks = tk.tasks_in_text(f.read_text(encoding="utf-8"), "meeting", stem=f.stem)
            except OSError:
                continue
            ctx |= {t.owner for t in tasks if t.owner in people}
    return ctx


def _resolve_owner(raw: str, persons: set[str]) -> tuple[str | None, str | None]:
    """(slug, rohname): eindeutig - auch erst ueber den Termin-Kontext - wird
    zum Slug; sonst bleibt der Rohname (als 'Name (?)' = Rueckfrage)."""
    name = " ".join(str(raw or "").split()).lstrip("@").strip()
    if not name or name.casefold() in _GENERIC_OWNERS:
        return None, None
    try:
        import aufloesen as rent
        slug, _ = rent.resolve_person_in_context(name, persons)
    except Exception:
        slug = None
    return (slug, None) if slug else (None, name)


def _topic_candidates(material: str, default_topic: str,
                      also: list[str] | None = None) -> list[tuple[str, str]]:
    """(slug, titel) der Themen, die fuer Punkte dieser Notiz in Frage kommen:
    Meeting-Thema zuerst, dann die weiteren Themen des Termins, dann Themen aus
    dem Begriffs-Index (<= 8)."""
    try:
        import begriffsindex as ti
        slugs = ti.candidate_topics(material, default_topic or None)
    except Exception as e:
        print(f"[WARN] Begriffs-Index nicht nutzbar ({type(e).__name__}: {e})", file=sys.stderr)
        slugs = [default_topic] if default_topic else []
    extra = [s for s in (also or []) if s and s not in slugs]
    slugs = (slugs[:1] + extra + slugs[1:]) if default_topic else (extra + slugs)
    # Nur Themen: der Begriffs-Index fuehrt auch Reihen, das Themen-Log schreibt aber nur in
    # Themen - eine Reihe als Ziel wurde eine Rueckfrage. Eine Reihe steht fuer ihre Themen.
    import themen as th
    projects = set(vp.entity_slugs("projects"))
    nur_themen: list[str] = []
    for s in slugs:
        for t in ([s] if s in projects else th.series_topics(s)):
            if t in projects and t not in nur_themen:
                nur_themen.append(t)
    names = tk.Names()
    return [(s, names.topic(s) or s) for s in nur_themen[:8]]


def _action_task(a: dict, meta: dict | None = None) -> tk.Task:
    meta = meta or {}
    owner, owner_raw = _resolve_owner(a.get("wer", ""), meta.get("persons") or set())
    bis = str(a.get("bis") or "").strip()
    created = str(meta.get("created") or "")
    topic = a.get("thema") or meta.get("topic")   # pro Punkt, sonst Meeting-Thema
    return tk.Task(status=" ", text=" ".join(str(a.get("was", "")).split()),
                   kind=tk.KIND_QUESTION if a.get("frage") else tk.KIND_TASK,
                   owner=owner, owner_raw=owner_raw,
                   topics=[topic] if topic else [],
                   due=bis if _ISO_RE.match(bis) else None,
                   created=created if _ISO_RE.match(created) else None)


def _render_bullet(text) -> str:
    return f"- {' '.join(str(text).split())}"


def _content_key(line: str) -> str:
    """Vergleichsschluessel ohne Praefix (`- `, `[E]`, `[ ]`/`[x]`) und Gross/
    Kleinschreibung - damit eine bereits erledigte Action (`[x]`) nicht erneut
    als offene Action (`[ ]`) auftaucht."""
    s = re.sub(r"^-\s*(\[[ ExX]\]\s*)?", "", line.strip())
    return re.sub(r"\s+", " ", s).casefold()


# ----------------------------------------------------- Abschnitte schreiben

def _canonical_order(kernteil: list[str]) -> list[str]:
    return _HEAD + [f"## {k}" for k in kernteil] + _TAIL


def _ensure_section(text: str, heading: str, order: list[str]) -> tuple[str, int, int]:
    """Sektion sicherstellen; fehlt sie, wird sie an ihrer kanonischen Position
    eingefuegt (vor der naechsten Sektion, die schon existiert)."""
    b = ms.section_span(text, heading)
    if b:
        return text, b[0], b[1]
    if heading not in order:
        order = order + [heading]
    idx = order.index(heading)
    insert_at = len(text)
    for later in order[idx + 1:]:
        b2 = ms.section_span(text, later)
        if b2:
            insert_at = b2[0]
            break
    prefix = text[:insert_at]
    if prefix and not prefix.endswith("\n\n"):
        prefix = prefix.rstrip("\n") + "\n\n"
    block = f"{heading}\n\n"
    new_text = prefix + block + text[insert_at:]
    return new_text, len(prefix), len(prefix) + len(block)


def _append_lines(text: str, heading: str, new_lines: list[str], order: list[str]) -> tuple[str, int]:
    if not new_lines:
        return text, 0
    text, start, end = _ensure_section(text, heading, order)
    section = text[start:end]
    existing_keys = {_content_key(l) for l in section.splitlines()[1:] if l.strip()}
    to_add = []
    for l in new_lines:
        k = _content_key(l)
        if k in existing_keys:
            continue
        existing_keys.add(k)
        to_add.append(l)
    if not to_add:
        return text, 0
    insertion = section.rstrip("\n") + "\n" + "\n".join(to_add) + "\n"
    return text[:start] + insertion + text[end:], len(to_add)


def write_extract(text: str, result: dict, playbook_view: dict,
                   previous_stem: str | None, meta: dict | None = None) -> tuple[str, dict]:
    """`meta`: {"topic": Themen-Slug, "created": Termin-Datum, "persons": Kontext-Slugs}."""
    order = _canonical_order(playbook_view.get("kernteil") or [])
    counts = {}

    dec_lines = [_render_decision(e) for e in result.get("entscheidungen") or []
                 if str(e.get("was", "")).strip()]
    act_tasks = [_action_task(a, meta) for a in result.get("actions") or []
                 if str(a.get("was", "")).strip()]
    # Offene Fragen aus dem Meeting werden ❓-Punkte in `## Actions`.
    act_tasks += [_action_task({"was": q, "frage": True}, meta)
                  for q in result.get("offene_fragen") or [] if str(q).strip()]
    park_lines = [_render_bullet(p) for p in result.get("parkplatz") or [] if str(p).strip()]

    text, counts["entscheidungen_neu"] = _append_lines(text, "## Entscheidungen", dec_lines, order)
    if act_tasks:
        # Abschnitt an kanonischer Stelle sicherstellen, dann ueber aufgaben.py
        # schreiben: Dubletten-Schutz ueber den Punkt-Text, nicht die ganze Zeile.
        text, _, _ = _ensure_section(text, "## Actions", order)
        text, counts["actions_neu"] = tk.append_to_section(text, "## Actions", act_tasks,
                                                           tk.Names())
    else:
        counts["actions_neu"] = 0
    text, counts["parkplatz_neu"] = _append_lines(text, "## Parkplatz", park_lines, order)

    allowed = {str(k).strip() for k in (playbook_view.get("kernteil") or [])}
    for block in result.get("kernteil") or []:
        abschnitt = str(block.get("abschnitt", "")).strip()
        if abschnitt not in allowed:
            continue  # sollte bereits durch nachbereiten_modell gefiltert sein - zur Sicherheit
        lines = [_render_bullet(p) for p in block.get("punkte") or [] if str(p).strip()]
        text, n = _append_lines(text, f"## {abschnitt}", lines, order)
        counts[f"kernteil:{abschnitt}"] = n

    if previous_stem:
        text, counts["verweise_neu"] = _append_lines(
            text, "## Verweise", [f"- [[{previous_stem}]]"], order)

    return text, counts


def _previous_meeting_stem(path: Path, fm: dict, title: str) -> str | None:
    """Vorgaenger derselben Reihe fuer `## Verweise` - ueber `vorbereiten.load_meeting_files()`
    und `agenda.find_previous()`, wie in der Vorbereitung. Fehler werden geschluckt,
    der Verweis ist ein Nice-to-have, kein Muss."""
    try:
        import vorbereiten
        all_meetings = vorbereiten.load_meeting_files()
    except Exception:
        return None
    mine = next((m for m in all_meetings if m.get("path") == path), None)
    if mine is None:
        mine = {"path": path, "title": title, "date": str(fm.get("date", "")),
                "series": fm.get("series") or ag.series_key(title)}
    try:
        prev = ag.find_previous(mine, all_meetings)
    except Exception:
        return None
    return prev["path"].stem if prev and prev.get("path") else None


# --------------------------------------------------------------------- Lauf

# Der Termin wurde geaendert, waehrend das Modell rechnete (etwa im Editor getippt): nichts geschrieben
GEAENDERT = "waehrenddessen geaendert"


def process_note(path: Path, *, dry_run: bool = False, min_chars: int = MIN_PROSE_CHARS) -> dict:
    """`min_chars`: ab wann Material reicht - auf Ansage (Nacherfassen, Vormerkung)
    genuegen wenige Stichpunkte, sonst gilt MIN_PROSE_CHARS. Solange das Modell rechnet, steht der
    Termin als in Arbeit (inarbeit.py): das Plugin schreibt andere Notizen weiter, diese erst danach."""
    import inarbeit
    with inarbeit.in_arbeit(path, aktiv=not dry_run):
        return _process_note(path, dry_run=dry_run, min_chars=min_chars)


def _process_note(path: Path, *, dry_run: bool, min_chars: int) -> dict:
    text = path.read_text(encoding="utf-8")
    fm, _ = vp.split_frontmatter(text)
    title = str(fm.get("title") or path.stem)

    material = find_material(text)
    if len(material) < min_chars:
        return {"path": path, "status": "kein Material", "changed": False,
                "entscheidungen": 0, "actions": 0}

    fp = fingerprint(material)
    if str(fm.get("wrapup_fingerprint") or "") == fp:
        return {"path": path, "status": "unveraendert", "changed": False,
                "entscheidungen": 0, "actions": 0}

    playbook_view = _load_playbook_view(fm, title)

    try:
        ok, reason = modell.available()
    except Exception as e:
        ok, reason = False, str(e)

    # Namen wie auf ihren Seiten (schreibweisen.py) - fuers Modell eine Kopie; Transkript,
    # Teams-Text, Mitschrift und eigene Notizen bleiben in der Notiz woertlich
    import schreibweisen
    stoff = schreibweisen.vereinheitlichen(material)[0]
    default_topic = (vp.note_themen(fm) or [""])[0]
    kandidaten = _topic_candidates(stoff, default_topic,
                                   fm.get("themen") if isinstance(fm.get("themen"), list) else None)
    if ok:
        try:
            result = nachbereiten_modell.extract(stoff, playbook_view, {
                "title": title, "date": str(fm.get("date", "")), "topics": kandidaten,
                "default_topic": default_topic})
            mode = "llm"
            if result.get("error"):
                error_reason = result["error"]
                result = _deterministic_extract(text)
                mode = f"deterministisch ({error_reason})"
            else:
                result = daten_pruefen(schreibweisen.json_vereinheitlichen(result), stoff,
                                       str(fm.get("date") or ""))
        except Exception as e:
            result = _deterministic_extract(text)
            mode = f"deterministisch (LLM-Fehler: {e})"
    else:
        result = _deterministic_extract(text)
        mode = f"deterministisch (Modell nicht erreichbar: {reason})"
    if mode != "llm":
        result = schreibweisen.json_vereinheitlichen(result)

    previous_stem = _previous_meeting_stem(path, fm, title)
    meta = {"topic": default_topic,
            "created": str(fm.get("date") or "")[:10], "persons": _person_context(fm, path)}
    new_text, counts = write_extract(text, result, playbook_view, previous_stem, meta)

    # Nur ein Transkript (oder eine Teams-Zusammenfassung) und noch kein Protokoll: das Modell
    # schreibt eines nach der Vorlage des Vaults (protokoll.py)
    counts["protokoll"] = False
    if ok and mode == "llm" and protokoll.braucht_protokoll(new_text):
        try:
            new_text = protokoll.einfuegen(new_text, protokoll.erzeugen(new_text, fm))
            counts["protokoll"] = protokoll.ZIEL in new_text
        except Exception as e:
            print(f"[WARN] Protokoll nicht geschrieben ({type(e).__name__}: {e})", file=sys.stderr)

    n_dec = len(result.get("entscheidungen") or [])
    n_act = len(result.get("actions") or [])

    if not dry_run:
        if path.read_text(encoding="utf-8") != text:
            # Geaendert, waehrend das Modell rechnete: der neue Text wuerde es ueberschreiben. Die
            # Notiz bleibt, wie sie jetzt ist; beim naechsten Nachbereiten kommt das Neue mit.
            return {"path": path, "status": GEAENDERT, "changed": False, "entscheidungen": 0, "actions": 0}
        save_undo(path, text)            # Zustand davor - fuer "Rueckgaengig"
        if new_text != text:
            path.write_text(new_text, encoding="utf-8", newline="\n")
        vp.update_frontmatter(path, {
            "status": "nachbereitet",
            "wrapped_at": datetime.now().isoformat(timespec="seconds"),
            "wrapup_fingerprint": fp,
            "entscheidungen": n_dec,
            "actions": n_act,
            # Nur eine Nachbereitung durch das Modell geht ins Themen-Log und danach ins
            # Archiv; der Notbehelf wartet auf eine echte Nachbereitung.
            "nachbereitet_von": "modell" if mode == "llm" else "notbehelf",
            # zweite Stufe (nachbereiten_modell.pruefen): welches Modell den Entwurf geprueft hat
            "geprueft_von": result.get("geprueft_von") if mode == "llm" else None,
            "eingearbeitet": None,
        })
        finish_undo(path)
        if mode == "llm":
            # Neue Verschreiber von Personen und Themen des Termins -> Rueckfrage (schreibweisen.py)
            umfeld = set(meta["persons"]) | set(vp.note_themen(fm)) | {s for s, _ in kandidaten}
            try:
                schreibweisen.rueckfragen_anlegen(material, umfeld, path)
            except Exception as e:                  # noqa: BLE001 - die Nachbereitung steht schon
                print(f"[WARN] Schreibweisen nicht geprueft ({type(e).__name__}: {e})", file=sys.stderr)

    return {"path": path, "status": mode, "changed": True,
            "entscheidungen": n_dec, "actions": n_act, "counts": counts,
            "result": result, "project": (vp.note_themen(fm) or [""])[0]}


# ----------------------------------------------------------- Rueckgaengig

# Eine Nachbereitung schreibt in die Notiz und (per Sync) in Themen-Logs. Damit
# sie sich zuruecknehmen laesst, haelt jede fest, was sie veraendert hat (je Notiz
# eine Datei; nur die letzte Nachbereitung zaehlt).
UNDO_DIR = vp.DATA_DIR / ".undo"


def _rel(path: Path) -> str | None:
    """Pfad relativ zum Vault - None ausserhalb (dort gibt es kein Rueckgaengig)."""
    try:
        return Path(path).resolve().relative_to(vp.VAULT.resolve()).as_posix()
    except ValueError:
        return None


def _undo_file(path: Path) -> Path | None:
    rel = _rel(path)
    return UNDO_DIR / (hashlib.sha1(rel.encode("utf-8")).hexdigest()[:16] + ".json") if rel else None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_undo(path: Path) -> dict | None:
    f = _undo_file(path)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f else None
    except (OSError, ValueError):
        return None


def _write_undo(path: Path, rec: dict) -> None:
    f = _undo_file(path)
    if f is None:
        return
    UNDO_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


def save_undo(path: Path, before: str) -> None:
    """Zustand vor der Nachbereitung sichern (die letzte Nachbereitung zaehlt)."""
    _write_undo(path, {"note": _rel(path), "before": before, "after_sha": None,
                       "at": datetime.now().isoformat(timespec="seconds"),
                       "sync": {"hash": None, "events": {}}})


def finish_undo(path: Path) -> None:
    rec = load_undo(path)
    if rec is not None:
        rec["after_sha"] = _sha(path.read_text(encoding="utf-8"))
        _write_undo(path, rec)


def verschiebe(src: Path, dest: Path) -> None:
    """Termin-Notiz verschieben (Archiv hin und zurueck); die Sicherung fuer "Zuruecknehmen"
    zieht mit."""
    rec, old = load_undo(src), _undo_file(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dest)
    if rec is not None:
        rec["note"] = _rel(dest)
        _write_undo(dest, rec)
        if old is not None and old != _undo_file(dest):
            old.unlink(missing_ok=True)


def zurueckholen(path: Path) -> Path:
    """Archivierte Termin-Notiz zurueck nach active-meetings/ - Zuruecknehmen macht auch das
    Archivieren rueckgaengig. Liegt die Notiz nicht im Archiv, bleibt alles, wie es ist."""
    if not Path(path).resolve().is_relative_to(vp.MEETINGS_DIR.resolve()):
        return path
    ziel = ACTIVE_DIR / Path(path).name
    if ziel.exists():
        return path
    verschiebe(Path(path), ziel)
    return ziel


def merke_automatik(path: Path, updates: dict) -> None:
    """Frontmatter-Vermerk der Automatik (eingearbeitet, archiviert). Das gilt nicht als
    Aenderung von Hand: stand die Notiz auf dem Stand nach der Nachbereitung, bleibt sie fuer
    "Zuruecknehmen" unveraendert."""
    before = path.read_text(encoding="utf-8")
    vp.update_frontmatter(path, updates)
    rec = load_undo(path)
    if rec is not None and rec.get("after_sha") == _sha(before):
        rec["after_sha"] = _sha(path.read_text(encoding="utf-8"))
        _write_undo(path, rec)


def record_sync(path: Path, payload_hash: str, events: dict[str, list[str]]) -> None:
    """Vom Sync geschriebene Log-Zeilen je Thema (`sync_to_logs`)."""
    rec = load_undo(path)
    if rec is not None:
        rec["sync"] = {"hash": payload_hash, "events": events}
        _write_undo(path, rec)


def undo(path: Path, *, force: bool = False) -> dict:
    """Letzte Nachbereitung zuruecknehmen: Notiz wie davor, Log-Eintraege aus den
    Themen und der Doppelt-Schutz des Syncs entfernt. Wurde die Notiz danach
    noch geaendert, nur mit `force` (die geaenderte Fassung wird gesichert)."""
    import altbestand as ab
    import uebernehmen as hs
    rec = load_undo(path)
    if rec is None:
        return {"ok": False, "grund": "Keine Nachbereitung zum Zurücknehmen gespeichert."}
    current = path.read_text(encoding="utf-8")
    changed = rec.get("after_sha") and _sha(current) != rec["after_sha"]
    if not (changed and not force):
        path = zurueckholen(path)        # aus dem Archiv zurueck nach active-meetings/
    if changed and not force:
        return {"ok": False, "grund": "Die Notiz wurde nach der Nachbereitung geändert.",
                "geaendert": True}
    if changed:
        keep = _undo_file(path).with_suffix(".ueberschrieben.md")
        keep.write_text(current, encoding="utf-8", newline="\n")
    path.write_text(rec["before"], encoding="utf-8", newline="\n")
    removed: dict[str, int] = {}
    for slug, lines in (rec.get("sync") or {}).get("events", {}).items():
        tp = ab.topic_path(slug)
        if tp is None or not lines:
            continue
        text_lines = tp.read_text(encoding="utf-8").split("\n")
        n = 0
        for line in lines:
            if line in text_lines:
                text_lines.remove(line)
                n += 1
        if n:
            tp.write_text("\n".join(text_lines), encoding="utf-8", newline="\n")
            removed[slug] = n
    h = (rec.get("sync") or {}).get("hash")
    if h and hs.PROCESSED_LOG.exists():
        seen = [x for x in hs.PROCESSED_LOG.read_text(encoding="utf-8").split() if x != h]
        hs.PROCESSED_LOG.write_text("\n".join(seen) + ("\n" if seen else ""),
                                    encoding="utf-8", newline="\n")
    _undo_file(path).unlink(missing_ok=True)
    return {"ok": True, "note": _rel(path), "log_entfernt": removed}


def linked_log_lines(stem: str) -> dict[str, list[str]]:
    """{thema: [Log-Zeilen mit (→ [[stem]])]} ueber alle Themen - vor/nach dem Sync
    verglichen ergibt das genau die Zeilen, die der Sync geschrieben hat."""
    import altbestand as ab
    mark = f"(→ [[{stem}]])"
    out: dict[str, list[str]] = {}
    for f in ab._topic_files():
        lines = [l for _, l in tk.section_lines(f.read_text(encoding="utf-8"), tk.EVENT_LOG_SECTION)
                 if mark in l]
        if lines:
            out[f.stem] = lines
    return out


def iter_notes(*, since: str | None = None, only_path: Path | None = None):
    if only_path:
        yield only_path
        return
    if not ACTIVE_DIR.is_dir():
        return
    today = date.today().isoformat()
    for f in sorted(ACTIVE_DIR.rglob("*.md")):
        fm = vp.read_frontmatter(f)
        d = str(fm.get("date") or "")[:10]
        if not _ISO_RE.match(d) or d > today:
            continue
        if since and d < since:
            continue
        if str(fm.get("status") or "") == "entfallen" or fm.get("skip_meeting") is True:
            continue
        yield f


# ------------------------------------------------------------- Themen-Log

def build_sync_payload(reports: list[dict]) -> dict:
    """Payload fuer `uebernehmen.sync` (validiert von `ausgabe_pruefen.py`/`uebernehmen.py`)
    - keine eigene Erfindung des Formats, keine Aufloesung von Slugs hier.

    Nur Entscheidungen und Risiken gehen ins Event Log des Themas. Aufgaben
    bleiben in der Meeting-Notiz, wo sie entstanden sind (KONZEPT §4.1: nie
    kopieren) - Themen- und Personenseiten zeigen sie per Abfrage, Ampel und
    Briefing lesen sie ueber aufgaben.py. Eine zusaetzliche `[ACTION]`-Zeile im
    Log waere eine zweite Kopie, die sich nicht abhaken laesst."""
    project_events: dict[str, list[str]] = {}

    for r in reports:
        result = r.get("result") or {}
        project = r.get("project") or ""

        for e in result.get("entscheidungen") or []:
            was = " ".join(str(e.get("was", "")).split())
            target = e.get("thema") or project     # Zuordnung pro Punkt
            if not was or not target:
                continue
            wer, datum = e.get("wer", ""), e.get("datum", "")
            extra = ", ".join(x for x in (wer, datum) if x)
            event = f"[DECISION] {was}" + (f" ({extra})" if extra else "")
            project_events.setdefault(target, []).append(event)

        # "Risiken" kommen nicht als eigenes Schema-Feld, sondern aus Kernteil-
        # Abschnitten, die inhaltlich Risiken/Blocker sind (Playbooks nennen sie
        # "Risiken", "Top-Risiken" oder "Blocker" - nie woertlich nur "Risiko").
        for block in result.get("kernteil") or []:
            abschnitt = str(block.get("abschnitt", "")).casefold()
            if "risik" not in abschnitt and "blocker" not in abschnitt:
                continue
            if not project:
                continue
            for p in block.get("punkte") or []:
                p = " ".join(str(p).split())
                if p:
                    project_events.setdefault(project, []).append(f"[RISK] {p}")

    return {
        "project_updates": [{"slug": slug, "health": None, "events": evs}
                            for slug, evs in project_events.items()],
        "action_items": [],
    }


def sync_to_logs(reports: list[dict], *, dry_run: bool = False) -> tuple[int, int]:
    """Je nachbereiteter Notiz ein Sync ins Themen-Log, mit ihr als Quelle (Datum + Link).
    Merkt sich die geschriebenen Zeilen fuer "Rueckgaengig". (Notizen, davon mit Rueckfragen)"""
    import uebernehmen
    applied, clarifications = 0, 0
    for r in reports:
        payload = build_sync_payload([r])
        if not payload["project_updates"]:
            if not dry_run:
                merke_automatik(Path(r["path"]), {"eingearbeitet": date.today().isoformat()})
            continue
        rel = Path(r["path"]).relative_to(vp.VAULT).as_posix()
        stem = Path(r["path"]).stem
        before = linked_log_lines(stem)
        rc = uebernehmen.sync(json.dumps(payload, ensure_ascii=False), source_file=rel,
                               dry_run=dry_run)
        if not dry_run:
            # fuer "Rueckgaengig": genau die Zeilen, die dieser Sync geschrieben hat
            after = linked_log_lines(stem)
            added = {s: [l for l in ls if l not in before.get(s, [])] for s, ls in after.items()}
            record_sync(Path(r["path"]), uebernehmen.payload_hash(payload),
                        {s: ls for s, ls in added.items() if ls})
            if rc != 2:                  # eingespielt (offene Rueckfragen laufen eigenstaendig weiter)
                merke_automatik(Path(r["path"]), {"eingearbeitet": date.today().isoformat()})
        applied += 1
        clarifications += rc == 3
    return applied, clarifications


def by_model(report: dict) -> bool:
    """Neu nachbereitet durch das Modell - nur das geht ins Themen-Log (nicht der Rueckfall)."""
    return bool(report.get("changed")) and str(report.get("status", "")).startswith("llm")


# ------------------------------------------------------------------ CLI

def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    as_json = "--json" in args
    only_path = None
    if "--path" in args:
        i = args.index("--path")
        if i + 1 < len(args):
            raw = args[i + 1]
            only_path = Path(raw) if Path(raw).is_absolute() else vp.VAULT / raw
    since = None
    if "--since" in args:
        i = args.index("--since")
        if i + 1 < len(args):
            since = args[i + 1]

    if only_path is not None and not only_path.is_file():
        print(f"[ERROR] Datei nicht gefunden: {only_path}", file=sys.stderr)
        return 1

    reports = [process_note(f, dry_run=dry_run) for f in iter_notes(since=since, only_path=only_path)]
    logged, clarifications = sync_to_logs([r for r in reports if by_model(r)], dry_run=dry_run)

    if as_json:
        public = [{k: (str(v) if isinstance(v, Path) else v) for k, v in r.items()
                   if k != "result"} for r in reports]
        print(json.dumps(public, ensure_ascii=False, indent=2))
        return 0

    if not reports:
        print("Keine faelligen Termin-Notizen unter active-meetings/.")
        return 0

    changed_any = False
    for r in reports:
        rel = r["path"].relative_to(vp.VAULT) if r["path"].is_absolute() else r["path"]
        line = f"  {rel}: {r['status']}"
        if r["changed"]:
            line += f" — {r['entscheidungen']} Entscheidung(en), {r['actions']} Action(s)"
            changed_any = True
        print(line)

    if changed_any:
        print(f"\n{sum(1 for r in reports if r['changed'])} Notiz(en) nachbereitet, "
              f"{logged} davon ins Themen-Log" + (f" ({clarifications} mit Rueckfragen)" if clarifications else "")
              + "." + ("  [DRY-RUN]" if dry_run else ""))
    else:
        print("\nKeine Notiz hatte neues Material.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
