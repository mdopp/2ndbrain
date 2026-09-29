#!/usr/bin/env python3
"""wissen.py - haelt Begriffs-Index, Kontext-Verzeichnis und Glossar aktuell (Automatik-Schritt `wissen`).

Jeder Teil laeuft nur, wenn sich seine Quellen geaendert haben - sonst kostet der Schritt nur
ein paar `stat`-Aufrufe. So arbeiten Nachbereiten und die Themen-Vorschlaege fuer Termine immer
mit einem aktuellen Begriffs-Index:

  Begriffs-Index       entities/, Kanon, LikeC4-Modell -> .2ndbrain/daten/term_index.json
  Kontext-Verzeichnis  Kanon -> entities/contexts/_index.md
  Glossar              Notizen (aktive Termine, Archiv) -> glossar.py. Das Modell ordnet je Lauf
                       hoechstens GLOSSAR_JE_LAUF Begriffe ein (eine Portion - Chat und Nachbereiten
                       warten sonst); ein Rest kommt im naechsten Lauf dran. Ohne Modell wartet es.

Die Arbeit selbst machen begriffsindex.py, kontexte.py und glossar.py; hier steht nur, wann.
Von Hand gestartet nimmt es dieselbe Sperre wie die Automatik - nie zwei Laeufe am Glossar.

    2ndbrain wissen [--force] [--dry-run] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

STATE = vp.DATA_DIR / ".wissen_state.json"
GLOSSAR_JE_LAUF = 8


def _sig(roots: list[Path | None], patterns: tuple[str, ...] = ("*.md",)) -> str:
    """Anzahl und juengste Aenderung der Dateien - billig, nur `stat`."""
    n, latest = 0, 0.0
    for root in roots:
        if root is None or not root.exists():
            continue
        files = [root] if root.is_file() else [f for pat in patterns for f in root.rglob(pat)]
        for f in files:
            try:
                latest = max(latest, f.stat().st_mtime)
                n += 1
            except OSError:
                continue
    return f"{n}:{latest:.0f}"


def _kanon_root() -> Path | None:
    import kanon
    k = kanon.konfig()
    p = k.get("pfad")
    if not p:
        return None
    return Path(p) / "canon" if k.get("format") == "domain-atlas" else Path(p)


def _load() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def aktualisieren(*, llm_ok: bool, dry_run: bool = False, force: bool = False) -> dict:
    """Was sich geaendert hat, nachziehen. Rueckgabe: detail (Liste), changed (Anzahl)."""
    import kontexte as ci
    import begriffsindex as ti
    state = _load()
    detail, changed = [], 0
    kanon_sig = _sig([_kanon_root()], ("*.yaml", "*.yml"))
    # 1. Begriffs-Index
    s = "|".join((_sig([vp.ENTITIES_DIR]), kanon_sig, _sig([vp.external_path("likec4_model")], ("*.c4",))))
    if force or state.get("begriffe") != s or not ti.INDEX_FILE.is_file():
        if not dry_run:
            idx = ti.build()
            ti.save(idx)
            ti._LOADED.clear()
            state["begriffe"] = s
            detail.append(f"Begriffs-Index neu ({len(idx['entries'])} Einträge)")
        else:
            detail.append("Begriffs-Index würde neu gebaut")
        changed += 1
    # 2. Kontext-Verzeichnis
    if force or state.get("kontexte") != kanon_sig:
        contexts = ci.load_contexts()
        if contexts:
            content = ci.build_content(contexts)
            alt = ci.INDEX_PATH.read_text(encoding="utf-8") if ci.INDEX_PATH.is_file() else ""
            if content != alt:
                if not dry_run:
                    ci.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
                    ci.INDEX_PATH.write_text(content, encoding="utf-8", newline="\n")
                detail.append(f"Kontext-Verzeichnis neu ({len(contexts)} Kontexte)")
                changed += 1
        if not dry_run:
            state["kontexte"] = kanon_sig
    # 3. Glossar - nach neuen Notizen; ein Rest fuers Modell auch ohne neue Notizen
    notes = _sig([vp.VAULT / "active-meetings", vp.SOURCES_DIR])
    faellig = force or state.get("glossar") != notes or (llm_ok and state.get("glossar_offen"))
    if faellig:
        import glossar
        llm_call = None
        if llm_ok and not dry_run:
            import modell
            llm_call = modell.complete_json
        r = glossar.run(apply=not dry_run, llm_call=llm_call, limit=GLOSSAR_JE_LAUF)
        neu = r.get("vorschlag_created", 0) + r.get("atlas_created", 0)
        bearbeitet = sum(r.get(k, 0) for k in ("vorschlag_updated", "messwerte_updated", "atlas_updated",
                                               "schreibweise"))
        wartet = r.get("wartet_auf_modell", 0)
        eingeordnet = (min(GLOSSAR_JE_LAUF, wartet) - r.get("ohne_vorschlag", 0)) if llm_call else 0
        offen = max(0, wartet - max(0, eingeordnet))
        if not dry_run:
            state["glossar"] = notes
            state["glossar_offen"] = offen
        teile = [f"{neu} neue Einträge" if neu else "", f"{bearbeitet} aktualisiert" if bearbeitet else "",
                 f"{offen} warten aufs Modell" if offen else ""]
        detail.append("Glossar: " + (", ".join(t for t in teile if t) or "unverändert"))
        changed += bearbeitet
    if not dry_run:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return {"detail": detail or ["nichts zu tun"], "changed": changed}


def main(argv: list[str] | None = None) -> int:
    vp.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="Begriffs-Index, Kontext-Verzeichnis und Glossar nachziehen")
    ap.add_argument("--force", action="store_true", help="alles neu, auch ohne Aenderung")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    import auto          # dieselbe Sperre wie die Automatik - nie zwei Laeufe am Glossar
    import modell
    ok, _reason = modell.available()
    if not auto.acquire_lock():
        print("[ABBRUCH] Die Automatik läuft gerade - gleich noch einmal.", file=sys.stderr)
        return 1
    try:
        r = aktualisieren(llm_ok=ok, dry_run=args.dry_run, force=args.force)
    finally:
        auto.release_lock()
    print(json.dumps(r, ensure_ascii=False) if args.json else "\n".join(r["detail"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
