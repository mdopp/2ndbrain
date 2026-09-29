#!/usr/bin/env python3
"""entdrahtung.py - Stehen Namen dieses Vaults im Code? (`2ndbrain entdrahtung`)

Gleicht Engine, Tests, Vorlagen, Chat-Skills, Doku und Plugin mit den Namen ab, die der Vault kennt:
Personen, Firmen, Systeme, Teams, Themen, Reihen (Name, Titel, Aliasse, Slug), dazu die eigene
Organisation, interne Mail-Adressen, private IP-Adressen und der eigene Benutzerpfad. Der Code
soll keine davon enthalten - das Wissen gehört in den Vault (Seiten, local.config.json).

Nur lesend. Wörter, die zugleich allgemein sind (Teams, Portal, API …), zählen nicht.

    2ndbrain entdrahtung [--gruppe Engine] [--datei frage.py] [--alle] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Entwickler-Werkzeug im Code-Repo: nutzt die Module der Engine aus dem Quelltext daneben
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "secondbrain"))

import vault_paths as vp

if not vp.VAULT_FOUND:
    sys.exit("[ABBRUCH] Kein Vault gefunden - im Vault-Ordner starten oder VAULT_DIR=<Vault> setzen.")

CATS = {"people": "Person", "companies": "Firma", "systems": "System", "teams": "Team",
        "projects": "Thema", "forums": "Reihe"}
# Namen, die zugleich allgemeine Wörter, Fachbegriffe oder Produkte sind - im Code kein Hinweis auf
# den Vault. Was nur in diesem Vault allgemein ist (eigene Team- und Systemnamen), steht in
# `.2ndbrain/local.config.json` unter "entdrahtung": {"allgemein": [...]}, nicht hier.
ALLGEMEIN = {x.lower() for x in (
    "cmd", "hits", "claude", "claude code", "claude-code", "mcp server", "mcp-server", "edi", "eai", "portal",
    "steering", "network", "database", "finance", "iam", "jira", "grafana", "snowflake", "workday",
    "domain atlas", "domain-atlas", "meta", "api", "teams", "team", "system", "systems", "test", "demo",
    "daten", "data", "status", "review", "chat", "mail", "outlook", "excel", "sap", "ai", "it", "one",
    "amazon", "azure ad", "azure-ad", "auth0", "api gateway", "api-gateway", "change management",
    "change-management", "tms", "check mk", "check-mk", "ki", "bpm", "cep", "dms", "crm", "ecmr",
    "it-management", "it management", "reporting", "migration", "linux", "windows", "citrix", "office",
    "sharepoint", "confluence", "github", "gitlab", "docker", "python", "obsidian", "likec4", "mermaid",
    "dataview", "templater", "ollama", "llama", "qwen", "gemma")}
ALLGEMEIN |= {str(x).lower() for x in ((vp.local_config().get("entdrahtung") or {}).get("allgemein") or [])}
GRUPPEN = (("Tests", lambda p: p.name.startswith("test_") or "/tests/" in p.as_posix()),
           ("Plugin", lambda p: "plugin" in p.parts or p.name in ("manifest.json", "versions.json")),
           ("Chat-Skills", lambda p: "chat-skills" in p.parts),
           ("Vorlage", lambda p: "vorlage" in p.parts),
           ("Doku", lambda p: p.suffix == ".md"),
           ("Engine", lambda p: True))


def terms() -> dict[str, str]:
    """Name -> Kategorie, aus den Seiten des Vaults (ab 3 Zeichen, ohne allgemeine Wörter)."""
    out: dict[str, str] = {}

    def add(t, cat):
        t = re.sub(r"^\[\[|\]\]$", "", str(t or "").strip().strip("'\""))
        base = re.sub(r"\s*\([^)]*\)\s*$", "", t).lower()        # "X (Bereich)" wie "X"
        if len(t) >= 3 and t.lower() not in ALLGEMEIN and base not in ALLGEMEIN:
            out.setdefault(t, cat)
    for sub, cat in CATS.items():
        for f in sorted(vp.CATEGORY_DIRS[sub].glob("*.md")) if vp.CATEGORY_DIRS.get(sub) else []:
            fm = vp.read_frontmatter(f) or {}
            add(f.stem, cat)
            for k in ("name", "title"):
                if isinstance(fm.get(k), str):
                    add(fm[k], cat)
                    add(re.sub(r"\s*\([^)]*\)\s*$", "", fm[k]), cat)
            al = fm.get("aliases") or []
            for a in (al if isinstance(al, list) else [al]):
                add(a, cat)
    if vp.organisation():
        add(vp.organisation(), "Organisation")
    # Vornamen allein ("Rueckfrage zu Anna") - bis auf die erfundenen Beispielnamen der Tests
    for f in sorted(vp.CATEGORY_DIRS["people"].glob("*.md")) if vp.CATEGORY_DIRS.get("people") else []:
        first = str((vp.read_frontmatter(f) or {}).get("name") or "").split(" ")[0].strip()
        if len(first) >= 4 and first.lower() not in ERFUNDEN and first.isalpha():
            add(first, "Vorname")
    # Titel von Terminen und Mails: frueher genutzte Namen, die keine Seite mehr haben
    for root in ("active-meetings", "archive/meetings"):
        d = vp.VAULT / root
        for f in sorted(d.rglob("*.md")) if d.is_dir() else []:
            fm = vp.read_frontmatter_head(f)
            titel = _titel(fm.get("title"))
            if titel:
                add(titel, "Mail-Betreff" if str(fm.get("type")) == "email-thread" else "Termin")
    cal = vp.VAULT / "archive" / "calendar" / "events.json"
    try:
        events = json.loads(cal.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        events = []
    for e in events if isinstance(events, list) else []:
        titel = _titel(e.get("summary"))
        if titel:
            add(titel, "Termin")
    return out


# Erfundene Beispielnamen, die Tests und Vorlagen bewusst nutzen - kein Hinweis auf den Vault
ERFUNDEN = {"anna", "max", "erika", "jana", "felix", "lisa", "timo", "tímo", "robert",
            "daniel", "paul", "lena", "otto"}


def _titel(value) -> str:
    """Titel ohne Antwort-Vorsilben; nur, was als ganze Wendung eindeutig ist (mind. zwei Woerter)."""
    t = re.sub(r"^(?:(?:AW|RE|WG|FW|Fwd|Antw)\s*[:-]\s*)+", "", str(value or "").strip(), flags=re.I).strip(" -")
    return t if len(t) >= 10 and len(t.split()) >= 2 else ""


# Das Code-Repo (bei einer Entwickler-Installation), sonst nur das installierte Paket
REPO = vp.ENGINE_DIR.parents[1] if (vp.ENGINE_DIR.parents[1] / "plugin" / "src").is_dir() else None
BASE = REPO or vp.ENGINE_DIR


def files() -> list[Path]:
    e = vp.ENGINE_DIR
    out = sorted(e.glob("*.py")) + sorted(e.glob("*.json")) + sorted(e.glob("*.yaml"))
    out += sorted(f for f in vp.VORLAGE_DIR.rglob("*") if f.is_file())
    if REPO:
        plug = REPO / "plugin"
        out += sorted((REPO / "engine" / "tests").glob("*.py"))
        out += sorted((REPO / "engine" / "tools").glob("*.py"))
        out += sorted((plug / "src").rglob("*.ts")) + sorted((plug / "tests").rglob("*.ts"))
        out += [plug / n for n in ("README.md", "package.json", "styles.css", "esbuild.config.mjs") if (plug / n).is_file()]
        out += [REPO / n for n in ("README.md", "manifest.json", "versions.json", "LICENSE") if (REPO / n).is_file()]
        out += [REPO / "engine" / n for n in ("README.md", "pyproject.toml") if (REPO / "engine" / n).is_file()]
        out += sorted((REPO / "docs").rglob("*.md")) + sorted((REPO / ".github").rglob("*.yml"))
    return out


def gruppe(p: Path) -> str:
    return next(name for name, test in GRUPPEN if test(p))


def scan(only_group: str = "", only_file: str = "") -> list[dict]:
    names = terms()
    # Vornamen nur gross geschrieben: "mark" oder "paras" im Code sind Woerter, keine Namen
    vornamen = sorted((n for n, c in names.items() if c == "Vorname"), key=len, reverse=True)
    long_first = sorted((n for n, c in names.items() if c != "Vorname"), key=len, reverse=True)
    rx_names = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in long_first) + r")(?![\w-])", re.I)
    rx_vornamen = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in vornamen) + r")(?![\w-])") \
        if vornamen else None
    specials = [("Organisation", re.compile(r"(?i)\b" + re.escape(vp.organisation()) + r"\b"))] if vp.organisation() else []
    specials += [("Mail-Domain", re.compile(r"@" + re.escape(d) + r"\b", re.I)) for d in sorted(vp.interne_domains())]
    specials += [("IP-Adresse", re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")),
                 ("Benutzerpfad", re.compile(re.escape(Path.home().as_posix()) + "|" + re.escape(str(Path.home())), re.I))]
    hits = []
    for p in files():
        g = gruppe(p)
        if (only_group and g.lower() != only_group.lower()) or (only_file and only_file not in p.as_posix()):
            continue
        try:
            lines = p.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines, 1):
            if ((p.name == "manifest.json" and line.strip().startswith(('"author"', '"authorUrl"')))
                    or (p.name == "LICENSE" and line.startswith("Copyright"))
                    or (p.name == "pyproject.toml" and line.startswith("authors"))):
                continue            # Autor bewusst (Veroeffentlichung unter github.com/mdopp)
            found = {m.group(1) for m in rx_names.finditer(line)}
            if rx_vornamen:
                found |= {m.group(1) for m in rx_vornamen.finditer(line)}
            kinds = {names.get(f) or next((c for n, c in names.items() if n.lower() == f.lower()), "?") for f in found}
            kinds |= {k for k, rx in specials if rx.search(line)}
            if found or kinds:
                hits.append({"gruppe": g, "datei": p.relative_to(BASE).as_posix(), "zeile": i,
                             "namen": sorted(found), "arten": sorted(kinds), "text": line.strip()[:160]})
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Namen dieses Vaults im Code finden")
    ap.add_argument("--gruppe", default="", help="Engine, Tests, Vorlage, Chat-Skills, Doku, Plugin")
    ap.add_argument("--datei", default="", help="nur Dateien, deren Pfad dies enthält")
    ap.add_argument("--alle", action="store_true", help="jede Fundstelle zeigen, nicht nur die Zählung")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    hits = scan(args.gruppe, args.datei)
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=1))
        return 0
    by_group, by_file = defaultdict(int), defaultdict(int)
    for h in hits:
        by_group[h["gruppe"]] += 1
        by_file[h["datei"]] += 1
    print(f"Namen dieses Vaults im Code: {len(hits)} Zeilen in {len(by_file)} Dateien")
    for g, _t in GRUPPEN:
        print(f"  {g:12} {by_group.get(g, 0):5}")
    if args.alle or args.datei:
        for h in hits:
            print(f"{h['datei']}:{h['zeile']}: [{', '.join(h['namen'] or h['arten'])}] {h['text']}")
    else:
        print("\nMeiste Fundstellen:")
        for f, n in sorted(by_file.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {n:4}  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
