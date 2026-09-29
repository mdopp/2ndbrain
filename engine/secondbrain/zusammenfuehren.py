#!/usr/bin/env python3
"""zusammenfuehren.py - zwei Entity-Dateien (Dubletten) zu einer zusammenfuehren.

Genutzt von `rueckfragen.py`, wenn eine Klaerung 'ambiguous_person_file' beantwortet
wird (`2ndbrain rueckfragen resolve <id> --as <slug>` oder per Haken in der Karte).
Kein eigener Befehl. Nur einen Slug aendern, ohne Dublette: umbenennen.py.

Merge-only: `drop` wird in `keep` gefaltet, nichts geht verloren.
  - Frontmatter: fehlende Felder in `keep` werden aus `drop` uebernommen,
    Aliasse und Schreibweisen vereinigt (inkl. `drop`s `name:` als Alias, falls abweichend).
  - Body: '## Referenzen' zeilenweise dedupliziert und ergaenzt; alle
    uebrigen Abschnitte, die in `keep` fehlen, landen unter einer
    Sammelueberschrift '## Übernommen aus „drop-slug“ (zusammengeführt <Datum>)' -
    lieber sichtbar doppelt gehalten als still verworfen. Automatische Bloecke
    und leere Abschnitte werden nicht mitgenommen.
  - Wikilinks/@mentions vault-weit von drop-slug auf keep-slug umgeschrieben
    (`umbenennen.update_links_only`).
  - `drop` geht nach `.trash/zusammengefuehrt/` (der Inhalt steckt jetzt in `keep`;
    geloescht wird nichts).

Idempotent: existiert `drop` beim zweiten Aufruf nicht mehr (schon
zusammengefuehrt), ist es ein No-op.
"""
from __future__ import annotations

import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import umbenennen as ren
import vault_paths as vp

REFERENCES_HEADING = "## Referenzen"
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_FM_COPY_SKIP = {"created", "last_updated", "name", "type", "aliases", "tags"}


def _split_sections(body: str) -> dict[str, tuple[str, str]]:
    """{heading_lower: (heading_original, block_text_ohne_ueberschrift)}."""
    matches = list(_HEADING_RE.finditer(body))
    out = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        heading = m.group(1).strip()
        out[heading.lower()] = (heading, body[start:end])
    return out


def merge_entity_files(keep: Path, drop: Path, *, type_override: str | None = None) -> dict:
    """Foldet `drop` in `keep`. Gibt eine Zusammenfassung fuer den Audit-Log
    zurueck. Idempotent (siehe Modul-Docstring)."""
    result = {"keep": keep.stem, "drop": drop.stem, "fields_added": [],
              "aliases_added": [], "sections_added": [], "references_added": 0,
              "links_rewritten": 0, "skipped": False}
    if not drop.exists():
        result["skipped"] = True
        result["reason"] = "drop existiert nicht (mehr) - vermutlich schon zusammengefuehrt"
        return result
    if not keep.exists():
        # Kein echtes Duplikat (mehr) - drop wird schlicht zu keep.
        drop.rename(keep)
        result["skipped"] = True
        result["reason"] = "keep fehlte - drop wurde umbenannt"
        return result
    if keep.resolve() == drop.resolve():
        result["skipped"] = True
        result["reason"] = "keep und drop sind dieselbe Datei"
        return result

    keep_text = keep.read_text(encoding="utf-8")
    drop_text = drop.read_text(encoding="utf-8")
    keep_fm, keep_body = vp.split_frontmatter(keep_text)
    drop_fm, drop_body = vp.split_frontmatter(drop_text)
    changed = False

    # --- Frontmatter: fehlende Felder uebernehmen ---
    for k, v in drop_fm.items():
        if k in _FM_COPY_SKIP or not v:
            continue
        if not keep_fm.get(k):
            keep_fm[k] = v
            result["fields_added"].append(k)
            changed = True

    # --- Aliasse vereinigen ---
    aliases = keep_fm.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    aliases = list(aliases)
    known_lower = {a.lower() for a in aliases} | {str(keep_fm.get("name") or "").lower()}
    for cand in [drop_fm.get("name"), *(drop_fm.get("aliases") or [])]:
        if not cand:
            continue
        cand = str(cand).strip()
        if cand and cand.lower() not in known_lower:
            aliases.append(cand)
            known_lower.add(cand.lower())
            result["aliases_added"].append(cand)
            changed = True
    if aliases:
        keep_fm["aliases"] = aliases

    # --- Schreibweisen (schreibweisen.py) vereinigen ---
    def _sw(fm: dict) -> list[str]:
        v = fm.get("schreibweisen") or []
        return [v] if isinstance(v, str) else [str(x) for x in v]
    schreibweisen = _sw(keep_fm)
    for cand in _sw(drop_fm):
        if cand.strip() and cand.casefold() not in {x.casefold() for x in schreibweisen}:
            schreibweisen.append(cand.strip())
            changed = True
    if schreibweisen:
        keep_fm["schreibweisen"] = schreibweisen

    if type_override and keep_fm.get("type") != type_override:
        keep_fm["type"] = type_override
        changed = True

    # --- Body: '## Referenzen' zeilenweise dedupliziert ergaenzen ---
    new_body = keep_body
    drop_sections = _split_sections(drop_body)
    keep_sections = _split_sections(keep_body)
    ref = drop_sections.get("referenzen")
    if ref:
        drop_lines = [l for l in ref[1].splitlines() if l.strip().startswith("- ")]
        fresh_refs = [l for l in drop_lines if l not in new_body]
        if fresh_refs:
            block = "\n".join(fresh_refs)
            if REFERENCES_HEADING in new_body:
                new_body = new_body.replace(REFERENCES_HEADING, f"{REFERENCES_HEADING}\n{block}", 1)
            else:
                new_body = new_body.rstrip() + f"\n\n{REFERENCES_HEADING}\n{block}\n"
            result["references_added"] = len(fresh_refs)
            changed = True

    # --- Body: alle uebrigen Abschnitte, die in keep fehlen ---
    # Nicht mitnehmen: automatische Bloecke (werden neu erzeugt - eine einzelne
    # End-Marke braechte sonst den naechsten Lauf durcheinander) und leere Abschnitte
    # ("-" aus der Vorlage). Die Ueberschrift nennt drop ohne Link: die Link-Umbiegung
    # unten machte aus [[drop-slug]] sonst einen Link der Seite auf sich selbst.
    missing = []
    for key, (heading, block) in drop_sections.items():
        if key == "referenzen":
            continue
        if key in keep_sections:
            continue
        block = re.sub(r"<!-- *[\w-]+-auto:start *-->.*?<!-- *[\w-]+-auto:end *-->", "", block, flags=re.S)
        block = re.sub(r"<!-- *[\w-]+-auto:(?:start|end) *-->", "", block).strip()
        if "(automatisch)" in heading or not block.strip(" -\n"):
            continue
        missing.append(f"### {heading}\n\n{block}")
    if missing:
        new_body = new_body.rstrip() + (
            f"\n\n## Übernommen aus „{drop.stem}“ (zusammengeführt {date.today().strftime('%d.%m.%Y')})\n\n"
            + "\n\n".join(missing) + "\n")
        result["sections_added"] = len(missing)
        changed = True

    if changed:
        keep_fm["last_updated"] = date.today().isoformat()
        keep.write_text(vp.dump_frontmatter(keep_fm, new_body), encoding="utf-8", newline="\n")

    # --- Wikilinks/@mentions vault-weit umschreiben, dann drop in den Papierkorb ---
    if drop.stem != keep.stem:
        log = ren.update_links_only(drop.stem, keep.stem)
        result["links_rewritten"] = len(log)
        result["log"] = log
    result["papierkorb"] = _in_papierkorb(drop)
    return result


def _in_papierkorb(f: Path) -> str:
    """Die zusammengefuehrte Datei nach .trash/zusammengefuehrt/ - geloescht wird nichts."""
    ziel_dir = vp.VAULT / ".trash" / "zusammengefuehrt"
    ziel_dir.mkdir(parents=True, exist_ok=True)
    ziel = ziel_dir / f.name
    if ziel.exists():
        ziel = ziel_dir / f"{f.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{f.suffix}"
    shutil.move(str(f), str(ziel))
    return ziel.relative_to(vp.VAULT).as_posix()
