#!/usr/bin/env python3
"""plugin_vergleich.py - liefert die Sicht der Engine auf den Vault als JSON fuer den Plugin-Vergleich.

Entwickler-Werkzeug: liegt nur im Code-Repo (engine/tools), nicht im installierten Paket.
Aufgerufen wird es vom Vergleichstest des Plugins (plugin/tests/vergleich.test.ts).

Aufgaben, Themen-Log, Risiken und Nacherfassen gibt es in beiden Teilen: die Engine braucht sie fuer
ihre eigenen Schritte, das Plugin rechnet damit selbst (am Desktop wie am Handy). Beide muessen auf
diesem Vault dasselbe liefern. Dieses Skript liest nur - Nacherfassen probiert es an Kopien in
einem temporaeren Ordner.

    2ndbrain plugin-vergleich      # startet `npm test` in plugin/ mit SB_VERGLEICH=1 (braucht Node)
    python engine/tools/plugin_vergleich.py [--teile aufgaben,log,risiken,nacherfassen] [--heute YYYY-MM-DD]
    python engine/tools/plugin_vergleich.py --fm-gleich < paare.json   # Frontmatter-Paare vergleichen
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

# Entwickler-Werkzeug im Code-Repo: nutzt die Module der Engine aus dem Quelltext daneben
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "secondbrain"))

import vault_paths as vp

if not vp.VAULT_FOUND:
    sys.exit("[ABBRUCH] Kein Vault gefunden - im Vault-Ordner starten oder VAULT_DIR=<Vault> setzen.")

ORDNER = ("active-meetings", "entities", "archive/meetings")


def frontmatter() -> dict[str, dict]:
    """Frontmatter aller Dateien, die die Vergleiche lesen - so, wie die Engine es sieht."""
    out = {}
    for rel in ORDNER:
        root = vp.VAULT / rel
        for f in root.rglob("*.md") if root.is_dir() else []:
            out[f.relative_to(vp.VAULT).as_posix()] = vp.read_frontmatter(f)
    return out


def aufgaben() -> list[dict]:
    import aufgaben as tk
    return [asdict(t) for t in tk.scan()]


def log() -> dict[str, list]:
    import frage
    import aufgaben as tk
    out = {}
    for d in (vp.PROJECTS_DIR, vp.FORUMS_DIR):
        for f in sorted(d.glob("*.md")) if d.is_dir() else []:
            rows = []
            for lineno, line in tk.section_lines(f.read_text(encoding="utf-8"), tk.EVENT_LOG_SECTION):
                m = frage._LOG_RE.match(line.strip())
                if m:
                    rows.append([m.group(1), m.group(2), m.group(3), lineno])
            out[f.relative_to(vp.VAULT).as_posix()] = rows
    return out


def risiken(today: date) -> dict:
    import ampel as he
    return {"fenster_tage": he.RISK_WINDOW_DAYS, "risiken": he.risk_rows(today)}


PROBE_TEXT = "Entscheidung: Rollout im Oktober  \n  Anna: Checkliste bis 2.10.\n\nOffen: Wer entscheidet?\n"


def nacherfassen(today: date) -> dict:
    """nacherfassen.py auf Kopien jeder aktiven Termin-Notiz - je Vorgang von der Originalfassung aus.
    Der echte Vault wird nicht beruehrt."""
    import shutil
    import tempfile
    import nacherfassen as cap
    ops = {"notizen": lambda p: cap.append_notes(p, PROBE_TEXT, today=today.isoformat()),
           "entfallen": lambda p: cap.set_entfallen(p, True, "Krank"),
           "wieder-offen": lambda p: cap.set_entfallen(p, False),
           "skip": lambda p: cap.set_skip(p, True),
           "no-skip": lambda p: cap.set_skip(p, False)}
    out = {}
    root = vp.VAULT / "active-meetings"
    tmpdir = Path(tempfile.mkdtemp(prefix="plugin-vergleich-"))
    try:
        for f in sorted(root.rglob("*.md")) if root.is_dir() else []:
            original = f.read_text(encoding="utf-8")
            res = {}
            for name, op in ops.items():
                tmp = tmpdir / "notiz.md"
                tmp.write_text(original, encoding="utf-8", newline="\n")
                r = op(tmp)
                res[name] = {"ok": bool(r.get("ok")), "grund": r.get("grund"), "text": tmp.read_text(encoding="utf-8")}
            out[f.relative_to(vp.VAULT).as_posix()] = {"original": original, "ops": res}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return {"probe_text": PROBE_TEXT, "notizen": out}


def fm_gleich(pairs: list) -> list[dict]:
    """Paare (Plugin, Engine): Rumpf gleich, Frontmatter inhaltlich gleich (leere Felder zaehlen
    nicht - die Engine entfernt sie beim Neuschreiben)."""
    diffs = []
    for i, (mine, theirs) in enumerate(pairs):
        fa, ba = vp.split_frontmatter(mine)
        fb, bb = vp.split_frontmatter(theirs)
        if vp.strip_empty(fa) != vp.strip_empty(fb) or ba != bb:
            keys = sorted(k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k))
            diffs.append({"nr": i, "felder": keys, "rumpf_gleich": ba == bb})
    return diffs


def main(argv: list[str] | None = None) -> int:
    vp.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="Engine-Sicht als JSON fuer den Plugin-Vergleich")
    ap.add_argument("--teile", default="aufgaben,log,risiken,nacherfassen")
    ap.add_argument("--heute", help="Stichtag (YYYY-MM-DD), sonst heute")
    ap.add_argument("--fm-gleich", action="store_true",
                    help="stdin: JSON-Liste von Paaren [Plugin-Text, Engine-Text] -> Abweichungen")
    args = ap.parse_args(argv)
    if args.fm_gleich:
        print(json.dumps(fm_gleich(json.loads(sys.stdin.buffer.read().decode("utf-8"))), ensure_ascii=False))
        return 0
    today = date.fromisoformat(args.heute) if args.heute else date.today()
    teile = {t.strip() for t in args.teile.split(",") if t.strip()}
    out: dict = {"heute": today.isoformat(), "vault": str(vp.VAULT), "frontmatter": frontmatter()}
    if "aufgaben" in teile:
        out["aufgaben"] = aufgaben()
    if "log" in teile:
        out["log"] = log()
    if "risiken" in teile:
        out["risiken"] = risiken(today)
    if "nacherfassen" in teile:
        out["nacherfassen"] = nacherfassen(today)
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
