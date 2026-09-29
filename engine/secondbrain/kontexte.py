#!/usr/bin/env python3
"""kontexte.py - schreibt das Kontext-Verzeichnis `entities/contexts/_index.md` aus dem Kanon.

Eine reine Verweisliste der Bounded Contexts (ID, Name, Subdomaene, Owner), bei jedem Lauf
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


def build_content(contexts: list[dict]) -> str:
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
            f"jeweiligen Entity (siehe `aufloesen.py`).", "",
            "| Kontext | Subdomain | Owner |", "|---|---|---|"]
    for c in sorted(contexts, key=lambda c: c["name"].lower()):
        name = c["name"].replace("|", "/")
        body.append(f"| `{c['id']}` {name} | {c['subdomain']} | {c['owner']} |")
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
    content = build_content(contexts)
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
