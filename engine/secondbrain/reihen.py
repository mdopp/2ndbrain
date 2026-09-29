#!/usr/bin/env python3
"""reihen.py - Reihen: Gremien und wiederkehrende Formate, je eine Forum-Datei in `entities/forums/`.

Zweite Achse neben dem Projekt:

  Projekt = *was* getan wird        (Portal-Relaunch)
  Forum   = *wo* berichtet wird     (Architektur-Board, Weekly Team Nord,
                                     Jour Fixe mit Anna, Checkin A/B)

Ein Termin hat beides. Beschluesse eines Boards gehoeren dem Board, nicht dem
Projekt, ueber das gerade berichtet wurde - ohne diese Achse landete
Gremienwissen in Projekten oder nirgends.

Ein Forum haelt ausserdem:
  - `## Standard-Agenda`  Punkte, die bei jedem Termin der Reihe mitkommen
  - `## Entwicklung`      Was an der Gruppe selbst verbessert werden soll -
                          kommt als Themen mit ins Briefing
  - `## Event Log`        Beschluesse und Risiken des Gremiums
Im Frontmatter die fuer die Reihe bestaetigten Themen (`reports_on`, `project`;
`kein_thema` = bewusst ohne) und beim Jourfix das Gegenueber (`mit`) - gesetzt ueber themen.py.

    2ndbrain reihe-neu "Weekly Team Nord" --kind weekly --keywords nord
    2ndbrain reihen                 # Uebersicht
    2ndbrain reihen --derive        # aus vorhandenen Meetings vorschlagen (--apply legt an)
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agenda as ag
import vault_paths as vp

VALID_KINDS = ("board", "steering", "weekly", "monthly", "jourfix", "checkin",
               "community", "workshop", "review", "abstimmung", "other")
MIN_OCCURRENCES_FOR_FORUM = 2

# Meeting-Typ -> Forum-Art
KIND_BY_MEETING_TYPE = {
    "weekly": "weekly", "monthly": "monthly", "jourfix": "jourfix",
    "checkin": "checkin", "steering": "steering", "workshop": "workshop",
    "review": "review", "abstimmung": "abstimmung", "projekt": "other",
    "other": "other",
}


def forum_key(title: str) -> str:
    """Slug des Forums aus dem Termintitel - identisch zu `agenda.series_key`."""
    return ag.series_key(title)


def read(slug: str) -> dict:
    p = vp.forum_path(slug)
    return vp.read_frontmatter(p) if p.is_file() else {}


def exists(slug: str) -> bool:
    return vp.forum_path(slug).is_file()


def _section(body: str, heading: str) -> list[str]:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$", body, re.MULTILINE)
    if not m:
        return []
    nxt = re.search(r"^##\s+\S", body[m.end():], re.MULTILINE)
    block = body[m.end():m.end() + nxt.start()] if nxt else body[m.end():]
    out = []
    for line in block.splitlines():
        t = line.strip()
        if t.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+[.)]\s", t):
            item = re.sub(r"^(?:[-*+]|\d+[.)])\s*(?:\[[ xX]\]\s*)?", "", t).strip()
            if item and not item.startswith("<!--"):
                out.append(item)
    return out


def standard_agenda(slug: str) -> list[str]:
    p = vp.forum_path(slug)
    if not p.is_file():
        return []
    return _section(vp.split_frontmatter(p.read_text(encoding="utf-8"))[1], "Standard-Agenda")


def development_items(slug: str) -> list[str]:
    """Punkte aus `## Entwicklung` - was an der Gruppe verbessert werden soll."""
    p = vp.forum_path(slug)
    if not p.is_file():
        return []
    return _section(vp.split_frontmatter(p.read_text(encoding="utf-8"))[1], "Entwicklung")


def create(name: str, *, slug: str = "", kind: str = "other", cadence: str = "",
           keywords: list[str] | None = None, members: list[str] | None = None,
           reports_on: list[str] | None = None, dry_run: bool = False) -> Path | None:
    slug = slug or forum_key(name)
    if not slug:
        print("[ERROR] Kein verwertbarer Slug.", file=sys.stderr)
        return None
    path = vp.forum_path(slug)
    if path.exists():
        print(f"[EXISTS] entities/forums/{slug}.md")
        return path
    if dry_run:
        print(f"[DRY] Wuerde anlegen: entities/forums/{slug}.md")
        return path

    if kind not in VALID_KINDS:
        kind = "other"
    today = date.today().isoformat()
    fm = {
        "type": "forum", "name": name, "kind": kind, "cadence": cadence,
        "members": members or [], "reports_on": reports_on or [],
        "keywords": keywords or [], "maturity": "neu", "status": "active",
        "created": today, "last_updated": today, "tags": ["forum"],
    }
    body = (f"\n# {name}\n\n"
            "## Zweck\n\n<!-- Worüber wird hier berichtet, welche Entscheidungen "
            "fallen hier? Ein Satz. -->\n\n"
            "## Standard-Agenda\n\n<!-- Punkte, die bei jedem Termin mitkommen. -->\n\n"
            "## Entwicklung\n\n<!-- Was soll sich an dieser Gruppe verbessern? "
            "Welche Rolle fehlt? Zielzustand? -->\n\n"
            "## Event Log\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(vp.dump_frontmatter(fm, body), encoding="utf-8", newline="\n")
    vp.invalidate_entity_caches()     # neues Gremium: Slug-/Alias-Zwischenspeicher verwerfen
    print(f"[CREATED] entities/forums/{slug}.md (kind: {kind})")
    return path


def derive_candidates(all_meetings: list[dict]) -> list[dict]:
    """Forum-Kandidaten aus vorhandenen Meetings ableiten.

    Ein Titel, der mehrfach auftaucht (nach Entfernen von Datum/Version), ist ein
    wiederkehrendes Format - also ein Forum.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in all_meetings:
        title = str(m.get("title") or "")
        if not title or re.match(r"^pasted[- ]image|^screenshot", title, re.I):
            continue
        groups[forum_key(title)].append(m)

    out = []
    for slug, ms in groups.items():
        if exists(slug):
            continue
        # Ueber **verschiedene Tage** wiederkehrend. Zwei Dateien vom selben Tag
        # sind Dubletten (derselbe Termin doppelt importiert), kein Format.
        distinct_days = {str(m.get("date", ""))[:10] for m in ms if m.get("date")}
        if len(distinct_days) < MIN_OCCURRENCES_FOR_FORUM:
            continue
        ms.sort(key=lambda x: str(x.get("date", "")))
        types = Counter(m.get("type") or ag.detect_meeting_type(m.get("title", "")) for m in ms)
        top_type = types.most_common(1)[0][0]
        dates = [str(m.get("date", ""))[:10] for m in ms if m.get("date")]
        out.append({
            "slug": slug,
            "name": ms[-1]["title"],
            "kind": KIND_BY_MEETING_TYPE.get(top_type, "other"),
            "occurrences": len(distinct_days),
            "files": len(ms),
            "first": dates[0] if dates else "",
            "last": dates[-1] if dates else "",
            "keywords": sorted({w for w in ag.normalize_title(slug.replace("-", " ")).split()
                                if len(w) > 3})[:6],
        })
    out.sort(key=lambda c: -c["occurrences"])
    return out


def main() -> int:
    args = sys.argv[1:]
    import vorbereiten

    if "--neu" in args:
        rest = [a for a in args if a != "--neu"]
        name = rest[0] if rest and not rest[0].startswith("--") else ""
        if not name:
            print('Verwendung: 2ndbrain reihe-neu "<Name>" [--kind weekly] [--keywords a,b] [--dry-run]')
            return 1
        kind = rest[rest.index("--kind") + 1] if "--kind" in rest else "other"
        kws = ([k.strip() for k in rest[rest.index("--keywords") + 1].split(",") if k.strip()]
               if "--keywords" in rest else [])
        create(name, kind=kind, keywords=kws, dry_run="--dry-run" in rest)
        return 0

    if "--derive" in args:
        cands = derive_candidates(vorbereiten.load_meeting_files())
        apply = "--apply" in args
        print(f"Forum-Kandidaten aus vorhandenen Meetings: {len(cands)}"
              + ("" if apply else "   [Vorschau]"))
        for c in cands[:40]:
            print(f"  {c['occurrences']:3}x  {c['kind']:11} {c['slug'][:46]:48} "
                  f"{c['first']}..{c['last']}")
            if apply:
                create(c["name"], slug=c["slug"], kind=c["kind"], keywords=c["keywords"])
        if not apply:
            print("\n  Anlegen mit:  2ndbrain reihen --derive --apply")
        return 0

    rows = list(vp.iter_forums())
    if not rows:
        print("Keine Foren angelegt.")
        print("  aus Terminen ableiten:  2ndbrain reihen --derive")
        print("  einzeln anlegen:        2ndbrain reihe-neu \"<Name>\" --kind weekly")
        return 0
    print(f"{len(rows)} Forum/Foren:")
    for slug, path, fm in rows:
        dev = len(development_items(slug))
        sa = len(standard_agenda(slug))
        print(f"  {str(fm.get('kind','?')):11} {slug[:44]:46} "
              f"Agenda={sa} Entwicklung={dev} maturity={fm.get('maturity','?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
