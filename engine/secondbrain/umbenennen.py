#!/usr/bin/env python3
"""umbenennen.py - den Slug eines Themas oder einer Entity vault-weit aendern.

Sucht die Datei unter entities/projects, people, teams, companies und systems und aendert:
1. den Dateinamen,
2. `name`/`title` im Frontmatter der Datei selbst - nur dort, wo der alte Slug steht,
3. alle Wikilinks [[alter-slug]] vault-weit, auch in Frontmatter-Feldern
   (lead, team, company, owner_team, systems), und @alter-slug-Erwaehnungen.

Aliasse und Link-Anzeigetexte ([[slug|Anzeige]]) bleiben, ebenso alles in Punkt-Ordnern
(.obsidian, .trash, .2ndbrain ...). Zwei Dateien zu einer machen: zusammenfuehren.py.

    2ndbrain umbenennen <alter-slug> <neuer-slug> [--dry-run]
"""
import re, sys
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import vault_paths as vp

VAULT = vp.VAULT


def find_entity_file(slug: str) -> Path | None:
    """Findet die Datei zu einem Slug unter entities/ (projects, people, teams, companies, systems)."""
    candidates = [
        vp.PROJECTS_DIR / f"{slug}.md",
        *[VAULT / "entities" / cat / f"{slug}.md"
          for cat in ("people", "teams", "companies", "systems")],
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def update_links_only(old_slug: str, new_slug: str, dry_run: bool = False) -> list[str]:
    """Nur Wikilinks/@mentions vault-weit umschreiben, ohne eine Datei
    umzubenennen - Baustein von `rename_entity()`, aber auch eigenstaendig
    gebraucht (z.B. `zusammenfuehren.py`, wo die Zieldatei schon existiert und
    nur die Verweise auf die geloeschte `drop`-Datei umgebogen werden muessen).
    """
    log = []
    # [[slug]], [[slug|Anzeige]], [[slug#Abschnitt]] - Anzeige/Anker bleiben.
    # Frontmatter-Werte in Anfuehrungszeichen sind darin enthalten.
    patterns = [
        (rf"\[\[{re.escape(old_slug)}(?=[\]|#])", f"[[{new_slug}"),
        (rf"\[\[proj-{re.escape(old_slug)}(?=[\]|#])", f"[[proj-{new_slug}"),
    ]
    # @slug nur als ganzes Token: sonst wird aus '@max-muster' beim Merge
    # 'max' -> 'max-muster' ein '@max-muster-muster'.
    mention = re.compile(rf"@{re.escape(old_slug)}(?![\w-])")

    # Nur, was Obsidian sieht: keine Punkt-Ordner (.trash, .obsidian, .2ndbrain ...)
    md_files = [f for f in VAULT.rglob("*.md")
                if not any(part.startswith(".") for part in f.relative_to(VAULT).parts)]
    for md in md_files:
        try:
            content = md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        original = content
        for pat, repl in patterns:
            content = re.sub(pat, repl, content)

        # Auch @old-slug in Action-Items
        content = mention.sub(f"@{new_slug}", content)

        if content != original:
            count = sum(len(re.findall(p, original)) for p, r in patterns)
            count += len(mention.findall(original))
            log.append(f"[UPDATE] {md.relative_to(VAULT)} ({count} Referenz(en))")
            if not dry_run:
                md.write_text(content, encoding="utf-8", newline="\n")

    return log


def rename_entity(old_slug: str, new_slug: str, dry_run: bool = False) -> list[str]:
    """Fuehrt die Umbenennung durch. Gibt Log-Zeilen zurueck."""
    log = []

    # 1. Datei finden und umbenennen
    old_file = find_entity_file(old_slug)
    if not old_file:
        log.append(f"[ERROR] Keine Datei gefunden fuer Slug: {old_slug}")
        return log

    new_file = old_file.parent / old_file.name.replace(old_slug, new_slug)
    log.append(f"[RENAME] {old_file.relative_to(VAULT)} -> {new_file.relative_to(VAULT)}")
    if not dry_run:
        # Frontmatter der Datei selbst anpassen
        content = old_file.read_text(encoding="utf-8")
        # name/title: alten Slug durch den neuen ersetzen
        content = re.sub(
            rf'^(name|title):\s*.*{re.escape(old_slug)}.*$',
            lambda m: m.group(0).replace(old_slug, new_slug),
            content, flags=re.MULTILINE
        )
        new_file.write_text(content, encoding="utf-8", newline="\n")
        if old_file != new_file:
            old_file.unlink()

    # 2. Alle Vault-Dateien durchsuchen und Referenzen aktualisieren
    log.extend(update_links_only(old_slug, new_slug, dry_run=dry_run))
    return log


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python umbenennen.py <old-slug> <new-slug> [--dry-run]")
        sys.exit(1)
    old = sys.argv[1]
    new = sys.argv[2]
    dry = "--dry-run" in sys.argv
    if dry:
        print("=== DRY RUN ===")
    log = rename_entity(old, new, dry_run=dry)
    for line in log:
        print(line)
    if not log:
        print("Keine Aenderungen.")
