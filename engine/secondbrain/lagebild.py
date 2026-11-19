#!/usr/bin/env python3
"""lagebild.py - drei Bilder, je eines fuer eine Frage: reports/lagebild.md.

  Zusagen     Wer schuldet mir was, und wie lange schon? Je Person die offenen Zusagen als Balken,
              dazu das typische Alter - viele frische Punkte sind etwas anderes als wenige alte.
  Radar       Wo liegt viel und bewegt sich nichts? Jedes Thema als Punkt: nach rechts die Tage
              seit dem letzten Log-Eintrag, nach oben die offenen Punkte.
  Ablaeufe    Wo im Ablauf klemmt es? Die Ablaeufe des Kanons (Kontext fuer Kontext), jeder Kasten
              in der Ampelfarbe des Themas dahinter und mit dessen offenen Punkten.

Alles rechnet der Code aus Punkten, Themen und Kanon - kein Modell. Die Bilder sind Mermaid und
eine Tabelle, sie zeichnet Obsidian selbst. In der Automatik mit dem Schritt `stand`.

    2ndbrain lagebild            reports/lagebild.md neu (--dry-run | --json)
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import organisation
import vault_paths as vp

BERICHT = "reports/lagebild.md"
ZUSAGEN_HOECHSTENS = 15
ALT_AB_TAGEN = 30            # ab diesem typischen Alter gilt eine Person als "haengt"
RADAR_TAGE = 45              # rechter Rand des Radars
RADAR_MIN_OFFEN = 3          # Themen mit weniger offenen Punkten stehen nicht im Radar
BALKEN = 24
_FARBE = {"red": "#E24B4A", "yellow": "#EF9F27", "green": "#639922"}


def _tage(iso: str | None, heute: date) -> int | None:
    try:
        return (heute - date.fromisoformat(str(iso)[:10])).days
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ Zusagen

def zusagen(tasks: list[tk.Task], ich: str, heute: date) -> list[dict]:
    """Je Person (nicht ich): offene Zusagen, typisches und hoechstes Alter, ueberfaellige."""
    je: dict[str, list[tk.Task]] = {}
    for t in tasks:
        if t.is_open and t.kind == tk.KIND_TASK and t.owner and t.owner != ich and not t.pruefen:
            je.setdefault(t.owner, []).append(t)
    out = []
    for slug, ts in je.items():
        alter = [a for a in (_tage(t.created, heute) for t in ts) if a is not None]
        out.append({"person": slug, "offen": len(ts), "typisch": round(statistics.median(alter)) if alter else None,
                    "aeltester": max(alter) if alter else None,
                    "ueberfaellig": sum(1 for t in ts if t.overdue(heute.isoformat()))})
    out.sort(key=lambda r: (-r["offen"], -(r["typisch"] or 0)))
    return out


def zusagen_tabelle(rows: list[dict], org: organisation.Organisation, ich: str) -> list[str]:
    if not rows:
        return ["_Niemand schuldet dir gerade etwas._"]
    groesste = max(r["offen"] for r in rows)
    out = ["| Person | offen | | typisch alt | ältester | Verhältnis |", "|---|---|---|---|---|---|"]
    for r in rows[:ZUSAGEN_HOECHSTENS]:
        balken = "█" * max(1, round(BALKEN * r["offen"] / groesste))
        haengt = r["typisch"] is not None and r["typisch"] >= ALT_AB_TAGEN
        typisch = "–" if r["typisch"] is None else (f"**{r['typisch']} Tage**" if haengt else f"{r['typisch']} Tage")
        v = organisation.VERHAELTNIS_TEXT.get(org.verhaeltnis(ich, r["person"]), "")
        out.append(f"| [[{r['person']}\\|{org.name(r['person'])}]] | {r['offen']} | `{balken}` | {typisch} | "
                   f"{'–' if r['aeltester'] is None else str(r['aeltester']) + ' Tage'} | {v} |")
    if len(rows) > ZUSAGEN_HOECHSTENS:
        rest = rows[ZUSAGEN_HOECHSTENS:]
        out.append(f"| … {len(rest)} weitere | {sum(r['offen'] for r in rest)} | | | | |")
    return out


# -------------------------------------------------------------------- Radar

def themen_lage(heute: date) -> list[dict]:
    """Je Thema: Titel, Ampel, offene Punkte (eigene, ohne Unterthemen), Tage seit der letzten Bewegung."""
    offen = {s: len(ts) for s, ts in tk.open_by_topic().items()}
    out = []
    for f in sorted(vp.PROJECTS_DIR.glob("*.md")) if vp.PROJECTS_DIR.is_dir() else []:
        fm = vp.read_frontmatter_head(f)
        out.append({"slug": f.stem, "titel": str(fm.get("title") or f.stem), "ampel": str(fm.get("health") or ""),
                    "offen": offen.get(f.stem, 0), "bewegt": str(fm.get("zuletzt_bewegt") or "")[:10],
                    "still": _tage(fm.get("zuletzt_bewegt"), heute),
                    "atlas": [str(x) for x in (fm.get("atlas_id") if isinstance(fm.get("atlas_id"), list)
                                                else [fm.get("atlas_id")] if fm.get("atlas_id") else [])]})
    # Stillstand misst sich am juengsten Eintrag im Vault, nicht am Kalender: nach drei Wochen Urlaub
    # stuende sonst jedes Thema am rechten Rand, und das Bild zeigte nur die Pause.
    juengste = max((t["bewegt"] for t in out if t["bewegt"]), default="")
    try:
        bezug = min(heute, date.fromisoformat(juengste)) if juengste else heute
    except ValueError:
        bezug = heute
    for t in out:
        t["still"] = _tage(t["bewegt"], bezug) if t["bewegt"] else None
        t["bezug"] = bezug.isoformat()
    return out


def _mermaid_text(text: str) -> str:
    return re.sub(r'["\[\]{}()<>|:;#&]', " ", str(text)).strip()


def _punkt_name(text: str) -> str:
    """Name eines Punkts im quadrantChart: nur Buchstaben, Ziffern und Leerzeichen (der Parser nimmt
    weder Bindestrich noch Umlaut sicher)."""
    t = str(text)
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", t).split())


def radar(themen: list[dict]) -> list[str]:
    """Mermaid quadrantChart: x = Tage seit der letzten Bewegung (0..RADAR_TAGE), y = offene Punkte."""
    punkte = [t for t in themen if t["offen"] >= RADAR_MIN_OFFEN and t["still"] is not None]
    if not punkte:
        return ["_Kein Thema mit offenen Punkten und bekanntem Bewegungsdatum._"]
    hoechst = max(t["offen"] for t in punkte)
    zeilen = ["```mermaid", "quadrantChart", "    title Themen - offene Punkte gegen Stillstand",
              f"    x-axis bewegt sich --> steht still ({RADAR_TAGE}+ Tage)", "    y-axis wenig offen --> viel offen",
              "    quadrant-1 viel offen, steht still", "    quadrant-2 viel offen, bewegt sich",
              "    quadrant-3 wenig offen, bewegt sich", "    quadrant-4 wenig offen, steht still"]
    gesehen: set[str] = set()
    for t in sorted(punkte, key=lambda t: -t["offen"]):
        name = _punkt_name(t["titel"])[:28].strip() or _punkt_name(t["slug"])
        if name in gesehen:
            name = _punkt_name(t["slug"])[:28].strip()
        gesehen.add(name)
        x = min(0.98, max(0.02, min(t["still"], RADAR_TAGE) / RADAR_TAGE))
        y = min(0.98, max(0.02, t["offen"] / hoechst))
        farbe = _FARBE.get(t["ampel"])
        stil = f" color: {farbe}" if farbe else ""
        zeilen.append(f"    {name} {t['offen']}: [{x:.2f}, {y:.2f}]{stil}")
    zeilen.append("```")
    return zeilen


def auffaellig(themen: list[dict]) -> list[str]:
    """Die zwei Gruppen, die das Radar zeigen soll, als Saetze."""
    still = sorted((t for t in themen if t["offen"] >= 10 and (t["still"] or 0) >= 14), key=lambda t: -(t["still"] or 0))
    rot_leer = [t for t in themen if t["ampel"] == "red" and 0 < t["offen"] <= 3]
    out = []
    if still:
        out.append("**Viel offen und still:** " + ", ".join(f"[[{t['slug']}|{t['titel']}]] ({t['offen']} offen, {t['still']} Tage)"
                                                              for t in still[:5]))
    if rot_leer:
        out.append("**Rot mit kaum offenen Punkten** (ein einzelnes hartes Problem): "
                   + ", ".join(f"[[{t['slug']}|{t['titel']}]] ({t['offen']})" for t in rot_leer[:5]))
    return out


# ------------------------------------------------------------------ Ablaeufe

def _thema_zu(kontext: str, kanon: dict, themen: dict[str, dict]) -> str:
    """Das Thema hinter einem Kontext: ueber seine Subdomaene (gleicher Name ohne `sd-`, oder die
    Kennung in `atlas_id` eines Themas); bei Externen ueber den Namen im Slug oder Titel."""
    ctx = next((k for k in kanon.get("kontexte") or [] if k.get("id") == kontext), None)
    if ctx:
        sd = str(ctx.get("subdomain") or "")
        kurz = sd[3:] if sd.startswith("sd-") else sd
        if kurz in themen:
            return kurz
        return next((s for s, t in themen.items() if sd in t["atlas"] or kontext in t["atlas"]), "")
    ext = next((e for e in kanon.get("externe") or [] if e.get("id") == kontext), None)
    if ext:
        wort = re.split(r"[\s(/]", str(ext.get("name") or ""))[0].casefold()
        if len(wort) >= 5:
            return next((s for s, t in themen.items() if wort in s or wort in t["titel"].casefold()), "")
    return ""


def _kontext_name(kontext: str, kanon: dict) -> str:
    for liste in ("kontexte", "externe"):
        k = next((x for x in kanon.get(liste) or [] if x.get("id") == kontext), None)
        if k:
            return str(k.get("name") or kontext)
    return kontext


def ablauf_bild(ablauf: dict, kanon: dict, themen: dict[str, dict]) -> list[str]:
    """Ein Ablauf als Mermaid-Fluss: die Kontexte in der Reihenfolge der Schritte, Externe als Rand."""
    schritte = [str(s.get("kontext") or "") for s in ablauf.get("schritte") or [] if s.get("kontext")]
    reihe = list(dict.fromkeys(schritte))
    if len(reihe) < 2:
        return []
    knoten = {k: f"k{i}" for i, k in enumerate(reihe)}
    zeilen = ["```mermaid", "graph LR"]
    for k in reihe:
        th = themen.get(_thema_zu(k, kanon, themen))
        text = _mermaid_text(_kontext_name(k, kanon))
        if th:
            text += f"<br/>{th['offen']} offen"
        form = f'(["{text}"])' if k.startswith("ext-") else f'["{text}"]'
        zeilen.append(f"  {knoten[k]}{form}")
        farbe = _FARBE.get(th["ampel"]) if th else None
        if farbe:
            zeilen.append(f"  style {knoten[k]} stroke:{farbe},stroke-width:3px")
    # Externe am Anfang laufen parallel in den ersten internen Kontext, Externe am Ende aus dem letzten
    intern = [k for k in reihe if not k.startswith("ext-")]
    vorn = [k for k in reihe[:reihe.index(intern[0])]] if intern else []
    kanten: list[tuple[str, str]] = [(e, intern[0]) for e in vorn] if intern else []
    rest = [k for k in reihe if k not in vorn]
    # ein Kontext, der mehrere Schritte nacheinander hat, verteilt: seine Nachfolger haengen an ihm
    verteiler = next((k for k in rest if schritte.count(k) > 1), "")
    for a, b in zip(rest, rest[1:]):
        quelle = verteiler if verteiler and rest.index(a) > rest.index(verteiler) and b != rest[-1] else a
        kanten.append((quelle if quelle != b else a, b))
    for a, b in dict.fromkeys(kanten):
        zeilen.append(f"  {knoten[a]} --> {knoten[b]}")
    zeilen.append("```")
    return zeilen


def ablaeufe(heute: date, themen_liste: list[dict]) -> list[str]:
    try:
        import kanon
        k = kanon.lade()
    except Exception as e:                           # noqa: BLE001 - ohne Kanon gibt es dieses Bild nicht
        return [f"_Kein Kanon lesbar ({type(e).__name__}) – ohne ihn gibt es keine Abläufe zu zeichnen._"]
    if not k or not k.get("ablaeufe"):
        return ["_Der Kanon beschreibt noch keine Abläufe._"]
    themen = {t["slug"]: t for t in themen_liste}
    out: list[str] = []
    for a in k["ablaeufe"]:
        bild = ablauf_bild(a, k, themen)
        if bild:
            out += [f"### {a.get('name') or a.get('id')}", "", *bild, ""]
    return out or ["_Kein Ablauf mit mindestens zwei Kontexten._"]


# ------------------------------------------------------------------ Bericht

def bericht(heute: date | None = None) -> str:
    heute = heute or date.today()
    ich = organisation.ich()
    org = organisation.lade()
    tasks = tk.scan()
    themen = themen_lage(heute)
    import rollen                      # Punkte anderer nur aus Themen, die ich fuehre (oder von meinen Berichten)
    z = zusagen(rollen.sichtbare(tasks, ich, immer=set(org.alle_berichte(ich)) if ich else set()), ich, heute)
    haengt = [r for r in z if r["typisch"] is not None and r["typisch"] >= ALT_AB_TAGEN and r["offen"] >= 3]
    out = ["# Lagebild", "",
           f"_Stand {heute.strftime('%d.%m.%Y')} – erzeugt von `2ndbrain lagebild` und bei jedem Lauf ersetzt. Drei Bilder, "
           "je eines für eine Frage; gerechnet aus Punkten, Themen und Kanon, ohne Modell._", "",
           "## Wer schuldet mir was – und wie lange schon?", ""]
    out += zusagen_tabelle(z, org, ich)
    if haengt:
        out += ["", "**Hängt:** " + ", ".join(f"[[{r['person']}|{org.name(r['person'])}]] ({r['offen']} offen, typisch {r['typisch']} Tage alt)"
                                               for r in haengt[:5]) + " – das Gespräch, das ansteht."]
    out += ["", "_Fett: typisch 30 Tage und älter. Ungeprüfter Altbestand zählt nicht mit; aus Themen, die du nicht führst, "
            "zählen nur die Punkte deiner Berichte (Rolle je Thema: Einstellungen → 2ndBrain)._", "",
            "## Wo liegt viel und bewegt sich nichts?", ""]
    out += radar(themen)
    bezug = next((t["bezug"] for t in themen if t.get("bezug")), heute.isoformat())
    gemessen = ("" if bezug == heute.isoformat() else
                f" Stillstand gemessen am jüngsten Log-Eintrag im Vault ({bezug[8:10]}.{bezug[5:7]}.{bezug[:4]}), nicht an heute.")
    out += ["", *auffaellig(themen), "",
            f"_Themen ab {RADAR_MIN_OFFEN} offenen Punkten. Hinter dem Namen: offene Punkte; die Farbe ist die Ampel.{gemessen}_", "",
            "## Wo im Ablauf klemmt es?", "",
            "_Die Abläufe des Kanons. Rahmenfarbe: Ampel des Themas hinter dem Kontext; rund: Externe._", ""]
    out += ablaeufe(heute, themen)
    return "\n".join(out).rstrip() + "\n"


def run(*, dry_run: bool = False) -> dict:
    text = bericht()
    f = vp.VAULT / BERICHT
    geaendert = not f.is_file() or f.read_text(encoding="utf-8") != text
    if geaendert and not dry_run:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline="\n")
    return {"ok": True, "bericht": BERICHT, "geaendert": geaendert, "zeilen": text.count("\n")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lagebild: Zusagen, Radar, Abläufe")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = run(dry_run=args.dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
