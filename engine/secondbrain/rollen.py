#!/usr/bin/env python3
"""rollen.py - meine Rolle je Thema: fuehre ich es, bin ich beteiligt, beobachte ich nur?

Nicht jedes Thema, in dessen Terminen man sitzt, fuehrt man. Die Rolle entscheidet, wessen offene
Punkte man nachhaelt:

  fuehre      ich fuehre das Thema: alle offenen Punkte, auch die der anderen (Nachfassen)
  beteiligt   ich arbeite mit: nur meine eigenen Punkte; die der anderen haelt jemand anderes nach
  beobachte   ich will den Stand kennen: keine Punkte anderer - Stand, Entscheidungen und Risiken bleiben

Die eigenen Punkte sieht man immer. Die Rolle steht im Frontmatter des Themas (`meine_rolle:`); ein
Unterthema ohne eigene Angabe erbt die seines Dachs, ohne jede Angabe gilt `fuehre` (wie bisher).
Punkte bleiben in ihrer Notiz stehen - die Rolle blendet nur aus: in "Nachfassen", im Lagebild, in der
Vorbereitung eines Jourfix.

Der Vorschlag rechnet der Code aus dem, was im Vault steht (kein Modell):
  fuehre      Fokus-Thema, `verantwortlich` bin ich, oder mindestens VORSCHLAG_ANTEIL der Punkte sind meine
  beobachte   ich hatte dort nie einen eigenen Punkt
  beteiligt   sonst

    2ndbrain rollen                    Tabelle: Thema, Rolle, Vorschlag mit Grund (--json)
    2ndbrain rollen --uebernehmen      die Vorschlaege fuer alle Themen ohne Rolle eintragen (--dry-run)
    2ndbrain rollen --setzen           {"slug": "fuehre" | "beteiligt" | "beobachte" | ""} von stdin eintragen
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import thema_schliessen
import vault_paths as vp

FUEHRE, BETEILIGT, BEOBACHTE = "fuehre", "beteiligt", "beobachte"
ROLLEN = (FUEHRE, BETEILIGT, BEOBACHTE)
ROLLEN_TEXT = {FUEHRE: "führe ich", BETEILIGT: "bin beteiligt", BEOBACHTE: "beobachte ich"}
FELD = "meine_rolle"
VORSCHLAG_ANTEIL = 0.4       # ab diesem Anteil eigener Punkte fuehrt man das Thema vermutlich
VORSCHLAG_MIN_PUNKTE = 5     # ... wenn es ueberhaupt genug Punkte gibt, um das zu sagen


def _slug(v) -> str:
    s = str(v or "").strip().strip("'\"")
    if s.startswith("[["):
        s = s[2:].split("]]")[0].split("|")[0].split("#")[0]
    return s.strip()


def _themen() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in sorted(vp.PROJECTS_DIR.glob("*.md")) if vp.PROJECTS_DIR.is_dir() else []:
        fm = vp.read_frontmatter_head(f)
        rolle = str(fm.get(FELD) or "").strip().casefold()
        out[f.stem] = {"titel": str(fm.get("title") or f.stem), "eigene": rolle if rolle in ROLLEN else "",
                       "parent": _slug(fm.get("parent")), "fokus": fm.get("fokus") not in (None, "", False),
                       "verantwortlich": _slug(fm.get("verantwortlich")), "pfad": f}
    return out


def lade(themen: dict[str, dict] | None = None) -> dict[str, str]:
    """{slug: rolle} fuer alle Themen - die eigene Angabe, sonst die des naechsten Dachs, sonst `fuehre`."""
    themen = themen if themen is not None else _themen()
    out: dict[str, str] = {}
    for slug in themen:
        cur, gesehen = slug, set()
        rolle = ""
        while cur in themen and cur not in gesehen and not rolle:
            gesehen.add(cur)
            rolle = themen[cur]["eigene"]
            cur = themen[cur]["parent"]
        out[slug] = rolle or FUEHRE
    return out


def sichtbar(t: tk.Task, ich: str, rollen: dict[str, str], immer: frozenset[str] | set[str] = frozenset()) -> bool:
    """Gehoert der Punkt in meine Sichten? Meine eigenen immer, ebenso die der Personen in `immer`
    (wer an mich berichtet: deren Punkte halte ich als Vorgesetzter nach, gleich in welchem Thema);
    die anderer nur, wenn ich (eines) ihrer Themen fuehre. Ein Punkt ohne Thema oder in einem Thema
    ohne Seite bleibt sichtbar."""
    if (ich and t.owner == ich) or (t.owner and t.owner in immer):
        return True
    bekannte = [rollen[s] for s in t.topics if s in rollen]
    return not bekannte or FUEHRE in bekannte


def meine_berichte(ich: str | None = None) -> set[str]:
    """Wer (ueber die Berichtslinie) an mich berichtet - leer, wenn die Organisation das nicht hergibt."""
    try:
        import organisation
        ich = vp.ich() if ich is None else ich
        return set(organisation.lade().alle_berichte(ich)) if ich else set()
    except Exception:                                # noqa: BLE001 - ohne Organisation gilt nur die Rolle
        return set()


def sichtbare(tasks: list[tk.Task], ich: str | None = None, rollen: dict[str, str] | None = None,
              immer: set[str] | None = None) -> list[tk.Task]:
    ich = vp.ich() if ich is None else ich
    rollen = lade() if rollen is None else rollen
    immer = meine_berichte(ich) if immer is None else immer
    return [t for t in tasks if sichtbar(t, ich, rollen, immer)]


def vorschlaege() -> list[dict]:
    """Je Thema: {slug, titel, rolle (gilt), eigene (eingetragen), vorschlag, grund, punkte, meine}."""
    ich = vp.ich()
    themen = _themen()
    gilt = lade(themen)
    alle: dict[str, int] = {}
    meine: dict[str, int] = {}
    for t in tk.scan():
        if t.kind != tk.KIND_TASK:
            continue
        for s in t.topics[:1]:
            alle[s] = alle.get(s, 0) + 1
            if ich and t.owner == ich:
                meine[s] = meine.get(s, 0) + 1
    out = []
    zu = thema_schliessen.abgeschlossene()
    for slug, th in themen.items():
        if slug in zu:                                   # abgeschlossen: keine Rolle mehr zu vergeben
            continue
        n, m = alle.get(slug, 0), meine.get(slug, 0)
        if th["fokus"]:
            v, grund = FUEHRE, "Fokus-Thema"
        elif ich and th["verantwortlich"] == ich:
            v, grund = FUEHRE, "du bist als verantwortlich eingetragen"
        elif n >= VORSCHLAG_MIN_PUNKTE and m / n >= VORSCHLAG_ANTEIL:
            v, grund = FUEHRE, f"{m} von {n} Punkten sind deine"
        elif m == 0:
            v, grund = BEOBACHTE, (f"{n} Punkte, keiner davon deiner" if n else "keine Punkte")
        else:
            v, grund = BETEILIGT, f"{m} von {n} Punkten sind deine"
        out.append({"slug": slug, "titel": th["titel"], "rolle": gilt[slug], "eigene": th["eigene"],
                    "geerbt": not th["eigene"] and gilt[slug] != FUEHRE, "vorschlag": v, "grund": grund,
                    "punkte": n, "meine": m, "parent": th["parent"]})
    out.sort(key=lambda r: (-r["punkte"], r["titel"].casefold()))
    return out


def setzen(angaben: dict[str, str], *, dry_run: bool = False) -> dict:
    """Rollen eintragen: {slug: rolle}; "" nimmt die eigene Angabe heraus (dann gilt wieder das Dach)."""
    themen = _themen()
    geaendert, unbekannt = [], []
    for slug, rolle in angaben.items():
        rolle = str(rolle or "").strip().casefold()
        if slug not in themen or (rolle and rolle not in ROLLEN):
            unbekannt.append(slug)
            continue
        if themen[slug]["eigene"] == rolle:
            continue
        if not dry_run:
            if rolle:
                vp.update_frontmatter(themen[slug]["pfad"], {FELD: rolle})
            else:
                vp.update_frontmatter(themen[slug]["pfad"], {}, remove=(FELD,))
        geaendert.append(slug)
    return {"ok": not unbekannt, "geaendert": geaendert, "unbekannt": unbekannt}


def uebernehmen(*, dry_run: bool = False) -> dict:
    """Die Vorschlaege fuer alle Themen eintragen, die noch keine eigene Rolle haben."""
    return setzen({v["slug"]: v["vorschlag"] for v in vorschlaege() if not v["eigene"]}, dry_run=dry_run)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Meine Rolle je Thema")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--uebernehmen", action="store_true", help="Vorschläge für Themen ohne Rolle eintragen")
    ap.add_argument("--setzen", action="store_true", help="Rollen als JSON {slug: rolle} von stdin eintragen")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.uebernehmen or args.setzen:
        import auto                       # dieselbe Sperre wie die Automatik (die schreibt Themen-Dateien)
        if not args.dry_run and not auto.acquire_lock():
            print(json.dumps({"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."}, ensure_ascii=False))
            return 1
        try:
            if args.setzen:
                try:
                    angaben = json.loads(sys.stdin.read() or "{}")
                except ValueError:
                    angaben = None
                r = (setzen(angaben, dry_run=args.dry_run) if isinstance(angaben, dict)
                     else {"ok": False, "grund": "Erwartet wird JSON {slug: rolle} von stdin."})
            else:
                r = uebernehmen(dry_run=args.dry_run)
        finally:
            if not args.dry_run:
                auto.release_lock()
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r.get("ok") else 1
    rows = vorschlaege()
    if args.json:
        print(json.dumps({"ok": True, "ich": vp.ich(), "themen": rows}, ensure_ascii=False))
        return 0
    for r in rows:
        gilt = ROLLEN_TEXT[r["rolle"]] + ("" if r["eigene"] else " (nicht eingetragen)")
        print(f"{r['titel'][:38]:40} {gilt:32} Vorschlag: {ROLLEN_TEXT[r['vorschlag']]} – {r['grund']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
