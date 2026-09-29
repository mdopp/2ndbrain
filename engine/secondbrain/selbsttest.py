#!/usr/bin/env python3
"""selbsttest.py - Konsistenz zwischen Werkzeugen, Konventionen und Daten pruefen.

Prueft die **Verdrahtung** - genau die Fehlerklasse, die im Betrieb zu falschen
Diagnosen fuehrt:

  - Eine Rueckfrage, deren Ziel nicht existiert (Endlosschleife beim Aufloesen)
  - Eine Notiz, die auf ein Thema oder eine Reihe zeigt, die es nicht gibt
  - Ein Verzeichnis, das ein Werkzeug voraussetzt, das aber fehlt
  - Frontmatter, das nicht als YAML parst (Datei ist dann fuer alles unsichtbar)
  - Toter Code: ein Modul, das kein anderes importiert oder aufruft

Nur lesend: Befunde werden gemeldet, nichts wird repariert (Exit 1 bei Befunden).

    2ndbrain selbsttest
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

PENDING_DIR = vp.DATA_DIR / ".pending"


def check_pending_targets() -> list[str]:
    """Rueckfrage, deren Ziel fehlt -> jeder Aufloesungsversuch scheitert."""
    out = []
    if not PENDING_DIR.is_dir():
        return out
    import json
    cat_by_kind = {"unknown_project": ("projects", "thema-neu"),
                   "unknown_person": ("people", "person-neu"),
                   "unknown_forum": ("forums", "reihe-neu")}
    for f in sorted(PENDING_DIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            out.append(f"{f.name}: nicht lesbar - Wiedervorlage verloren")
            continue
        info = cat_by_kind.get(str(d.get("kind") or ""))
        if not info:
            continue
        category, maker = info
        raw = str(d.get("raw_slug") or "")
        known = vp.entity_slugs(category)
        # existiert irgendetwas, das passen koennte?
        import difflib
        guess = difflib.get_close_matches(raw.lower().replace(" ", "-"), known, n=1, cutoff=0.7)
        if not guess:
            out.append(f"{f.stem}: Ziel '{raw}' hat keine Entity in entities/{category}/ "
                       f"-> anlegen mit `2ndbrain {maker} \"{raw}\"`, sonst nicht aufloesbar")
    return out


def check_dangling_references() -> list[str]:
    """Notizen, die auf ein nicht existierendes Thema (`themen:`) oder eine Reihe (`forum:`) zeigen."""
    out = []
    projects = set(vp.entity_slugs("projects"))
    forums = set(vp.entity_slugs("forums"))
    roots = [vp.VAULT.glob("*.md"), (vp.VAULT / "active-meetings").rglob("*.md"),
             vp.MEETINGS_DIR.rglob("*.md")]
    for it in roots:
        for f in it:
            if not f.is_file():
                continue
            fm = vp.read_frontmatter(f)
            fo = fm.get("forum")
            for p in vp.note_themen(fm):
                if p not in projects:
                    out.append(f"{f.name}: Thema '{p}' existiert nicht")
            if fo and str(fo) not in forums:
                out.append(f"{f.name}: forum '{fo}' existiert nicht")
    return out


def check_unparseable_frontmatter() -> list[str]:
    """Frontmatter, das nicht parst - die Datei ist dann fuer alles unsichtbar."""
    import yaml
    out = []
    for f in vp.VAULT.rglob("*.md"):
        # `.templates/` enthaelt Platzhalter ({{title}}), die YAML als Flow-Mapping
        # liest - gewollt, kein Befund. Der Papierkorb gehoert nicht zum Vault.
        if any(x in (".obsidian", ".trash", "node_modules", ".templates") for x in f.parts):
            continue
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            out.append(f"{f.name}: nicht lesbar")
            continue
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if not m:
            continue
        try:
            d = yaml.safe_load(m.group(1))
        except yaml.YAMLError as e:
            first = str(e).splitlines()[0]
            out.append(f"{f.relative_to(vp.VAULT)}: YAML kaputt ({first})")
            continue
        if not isinstance(d, dict):
            out.append(f"{f.relative_to(vp.VAULT)}: Frontmatter ist kein Mapping")
    return out


def check_expected_dirs() -> list[str]:
    """Verzeichnisse, die Werkzeuge voraussetzen."""
    out = []
    for label, path in (("Projekte", vp.PROJECTS_DIR), ("Personen", vp.PEOPLE_DIR),
                        ("Foren", vp.FORUMS_DIR), ("Systeme", vp.SYSTEMS_DIR),
                        ("Quellen-Archiv", vp.SOURCES_DIR)):
        if not path.is_dir():
            out.append(f"{label}: {path.relative_to(vp.VAULT)} fehlt")
    return out


def check_dead_modules() -> list[str]:
    """Module, die kein anderes Modul importiert oder aufruft - vorhanden, aber nicht verdrahtet."""
    out = []
    files = sorted(p for p in vp.ENGINE_DIR.glob("*.py")
                   if not p.name.startswith(("test_", "_")))
    texts = {q: q.read_text(encoding="utf-8", errors="replace") for q in files}
    # Einstiegspunkte: die Befehlszeile selbst und jedes Modul, das ein Befehl startet
    # (Befehlsliste in befehle.py: ("befehl", "modul", …))
    entry = {"befehle.py", "selbsttest.py"}
    befehle = vp.ENGINE_DIR / "befehle.py"
    tabelle = befehle.read_text(encoding="utf-8", errors="replace") if befehle.is_file() else ""
    gestartet = set(re.findall(r'\(\s*"[\w-]+",\s*"([a-z_][a-z0-9_]*)"', tabelle))
    for p in files:
        mod = p.stem
        if p.name in entry or mod in gestartet:
            continue
        # Nur ANDERE Dateien zaehlen: der eigene Hilfetext ("python -m secondbrain.<modul>")
        # machte ein Modul sonst "benutzt".
        corpus = "\n".join(t for q, t in texts.items() if q != p)
        # Auch Aufrufe ueber den Dateinamen zaehlen (einlesen.py: TOOLS / "kalender.py").
        used = (re.search(rf"\bimport\s+{re.escape(mod)}\b", corpus)
                or re.search(rf"\bfrom\s+{re.escape(mod)}\s+import\b", corpus)
                or re.search(rf"(?<![\w.-]){re.escape(p.name)}", corpus))
        if not used:
            out.append(f"{p.name}: wird von keinem Werkzeug aufgerufen "
                       f"(toter Code oder fehlende Verdrahtung)")
    return out


CHECKS = (
    ("Rueckfragen ohne Ziel", check_pending_targets),
    ("Verweise auf fehlende Projekte/Foren", check_dangling_references),
    ("unlesbares Frontmatter", check_unparseable_frontmatter),
    ("erwartete Verzeichnisse", check_expected_dirs),
    ("nicht verdrahtete Module", check_dead_modules),
)


def run(verbose: bool = True) -> dict[str, list[str]]:
    findings = {}
    for label, fn in CHECKS:
        try:
            res = fn()
        except Exception as e:
            res = [f"Pruefung selbst fehlgeschlagen: {type(e).__name__}: {e}"]
        if res:
            findings[label] = res
    if verbose:
        total = sum(len(v) for v in findings.values())
        print("=" * 60)
        print(f"SELBSTTEST — Verdrahtung und Konventionen ({total} Befund(e))")
        print("=" * 60)
        if not findings:
            print("\nKeine Befunde: Werkzeuge, Konventionen und Daten passen zusammen.")
        for label, items in findings.items():
            print(f"\n{label} ({len(items)}):")
            for i in items[:12]:
                print(f"  - {i}")
            if len(items) > 12:
                print(f"  ... und {len(items) - 12} weitere")
    return findings


if __name__ == "__main__":
    f = run()
    sys.exit(1 if f else 0)
