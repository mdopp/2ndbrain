#!/usr/bin/env python3
"""playbook.py - einziger Leser von `entities/meeting-playbooks/`: Termin-Typ, Variante, Leitfaden.

Je Termin-Typ eine Datei (dazu `other` als Rueckfall) - dort steht **die** Quelle
fuer Vor- und Nachbereitung: Frontmatter-Schema in
`entities/meeting-playbooks/README.md`. `vorbereiten.py` (Vorbereitung), `nachbereiten.py`
(Nachbereitung samt Prompt fuer das Modell) und `agenda.py` (Typ-Erkennung) lesen
ausschliesslich ueber dieses Modul - nie direkt aus dem Ordner.

Zirkelimport-Regel (Absicht, nicht Zufall): dieses Modul importiert `agenda`
auf Modulebene (fuer `normalize_title`). `agenda.py` importiert `playbook`
**nur lokal** in `detect_meeting_type()` - sonst wuerde
beim allerersten Import einer der beiden Dateien ein halbfertiges Modul der
anderen im `sys.modules`-Cache landen.

    2ndbrain playbooks                                   # Uebersicht
    2ndbrain playbooks --show <typ> [--variante <v>]     # ein Playbook im Detail
    2ndbrain playbooks --detect "<Titel>"                # Typ eines Titels
    2ndbrain playbooks --prompt <typ> [--variante <v>]   # Prompt-Baustein
    2ndbrain playbooks --json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import agenda
import vault_paths as vp

PLAYBOOK_DIR = vp.ENTITIES_DIR / "meeting-playbooks"

# Die neun Pflicht-H2-Abschnitte, in der vom README vorgegebenen Reihenfolge.
# Ueberschrift (klein) -> Ergebnis-Schluessel, plus ob Bullet-Liste oder Fliesstext.
_SECTION_MAP = {
    "ziel": ("goal", "text"),
    "abgrenzung": ("abgrenzung", "text"),
    "leitfragen": ("questions", "bullets"),
    "risiko-fokus": ("risks", "bullets"),
    "gesprächsführung": ("framing", "bullets"),
    "gespraechsfuehrung": ("framing", "bullets"),
    "vorbereitung": ("checklist", "checkbox"),
    "abbruchkriterium": ("abbruch", "text"),
    "typischer fehler": ("typischer_fehler", "text"),
    "nachbereitung": ("nachbereitung", "bullets"),
}


def _self_slug_default() -> str:
    """Vault-Eigentuemer: `"ich"` in local.config.json, sonst `owner.name` aus
    `calendar.config.json` ("Vorname Nachname" -> "vorname-nachname").
    Ohne beides: leer - kein fester Name als Rueckfall."""
    if vp.ich():
        return vp.ich()
    try:
        cfg_path = vp.DATA_ROOT / "calendar.config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        name = str((cfg.get("owner") or {}).get("name") or "").strip()
        if name:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            if slug:
                return slug
    except Exception:
        pass
    return ""


SELF_SLUG = _self_slug_default()


# ------------------------------------------------------------- Body parsen

def _split_sections(body: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in body.splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            current = h.group(1).strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def _as_text(lines: list[str]) -> str:
    """Absaetze zu einem String verbunden - fuer Ziel/Abgrenzung/Abbruch/Fehler."""
    return " ".join(l.strip() for l in lines if l.strip())


def _as_bullets(lines: list[str]) -> list[str]:
    out = []
    for l in lines:
        t = l.strip()
        if t.startswith(("- ", "* ", "+ ")):
            out.append(re.sub(r"^[-*+]\s*", "", t).strip())
    return out


def _as_checkbox(lines: list[str]) -> list[str]:
    out = []
    for l in lines:
        t = l.strip()
        m = re.match(r"^[-*+]\s*\[[ xX]\]\s*(.+)$", t)
        if m:
            out.append(m.group(1).strip())
    return out


def _parse_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    fm, body = vp.split_frontmatter(text)
    result: dict = dict(fm)
    sections = _split_sections(body)
    for heading, (key, kind) in _SECTION_MAP.items():
        lines = sections.get(heading)
        if lines is None:
            # Fehlender Abschnitt ist kein Fehler (README: "ist er leer").
            result.setdefault(key, "" if kind == "text" else [])
            continue
        if kind == "text":
            result[key] = _as_text(lines)
        elif kind == "bullets":
            result[key] = _as_bullets(lines)
        else:
            result[key] = _as_checkbox(lines)
    result["body"] = body
    result.setdefault("meeting_type", path.stem)
    return result


# --------------------------------------------------------- Cache & Zugriff

_CACHE: dict = {"sig": None, "by_type": None, "ordered": None}


def _playbook_files() -> list[Path]:
    """Playbook-Dateien, `README.md` (Spezifikation, kein Playbook) ausgenommen."""
    if not PLAYBOOK_DIR.is_dir():
        return []
    return sorted(f for f in PLAYBOOK_DIR.glob("*.md") if f.name.lower() != "readme.md")


def _dir_signature() -> tuple:
    return tuple(sorted((f.name, f.stat().st_mtime) for f in _playbook_files()))


def _load_all() -> dict[str, dict]:
    sig = _dir_signature()
    if _CACHE["sig"] == sig and _CACHE["by_type"] is not None:
        return _CACHE["by_type"]
    by_type: dict[str, dict] = {}
    if PLAYBOOK_DIR.is_dir():
        for f in _playbook_files():
            try:
                entry = _parse_file(f)
            except Exception:
                continue
            typ = entry.get("meeting_type") or f.stem
            by_type[typ] = entry
    ordered = sorted(
        by_type.values(),
        key=lambda e: (e.get("match") or {}).get("priority", 999),
    )
    _CACHE.update(sig=sig, by_type=by_type, ordered=ordered)
    return by_type


def all_playbooks() -> list[dict]:
    """Alle Playbooks, aufsteigend nach `match.priority` - Reihenfolge der Erkennung."""
    _load_all()
    return list(_CACHE["ordered"] or [])


_FALLBACK = {
    "meeting_type": "other", "label": "Sonstiges", "leitfrage": "",
    "dauer": "", "kadenz": "", "pflicht_output": "", "vorbereitung_vorlauf": "1 Tag",
    "entscheidung_erforderlich": "offen", "kernteil": [], "blocks": [],
    "match": {"priority": 999, "keywords": []}, "varianten": {}, "extract": [],
    "goal": "", "abgrenzung": "", "questions": [], "risks": [], "framing": [],
    "checklist": [], "abbruch": "", "typischer_fehler": "", "nachbereitung": [],
    "body": "",
}


def load(meeting_type: str) -> dict:
    """Playbook laden. Faellt auf `other` zurueck, wirft nie."""
    by_type = _load_all()
    entry = by_type.get(str(meeting_type or ""))
    if entry is not None:
        return entry
    entry = by_type.get("other")
    return entry if entry is not None else dict(_FALLBACK)


# ----------------------------------------------------------------- Detect

# Deutsche und englische Plurale/Flexionen, die ein Keyword nicht verfehlen
# duerfen: "Portal Nord - Workshops" traegt das Keyword `workshop`, und "Sprint
# Reviews Q3" ist ein `review` - ohne Endung passte `reviews` nicht auf `review`,
# und danach griffe `sprint` (`projekt`). Eine falsche Einstufung
# ist teurer als gar keine - deshalb ist das hier eine geschlossene Liste von
# Endungen und **kein** Praefix-Match: sonst traefe `abnahme` auch auf
# `abnahmekriterium` und `review` auf `reviewer`.
# "er" fehlt bewusst: es macht aus "Reviewer-Runde" ein Review. Kein
# Keyword der Playbooks braucht die Endung.
_KEYWORD_SUFFIXES = ("", "s", "e", "n", "en", "es")


def _keyword_hit(kw: str, padded_norm: str) -> bool:
    kw = str(kw or "").strip().lower()
    if not kw:
        return False
    if f" {kw} " in padded_norm:
        return True
    # Nur das letzte Wort beugen - "roadmap review" wird zu "roadmap reviews",
    # nie zu "roadmaps review".
    return any(f" {kw}{suf} " in padded_norm for suf in _KEYWORD_SUFFIXES[1:])


def _variant_for_entry(entry: dict, title: str, participants=None) -> str:
    if entry.get("varianten_quelle") == "orgchart":
        return resolve_direction(participants, title)
    norm = agenda.normalize_title(title)
    padded = f" {norm} "
    for name, variant in (entry.get("varianten") or {}).items():
        for kw in variant.get("keywords") or []:
            if _keyword_hit(kw, padded):
                return name
    return ""


def variant_for(meeting_type: str, title: str, participants=None) -> str:
    """Variante fuer einen bereits bekannten Typ bestimmen (z.B. bei Handkorrektur)."""
    return _variant_for_entry(load(meeting_type), title, participants)


def detect(title: str, participants=None) -> tuple[str, str]:
    """Meeting-Typ + Variante aus dem Titel. (typ, variante)

    Playbooks nach `match.priority` aufsteigend pruefen, **erster Treffer
    gewinnt** - das ist Absicht: "Roadmap Review" muss `steering` werden, nicht
    `review`; `oneonone` steht vor `checkin`, sonst wird jeder Jour Fixe ein
    Check-in.
    `match.regex` hat gegen den rohen Titel Vorrang (noetig fuer "1:1"/"JF",
    weil `normalize_title` reine Ziffern wegwirft); sonst zaehlen
    `match.keywords` wortgrenzensicher gegen den normalisierten Titel.
    """
    raw = str(title or "")
    norm = agenda.normalize_title(raw)
    padded = f" {norm} "
    for entry in all_playbooks():
        match = entry.get("match") or {}
        rx = match.get("regex") or ""
        hit = bool(rx) and re.search(rx, raw, re.I)
        if not hit:
            hit = any(_keyword_hit(kw, padded) for kw in (match.get("keywords") or []))
        if hit:
            typ = entry.get("meeting_type")
            return typ, _variant_for_entry(entry, raw, participants)
    return "other", ""


# ------------------------------------------------------------- Organigramm

_ORG_START = "<!-- orgchart-auto:start -->"
_ORG_END = "<!-- orgchart-auto:end -->"
_WIKILINK_RE = re.compile(r"\[\[([^\|\]#]+)(?:[^\]]*)?\]\]")

_ORG_CACHE: dict = {"sig": None, "managers": set(), "reports": set()}


def _org_sets() -> tuple[set[str], set[str]]:
    path = vp.PEOPLE_DIR / f"{SELF_SLUG}.md"
    try:
        sig = path.stat().st_mtime
    except OSError:
        sig = None
    if _ORG_CACHE["sig"] == sig and sig is not None:
        return _ORG_CACHE["managers"], _ORG_CACHE["reports"]
    managers: set[str] = set()
    reports: set[str] = set()
    if sig is not None:
        text = path.read_text(encoding="utf-8")
        i, j = text.find(_ORG_START), text.find(_ORG_END)
        block = text[i:j] if 0 <= i < j else ""
        for line in block.splitlines():
            low = line.lower()
            slugs = {m.group(1).strip().lower() for m in _WIKILINK_RE.finditer(line)}
            if "berichtet fachlich an" in low or "vorgesetzt:" in low:
                managers |= slugs
            if "direct reports" in low:
                reports |= slugs
    _ORG_CACHE.update(sig=sig, managers=managers, reports=reports)
    return managers, reports


def _resolve_name(term: str) -> str | None:
    """Eindeutigen Personen-Slug zu Namen/Namensteil - nie fuzzy, nie geraten.

    Nutzt `aufloesen._resolve_person()`, das bei Mehrdeutigkeit bewusst
    `None`-artiges Verhalten zeigt (Kandidatenliste statt Erstbestem). Genau
    diese Enthaltung ist hier gewollt: eine mehrdeutige Namensangabe im Titel
    darf nie zufaellig auf "up" oder "down" fallen, sondern muss "peer" ergeben.
    """
    try:
        import aufloesen
    except Exception:
        return None
    hit = aufloesen._resolve_person(term)
    if hit and hit.get("resolved") == "vault" and hit.get("slug"):
        return str(hit["slug"])
    return None


def _counterpart_slugs(participants, title: str) -> list[str]:
    out: list[str] = []
    parts = participants
    if parts:
        if isinstance(parts, str):
            parts = [parts]
        for p in parts:
            raw = str(p).strip()
            m = re.match(r"^\[\[([^\|\]]+)(?:\|.*)?\]\]$", raw)
            slug = m.group(1).strip() if m else _resolve_name(raw)
            if slug and slug != SELF_SLUG:
                out.append(slug)
        if out:
            return out
    for word in re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", str(title or "")):
        slug = _resolve_name(word)
        if slug and slug != SELF_SLUG:
            return [slug]
    return []


def resolve_direction(participants, title: str) -> str:
    """Richtung des Gegenuebers: 'up' (Vorgesetzter), 'down' (Direct Report), sonst 'peer'.

    Kommt ausschliesslich aus dem Organigramm-Block in
    `entities/people/<SELF_SLUG>.md` - keine Namensliste im Code: hartkodierte
    Vornamen veralten bei jedem Teamwechsel.
    """
    managers, reports = _org_sets()
    for slug in _counterpart_slugs(participants, title):
        if slug in managers:
            return "up"
        if slug in reports:
            return "down"
    return "peer"


# ------------------------------------------------------------------- View

# ------------------------------------------------ Variantenbezogene Bullets

# Abschnitte, deren Bullets einer einzelnen Variante gelten koennen. Ein
# Playbook beschreibt alle Varianten in *einem* Body - ohne diesen Filter
# stuenden bei Variante `down` auch die "Nach oben"-Zeilen in der Notiz. Fuer
# das lokale Modell ist das nicht nur Rauschen, sondern eine falsche Anweisung.
VARIANT_FILTERED_SECTIONS = ("questions", "risks", "framing", "checklist",
                             "nachbereitung")

# Zwei Schreibweisen (README der Playbooks):
#   "Variante `quartal`/`jahr`: ..."   -> Variantennamen stehen in Backticks
#   "Nach oben zusätzlich: ..."        -> Klartext-Marke, im Frontmatter der
#                                         Variante als `marker:` hinterlegt
_VARIANT_TAG_RE = re.compile(
    r"^(?:✅\s*|❌\s*)?Variante\s+((?:`[\w-]+`\s*(?:/|,|\s+oder\s+)?\s*)+):\s*",
    re.IGNORECASE)
_MARKER_TAG_RE = r"^({marker})(?:\s+zus[äa]tzlich)?\s*:\s*"


def filter_variant_lines(items: list, variante: str, marker: str = "") -> list:
    """Bullets entfernen, die ausdruecklich einer *anderen* Variante gelten.

    Bullets ohne Marke gelten immer. Trifft die Marke zu, wird sie abgestreift -
    im Ergebnis steht die Anweisung ohne das "Nach unten:"-Praefix, weil die
    Variante an der Notiz ohnehin dransteht.

    Ohne `variante` (Basis-Sicht, z.B. `2ndbrain playbooks --show oneonone`) bleibt
    alles stehen - dort will man den vollstaendigen Text sehen.
    """
    if not variante:
        return list(items)

    # Marken aller *anderen* Varianten desselben Playbooks fallen unten durch
    # die Backtick-Regel bzw. ueber die eigene Marke.
    own_marker_re = re.compile(_MARKER_TAG_RE.format(marker=re.escape(marker)),
                               re.IGNORECASE) if marker else None
    other_marker_re = re.compile(r"^(Nach oben|Nach unten)(?:\s+zus[äa]tzlich)?\s*:\s*",
                                 re.IGNORECASE)

    out = []
    for raw in items:
        line = str(raw)
        m = _VARIANT_TAG_RE.match(line)
        if m:
            named = {n.strip("`").lower() for n in re.findall(r"`([\w-]+)`", m.group(1))}
            if variante.lower() in named:
                out.append(line[m.end():].strip())
            continue
        if own_marker_re:
            m = own_marker_re.match(line)
            if m:
                out.append(line[m.end():].strip())
                continue
        if other_marker_re.match(line):
            continue          # Marke einer anderen Richtung
        out.append(line)
    return out


def view(meeting_type: str, variante: str = "") -> dict:
    """Playbook-Basis + Variante gemischt.

    Die Variante ueberschreibt jeden gleichnamigen Schluessel der Basis
    (`blocks`, `kernteil`, `dauer`, `entscheidung_erforderlich`,
    `vorbereitung_vorlauf`, `typischer_fehler`, `label`, ...) per Dict-Update -
    nicht gesetzte Schluessel bleiben von der Basis. Variantenfelder ohne
    Basis-Gegenstueck (`frage`, `horizont`, `waehrung`) landen als zusaetzliche
    Schluessel im Ergebnis.
    """
    base = load(meeting_type)
    merged = dict(base)
    variant_entry = (base.get("varianten") or {}).get(variante) if variante else None
    if variant_entry:
        merged.update(variant_entry)
    merged["variante"] = variante or ""
    if variante:
        marker = str((variant_entry or {}).get("marker") or "")
        for key in VARIANT_FILTERED_SECTIONS:
            if isinstance(merged.get(key), list):
                merged[key] = filter_variant_lines(merged[key], variante, marker)
    return merged


# --------------------------------------------------------- Prompt-Baustein

DEFAULT_PROMPT_SECTIONS = ("leitfrage", "pflicht_output", "framing",
                            "typischer_fehler", "nachbereitung")
PROMPT_CHAR_LIMIT = 1200  # quantisiertes Modell: Prompt-Laenge ist das Hauptrisiko, nicht Formulierung.


def prompt_block(meeting_type: str, variante: str = "",
                  sections=DEFAULT_PROMPT_SECTIONS) -> str:
    """Kompakter Playbook-Text fuer einen Prompt des lokalen Modells - hart auf 1200 Zeichen
    gedeckelt. Zurzeit nur ueber `2ndbrain playbooks --prompt` genutzt."""
    v = view(meeting_type, variante)
    label = v.get("label") or meeting_type
    parts = [f"Meeting-Typ: {label}" + (f" ({v['variante']})" if v.get("variante") else "")]
    for key in sections:
        val = v.get(key)
        if not val:
            continue
        if key == "leitfrage":
            parts.append(f"Leitfrage: {val}")
        elif key == "pflicht_output":
            parts.append(f"Pflicht-Output: {val}")
        elif key == "typischer_fehler":
            parts.append(f"Typischer Fehler: {val}")
        elif isinstance(val, list):
            parts.append(f"{key.capitalize()}:\n" + "\n".join(f"- {x}" for x in val[:4]))
        else:
            parts.append(f"{key.capitalize()}: {val}")
    text = "\n".join(parts).strip()
    if len(text) > PROMPT_CHAR_LIMIT:
        text = text[:PROMPT_CHAR_LIMIT - 1].rstrip() + "…"
    return text


def _cli(argv: list[str]) -> int:
    """Auflisten, anzeigen, Typ-Erkennung pruefen.

    Der Standardfall ist die **Auflistung** (`2ndbrain playbooks`). Die Typ-Erkennung
    liegt hinter `--detect`, damit eine Demo-Ausgabe nie als Antwort auf "welche
    Playbooks gibt es" durchgeht.
    """
    import json as _json

    def _arg(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default

    if "--detect" in argv:
        titel = _arg("--detect")
        if not titel:
            print('Aufruf: 2ndbrain playbooks --detect "<Titel>"')
            return 1
        typ, var = detect(titel)
        v = view(typ, var)
        print(f"{titel!r}\n  Typ:       {typ}" + (f"/{var}" if var else ""))
        print(f"  Label:     {v.get('label')}")
        print(f"  Leitfrage: {v.get('leitfrage')}")
        print(f"  Kernteil:  {', '.join(v.get('kernteil') or [])}")
        return 0

    if "--show" in argv:
        typ = _arg("--show")
        v = view(typ or "other", _arg("--variante", ""))
        print(f"# {v.get('label')}" + (f"  [{v['variante']}]" if v.get("variante") else ""))
        print(f"\nLeitfrage:      {v.get('leitfrage')}")
        print(f"Dauer:          {v.get('dauer')}   Kadenz: {v.get('kadenz')}")
        print(f"Pflicht-Output: {v.get('pflicht_output')}")
        print(f"Vorlauf:        {v.get('vorbereitung_vorlauf')}   "
              f"Entscheidung erforderlich: {v.get('entscheidung_erforderlich')}")
        print("\nBloecke:")
        for b in v.get("blocks") or []:
            print(f"  {b['anteil']:>3}%  {b['block']:<28} {b['inhalt']}")
        print("\nKernteil-Abschnitte: " + ", ".join(v.get("kernteil") or []))
        if v.get("checklist"):
            print("\nVorbereitung:")
            for c in v["checklist"]:
                print(f"  - [ ] {c}")
        print(f"\nAbbruchkriterium: {v.get('abbruch')}")
        print(f"Typischer Fehler: {v.get('typischer_fehler')}")
        return 0

    if "--prompt" in argv:
        print(prompt_block(_arg("--prompt") or "other", _arg("--variante", "")))
        return 0

    pbs = all_playbooks()
    if "--json" in argv:
        print(_json.dumps([{k: p.get(k) for k in
                            ("meeting_type", "label", "leitfrage", "dauer", "kadenz",
                             "pflicht_output", "entscheidung_erforderlich",
                             "vorbereitung_vorlauf", "kernteil")}
                           | {"varianten": list((p.get("varianten") or {}).keys())}
                           for p in pbs], ensure_ascii=False, indent=2))
        return 0

    print(f"{len(pbs)} Playbooks in entities/meeting-playbooks/\n")
    print(f"  {'Typ':<11} {'Leitfrage':<44} {'Dauer':<14} Varianten")
    print(f"  {'-'*11} {'-'*44} {'-'*14} {'-'*30}")
    for p in pbs:
        var = ", ".join((p.get("varianten") or {}).keys()) or "-"
        print(f"  {p['meeting_type']:<11} {str(p.get('leitfrage'))[:44]:<44} "
              f"{str(p.get('dauer'))[:14]:<14} {var}")
    print("\n  Ein Playbook im Detail:  2ndbrain playbooks --show <typ> [--variante <v>]")
    print('  Typ eines Titels:        2ndbrain playbooks --detect "<Titel>"')
    print("\nNEXT: 2ndbrain vorbereiten")
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(_cli(_sys.argv[1:]))
