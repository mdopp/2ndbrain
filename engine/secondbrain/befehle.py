#!/usr/bin/env python3
"""befehle.py - Befehlszeile der Engine (`2ndbrain <befehl>` / `python -m secondbrain <befehl>`).

Das Plugin startet die Engine ueber diese Befehle (Automatik, Nachbereiten, Thema, Offene Fragen,
Einrichten); man kann sie auch im Terminal nutzen. Jeder Befehl startet sein Modul als eigenen
Prozess - so bleibt ein Fehler in einem Werkzeug auf dieses beschraenkt. Fachlogik steht hier
bewusst nicht: nur die Befehlsliste (GRUPPEN, zugleich die Hilfe) und die Sonderfaelle version,
test, mcp und plugin-vergleich.

    2ndbrain help                     # alle Befehle
    2ndbrain <befehl> [argumente]     # im Vault-Ordner oder mit VAULT_DIR=<Vault>
"""
import os
import subprocess
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
# Das Code-Repo (Tests, Entwickler-Werkzeuge, Plugin-Quelle) - nur bei `pip install -e engine`
REPO = ENGINE_DIR.parents[1] if (ENGINE_DIR.parents[1] / "plugin" / "src").is_dir() else None
TOOLS_DIR = REPO / "engine" / "tools" if REPO else None

# Alle Unterprozesse im UTF-8-Modus starten (Windows-Pipes sind sonst cp1252;
# Ausgaben mit '→' oder Umlauten brechen dort ab). Erbt jedes subprocess.run.
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Befehl -> (Modul, feste Argumente vorweg, Hilfetext). Gruppen in der Reihenfolge der Hilfe.
GRUPPEN = [
    ("Automatik und Einsortieren", [
        ("auto", "auto", [], "alle Schritte in Reihenfolge, idempotent, mit Sperre\n"
                              "(--only nachbereiten,stand | --force | --dry-run | --json | --note <pfad>)"),
        ("einlesen", "einlesen", [], "Kalender, Mails, Dokumente -> Notizen in inbox/ (--dry-run | --no-calendar |\n"
                                      "--source calendar|emails|containers|documents|refill)"),
        ("einarbeiten", "einarbeiten", [], "Eingang mit dem lokalen Modell einsortieren: Themen-Log, Aufgaben,\n"
                                            "Personen, Archiv (--probelauf | --max N | --rueckgaengig <notiz>)"),
        ("vorbereiten", "vorbereiten", [], "Termine vorbereiten (--today | --days N | --dry-run | --json)"),
        ("nachbereiten", "nachbereiten", [], "Termine nachbereiten (--path <datei> | --since YYYY-MM-DD | --dry-run |\n"
                                              "--json); ohne Modell ein einfacher Rueckfall"),
        ("nacherfassen", "nacherfassen", [], "Termin nacherfassen (--note <pfad> --stdin | --entfallen | --wieder-offen |\n"
                                              "--undo | --info) - das Plugin erfasst selbst, hier Rueckgaengig"),
        ("altbestand", "altbestand", [], "Altbestand je Thema und naechster Termin (--settle | --geprueft <slug>)"),
        ("archivieren", "archivieren", [], "erledigte Termin-Notizen abschliessen und nach archive/meetings/ (--dry-run | --json)"),
        ("protokolle", "protokolle", [], "Protokolle im Eingang ihrem Termin zuordnen, unklar -> Rueckfrage (--dry-run | --json)"),
        ("schreibweisen", "schreibweisen", [], "Namen sauber: --liste (Startliste), --antworten, --bereinigen [--vorschau], --text"),
        ("stand", "stand", [], "Stand-Block je Thema (--topic <slug> --force --no-llm --dry-run --json)"),
        ("verdichten", "verdichten", [], "Themen schlank halten (Vorschau reports/verdichten.md; --apply)"),
        ("nachfuellen", "nachfuellen", [], "leere Notizen aus Anhaengen nachfuellen (pypdf, Texterkennung, kein Modell)"),
    ]),
    ("Wissen", [
        ("wissen", "wissen", [], "Begriffs-Index, Kontext-Verzeichnis, Glossar nachziehen - nur was sich\n"
                                  "geaendert hat (--force alles; laeuft auch in der Automatik)"),
        ("glossar", "glossar", [], "Glossar: zaehlen, Kanon, Messwerte, Einordnung durch das Modell\n"
                                    "(Bericht; --apply schreibt; --no-llm | --limit N | --min-count N)"),
        ("begriffe", "begriffsindex", [], "Begriffs-Index bauen; --find \"<text>\" zeigt Begriffe und Themen-Kandidaten"),
        ("kontexte", "kontexte", [], "entities/contexts/_index.md aus dem Kanon (Kontexte, Subdomaenen, Nachrichten)"),
        ("kontext-systeme", "kontext_systeme", [], "welches System welchen Kontext umsetzt: Haken aus\n"
                                                    "reports/kontext-systeme.md uebernehmen, Liste neu (--dry-run | --json)"),
        ("aufloesen", "aufloesen", [], "\"<begriff>\" aufloesen: Kanon, Systemuebersicht, Vault (--json | --kind system)"),
        ("systemuebersicht", "systemuebersicht", [], "LikeC4-Modell und reports/systemuebersicht.md aus den System-Seiten"),
        ("kanon-vorschlaege", "kanon_vorschlaege", [], "Fragen an Kanon und Systemuebersicht (--review: Angekreuztes uebernehmen)"),
    ]),
    ("Termine, Themen, Personen", [
        ("thema", "themen", [], "Termin -> Thema: --note <pfad> --vorschlag | --set a,b [--reihe];\n"
                                 "--offen | --neu-berechnen [--apply]"),
        ("playbooks", "playbook", [], "Termin-Typen aus entities/meeting-playbooks/ auflisten"),
        ("reihen", "reihen", [], "Reihen (Gremien, Formate) auflisten (--derive schlaegt sie aus Terminen vor)"),
        ("beteiligte", "beteiligte", [], "Beteiligte je Thema berechnen (--topic --json)"),
        ("personen", "personen", [], "Ueberblick je Person erzeugen (--dry-run | --slug <person> | --json)"),
        ("thema-neu", "thema_anlegen", [], "\"<Name>\" [--keywords a,b]: Themen-Seite anlegen"),
        ("person-neu", "anlegen", ["people"], "\"<Name>\" [--aliases A,B] [--role \"...\"]: Person anlegen"),
        ("team-neu", "anlegen", ["teams"], "\"<Name>\": Team anlegen"),
        ("firma-neu", "anlegen", ["companies"], "\"<Name>\": Firma anlegen"),
        ("reihe-neu", "reihen", ["--neu"], "\"<Name>\" [--kind weekly] [--keywords a,b]: Reihe anlegen"),
        ("umbenennen", "umbenennen", [], "<alt> <neu>: vault-weit umbenennen (--dry-run)"),
        ("rueckfragen", "rueckfragen", [], "offene Rueckfragen (list | add | resolve)"),
    ]),
    ("Lesen - das Plugin rechnet selbst; diese Fassungen dienen dem Terminal", [
        ("aufgaben", "aufgaben", [], "offene Punkte (--open --owner <slug> --topic <slug> --json | --summary)"),
        ("risiken", "ampel", [], "Risiken aus dem Themen-Log (JSON)"),
        ("frage", "frage", [], "Frage-Modus des Chats (Offene Fragen), JSON von stdin"),
    ]),
    ("Einrichten und Pruefen", [
        ("einrichten", "einrichten", [], "Vault auf diesem Rechner einrichten: Python, Engine, fehlende Vorlagen,\n"
                                          "Pfade, Kalender, MCP (--nur-pruefen | --json)"),
        ("pfade", "einrichten", ["--pfade"], "Pfade, likec4-Befehl, Python und Version als JSON (fuer das Plugin)"),
        ("version", None, [], "Version der Engine (--json)"),
        ("mcp", None, [], "MCP-Server fuer Claude (stdio; --selftest)"),
        ("modell", "modell", [], "Modell-Server pruefen (--selftest | --config)"),
        ("selbsttest", "selbsttest", [], "Verdrahtung, Konventionen, Daten pruefen"),
    ]),
    ("Entwickeln (nur mit dem Code-Repo, `pip install -e engine`)", [
        ("test", None, [], "Regressionstests"),
        ("referenz", "tools:referenzlauf", [], "Referenzlauf: --speichern NAME / --vergleichen NAME"),
        ("plugin-vergleich", None, [], "Plugin und Engine auf diesem Vault vergleichen (nur lesend, braucht Node)"),
        ("entdrahtung", "tools:entdrahtung", [], "Namen dieses Vaults im Code finden"),
        ("prompt-vergleich", "tools:prompt_vergleich", [], "glossar [--laeufe 2]: Prompt-Varianten mit dem Modell vergleichen"),
    ]),
]
BEFEHLE = {name: (modul, vorweg) for _, rows in GRUPPEN for name, modul, vorweg, _h in rows}
# Ohne Argument sinnvolle Vorgaben
VORGABE = {"rueckfragen": ["list"], "modell": ["--selftest"]}


def print_help() -> None:
    out = ["", "2ndBrain-Engine - Befehlszeile", "", "Verwendung:",
           "  2ndbrain <Befehl> [Argumente]          (oder: python -m secondbrain <Befehl>)",
           "  im Vault-Ordner oder mit VAULT_DIR=<Vault>"]
    for titel, rows in GRUPPEN:
        out += ["", titel]
        for name, _m, _v, hilfe in rows:
            first, *rest = hilfe.split("\n")
            out.append(f"  {name:18} {first}")
            out += [f"  {'':18} {r}" for r in rest]
    out += ["", "Konventionen",
            "  Eingang: inbox/ - Termine: active-meetings/ - Themen: entities/projects/ (Pfade: vault_paths.py)",
            "  Konfiguration, Chat-Rezepte und Daten des Vaults: .2ndbrain/ - der Code liegt nicht im Vault", ""]
    print("\n".join(out))


def _script(modul: str) -> Path | None:
    if modul.startswith("tools:"):
        return TOOLS_DIR / f"{modul[6:]}.py" if TOOLS_DIR else None
    return ENGINE_DIR / f"{modul}.py"


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print_help()
        return 0
    cmd, args = sys.argv[1].lower(), sys.argv[2:]
    py = sys.executable

    if cmd in ("version", "--version"):
        import json
        import einrichten
        v = einrichten.version()
        # aus dem Code-Repo installiert (pip install -e): das Plugin legt dann kein Wheel darueber
        quelltext = str(REPO / "engine") if REPO else None
        print(json.dumps({"version": v, "python": py, "quelltext": quelltext}) if "--json" in args else v)
        return 0
    if cmd not in BEFEHLE:
        print(f"[FEHLER] Unbekannter Befehl: '{cmd}'", file=sys.stderr)
        print_help()
        return 1

    if cmd == "test":
        # Beide Testdateien nacheinander; jeder Test baut sich einen eigenen Vault.
        if REPO is None:
            print("[ABBRUCH] Die Tests liegen im Code-Repo (engine/tests) - Engine von dort installieren "
                  "(`pip install -e engine`).", file=sys.stderr)
            return 1
        tests = REPO / "engine" / "tests"
        rc1 = subprocess.run([py, str(tests / "test_tools.py")] + args).returncode
        print()
        rc2 = subprocess.run([py, str(tests / "test_harness.py")] + args).returncode
        return rc1 or rc2

    import vault_paths as vp
    if not vp.VAULT_FOUND:
        print("[ABBRUCH] Kein Vault gefunden - im Vault-Ordner starten oder VAULT_DIR=<Vault> setzen.",
              file=sys.stderr)
        return 2
    # Unterprozesse finden denselben Vault, egal in welchem Ordner sie starten
    os.environ["VAULT_DIR"] = str(vp.VAULT)

    if cmd == "mcp":
        # MCP-Server fuer Claude (stdio): `claude mcp add ... -- <python> -m secondbrain mcp`
        import mcp_server
        return mcp_server.selftest() if "--selftest" in args else mcp_server.serve()

    if cmd == "plugin-vergleich":
        # Plugin (TypeScript) und Engine auf diesem Vault vergleichen - nur lesend
        import shutil
        npm = shutil.which("npm")
        if not npm or REPO is None:
            print("[ABBRUCH] Der Vergleich braucht das Code-Repo (plugin/) und Node.js (npm).", file=sys.stderr)
            return 1
        env = {**os.environ, "SB_VERGLEICH": "1", "SB_PYTHON": py, "SB_VAULT": str(vp.VAULT),
               "SB_TOOLS": str(TOOLS_DIR)}
        return subprocess.run([npm, "test"], cwd=REPO / "plugin", env=env).returncode

    modul, vorweg = BEFEHLE[cmd]
    script = _script(modul)
    if script is None or not script.is_file():
        print(f"[ABBRUCH] '{cmd}' gibt es nur im Code-Repo (engine/tools) - Engine von dort installieren.",
              file=sys.stderr)
        return 1
    if cmd == "umbenennen" and len(args) < 2:
        print("Verwendung: 2ndbrain umbenennen <alter-slug> <neuer-slug> [--dry-run]", file=sys.stderr)
        return 1
    if cmd in ("person-neu", "team-neu", "firma-neu", "reihe-neu", "thema-neu", "aufloesen") and not args:
        print(f"Verwendung: 2ndbrain {cmd} \"<Name>\" ...", file=sys.stderr)
        return 1
    return subprocess.run([py, str(script)] + vorweg + (args or VORGABE.get(cmd, []))).returncode


if __name__ == "__main__":
    sys.exit(main())
