#!/usr/bin/env python3
"""altbestand.py - Alt-Aufgaben im naechsten Termin des Themas klaeren (`2ndbrain altbestand`).

Uebergang: Alt-Aufgaben aus dem frueheren Aufgaben-Format stehen je Thema im
Unterabschnitt `### Altbestand – im nächsten Termin prüfen` unter `## Offene Punkte`
(aufgaben.py: `Task.pruefen`). Alles vorab durchzugehen waere ermuedend und ohne
Kontext - geklaert wird deshalb dort, wo man ohnehin im Thema ist:

  1. Die Vorbereitung (vorbereiten.py) legt den Altbestand im naechsten Termin zum
     Thema vor: eine Dataview-Liste (abhaken wirkt direkt im Thema), gruppiert
     nach offen / als erledigt uebernommen / verworfen. Ein Jourfix/1:1 zeigt den
     Altbestand der Person ueber alle Themen.
  2. Ist dieser Termin vorbei und nachbereitet, gilt der Rest als geprueft
     (`--settle`, Schritt `altbestand` der Automatik): der Unterabschnitt wird aufgeloest
     (die Punkte bleiben als normale Punkte stehen), das Event Log bekommt
     einen Eintrag, und in der Meeting-Notiz ersetzt das Ergebnis die Live-Liste.

Ein Termin ohne Nachbereitung (ausgefallen, keine Notizen) loest nichts auf -
dann legt der naechste Termin den Rest erneut vor. Neuer Altbestand entsteht nicht;
ist der vorhandene geklaert oder archiviert, entfaellt das Modul.

    2ndbrain altbestand                  # Uebersicht: Themen, naechster Termin
    2ndbrain altbestand --settle         # nachbereitete Termine auswerten
    2ndbrain altbestand --geprueft SLUG  # Thema von Hand als geprueft markieren
        [--dry-run] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import vault_paths as vp

MARK_RE = re.compile(r"<!-- altbestand:(?P<slug>[a-z0-9-]+) -->\n.*?<!-- altbestand:end -->\n?", re.S)
MARK_END = "<!-- altbestand:end -->"
GROUPS = {" ": "① offen – noch aktuell?", "x": "② als erledigt übernommen – stimmt das?",
          "-": "③ verworfen"}
SYMBOL = {"offen": "⏳", "erledigt": "✅", "verworfen": "🗑"}
_PROCESSED_STATUS = {"nachbereitet", "done", "processed"}


def _de(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}" if len(iso or "") >= 10 else iso


def _topic_files():
    for d in (vp.PROJECTS_DIR, vp.FORUMS_DIR):
        if d.is_dir():
            yield from sorted(f for f in d.glob("*.md") if vp._usable(f))


def topic_path(slug: str) -> Path | None:
    for d in (vp.PROJECTS_DIR, vp.FORUMS_DIR):
        p = d / f"{slug}.md"
        if p.is_file():
            return p
    return None


def items(text: str, slug: str = "") -> list[tk.Task]:
    """Punkte im Altbestand einer Themen-Datei (alle Status)."""
    return [t for t in tk.tasks_in_text(text, "topic", stem=slug) if t.pruefen]


def counts(tasks: list[tk.Task], today: str | None = None) -> dict:
    today = today or date.today().isoformat()
    return {"offen": sum(1 for t in tasks if t.is_open),
            "erledigt": sum(1 for t in tasks if t.status in ("x", "X")),
            "verworfen": sum(1 for t in tasks if t.status == "-"),
            "ueberfaellig": sum(1 for t in tasks if t.overdue(today))}


def pending(today: str | None = None) -> dict[str, dict]:
    """{slug: {path, offen, erledigt, verworfen, ueberfaellig}} - Themen mit Altbestand."""
    out = {}
    for f in _topic_files():
        its = items(f.read_text(encoding="utf-8"), f.stem)
        if its:
            out[f.stem] = {"path": f, **counts(its, today)}
    return out


# ------------------------------------------------------------ Vorbereitung

def prep_block(slug: str, path: Path, c: dict, title: str = "") -> list[str]:
    """Abschnitt fuer `## Vorbereitung` (vorbereiten.py): Live-Liste zum Abhaken."""
    folder = path.parent.relative_to(vp.VAULT).as_posix()
    total = c["offen"] + c["erledigt"] + c["verworfen"]
    head = f"### Altbestand klären ({total} Punkte"
    head += f", {c['ueberfaellig']} mit verstrichener Frist)" if c.get("ueberfaellig") else ")"
    group = ('choice(status = "x", "{x}", choice(status = "-", "{d}", "{o}"))'
             .format(x=GROUPS["x"], d=GROUPS["-"], o=GROUPS[" "]))
    return [
        f"<!-- altbestand:{slug} -->", head, "",
        f"Aus den alten Aufgaben-Zeilen von [[{slug}|{title or slug}]] übernommen, noch ungeprüft. "
        "Im Termin kurz durchgehen: abhaken = erledigt, `[-]` im Thema = verworfen, offen "
        "lassen = gilt weiter. Nach der Nachbereitung dieses Termins gilt der Rest als geprüft.",
        "", "```dataview", "TASK", f'FROM "{folder}"',
        f'WHERE file.name = "{slug}" AND {tk.ALTBESTAND_DV}',
        f"GROUP BY {group}", "```", MARK_END,
    ]


# ------------------------------------------------- Jourfix: je Person

PERSON_MARK_RE = re.compile(r"<!-- altbestand-person:(?P<person>[a-z0-9-]+) -->\n.*?<!-- altbestand:end -->\n?",
                            re.S)
_SECTIONS_DQL = ('(meta(section).subpath = "Actions" OR meta(section).subpath = "Offene Punkte")')


def person_items(person: str) -> list[tuple[str, tk.Task]]:
    """(thema, punkt) - Altbestand-Punkte dieser Person ueber alle Themen."""
    out = []
    for f in _topic_files():
        for t in items(f.read_text(encoding="utf-8"), f.stem):
            if t.owner == person:
                out.append((f.stem, t))
    return out


def person_block(person: str, name: str, topics: list[tuple[str, str, str]]) -> list[str]:
    """Abschnitt fuer `## Vorbereitung` eines Jourfix/1:1: Themen der Person,
    ihre Zusagen und Fragen (live), ihr Altbestand aus allen Themen.
    `topics`: (slug, titel, ampel) - wo die Person beteiligt ist."""
    emo = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
    first = name.split()[0] if name else person
    lines = [f"### Mit {name or person}", ""]
    if topics:
        lines += ["**Themen:** " + " · ".join(f"{emo.get(h, '⚪')} [[{s}|{t}]]" for s, t, h in topics), ""]
    lines += [f"**Zusagen und Fragen von {first}** – live, abhaken wirkt an der Quelle:", "",
              "```dataview", "TASK",
              'FROM "active-meetings" OR "archive/meetings" OR "entities/projects" OR "entities/forums"',
              f'WHERE status = " " AND (contains(text, "— [[{person}") OR contains(text, "— an [[{person}"))',
              f"  AND {_SECTIONS_DQL}", "SORT due ASC", "GROUP BY file.link", "```"]
    n = len(person_items(person))
    if n:
        lines += ["", f"<!-- altbestand-person:{person} -->",
                  f"**Altbestand bei {first} ({n})** – aus alten Aufgaben-Zeilen, noch ungeprüft: "
                  "abhaken = erledigt, offen lassen = gilt weiter. Nach der Nachbereitung dieses "
                  "Termins gilt der Rest als geprüft.", "",
                  "```dataview", "TASK", 'FROM "entities/projects" OR "entities/forums"',
                  f'WHERE contains(text, "— [[{person}") AND {tk.ALTBESTAND_DV}',
                  "GROUP BY file.link", "```", MARK_END]
    return lines


def settle_person(person: str, *, day: str, source: str | None,
                  dry_run: bool = False) -> dict | None:
    """Altbestand einer Person (aus einem Jourfix) als geprueft uebernehmen - nur
    ihre Punkte, der Rest bleibt fuer andere Termine. None, wenn es keine gibt."""
    import uebernehmen as hs
    reviewed = person_items(person)
    if not reviewed:
        return None
    name = tk.Names().person(person) or person
    total = {"offen": 0, "erledigt": 0, "verworfen": 0}
    src = f" (→ [[{source}]])" if source else ""
    for topic in dict.fromkeys(t for t, _ in reviewed):
        path = topic_path(topic)
        text = path.read_text(encoding="utf-8")
        new_text, c = tk.dissolve_altbestand(text, day, owner=person)
        if new_text == text:
            continue
        for k in total:
            total[k] += c[k]
        entry = (f"- [{day}] [STATUS] Altbestand von {name} geklärt: {c['offen']} weiter offen, "
                 f"{c['erledigt']} erledigt, {c['verworfen']} verworfen{src}")
        if not dry_run:
            path.write_text(hs._append_events(new_text, [entry]), encoding="utf-8", newline="\n")
    return {"person": person, "name": name, "counts": total, "reviewed": reviewed}


# ------------------------------------------------------- nach dem Termin

def _processed(fm: dict) -> bool:
    p = fm.get("processed")
    if p is True or str(p).strip().lower() in ("true", "yes", "ja"):
        return True
    return str(fm.get("status") or "").strip().lower() in _PROCESSED_STATUS


def _result_block(slug: str, title: str, reviewed: list[tk.Task], c: dict, day: str,
                  names: tk.Names) -> str:
    """Ergebnis statt Live-Liste - die Meeting-Notiz haelt fest, was geklaert wurde."""
    lines = [f"<!-- altbestand:{slug}:geklärt -->",
             f"### Altbestand geklärt — [[{slug}|{title or slug}]]", "",
             f"{c['offen']} weiter offen · {c['erledigt']} erledigt · {c['verworfen']} verworfen "
             f"(mit der Nachbereitung am {_de(day)} übernommen)", ""]
    for t in reviewed:
        state = "erledigt" if t.status in ("x", "X") else "verworfen" if t.status == "-" else "offen"
        line = tk.render(t, names)
        lines.append(f"- {SYMBOL[state]} " + line[len("- [ ] "):])
    lines.append(MARK_END)
    return "\n".join(lines) + "\n"


def settle_topic(slug: str, *, day: str, source: str | None,
                 dry_run: bool = False) -> dict | None:
    """Altbestand eines Themas als geprueft uebernehmen. None, wenn es keinen gibt."""
    import uebernehmen as hs
    path = topic_path(slug)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8")
    reviewed = items(text, slug)
    if not reviewed:
        return None
    new_text, c = tk.dissolve_altbestand(text, day)
    src = f" (→ [[{source}]])" if source else ""
    entry = (f"- [{day}] [STATUS] Altbestand geklärt: {c['offen']} weiter offen, "
             f"{c['erledigt']} erledigt, {c['verworfen']} verworfen{src}")
    new_text = hs._append_events(new_text, [entry])
    if not dry_run:
        path.write_text(new_text, encoding="utf-8", newline="\n")
    fm = vp.split_frontmatter(text)[0]
    return {"slug": slug, "title": str(fm.get("name") or fm.get("title") or ""),
            "counts": c, "reviewed": reviewed}


def settle(today: date | None = None, dry_run: bool = False) -> list[dict]:
    """Vergangene, nachbereitete Termine mit Altbestand-Block auswerten."""
    today_s = (today or date.today()).isoformat()
    root = vp.VAULT / tk.MEETINGS_SUBDIR
    names = tk.Names()
    done: list[dict] = []
    for f in sorted(root.rglob("*.md")) if root.is_dir() else []:
        text = f.read_text(encoding="utf-8")
        if "<!-- altbestand" not in text:          # :thema oder -person:
            continue
        fm, _ = vp.split_frontmatter(text)
        day = str(fm.get("date") or "")[:10]
        if not day or day >= today_s or not _processed(fm):
            continue
        # Am Tag der Nachbereitung laesst sie sich noch sauber zuruecknehmen
        if str(fm.get("wrapped_at") or "")[:10] >= today_s:
            continue
        new_text = text
        for m in list(PERSON_MARK_RE.finditer(text)):
            person = m.group("person")
            r = settle_person(person, day=day, source=f.stem, dry_run=dry_run)
            if r is None:
                block = (f"<!-- altbestand-person:{person}:geklärt -->\n"
                         "_Altbestand dieser Person war schon geklärt._\n" + MARK_END + "\n")
            else:
                c = r["counts"]
                lines = [f"<!-- altbestand-person:{person}:geklärt -->",
                         f"**Altbestand bei {r['name']} geklärt:** {c['offen']} weiter offen · "
                         f"{c['erledigt']} erledigt · {c['verworfen']} verworfen "
                         f"(mit der Nachbereitung am {_de(day)} übernommen)", ""]
                for topic, t in r["reviewed"]:
                    state = ("erledigt" if t.status in ("x", "X")
                             else "verworfen" if t.status == "-" else "offen")
                    lines.append(f"- {SYMBOL[state]} {t.text} · [[{topic}]]")
                block = "\n".join(lines + [MARK_END]) + "\n"
                done.append({"slug": f"person:{person}", "meeting": f.stem, "counts": c})
            new_text = new_text.replace(m.group(0), block, 1)
        for m in list(MARK_RE.finditer(text)):
            slug = m.group("slug")
            r = settle_topic(slug, day=day, source=f.stem, dry_run=dry_run)
            if r is None:
                block = (f"<!-- altbestand:{slug}:geklärt -->\n"
                         f"_Altbestand von [[{slug}]] war schon geklärt – siehe dort im Event Log._\n"
                         f"{MARK_END}\n")
            else:
                block = _result_block(slug, r["title"], r["reviewed"], r["counts"], day, names)
                done.append({"slug": slug, "meeting": f.stem, "counts": r["counts"]})
            new_text = new_text.replace(m.group(0), block, 1)
        if new_text != text and not dry_run:
            f.write_text(new_text, encoding="utf-8", newline="\n")
    return done


# ----------------------------------------------------------------------- CLI

def overview(today: date | None = None) -> list[dict]:
    import stand
    today_s = (today or date.today()).isoformat()
    nxt = stand.next_meetings(today_s)
    out = []
    for slug, p in sorted(pending(today_s).items()):
        m = nxt.get(slug)
        out.append({"slug": slug, "offen": p["offen"], "erledigt": p["erledigt"],
                    "verworfen": p["verworfen"], "ueberfaellig": p["ueberfaellig"],
                    "naechster_termin": m[0] if m else None,
                    "termin": (m[1] or m[2]) if m else None})   # Notiz, sonst Kalendertitel
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Altbestand im naechsten Termin klaeren")
    ap.add_argument("--settle", action="store_true", help="nachbereitete Termine auswerten")
    ap.add_argument("--geprueft", metavar="SLUG", help="Thema von Hand als geprueft markieren")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.geprueft:
        import auto   # dieselbe Sperre wie die Automatik
        if not args.dry_run and not auto.acquire_lock():
            print("[ABBRUCH] Die Automatik läuft gerade - gleich noch einmal.", file=sys.stderr)
            return 1
        try:
            r = settle_topic(args.geprueft, day=date.today().isoformat(), source=None,
                             dry_run=args.dry_run)
        finally:
            if not args.dry_run:
                auto.release_lock()
        if r is None:
            print(f"Kein Altbestand in '{args.geprueft}'.")
            return 1
        c = r["counts"]
        print(f"{args.geprueft}: als geprüft übernommen - {c['offen']} weiter offen, "
              f"{c['erledigt']} erledigt, {c['verworfen']} verworfen")
        return 0

    if args.settle:
        done = settle(dry_run=args.dry_run)
        if args.json:
            print(json.dumps(done, ensure_ascii=False, indent=2))
        else:
            print(f"Altbestand: {len(done)} Thema/Themen nach dem Termin übernommen")
            for d in done:
                c = d["counts"]
                print(f"  {d['slug']:34} {c['offen']} offen, {c['erledigt']} erledigt, "
                      f"{c['verworfen']} verworfen  ({d['meeting']})")
        return 0

    rows = overview()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("Kein Altbestand mehr - alles geklärt.")
        return 0
    print(f"Altbestand in {len(rows)} Thema/Themen:")
    for r in rows:
        when = f"nächster Termin {_de(r['naechster_termin'])}" if r["naechster_termin"] \
            else "noch kein Termin vorbereitet"
        print(f"  {r['slug']:34} {r['offen']:3} offen · {r['erledigt']:2} erledigt · "
              f"{r['verworfen']:2} verworfen   {when}")
    no_meeting = [r["slug"] for r in rows if not r["naechster_termin"]]
    if no_meeting:
        print(f"\nNoch ohne vorbereiteten Termin ({len(no_meeting)}): Termin-Notizen entstehen "
              "1-2 Tage vorher. Wer nicht warten will: im Thema durchgehen, dann "
              "`2ndbrain altbestand --geprueft <slug>`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
