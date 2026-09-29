#!/usr/bin/env python3
"""referenzlauf.py - prüft, ob ein Umbau das Verhalten der Engine auf dem echten Vault ändert.

Entwickler-Werkzeug: liegt nur im Code-Repo (engine/tools), nicht im installierten Paket;
`2ndbrain referenz` gibt es nur bei einer Installation aus dem Code-Repo (`pip install -e engine`).

Vor einem Umbau, der das Verhalten NICHT ändern soll (z. B. Firmenwissen aus dem Code in die
Konfiguration verschieben), einen Schnappschuss speichern; danach vergleichen - mit dem Stichtag
des Schnappschusses. Jede Probe ruft dieselben Funktionen auf wie die Engine - nur lesend, ohne
Modell, ohne Schreibzugriff auf Notizen. Die Schnappschüsse enthalten Vault-Inhalte und liegen
deshalb bei den Daten (`.2ndbrain/daten/.referenz/`), nicht im Code.

Proben: ich · organisation · modell · texte · themen (jeder Termin-Titel -> Themen) ·
begriffe (Begriffs-Index) · glossar (Kandidaten nach Filter) · atlas (offene Kanon-Fragen,
wie sie im Chat stehen) · systemuebersicht (LikeC4-Text) · personen (Vornamen im Titel -> Personen).

    2ndbrain referenz --speichern vorher [--nur themen,atlas]
    2ndbrain referenz --vergleichen vorher      (Exit 1 bei Unterschieden)
    2ndbrain referenz --liste
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

# Entwickler-Werkzeug im Code-Repo: nutzt die Module der Engine aus dem Quelltext daneben
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "secondbrain"))

import vault_paths as vp

if not vp.VAULT_FOUND:
    sys.exit("[ABBRUCH] Kein Vault gefunden - im Vault-Ordner starten oder VAULT_DIR=<Vault> setzen.")

DIR = vp.DATA_DIR / ".referenz"
PROBES: dict = {}
MAX_SHOWN = 12


def probe(name: str):
    def reg(fn):
        PROBES[name] = fn
        return fn
    return reg


def _titles() -> list[tuple[str, dict, Path]]:
    """Titel aller Termin-Notizen (aktiv und archiviert) mit Frontmatter."""
    out = []
    for base in (vp.VAULT / "active-meetings", vp.VAULT / "archive" / "meetings"):
        for f in sorted(base.rglob("*.md")) if base.is_dir() else []:
            fm = vp.read_frontmatter(f) or {}
            if str(fm.get("type") or "meeting") != "meeting":
                continue
            out.append((str(fm.get("title") or f.stem), fm, f))
    return out


@probe("ich")
def _ich(day: date) -> dict:
    import beteiligte
    import playbook
    return {"beteiligte.me": beteiligte.me(), "playbook.SELF_SLUG": playbook.SELF_SLUG}


@probe("organisation")
def _organisation(day: date) -> dict:
    import mails as ie
    mails = {"jemand@lieferant.example", "a@b.de", "x@example.com"}
    for f in sorted(vp.CATEGORY_DIRS["people"].glob("*.md")):
        m = str((vp.read_frontmatter(f) or {}).get("email") or "").strip().lower()
        if "@" in m:
            mails.add(m)
    return {"interne_domains": sorted(vp.interne_domains()),
            "firma_aus_mail": {m: ie.company_from_email(m) for m in sorted(mails)}}


@probe("modell")
def _modell(day: date) -> dict:
    import modell
    c = modell.config()
    return {k: c.get(k) for k in ("url", "model", "timeout_s", "max_input_chars", "temperature", "retries")}


@probe("texte")
def _texte(day: date) -> dict:
    import kanon_vorschlaege as av
    import glossar
    import mcp_server
    return {"mcp.INSTRUCTIONS": mcp_server.INSTRUCTIONS,
            # der Prompt, den das Glossar-Modell wirklich bekommt (feste oder abgeleitete Beispiele)
            "glossar.PROMPT": glossar.build_prompt(glossar.configured_examples()
                                                   or glossar.derived_examples(glossar.corpus())),
            "atlas.EXT_HINT": av.EXT_HINT}


@probe("themen")
def _themen(day: date) -> dict:
    import vorbereiten
    import themen
    projects, aliases = vorbereiten.load_projects(), vp.alias_map()
    out = {}
    for title, fm, f in _titles():
        key = sorted(themen.note_keys(fm, f))[0] if themen.note_keys(fm, f) else ""
        out[f.relative_to(vp.VAULT).as_posix()] = {
            "titel": [s for s, _ in themen.title_topics(title, projects, aliases)],
            "vorschlag": [(s["slug"], round(s["score"], 3)) for s in
                          themen.suggest(title, fm, key, projects, aliases, note_path=f)]}
    return out


@probe("personen")
def _personen(day: date) -> dict:
    import beteiligte
    import themen
    me = beteiligte.me()
    return {f.relative_to(vp.VAULT).as_posix(): themen.title_person_candidates(title, me)
            for title, fm, f in _titles()}


@probe("begriffe")
def _begriffe(day: date) -> dict:
    import begriffsindex
    idx = begriffsindex.build()
    return {"quellen": idx["sources"],
            "eintraege": sorted(f"{e['norm']} -> {e['target']} ({e['kind']})" for e in idx["entries"])}


@probe("glossar")
def _glossar(day: date) -> dict:
    import glossar as gs
    kept, stats = gs.filter_candidates(gs.load_candidates(), gs.DEFAULT_MIN_COUNT)
    return {"behalten": sorted(kept), "verworfen_nach_grund": stats}


@probe("atlas")
def _atlas(day: date) -> dict:
    import kanon_vorschlaege as av
    qs, _note, _stats = av.collect(day)
    out = {}
    for i, q in enumerate(qs, 1):
        c = av.card(q, i, len(qs))          # was im Chat steht: Text, Belege, Hinweis, Knöpfe
        out[q["id"]] = {k: q.get(k) for k in ("art", "typ", "frage", "erklaerung", "vorschlag")} | {
            "karte": c["markdown"].split("\n"), "knoepfe": [f"{o.get('key')}: {o.get('label')}" for o in c["optionen"]]}
    return out


@probe("systemuebersicht")
def _systemuebersicht(day: date) -> dict:
    import systemuebersicht as su
    topics = su.load_topics()
    systems = su.load_systems(topics)
    su.place(systems, topics)
    rels = su.links(systems, topics)
    return {"c4": su.build_c4(systems, topics, rels, day.isoformat()).split("\n")}


def run(names: list[str], day: date) -> dict:
    res = {}
    for n in names:
        t0 = time.time()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                res[n] = PROBES[n](day)
        except Exception as e:                      # eine kaputte Probe kippt den Lauf nicht
            res[n] = {"FEHLER": f"{type(e).__name__}: {e}"}
        print(f"  {n:17} {time.time() - t0:5.1f} s", file=sys.stderr)
    return res


def _norm(x):
    return json.loads(json.dumps(x, ensure_ascii=False, default=str))


def diff(old, new, path: str = "") -> list[str]:
    """Unterschiede lesbar: Schlüssel neu/weg/anders, Texte als Zeilen-Diff."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k in sorted(set(old) | set(new)):
            p = f"{path}/{k}" if path else str(k)
            if k not in new:
                out.append(f"- weg: {p}")
            elif k not in old:
                out.append(f"+ neu: {p} = {json.dumps(new[k], ensure_ascii=False)[:160]}")
            elif old[k] != new[k]:
                out += diff(old[k], new[k], p)
        return out
    if isinstance(old, str) and isinstance(new, str) and ("\n" in old or len(old) > 120):
        lines = [x for x in difflib.unified_diff(old.split("\n"), new.split("\n"), lineterm="", n=0)
                 if not x.startswith(("---", "+++", "@@"))]
        return [f"~ {path}:"] + [f"    {x[:160]}" for x in lines]
    if isinstance(old, list) and isinstance(new, list) and all(isinstance(x, str) for x in old + new):
        lines = [x for x in difflib.unified_diff(old, new, lineterm="", n=0)
                 if not x.startswith(("---", "+++", "@@"))]
        return [f"~ {path}:"] + [f"    {x[:160]}" for x in lines]
    return [f"~ {path}: {json.dumps(old, ensure_ascii=False)[:150]}  ->  {json.dumps(new, ensure_ascii=False)[:150]}"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Referenzlauf: Verhalten der Engine auf dem echten Vault festhalten")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--speichern", metavar="NAME")
    g.add_argument("--vergleichen", metavar="NAME")
    g.add_argument("--liste", action="store_true")
    ap.add_argument("--nur", help="nur diese Proben, komma-getrennt: " + ",".join(PROBES))
    args = ap.parse_args(argv)
    if args.liste:
        for f in sorted(DIR.glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            print(f"  {f.stem:20} {d['erstellt']}  Stichtag {d['stichtag']}  {', '.join(d['proben'])}")
        return 0
    names = [n.strip() for n in args.nur.split(",")] if args.nur else list(PROBES)
    unknown = [n for n in names if n not in PROBES]
    if unknown:
        print(f"Unbekannte Proben: {', '.join(unknown)}", file=sys.stderr)
        return 2
    if args.speichern:
        day = date.today()
        snap = {"erstellt": datetime.now().isoformat(timespec="seconds"), "stichtag": day.isoformat(),
                "proben": _norm(run(names, day))}
        DIR.mkdir(parents=True, exist_ok=True)
        (DIR / f"{args.speichern}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1),
                                                    encoding="utf-8", newline="\n")
        broken = [n for n, v in snap["proben"].items() if isinstance(v, dict) and "FEHLER" in v]
        print(f"Referenz „{args.speichern}“ gespeichert: {len(names)} Proben"
              + (f" – FEHLER in {', '.join(broken)}" if broken else ""))
        return 1 if broken else 0
    path = DIR / f"{args.vergleichen}.json"
    if not path.is_file():
        print(f"Keine Referenz „{args.vergleichen}“ (--liste)", file=sys.stderr)
        return 2
    snap = json.loads(path.read_text(encoding="utf-8"))
    day = date.fromisoformat(snap["stichtag"])        # gleicher Stichtag wie beim Speichern
    names = [n for n in names if n in snap["proben"]]
    now = _norm(run(names, day))
    changed = 0
    for n in names:
        d = diff(snap["proben"][n], now[n])
        if d:
            changed += 1
            print(f"\n✗ {n}: {len(d)} Unterschied(e)")
            for line in d[:MAX_SHOWN]:
                print("  " + line)
            if len(d) > MAX_SHOWN:
                print(f"  … und {len(d) - MAX_SHOWN} weitere")
        else:
            print(f"✓ {n}: gleich")
    print(f"\n{len(names) - changed} von {len(names)} Proben gleich.")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
