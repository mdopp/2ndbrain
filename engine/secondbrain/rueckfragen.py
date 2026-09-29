#!/usr/bin/env python3
"""rueckfragen.py - Rueckfragen an den Benutzer (Klaerungskarten in 04_Clarifications.md) anlegen,
beantworten und einarbeiten.

Wo die Engine etwas nicht sicher zuordnen kann (mehrere passende Personen, unklare
Themennamen, widerspruechliche Aussagen), wird KEINE Annahme geraten, sondern eine
Klaerungskarte angelegt. Den dabei verworfenen Teil der Modell-Ausgabe bewahrt
`.2ndbrain/daten/.pending/<id>.json` auf; mit der Antwort wird er angewendet.

Beantwortet wird per Haken an einer Option in der Karte (der Automatik-Schritt
`rueckfragen` arbeitet das ein, erledigte Karten gehen ins Archiv) oder per Befehl:

    2ndbrain rueckfragen list
    2ndbrain rueckfragen add "Titel" "Kontext" --options "Opt A" "Opt B" "Opt C"
    2ndbrain rueckfragen resolve <id> "Text"          # nur als erledigt markieren
    2ndbrain rueckfragen resolve <id> --as <slug>     # aufbewahrten Payload anwenden
    2ndbrain rueckfragen pending                      # Karten mit aufbewahrtem Payload
    2ndbrain rueckfragen abhaken | aufraeumen [--dry-run]
"""
import sys, json, re
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vault_paths as vp

VAULT = vp.VAULT
# anlegen/zusammenfuehren werden erst in den Funktionen importiert, die sie
# brauchen - der Normalfall 'list'/'add' kommt ohne sie aus.
CLARIFICATION_FILE = VAULT / "04_Clarifications.md"
# Verworfene Teil-Payloads zu offenen Rueckfragen. Damit ist eine Klaerung
# *anwendbar* und nicht nur dokumentiert.
PENDING_DIR = vp.DATA_DIR / ".pending"


def load_clarifications() -> str:
    if CLARIFICATION_FILE.exists():
        return CLARIFICATION_FILE.read_text(encoding="utf-8")
    return (
        "# ❓ Offene Klaerungen & Rueckfragen an den Benutzer\n\n"
        "> Hier sammeln sich automatisch Unklarheiten aus Meetings und Notizen,\n"
        "> bei denen das System nicht raten wollte, sondern deine Bestaetigung braucht.\n\n"
        "---\n\n"
    )


def save_pending(cid: str, data: dict) -> Path:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    p = PENDING_DIR / f"{cid}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return p


def load_pending(cid: str) -> dict | None:
    p = PENDING_DIR / f"{cid}.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def find_open(kind: str, raw_slug: str) -> str | None:
    """Offene Klaerungskarte fuer denselben (kind, raw_slug) finden - falls
    vorhanden; so bekommt derselbe unbekannte Slug keine zweite Karte.

    Sucht zuerst strukturiert in `.2ndbrain/daten/.pending/*.json` (zuverlaessiger
    als Text-Matching), dann als Fallback im Titel offener Karten (fuer Karten
    ohne Pending-Datei, z.B. Klaerungen ohne aufbewahrten Payload).
    """
    if not kind or not raw_slug:
        return None
    for cid in list_pending():
        data = load_pending(cid)
        if not data:
            continue
        if data.get("kind") == kind and data.get("raw_slug") == raw_slug:
            return cid
    # Fallback: Titel-Text bei Karten ohne (oder mit geloeschter) Pending-Datei.
    # Nur offene Karten ("### ❓", nicht "### ✅") zaehlen.
    needle = f"'{raw_slug}'"
    for card in list_clarifications():
        if needle in card["title"]:
            return card["id"]
    return None


def list_pending() -> list[str]:
    if not PENDING_DIR.is_dir():
        return []
    return sorted(p.stem for p in PENDING_DIR.glob("*.json"))


def _resolve_ambiguous_person_file(cid: str, data: dict, replacement: str, *,
                                    dry_run: bool = False) -> bool:
    """Klaerung 'ambiguous_person_file' aufloesen: eine Einwort-Stub-Datei
    ('max.md') passt zu mehreren echten Personen - der Benutzer waehlt per
    `--as <slug>`, danach wird die Stub-Datei per
    `zusammenfuehren.merge_entity_files()` in die gewaehlte Person gefaltet
    (Referenzen/Aliasse bleiben erhalten, nichts geht verloren)."""
    raw_slug = str(data.get("raw_slug") or "")
    candidates = data.get("candidates") or []
    if replacement not in candidates:
        print(f"[ABBRUCH] '{replacement}' ist keiner der Kandidaten fuer "
              f"'{raw_slug}': {', '.join(candidates)}", file=sys.stderr)
        return False
    target = vp.PEOPLE_DIR / f"{replacement}.md"
    if not target.exists():
        print(f"[ABBRUCH] entities/people/{replacement}.md existiert nicht.",
              file=sys.stderr)
        return False
    if dry_run:
        print(f"[DRY] Wuerde {raw_slug}.md -> {replacement}.md zusammenfuehren.")
        return True
    import zusammenfuehren
    bare = vp.PEOPLE_DIR / f"{raw_slug}.md"
    result = zusammenfuehren.merge_entity_files(target, bare)
    (PENDING_DIR / f"{cid}.json").unlink(missing_ok=True)
    resolve_clarification(cid, f"zusammengefuehrt mit '{replacement}' ({result})")
    print(f"[OK] {raw_slug} -> {replacement}: {result}")
    return True


def _resolve_possible_duplicate_person(cid: str, data: dict, replacement: str, *,
                                        dry_run: bool = False) -> bool:
    """Klaerung 'possible_duplicate_person' aufloesen: eine neue E-Mail-Person
    aehnelt einer bestehenden und wurde deshalb NICHT automatisch angelegt.

    `--as <bestehender-slug>` -> ist dieselbe Person: E-Mail/Name werden als
    Alias/E-Mail-Feld in die bestehende Datei nachgetragen, keine neue Datei.
    `--as <anderer-slug>` (z.B. der vorgeschlagene Slug) -> ist doch eine
    eigenstaendige Person: wird jetzt angelegt.
    """
    import anlegen
    name = str(data.get("name") or "")
    email = str(data.get("email") or "")
    target = vp.PEOPLE_DIR / f"{replacement}.md"
    if dry_run:
        print(f"[DRY] Wuerde '{name}' der Person '{replacement}' zuordnen "
              f"oder als neue Person '{replacement}' anlegen.")
        return True
    if target.exists():
        fm = vp.read_frontmatter(target)
        updates = {}
        if email and not fm.get("email"):
            updates["email"] = email
        aliases = fm.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        aliases = list(aliases)
        known_lower = {a.lower() for a in aliases} | {str(fm.get("name") or "").lower()}
        if name and name.lower() not in known_lower:
            aliases.append(name)
            updates["aliases"] = aliases
        if updates:
            vp.update_frontmatter(target, updates)
        action = f"vorhandener Person '{replacement}' zugeordnet (kein Duplikat)"
    else:
        anlegen.create("people", name or replacement,
                          slug=replacement, meta={"email": email} if email else {})
        action = f"als eigenstaendige neue Person '{replacement}' angelegt"
    (PENDING_DIR / f"{cid}.json").unlink(missing_ok=True)
    resolve_clarification(cid, action)
    print(f"[OK] {cid}: {action}")
    return True


def apply_pending(cid: str, replacement: str, *, dry_run: bool = False) -> bool:
    """Wiedervorlage: `__RESOLVE__` durch den echten Slug ersetzen und anwenden."""
    data = load_pending(cid)
    if not data:
        print(f"[ERROR] Kein aufbewahrter Payload fuer {cid}.", file=sys.stderr)
        return False

    kind0 = str(data.get("kind") or "")
    if kind0 == "ambiguous_person_file":
        return _resolve_ambiguous_person_file(cid, data, replacement, dry_run=dry_run)
    if kind0 == "possible_duplicate_person":
        return _resolve_possible_duplicate_person(cid, data, replacement, dry_run=dry_run)

    raw = json.dumps(data.get("payload") or {}, ensure_ascii=False)
    if "__RESOLVE__" not in raw:
        print(f"[WARN] {cid}: kein Platzhalter im Payload.", file=sys.stderr)
    raw = raw.replace("__RESOLVE__", replacement)

    # --- Vorabpruefung: existiert das Ziel ueberhaupt? ---
    # Ohne diese Pruefung entsteht eine Schleife: der Platzhalter wird ersetzt,
    # die Validierung findet den Slug nicht, setzt 'unassigned' und legt eine
    # NEUE Rueckfrage an. Der Benutzer loest dieselbe Sache endlos auf.
    kind = str(data.get("kind") or "")
    expect = {"unknown_project": ("projects", "thema-neu"),
              "unknown_person": ("people", "person-neu"),
              "unknown_forum": ("forums", "reihe-neu")}.get(kind)
    if expect:
        category, maker = expect
        known = vp.entity_slugs(category)
        if replacement not in known:
            import difflib
            close = difflib.get_close_matches(replacement, known, n=3, cutoff=0.6)
            print(f"[ABBRUCH] '{replacement}' existiert nicht in entities/{category}/.",
                  file=sys.stderr)
            if close:
                print(f"  Gemeint war vielleicht: {', '.join(close)}", file=sys.stderr)
            print(f"  Anlegen mit:  2ndbrain {maker} \"<Name>\"",
                  file=sys.stderr)
            print("  Danach diesen Befehl erneut ausfuehren. Die Rueckfrage bleibt "
                  "so lange bestehen - nichts geht verloren.", file=sys.stderr)
            return False

    sys.path.insert(0, str(vp.ENGINE_DIR))
    from uebernehmen import sync
    rc = sync(raw, source_file=data.get("source_file", ""), dry_run=dry_run,
              allow_new_projects=False)
    if rc == 2:
        print(f"[ERROR] {cid}: aufbewahrter Payload nicht verwertbar.", file=sys.stderr)
        return False
    if rc == 3:
        # Angewendet, aber es sind neue Klaerungen entstanden - Wiedervorlage
        # behalten, damit der Rest nicht verloren geht.
        print(f"[TEILWEISE] {cid}: angewendet, aber neue Klaerung(en) entstanden. "
              f"Wiedervorlage bleibt bestehen.", file=sys.stderr)
        return False
    if not dry_run:
        (PENDING_DIR / f"{cid}.json").unlink(missing_ok=True)
        resolve_clarification(cid, f"zugeordnet an '{replacement}' und angewendet")
    return True


def add_clarification(title: str, context: str, options: list[str], source_file: str = "") -> str:
    """Fuegt eine neue Klaerungskarte hinzu.

    Die CID ist nur sekundengenau (`%m%d-%H%M%S`) - mehrere Klaerungen aus
    demselben Lauf (z.B. mehrere unbekannte Personen aus einem einzigen
    Meeting) koennen dieselbe Sekunde treffen. Da `save_pending()` bedingungslos
    schreibt, ueberschriebe die zweite Karte den aufbewahrten Payload der ersten.
    Deshalb hier auf Kollision gegen bestehende Karten UND vorhandene
    `.pending/*.json` pruefen und bei Bedarf `-2`, `-3`, ... anhaengen.
    """
    content = load_clarifications()
    today = date.today().isoformat()
    base = f"CLARIFY-{datetime.now().strftime('%m%d-%H%M%S')}"
    cid = base
    i = 2
    while f"[{cid}]" in content or (PENDING_DIR / f"{cid}.json").exists():
        cid = f"{base}-{i}"
        i += 1

    lines = [
        f"### ❓ [{cid}] {title}",
        f"*Erstellt: {today}* " + (f"*(Quelle: [[{source_file}]])* " if source_file else ""),
        "",
        f"**Situation / Kontext:**",
        f"{context}",
        "",
        f"**Optionen zur Auswahl:**",
    ]
    for opt in options:
        lines.append(f"- [ ] {opt}")
    lines.extend(["", "---", ""])

    new_card = "\n".join(lines)
    # Unter der Einleitung einfuegen
    if "---\n\n" in content:
        parts = content.split("---\n\n", 1)
        updated = parts[0] + "---\n\n" + new_card + parts[1]
    else:
        updated = content + "\n" + new_card

    CLARIFICATION_FILE.write_text(updated, encoding="utf-8", newline="\n")
    print(f"[CLARIFICATION ADDED] {cid}: {title}")
    return cid


def list_clarifications() -> list[dict]:
    """Liest alle offenen Klaerungskarten."""
    content = load_clarifications()
    cards = []
    pattern = re.compile(r"### ❓ \[(CLARIFY-[\w\-]+)\] (.+?)\n(.*?)(?=\n### ❓|\Z)", re.DOTALL)
    for m in pattern.finditer(content):
        cid, title, body = m.groups()
        cards.append({
            "id": cid,
            "title": title.strip(),
            "body": body.strip()
        })
    return cards


def resolve_clarification(cid: str, resolution: str) -> bool:
    """Markiert eine Klaerung als erledigt."""
    content = load_clarifications()
    pattern = rf"### ❓ \[{re.escape(cid)}\] (.+?)\n(.*?)(?=\n### ❓|\n---\n\Z|\Z)"
    m = re.search(pattern, content, re.DOTALL)
    if not m:
        print(f"[ERROR] Clarification ID '{cid}' nicht gefunden.")
        return False

    old_block = m.group(0)
    today = date.today().isoformat()
    new_block = f"### ✅ [{cid}] ~~{m.group(1)}~~\n*Geloest am {today}: {resolution}*\n"

    updated = content.replace(old_block, new_block)
    CLARIFICATION_FILE.write_text(updated, encoding="utf-8", newline="\n")
    print(f"[RESOLVED] {cid}: {resolution}")
    return True


# ------------------------------------------------------------------ Abhaken
# Der Benutzer beantwortet eine Karte meist, indem er bei einer Option den Haken
# setzt. `abhaken` (und der Automatik-Schritt `rueckfragen`) arbeitet solche Karten
# ein, `aufraeumen` legt erledigte ins Archiv.

ARCHIVE_DIR = vp.SOURCES_DIR / "clarifications"
_CHECKED_RE = re.compile(r"^- \[[xX]\]\s*(?:[A-Z]\)\s*)?(.+)$", re.M)
_NAME_RE = re.compile(r"[A-ZÄÖÜ][\wäöüß'-]+(?:\s+(?:von|van|de|der|zu|[A-ZÄÖÜ][\wäöüß'-]+))+")


def checked_option(body: str) -> str | None:
    m = _CHECKED_RE.search(body)
    return m.group(1).strip() if m else None


def decide(choice: str, people: set[str], aliases: dict[str, str]) -> tuple[str, str]:
    """(aktion, wert) fuer die angehakte Option: ("person", slug) · ("neu", "Vorname Nachname")
    · ("bleibt", "") · ("extrahieren", "") · ("", grund) wenn nichts sicher erkennbar ist."""
    m = re.search(r'person-new\s+"([^"]+)"', choice)
    new_name = m.group(1) if m else ""
    m = (re.search(r"--as\s+([a-z0-9][a-z0-9-]*)", choice)
         or re.search(r"\(([a-z0-9]+(?:-[a-z0-9]+)+)\)\s*$", choice)
         or re.search(r"\[\[([a-z0-9-]+)\|", choice))
    if m:
        slug = m.group(1)
        if slug in people:
            return "person", slug
        return ("neu", new_name) if new_name else ("", f"Person '{slug}' gibt es nicht")
    low = choice.lower()
    if any(w in low for w in ("unklar", "überspringen", "ueberspringen", "bleibt")):
        return "bleibt", ""
    if "erneut extrahieren" in low:
        return "extrahieren", ""
    if low.startswith("neue person") or "löschen" in low or "loeschen" in low:
        return "", "bitte von Hand (vollen Namen als eigene Option eintragen bzw. Datei löschen)"
    name = re.sub(r"[`*_]", "", choice).strip()
    if _NAME_RE.fullmatch(name):                      # frei eingetragen: "D) Clara von Beispiel"
        slug = aliases.get(name.lower(), "")
        return ("person", slug) if slug in people else ("neu", name)
    return "", "Auswahl nicht erkannt"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\wäöüß ]", " ", str(text).lower())).strip()


def _project_for(slug: str, known: set[str]) -> str:
    """Thema eines Payloads - ist es inzwischen eine Reihe (z. B. ein Weekly), deren Thema."""
    if slug in known:
        return slug
    import themen as th
    return next((t for t in th.series_topics(slug) if t in known), slug)


def _assign_owner(cid: str, data: dict, slug: str, *, dry_run: bool) -> str:
    """Aufgaben mit offener Person: steht die Aufgabe schon im Vault (Person "(?)"
    oder leer), bekommt die Zeile die Person - erneutes Einspielen legte sie sonst
    doppelt an. Nur was fehlt, wird mit der Person eingespielt."""
    import difflib
    import aufgaben as tk
    names = tk.Names()
    known = set(vp.entity_slugs("projects"))
    open_tasks = [t for t in tk.scan() if t.is_open and t.path and t.line is not None]
    fixed, rest = 0, []
    for item in (data.get("payload") or {}).get("action_items") or []:
        if item.get("owner") != "__RESOLVE__":
            continue
        want = _norm(item.get("task"))
        score, hit = max(((difflib.SequenceMatcher(None, want, _norm(t.text)).ratio(), t) for t in open_tasks),
                         default=(0.0, None), key=lambda x: x[0])
        if hit is not None and score >= 0.8:
            if not hit.owner and not dry_run:
                p = vp.VAULT / hit.path
                lines = p.read_text(encoding="utf-8").split("\n")
                task = tk.parse_line(lines[hit.line])
                if task is not None and not task.owner:
                    task.owner, task.owner_raw = slug, None
                    indent = lines[hit.line][: len(lines[hit.line]) - len(lines[hit.line].lstrip())]
                    lines[hit.line] = indent + tk.render(task, names)
                    p.write_text("\n".join(lines), encoding="utf-8", newline="\n")
            fixed += 1
        else:
            rest.append({**item, "owner": slug, "project": _project_for(str(item.get("project") or ""), known)})
    if rest and not dry_run:
        from uebernehmen import sync
        if sync(json.dumps({"action_items": rest}, ensure_ascii=False), source_file=data.get("source_file", ""),
                dry_run=False, allow_new_projects=False) == 2:
            return "Einspielen fehlgeschlagen"
    return f"{fixed} vorhandene Aufgabe(n) zugeordnet, {len(rest)} neu eingespielt"


def _merge_stub(data: dict, slug: str, *, dry_run: bool) -> str:
    import zusammenfuehren
    stub = vp.PEOPLE_DIR / f"{data.get('raw_slug')}.md"
    if dry_run:
        return f"{stub.stem} -> {slug}"
    r = zusammenfuehren.merge_entity_files(vp.PEOPLE_DIR / f"{slug}.md", stub)
    return f"{stub.stem} zusammengeführt mit {slug} ({r.get('references_added', 0)} Verweise)"


THEMEN_KARTEN = {"unknown_project": "projects", "unknown_forum": "forums"}


def _topic_card(cid: str, data: dict, choice: str, *, dry_run: bool) -> dict:
    """Karte zu einem unbekannten Thema oder einer unbekannten Reihe. "Verwerfen" legt die
    aufbewahrten Ereignisse ab; "zuordnen" braucht das Ziel in der Zeile ([[slug]] oder den
    Slug) und spielt dort ein; "anlegen" legt das Ziel unter dem vorgeschlagenen Namen an."""
    low = choice.lower()
    raw_slug = str(data.get("raw_slug") or "")
    if "verwerfen" in low:
        if not dry_run:
            (PENDING_DIR / f"{cid}.json").unlink(missing_ok=True)
            resolve_clarification(cid, f"Haken „{choice[:60]}“ – verworfen, nichts eingespielt")
        return {"id": cid, "ok": True, "ergebnis": "verworfen", "auswahl": choice}
    known = set(vp.entity_slugs(THEMEN_KARTEN[data["kind"]]))
    if "anlegen" in low:
        if raw_slug not in known and not dry_run:
            name = raw_slug.replace("-", " ").title()
            if data["kind"] == "unknown_project":
                import thema_anlegen
                thema_anlegen.create(name, [], slug=raw_slug)
            else:
                import reihen
                reihen.create(name, slug=raw_slug)
        ziel = raw_slug
    else:
        m = (re.search(r"\[\[([a-z0-9-]+)(?:\|[^\]]*)?\]\]", choice)
             or re.search(r"\b([a-z0-9]+(?:-[a-z0-9]+)+)\b", choice))
        ziel = m.group(1) if m else ""
        if ziel not in known:
            return {"id": cid, "ok": False, "auswahl": choice,
                    "grund": "Ziel fehlt - in die Zeile schreiben, z. B. „B) … zuordnen: [[thema-slug]]“"}
    ok = dry_run or apply_pending(cid, ziel, dry_run=dry_run)
    return {"id": cid, "ok": bool(ok), "auswahl": choice,
            **({"ergebnis": f"eingespielt in {ziel}"} if ok else {"grund": f"nicht eingespielt ({ziel})"})}


def apply_checked(*, dry_run: bool = False) -> list[dict]:
    """Angehakte Karten einarbeiten. Liefert je Karte, was passiert ist (oder warum nicht)."""
    import anlegen
    out = []
    people = set(vp.entity_slugs("people"))
    aliases = vp.alias_map()
    for card in list_clarifications():
        choice = checked_option(card["body"])
        if not choice:
            continue
        cid, data = card["id"], load_pending(card["id"]) or {}
        if data.get("kind") in THEMEN_KARTEN:
            out.append(_topic_card(cid, data, choice, dry_run=dry_run))
            continue
        if data.get("kind") == "protokoll_termin":
            import protokolle
            out.append(protokolle.antwort(cid, data, choice, dry_run=dry_run))
            continue
        if data.get("kind") == "schreibweise":
            import schreibweisen
            out.append(schreibweisen.antwort(cid, data, choice, dry_run=dry_run))
            continue
        action, value = decide(choice, people, aliases)
        done = ""
        if action == "neu":
            slug = vp.slugify(value)
            if not dry_run and slug not in people:
                anlegen.create("people", value, slug=slug)
                people.add(slug)
            action, value, done = "person", slug, f"Person {value} angelegt; "
        if action == "person" and data.get("kind") == "ambiguous_person_file":
            done += _merge_stub(data, value, dry_run=dry_run)
        elif action == "person" and data.get("kind") == "unknown_person":
            done += _assign_owner(cid, data, value, dry_run=dry_run)
        elif action == "person":
            action, value = "", "keine aufbewahrten Daten zur Karte"
        elif action == "bleibt":
            done = "bleibt so (Entscheidung des Benutzers)"
        elif action == "extrahieren":
            m = re.search(r"Quelle: \[*([^\n\]]+?\.md)", card["body"])      # auch "(Quelle: [[x.md]])"
            src = Path(str(data.get("source_file") or (m.group(1) if m else ""))).stem
            refs = sum(f.read_text(encoding="utf-8").count(f"[[{src}") for f in vp.PROJECTS_DIR.glob("*.md")) if src else 0
            if refs:
                done = f"überholt: eine spätere Auswertung liegt vor ({refs} Einträge verweisen auf die Quelle)"
            else:
                action, value = "", "bitte Termin-Notiz erneut nachbereiten (Plugin: Nacherfassen)"
        if not action:
            out.append({"id": cid, "ok": False, "grund": value, "auswahl": choice})
            continue
        if not dry_run:
            (PENDING_DIR / f"{cid}.json").unlink(missing_ok=True)
            resolve_clarification(cid, f"Haken „{choice[:60]}“ – {done}")
        out.append({"id": cid, "ok": True, "ergebnis": done, "auswahl": choice})
    return out


def archive_resolved(*, dry_run: bool = False) -> int:
    """Erledigte Karten (✅) aus der Datei ins Archiv - die Datei zeigt nur Offenes."""
    content = load_clarifications()
    blocks = re.findall(r"^### ✅ .*?(?=^### |^---[ \t]*$|\Z)", content, re.M | re.S)
    if not blocks or dry_run:
        return len(blocks)
    archive = ARCHIVE_DIR / f"erledigt-{date.today().year}.md"
    archive.parent.mkdir(parents=True, exist_ok=True)
    year = date.today().year
    head = "" if archive.exists() else (f"---\ntype: archiv\ntitle: Erledigte Rückfragen {year}\n---\n"
                                        f"# Erledigte Rückfragen {year}\n\n")
    with open(archive, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(head + "".join(b.rstrip() + "\n\n" for b in blocks))
    for b in blocks:
        content = content.replace(b, "", 1)
    content = re.sub(r"(\n---[ \t]*\n)(\s*---[ \t]*\n)+", r"\1", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    CLARIFICATION_FILE.write_text(content, encoding="utf-8", newline="\n")
    return len(blocks)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: rueckfragen.py [list|add|resolve|abhaken|aufraeumen] ...")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "list":
        cards = list_clarifications()
        print(f"Offene Klaerungen: {len(cards)}")
        for c in cards:
            print(f"• {c['id']}: {c['title']}")
    elif cmd == "add":
        if len(sys.argv) < 4:
            print("Usage: rueckfragen.py add <title> <context> [--options opt1 opt2 ...]")
            sys.exit(1)
        title = sys.argv[2]
        context = sys.argv[3]
        options = []
        if "--options" in sys.argv:
            idx = sys.argv.index("--options")
            options = sys.argv[idx + 1:]
        if not options:
            options = ["Option A bestaetigen", "Option B verwerfen", "Manuell bearbeiten"]
        add_clarification(title, context, options)
    elif cmd == "resolve":
        if len(sys.argv) < 4:
            print("Usage:")
            print("  rueckfragen.py resolve <id> <text>          # nur abhaken")
            print("  rueckfragen.py resolve <id> --as <slug>     # anwenden")
            sys.exit(1)
        if sys.argv[3] == "--as":
            if len(sys.argv) < 5:
                print("Usage: resolve <id> --as <slug> [--dry-run]")
                sys.exit(1)
            ok = apply_pending(sys.argv[2], sys.argv[4], dry_run="--dry-run" in sys.argv)
            sys.exit(0 if ok else 1)
        resolve_clarification(sys.argv[2], sys.argv[3])

    elif cmd in ("abhaken", "aufraeumen"):
        dry = "--dry-run" in sys.argv
        if cmd == "abhaken":
            for r in apply_checked(dry_run=dry):
                print(f"  {'OK ' if r['ok'] else '-- '} {r['id']}: {r.get('ergebnis') or r.get('grund')}"
                      f"  [{r['auswahl'][:50]}]")
        n = archive_resolved(dry_run=dry)
        print(f"{'Würde' if dry else ''} {n} erledigte Karte(n) ins Archiv "
              f"({ARCHIVE_DIR.relative_to(vp.VAULT).as_posix()}){' legen' if dry else ' gelegt'}")

    elif cmd == "pending":
        ids = list_pending()
        print(f"Anwendbare Rueckfragen: {len(ids)}")
        for cid in ids:
            d = load_pending(cid) or {}
            pl = d.get("payload") or {}
            n = sum(len(v) for v in pl.values() if isinstance(v, list))
            print(f"  {cid}  {d.get('title','?')[:52]:54} {n} Eintrag/Eintraege")
        if ids:
            print("\n  Anwenden:  2ndbrain rueckfragen resolve <id> --as <slug>")
