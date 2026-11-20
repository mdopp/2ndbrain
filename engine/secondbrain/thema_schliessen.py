#!/usr/bin/env python3
"""thema_schliessen.py - ein Thema abschliessen (oder wieder oeffnen), mit seinen offenen Punkten.

Ein Projekt ist fertig, ein Vorhaben gestrichen - bisher blieb das Thema mit seinen Punkten stehen,
bis jeder einzeln abgehakt war. Abschliessen heisst hier:

  - je offenem Punkt des Themas (auf seiner Seite und in Termin-Notizen) eine Entscheidung:
    erledigt, verworfen oder ans Dach-Thema umhaengen - mit dem Grund als Unterpunkt an der Quelle
  - das Thema bekommt `status: done`, `abgeschlossen:` (Datum), `abschluss_grund:`; Fokus-Rang und
    naechster Schritt fallen weg; im Event Log steht "[MILESTONE] Thema abgeschlossen: <Grund>"
  - Unterthemen werden angeboten, aber nur mit abgeschlossen, wenn man sie nennt

Ein abgeschlossenes Thema bleibt als Seite stehen (nichts wird geloescht) und faellt aus Heute,
Radar, Lagebild, Rollen und Themen-Verzeichnis. Wieder oeffnen setzt `status: active` zurueck; die
dabei geschlossenen Punkte bleiben geschlossen (einzeln oeffnen: `[x]`/`[-]` zu `[ ]`).

    2ndbrain thema-schliessen SLUG                 Vorschau als JSON: Punkte mit Vorschlag, Unterthemen
    2ndbrain thema-schliessen SLUG --anwenden      {"grund": "...", "punkte": {"pfad:zeile": aktion},
                                                    "sonst": "verworfen", "unterthemen": ["slug"]} von stdin
    2ndbrain thema-schliessen SLUG --oeffnen
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aendern
import aufgaben as tk
import vault_paths as vp

DONE = "done"
DACH = "dach"
WAHL = (aendern.ERLEDIGT, aendern.VERWORFEN, DACH)


def abgeschlossen(fm: dict) -> bool:
    """Ist das Thema abgeschlossen? Die eine Stelle, die das Frontmatter dafuer liest."""
    return str(fm.get("status") or "").strip().casefold() in (DONE, "closed", "abgeschlossen")


def abgeschlossene() -> set[str]:
    """Slugs aller abgeschlossenen Themen."""
    if not vp.PROJECTS_DIR.is_dir():
        return set()
    return {f.stem for f in vp.PROJECTS_DIR.glob("*.md") if abgeschlossen(vp.read_frontmatter_head(f))}


def _slug(v) -> str:
    s = str(v or "").strip().strip("'\"")
    if s.startswith("[["):
        s = s[2:].split("]]")[0].split("|")[0].split("#")[0]
    return s.strip()


def _kopf(slug: str) -> dict | None:
    f = vp.project_path(slug)
    return vp.read_frontmatter_head(f) if f.is_file() else None


def _unterthemen(slug: str) -> list[str]:
    return [f.stem for f in sorted(vp.PROJECTS_DIR.glob("*.md"))
            if _slug(vp.read_frontmatter_head(f).get("parent")) == slug]


def _punkte(slug: str) -> list[tk.Task]:
    return [t for t in tk.scan() if t.is_open and slug in t.topics and t.path and t.line is not None]


def vorschau(slug: str) -> dict:
    fm = _kopf(slug)
    if fm is None:
        return {"ok": False, "grund": f"Das Thema „{slug}“ gibt es nicht."}
    names = tk.Names()
    ich = vp.ich()
    dach = _slug(fm.get("parent"))
    dach = dach if dach and vp.project_path(dach).is_file() and not abgeschlossen(_kopf(dach) or {}) else ""
    punkte = []
    for t in _punkte(slug):
        # Vorschlag: was niemand geprueft hat oder eine Frage war, faellt weg; das Uebrige ist mit dem
        # Thema erledigt - man aendert, was nicht stimmt.
        vorschlag = aendern.VERWORFEN if t.pruefen or t.kind == tk.KIND_QUESTION else aendern.ERLEDIGT
        punkte.append({"id": f"{t.path}:{t.line}", "path": t.path, "line": t.line, "text": t.text,
                       "person": names.person(t.owner) or t.owner if t.owner else (t.owner_raw or ""),
                       "meiner": bool(ich and t.owner == ich), "frist": t.due or "", "seit": t.created or "",
                       "frage": t.kind == tk.KIND_QUESTION, "altbestand": t.pruefen, "vorschlag": vorschlag})
    unter = []
    for s in _unterthemen(slug):
        k = _kopf(s) or {}
        if not abgeschlossen(k):
            unter.append({"slug": s, "titel": str(k.get("title") or s), "offen": len(_punkte(s))})
    return {"ok": True, "slug": slug, "titel": str(fm.get("title") or slug), "abgeschlossen": abgeschlossen(fm),
            "dach": dach, "dach_titel": names.topic(dach) or dach if dach else "", "punkte": punkte, "unterthemen": unter}


def schliessen(slug: str, grund: str, punkte: dict[str, str] | None = None, *, sonst: str = aendern.VERWORFEN,
               unterthemen: list[str] | None = None, heute: date | None = None, _tiefe: int = 0) -> dict:
    """Das Thema abschliessen. `punkte`: {"pfad:zeile": erledigt | verworfen | dach}; was nicht genannt
    ist, bekommt `sonst`. Unterthemen in `unterthemen` werden mit demselben Grund mit abgeschlossen."""
    heute = heute or date.today()
    v = vorschau(slug)
    if not v["ok"]:
        return v
    if v["abgeschlossen"]:
        return {"ok": False, "grund": f"„{v['titel']}“ ist schon abgeschlossen."}
    grund = " ".join(str(grund or "").split())
    if not grund:
        return {"ok": False, "grund": "Es fehlt der Grund – ein Satz, warum das Thema abgeschlossen ist."}
    sonst = sonst if sonst in WAHL else aendern.VERWORFEN
    punkte = punkte or {}
    aenderungen = []
    for p in v["punkte"]:
        wahl = punkte.get(p["id"], sonst)
        wahl = wahl if wahl in WAHL else sonst
        if wahl == DACH and not v["dach"]:
            wahl = aendern.VERWORFEN
        a = {"path": p["path"], "line": p["line"], "text": p["text"], "hinweis": grund,
             "aktion": aendern.UMHAENGEN if wahl == DACH else wahl}
        if wahl == DACH:
            a.update({"thema_von": slug, "thema_nach": v["dach"]})
        aenderungen.append(a)
    getan = aendern.punkte_aendern(aenderungen, heute=heute, woher=f"Thema „{v['titel']}“ abgeschlossen")
    vp.update_frontmatter(vp.project_path(slug), {"status": DONE, "abgeschlossen": heute.isoformat(),
                                                  "abschluss_grund": grund, "last_updated": heute.isoformat()},
                          remove=("fokus", "naechster_schritt"))
    aendern.log_eintrag(slug, "MILESTONE", f"Thema abgeschlossen: {grund}", heute=heute)
    je = {k: sum(1 for a in getan if a["aktion"] == k) for k in (aendern.ERLEDIGT, aendern.VERWORFEN, aendern.UMHAENGEN)}
    mit = []
    for s in unterthemen or []:
        if _tiefe < 8 and s in {u["slug"] for u in v["unterthemen"]}:
            r = schliessen(s, grund, sonst=sonst if sonst != DACH else aendern.VERWORFEN, heute=heute,
                           unterthemen=_unterthemen(s), _tiefe=_tiefe + 1)
            if r.get("ok"):
                mit += [s, *r["unterthemen"]]
                for k in je:
                    je[k] += r["punkte"][k]
    if _tiefe == 0:
        aendern.berichten(f"Thema abgeschlossen: {v['titel']}", getan, heute=heute,
                          weitere=[f"Grund: {grund}"] + ([f"Mit abgeschlossen: {', '.join(f'[[{s}]]' for s in mit)}"] if mit else []))
        vp.invalidate_entity_caches()
    return {"ok": True, "slug": slug, "titel": v["titel"], "punkte": je, "unterthemen": mit,
            "nicht_geaendert": len(aenderungen) - len(getan)}


def oeffnen(slug: str, *, heute: date | None = None) -> dict:
    heute = heute or date.today()
    fm = _kopf(slug)
    if fm is None:
        return {"ok": False, "grund": f"Das Thema „{slug}“ gibt es nicht."}
    if not abgeschlossen(fm):
        return {"ok": False, "grund": "Das Thema ist nicht abgeschlossen."}
    vp.update_frontmatter(vp.project_path(slug), {"status": "active", "last_updated": heute.isoformat()},
                          remove=("abgeschlossen", "abschluss_grund"))
    aendern.log_eintrag(slug, "STATUS", "Thema wieder geöffnet", heute=heute)
    vp.invalidate_entity_caches()
    return {"ok": True, "slug": slug, "titel": str(fm.get("title") or slug)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ein Thema abschließen oder wieder öffnen")
    ap.add_argument("slug")
    ap.add_argument("--anwenden", action="store_true", help="JSON {grund, punkte, sonst, unterthemen} von stdin")
    ap.add_argument("--oeffnen", action="store_true")
    args = ap.parse_args(argv)
    if not (args.anwenden or args.oeffnen):
        print(json.dumps(vorschau(args.slug), ensure_ascii=False))
        return 0
    import auto                           # dieselbe Sperre wie die Automatik (die schreibt dieselben Dateien)
    if not auto.acquire_lock():
        print(json.dumps({"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."}, ensure_ascii=False))
        return 1
    try:
        if args.oeffnen:
            r = oeffnen(args.slug)
        else:
            try:
                d = json.loads(sys.stdin.read() or "{}")
            except ValueError:
                d = None
            r = ({"ok": False, "grund": "Erwartet wird JSON {grund, punkte, sonst, unterthemen} von stdin."}
                 if not isinstance(d, dict) else
                 schliessen(args.slug, str(d.get("grund") or ""), d.get("punkte") if isinstance(d.get("punkte"), dict) else None,
                            sonst=str(d.get("sonst") or aendern.VERWORFEN),
                            unterthemen=[str(s) for s in d.get("unterthemen") or []] if isinstance(d.get("unterthemen"), list) else None))
    finally:
        auto.release_lock()
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
