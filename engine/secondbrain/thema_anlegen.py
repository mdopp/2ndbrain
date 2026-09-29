#!/usr/bin/env python3
"""thema_anlegen.py - eine neue Themen-Seite unter entities/projects/ anlegen.

    2ndbrain thema-neu "Portal Nord" [--keywords portal,nord] [--slug portal-nord] [--dry-run]

Ohne Themen-Seite findet die Zuordnung von Terminen und Notizen kein Ziel.
`keywords:` im Frontmatter ist der Hebel fuer die Zuordnung: alles, was dort
steht, wird beim Titel-Match beruecksichtigt. Angelegt wird immer `kind: project`
(befristetes Projekt); Produkt-, Firmen- oder Bereichs-Themen stellt man danach im
Frontmatter um. Eine vorhandene Seite bleibt unveraendert.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp


def create(name: str, keywords: list[str], *, slug: str = "", dry_run: bool = False) -> Path | None:
    slug = slug or vp.slugify(name)
    if not slug:
        print("[ERROR] Kein verwertbarer Slug.", file=sys.stderr)
        return None
    path = vp.project_path(slug)
    if path.exists():
        print(f"[EXISTS] {path.relative_to(vp.VAULT)}")
        return path
    if dry_run:
        print(f"[DRY] Wuerde anlegen: {path.relative_to(vp.VAULT)}")
        return path

    today = date.today().isoformat()
    tmpl = vp.TEMPLATES_DIR / "project.md"
    fm = {
        "type": "project",
        "name": name,
        "status": "active",
        # project = befristet | product = produkt-<system> | account = firma-<firma> | area = Bereich
        "kind": "project",
        "scope": "internal",
        "aliases": [],
        # Dieses Feld steuert die automatische Meeting-Zuordnung
        "keywords": keywords,
        "created": today,
        "last_updated": today,
        "tags": ["project"],
    }
    body = (f"\n# {name}\n\n## Beschreibung\n\n<!-- Worum geht es? -->\n\n"
            f"## Kontext\n\n- **Systeme:** \n- **Beteiligte:** \n- **Zieltermin:** \n\n"
            f"## Event Log\n")
    if tmpl.is_file():
        raw = tmpl.read_text(encoding="utf-8")
        _, tbody = vp.split_frontmatter(raw)
        if tbody.strip():
            body = "\n" + tbody.replace("{{title}}", name).replace("{{date:YYYY-MM-DD}}", today)
            if "## Event Log" not in body:
                body = body.rstrip() + "\n\n## Event Log\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(vp.dump_frontmatter(fm, body), encoding="utf-8", newline="\n")
    vp.invalidate_entity_caches()     # neues Thema: Slug-/Alias-Zwischenspeicher verwerfen
    print(f"[CREATED] {path.relative_to(vp.VAULT)}")
    if keywords:
        print(f"          keywords: {', '.join(keywords)}")
    else:
        print("          Tipp: 'keywords:' im Frontmatter ergaenzen, damit Termine "
              "automatisch zugeordnet werden.")
    return path


def aus_kanon(atlas_id: str, *, dry_run: bool = False) -> str | None:
    """Thema zu einer Subdomaene des Kanons (Vorschlag "neu aus dem Atlas"): Name aus dem Kanon,
    Slug = ID ohne Praefix, verknuepft ueber `atlas_id` (samt gleichnamigem Team), eingeordnet wie
    die uebrigen Subdomaenen-Themen (haeufigstes `parent`), Bereich. Gibt es schon ein Thema zur
    Subdomaene, bleibt es. None, wenn der Kanon die ID nicht kennt."""
    from collections import Counter
    import begriffsindex as bi
    import kanon
    k = kanon.lade()
    sd = next((s for s in (k or {}).get("subdomaenen") or [] if s.get("id") == atlas_id), None)
    if sd is None:
        return None
    themen = bi.kanon_themen(k)
    if themen.get(atlas_id):
        return themen[atlas_id]
    basis = kanon.strip_prefix(atlas_id, fmt=k["format"])
    slug = vp.slugify(basis)
    teams = [str(t.get("id")) for t in k["teams"] if kanon.strip_prefix(str(t.get("id")), fmt=k["format"]) == basis]
    eltern = Counter(str(vp.read_frontmatter(vp.project_path(themen[s["id"]])).get("parent") or "")
                     for s in k["subdomaenen"] if themen.get(s.get("id")))
    parent = next((p for p, _ in eltern.most_common() if p), "")
    path = create(f"{sd.get('name') or basis} (Bereich)", [], slug=slug, dry_run=dry_run)
    if path is None or dry_run:
        return slug if path else None
    vp.update_frontmatter(path, {"kind": "area", "atlas_id": list(dict.fromkeys([atlas_id, *teams])),
                                 **({"parent": parent} if parent else {})})
    if sd.get("beschreibung"):
        text = path.read_text(encoding="utf-8")
        leer = re.search(r"^## Beschreibung\n+(<!--.*?-->\n)?", text, re.M | re.S)
        if leer:
            path.write_text(text[:leer.start()] + f"## Beschreibung\n\n{sd['beschreibung']}\n"
                            + text[leer.end():], encoding="utf-8", newline="\n")
    bi.save(bi.build())                  # der Begriffs-Index kennt das Thema sofort
    return slug


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        return 1
    name = args[0]
    keywords: list[str] = []
    if "--keywords" in args:
        i = args.index("--keywords")
        if i + 1 < len(args):
            keywords = [k.strip() for k in args[i + 1].split(",") if k.strip()]
    slug = ""
    if "--slug" in args:
        i = args.index("--slug")
        if i + 1 < len(args):
            slug = vp.slugify(args[i + 1])
    return 0 if create(name, keywords, slug=slug, dry_run="--dry-run" in args) else 1


if __name__ == "__main__":
    sys.exit(main())
