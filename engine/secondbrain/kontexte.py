#!/usr/bin/env python3
"""kontexte.py - schreibt das Kontext-Verzeichnis `entities/contexts/_index.md` aus dem Kanon.

Ein Verzeichnis der Bounded Contexts (ID, Name, Subdomaene, Owner, Reife, Kurzbeschreibung), dazu
die Subdomaenen, die Nachrichten zwischen den Kontexten (Typ, Reife, von, an), Fachobjekte, Teams,
Externe, Beziehungen und Ablaeufe - daraus zeichnet der Chat im Plugin, wie Kontexte zusammenspielen,
und seine Werkzeuge (Suche, Lesen, Wege im Graphen) kennen den Kanon auch am Handy, wo er selbst
fehlt. Bei jedem Lauf ueberschrieben, nie von Hand gepflegt. Bewusst eine Datei, kein Spiegeln je
Element: eine Datei je Kontext waere ein zweiter Datenbestand, der mit dem Kanon auseinanderlaeuft.
Die IDs selbst stehen als `atlas_id` im Frontmatter der betroffenen Entities
(`uebernehmen.apply_entities()` ueber aufloesen.py) - das hier ist nur der Index, keine Aufloesung.

Die Automatik zieht das Verzeichnis im Schritt `wissen` nach, wenn sich der Kanon geaendert hat
(wissen.py).

Usage:
    2ndbrain kontexte [--dry-run]
    2ndbrain kontexte --json          # Kontexte als JSON, schreibt nichts
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


import vault_paths as vp

INDEX_PATH = vp.CONTEXTS_DIR / "_index.md"
# Fassung des Formats: aendert sie sich, schreibt die Automatik (wissen.py) den Index einmal neu
FASSUNG = "landkarte-4"

GENERATED_NOTICE = (
    "<!-- Automatisch generiert von kontexte.py. "
    "Nicht von Hand editieren - wird beim naechsten Lauf ueberschrieben. -->"
)


def load_contexts() -> list[dict]:
    """Kontexte aus dem Kanon (kanon.py - Domain Atlas oder einfache YAML-Datei)."""
    import kanon
    k = kanon.lade()
    if not k:
        print("[WARN] Kein Kanon gefunden (`kanon` bzw. `paths.domain_atlas`).", file=sys.stderr)
        return []
    return [{"id": c.get("id") or c.get("datei"), "name": c.get("name") or c.get("datei"),
             "subdomain": c.get("subdomain") or "", "owner": ", ".join(str(o) for o in c.get("owner") or []),
             "reife": str(c.get("reife") or ""),
             "description": str(c.get("beschreibung") or "").replace("\n", " ").strip()}
            for c in k["kontexte"]]


def load_landkarte() -> tuple[list[dict], list[dict], dict[str, list[dict]]]:
    """Subdomaenen, Nachrichten und der Rest des Kanons (Objekte, Teams, Externe, Beziehungen,
    Ablaeufe) - fuer die Abschnitte unter der Kontext-Liste. Das Plugin liest sie hier (auch am
    Handy, wo der Kanon selbst fehlt), zeichnet daraus, wie Kontexte zusammenspielen, und baut seinen
    Graphen fuer die Werkzeuge des Chats."""
    import kanon
    k = kanon.lade()
    if not k:
        return [], [], {}
    s_ = _text
    subs =[{"id": s_(s.get("id")), "name": s_(s.get("name") or s.get("id")), "art": s_(s.get("art")),
             "reife": s_(s.get("reife")), "beschreibung": s_(s.get("beschreibung"))}
            for s in k.get("subdomaenen") or [] if s.get("id")]
    msgs = [{"id": s_(m.get("id")), "name": s_(m.get("name") or m.get("id")),
             "typ": s_(m.get("typ")), "reife": s_(m.get("reife")),
             "von": list(m.get("produzenten") or []), "an": list(m.get("konsumenten") or []),
             "kanten_reife": dict(m.get("kanten_reife") or {}), "beschreibung": s_(m.get("beschreibung"))}
            for m in k.get("nachrichten") or [] if m.get("id")]
    weitere = {
        "objekte": [{"id": s_(o.get("id")), "name": s_(o.get("begriff") or o.get("name") or o.get("id")),
                     "kontext": s_(o.get("kontext")), "definition": s_(o.get("definition")),
                     "synonyme": [s_(x) for x in o.get("synonyme") or [] if x], "stereotyp": s_(o.get("stereotyp")),
                     "relationen": list(o.get("relationen") or [])}
                    for o in k.get("objekte") or [] if o.get("id")],
        "teams": [{"id": s_(t.get("id")), "name": s_(t.get("name") or t.get("id")),
                   "beschreibung": s_(t.get("beschreibung"))} for t in k.get("teams") or [] if t.get("id")],
        "externe": [{"id": s_(e.get("id")), "name": s_(e.get("name") or e.get("id")), "kategorie": s_(e.get("kategorie")),
                     "beschreibung": s_(e.get("beschreibung"))} for e in k.get("externe") or [] if e.get("id")],
        "beziehungen": [{"id": s_(r.get("id")), "name": s_(r.get("name") or r.get("id")), "typ": s_(r.get("typ")),
                         "reife": s_(r.get("reife")), "von": s_(r.get("von")), "zu": s_(r.get("zu")),
                         "beschreibung": s_(r.get("beschreibung"))} for r in k.get("beziehungen") or [] if r.get("id")],
        "ablaeufe": [{"id": s_(a.get("id")), "name": s_(a.get("name") or a.get("id")), "reife": s_(a.get("reife")),
                      "betrifft": [s_(x) for x in a.get("betrifft") or [] if x],
                      "schritte": list(a.get("schritte") or []), "beschreibung": s_(a.get("beschreibung"))}
                     for a in k.get("ablaeufe") or [] if a.get("id")],
    }
    return subs, msgs, weitere


def _text(v) -> str:
    return str(v or "")


def _zelle(text: str) -> str:
    return " ".join(str(text or "").split()).replace("|", "/")


def _knoten(ids: list[str], reife: dict[str, str]) -> str:
    return ", ".join(f"`{i}`" + (f" ({reife[i]})" if reife.get(i) else "") for i in ids)


def _ids(ids: list[str]) -> str:
    return ", ".join(f"`{i}`" for i in ids if i)


def _schritte(schritte: list[dict]) -> str:
    """Schritte eines Ablaufs: "`ctx-a`: `msg-x` → `ctx-b`: `msg-y`"."""
    return " → ".join(": ".join(f"`{v}`" for v in (s.get("kontext"), s.get("nachricht")) if v) for s in schritte)


def _relationen(relationen: list[dict]) -> str:
    """Relationen eines Fachobjekts: "betrifft `obj-b` (0..n) · liegt-an `obj-c` (1..1)"."""
    return " · ".join(f"{_zelle(r.get('verb')) or 'bezieht sich auf'} `{r['ziel']}`"
                      + (f" ({_zelle(r.get('kardinalitaet'))})" if r.get("kardinalitaet") else "")
                      for r in relationen if r.get("ziel"))


def build_content(contexts: list[dict], subdomaenen: list[dict] | None = None,
                  nachrichten: list[dict] | None = None, weitere: dict[str, list[dict]] | None = None) -> str:
    import kanon
    R, fmt = kanon.regeln(), kanon.konfig().get("format") or "domain-atlas"
    today = date.today().isoformat()
    weitere = weitere or {}
    fm_lines = ["---", "type: contexts-index", "generated: true",
                f"source: {fmt}", f"count: {len(contexts)}",
                f"synced_at: {today}", "tags: [contexts, generated]", "---", ""]
    body = [GENERATED_NOTICE, "", f"# {R['kontexte_titel']}", "",
            f"> {len(contexts)} Bounded Contexts aus "
            f"{R['kontexte_quelle']} - ein Verzeichnis mit Kurzbeschreibungen für Chat und Suche, "
            f"die Wahrheit bleibt der Kanon. IDs landen als `atlas_id` im Frontmatter der "
            f"jeweiligen Entity (siehe `aufloesen.py`).", ""]
    if subdomaenen:
        n = {}
        for c in contexts:
            n[c["subdomain"]] = n.get(c["subdomain"], 0) + 1
        body += ["## Subdomänen", "", "| Subdomäne | Name | Kontexte | Art | Reife | Beschreibung |",
                 "|---|---|---|---|---|---|"]
        for s in sorted(subdomaenen, key=lambda s: s["name"].lower()):
            body.append(f"| `{s['id']}` | {_zelle(s['name'])} | {n.get(s['id'], 0)} | {_zelle(s.get('art'))} "
                        f"| {_zelle(s.get('reife'))} | {_zelle(s.get('beschreibung'))} |")
        body += ["", "## Kontexte", ""]
    body += ["| Kontext | Subdomain | Owner | Reife | Beschreibung |", "|---|---|---|---|---|"]
    for c in sorted(contexts, key=lambda c: c["name"].lower()):
        name = c["name"].replace("|", "/")
        body.append(f"| `{c['id']}` {name} | {c['subdomain']} | {c['owner']} | {_zelle(c.get('reife'))} "
                    f"| {_zelle(c.get('description'))} |")
    if nachrichten:
        body += ["", "## Nachrichten", "",
                 "> Was eine Kontextgrenze überquert: Typ, Reife, wer sendet (von) und wer empfängt (an). "
                 "Eine Kante mit eigener Reife steht in Klammern.", "",
                 "| Nachricht | Typ | Reife | von | an | Beschreibung |", "|---|---|---|---|---|---|"]
        for m in sorted(nachrichten, key=lambda m: m["name"].lower()):
            body.append(f"| `{m['id']}` {_zelle(m['name'])} | {m['typ']} | {m['reife']} "
                        f"| {_knoten(m['von'], m['kanten_reife'])} | {_knoten(m['an'], m['kanten_reife'])} "
                        f"| {_zelle(m.get('beschreibung'))} |")
    abschnitte = (
        ("objekte", "Fachobjekte", "| Objekt | Kontext | Stereotyp | Synonyme | Relationen | Definition |",
         lambda o: f"| `{o['id']}` {_zelle(o['name'])} | {_ids([o['kontext']])} | {_zelle(o.get('stereotyp'))} "
                   f"| {_zelle(', '.join(o['synonyme']))} | {_relationen(o.get('relationen') or [])} | {_zelle(o['definition'])} |"),
        ("teams", "Teams", "| Team | Beschreibung |",
         lambda t: f"| `{t['id']}` {_zelle(t['name'])} | {_zelle(t['beschreibung'])} |"),
        ("externe", "Externe", "| Externer | Kategorie | Beschreibung |",
         lambda e: f"| `{e['id']}` {_zelle(e['name'])} | {_zelle(e['kategorie'])} | {_zelle(e['beschreibung'])} |"),
        ("beziehungen", "Beziehungen", "| Beziehung | Typ | Reife | von | zu | Beschreibung |",
         lambda r: f"| `{r['id']}` {_zelle(r['name'])} | {_zelle(r['typ'])} | {_zelle(r['reife'])} | {_ids([r['von']])} "
                   f"| {_ids([r['zu']])} | {_zelle(r['beschreibung'])} |"),
        ("ablaeufe", "Abläufe", "| Ablauf | Reife | betrifft | Schritte | Beschreibung |",
         lambda a: f"| `{a['id']}` {_zelle(a['name'])} | {_zelle(a['reife'])} | {_ids(a['betrifft'])} "
                   f"| {_schritte(a['schritte'])} | {_zelle(a['beschreibung'])} |"),
    )
    for key, titel, kopf, zeile in abschnitte:
        items = weitere.get(key) or []
        if not items:
            continue
        spalten = kopf.count("|") - 1
        body += ["", f"## {titel}", "", kopf, "|" + "---|" * spalten]
        body += [zeile(x) for x in sorted(items, key=lambda x: (x["name"].lower(), x["id"]))]
    return "\n".join(fm_lines + body) + "\n"


def run(as_json: bool, dry_run: bool) -> int:
    contexts = load_contexts()
    if as_json:
        print(json.dumps({"count": len(contexts), "contexts": contexts},
                         ensure_ascii=False, indent=2))
        return 0
    import kanon
    print(f"Kontexte — {len(contexts)} Kontext(e) aus {kanon.regeln()['kontexte_quelle']}")
    if not contexts:
        print("[WARN] Keine Kontexte gefunden - Index wird nicht geschrieben.")
        return 1
    content = build_content(contexts, *load_landkarte())
    if dry_run:
        print(f"[DRY] Wuerde schreiben: {INDEX_PATH.relative_to(vp.VAULT)} "
              f"({len(content)} Byte)")
        return 0
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(content, encoding="utf-8", newline="\n")
    print(f"[OK] {INDEX_PATH.relative_to(vp.VAULT)} geschrieben "
          f"({len(contexts)} Kontexte).")
    return 0


def main() -> int:
    args = sys.argv[1:]
    return run("--json" in args, "--dry-run" in args)


if __name__ == "__main__":
    sys.exit(main())
