#!/usr/bin/env python3
"""kontexte.py - schreibt das Kontext-Verzeichnis `entities/contexts/_index.md` aus dem Kanon.

Eine reine Verweisliste der Bounded Contexts (ID, Name, Subdomaene, Owner), dazu die Subdomaenen
und die Nachrichten zwischen den Kontexten (Typ, Reife, von, an) - daraus zeichnet der Chat im
Plugin, wie Kontexte zusammenspielen, auch am Handy, wo der Kanon selbst fehlt. Bei jedem Lauf
ueberschrieben, nie von Hand gepflegt. Bewusst kein Spiegeln: eine Datei je Kontext waere ein
zweiter Datenbestand, der mit dem Kanon auseinanderlaeuft. Die IDs selbst stehen als
`atlas_id` im Frontmatter der betroffenen Entities (`uebernehmen.apply_entities()` ueber
aufloesen.py) - das hier ist nur der Index, keine Aufloesung.

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
FASSUNG = "landkarte-2"

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
             "description": str(c.get("beschreibung") or "").replace("\n", " ").strip()}
            for c in k["kontexte"]]


def load_landkarte() -> tuple[list[dict], list[dict]]:
    """Subdomaenen und Nachrichten aus dem Kanon - fuer die Abschnitte unter der Kontext-Liste.
    Das Plugin liest sie hier (auch am Handy, wo der Kanon selbst fehlt) und zeichnet daraus, wie
    Kontexte zusammenspielen."""
    import kanon
    k = kanon.lade()
    if not k:
        return [], []
    subs = [{"id": str(s.get("id") or ""), "name": str(s.get("name") or s.get("id") or "")}
            for s in k.get("subdomaenen") or [] if s.get("id")]
    msgs = [{"id": str(m.get("id") or ""), "name": str(m.get("name") or m.get("id") or ""),
             "typ": str(m.get("typ") or ""), "reife": str(m.get("reife") or ""),
             "von": list(m.get("produzenten") or []), "an": list(m.get("konsumenten") or []),
             "kanten_reife": dict(m.get("kanten_reife") or {})}
            for m in k.get("nachrichten") or [] if m.get("id")]
    return subs, msgs


def _zelle(text: str) -> str:
    return " ".join(str(text or "").split()).replace("|", "/")


def _knoten(ids: list[str], reife: dict[str, str]) -> str:
    return ", ".join(f"`{i}`" + (f" ({reife[i]})" if reife.get(i) else "") for i in ids)


def build_content(contexts: list[dict], subdomaenen: list[dict] | None = None,
                  nachrichten: list[dict] | None = None) -> str:
    import kanon
    R, fmt = kanon.regeln(), kanon.konfig().get("format") or "domain-atlas"
    today = date.today().isoformat()
    fm_lines = ["---", "type: contexts-index", "generated: true",
                f"source: {fmt}", f"count: {len(contexts)}",
                f"synced_at: {today}", "tags: [contexts, generated]", "---", ""]
    body = [GENERATED_NOTICE, "", f"# {R['kontexte_titel']}", "",
            f"> {len(contexts)} Bounded Contexts aus "
            f"{R['kontexte_quelle']} - reine Verweisliste, kein "
            f"Spiegel. IDs landen als `atlas_id` im Frontmatter der "
            f"jeweiligen Entity (siehe `aufloesen.py`).", ""]
    if subdomaenen:
        n = {}
        for c in contexts:
            n[c["subdomain"]] = n.get(c["subdomain"], 0) + 1
        body += ["## Subdomänen", "", "| Subdomäne | Name | Kontexte |", "|---|---|---|"]
        for s in sorted(subdomaenen, key=lambda s: s["name"].lower()):
            body.append(f"| `{s['id']}` | {_zelle(s['name'])} | {n.get(s['id'], 0)} |")
        body += ["", "## Kontexte", ""]
    body += ["| Kontext | Subdomain | Owner |", "|---|---|---|"]
    for c in sorted(contexts, key=lambda c: c["name"].lower()):
        name = c["name"].replace("|", "/")
        body.append(f"| `{c['id']}` {name} | {c['subdomain']} | {c['owner']} |")
    if nachrichten:
        body += ["", "## Nachrichten", "",
                 "> Was eine Kontextgrenze überquert: Typ, Reife, wer sendet (von) und wer empfängt (an). "
                 "Eine Kante mit eigener Reife steht in Klammern.", "",
                 "| Nachricht | Typ | Reife | von | an |", "|---|---|---|---|---|"]
        for m in sorted(nachrichten, key=lambda m: m["name"].lower()):
            body.append(f"| `{m['id']}` {_zelle(m['name'])} | {m['typ']} | {m['reife']} "
                        f"| {_knoten(m['von'], m['kanten_reife'])} | {_knoten(m['an'], m['kanten_reife'])} |")
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
