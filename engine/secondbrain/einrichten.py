#!/usr/bin/env python3
"""einrichten.py - 2ndBrain in einem Vault auf diesem Rechner einrichten (`2ndbrain einrichten`).

Im Vault-Ordner ausfuehren (oder VAULT_DIR setzen) - mit dem Python, in dem die Engine installiert
ist; das Plugin ruft es mit seinem Knopf "Einrichten" genauso auf. Jeder Schritt meldet ✓ oder !:
  1. Python: genau dieses Python (vollstaendiger Pfad) wird im 2ndBrain-Plugin eingetragen.
     Mindestens 3.10. (Findet das Plugin es spaeter nicht mehr, sucht es selbst: py, python, python3.)
  2. Engine: Version und Pakete (kommen mit `pip install` der Engine).
  3. Vault: fehlende Ordner und Vorlagen anlegen (Cockpit-Seiten, Templates, Playbooks,
     Chat-Rezepte in .2ndbrain/chat-skills) - Vorhandenes wird nie ueberschrieben.
  4. Ich und Pfade: `ich` (eigene Personen-Seite) und die interne Mail-Domain pruefen;
     likec4-model und domain-atlas (neben dem Vault, ~/code, ~) -> local.config.json;
     ein eingetragener, aber verschwundener Pfad wird durch den gefundenen ersetzt.
  5. Kalender: aus dem Obsidian-Schluesselbund (das Plugin reicht ihn herein) oder
     .2ndbrain/calendar.config.json; `--kalender-url` schreibt die Datei (fuer Laeufe ohne Plugin).
     Die URL wirkt wie ein Zugangsschluessel und wird nie ausgegeben.
  6. Modell-Server, Kanon, Node/likec4, Obsidian-Plugins (2ndBrain, Dataview).
  7. MCP-Befehl fuer Claude - mit genau diesem Python und diesem Vault.

    2ndbrain einrichten [--kalender-url URL] [--nur-pruefen] [--json]
    2ndbrain pfade --json     (fuer das Plugin: Modell-Ordner, likec4-Befehl, Python, Version)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

MIN_PY = (3, 10)
PLUGIN_DATA = Path(".obsidian") / "plugins" / "2ndbrain" / "data.json"
CAL_CONFIG = Path(".2ndbrain") / "calendar.config.json"
PLUGINS = {"2ndbrain": "2ndBrain", "dataview": "Dataview"}
# Ordner, die die Werkzeuge voraussetzen (vault_paths)
ORDNER = ("inbox", "active-meetings", "archive", "reports", "entities/projects", "entities/people",
          "entities/teams", "entities/companies", "entities/systems", "entities/forums",
          "entities/contexts", "entities/glossary", "entities/meeting-playbooks", ".2ndbrain/daten")
PAKETE = ("yaml", "pypdf", "docx", "pptx", "openpyxl")


def version() -> str:
    """Version der Engine (secondbrain/__init__.py) - ohne das Paket zu importieren."""
    import re
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (vp.ENGINE_DIR / "__init__.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "?"


def vorlage_anlegen(schreiben: bool = True) -> list[str]:
    """Fehlende Ordner und Vorlagen-Dateien in den Vault; nichts wird ueberschrieben. Angelegte (relativ)."""
    neu = []
    for d in ORDNER:
        if not (vp.VAULT / d).is_dir():
            neu.append(d + "/")
            if schreiben:
                (vp.VAULT / d).mkdir(parents=True, exist_ok=True)
    for root, _dirs, files in os.walk(vp.VORLAGE_DIR):
        for name in sorted(files):
            src = Path(root) / name
            rel = src.relative_to(vp.VORLAGE_DIR)
            dst = vp.VAULT / rel
            if dst.exists():
                continue
            neu.append(rel.as_posix())
            if schreiben:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
    return neu


def mcp_befehl() -> str:
    return (f'claude mcp add --scope user 2ndbrain-vault -e VAULT_DIR="{vp.VAULT.as_posix()}" '
            f'-- "{sys.executable}" -m secondbrain mcp')


def _load(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def likec4_command(model: Path | None) -> list[str] | None:
    """Wie das Plugin den Explorer startet: likec4 im PATH > im Modell- oder Atlas-Ordner.
    Bewusst kein `npx`-Rueckfall: der laedt likec4 beim ersten Start ungefragt aus npm."""
    found = shutil.which("likec4")
    if found:
        return [found]
    atlas = vp.external_path("domain_atlas")
    for base in [b for b in (model, atlas) if b]:
        for name in ("likec4.cmd", "likec4"):
            p = base / "node_modules" / ".bin" / name
            if p.is_file():
                return [str(p)]
    return None


def needs_shell(cmd: list[str]) -> bool:
    """.cmd/.bat (npm-Starter unter Windows) laufen nur über die Shell."""
    return os.name == "nt" and cmd[0].lower().endswith((".cmd", ".bat"))


def paths() -> dict:
    model = vp.external_path("likec4_model")
    atlas = vp.external_path("domain_atlas")
    return {"likec4_model": str(model) if model and model.is_dir() else None,
            "domain_atlas": str(atlas) if atlas and atlas.is_dir() else None,
            "likec4_befehl": likec4_command(model if model and model.is_dir() else None),
            "python": sys.executable,
            "version": version(),
            "ich": vp.ich(),
            "kalender": kalender_quelle() != "",                              # nur ob - nie die URL
            "kalender_quelle": kalender_quelle()}


def kalender_quelle() -> str:
    """Woher die Kalender-Adresse kommt: "schluesselbund" (vom Plugin), "datei" oder ""."""
    if os.environ.get("VAULT_CALENDAR_URL", "").strip():
        return "schluesselbund"
    return "datei" if _load(vp.VAULT / CAL_CONFIG).get("ical_url") else ""


def run(kalender_url: str | None = None, schreiben: bool = True) -> dict:
    """schreiben=False: nur prüfen und melden, was eingetragen würde (`--nur-pruefen`)."""
    vault = vp.VAULT
    out: dict = {"schritte": []}
    würde = "" if schreiben else " (würde eingetragen – nur geprüft)"

    def step(ok: bool, name: str, text: str) -> None:
        out["schritte"].append({"ok": ok, "schritt": name, "text": text})

    # 1. Python
    ver = sys.version_info
    py_ok = (ver.major, ver.minor) >= MIN_PY
    data_path = vault / PLUGIN_DATA
    if data_path.parent.is_dir():
        data = _load(data_path)
        data["pythonPath"] = sys.executable
        if schreiben:
            _save(data_path, data)
        step(py_ok, "Python", f"{sys.executable} (Version {ver.major}.{ver.minor})"
             + (" im Plugin eingetragen" if schreiben else würde)
             + ("" if py_ok else f" – zu alt, mindestens {MIN_PY[0]}.{MIN_PY[1]}"))
    else:
        step(False, "Python", f"{sys.executable} – 2ndBrain-Plugin fehlt unter .obsidian/plugins/2ndbrain")
    # 2. Engine und ihre Pakete (kommen mit der Installation der Engine)
    import importlib.util
    fehlt = [m for m in PAKETE if importlib.util.find_spec(m) is None]
    step(not fehlt, "Engine", f"Version {version()} in {sys.executable}"
         + (f" – Pakete fehlen: {', '.join(fehlt)} (Engine neu installieren: "
            f"`{Path(sys.executable).name} -m pip install --upgrade <Engine>`)" if fehlt else ""))
    # 3. Vault: Ordner und Vorlagen, die fehlen
    neu = vorlage_anlegen(schreiben)
    step(True, "Vault", ("nichts zu ergänzen" if not neu else f"{len(neu)} Ordner/Vorlagen "
                         + ("angelegt" if schreiben else "würden angelegt") + ": "
                         + ", ".join(neu[:6]) + (" …" if len(neu) > 6 else "")))
    # 4. Ich und Pfade - gefundene eintragen, verschwundene durch gefundene ersetzen
    cfg_path = vp.LOCAL_CONFIG_FILE
    cfg = _load(cfg_path)
    changed = False
    if not cfg.get("ich"):
        step(False, "Ich", "kein \"ich\" in local.config.json – eigenen Personen-Slug eintragen (z. B. vorname-nachname)")
    elif not (vp.PEOPLE_DIR / f"{cfg['ich']}.md").is_file():
        step(False, "Ich", f"\"ich\": {cfg['ich']} – aber entities/people/{cfg['ich']}.md fehlt")
    else:
        domains = vp.interne_domains()
        step(bool(domains), "Ich", f"{cfg['ich']} · interne Mail-Domain: "
             + (", ".join(sorted(domains)) if domains
                else "unbekannt – `email:` auf der eigenen Personen-Seite eintragen (sonst gilt niemand als intern)"))
    for name, (env_var, _dirs) in vp.EXTERNAL_SOURCES.items():
        if os.environ.get(env_var):
            p = Path(os.environ[env_var]).expanduser()
            step(p.is_dir(), f"Pfad {name}", f"{p.as_posix()} (aus {env_var})"
                 + ("" if p.is_dir() else " – nicht vorhanden"))
            continue
        configured = (cfg.get("paths") or {}).get(name)
        p = Path(configured).expanduser() if configured else None
        if p and p.is_dir():
            step(True, f"Pfad {name}", p.as_posix())
            continue
        found = vp.detect_path(name)
        if found:
            cfg.setdefault("paths", {})[name] = found.as_posix()
            changed = True
            step(True, f"Pfad {name}", found.as_posix() + (f" (statt {configured}, das fehlt)" if configured else "")
                 + (" – in local.config.json eingetragen" if schreiben else würde))
        elif configured:
            step(False, f"Pfad {name}", f"{configured} eingetragen, aber nicht vorhanden")
        else:
            step(False, f"Pfad {name}", "nicht gefunden – neben den Vault legen oder in local.config.json eintragen")
    if changed and schreiben:
        _save(cfg_path, cfg)
    # 5. Kalender (die URL nie ausgeben). Eine ausdrücklich angegebene Adresse ersetzt
    # die alte (Kalender in Outlook neu veröffentlicht -> neue Adresse).
    cal_path = vault / CAL_CONFIG
    cal = _load(cal_path)
    had = bool(cal.get("ical_url"))
    if kalender_quelle() == "schluesselbund" and not kalender_url:
        step(True, "Kalender", "aus dem Obsidian-Schlüsselbund (Plugin-Einstellungen)")
    have, replaced = had, False
    if kalender_url and schreiben:
        import kalender
        if kalender.source_kind(kalender_url):
            replaced = had and cal.get("ical_url") != kalender_url
            _save(cal_path, {**cal, "ical_url": kalender_url})
            have = True
        else:
            step(False, "Kalender", "das sieht nicht nach einer Kalender-Adresse aus (https://, webcal:// "
                                    "oder Pfad zu einer .ics-Datei) – nicht gespeichert")
    if have and not any(s["schritt"] == "Kalender" for s in out["schritte"]):
        step(True, "Kalender", (".2ndbrain/calendar.config.json: Adresse ersetzt" if replaced
                                else ".2ndbrain/calendar.config.json vorhanden")
             + " (eigene Datei, nicht weitergeben)")
    elif not any(s["schritt"] == "Kalender" for s in out["schritte"]):
        step(False, "Kalender", "fehlt – im Plugin unter Einstellungen → Kalender eintragen "
                                "(oder `2ndbrain einrichten --kalender-url <iCal-Adresse>`)")
    # Modell-Server: steht nur in llm.config.json (der Code kennt keine Adresse)
    llm_cfg = _load(vp.DATA_ROOT / "llm.config.json")
    step(bool(llm_cfg.get("url")), "Modell-Server",
         f"{llm_cfg['url']} · Modell {llm_cfg.get('model') or '?'} (.2ndbrain/llm.config.json)" if llm_cfg.get("url")
         else "keine Adresse – .2ndbrain/llm.config.json mit \"url\" und \"model\" anlegen (ohne Modell: nur Fakten)")
    # Kanon (optional): Domain Atlas oder einfache YAML-Datei (kanon.py)
    import kanon
    kc = kanon.konfig()
    kn = kanon.lade() if kc else None
    if not kc:
        step(True, "Kanon", "keiner (optional: `kanon` in .2ndbrain/local.config.json, Vorlage "
                            f"{(vp.ENGINE_DIR / 'kanon.example.yaml').as_posix()})")
    elif kn:
        step(True, "Kanon", f"{kn['regeln']['name']} ({kc['format']}): {len(kn['kontexte'])} Kontexte, "
                            f"{len(kn['objekte'])} Fachbegriffe")
    else:
        step(False, "Kanon", f"{kc['format']} unter {kc['pfad']} nicht lesbar")
    # 6. Node / likec4
    pf = paths()
    cmd = pf["likec4_befehl"]
    if not pf["likec4_model"]:
        step(False, "LikeC4", "kein Modell-Ordner – `2ndbrain systemuebersicht` legt ihn an")
    elif cmd:
        step(True, "LikeC4", "Explorer startet über " + " ".join(Path(cmd[0]).name if i == 0 else c for i, c in enumerate(cmd)))
    else:
        step(False, "LikeC4", "likec4 nicht gefunden – Node.js (nodejs.org) und im Modell-Ordner `npm install likec4` "
                              "(oder `npm install -g likec4`), dann startet das Plugin den Explorer")
    # Obsidian-Plugins
    missing = [label for pid, label in PLUGINS.items() if not (vault / ".obsidian" / "plugins" / pid / "main.js").is_file()]
    step(not missing, "Obsidian-Plugins", "alle da" if not missing else f"fehlen: {', '.join(missing)} – in Obsidian: Einstellungen → Community-Plugins")
    # 7. MCP
    out["mcp"] = mcp_befehl()
    out["ok"] = all(s["ok"] for s in out["schritte"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="2ndBrain auf diesem Rechner einrichten")
    ap.add_argument("--kalender-url", help="iCal-Adresse des Kalenders: https://, webcal:// oder .ics-Datei (fuer Laeufe ohne Plugin)")
    ap.add_argument("--pfade", action="store_true", help="nur Pfade/Befehle als JSON (für das Plugin)")
    ap.add_argument("--nur-pruefen", action="store_true", help="nichts schreiben, nur melden, was fehlt/eingetragen würde")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.pfade:
        print(json.dumps(paths(), ensure_ascii=False))
        return 0
    r = run(args.kalender_url, schreiben=not args.nur_pruefen)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 1
    for s in r["schritte"]:
        print(f"  {'✓' if s['ok'] else '!'} {s['schritt']:18} {s['text']}")
    print("\nClaude-Anbindung (einmal, im Terminal):\n  " + r["mcp"])
    print("\nPrüfen: 2ndbrain selbsttest")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
