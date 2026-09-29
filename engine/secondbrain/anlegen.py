#!/usr/bin/env python3
"""anlegen.py - Personen, Teams und Firmen als Entity-Datei anlegen.

So hat jede Rueckfrage "Unbekannte Person" ein anlegbares Ziel - sonst liesse sie
sich nicht aufloesen, und jeder Versuch erzeugte eine neue Rueckfrage. Geprueft
wird nur der Slug: eine vorhandene Person mit anderem Slug erkennt es nicht.
Themen legt thema_anlegen.py an, Reihen reihen.py.

    2ndbrain person-neu "Max Mustermann" [--role "Head of X"] [--aliases "M. Mustermann"]
    2ndbrain team-neu "Team Nord"
    2ndbrain firma-neu "Beispiel und Partner"
    (weitere Felder: --company, --organization, --team; Vorschau: --dry-run)
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

TYPE_BY_CATEGORY = {"people": "person", "teams": "team", "companies": "company"}


def first_name_alias(name: str, existing: list[str] | None = None) -> list[str]:
    """Setzt bewusst KEINEN Vornamen als Alias.

    Vornamen sind nicht eindeutig ("Max" koennen viele sein). Ein Alias
    wuerde jeden "Max" still auf eine einzige Person abbilden. Die Aufloesung
    von Vornamen macht `aufloesen._resolve_person()` - eindeutig ->
    Treffer, mehrdeutig -> Klaerung; die Zuordnung entscheidet der Kontext.
    Die Funktion bleibt als gemeinsamer Einstiegspunkt fuer alle Anleger
    (`create()` hier, `uebernehmen.apply_entities()`).
    """
    return list(existing or [])


def create(category: str, name: str, *, slug: str = "", aliases: list[str] | None = None,
           meta: dict | None = None, dry_run: bool = False) -> Path | None:
    if category not in TYPE_BY_CATEGORY:
        print(f"[ERROR] Kategorie '{category}' unbekannt. "
              f"Erlaubt: {', '.join(TYPE_BY_CATEGORY)}", file=sys.stderr)
        return None
    slug = slug or vp.slugify(name)
    if not slug:
        print("[ERROR] Kein verwertbarer Slug.", file=sys.stderr)
        return None

    path = vp.CATEGORY_DIRS[category] / f"{slug}.md"
    if path.exists():
        print(f"[EXISTS] entities/{category}/{slug}.md")
        return path
    if dry_run:
        print(f"[DRY] Wuerde anlegen: entities/{category}/{slug}.md")
        return path

    al = list(aliases or [])
    if category == "people":
        al = first_name_alias(name, al)

    today = date.today().isoformat()
    fm = {"type": TYPE_BY_CATEGORY[category], "name": name, "aliases": al,
          **(meta or {}), "created": today, "last_updated": today,
          "tags": [TYPE_BY_CATEGORY[category]]}
    body = f"\n# {name}\n\n## Beschreibung\n\n<!-- Rolle, Zustaendigkeit, Kontext -->\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(vp.dump_frontmatter(fm, body), encoding="utf-8", newline="\n")
    vp.invalidate_entity_caches()     # neue Entitaet: Slug-/Alias-Zwischenspeicher verwerfen
    print(f"[CREATED] entities/{category}/{slug}.md")
    if al:
        print(f"          aliases: {', '.join(al)}")
    return path


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 1
    category, name = args[0], args[1]
    rest = args[2:]
    aliases, meta = [], {}
    if "--aliases" in rest:
        aliases = [a.strip() for a in rest[rest.index("--aliases") + 1].split(",") if a.strip()]
    for key in ("role", "company", "organization", "team"):
        flag = f"--{key}"
        if flag in rest:
            meta[key] = rest[rest.index(flag) + 1]
    return 0 if create(category, name, aliases=aliases, meta=meta,
                       dry_run="--dry-run" in rest) else 1


if __name__ == "__main__":
    sys.exit(main())
