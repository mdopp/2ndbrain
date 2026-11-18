#!/usr/bin/env python3
"""organisation.py - wer berichtet an wen: die Organisation als Daten, Bild und Pflegeliste.

Die Berichtslinie steht auf den Personenseiten. Drei Quellen, die staerkste gewinnt:

  1. `berichtet_an: '[[slug]]'` im Frontmatter der Person - von Hand gepflegt, gilt immer
  2. disziplinarisch (Verzeichnis): "Vorgesetzt: [[...]]" im Abschnitt "Organisation (automatisch)",
     oder die Person steht bei jemandem unter "Direct Reports"
  3. fachlich (Organigramm): "Berichtet fachlich an (Organigramm): [[...]]" im selben Abschnitt

Der Abschnitt "Organisation (automatisch)" (`<!-- orgchart-auto:start -->`) stammt aus einem
Organigramm-Import; dieses Modul liest ihn nur. Aendert sich etwas, traegt man `berichtet_an` ein -
das ueberstimmt den Import und haelt bis zum naechsten Organigramm.

Wofuer: die Einordnung der Aufgaben (wem kann ich etwas uebergeben, bei wem fasse ich nach), die
Vorbereitung von Jourfixen, das Bild der eigenen Linie.

    2ndbrain orgchart                 reports/orgchart.md neu: Bild der eigenen Linie, Pflegeliste
    2ndbrain orgchart --json          die Organisation als JSON (nichts wird geschrieben)
    2ndbrain orgchart --person <slug> Linie, Berichte und Verhaeltnis zu mir fuer eine Person
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

BERICHT = "reports/orgchart.md"
FELD = "berichtet_an"
_START, _ENDE = "<!-- orgchart-auto:start -->", "<!-- orgchart-auto:end -->"
_LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
BILD_JE_PERSON = 8           # so viele Berichte je Person zeigt das Bild, der Rest als "+ n weitere"

# Verhaeltnis einer Person zu mir
DIREKT, LINIE, VORGESETZT, KOLLEGE, ANDERE, UNBEKANNT = "direkt", "linie", "vorgesetzt", "kollege", "andere", "unbekannt"
MATRIX = "matrix"            # nicht in meiner Linie, aber in meinem Fachkreis (Matrix-Organisation)
VERHAELTNIS_TEXT = {DIREKT: "berichtet an mich", LINIE: "in meiner Linie", VORGESETZT: "über mir",
                    MATRIX: "in deinem Fachkreis (Matrix)",
                    KOLLEGE: "gleiche Führungskraft", ANDERE: "andere Linie", UNBEKANNT: "ohne Platz im Organigramm"}


def _slug(v) -> str:
    m = _LINK_RE.search(str(v or ""))
    return (m.group(1) if m else str(v or "")).strip().strip("'\"")


def _links(text: str) -> list[str]:
    return [m.group(1).strip() for m in _LINK_RE.finditer(text)]


class Organisation:
    """{slug: {name, rolle, team, aktiv, vorgesetzt, quelle}} plus die Umkehrung `berichte`."""

    def __init__(self, personen: dict[str, dict]) -> None:
        self.personen = personen
        self.berichte: dict[str, list[str]] = {}
        for slug, p in personen.items():
            if p.get("vorgesetzt"):
                self.berichte.setdefault(p["vorgesetzt"], []).append(slug)
        for chef in self.berichte:
            self.berichte[chef].sort(key=lambda s: self.name(s).casefold())

    def name(self, slug: str) -> str:
        return (self.personen.get(slug) or {}).get("name") or slug

    def vorgesetzt(self, slug: str) -> str | None:
        return (self.personen.get(slug) or {}).get("vorgesetzt") or None

    def linie(self, slug: str) -> list[str]:
        """Die Kette nach oben, die naechste Fuehrungskraft zuerst - ein Kreis in den Daten endet sie."""
        out: list[str] = []
        cur = self.vorgesetzt(slug)
        while cur and cur not in out and cur != slug:
            out.append(cur)
            cur = self.vorgesetzt(cur)
        return out

    def direkte(self, slug: str) -> list[str]:
        return list(self.berichte.get(slug, []))

    def alle_berichte(self, slug: str) -> list[str]:
        """Alle unter einer Person, ueber alle Ebenen."""
        out, offen = [], self.direkte(slug)
        while offen:
            s = offen.pop(0)
            if s in out or s == slug:
                continue
            out.append(s)
            offen += self.direkte(s)
        return out

    def verhaeltnis(self, ich: str, person: str) -> str:
        """Wo steht `person` von mir aus gesehen?"""
        if not person or person == ich or person not in self.personen:
            return UNBEKANNT
        if self.vorgesetzt(person) == ich:
            return DIREKT
        if ich in self.linie(person):
            return LINIE
        if person in self.linie(ich):
            return VORGESETZT
        chef = self.vorgesetzt(person)
        if chef and chef == self.vorgesetzt(ich):
            return KOLLEGE
        if not chef and not self.berichte.get(person):
            return UNBEKANNT
        return ANDERE

    def als_dict(self) -> dict:
        return {"personen": self.personen, "berichte": self.berichte}


def _block(text: str) -> str:
    i, j = text.find(_START), text.find(_ENDE)
    return text[i:j] if 0 <= i < j else ""


def lade() -> Organisation:
    """Die Organisation aus den Personenseiten lesen (Frontmatter und Abschnitt "Organisation")."""
    roh: dict[str, dict] = {}
    gelistet: dict[str, str] = {}                # Person -> bei wem sie unter "Direct Reports" steht
    for f in sorted(vp.PEOPLE_DIR.glob("*.md")) if vp.PEOPLE_DIR.is_dir() else []:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fm, _ = vp.split_frontmatter(text)
        p = {"name": str(fm.get("name") or f.stem), "rolle": str(fm.get("role") or ""),
             "team": _slug(fm.get("team")), "aktiv": str(fm.get("status") or "active") not in ("inactive", "left"),
             "hand": _slug(fm.get(FELD)), "m365": "", "fachlich": ""}
        for line in _block(text).splitlines():
            low = line.lower()
            if "vorgesetzt:" in low:
                nach = line[low.index("vorgesetzt:"):]
                p["m365"] = (_links(nach) or [""])[0]
            elif "berichtet fachlich an" in low:
                p["fachlich"] = (_links(line) or [""])[0]
            elif "direct reports" in low:
                for s in _links(line):
                    gelistet.setdefault(s, f.stem)
        roh[f.stem] = p

    personen: dict[str, dict] = {}
    for slug, p in roh.items():
        kandidaten = [(p["hand"], "von Hand"), (p["m365"] or gelistet.get(slug, ""), "Verzeichnis"),
                      (p["fachlich"], "Organigramm")]
        chef, quelle = next(((c, q) for c, q in kandidaten if c and c != slug and c in roh), ("", ""))
        personen[slug] = {"name": p["name"], "rolle": p["rolle"], "team": p["team"], "aktiv": p["aktiv"],
                          "vorgesetzt": chef, "quelle": quelle}
    return Organisation(personen)


def ich() -> str:
    return str(vp.local_config().get("ich") or "")


# ------------------------------------------------------------- Matrix
#
# In einer Matrix-Organisation uebergibt man nicht nur in der eigenen Linie: eine Enterprise-
# Architektin gibt Arbeit auch an die Architekten der Bereiche, an ein Team oder in eine Runde.
# `delegation` in .2ndbrain/local.config.json sagt, an wen:
#   "rollen":   ["architekt", "architect"]   Personen, deren Rolle eines dieser Woerter enthaelt
#   "personen": ["vorname-nachname"]         einzelne Personen dazu
#   "gruppen":  ["team-slug", "reihen-slug"] nur diese Gruppen (leer = alle Teams und Reihen)
# Gruppen sind die Teams (entities/teams, mit Leitung und Mitgliedern) und die Reihen (entities/forums:
# die Runden aus dem Kalender, mit den Personen, die dort regelmaessig dabei sind).

def delegation_einstellung() -> dict:
    cfg = vp.local_config().get("delegation") or {}
    liste = lambda v: [str(x).strip() for x in (v if isinstance(v, list) else []) if str(x).strip()]   # noqa: E731
    return {"rollen": [r.casefold() for r in liste(cfg.get("rollen"))], "personen": liste(cfg.get("personen")),
            "gruppen": liste(cfg.get("gruppen"))}


def kreis(org: Organisation, ich_slug: str, einstellung: dict | None = None) -> dict[str, str]:
    """An wen ich etwas uebergeben kann: {slug: DIREKT | LINIE | MATRIX}. Die eigene Linie zuerst,
    dann der Fachkreis der Matrix (nach Rolle oder einzeln benannt)."""
    e = einstellung if einstellung is not None else delegation_einstellung()
    out = {s: (DIREKT if org.vorgesetzt(s) == ich_slug else LINIE)
           for s in org.alle_berichte(ich_slug) if org.personen[s]["aktiv"]}
    for s, p in org.personen.items():
        if s == ich_slug or s in out or not p["aktiv"]:
            continue
        rolle = p["rolle"].casefold()
        if s in e["personen"] or any(r in rolle for r in e["rollen"]):
            out[s] = MATRIX
    return out


def gruppen(org: Organisation, einstellung: dict | None = None) -> dict[str, dict]:
    """Die Gruppen, an die sich etwas geben laesst: {slug: {art: team|reihe, name, namen, lead,
    personen, thema}}. Ein Team hat eine Leitung (die den Punkt dann traegt); eine Reihe ist eine
    Runde, in die man den Punkt mitnimmt."""
    e = einstellung if einstellung is not None else delegation_einstellung()
    out: dict[str, dict] = {}
    for f in sorted(vp.TEAMS_DIR.glob("*.md")) if vp.TEAMS_DIR.is_dir() else []:
        fm = vp.read_frontmatter_head(f)
        name = str(fm.get("name") or f.stem)
        aliases = fm.get("aliases") if isinstance(fm.get("aliases"), list) else []
        out[f.stem] = {"art": "team", "name": name, "namen": [name, *[str(a) for a in aliases]],
                       "lead": _slug(fm.get("lead")), "thema": "",
                       "personen": [s for s, p in org.personen.items() if p["team"] == f.stem and p["aktiv"]]}
    for f in sorted(vp.FORUMS_DIR.glob("*.md")) if vp.FORUMS_DIR.is_dir() else []:
        fm = vp.read_frontmatter_head(f)
        name = str(fm.get("name") or f.stem)
        mit = [_slug(x) for x in (fm.get("mit") if isinstance(fm.get("mit"), list) else [])]
        try:
            import themen
            mit = list(dict.fromkeys([*mit, *[_slug(x) for x in themen.series_persons(f.stem)]]))
        except Exception:                            # noqa: BLE001 - die Reihe gilt auch ohne ihre Personen
            pass
        out.setdefault(f.stem, {"art": "reihe", "name": name, "namen": [name], "lead": "",
                                "thema": _slug(fm.get("project")), "personen": [s for s in mit if s in org.personen]})
    if e["gruppen"]:
        out = {s: g for s, g in out.items() if s in e["gruppen"]}
    return out


# ------------------------------------------------------------------- Bild

def _offen_je_person() -> dict[str, int]:
    import aufgaben as tk
    out: dict[str, int] = {}
    for t in tk.scan():
        if t.is_open and t.owner and t.kind == tk.KIND_TASK:
            out[t.owner] = out.get(t.owner, 0) + 1
    return out


def _knoten(slug: str) -> str:
    return "p_" + re.sub(r"[^a-z0-9]", "_", slug.lower())


def _beschriftung(org: Organisation, slug: str, offen: dict[str, int]) -> str:
    text = org.name(slug).replace('"', "'")
    n = offen.get(slug, 0)
    return f'{_knoten(slug)}["{text}' + (f"<br/>{n} offen" if n else "") + '"]'


def bild(org: Organisation, mitte: str, offen: dict[str, int] | None = None) -> str:
    """Mermaid: die Linie ueber `mitte`, `mitte`, die direkten Berichte und deren Berichte. Hinter dem
    Namen steht, wie viele offene Zusagen die Person hat."""
    offen = offen or {}
    zeilen = ["```mermaid", "graph TD"]
    kette = list(reversed(org.linie(mitte))) + [mitte]
    for s in kette:
        zeilen.append("  " + _beschriftung(org, s, offen))
    for oben, unten in zip(kette, kette[1:]):
        zeilen.append(f"  {_knoten(oben)} --> {_knoten(unten)}")

    def unter(chef: str, tiefe: int) -> None:
        berichte = org.direkte(chef)
        # wer offene Zusagen hat, zuerst - der Rest zusammengefasst
        berichte.sort(key=lambda s: (-offen.get(s, 0), org.name(s).casefold()))
        gezeigt = berichte if tiefe == 0 else berichte[:BILD_JE_PERSON]
        for s in gezeigt:
            zeilen.append("  " + _beschriftung(org, s, offen))
            zeilen.append(f"  {_knoten(chef)} --> {_knoten(s)}")
            if tiefe == 0:
                unter(s, 1)
            elif org.direkte(s):
                k = _knoten(s) + "_mehr"
                zeilen.append(f'  {k}(["+ {len(org.alle_berichte(s))} darunter"])')
                zeilen.append(f"  {_knoten(s)} -.-> {k}")
        if len(berichte) > len(gezeigt):
            k = _knoten(chef) + "_rest"
            zeilen.append(f'  {k}(["+ {len(berichte) - len(gezeigt)} weitere"])')
            zeilen.append(f"  {_knoten(chef)} -.-> {k}")

    unter(mitte, 0)
    zeilen.append(f"  style {_knoten(mitte)} stroke-width:3px")
    zeilen.append("```")
    return "\n".join(zeilen)


# ---------------------------------------------------------------- Bericht

def luecken(org: Organisation, ich_slug: str, offen: dict[str, int]) -> list[str]:
    """Personen mit offenen Zusagen, deren Platz in der Organisation unbekannt ist - ohne ihn laesst
    sich nicht sagen, ob man ihnen etwas uebergeben kann oder bei ihnen nur nachfasst."""
    return sorted((s for s, n in offen.items() if n and s != ich_slug and org.verhaeltnis(ich_slug, s) == UNBEKANNT),
                  key=lambda s: -offen[s])


def bericht(org: Organisation | None = None) -> str:
    org = org or lade()
    ich_slug = ich()
    offen = _offen_je_person()
    link = lambda s: f"[[{s}|{org.name(s)}]]"                                     # noqa: E731
    quellen: dict[str, int] = {}
    for p in org.personen.values():
        quellen[p["quelle"] or "ohne"] = quellen.get(p["quelle"] or "ohne", 0) + 1
    out = ["# Organisation", "",
           f"_Stand {date.today().strftime('%d.%m.%Y')} – erzeugt von `2ndbrain orgchart` aus den Personenseiten und bei jedem "
           "Lauf ersetzt. Eine Berichtslinie ändern: auf der Personenseite `berichtet_an: '[[slug]]'` ins Frontmatter – "
           "das gilt vor Verzeichnis und Organigramm._", ""]
    if not ich_slug or ich_slug not in org.personen:
        out += ["Unter `ich` in `.2ndbrain/local.config.json` steht keine Person mit eigener Seite – ohne sie gibt es keine eigene Linie.", ""]
        return "\n".join(out)

    out += ["## Meine Linie", "", bild(org, ich_slug, offen), "",
            "_Hinter dem Namen: offene Zusagen der Person. Dick umrandet: ich._", ""]
    kette = org.linie(ich_slug)
    if kette:
        out += ["**Über mir:** " + " › ".join(link(s) for s in reversed(kette)), ""]
    direkte = org.direkte(ich_slug)
    out += [f"## Berichten an mich ({len(direkte)})", "", "| Person | Rolle | Quelle | darunter | offene Zusagen |", "|---|---|---|---|---|"]
    for s in direkte:
        p = org.personen[s]
        out.append(f"| {link(s)} | {p['rolle'] or '–'} | {p['quelle']} | {len(org.alle_berichte(s))} | {offen.get(s, 0)} |")
    gesamt = org.alle_berichte(ich_slug)
    out += ["", f"In meiner Linie insgesamt: {len(gesamt)} Personen, {sum(offen.get(s, 0) for s in gesamt)} offene Zusagen.", ""]

    fehlt = luecken(org, ich_slug, offen)
    out += [f"## Zu pflegen ({len(fehlt)})", "",
            "_Personen mit offenen Zusagen, deren Platz in der Organisation unbekannt ist. Auf ihrer Seite "
            "`berichtet_an: '[[slug]]'` eintragen._", ""]
    out += [f"- {link(s)} – {offen[s]} offen" + (f" · {org.personen[s]['rolle']}" if org.personen[s]["rolle"] else "")
            for s in fehlt[:60]] or ["- niemand"]
    out += ["", "## Woher die Berichtslinien stammen", "",
            " · ".join(f"{q}: {n}" for q, n in sorted(quellen.items(), key=lambda kv: -kv[1])), ""]
    return "\n".join(out)


def run(*, dry_run: bool = False) -> dict:
    org = lade()
    text = bericht(org)
    f = vp.VAULT / BERICHT
    geaendert = not f.is_file() or f.read_text(encoding="utf-8") != text
    if geaendert and not dry_run:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline="\n")
    ich_slug = ich()
    return {"ok": True, "bericht": BERICHT, "geaendert": geaendert, "personen": len(org.personen),
            "mit_linie": sum(1 for p in org.personen.values() if p["vorgesetzt"]),
            "direkte": len(org.direkte(ich_slug)), "in_meiner_linie": len(org.alle_berichte(ich_slug))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Organisation: wer berichtet an wen")
    ap.add_argument("--json", action="store_true", help="die Organisation als JSON, nichts schreiben")
    ap.add_argument("--person", metavar="SLUG", help="Linie, Berichte und Verhältnis zu mir")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.person:
        org, s, i = lade(), args.person, ich()
        if s not in org.personen:
            print(json.dumps({"ok": False, "grund": f"Keine Personenseite „{s}“."}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, "person": s, **org.personen[s], "linie": org.linie(s), "direkte": org.direkte(s),
                          "verhaeltnis": org.verhaeltnis(i, s), "verhaeltnis_text": VERHAELTNIS_TEXT[org.verhaeltnis(i, s)]},
                         ensure_ascii=False, indent=2))
        return 0
    if args.json:
        print(json.dumps(lade().als_dict(), ensure_ascii=False))
        return 0
    print(json.dumps(run(dry_run=args.dry_run), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
