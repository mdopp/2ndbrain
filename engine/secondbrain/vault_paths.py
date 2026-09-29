#!/usr/bin/env python3
"""vault_paths.py - Single Source of Truth fuer Vault-Pfade, Slugs und Frontmatter.

Alle Werkzeuge holen Pfade und Konventionen von hier, statt sie selbst zu bauen - so
arbeiten sie unabhaengig vom aktuellen Ordner auf demselben Vault (Themen etwa liegen
in `entities/projects/<slug>.md`).

Dieses Modul kapselt:
  - Vault-Root-Aufloesung (unabhaengig vom CWD)
  - die kanonischen Verzeichnisse und die Einstellungen des Vaults (local.config.json)
  - Frontmatter lesen/schreiben mit **Upsert** (fehlende Keys werden eingefuegt,
    nicht stillschweigend ignoriert wie bei `re.sub` auf einem nicht vorhandenen Key)
  - `known_slugs()` als Whitelist fuer die LLM-Validierung (siehe ausgabe_pruefen.py)

Beim Import legt es hoechstens `.2ndbrain/daten/` an, und nur in einem gefundenen Vault.
"""
from __future__ import annotations

import json as _json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import yaml


def ensure_utf8_stdio() -> None:
    """stdout/stderr auf UTF-8 stellen (Windows).

    Die Werkzeuge geben Pfeile, Umlaute und JSON mit `ensure_ascii=False` aus.
    Unter Windows ist eine Pipe standardmaessig cp1252 - jede Ausgabe mit '→'
    bricht dort sonst mit UnicodeEncodeError ab (Exit 1, Arbeitspaket verloren).
    Auf macOS/Linux ist das ein No-op. Jedes Werkzeug importiert dieses Modul
    zuerst, deshalb passiert es genau hier.
    """
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


ensure_utf8_stdio()

ENTITY_CATEGORIES = ("people", "teams", "companies", "systems", "projects",
                     "forums", "contexts", "glossary")


def slugify(text: str) -> str:
    """Name -> Slug: klein, Umlaute ausgeschrieben, alles andere zu Bindestrichen
    ("Qualitätssicherung (QS)" -> "qualitaetssicherung-qs"). Die eine Regel fuer alle Seiten."""
    t = str(text or "").strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def note_themen(fm: dict) -> list[str]:
    """Themen einer Termin-Notiz (Frontmatter `themen:`) als Slugs, ohne Dubletten;
    `[[slug|Name]]` wird zu `slug`. Das erste ist das Hauptthema."""
    th = fm.get("themen") or []
    if isinstance(th, str):
        th = [th]
    out = []
    for x in th:
        s = str(x or "").strip()
        m = re.match(r"^\[\[([^\]|#]+)", s)
        s = (m.group(1) if m else s).strip()
        if s and s not in out:
            out.append(s)
    return out


def note_date(fm: dict, path: Path | None = None) -> str:
    """Tag einer Termin-Notiz (JJJJ-MM-TT): `date`, bei aelteren Notizen `timestamp`, sonst der
    Anfang des Dateinamens; "" wenn nichts davon."""
    for v in (fm.get("date"), fm.get("timestamp")):
        if v:
            return str(v)[:10]
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", path.name) if path is not None else None
    return m.group(1) if m else ""


def find_vault_root(start: Path | str | None = None) -> Path | None:
    """Vault-Root: $VAULT_DIR (so startet das Plugin die Engine, so steht es im MCP-Befehl) >
    Aufwaertssuche ab dem aktuellen Ordner nach `.2ndbrain/` oder `.obsidian/`. None = keiner.
    Der Code liegt nicht im Vault - sein eigener Ort sagt nichts ueber den Vault."""
    env = os.environ.get("VAULT_DIR")
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_dir():
            return p
    base = Path(start).resolve() if start else Path.cwd().resolve()
    for cand in (base, *base.parents):
        if (cand / ".2ndbrain").is_dir() or (cand / ".obsidian").is_dir():
            return cand
    return None


_root = find_vault_root()
VAULT_FOUND = _root is not None
# Ohne Vault bleibt der Import moeglich (Hilfe, Version, Tests setzen VAULT_DIR danach);
# befehle.py bricht dann mit einer klaren Meldung ab, bevor irgendetwas geschrieben wird.
VAULT = _root or Path.cwd().resolve()

ENTITIES_DIR = VAULT / "entities"
PROJECTS_DIR = ENTITIES_DIR / "projects"
PEOPLE_DIR = ENTITIES_DIR / "people"
TEAMS_DIR = ENTITIES_DIR / "teams"
COMPANIES_DIR = ENTITIES_DIR / "companies"
SYSTEMS_DIR = ENTITIES_DIR / "systems"
GLOSSARY_DIR = ENTITIES_DIR / "glossary"
# Archiv verarbeiteter Quellen (Meetings, Mails, Dokumente). Sichtbarer Ordner - einen
# Punkt-Ordner indiziert Obsidian nicht, Quellen-Links im Event Log waeren tot.
SOURCES_DIR = VAULT / "archive"
# Eingang: neue Dateien gehoeren nach `inbox/`. Der Root wird mitgelesen (.eml,
# Dokumente, ZIPs), taugt aber nicht als Ablage: dort liegen die Cockpit-Dateien 01_-07_.
INBOX_DIR = VAULT / "inbox"
MEETINGS_DIR = SOURCES_DIR / "meetings"
ENGINE_DIR = Path(__file__).resolve().parent   # Code der Engine (das Paket), nicht im Vault
VORLAGE_DIR = ENGINE_DIR / "vorlage"            # was ein neuer Vault braucht (einrichten legt an, was fehlt)


def _pruefe_start() -> None:
    """Ein Werkzeug direkt gestartet (`python -m secondbrain.glossar`), aber kein Vault: abbrechen,
    bevor etwas im aktuellen Ordner landet. befehle.py und __main__ melden das selbst (Hilfe und
    Version gehen ohne Vault); Tests setzen VAULT_DIR."""
    if VAULT_FOUND or not sys.argv or not sys.argv[0]:
        return
    try:
        start = Path(sys.argv[0]).resolve()
    except (OSError, ValueError):
        return
    if start.parent == ENGINE_DIR and start.name not in ("befehle.py", "__main__.py"):
        sys.exit("[ABBRUCH] Kein Vault gefunden - im Vault-Ordner starten oder VAULT_DIR=<Vault> setzen.")


_pruefe_start()
# Konfiguration und Daten DIESES Vaults - getrennt vom Code
DATA_ROOT = VAULT / ".2ndbrain"              # local.config.json, llm.config.json, chat-skills/
DATA_DIR = DATA_ROOT / "daten"               # Zustaende, Caches, Protokolle
ENTITY_DISK_CACHE = DATA_DIR / ".entity_cache.json"
TEMPLATES_DIR = VAULT / ".templates"

CONTEXTS_DIR = ENTITIES_DIR / "contexts"
# Gremien und wiederkehrende Formate: Boards, Weeklies, Jour Fixes, Checkins.
# Zweite Achse neben dem Thema - "wo wird berichtet" statt "was wird getan".
FORUMS_DIR = ENTITIES_DIR / "forums"

# ------------------------------------------------------------ externe Quellen
# Domain Atlas und LikeC4-Modell liegen ausserhalb des Vaults, je Rechner an
# anderer Stelle (Mac: ~/code/domain-atlas, Windows: C:\Users\<u>\domain-atlas) -
# deshalb kein fester Pfad im Code, sondern external_path().
LOCAL_CONFIG_FILE = DATA_ROOT / "local.config.json"

# Datenordner anlegen - nur in einem gefundenen Vault; sonst entstuende .2ndbrain/ im aktuellen Ordner
if VAULT_FOUND:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

EXTERNAL_SOURCES = {
    # Name: (Umgebungsvariable, Verzeichnisnamen fuer die Auto-Erkennung)
    "domain_atlas": ("VAULT_DOMAIN_ATLAS", ("domain-atlas",)),
    "likec4_model": ("VAULT_LIKEC4_MODEL", ("likec4-model",)),
}


def local_config() -> dict:
    """Einstellungen dieses Vaults aus `.2ndbrain/local.config.json`
    (nicht versioniert; Vorlage: `local.config.example.json`)."""
    try:
        data = _json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def ich() -> str:
    """Eigener Personen-Slug (`"ich"` in local.config.json) - die eine Quelle fuer
    "wer bin ich" (eigene Aufgaben, Nachfassen, Beschriftungen)."""
    return str(local_config().get("ich") or "").strip()


def ich_seite() -> dict:
    """Frontmatter der eigenen Personen-Seite ({} ohne `ich` oder ohne Seite)."""
    slug = ich()
    return (read_frontmatter(PEOPLE_DIR / f"{slug}.md") or {}) if slug else {}


def ich_vorname() -> str:
    name = str(ich_seite().get("name") or "").strip()
    return name.split()[0] if name else ""


def interne_domains() -> set[str]:
    """Mail-Domain(s) der eigenen Organisation: `interne_domains` in local.config.json,
    sonst die Domain der eigenen Adresse (`email:` auf der eigenen Personen-Seite).
    Leer = unbekannt - dann gilt niemand als intern (nichts wird still angelegt)."""
    cfg = local_config().get("interne_domains")
    if isinstance(cfg, list) and cfg:
        return {str(x).strip().lower().lstrip("@") for x in cfg if str(x).strip()}
    mail = str(ich_seite().get("email") or "").strip().lower()
    return {mail.split("@", 1)[1]} if "@" in mail else set()


def organisation() -> str:
    """Name der eigenen Organisation: `organisation` in local.config.json, sonst `company:`
    auf der eigenen Personen-Seite (leer = unbekannt)."""
    return str(local_config().get("organisation") or ich_seite().get("company") or "").strip()


def vault_beschreibung() -> str:
    """Wofuer der Vault da ist, fuer Prompts und die MCP-Beschreibung (`beschreibung`)."""
    return str(local_config().get("beschreibung") or "").strip()


def genitiv(name: str) -> str:
    """"Anna" -> "Annas", "Max" -> "Max'"."""
    return f"{name}'" if name[-1:].lower() in ("s", "ß", "x", "z") else f"{name}s"


def external_path(name: str) -> Path | None:
    """Pfad einer externen Quelle.

    Reihenfolge: Umgebungsvariable > `local.config.json` (`paths.<name>`) >
    Auto-Erkennung neben dem Vault (so packt das Umzugs-Paket aus), unter
    `~/code/<dir>` und `~/<dir>`. Ein ausdruecklich konfigurierter Pfad wird
    auch zurueckgegeben, wenn er fehlt - dann kann der Aufrufer ihn in der
    Warnung nennen. None = nichts gefunden.
    """
    env_var, _dirs = EXTERNAL_SOURCES[name]
    configured = os.environ.get(env_var) or (local_config().get("paths") or {}).get(name)
    if configured:
        return Path(configured).expanduser()
    return detect_path(name)


def detect_path(name: str) -> Path | None:
    """Nur die Auto-Erkennung: neben dem Vault, `~/code/<dir>`, `~/<dir>`."""
    _env, dir_names = EXTERNAL_SOURCES[name]
    home = Path.home()
    for base in (VAULT.parent, home / "code", home):
        for dn in dir_names:
            if (base / dn).is_dir():
                return base / dn
    return None


CATEGORY_DIRS = {
    "people": PEOPLE_DIR,
    "teams": TEAMS_DIR,
    "companies": COMPANIES_DIR,
    "systems": SYSTEMS_DIR,
    "projects": PROJECTS_DIR,
    "forums": FORUMS_DIR,
    "contexts": CONTEXTS_DIR,
    "glossary": GLOSSARY_DIR,
}

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---[ \t]*\n?", re.DOTALL)

# Entity-Whitelists/-Aliasse sind teuer (ein Read pro Entity-Datei)
# und werden pro Verarbeitungsschritt mehrfach gebraucht. Der Prozess-Cache ist
# gefahrlos, solange jeder Schreiber (uebernehmen, anlegen ...) invalidate_entity_caches() ruft
# (der Datei-Cache .entity_cache.json gilt nur, solange `_dir_signature` gleich bleibt).
_ENTITY_CACHE: dict = {"alias_map": None, "known_slugs": None, "epoch": 0}


def _dir_signature() -> dict:
    """Je Entity-Verzeichnis: seine mtime (Anlegen/Loeschen/Umbenennen) und die
    juengste Datei-mtime. Die Verzeichnis-mtime allein reicht nicht: Aliasse, die
    man in Obsidian an einer bestehenden Notiz aendert, aendern sie nicht - der
    Cache bliebe alt."""
    sig = {}
    for cat, d in CATEGORY_DIRS.items():
        try:
            newest = max((f.stat().st_mtime for f in d.glob("*.md")), default=0.0)
            sig[cat] = [d.stat().st_mtime, newest]
        except OSError:
            sig[cat] = 0
    return sig


def _read_many(paths, workers: int = 16):
    """Latenz-gebundene Reads parallelisieren (langsame Dateisysteme wie DrvFS: ~40ms pro Open)."""
    def one(p):
        try:
            return p, p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return p, None
    if len(paths) <= 2:
        return [one(p) for p in paths]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, paths))


def invalidate_entity_caches() -> None:
    _ENTITY_CACHE["alias_map"] = None
    _ENTITY_CACHE["known_slugs"] = None
    _ENTITY_CACHE["epoch"] += 1
    try:
        if ENTITY_DISK_CACHE.exists():
            ENTITY_DISK_CACHE.unlink()
    except OSError:
        pass


def _load_disk_cache() -> bool:
    try:
        data = _json.loads(ENTITY_DISK_CACHE.read_text(encoding="utf-8"))
        if data.get("sig") != _dir_signature():
            return False
        _ENTITY_CACHE["alias_map"] = data["alias_map"]
        _ENTITY_CACHE["known_slugs"] = data["known_slugs"]
        return True
    except (OSError, ValueError, KeyError):
        return False


def _save_disk_cache() -> None:
    if _ENTITY_CACHE["alias_map"] is None or _ENTITY_CACHE["known_slugs"] is None:
        return
    try:
        ENTITY_DISK_CACHE.write_text(_json.dumps({
            "sig": _dir_signature(),
            "alias_map": _ENTITY_CACHE["alias_map"],
            "known_slugs": _ENTITY_CACHE["known_slugs"],
        }, ensure_ascii=False), encoding="utf-8", newline="\n")
    except OSError:
        pass


def cache_epoch() -> int:
    return _ENTITY_CACHE["epoch"]


def ensure_dirs() -> None:
    for d in CATEGORY_DIRS.values():
        d.mkdir(parents=True, exist_ok=True)
    MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
    INBOX_DIR.mkdir(parents=True, exist_ok=True)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """(frontmatter_dict, body) - tolerant bei fehlendem/kaputtem Frontmatter."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, text[m.end():]


def read_frontmatter(path: Path | str) -> dict:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    return split_frontmatter(text)[0]


def read_frontmatter_head(path: Path | str, max_bytes: int = 8192) -> dict:
    """Frontmatter lesen, ohne die ganze Datei zu laden.

    Auf langsamen Dateisystemen (DrvFS, /mnt/c) kostet jeder volle Read einer grossen
    Notiz Millisekunden; fuer den Laufplan des Eingangs (arbeitspaket.py) braucht es nur
    den Kopf. Faellt auf den vollen Read zurueck, wenn das schliessende `---` nicht im
    Kopf liegt.
    """
    p = Path(path)
    try:
        with open(p, "rb") as fh:
            head = fh.read(max_bytes)
    except OSError:
        return {}
    text = head.decode("utf-8", errors="replace")
    m = _FM_RE.match(text)
    if m:
        return split_frontmatter(text)[0]
    if len(head) < max_bytes or not text.startswith("---"):
        return {}
    return read_frontmatter(p)


# ------------------------------------------------ leeres Frontmatter
# Regel: ein leeres Feld wird nicht geschrieben. Leere Felder (`atlas_id: ''`,
# `company: "[[]]"`, `aliases: []`) sind Rauschen ohne Information; eine
# Eigenschaft laesst sich jederzeit anlegen.

_EMPTY_STRINGS = {"", "[[]]", "null", "~"}
_EMPTY_LINE_RE = re.compile(      # optional mit YAML-Kommentar dahinter
    r"^[A-Za-z_][\w-]*:\s*(?:\"\"|''|\[\]|\{\}|null|~|\"\[\[\]\]\"|'\[\[\]\]')?\s*(?:#.*)?$")


def is_empty_value(value) -> bool:
    """None, "", nur Leerzeichen, [], {}, leerer Link "[[]]"."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in _EMPTY_STRINGS
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def strip_empty(fm: dict) -> dict:
    return {k: v for k, v in fm.items() if not is_empty_value(v)}


def strip_empty_frontmatter(text: str) -> str:
    """Leere Felder zeilenweise aus dem Frontmatter entfernen - alle anderen
    Zeilen bleiben byte-gleich (kein YAML-Neuschreiben). `key:` ohne Wert gilt
    nur als leer, wenn keine eingerueckte Folgezeile (Liste/Map) kommt."""
    m = _FM_RE.match(text)
    if not m:
        return text
    lines = m.group(1).split("\n")
    kept = []
    for i, line in enumerate(lines):
        if _EMPTY_LINE_RE.match(line):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if line.rstrip().endswith(":") and nxt.startswith((" ", "\t", "-")):
                kept.append(line)
            continue
        kept.append(line)
    if len(kept) == len(lines):
        return text
    return "---\n" + "\n".join(kept) + "\n---\n" + text[m.end():]


def dump_frontmatter(fm: dict, body: str) -> str:
    fm = strip_empty(fm)
    if not fm:
        return body
    y = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{y}---\n{body}"


def update_frontmatter(path: Path | str, updates: dict, remove: tuple = ()) -> bool:
    """Frontmatter-Keys upserten (und gezielt entfernen). True = Datei geaendert.

    Anders als `re.sub(rf"^{key}:.*$", ...)` (stiller No-op bei fehlendem Key)
    werden fehlende Keys angelegt. `remove` loescht Keys (z.B. `processed_at`
    beim Zuruecksetzen in eingang_abschluss.py) - fehlende Keys sind kein Fehler.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    changed = False
    for k, v in updates.items():
        if is_empty_value(v):          # leerer Wert = Feld entfernen (Regel oben)
            if k in fm:
                del fm[k]
                changed = True
        elif fm.get(k) != v:
            fm[k] = v
            changed = True
    for k in remove:
        if k in fm:
            del fm[k]
            changed = True
    # Beim Neuschreiben gleich vorhandene Leerfelder mit entfernen.
    if any(is_empty_value(v) for v in fm.values()):
        fm = strip_empty(fm)
        changed = True
    if not changed:
        return False
    p.write_text(dump_frontmatter(fm, body), encoding="utf-8", newline="\n")
    return True


# Frontmatter-Keys, die fehlerhafte Editier-Laeufe als nackte Zeilen NACH dem
# schliessenden `---` in den Body schreiben koennen (z.B. timestamp/last_updated/notes
# direkt unter dem Frontmatter). repair_leaked_keys() entfernt genau diesen fuehrenden Lauf.
_LEAKED_KEY_RE = re.compile(
    r"^(timestamp|last_updated|notes|status|processed|processed_at|"
    r"entities_created|entities_updated):")
_LEAKED_CONT_RE = re.compile(r"^\s*- ")


def repair_leaked_keys(path: Path | str) -> bool:
    """Nackte Frontmatter-Keys direkt nach dem schliessenden `---` entfernen.

    Entfernt nur den zusammenhaengenden fuehrenden Lauf solcher Zeilen (samt
    unmittelbar folgender `- `-Listenzeilen); regulaerer Body-Text bleibt
    unangetastet. True = Datei wurde repariert.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    m = _FM_RE.match(text)
    if not m:
        return False
    body = text[m.end():]
    lines = body.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        if _LEAKED_KEY_RE.match(lines[i]):
            i += 1
            while i < len(lines) and _LEAKED_CONT_RE.match(lines[i]):
                i += 1
            continue
        break
    if i == 0:
        return False
    p.write_text(text[:m.end()] + "".join(lines[i:]), encoding="utf-8", newline="\n")
    return True


def project_path(slug: str) -> Path:
    return PROJECTS_DIR / f"{slug}.md"


def forum_path(slug: str) -> Path:
    return FORUMS_DIR / f"{slug}.md"


def iter_forums():
    """Yield (slug, path, frontmatter) fuer alle Gremien/Formate."""
    if not FORUMS_DIR.is_dir():
        return
    for f in sorted(FORUMS_DIR.glob("*.md")):
        if _usable(f):
            yield f.stem, f, read_frontmatter(f)


def iter_projects():
    """Yield (slug, path, frontmatter) fuer alle Projektdateien.

    Fehlendes Verzeichnis ist *leer*, kein Fehler.
    """
    if not PROJECTS_DIR.is_dir():
        return
    for f in sorted(PROJECTS_DIR.glob("*.md")):
        if not _usable(f):
            continue
        yield f.stem, f, read_frontmatter(f)


def _usable(f: Path) -> bool:
    """Existiert wirklich und ist lesbar.

    Ein Vault kann Alias-Symlinks enthalten (z.B. `Anna.md -> anna-beispiel.md`), deren
    Ziel fehlt. `glob` findet sie trotzdem - ohne diese Pruefung landen sie
    als gueltige Slugs in der LLM-Whitelist und werden zu Geister-Entities.
    """
    try:
        return f.is_file() and f.stat().st_size >= 0
    except OSError:
        return False


def broken_links(category: str | None = None) -> list[Path]:
    """Nicht aufloesbare Entity-Dateien (kaputte Symlinks) - Diagnose beim Direktaufruf
    dieses Moduls (`python -m secondbrain.vault_paths`)."""
    cats = [category] if category else list(ENTITY_CATEGORIES)
    out = []
    for cat in cats:
        d = CATEGORY_DIRS.get(cat)
        if not d or not d.is_dir():
            continue
        out.extend(f for f in sorted(d.glob("*.md")) if not _usable(f))
    return out


def entity_slugs(category: str) -> list[str]:
    d = CATEGORY_DIRS.get(category)
    if not d or not d.is_dir():
        return []
    return sorted(f.stem for f in d.glob("*.md") if _usable(f))


def known_slugs() -> dict[str, list[str]]:
    """Whitelist fuer die LLM-Ausgabe-Validierung (prozessweit gecacht)."""
    if _ENTITY_CACHE["known_slugs"] is None and not _load_disk_cache():
        _ENTITY_CACHE["known_slugs"] = {cat: entity_slugs(cat)
                                        for cat in ENTITY_CATEGORIES}
    return {cat: list(v) for cat, v in _ENTITY_CACHE["known_slugs"].items()}


def alias_map() -> dict[str, str]:
    """{alias_lowercase: slug} ueber alle Entities (prozessweit gecacht)."""
    if _ENTITY_CACHE["alias_map"] is not None:
        return dict(_ENTITY_CACHE["alias_map"])
    if _load_disk_cache():
        return dict(_ENTITY_CACHE["alias_map"])
    files = []
    for cat in ENTITY_CATEGORIES:
        d = CATEGORY_DIRS.get(cat)
        if d and d.is_dir():
            files.extend(f for f in sorted(d.glob("*.md")) if _usable(f))
    out: dict[str, str] = {}
    for f, text in _read_many(files):
        if text is None:
            continue
        fm = split_frontmatter(text)[0]
        keys = [f.stem, fm.get("name")]
        # `schreibweisen:` (bestaetigte Verschreiber, schreibweisen.py) zaehlen beim Zuordnen mit
        for feld in ("aliases", "schreibweisen"):
            werte = fm.get(feld) or []
            keys.extend([werte] if isinstance(werte, str) else werte)
        for k in keys:
            if k:
                out.setdefault(str(k).strip().lower(), f.stem)
    _ENTITY_CACHE["alias_map"] = out
    known_slugs()  # zweiten Cache-Teil fuellen, dann gemeinsam persistieren
    _save_disk_cache()
    return dict(out)


_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def archive_migration(report: Path, name: str, day: str | None = None) -> Path:
    """Uebernommenen Vorschlag nach `archive/migrations/<datum>-<name>` verschieben - nie
    ueberschreiben: die zweite Runde am selben Tag wird `-2`, dann `-3` (sonst ginge die
    erste Runde verloren)."""
    day = day or date.today().isoformat()
    stem, suffix = Path(name).stem, Path(name).suffix or ".md"
    target = SOURCES_DIR / "migrations" / f"{day}-{stem}{suffix}"
    n = 2
    while target.exists():
        target = target.with_name(f"{day}-{stem}-{n}{suffix}")
        n += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    report.replace(target)
    return target


def source_date(source_file: str, fallback: str | None = None) -> str:
    """Datum einer Quelldatei: Frontmatter `date:` -> Dateiname-Praefix -> Fallback/heute.

    Zentrale Regel: Ereignisse tragen das Datum des Termins bzw. der Quelle, nicht
    das heutige. Genutzt von `uebernehmen.py` - an dieser einen Stelle implementiert.
    """
    if source_file:
        p = Path(source_file)
        if not p.is_absolute():
            p = VAULT / source_file
        if p.is_file():
            fm = read_frontmatter(p)
            d = str(fm.get("date") or "")[:10]
            if _ISO_DATE_RE.match(d):
                return d
        m = _DATE_PREFIX_RE.match(Path(source_file).name)
        if m:
            return m.group(1)
    return fallback or date.today().isoformat()


if __name__ == "__main__":
    import json
    print(json.dumps({
        "vault": str(VAULT),
        "projects_dir": str(PROJECTS_DIR),
        "known_slugs": {k: len(v) for k, v in known_slugs().items()},
        "aliases": len(alias_map()),
        "broken_entity_links": [str(f.relative_to(VAULT)) for f in broken_links()],
    }, indent=2, ensure_ascii=False))
