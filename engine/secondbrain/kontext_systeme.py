#!/usr/bin/env python3
"""kontext_systeme.py - welches System setzt welchen Kontext des Domain Atlas um?

Die Zuordnung steht auf der System-Seite: `atlas_kontexte: [ctx-…]`. Daraus zeichnet der Chat im
Plugin unter dem Bild "Kontexte" die Software dahinter (Systeme, ihre Verbindungen, die
Atlas-Nachrichten auf die Systeme uebertragen). Geraten wird nicht: dieses Modul schlaegt vor,
du hakst ab.

Belege fuer einen Vorschlag:
  - Name      der Kontext traegt den Namen des Systems ("Rampen-Planer" <-> "Rampen Planer")
  - Daten     Migrationstabellen im Atlas (`canon/migration-tables/`): die Daten des Kontexts liegen
              heute im System (`sourceSystem`), geplant ist ein anderes ("Eigentuemer: A → geplant: B")
  - Team      das Team, das den Kontext besitzt, betreut auch das System (`owner_team`)

Liste zum Abhaken: `reports/kontext-systeme.md`. Haken = zugeordnet, Haken weg = Zuordnung weg; eine
eigene Zeile `- [x] [[system]]` unter einem Kontext ordnet ein System ohne Vorschlag zu. Die Automatik
uebernimmt die Haken im Schritt `wissen`.

    2ndbrain kontext-systeme                  # Haken uebernehmen, Liste neu schreiben
    2ndbrain kontext-systeme --dry-run        # nur zeigen, was sich aendern wuerde
    2ndbrain kontext-systeme --json           # Vorschlaege als JSON
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

BERICHT = vp.VAULT / "reports" / "kontext-systeme.md"
FELD = "atlas_kontexte"
_MARKE = re.compile(r"<!-- ks:([^:\s]+):([^:\s]+):([01]) -->")
_LINK = re.compile(r"\[\[([^\]|#]+)")
_GEPLANT = re.compile(r"geplant:\s*([^\n\r]+)", re.I)


def _norm(s: str) -> str:
    t = str(s or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _slug(v) -> str:
    m = _LINK.search(str(v or ""))
    return (m.group(1) if m else str(v or "")).strip().strip("'\"").split("/")[-1]


def _liste(v) -> list:
    return v if isinstance(v, list) else ([v] if v else [])


# ------------------------------------------------------------------ Daten

def systeme() -> dict[str, dict]:
    """System-Seiten: {slug: {name, namen (normalisiert), team, kontexte, pfad}}."""
    out = {}
    for p in sorted(vp.SYSTEMS_DIR.glob("*.md")) if vp.SYSTEMS_DIR.is_dir() else []:
        if p.stem.startswith("ctx-"):
            continue
        fm = vp.read_frontmatter(p)
        name = str(fm.get("name") or p.stem)
        namen = {_norm(n) for n in [name, p.stem.replace("-", " "), *_liste(fm.get("aliases"))] if len(_norm(n)) >= 3}
        out[p.stem] = {"name": name, "namen": namen, "team": _slug(fm.get("owner_team")),
                       "kontexte": [str(x).strip() for x in _liste(fm.get(FELD)) if str(x).strip()], "pfad": p}
    return out


def _teams_im_vault(atlas_team: dict) -> set[str]:
    """Vault-Teams zu einem Atlas-Team: `team-halle` -> halle, halle-team; oder gleicher Name."""
    tid = str(atlas_team.get("id") or "")
    base = tid[5:] if tid.startswith("team-") else tid
    name = _norm(atlas_team.get("name") or "")
    out = set()
    for p in vp.TEAMS_DIR.glob("*.md") if vp.TEAMS_DIR.is_dir() else []:
        fm = vp.read_frontmatter(p)
        ids = {str(x) for x in _liste(fm.get("atlas_id"))}
        if p.stem in (base, f"{base}-team", f"team-{base}") or tid in ids or (name and _norm(fm.get("name")) == name):
            out.add(p.stem)
    return out


def _migration(root: Path | None) -> list[dict]:
    """Migrationstabellen: [{objekt, quelle (System-Name), geplant (Name oder "")}]."""
    d = root / "canon" / "migration-tables" if root else None
    if not d or not d.is_dir():
        return []
    import yaml
    out = []
    for f in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict) or not data.get("migratingToObjectRef"):
            continue
        m = _GEPLANT.search(str(data.get("description") or ""))
        geplant = re.split(r"[?,;(]", m.group(1))[0].strip() if m else ""
        out.append({"objekt": str(data["migratingToObjectRef"]), "quelle": str(data.get("sourceSystem") or ""),
                    "geplant": geplant})
    return out


def _passt(name: str, sys_: dict) -> bool:
    n = _norm(name)
    return bool(n) and n in sys_["namen"]


def vorschlaege() -> dict:
    """{kanon, kontexte: [{id, name, sd, vorschlaege: [{system, gruende}], zugeordnet: [system]}]}."""
    import kanon
    k = kanon.lade()
    if not k:
        return {"kanon": None, "kontexte": []}
    sys_ = systeme()
    obj_ctx = {str(o.get("id")): str(o.get("kontext") or "") for o in k.get("objekte") or []}
    tabellen: dict[tuple[str, str], list[str]] = {}
    for t in _migration(k.get("root")):
        ctx = obj_ctx.get(t["objekt"])
        if not ctx:
            continue
        for art, wer in (("heute", t["quelle"]), ("geplant", t["geplant"])):
            for slug, s in sys_.items():
                if wer and _passt(wer, s):
                    tabellen.setdefault((ctx, slug), []).append(art)
    team_vault = {str(t.get("id")): _teams_im_vault(t) for t in k.get("teams") or []}
    out = []
    for c in k.get("kontexte") or []:
        cid, cname = str(c.get("id") or ""), str(c.get("name") or c.get("id") or "")
        ohne_klammer = re.sub(r"\s*\([^)]*\)", " ", cname)      # "Annahme (Auftragswesen)"
        cn = " " + _norm(ohne_klammer) + " "
        teams = set().union(*[team_vault.get(str(o), set()) for o in c.get("owner") or []]) if c.get("owner") else set()
        vor = []
        for slug, s in sys_.items():
            gruende = []
            if any(f" {n} " in cn for n in s["namen"]):
                gruende.append("Name")
            arten = tabellen.get((cid, slug), [])
            if arten.count("heute"):
                gruende.append(f"Daten heute in {s['name']} ({arten.count('heute')} Tabelle{'n' if arten.count('heute') > 1 else ''})")
            if arten.count("geplant"):
                gruende.append("geplant laut Atlas")
            if s["team"] and s["team"] in teams:
                gruende.append(f"Team [[{s['team']}]]")
            if gruende or cid in s["kontexte"]:
                vor.append({"system": slug, "gruende": gruende or ["von Hand"]})
        rang = {"Name": 0}
        vor.sort(key=lambda v: (0 if cid in sys_[v["system"]]["kontexte"] else 1,
                                min(rang.get(g, 1 if g.startswith("Daten") else 2) for g in v["gruende"]),
                                -len(v["gruende"]), v["system"]))
        out.append({"id": cid, "name": cname, "sd": str(c.get("subdomain") or ""), "vorschlaege": vor[:6],
                    "zugeordnet": sorted(sl for sl, s in sys_.items() if cid in s["kontexte"])})
    return {"kanon": k, "kontexte": out, "systeme": sys_}


# ------------------------------------------------------------------ Liste

def liste(v: dict) -> str:
    k, sys_ = v["kanon"], v["systeme"]
    sd_name = {str(s.get("id")): str(s.get("name") or s.get("id")) for s in k.get("subdomaenen") or []}
    kopf = ["---", "type: bericht", f"erstellt: '{date.today().isoformat()}'", "---", "", "# Kontexte und Systeme", "",
            "> Welches System setzt welchen Kontext des Domain Atlas um? **Haken** = zugeordnet (Feld "
            f"`{FELD}:` auf der System-Seite), **Haken weg** = Zuordnung weg. Ein System ohne Vorschlag: "
            "eigene Zeile `- [x] [[system]]` unter den Kontext schreiben. Die Automatik übernimmt beim "
            "nächsten Lauf (sofort: `2ndbrain kontext-systeme`). Daraus zeichnet der Chat unter dem Bild "
            "„Kontexte“ die Software dahinter.", ""]
    body, ohne = [], []
    gruppen: dict[str, list[dict]] = {}
    for c in v["kontexte"]:
        gruppen.setdefault(c["sd"], []).append(c)
    for sd in sorted(gruppen, key=lambda s: sd_name.get(s, s).lower()):
        teile = []
        for c in sorted(gruppen[sd], key=lambda c: c["name"].lower()):
            if not c["vorschlaege"]:
                ohne.append(f"{c['name']} `{c['id']}`")
                continue
            teile += ["", f"### {c['name']} `{c['id']}`"]
            for vo in c["vorschlaege"]:
                s = sys_[vo["system"]]
                an = c["id"] in s["kontexte"]
                teile.append(f"- [{'x' if an else ' '}] [[{vo['system']}|{s['name']}]] – {', '.join(vo['gruende'])} "
                             f"<!-- ks:{c['id']}:{vo['system']}:{1 if an else 0} -->")
        if teile:
            body += ["", f"## {sd_name.get(sd, sd)} `{sd}`", *teile]
    zahl = sum(1 for c in v["kontexte"] if c["zugeordnet"])
    kopf.append(f"{zahl} von {len(v['kontexte'])} Kontexten sind einem System zugeordnet.")
    if ohne:
        body += ["", "## Ohne Vorschlag", "",
                 "Kein Beleg im Atlas oder in den System-Seiten. Zum Zuordnen einen Eintrag als Überschrift "
                 "(`### ` davor, samt ID) hierher kopieren und darunter `- [x] [[system]]` schreiben:", "",
                 ", ".join(ohne)]
    return "\n".join(kopf + body) + "\n"


def haken(text: str) -> list[tuple[str, str, bool, bool]]:
    """(kontext, system, angehakt, war_zugeordnet) aus der Liste - auch eigene Zeilen ohne Marke."""
    out, ctx = [], ""
    for line in text.splitlines():
        m = re.match(r"^#{2,4}\s.*`(ctx-[^`]+)`", line)
        if m:
            ctx = m.group(1)
            continue
        if re.match(r"^#{1,2}\s", line):
            ctx = ""
            continue
        m = re.match(r"^\s*-\s*\[([ xX])\]\s*(.*)$", line)
        if not m:
            continue
        an, rest = m.group(1).lower() == "x", m.group(2)
        marke = _MARKE.search(rest)
        if marke:
            out.append((marke.group(1), marke.group(2), an, marke.group(3) == "1"))
        elif ctx and _LINK.search(rest):
            out.append((ctx, _slug(rest), an, False))
    return out


def uebernehmen(text: str, sys_: dict, *, dry_run: bool = False) -> list[str]:
    """Haken auf die System-Seiten uebertragen. Rueckgabe: Aenderungen als Text."""
    neu = {slug: list(s["kontexte"]) for slug, s in sys_.items()}
    meldungen = []
    for ctx, slug, an, war in haken(text):
        if slug not in neu:
            meldungen.append(f"[[{slug}]] gibt es nicht als System-Seite – übersprungen")
            continue
        if an and ctx not in neu[slug]:
            neu[slug].append(ctx)
            meldungen.append(f"{sys_[slug]['name']} setzt {ctx} um")
        elif not an and war and ctx in neu[slug]:
            neu[slug].remove(ctx)
            meldungen.append(f"{sys_[slug]['name']}: {ctx} entfernt")
    if not dry_run:
        for slug, ks in neu.items():
            if ks != sys_[slug]["kontexte"]:
                vp.update_frontmatter(sys_[slug]["pfad"], {FELD: sorted(ks)})
                sys_[slug]["kontexte"] = sorted(ks)
    return meldungen


def automatik(*, dry_run: bool = False) -> dict:
    """Haken uebernehmen, Liste neu schreiben (nur bei Aenderung). Ohne Kanon: nichts."""
    v = vorschlaege()
    if not v["kanon"]:
        return {"changed": 0, "detail": []}
    detail = []
    alt = BERICHT.read_text(encoding="utf-8") if BERICHT.is_file() else ""
    meldungen = uebernehmen(alt, v["systeme"], dry_run=dry_run) if alt else []
    if meldungen:
        detail.append(f"Kontexte und Systeme: {len(meldungen)} Zuordnung(en) übernommen")
        v = vorschlaege() if not dry_run else v
    text = liste(v)
    if _ohne_datum(text) != _ohne_datum(alt):
        if not dry_run:
            BERICHT.parent.mkdir(parents=True, exist_ok=True)
            BERICHT.write_text(text, encoding="utf-8", newline="\n")
        if not meldungen:
            detail.append("Kontexte und Systeme: Liste neu")
    return {"changed": len(meldungen) + (1 if detail else 0), "detail": detail, "meldungen": meldungen}


def _ohne_datum(t: str) -> str:
    return re.sub(r"^erstellt: .*$", "", t, count=1, flags=re.M)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Kontexte des Domain Atlas und die Systeme dahinter")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.json:
        v = vorschlaege()
        print(json.dumps([{k: c[k] for k in ("id", "name", "sd", "vorschlaege", "zugeordnet")} for c in v["kontexte"]],
                         ensure_ascii=False, indent=1))
        return 0
    r = automatik(dry_run=args.dry_run)
    for m in r.get("meldungen", []):
        print(f"  {m}")
    print("; ".join(r["detail"]) or "Kontexte und Systeme: nichts zu tun")
    print(f"Liste: {BERICHT.relative_to(vp.VAULT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
