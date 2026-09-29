#!/usr/bin/env python3
"""glossar.py - haelt das Glossar des Vaults (`entities/glossary/`) aus Notizen und Kanon aktuell.

Vier Stufen in einem Lauf; die Automatik startet ihn im Schritt `wissen`, sobald neue Notizen
da sind (wissen.py):

  1. Zaehlen: Begriffe in allen Notizen (fett, Abkuerzungen, Mehrwort-Namen, Tags) ->
     Haeufigkeitsindex `.2ndbrain/daten/glossary.json` (Messwerte fuer die Seiten).
  2. Kanon: Fachobjekte mit Definition -> `status: atlas` (Quelle der Wahrheit, ohne Modell).
  3. Bestand: Messwerte in vorhandenen Seiten nachziehen, Schreibweise ("erp" -> "ERP").
  4. Modell: neue Begriffe (haeufig genug, in mindestens MIN_FILES Notizen, kein Rauschen, keine
     Entity), neue Abkuerzungen (zwei Buchstaben nur mit ausgeschriebener Langform im Text) und
     Seiten ohne Definition. Beide Stopplisten gelten fuer Begriffe und Abkuerzungen. Das Modell
     ordnet ein (Art) und schlaegt eine Definition NUR aus Fundstellen vor. Eine NEUE Seite
     entsteht nur fuer Fachbegriffe, Systeme, Organisation und Abkuerzungen - sonst bekaeme jeder
     haeufige Begriff eine Seite, auch Rauschen. Was das Modell schon eingeordnet hat, fragt es
     erst wieder, wenn sich die Zahl der Fundstellen aendert (`.2ndbrain/daten/glossar_state.json`).

Bestehende Texte werden nie ueberschrieben: nur ein leerer Definitions-Abschnitt wird gefuellt.
`art` ist ein Hinweis; den Status (z.B. zurueckweisen) aendert nur der Mensch. Seiten, die
inzwischen auf eine echte Entity zeigen, meldet der Lauf nur - geloescht wird nichts.

    2ndbrain glossar                 # Bericht, schreibt nichts
    2ndbrain glossar --apply [--no-llm] [--limit N] [--min-count N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import abschnitte as ms
import schreibweisen
import vault_paths as vp

GLOSSARY_JSON = vp.DATA_DIR / "glossary.json"
GLOSSARY_DIR = vp.GLOSSARY_DIR
STATE_FILE = vp.DATA_DIR / "glossar_state.json"
SCAN_MIN_COUNT = 2          # in den Index kommt, was mindestens so oft vorkommt
# Nur Inhalte zaehlen - nicht was Maschinen schreiben: Kalender-Exporte, Migrationsprotokolle,
# Uebersichten und beantwortete Rueckfragen liefern sonst Begriffe wie UID, ACTION und die Titel
# von Terminreihen.
INHALT = ("active-meetings", "archive/meetings", "archive/documents", "archive/emails", "archive/transcripts")


# ------------------------------------------------------------ Kandidaten und Filter

DEFAULT_MIN_COUNT = 10

MIN_LEN = 3

MAX_SOURCES = 12

STOPWORDS = {
    "and", "der", "die", "das", "abo",

    # Dateiformate und Editor-Artefakte
    "pdf", "json", "png", "jpg", "jpeg", "xlsx", "pptx", "docx", "csv", "svg",
    "pasted image", "screenshot", "bild", "image", "attachment", "anhang",

    "naechste schritte", "nächste schritte", "dokumenten-inhalt",
        "one", "neue", "alte", "offene",
    # Struktur-/Dokumentwoerter, die in Protokollen dauernd vorkommen
    "seite", "folie", "slide", "page", "overview", "update", "status", "thema",
    "themen", "meeting", "termin", "notes", "notizen", "protokoll", "agenda",
    "transcript", "call", "review", "weekly", "monthly", "jourfix", "workshop",
    "kontext", "beispiel", "punkt", "punkte", "frage", "fragen", "antwort",
    "ziel", "ziele", "schritt", "schritte", "woche", "monat", "jahr", "tag",
    "uhr", "min", "std", "team", "teams", "person", "personen", "kunde",
    "kunden", "projekt", "projekte", "aufgabe", "aufgaben", "task", "tasks",
    "follow", "generated", "accuracy", "sure", "check", "und", "oder", "aber",
    "software", "development", "grobplanung", "klassifikation",
    # Mail-Header, Teams-/Transkript-Boilerplate, Vault-Artefakte
    "betreff", "gesendet", "name", "neu", "new", "with", "nicht", "participants",
    "vollstaendiger thread", "vollständiger thread", "microsoft teams besprechung",
    "meeting-notizen", "meeting notizen", "inbox", "document-import", "gmbh", "url", "tbd",
    "follow-up", "follow-ups", "next steps", "offene actions", "offene fragen",
    "offene projektfragen", "hauptthema", "ist-zustand", "moving", "tips",
    "app", "bis", "use cases", "technische umsetzung", "team-ordner", "solution design",
    "platform overview", "business unit",
    "key insights", "key takeaways", "action items", "topics discussed", "open questions", "due date",
    "meeting notes", "follow-up tasks", "meeting recap",
    "iii", "microsoft teams-besprechung", "business-unit",
    # Mail-Grussformeln, Waehrung/Zeitzone, Disclaimer (Haftungsklauseln: "SZR"/"SDR"), Betreffzeilen
    "viele grüße", "beste grüße", "millionen euro", "eur", "cest", "szr", "sdr", "agb",
    # Platzhalter und Floskeln
    "yyyy", "yyyy-mm-dd", "vielen dank", "nichts neues", "kein ziel", "vorab", "info",
    "best regards", "kind regards", "weitere informationen",
    # SQL aus zitierten Abfragen in Mails ("LEFT JOIN ... WHERE ... GROUP BY")
    "select", "from", "where", "join", "left", "right", "inner", "outer", "group", "order",
    "union", "distinct", "null", "case", "when", "then", "else", "limit",
    # Praepositionen, die als Abkuerzung durchrutschen ("VOR" in Betreffzeilen)
    "vor", "nach", "bei", "mit", "von", "zum", "zur",
}

# Rausch-Woerter eines bestimmten Vaults (Firmenname, Orte, Personen, Transkriptionsfehler wie
# "Cloud Code" statt Claude Code) stehen in dessen local.config.json unter glossar.ignorieren.
TIME_RE = re.compile(r"^\d{1,2}[:.-]\d{2}$")

# Start-Kategorien fuer einen neuen Vault - nur allgemeine DDD-Begriffe. Die Kategorien
# eines Vaults stehen in seiner glossary.json ("categories") und werden dort gepflegt,
# nicht im Code.
STATIC_CATEGORIES = {
    "ddd": [
        "bounded.*context", "subdomain", "aggregat", "entity", "value.*object",
        "domain.*event", "domain.*service", "context.*map",
    ],
}

# Deutsche/englische Funktionswoerter - eine Mehrwortphrase, die damit endet
# oder beginnt, ist kein Fachbegriff ("Koordination der", "Automatisch importiert aus").
_FUNCTION_WORDS = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "eines", "und", "oder", "aber", "mit", "ohne", "fuer", "für", "von", "vom",
    "zu", "zum", "zur", "aus", "bei", "nach", "ueber", "über", "unter", "auf",
    "in", "im", "ist", "sind", "war", "wird", "werden", "wurde", "hat", "haben",
    "kann", "koennen", "können", "soll", "sollen", "muss", "muessen", "müssen",
    "welche", "welcher", "welches", "diese", "dieser", "dieses", "auch", "noch",
    "nur", "schon", "sehr", "mehr", "alle", "allen", "als", "wie", "wenn",
    "the", "and", "or", "of", "for", "with", "to", "from", "at", "on", "in",
    "is", "are", "was", "will", "be", "by", "as", "that", "this",
}

# Woerter, die in Protokollen strukturell auftauchen, nicht fachlich
_NOISE_WORDS = {
    "naechste", "nächste", "schritte", "dokumenten-inhalt",
        "zusammenfassung", "summary", "referenzen", "anhang", "quelle",
    "generated", "accuracy", "sure", "check", "meeting", "notes", "notizen",
    "follow", "seite", "folie", "slide", "page", "agenda", "status", "update",
    "thema", "themen", "kontext", "inhalt", "datum", "dokumenten", "erkanntes",
    "automatisch", "importiert", "daten", "beispiel", "uebersicht", "übersicht",
}

DEF_HEADING = "## Definition (Ubiquitous Language)"

MIN_FILES = 3

MIN_COUNT = 5

BATCH = 8

MAX_SNIPPETS = 4

ARTEN = ("fachbegriff", "abkuerzung", "system", "organisation", "allgemein", "rauschen", "unklar")

# Abkuerzungen, die nichts Vault-Spezifisches bezeichnen
ACRONYM_STOP = {
    "IT", "KW", "EUR", "AG", "GMBH", "PDF", "OK", "CEO", "CIO", "CTO", "CFO", "HR", "USA", "UK",
    "DE", "EN", "EU", "AI", "KI", "FYI", "ASAP", "TBD", "PS", "CC", "BCC", "RE", "AW", "WG", "FW",
    "MS", "PC", "ID", "IDS", "URL", "URLS", "PPT", "XLS", "CSV", "QA", "Q1", "Q2", "Q3", "Q4",
    "API", "APIS", "UI", "UX", "VPN", "SSO", "MFA", "ETC", "CET", "CEST", "UTC", "MIT", "ICH",
    "PO", "PM", "IST", "NR", "ZB", "BZW", "DH", "USW", "SOW", "VS",
    "INFO", "EVENTS", "MOVING", "CORE", "DEV", "APP", "III", "HTML", "HTTPS", "JSON", "GB",
    "KB", "KG", "HRB", "HGB", "NET", "ISO", "AT", "ES",
    # Laendercodes und Rechtsformen ("SE & Co. KG"); NL fehlt bewusst - in
    # Protokollen oft eine Abkuerzung (z. B. Niederlassung), nicht das Land
    "BE", "BG", "BR", "CA", "CH", "CN", "CZ", "DK", "EE", "FI", "FR", "GR", "HU", "IE", "IN",
    "LT", "LU", "LV", "MX", "NO", "PL", "PT", "RO", "RS", "RU", "SE", "SI", "SK", "TR", "UA",
    "US", "KGAA", "MBH", "SARL", "SPA", "BV",
}

# Nur diese Arten sind Sprache des Vaults (Fach, Systeme, Organisation) und bekommen einen (neuen) Eintrag.
RELEVANT = ("fachbegriff", "abkuerzung", "system", "organisation")

_ACRONYM_RE = re.compile(r"(?<![\w-])([A-ZÄÖÜ][A-ZÄÖÜ0-9]{1,5})(?![\w-])")

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9„\"(\[])")

# Zeilen, die einen neuen Block beginnen (sonst: hart umbrochene Fortsetzung)
_BLOCK_START = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|\||```|---+\s*$)")

_STANDALONE = re.compile(r"^\s*(?:#{1,6}\s|\||```|---+\s*$)")

_LINK_RE = re.compile(r"!?\[\[[^\]]*\]\]|\]\([^)]*\)|https?://\S+")

_PLACEHOLDER_RE = re.compile(r"^\s*(<!--.*?-->\s*)*$", re.S)

_META_LINE_RE = re.compile(r"^[\w-]{2,30}:\s")   # "title: ...", "source_file: ..."

_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

MAX_SNIPPET = 400

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["begriffe"],
    "properties": {"begriffe": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["begriff", "art", "langform", "definition"],
        "properties": {"begriff": {"type": "string"},
                       "art": {"type": "string", "enum": list(ARTEN)},
                       "langform": {"type": "string"}, "definition": {"type": "string"}}}}},
}


def _acceptable_phrase(phrase):
    """Mehrwortphrase pruefen: keine Funktionswoerter am Rand, kein Rauschen."""
    words = phrase.split()
    if not words:
        return False
    if words[0].lower() in _FUNCTION_WORDS or words[-1].lower() in _FUNCTION_WORDS:
        return False
    if any(w.lower() in _NOISE_WORDS for w in words):
        return False
    return True

def extract_candidates_from_content(content):
    r"""Extrahiert potenzielle Fachbegriffe - praezisionsorientiert.

    Eine breite Regel fuer grossgeschriebene Woerter faengt im Deutschen jedes
    satzinitiale Wort und jedes Substantiv ("Welche", "Daten", "Automatisch
    importiert aus", "Koordination der") - der Kandidaten-Index bestuende dann
    ueberwiegend aus Rauschen. Deshalb nur Signale mit hoher Trefferquote:
      1. **Fettgedruckte** Begriffe (in Protokollen meist die Themen-Marker)
      2. Akronyme (ERP, CRM, EDI - meist sehr aussagekraeftig)
      3. Durchgaengig gross geschriebene Mehrwortbegriffe ("Quality Gate",
         "Service Level Agreement") - schliesst satzinitiales Rauschen aus
      4. Frontmatter-Tags
    """
    candidates = []

    # 1. Fettgedruckte Begriffe; an Komma, Semikolon und Schraegstrich trennen
    for b in re.findall(r'\*\*([^*\n]{3,60})\*\*', content):
        if b.strip().endswith(':'):
            continue                  # Beschriftung ("**Playbook:**", "**Risiko:**"), kein Begriff
        b = b.strip().rstrip(':').strip()
        for part in re.split(r'[,;/]', b):
            part = part.strip().rstrip(':').strip()
            if len(part) >= 3 and _acceptable_phrase(part):
                candidates.append(part.lower())

    # 2. Akronyme (2-6 Grossbuchstaben, optional mit Ziffer)
    for a in re.findall(r'\b([A-Z]{2,6}[0-9]{0,2})\b', content):
        if a.lower() not in _NOISE_WORDS:
            candidates.append(a)          # Schreibweise erhalten: EDI, nicht edi

    # 3. Title-Case-Mehrwortbegriffe: JEDES Wort gross
    for m in re.findall(r'\b((?:[A-ZÄÖÜ][a-zäöüß]{2,20})(?:[ -](?:[A-ZÄÖÜ][a-zäöüß]{2,20})){1,3})\b',
                        content):
        if _acceptable_phrase(m):
            candidates.append(m.lower())

    # 4. Frontmatter-Tags
    for tag_block in re.findall(r'tags:\s*\n((?:\s*-\s.*\n)+)', content):
        for line in tag_block.strip().split('\n'):
            tag = line.strip().lstrip('-').strip().lower()
            if len(tag) > 2 and tag not in _NOISE_WORDS:
                candidates.append(tag)

    return candidates


# ------------------------------------------------------------------ 1. Zaehlen

def categorize_term(term, categories):
    """Kategorie ueber die Muster des Index (Start: allgemeine DDD-Begriffe), sonst 'unknown'."""
    term_lower = term.lower()
    for cat, patterns in (categories or STATIC_CATEGORIES).items():
        for pattern in patterns:
            if re.search(pattern, term_lower, re.I):
                return cat
    return "unknown"


_ZAUNBLOCK_RE = re.compile(r"^[ \t>]*(`{3,}|~{3,})[ \t]*([^\s`]*)([^\n]*)\n.*?(?:^[ \t>]*\1[ \t]*$|\Z)", re.M | re.S)
# Code und Diagramme - Mails stehen in einem schlichten Zaun (fremdtext.zaun), die bleiben
_CODE_SPRACHEN = {"mermaid", "dataview", "dataviewjs", "base", "yaml", "yml", "xml", "json", "bash", "sh", "js",
                  "javascript", "ts", "typescript", "python", "py", "sql", "powershell", "ps1", "c4", "likec4"}


def _ohne_code(m: re.Match) -> str:
    lang = m.group(2).lower()
    code = lang in _CODE_SPRACHEN or (lang == "text" and m.group(3).strip() != "")   # ```text dataviewjs
    return " " if code else m.group(0)
_AUTO_BLOCK_RE = re.compile(r"<!--\s*(stand-auto|people-auto|orgchart-auto):start\s*-->.*?<!--\s*\1:end\s*-->"
                            r"|<!--\s*altbestand(?:-person)?:[\w-]+\s*-->.*?<!--\s*altbestand:end\s*-->", re.S)
_KOMMENTAR_RE = re.compile(r"<!--.*?-->", re.S)
_MARKER_RE = re.compile(r"\[(?:STATUS|DECISION|RISK|ACTION|MILESTONE|DEADLINE|E)\]")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_VORLAGE_RE = re.compile(r"^## Vorbereitung[ \t]*$.*?(?=^## |\Z)", re.M | re.S)


def inhalt(body: str) -> str:
    """Nur, was Menschen geschrieben haben: ohne Code und Diagramme (Mermaid "flowchart LR", Dataview;
    Mails im schlichten Zaun zaehlen),
    automatische Bloecke (Stand, Altbestand, Personen), Kommentare, Log-Markierungen ([RISK]) und
    die Vorlage unter `## Vorbereitung` (Playbook-Tabellen, die jede Termin-Notiz mitbringt).
    Sonst werden "LR", "RISK", "Konkrete Zusagen" oder "Aufgaben-Zeilen" zu Glossar-Seiten."""
    t = _ZAUNBLOCK_RE.sub(_ohne_code, body)
    t = _AUTO_BLOCK_RE.sub(" ", t)
    t = _KOMMENTAR_RE.sub(" ", t)
    t = _VORLAGE_RE.sub(" ", t)
    t = _MARKER_RE.sub(" ", t)
    return _INLINE_CODE_RE.sub(" ", t)


def _scan_sources():
    """(datei, frontmatter-text, rumpf, datum) aller Notizen: Root, Archiv, aktive Termine.
    Nur der Rumpf zaehlt - Frontmatter ist Metadatenrauschen, ausser den Tags."""
    seen = set()
    for pattern in ("*.md",) + tuple(f"{d}/**/*.md" for d in INHALT):
        for f in vp.VAULT.glob(pattern):
            if not f.is_file():
                continue
            rp = f.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            if f.name.startswith((".", "0")) or f.name in ("README.md", "MEMORY.md"):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
            fm_text, body = (m.group(1), text[m.end():]) if m else ("", text)
            dm = re.search(r"^date:\s*['\"]?(\d{4}-\d{2}-\d{2})", fm_text, re.MULTILINE)
            nm = re.match(r"^(\d{4}-\d{2}-\d{2})", f.name)
            yield f.name, fm_text, body, dm.group(1) if dm else (nm.group(1) if nm else "")


def load_index() -> dict:
    try:
        data = json.loads(GLOSSARY_JSON.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "last_updated": "", "terms": {}, "categories": dict(STATIC_CATEGORIES)}


def load_candidates() -> dict[str, dict]:
    """Begriffe des Haeufigkeitsindex (fuer Filter und Referenzlauf)."""
    terms = load_index().get("terms") or {}
    return terms if isinstance(terms, dict) else {}


def scan(min_count: int = SCAN_MIN_COUNT) -> dict:
    """Haeufigkeitsindex neu aus allen Notizen - Zaehler werden gesetzt, nicht addiert (sonst
    erhoeht jeder Lauf die Zahlen). Von Hand ergaenzte Begriffe ohne Fundstellen bleiben. Schreibt nicht."""
    index = load_index()
    previous = index.get("terms") or {}
    term_count, term_files, term_first, term_last = Counter(), {}, {}, {}
    for fname, fm_text, body, day in _scan_sources():
        # Links verweisen auf Seiten (Dateinamen wie "… - checkin - <Reihe>"), sie sind keine Fundstellen
        candidates = extract_candidates_from_content(_LINK_RE.sub(" ", inhalt(body)))
        candidates += extract_candidates_from_content(fm_text if "tags:" in fm_text else "")
        for c in candidates:
            c = c.strip().lower()
            if len(c) < 3:
                continue
            term_count[c] += 1
            term_files.setdefault(c, set()).add(fname)
            if day:
                if c not in term_first or day < term_first[c]:
                    term_first[c] = day
                if c not in term_last or day > term_last[c]:
                    term_last[c] = day
    terms = {}
    for term, count in term_count.items():
        if count < min_count:
            continue
        old = previous.get(term, {})
        terms[term] = {"count": count,
                       "category": old.get("category") or categorize_term(term, index.get("categories")),
                       "first_seen": term_first.get(term, old.get("first_seen", "")),
                       "last_seen": term_last.get(term, old.get("last_seen", "")),
                       "files": sorted(term_files.get(term, set()))[:20]}
    for term, meta in previous.items():
        if term not in terms and not meta.get("files"):
            terms[term] = meta
    index["terms"] = terms
    index["last_updated"] = datetime.now().isoformat()
    return index


def save_index(index: dict) -> None:
    """Index schreiben - UTF-8 ausdruecklich (sonst schreibt Windows cp1252 und bricht an einem
    Sonderzeichen ab) und ueber eine .tmp-Datei, damit ein Abbruch keine leere Datei hinterlaesst."""
    GLOSSARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = GLOSSARY_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    tmp.replace(GLOSSARY_JSON)


# ------------------------------------------------------------ Filter und Bestand

# Die Glossar-Kategorie ist hier bewusst ausgenommen: sonst filtert der Lauf
# genau die Begriffe weg, die er im Lauf davor angelegt hat (die sind dann
# selbst Entities). Vorhandene Glossardateien erkennt `existing_terms()`.
_ENTITY_CATEGORIES_FOR_NOISE = ("people", "teams", "companies", "systems",
                                "projects", "contexts")


def entity_names() -> set[str]:
    """Alles, was schon eine eigene Nicht-Glossar-Entity hat (inkl. Aliasse)."""
    out = set()
    for cat in _ENTITY_CATEGORIES_FOR_NOISE:
        d = vp.CATEGORY_DIRS.get(cat)
        if not d or not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            fm = vp.read_frontmatter(f)
            keys = [f.stem, f.stem.replace("-", " "), fm.get("name")]
            aliases = fm.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            keys.extend(aliases)
            for k in keys:
                if k:
                    out.add(str(k).strip().lower())
            for part in f.stem.split("-"):
                if len(part) > 2:
                    out.add(part)
    return out


_ENGINE_WOERTER: set[str] = set()


def _zeichenketten(f: Path) -> list[str]:
    """String-Literale einer Code-Datei, ohne Docstrings."""
    import ast
    try:
        tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def engine_woerter() -> set[str]:
    """Ueberschriften (`## …`) und fette Beschriftungen (`**…**`), die die Engine selbst in Notizen
    schreibt - aus den Zeichenketten ihres Codes gelesen. Sie stehen in fast jeder Notiz und sind
    doch kein Fachbegriff (sonst ordnet das Modell z. B. "Risiko" und "Playbook" als Fachbegriff ein).
    Kommentare und Docstrings zaehlen nicht: sie beschreiben den Code und landen in keiner Notiz -
    wer die Doku umschreibt, veraendert damit nicht das Glossar."""
    if _ENGINE_WOERTER:
        return _ENGINE_WOERTER
    rx = re.compile(r"#{2,4} ([A-ZÄÖÜ][^\n\"'{}#]{2,50})|\*\*([A-ZÄÖÜ][^*\n\"'{}]{1,50}?)\*\*")
    for f in Path(__file__).resolve().parent.glob("*.py"):
        if f.name.startswith("test_"):
            continue
        for text in _zeichenketten(f):
            for m in rx.finditer(text):
                phrase = " ".join((m.group(1) or m.group(2)).split()).rstrip(":").strip().lower()
                if len(phrase) >= 3:
                    _ENGINE_WOERTER.add(phrase)
    return _ENGINE_WOERTER


def first_names() -> set[str]:
    """Vornamen aus den Personen-Slugs (`anna-beispiel` -> 'anna')."""
    out = set()
    for slug in vp.entity_slugs("people"):
        head = slug.split("-")[0]
        if len(head) > 2:
            out.add(head)
    return out


def looks_like_person(term: str, names: set[str]) -> bool:
    """'anna beispiel' ist ein Name, kein Fachbegriff.

    Deterministisch statt heuristisch: genau zwei Woerter und das erste ist ein
    Vorname, der im Vault schon bei einer Person vorkommt.
    """
    import unicodedata
    plain = unicodedata.normalize("NFKD", term.lower()).encode("ascii", "ignore").decode()
    parts = plain.split()
    if len(parts) == 1 and "-" in plain:  # 'anna-lena'
        return plain.split("-")[0] in names
    return len(parts) == 2 and parts[0] in names


def looks_like_meeting_title(term: str, names: set[str]) -> bool:
    """'weekly anna', 'abstimmung berta': Termintyp + Vorname - ein Terminname aus den
    Titeln, kein Begriff. Den Typ erkennt dieselbe Regel wie bei den Terminen (Playbooks)."""
    parts = term.lower().split()
    if len(parts) != 2 or not any(p in names for p in parts):
        return False
    import playbook
    return playbook.detect(term)[0] != "other"


def vault_stopwords() -> set[str]:
    """Rausch-Woerter dieses Vaults: `glossar.ignorieren` in local.config.json."""
    g = vp.local_config().get("glossar")
    words = g.get("ignorieren") if isinstance(g, dict) else None
    return {str(w).strip().lower() for w in (words or []) if str(w).strip()}


def filter_candidates(terms: dict[str, dict], min_count: int) -> tuple[dict, dict[str, int]]:
    # Beide Quellen zusammen, damit keine Abdeckung verloren geht: `entity_names()`
    # deckt Slug-Teile ab (wie 'mustermann' aus 'max-mustermann'), die `alias_map()`
    # nicht einzeln fuehrt; `alias_map()` deckt `aliases:` robuster ab, auch die
    # automatisch gesetzten Vornamen-Aliasse.
    known = entity_names() | set(vp.alias_map().keys())
    ignore = vault_stopwords()
    engine = engine_woerter()
    names = first_names()
    kept = {}
    reasons = {"zu_selten": 0, "zu_wenig_notizen": 0, "zu_kurz": 0, "stoppwort": 0, "ist_entity": 0,
               "personenname": 0, "engine_wort": 0}
    for term, meta in terms.items():
        t = str(term).strip()
        low = t.lower()
        if int(meta.get("count", 0)) < min_count:
            reasons["zu_selten"] += 1
        elif len(set(meta.get("files") or [])) < MIN_FILES:
            # Sprache des Vaults steht in mehreren Notizen - eine einzige (eine Liste, eine
            # Spezifikation) liefert sonst Namen und Technikwoerter, die nirgends sonst stehen
            reasons["zu_wenig_notizen"] += 1
        elif len(t) < MIN_LEN:
            reasons["zu_kurz"] += 1
        elif low in STOPWORDS or low in ignore or low.upper() in ACRONYM_STOP or TIME_RE.match(low):
            reasons["stoppwort"] += 1
        elif low in engine or (" " in low and any(f" {low} " in f" {e} " for e in engine)):
            reasons["engine_wort"] += 1
        elif low in known:
            reasons["ist_entity"] += 1
        elif looks_like_person(low, names) or looks_like_meeting_title(low, names):
            reasons["personenname"] += 1
        else:
            kept[t] = meta
    return kept, reasons


def managed_fields(meta: dict) -> dict:
    files = [str(f) for f in (meta.get("files") or [])]
    return {
        "occurrences": int(meta.get("count", 0)),
        "first_seen": str(meta.get("first_seen", ""))[:10],
        "last_seen": str(meta.get("last_seen", ""))[:10],
        "source_files": len(set(files)),
        "sources": sorted(set(files))[:MAX_SOURCES],
        "auto_category": str(meta.get("category", "unknown")),
        "synced_at": date.today().isoformat(),
    }


def update_term(path: Path, meta: dict, dry_run: bool) -> str:
    """Nur die automatisch gepflegten Zahlen aktualisieren - Rumpf bleibt unberuehrt."""
    fields = managed_fields(meta)
    current = vp.read_frontmatter(path)
    if all(current.get(k) == v for k, v in fields.items() if k != "synced_at"):
        return "unchanged"
    if dry_run:
        return "would-update"
    vp.update_frontmatter(path, fields)
    return "updated"


def find_shadowed_terms() -> list[tuple[Path, str]]:
    """Bestehende Glossar-Dateien, die inzwischen auf eine echte Entity zeigen.

    `filter_candidates()` verhindert nur *neue* Duplikate (ueber `entity_names()`).
    Eine Glossar-Datei, die vor der passenden Entity entstand (z. B. ein
    Personen-Slug wie `vorname-nachname` vor `entities/people/*.md`), bliebe
    sonst liegen - `update_term()` prueft nicht erneut, ob ein Begriff
    nachtraeglich zur Entity wurde. Das hier ist diese Nachpruefung.
    """
    aliases = vp.alias_map()
    out = []
    if not GLOSSARY_DIR.is_dir():
        return out
    # 'glossary' selbst ausnehmen: sonst gewinnt bei identischem Dateinamen
    # (z.B. 'max-mustermann.md' liegt sowohl unter people/ als auch unter
    # glossary/) ein blosser String-Vergleich `slug != f.stem` nicht - beide
    # Seiten haben denselben Namen, obwohl die Glossar-Datei tatsaechlich
    # von der Personen-Datei ueberdeckt wird. Massgeblich ist, ob der
    # aufgeloeste Slug in einer ANDEREN Kategorie als 'glossary' existiert.
    non_glossary_dirs = [(c, d) for c, d in vp.CATEGORY_DIRS.items() if c != "glossary"]
    for f in sorted(GLOSSARY_DIR.glob("*.md")):
        fm = vp.read_frontmatter(f)
        term = str(fm.get("term") or f.stem)
        slug = aliases.get(term.strip().lower())
        if not slug:
            # Fallback: der Glossar-Dateiname selbst ist oft schon der Slug
            # (`anna-beispiel.md`), auch wenn `term:` im Frontmatter vom
            # gepflegten `name:`/`aliases:` der Person abweicht (z.B. `term:
            # anna beispiel` (zwei Woerter) gegen `name: Anna` (nur Vorname,
            # keine Aliasse) - der Alias-Index kennt dann "anna beispiel"
            # nicht, obwohl es dieselbe Person ist). Slugify des Dateinamens
            # selbst pruefen, bevor aufgegeben wird.
            slug = vp.slugify(f.stem)
        if not slug:
            continue
        if any(d.is_dir() and (d / f"{slug}.md").exists() for _, d in non_glossary_dirs):
            out.append((f, slug))
    return out


def existing_terms() -> dict[str, Path]:
    """slug -> Pfad, plus Zuordnung ueber `term`/`synonyms` im Frontmatter."""
    out = {}
    if not GLOSSARY_DIR.is_dir():
        return out
    for f in sorted(GLOSSARY_DIR.glob("*.md")):
        fm = vp.read_frontmatter(f)
        out[f.stem] = f
        for key in (fm.get("term"), *(fm.get("synonyms") or [])):
            if key:
                out[vp.slugify(str(key))] = f
    return out


# ------------------------------------------------------------ 2.-4. Kanon, Fundstellen, Modell

def _glossar_cfg() -> dict:
    """`glossar` in local.config.json: kontext ("der IT von <Firma>"), fach (z.B. "Logistik"),
    beispiele je Art ({"system": "…", "fachbegriff": "…", "organisation": "…"}). Die Beispiele
    helfen dem kleinen Modell beim Einordnen - sie gehoeren zum Vault, nicht in den Code."""
    c = vp.local_config().get("glossar")
    return c if isinstance(c, dict) else {}


def configured_examples() -> dict[str, str] | None:
    """Feste Beispiele aus der Konfiguration; None bei "auto" oder ohne Angabe (dann abgeleitet)."""
    b = _glossar_cfg().get("beispiele")
    return {k: str(v) for k, v in b.items() if v} if isinstance(b, dict) and any(b.values()) else None


def build_prompt(beispiele: dict[str, str] | None = None) -> str:
    """System-Prompt fuer das Einordnen; `beispiele` je Art (system, fachbegriff, organisation)."""
    b = beispiele or {}
    fach = str(_glossar_cfg().get("fach") or "").strip()

    def bsp(art: str) -> str:
        return f" (z.B. {b[art]})" if b.get(art) else ""
    return (
        f"Du pflegst das Glossar (Ubiquitous Language) {_glossar_cfg().get('kontext') or 'dieses Vaults'}. Fuer jeden "
        "Begriff: art bestimmen und eine Definition in 1-2 Saetzen NUR aus den Fundstellen - "
        "erfinde nichts. langform nur, wenn sie woertlich in den Fundstellen steht, sonst leer.\n"
        "art - was bezeichnet der Begriff in den Fundstellen?\n"
        f"- system: IT-System, Plattform, Anwendung, Schnittstelle, Datenmodell{bsp('system')}\n"
        f"- fachbegriff: Begriff aus {fach + ', ' if fach else ''}Geschaeft oder Projektarbeit{bsp('fachbegriff')}\n"
        f"- organisation: Team, Bereich, Gremium, Standort, Firma{bsp('organisation')}\n"
        "- abkuerzung: Abkuerzung, deren Bedeutung die Fundstellen nicht zeigen\n"
        "- allgemein: NUR weltweit gebraeuchlicher IT-Standard (Protokoll, Format, Sprache: "
        "HTTP, SQL, XML, DNS, REST, PHP) - nie fuer Systeme, Projekte oder Fachbegriffe\n"
        "- rauschen: kein Begriff (Personenname, Datum, Fuellwort)\n"
        "- unklar: die Fundstellen reichen nicht fuer eine Einordnung - im Zweifel 'unklar'.\n"
        "Geben die Fundstellen keine Definition her: definition leer. Deutsch.")


def _clean_name(n) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(n or "")).strip()


def example_pools(docs: list[tuple[str, str]]) -> dict[str, list[tuple[int, str]]]:
    """Was der Vault je Art bestaetigt, nach Nennungen in den Notizen (meiste zuerst):
    system = Systeme der Systemuebersicht (dieselbe Auswahl wie im LikeC4-Modell: keine Themen-
    oder Kontext-Seiten, nichts mit `uebersicht: false`), organisation = Teams, Reihen/Gremien,
    Firmen; fachbegriff = Fachobjekte aus dem Kanon (Glossar mit `status: atlas`).
    Ein Name in zwei Pools (ein Team, das wie sein Produkt heisst) ist mehrdeutig und faellt raus."""
    import systemuebersicht as su
    names: dict[str, set[str]] = {"system": set(), "organisation": set(), "fachbegriff": set()}
    topics = su.load_topics()
    systems = su.load_systems(topics)
    su.place(systems, topics)
    for x in systems.values():
        if x["bereich"] and not x["aus"]:
            names["system"].add(_clean_name(x["name"]))
    for cat in ("teams", "forums", "companies"):
        for f in sorted(vp.CATEGORY_DIRS[cat].glob("*.md")):
            fm = vp.read_frontmatter(f) or {}
            names["organisation"].add(_clean_name(fm.get("name") or fm.get("title") or f.stem))
    for f in sorted(vp.GLOSSARY_DIR.glob("*.md")) if vp.GLOSSARY_DIR.is_dir() else []:
        fm = vp.read_frontmatter(f) or {}
        if fm.get("status") == "atlas":
            names["fachbegriff"].add(str(fm.get("term") or f.stem).strip())
    low = [t.lower() for _, t in docs]
    seen: dict[str, int] = {}
    for ns in names.values():
        for n in {x.lower() for x in ns}:
            seen[n] = seen.get(n, 0) + 1
    out = {}
    for art, ns in names.items():
        ranked = []
        for n in ns:
            if seen.get(n.lower(), 0) > 1:
                continue
            if not 2 <= len(n) <= 30:
                continue
            rx = re.compile(r"(?<![\w-])" + re.escape(n.lower()) + r"(?![\w-])")
            c = sum(1 for t in low if rx.search(t))
            if c >= 2:
                ranked.append((c, n))
        out[art] = sorted(ranked, key=lambda x: (-x[0], x[1].lower()))
    return out


def derived_examples(docs: list[tuple[str, str]], k: int = 3, exclude: set[str] | frozenset = frozenset(),
                     pools: dict | None = None) -> dict[str, str]:
    """Je Art die k meistgenannten bestaetigten Namen (ohne `exclude`) - statt fester Beispiele im Code."""
    pools = pools or example_pools(docs)
    ex = {e.lower() for e in exclude}
    return {art: ", ".join(n for _c, n in [x for x in ranked if x[1].lower() not in ex][:k])
            for art, ranked in pools.items() if ranked}

SYSTEM_PROMPT = build_prompt(configured_examples())


def corpus() -> list[tuple[str, str]]:
    """(datei-stem, text) aller Meeting-/Mail-Notizen (aktiv + Archiv)."""
    out = []
    for root in (vp.VAULT / d for d in INHALT):
        if root.is_dir():
            for f in sorted(root.rglob("*.md")):
                try:
                    # nur der Text: im Frontmatter stehen Titel/Dateinamen, keine Aussagen
                    out.append((f.stem, inhalt(vp.split_frontmatter(f.read_text(encoding="utf-8"))[1])))
                except (OSError, UnicodeDecodeError):
                    continue
    return out


def _paragraphs(text: str):
    """Absaetze mit zusammengefuegten harten Umbruechen - sonst zerfaellt
    "... vom Wegwerf-\\nPrototyp bis zum Betrieb." in ein Fragment ohne
    Aussage. Listenpunkte, Ueberschriften und Tabellenzeilen beginnen einen
    neuen Absatz."""
    para: list[str] = []
    quote = False
    for line in text.splitlines():
        stripped = line.strip()
        is_quote = stripped.startswith(">")
        if not stripped or _BLOCK_START.match(line) or is_quote != quote:
            if para:
                yield " ".join(para)
            para = []
        quote = is_quote
        if not stripped:
            continue
        if _STANDALONE.match(line):          # Ueberschrift/Tabellenzeile: nie fortgesetzt
            yield stripped
            continue
        para.append(stripped.lstrip("> ").strip() if is_quote else stripped)
    if para:
        yield " ".join(para)


def _window(s: str, start: int, size: int = MAX_SNIPPET) -> str:
    """Ueberlange Saetze auf ein Fenster um die Fundstelle kuerzen."""
    if len(s) <= size:
        return s
    a = max(0, min(start - size // 2, len(s) - size))
    return ("…" if a else "") + s[a:a + size].strip() + ("…" if a + size < len(s) else "")


def expansion(term: str, sentence: str) -> str:
    """Belegte Langform eines Akronyms: "Enterprise Resource Planning (ERP)" oder
    "ERP (Enterprise Resource Planning)" - nur wenn die Anfangsbuchstaben passen."""
    t = term.upper()
    if not 2 <= len(t) <= 6 or not t.isalpha():
        return ""
    word = r"[A-Za-zÄÖÜäöüß][\w&]*"
    before = re.search(rf"(?<![\w-])((?:{word}[ -]+){{{len(t) - 1}}}{word})\s*\(\s*{re.escape(t)}\s*\)", sentence)
    after = re.search(rf"(?<![\w-]){re.escape(t)}\s*\(\s*((?:{word}[ -]+){{{len(t) - 1}}}{word})\s*\)",
                      sentence)
    for m in (before, after):
        if m and "".join(w[0] for w in re.split(r"[ -]+", m.group(1))).upper() == t:
            return m.group(1)
    return ""


def snippets(term: str, docs: list[tuple[str, str]], limit: int = MAX_SNIPPETS) -> list[tuple[str, str]]:
    """Aussagekraeftigste Saetze mit dem Begriff, je Quelle einer, neueste zuerst.

    Bevorzugt: belegte Langform ("Enterprise Resource Planning (ERP)"), Klammer-
    erklaerung, ganze Saetze (>= 8 Woerter). Ausgelassen: Metadaten-Zeilen
    ("title: ...") und Begriffe, die nur in Links/Dateinamen stehen; derselbe
    Satz aus Meeting-Notiz und Archivkopie zaehlt einmal.
    """
    flags = 0 if term.isupper() else re.IGNORECASE
    rx = re.compile(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", flags)
    paren = re.compile(re.escape(term) + r"\s*\([^)]{4,80}\)|\([^)]{0,10}" + re.escape(term)
                       + r"[^)]{0,10}\)", flags)
    scored = []
    for order, (stem, text) in enumerate(docs):
        best = None
        for para in _paragraphs(text):
            for sent in _SENT_SPLIT.split(para):
                s = " ".join(sent.split())
                m = rx.search(_LINK_RE.sub(" ", s))
                if not m or len(s) < 20 or _META_LINE_RE.match(s):
                    continue
                s = _window(s, rx.search(s).start())
                score = ((5 if expansion(term, s) else 0) + (3 if paren.search(s) else 0)
                         + (1 if len(s.split()) >= 8 else 0))
                if best is None or score > best[0]:
                    best = (score, s)
        if best:
            date_prefix = (_DATE_PREFIX_RE.match(stem) or [""])[0]
            scored.append((best[0], date_prefix, order, stem, best[1]))
    # Aussagekraft, dann neueste Quelle; bei gleichem Datum die Corpus-Reihenfolge
    # (aktive Meetings vor Archivkopien)
    scored.sort(key=lambda x: (-x[0], _neg(x[1]), x[2]))
    out, seen = [], set()
    for _, _, _, stem, s in scored:
        key = re.sub(r"\W+", "", s.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((stem, s))
        if len(out) >= limit:
            break
    return out


def _neg(date_prefix: str) -> str:
    """Sortierschluessel 'neuestes Datum zuerst' fuer aufsteigende Sortierung."""
    return "".join(chr(0x7F - ord(c)) for c in date_prefix) if date_prefix else "\x7f"


def display_form(term: str, docs: list[tuple[str, str]]) -> str:
    """Gebraeuchlichste Schreibweise im Text ("erp" -> "ERP"); der Begriff selbst,
    wenn er nicht (oder nicht eindeutig oefter als 1x) vorkommt. Kurze
    Einzelwoerter nehmen die belegte Grossschreibung: "rest" -> "REST", auch
    wenn das deutsche "Rest" haeufiger ist."""
    rx = re.compile(r"(?<![\w-])" + re.escape(term).replace(r"\ ", r"[ -]") + r"(?![\w-])",
                    re.IGNORECASE)
    counts: Counter = Counter()
    for _, text in docs:
        counts.update(m.group(0) for m in rx.finditer(_LINK_RE.sub(" ", text)))
    if not counts:
        return term
    upper = [(f, n) for f, n in counts.most_common() if f.isupper() and n >= 2]
    if upper and len(term) <= 6 and not re.search(r"[ -]", term):
        return upper[0][0]
    form, n = counts.most_common(1)[0]
    return form if n >= 2 else term


def acronym_candidates(docs: list[tuple[str, str]], known: set[str]) -> list[str]:
    ignore = STOPWORDS | vault_stopwords()
    files: dict[str, set[str]] = defaultdict(set)
    counts: Counter = Counter()
    for stem, text in docs:
        for m in _ACRONYM_RE.finditer(text):
            a = m.group(1)
            if a in ACRONYM_STOP or a.lower() in ignore or a.isdigit() or sum(c.isalpha() for c in a) < 2:
                continue
            counts[a] += 1
            files[a].add(stem)
    cands = [a for a, n in counts.items()
             if n >= MIN_COUNT and len(files[a]) >= MIN_FILES and vp.slugify(a) not in known]
    # Hervorhebung statt Abkuerzung: "NICHT", "ORDER" stehen sonst normal im Text
    if cands:
        rx = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, cands)) + r")(?![\w-])",
                        re.IGNORECASE)
        other: Counter = Counter()
        for _, text in docs:
            other.update(m.group(1).upper() for m in rx.finditer(text) if not m.group(1).isupper())
        cands = [a for a in cands if other[a] <= counts[a]]
    # Zwei Buchstaben sind mehrdeutig: ohne ausgeschriebene Langform im Text raet das Modell eine
    # Deutung, die nirgends belegt ist - mit ihr ("Change Request (CR)") nicht
    return sorted(a for a in cands if len(a) > 2 or any(expansion(a, sent) for _, sent in snippets(a, docs)))


def atlas_terms(k: dict | None) -> list[dict]:
    """Fachobjekte mit Definition aus dem Kanon (kanon.py) - Quelle der Wahrheit fuers Glossar."""
    if not k:
        return []
    contexts = {c.get("id"): c.get("name") or c.get("id") for c in k["kontexte"]}
    out = []
    for o in k["objekte"]:
        term = o.get("begriff")
        if not term or not o.get("definition"):
            continue
        out.append({"term": str(term), "slug": vp.slugify(term), "atlas_id": o.get("id"),
                    "definition": " ".join(str(o["definition"]).split()),
                    "context": contexts.get(o.get("kontext"), o.get("kontext") or ""),
                    "synonyms": [str(a) for a in o.get("synonyme") or []]})
    return out


KANON_START, KANON_ENDE = "<!-- kanon-auto:start -->", "<!-- kanon-auto:end -->"
_KANON_BLOCK_RE = re.compile(re.escape(KANON_START) + r".*?" + re.escape(KANON_ENDE) + r"\n?", re.S)
KANON_ART = {"subdomaenen": "subdomäne", "teams": "team", "kontexte": "kontext", "objekte": "fachbegriff"}


def kanon_begriffe(k: dict | None) -> list[dict]:
    """Der Kanon als Wortschatz: je Name ein Begriff mit allem, was der Kanon zu ihm fuehrt -
    Subdomaenen (Art, Reife, Kontexte, Teams), Teams (Kontexte), Kontexte (Subdomaene, Owner),
    Fachobjekte (Kontext) - und dem Thema dazu. Ohne den Platzhalter fuer offene Owner."""
    if not k:
        return []
    import aufgaben as tk
    import begriffsindex as bi
    R = k["regeln"]
    offen = str(R.get("owner_offen") or "")
    themen = bi.kanon_themen(k)
    names = tk.Names()
    kontexte = {c.get("id"): c for c in k["kontexte"]}
    teams = {t.get("id"): t for t in k["teams"]}
    subs = {s.get("id"): s for s in k["subdomaenen"]}

    def name(eid, tab) -> str:
        return str((tab.get(eid) or {}).get("name") or eid)

    def thema(eid) -> str:
        s = themen.get(eid)
        return f" · Thema: [[{s}|{names.topic(s) or s}]]" if s else ""

    gruppen: dict[str, dict] = {}

    def add(term, eid, art, zeile, beschreibung=""):
        slug = vp.slugify(str(term or ""))
        if not slug or not eid or eid == offen:
            return
        g = gruppen.setdefault(slug, {"slug": slug, "term": str(term), "art": art, "ids": [], "zeilen": [],
                                      "beschreibung": "", "eigenes_thema": False})
        # Eine Subdomaene mit Thema hat ihre Seite schon (auch unter anderem Namen, ueber atlas_id)
        g["eigenes_thema"] = g["eigenes_thema"] or (art == KANON_ART["subdomaenen"] and bool(themen.get(eid)))
        g["ids"].append(str(eid))
        g["zeilen"].append(zeile)
        g["beschreibung"] = g["beschreibung"] or " ".join(str(beschreibung or "").split())

    for s in k["subdomaenen"]:
        kx = [c for c in k["kontexte"] if c.get("subdomain") == s.get("id")]
        owner = sorted({name(o, teams) for c in kx for o in c.get("owner") or [] if o != offen})
        art = ", ".join(x for x in (s.get("art"), s.get("reife")) if x)
        add(s.get("name"), s.get("id"), KANON_ART["subdomaenen"],
            f"**Subdomäne** `{s.get('id')}`" + (f" ({art})" if art else "")
            + (f" · Kontexte: {', '.join(sorted(c.get('name') or c.get('id') for c in kx))}" if kx else "")
            + (f" · Teams: {', '.join(owner)}" if owner else "") + thema(s.get("id")), s.get("beschreibung"))
    for t in k["teams"]:
        kx = [c for c in k["kontexte"] if t.get("id") in (c.get("owner") or [])]
        sd = sorted({name(c.get("subdomain"), subs) for c in kx if c.get("subdomain")})
        add(t.get("name"), t.get("id"), KANON_ART["teams"],
            f"**Team** `{t.get('id')}`"
            + (f" · zuständig für: {', '.join(sorted(c.get('name') or c.get('id') for c in kx))}" if kx else "")
            + (f" (Subdomäne {', '.join(sd)})" if sd else "") + thema(t.get("id")), t.get("beschreibung"))
    for c in k["kontexte"]:
        owner = [name(o, teams) for o in c.get("owner") or [] if o != offen]
        add(c.get("name"), c.get("id"), KANON_ART["kontexte"],
            f"**Kontext** `{c.get('id')}`"
            + (f" in der Subdomäne {name(c.get('subdomain'), subs)}" if c.get("subdomain") else "")
            + (f" · Owner: {', '.join(owner)}" if owner else "") + thema(c.get("id")), c.get("beschreibung"))
    for o in k["objekte"]:
        syn = [str(x) for x in o.get("synonyme") or [] if x]
        add(o.get("begriff") or o.get("name"), o.get("id"), KANON_ART["objekte"],
            f"**Fachobjekt** `{o.get('id')}`"
            + (f" im Kontext {name(o.get('kontext'), kontexte)}" if o.get("kontext") else "")
            + (f" · Synonyme: {', '.join(syn)}" if syn else "") + thema(o.get("id")))
    return list(gruppen.values())


def _kanon_block(g: dict, titel: str) -> str:
    block = "\n".join([KANON_START, f"> [!abstract] Im {titel}", *(f"> {z}" for z in g["zeilen"]), KANON_ENDE])
    return schreibweisen.vereinheitlichen(block)[0]      # Namen wie im Vault, auch wenn der Kanon sie anders schreibt


def _mit_kanon_block(text: str, block: str) -> str:
    """Block ersetzen - oder direkt unter die H1 setzen (ohne H1: an den Anfang). Das
    Frontmatter bleibt Zeichen fuer Zeichen, wie es ist."""
    if _KANON_BLOCK_RE.search(text):
        return _KANON_BLOCK_RE.sub(lambda _: block + "\n", text, count=1)
    m_fm = re.match(r"^---\n.*?\n---\n", text, re.S)
    head, body = (text[:m_fm.end()], text[m_fm.end():]) if m_fm else ("", text)
    m = re.search(r"^# .*\n", body, re.M)
    at = m.end() if m else 0
    return head + body[:at] + "\n" + block + "\n\n" + body[at:].lstrip("\n")


def kanon_eintrag(g: dict, k: dict, *, known: dict[str, Path], andere: set[str], dry_run: bool) -> str:
    """Glossar-Seite eines Kanon-Begriffs anlegen oder ihren Kanon-Block auffrischen.
    'created' | 'updated' | 'unchanged' | 'entity' (der Begriff hat schon eine eigene Seite:
    Thema, Person, System ...)."""
    path = known.get(g["slug"])
    if path is None and (g["slug"] in andere or g.get("eigenes_thema")):
        return "entity"
    block = _kanon_block(g, k["regeln"]["name"])
    definition = (_definition_block(g["beschreibung"], f"{k['regeln']['name']} `{g['ids'][0]}`", [], review=False)
                  if g["beschreibung"] else None)
    if path is None:
        if not dry_run:
            write_entry(g["slug"], term=g["term"], dry_run=False, definition_md=definition,
                        fm_updates={"status": "atlas", "art": g["art"], "quelle": k["format"],
                                    "atlas_id": g["ids"][0]})
            p = GLOSSARY_DIR / f"{g['slug']}.md"
            p.write_text(_mit_kanon_block(p.read_text(encoding="utf-8"), block), encoding="utf-8", newline="\n")
        return "created"
    text = path.read_text(encoding="utf-8")
    neu = _mit_kanon_block(text, block)
    fm = vp.read_frontmatter(path)
    updates = {} if fm.get("atlas_id") else {"atlas_id": g["ids"][0]}
    if neu == text and not updates:
        return "unchanged"
    if not dry_run:
        if neu != text:
            path.write_text(neu, encoding="utf-8", newline="\n")
        if updates:
            vp.update_frontmatter(path, updates)
    return "updated"


def kanon_seiten() -> dict[str, Path]:
    """Glossar-Seiten nach Dateiname und Begriff (nicht nach Synonymen - ein Synonym ist kein
    eigener Begriff, sonst schrieben zwei Kanon-Begriffe in dieselbe Seite)."""
    out: dict[str, Path] = {}
    for f in sorted(GLOSSARY_DIR.glob("*.md")) if GLOSSARY_DIR.is_dir() else []:
        out[f.stem] = f
        term = vp.read_frontmatter(f).get("term")
        if term:
            out.setdefault(vp.slugify(str(term)), f)
    return out


def andere_seiten() -> set[str]:
    """Slugs, die keine eigene Kanon-Seite bekommen: Nicht-Glossar-Seiten (Themen, Personen,
    Systeme ...), ihre Aliasse und die Synonyme im Glossar."""
    out = {f.stem for c, d in vp.CATEGORY_DIRS.items() if c != "glossary" and d.is_dir() for f in d.glob("*.md")}
    out |= {vp.slugify(a) for a in vp.alias_map()}
    for f in sorted(GLOSSARY_DIR.glob("*.md")) if GLOSSARY_DIR.is_dir() else []:
        out |= {vp.slugify(str(s)) for s in vp.read_frontmatter(f).get("synonyms") or [] if s}
    return out


def propose_definitions(terms: list[str], docs, llm_call, system_prompt: str | None = None) -> dict[str, dict]:
    """{begriff: {art, langform, definition, fundstellen}} - nur belegte Vorschlaege."""
    out: dict[str, dict] = {}
    for start in range(0, len(terms), BATCH):
        chunk = terms[start:start + BATCH]
        found = {t: snippets(t, docs) for t in chunk}
        # belegte Langform deterministisch (Code findet, Modell formuliert)
        expanded = {t: next((e for _, s in found[t] if (e := expansion(t, s))), "") for t in chunk}
        blocks = []
        for t in chunk:
            lines = "\n".join(f"  - {s}" for _, s in found[t]) or "  (keine Fundstelle)"
            hint = f"\nLangform (belegt): {expanded[t]}" if expanded[t] else ""
            blocks.append(f"Begriff: {t}{hint}\nFundstellen:\n{lines}")
        try:
            res, _ = llm_call([{"role": "system", "content": system_prompt or SYSTEM_PROMPT},
                               {"role": "user", "content": "\n\n".join(blocks)}],
                              SCHEMA, max_tokens=1500, task="glossary")
        except Exception as e:
            print(f"[WARN] Glossar-Modellaufruf fehlgeschlagen: {type(e).__name__}: {e}",
                  file=sys.stderr)
            continue
        by_lower = {t.lower(): t for t in chunk}
        for b in (res or {}).get("begriffe") or []:
            t = by_lower.get(str(b.get("begriff") or "").strip().lower())
            if t is None or b.get("art") not in ARTEN:
                continue
            text = " ".join(s for _, s in found[t]).lower()
            langform = " ".join(str(b.get("langform") or "").split())
            if langform and (langform.lower() not in text or langform.lower() == t.lower()):
                langform = ""          # nicht belegt (oder nur der Begriff selbst) -> verworfen
            definition = " ".join(str(b.get("definition") or "").split())[:400]
            definition = schreibweisen.vereinheitlichen(definition)[0]      # Namen wie auf ihren Seiten
            out[t] = {"art": b["art"], "langform": langform or expanded[t],
                      "definition": definition if found[t] else "",
                      "fundstellen": [stem for stem, _ in found[t]]}
    return out


def _definition_block(text: str, source: str, fundstellen: list[str], review: bool = True) -> str:
    """Definition als Callout; `review` nur fuer Modell-Vorschlaege (der Kanon
    ist Quelle der Wahrheit und braucht kein "bitte pruefen")."""
    links = ", ".join(f"[[{s}]]" for s in fundstellen)
    return (f"> [!note] {source}{' – bitte prüfen' if review else ''}\n> {text}"
            + (f"\n>\n> Fundstellen: {links}" if links else ""))


def write_entry(slug: str, *, term: str, fm_updates: dict, definition_md: str | None,
                dry_run: bool) -> str:
    """'created' | 'updated' | 'unchanged'. Vorhandene Definitionen bleiben."""
    path = vp.GLOSSARY_DIR / f"{slug}.md"
    if not path.exists():
        term = schreibweisen.vereinheitlichen(term)[0]        # neuer Begriff: Namen wie auf ihren Seiten
        fm = {"type": "glossary_term", "term": term, "slug": slug, **fm_updates,
              "tags": ["glossary", "ddd"]}
        body = f"\n# {term}\n\n{DEF_HEADING}\n\n{definition_md or ''}\n"
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(vp.dump_frontmatter(fm, body), encoding="utf-8", newline="\n")
        return "created"
    text = path.read_text(encoding="utf-8")
    new_text = text
    current = ms.section_body(text, DEF_HEADING)
    if definition_md and _PLACEHOLDER_RE.match(current or ""):
        new_text = ms.replace_section(text, DEF_HEADING, definition_md)
    fm, _ = vp.split_frontmatter(new_text)
    fm_changed = any(fm.get(k) != v for k, v in fm_updates.items() if v not in (None, "", []))
    if new_text == text and not fm_changed:
        return "unchanged"
    if not dry_run:
        if new_text != text:
            path.write_text(new_text, encoding="utf-8", newline="\n")
        vp.update_frontmatter(path, fm_updates)
    return "updated"


def _set_term(path: Path, old: str, new: str) -> None:
    """Schreibweise in `term:` und in der generierten H1 ("# erp") anpassen."""
    text = path.read_text(encoding="utf-8")
    fm, body = vp.split_frontmatter(text)
    fm["term"] = new
    body = re.sub(rf"^# {re.escape(old)}[ \t]*$", f"# {new}", body, count=1, flags=re.M)
    path.write_text(vp.dump_frontmatter(fm, body), encoding="utf-8", newline="\n")


# ------------------------------------------------------------------ Ablauf

def _load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True),
                          encoding="utf-8", newline="\n")


def run(*, apply: bool, llm_call=None, limit: int = 200, min_count: int = DEFAULT_MIN_COUNT) -> dict:
    """Zaehlen -> Kanon -> Bestand -> Modell (siehe Modulkopf). Ohne `apply` ein Bericht."""
    import kanon
    report = Counter()
    today = date.today().isoformat()
    # 1. Zaehlen
    index = scan()
    if apply:
        save_index(index)
    report["index_begriffe"] = len(index["terms"])
    kept, reasons = filter_candidates(index["terms"], min_count)
    for key, n in reasons.items():
        report[f"verworfen_{key}"] = n
    # 2. Kanon - Quelle der Wahrheit
    docs = corpus()
    k = kanon.lade()
    for a in atlas_terms(k):
        r = write_entry(a["slug"], term=a["term"], dry_run=not apply,
                        fm_updates={"status": "atlas", "quelle": k["format"],
                                    "atlas_id": a["atlas_id"], "bounded_context": a["context"],
                                    "synonyms": a["synonyms"]},
                        definition_md=_definition_block(a["definition"],
                                                        f"{k['regeln']['name']} `{a['atlas_id']}`", [],
                                                        review=False))
        report[f"atlas_{r}"] += 1
    # 2b. Kanon als Wortschatz: Subdomaenen, Teams, Kontexte und Fachobjekte ohne eigene Seite werden
    # Begriffe (Seite `status: atlas`); vorhandene Seiten bekommen den Kanon-Block dazu
    seiten, andere = kanon_seiten(), andere_seiten()
    for g in kanon_begriffe(k):
        report[f"kanon_{kanon_eintrag(g, k, known=seiten, andere=andere, dry_run=not apply)}"] += 1
    # 3. Bestand: Messwerte und Schreibweise. Messwerte fuer jede vorhandene Seite, deren Begriff
    # gezaehlt wurde - auch unter der Mindestzahl, sonst behielte sie alte Zahlen.
    known = existing_terms()
    gezaehlt: dict[str, dict] = {}
    for term, meta in index["terms"].items():
        slug = vp.slugify(term)
        if slug in known and int(meta.get("count", 0)) > int(gezaehlt.get(slug, {}).get("count", -1)):
            gezaehlt[slug] = meta
    for slug, meta in sorted(gezaehlt.items()):
        report[f"messwerte_{update_term(known[slug], meta, dry_run=not apply)}"] += 1
    existing = {p.stem: vp.read_frontmatter(p) for p in GLOSSARY_DIR.glob("*.md")} \
        if GLOSSARY_DIR.is_dir() else {}
    for slug, fm in existing.items():
        term = str(fm.get("term") or "")
        if term and term == term.lower() and fm.get("status") != "atlas":
            form = display_form(term, docs)
            if form != term:
                if apply:
                    _set_term(GLOSSARY_DIR / f"{slug}.md", term, form)
                fm["term"] = form
                report["schreibweise"] += 1
    # 4. Modell: neue Begriffe, neue Abkuerzungen, Seiten ohne Definition
    state = _load_state()
    neu = [(t, vp.slugify(t), int(m.get("count", 0)), m) for t, m in
           sorted(kept.items(), key=lambda x: -int(x[1].get("count", 0))) if vp.slugify(t) not in known]
    abk = [(a, vp.slugify(a), 0, None) for a in acronym_candidates(docs, set(existing))]
    ohne = []
    for slug, fm in existing.items():
        body = ms.section_body((GLOSSARY_DIR / f"{slug}.md").read_text(encoding="utf-8"), DEF_HEADING)
        if fm.get("status") != "atlas" and _PLACEHOLDER_RE.match(body or ""):
            ohne.append((str(fm.get("term") or slug), slug, int(fm.get("occurrences") or 0), None))
    report["neue_begriffe"], report["neue_abkuerzungen"], report["ohne_definition"] = len(neu), len(abk), len(ohne)
    todo, gesehen = [], set()
    for term, slug, occ, meta in neu + abk + ohne:
        s = state.get(slug)
        if slug in gesehen or (s is not None and s.get("occ") == occ):
            continue                                   # schon eingeordnet, Fundstellen unveraendert
        gesehen.add(slug)
        todo.append((term, slug, occ, meta))
    report["wartet_auf_modell"] = len(todo)
    todo = todo[:limit]
    prompt = SYSTEM_PROMPT if configured_examples() else build_prompt(derived_examples(docs))
    proposals = propose_definitions([t for t, *_ in todo], docs, llm_call, prompt) if llm_call and todo else {}
    for term, slug, occ, meta in todo:
        p = proposals.get(term)
        if p is None:
            report["ohne_vorschlag"] += 1
            continue
        report[f"art_{p['art']}"] += 1
        state[slug] = {"art": p["art"], "occ": occ, "am": today}
        is_new = slug not in existing
        if is_new and p["art"] not in RELEVANT:
            report["nicht_angelegt"] += 1             # allgemeine IT-Woerter, Rauschen, Unklares
            continue
        md = None
        if p["definition"] or p["langform"]:
            text = ": ".join(x for x in (p["langform"], p["definition"]) if x)
            md = _definition_block(text, f"Vorschlag lokales Modell ({today})", p["fundstellen"])
        fm_updates = {"art": p["art"], "langform": p["langform"] or None}
        if is_new:
            fm_updates.update({"status": "candidate", "bounded_context": "", "synonyms": [],
                               "related_terms": [], **(managed_fields(meta) if meta else {})})
        r = write_entry(slug, term=display_form(term, docs) if is_new else term, dry_run=not apply,
                        definition_md=md, fm_updates=fm_updates)
        report[f"vorschlag_{r}"] += 1
    if apply and proposals:
        _save_state(state)
    report["verweist_auf_entity"] = len(find_shadowed_terms())
    return dict(report)


def main(argv: list[str] | None = None) -> int:
    vp.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="Glossar: zaehlen, Kanon, Bestand, Vorschlaege des Modells")
    ap.add_argument("--apply", action="store_true", help="schreiben (sonst nur Bericht)")
    ap.add_argument("--no-llm", action="store_true", help="ohne Modell (Zaehlen, Kanon, Bestand)")
    ap.add_argument("--limit", type=int, default=200, help="hoechstens so viele Begriffe ans Modell")
    ap.add_argument("--min-count", type=int, default=DEFAULT_MIN_COUNT)
    args = ap.parse_args(argv)
    llm_call = None
    if not args.no_llm:
        import modell
        ok, reason = modell.available()
        llm_call = modell.complete_json if ok else None
        if not ok:
            print(f"[WARN] Modell nicht erreichbar ({reason}) - ohne Vorschlaege", file=sys.stderr)
    r = run(apply=args.apply, llm_call=llm_call, limit=args.limit, min_count=args.min_count)
    print(("Glossar geschrieben" if args.apply else "Glossar-Bericht [schreibt nichts - --apply]") + ":")
    for key, v in sorted(r.items()):
        print(f"  {key:24} {v}")
    shadowed = find_shadowed_terms()
    if shadowed:
        print(f"\n{len(shadowed)} Glossar-Eintrag/Eintraege verweisen inzwischen auf eine echte Entity - "
              "im Eintrag auf die Entity verweisen oder ihn entfernen:")
        for f, slug in shadowed:
            print(f"  {f.stem:28} -> {slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
