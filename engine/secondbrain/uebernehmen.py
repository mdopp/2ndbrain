#!/usr/bin/env python3
"""uebernehmen.py - das JSON des Modells deterministisch in die Vault-Dateien schreiben.

  - Eingang durch `modell_ausgabe.parse_json` (Fences, <think>-Bloecke) und
    `ausgabe_pruefen.validate_and_fix`: unbekannte Themen-Slugs werden verworfen und als
    Rueckfrage notiert, statt blind eine Themen-Datei anzulegen.
  - Schreibt nur anhaengend: Ereignisse ins Event Log des Themas, Aufgaben nach
    `## Offene Punkte`, Aussagen zu Personen, Datenfluesse an Systemen, neue
    Personen/Teams/Firmen/Systeme aus den Vorlagen. Geloescht wird nichts.
  - Der Idempotenz-Hash wird erst **nach** erfolgreichem Anwenden geschrieben - ein
    Absturz davor laesst den naechsten Versuch nicht stillschweigend aus.
  - Frontmatter wird upgesertet (fehlende Keys werden angelegt), Pfade aus `vault_paths`.

Kein eigener Befehl; aufgerufen aus der Engine (einarbeiten.py, arbeitspaket.py,
nachbereiten.py, rueckfragen.py): `sync(json, source_file=...)`.
Rueckgabe: 0 = sauber angewendet, 2 = Modell-Ausgabe unbrauchbar, 3 = angewendet, aber neue
Klaerungen offen.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import vault_paths as vp
import verdichten
from modell_ausgabe import LLMOutputError, parse_json
from ausgabe_pruefen import validate_and_fix

VAULT = vp.VAULT
TEMPLATES = vp.TEMPLATES_DIR
PROCESSED_LOG = vp.DATA_DIR / ".processed_hashes"

EVENT_LOG_HEADING = "## Event Log"


def ensure_dirs() -> None:
    vp.ensure_dirs()


def payload_hash(payload: dict) -> str:
    """Hash ueber den *kanonisierten* Payload.

    Bewusst nicht ueber den Rohstring: derselbe Inhalt umformatiert (pretty-print
    vs. kompakt) ergaebe sonst einen anderen Hash und wuerde erneut angewandt.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def already_applied(h: str) -> bool:
    if not PROCESSED_LOG.exists():
        return False
    return h in PROCESSED_LOG.read_text(encoding="utf-8").split()


def mark_applied(h: str) -> None:
    """Erst nach erfolgreichem Apply aufrufen."""
    seen = []
    if PROCESSED_LOG.exists():
        seen = PROCESSED_LOG.read_text(encoding="utf-8").split()
    if h in seen:
        return
    seen.append(h)
    PROCESSED_LOG.write_text("\n".join(seen) + "\n", encoding="utf-8", newline="\n")


def _append_events(content: str, entries: list[str]) -> str:
    """Events oben in den Event-Log einhaengen (append-only, Sektion bei Bedarf anlegen)."""
    if not entries:
        return content
    block = "\n".join(entries)
    if EVENT_LOG_HEADING in content:
        return content.replace(EVENT_LOG_HEADING, f"{EVENT_LOG_HEADING}\n{block}", 1)
    return content.rstrip() + f"\n\n{EVENT_LOG_HEADING}\n{block}\n"


def apply_project_updates(updates, dry_run: bool = False, source_file: str = "") -> list[str]:
    """Events an bestehende Themen anhaengen.

    Legt **keine** Themen an: unbekannte Slugs hat ausgabe_pruefen.py vorher
    verworfen - sonst entstuenden Themen-Dateien fuer halluzinierte Slugs.

    Event-Datum kommt aus der Quelle (`vp.source_date()`), nicht aus
    `date.today()` - sonst tragen alle Events das Datum des Verarbeitungslaufs
    statt des Meetings.
    """
    today = date.today().isoformat()
    event_date = vp.source_date(source_file, fallback=today)
    suffix = f" (→ [[{Path(source_file).stem}]])" if source_file else ""
    touched = []
    for upd in updates:
        slug = upd.get("slug")
        fpath = vp.project_path(slug)
        if not fpath.exists():
            print(f"[SKIP] Projekt '{slug}' existiert nicht ({fpath.relative_to(VAULT)})")
            continue

        entries = [f"- [{event_date}] {e}{suffix}" for e in upd.get("events", [])]
        content = fpath.read_text(encoding="utf-8")
        archived = verdichten.archived_text(fpath.stem)
        new_content = _append_events(content, [e for e in entries
                                               if e not in content and e not in archived])

        # 'last_updated' ist der Verarbeitungszeitpunkt, nicht das Ereignis -
        # bewusst 'today', nicht 'event_date'.
        fm_updates = {"last_updated": today}
        for field in ("health", "target_date", "last_milestone"):
            if upd.get(field):
                fm_updates[field] = upd[field]

        if dry_run:
            print(f"[DRY] {fpath.name}: +{len(entries)} Event(s), Frontmatter {list(fm_updates)}")
            continue

        if new_content != content:
            fpath.write_text(new_content, encoding="utf-8", newline="\n")
        vp.update_frontmatter(fpath, fm_updates)
        touched.append(slug)
        print(f"[UPDATED] entities/projects/{fpath.name} (+{len(entries)} Event(s))")
    return touched


# Kategorie -> Template-/Typname, ausdruecklich statt `cat.rstrip("s")`: das ergaebe fuer
# "companies" "companie", `company.md` wuerde nie gefunden, und jede automatisch angelegte
# Firma bekaeme den generischen Fallback statt des Templates (Vertraege, SLAs, Dataview-Abfragen).
CATEGORY_TYPE = {"people": "person", "teams": "team", "companies": "company",
                 "systems": "system"}


def _insert_description(content: str, name: str, description: str) -> str:
    """`## Beschreibung`-Abschnitt direkt nach der Titelzeile einfuegen.

    Nur wenn eine `description` im Payload steht - sonst bleibt der
    TODO-Platzhalter des Templates unveraendert (kein Erfinden von Text)."""
    if not description:
        return content
    marker = f"# {name}\n"
    idx = content.find(marker)
    if idx == -1:
        return content
    insert_at = idx + len(marker)
    return content[:insert_at] + f"\n## Beschreibung\n\n{description}\n" + content[insert_at:]


def apply_entities(entities, dry_run: bool = False) -> list[str]:
    today = date.today().isoformat()
    wikilink_keys = {"team", "company", "owner_team", "lead", "parent_system"}
    created = []
    for ent in entities:
        cat, slug = ent.get("category"), ent.get("slug")
        fpath = vp.CATEGORY_DIRS[cat] / f"{slug}.md"
        if fpath.exists():
            continue
        name = ent.get("name", slug)
        meta = dict(ent.get("meta", {}))
        description = str(meta.pop("description", "") or "").strip()

        typ = CATEGORY_TYPE.get(cat, cat.rstrip("s"))

        # Personen: dieselbe Alias-Regel wie `anlegen.create()` (keine
        # Vornamen-Aliasse - Vornamen loest aufloesen.py kontextsensitiv auf).
        if cat == "people":
            import anlegen
            al = meta.get("aliases") or []
            if isinstance(al, str):
                al = [al]
            meta["aliases"] = anlegen.first_name_alias(name, list(al))

        # Projekte brauchen `keywords` (steuert die Meeting-Zuordnung) und
        # `status: proposed`, damit erkennbar bleibt, was automatisch entstand.
        if cat == "projects":
            kw = meta.get("keywords") or []
            if isinstance(kw, str):
                kw = [k.strip() for k in kw.split(",") if k.strip()]
            beschreibung = (description or
                "<!-- Automatisch aus einem Meeting angelegt. Bitte pruefen: "
                "Name, keywords, und status auf active setzen. -->")
            fm_lines = ["---", "type: project", f'name: "{name}"',
                        "status: proposed", "kind: project", "scope: internal", "aliases: []",
                        f"keywords: {list(kw)}",
                        f"created: {today}", f"last_updated: {today}",
                        f'source: "{ent.get("source", "meeting-extractor")}"',
                        "tags:", "- project", "---", "",
                        f"# {name}", "", "## Beschreibung", "",
                        beschreibung, "",
                        "## Event Log", ""]
            if dry_run:
                print(f"[DRY] Wuerde Projekt anlegen: entities/projects/{slug}.md")
                continue
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(vp.strip_empty_frontmatter("\n".join(fm_lines)),
                             encoding="utf-8", newline="\n")
            created.append(f"entities/projects/{slug}.md")
            print(f"[CREATED] entities/projects/{slug}.md (status: proposed)")
            continue

        if cat == "forums":
            import reihen as _forum
            if dry_run:
                print(f"[DRY] Wuerde Forum anlegen: entities/forums/{slug}.md")
                continue
            kw = meta.get("keywords") or []
            if isinstance(kw, str):
                kw = [k.strip() for k in kw.split(",") if k.strip()]
            _forum.create(name, slug=slug, kind=str(meta.get("kind") or "other"),
                          cadence=str(meta.get("cadence") or ""),
                          keywords=list(kw),
                          members=meta.get("members") or [],
                          reports_on=meta.get("reports_on") or [])
            created.append(f"entities/forums/{slug}.md")
            continue

        tmpl = TEMPLATES / f"{typ}.md"
        if tmpl.exists():
            content = tmpl.read_text(encoding="utf-8")
            content = content.replace("{{title}}", name).replace("{{date:YYYY-MM-DD}}", today)
            for k, v in meta.items():
                if v:
                    if k in wikilink_keys:
                        content = content.replace(f'{k}: "[[]]"', f'{k}: "[[{v}]]"')
                    elif k == "aliases" and isinstance(v, list):
                        content = content.replace("aliases: []", f"aliases: {list(v)}", 1)
                    else:
                        content = content.replace(f"{k}: \n", f"{k}: {v}\n", 1)
            # status: stub steht bereits im Template: automatisch angelegte
            # Entities bleiben stub, bis ein Mensch sie prueft.
            content = _insert_description(content, name, description)
        else:
            lines = ["---", f"type: {typ}", f'name: "{name}"']
            for k, v in meta.items():
                if v:
                    val = f'"[[{v}]]"' if k in wikilink_keys else f'"{v}"'
                    lines.append(f"{k}: {val}")
            lines += ["status: stub", f"created: {today}", f"last_updated: {today}",
                      "---", "", f"# {name}", ""]
            content = "\n".join(lines)
            content = _insert_description(content, name, description)

        if dry_run:
            print(f"[DRY] Wuerde anlegen: entities/{cat}/{slug}.md")
            continue
        # Die Template-Felder sind Anker fuer die Ersetzung oben; was danach
        # leer geblieben ist, wird nicht geschrieben (Regel in vault_paths).
        content = vp.strip_empty_frontmatter(content)
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8", newline="\n")
        created.append(f"entities/{cat}/{slug}.md")
        print(f"[CREATED] entities/{cat}/{slug}.md")

        # Kanon-/C4-Referenz (`atlas_id`/`c4_id`) eintragen - kein Spiegeln, nur
        # die IDs. Ein Fehlschlag (Kanon/C4 nicht erreichbar) darf das Anlegen der
        # Datei nicht verhindern - nur die IDs bleiben dann leer.
        try:
            import aufloesen as re_
            index = re_.build_index()
            hit = re_.resolve(name, index, kind_hint=typ)
            ref_updates = {}
            if hit.get("resolved") == "atlas" and hit.get("slug"):
                ref_updates["atlas_id"] = hit["slug"]
            elif hit.get("resolved") == "c4" and hit.get("slug"):
                ref_updates["c4_id"] = hit["slug"]
            if ref_updates:
                vp.update_frontmatter(fpath, ref_updates)
        except Exception as e:
            print(f"[WARN] Atlas/C4-Referenz fuer '{name}' nicht ermittelbar: {e}",
                  file=sys.stderr)
    return created


def apply_data_flows(flows, dry_run: bool = False, source_file: str = "") -> None:
    today = vp.source_date(source_file, fallback=date.today().isoformat())
    for flow in flows:
        src, tgt = flow.get("source_system"), flow.get("target_system")
        proto = flow.get("protocol", "N/A")
        desc = flow.get("description", "")
        for path, direction, other in [
            (vp.SYSTEMS_DIR / f"{src}.md", "Sendet an", tgt),
            (vp.SYSTEMS_DIR / f"{tgt}.md", "Empfaengt von", src),
        ]:
            if not path.exists():
                continue
            c = path.read_text(encoding="utf-8")
            entry = f"- [{today}] {direction} [[{other}]] via {proto} ({desc})"
            if entry in c:
                continue
            if dry_run:
                print(f"[DRY] {path.name}: {entry}")
                continue
            path.write_text(c.rstrip() + f"\n{entry}\n", encoding="utf-8", newline="\n")
        print(f"[FLOW] {src} -> {tgt}")


def apply_action_items(actions, dry_run: bool = False, source_file: str = "") -> None:
    """Aufgaben als kanonische Punkte (`aufgaben.py`) nach `## Offene Punkte` der
    Themen-Datei - nicht als `[ACTION]`-Zeile ins Event Log, weil es dort keinen
    Erledigt-Status gibt (KONZEPT.md §4.1). Append-only, ohne Dubletten; das
    Datum ist das der Quelle, nicht des Laufs."""
    created = vp.source_date(source_file, fallback=date.today().isoformat())
    source = Path(source_file).stem if source_file else None
    names = tk.Names()
    for act in actions:
        fpath = vp.project_path(act.get("project"))
        if not fpath.exists():
            print(f"[SKIP] Action ohne Projektdatei: {act.get('project')}")
            continue
        deadline = str(act.get("deadline") or "").strip()
        task = tk.Task(status=" ", text=" ".join(str(act.get("task", "")).split()),
                       owner=str(act.get("owner") or "").strip() or None,
                       due=deadline if re.match(r"^\d{4}-\d{2}-\d{2}$", deadline) else None,
                       created=created, source=source)
        content = fpath.read_text(encoding="utf-8")
        # auch gegen das Archiv: ein verdichteter Punkt kommt nicht als neu zurueck
        new_content, added = tk.append_to_section(content, tk.TOPIC_SECTION, [task], names,
                                                  known=verdichten.archived_keys(fpath.stem))
        if not added:
            continue
        if dry_run:
            print(f"[DRY] {fpath.name}: {tk.render(task, names)}")
            continue
        fpath.write_text(new_content, encoding="utf-8", newline="\n")
        print(f"[ACTION] {act.get('owner')}: {act.get('task', '')[:60]}")


PERSON_FACTS_HEADING = "## Expertise & Verantwortung"
_EMPTY_ROLES = {"", "unbekannt", "none", "null"}


def _fact_key(line: str) -> str:
    """Vergleichsschluessel: ohne Datum, Quelle und Gross/Klein."""
    line = re.sub(r"^- \[\d{4}-\d{2}-\d{2}\]\s*", "", line.strip())
    line = re.sub(r"\s*\(→ \[\[[^\]]+\]\]\)\s*$", "", line)
    return " ".join(line.casefold().split())


def _insert_person_fact(content: str, line: str) -> str:
    """Unter '## Expertise & Verantwortung' nach dem letzten Listenpunkt einfuegen."""
    lines = content.split("\n")
    try:
        h = next(i for i, l in enumerate(lines) if l.strip() == PERSON_FACTS_HEADING)
    except StopIteration:
        return content.rstrip() + f"\n\n{PERSON_FACTS_HEADING}\n{line}\n"
    end = next((i for i in range(h + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    bullets = [i for i in range(h + 1, end)
               if lines[i].startswith("- ") and lines[i].strip() not in ("-", "- ")]
    at = (bullets[-1] + 1) if bullets else h + 1
    lines.insert(at, line)
    return "\n".join(lines)


def apply_person_facts(facts, dry_run: bool = False, source_file: str = "") -> list[str]:
    """Ausdrueckliche Aussagen zu Personen anhaengen (append-only, mit Datum und Quelle).

    So steht eine Rolle wie "Anna Beispiel (Einkauf)" in der Personen-Notiz und nicht
    nur im Meeting-Text. `kind: role` fuellt zusaetzlich das Frontmatter-Feld `role`,
    solange es leer ist."""
    event_date = vp.source_date(source_file, fallback=date.today().isoformat())
    suffix = f" (→ [[{Path(source_file).stem}]])" if source_file else ""
    touched = []
    for fact in facts or []:
        path = vp.PEOPLE_DIR / f"{fact['person']}.md"
        if not path.exists():
            print(f"[SKIP] Person '{fact['person']}' existiert nicht")
            continue
        line = f"- [{event_date}] {fact['fact']}{suffix}"
        content = path.read_text(encoding="utf-8")
        known = {_fact_key(l) for l in content.split("\n") if l.startswith("- ")}
        if _fact_key(line) in known:
            continue
        if dry_run:
            print(f"[DRY] {path.name}: {line}")
            continue
        path.write_text(_insert_person_fact(content, line), encoding="utf-8", newline="\n")
        updates = {"last_updated": date.today().isoformat()}
        role = str(vp.read_frontmatter(path).get("role") or "").strip()
        if fact["kind"] == "role" and role.casefold() in _EMPTY_ROLES and len(fact["fact"]) <= 80:
            updates["role"] = fact["fact"]
        vp.update_frontmatter(path, updates)
        touched.append(fact["person"])
        print(f"[PERSON] {fact['person']}: {fact['fact'][:70]}")
    return touched


def record_clarifications(clarifications, source_file: str = "") -> None:
    """Klaerungen anlegen - dedupliziert gegen bereits offene Karten.

    Gibt es fuer `(kind, raw_slug)` schon eine offene Karte, wird nur die neue
    Quelle im aufbewahrten Payload ergaenzt (append-only, nichts geht verloren,
    keine Dublette) - sonst bekaeme derselbe unbekannte Slug aus jedem Meeting
    eine eigene Karte.
    """
    if not clarifications:
        return
    try:
        from rueckfragen import add_clarification, find_open
    except ImportError:
        print(f"[WARN] {len(clarifications)} Klaerung(en) nicht notiert (rueckfragen fehlt)")
        return
    from rueckfragen import load_pending, save_pending
    for c in clarifications:
        kind, raw_slug = c.get("kind"), c.get("raw_slug")
        existing_cid = find_open(kind, raw_slug) if kind and raw_slug else None
        if existing_cid:
            data = load_pending(existing_cid) or {
                "title": c["title"], "kind": kind, "raw_slug": raw_slug,
                "source_file": source_file, "payload": c.get("payload") or {}}
            # Quellen als Liste fuehren; eine Karte mit nur einer Quelle traegt
            # erst das Feld 'source_file'.
            sources = data.get("sources") or (
                [data["source_file"]] if data.get("source_file") else [])
            if source_file and source_file not in sources:
                sources.append(source_file)
            data["sources"] = sources
            # Neue Auspraegungen des Payloads (z.B. weitere action_items mit
            # demselben unbekannten Owner) anhaengen statt zu ersetzen.
            if c.get("payload"):
                for key, items in c["payload"].items():
                    if not isinstance(items, list):
                        continue
                    dest = data.setdefault("payload", {}).setdefault(key, [])
                    for item in items:
                        if item not in dest:
                            dest.append(item)
            save_pending(existing_cid, data)
            print(f"[CLARIFICATION MERGED] {existing_cid}: {c['title']} "
                  f"(+Quelle {source_file or 'stdin'})")
            continue
        cid = add_clarification(c["title"], c["context"], c.get("options", []),
                                source_file=source_file)
        if c.get("payload"):
            save_pending(cid, {"title": c["title"], "kind": kind,
                               "raw_slug": raw_slug,
                               "source_file": source_file, "payload": c["payload"]})


def classify_unknown_slug(slug: str) -> tuple[str | None, str]:
    """Bestimmt, in welche Kategorie ein unbekannter Slug gehoert - statt ihn
    blind als Thema anzulegen.

    `ausgabe_pruefen.py` prueft die Slugs von Themen-Updates nur gegen die
    Themen-Liste: ein Team-Slug erscheint dort als "unbekanntes Projekt" und
    laege sonst doppelt im Vault - unter `entities/teams/` und als Thema unter
    `entities/projects/`.

    Rueckgabe `(kategorie, begruendung)`. `kategorie is None` heisst: keine
    Datei anlegen (Kanon-Kontext - wird nur referenziert, siehe
    `entities/contexts/_index.md`).
    """
    import aufloesen as re_
    index = re_.build_index()
    result = re_.resolve(slug, index, kind_hint=None)

    if result.get("resolved") == "vault":
        cat = (result.get("sources", {}).get("vault") or {}).get("category")
        if cat:
            return cat, f"existiert bereits im Vault als '{cat}/{result['slug']}'"

    atlas = result.get("sources", {}).get("atlas") or {}
    if result.get("resolved") == "atlas":
        if atlas.get("kind") == "team":
            return "teams", f"Atlas-Team '{atlas.get('id')}'"
        if atlas.get("kind") == "context":
            return None, (f"Atlas-Kontext '{atlas.get('id')}' - siehe "
                          f"entities/contexts/_index.md")

    if result.get("resolved") == "c4":
        return "systems", f"C4-Treffer '{result.get('slug')}'"

    return "projects", "kein Treffer in Atlas/C4/Vault"


def bootstrap_projects(slugs: list[str], source_file: str, dry_run: bool) -> list[str]:
    """Unbekannte Slugs typklassifiziert anlegen (Thema, Team oder System).

    Nur mit `sync(..., allow_new_projects=True)`. Gedacht fuer einen Erstlauf
    ueber einen Altbestand: dort ist ein Grossteil der Themen noch nicht als
    Datei vorhanden, und die Events wuerden sonst reihenweise verworfen. Im
    Normalbetrieb bleibt das aus - da ist ein unbekannter Slug eher eine
    Halluzination als ein neues Thema.

    Trotz des Namens nicht nur Themen: die Kategorie bestimmt
    `classify_unknown_slug()`.
    """
    made = []
    for slug in slugs:
        category, why = classify_unknown_slug(slug)
        if category is None:
            print(f"[SKIP] '{slug}' ist {why}")
            continue
        name = slug.replace("-", " ").title()
        meta = {"keywords": []} if category == "projects" else {}
        ents = [{"category": category, "slug": slug, "name": name,
                 "meta": meta, "source": source_file or "bootstrap"}]
        if category != "projects":
            print(f"[CLASSIFIED] '{slug}' -> {category} ({why})")
        made += apply_entities(ents, dry_run)
    return made


def _personen_der_quelle(source_file: str) -> set[str]:
    """In der Quelle verlinkte Personen (Kontext fuer mehrdeutige Vornamen)."""
    if not source_file:
        return set()
    from aufloesen import personen_in
    p = Path(source_file)
    return personen_in([p if p.is_absolute() else vp.VAULT / p])


def sync(raw: str, source_file: str = "", dry_run: bool = False,
         allow_new_projects: bool = False, force: bool = False) -> int:
    """Rueckgabe: Exit-Code. 0 = ok/no-op, 2 = LLM-Ausgabe unbrauchbar.

    `force=True` umgeht den Payload-Hash-Skip (gezielter Re-Apply);
    der Text-Dedupe im Event-Log bleibt als zweites Netz aktiv."""
    try:
        payload, repairs = parse_json(raw, expect=dict)
    except LLMOutputError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        record_clarifications([{
            "title": "LLM-Ausgabe nicht verwertbar",
            "context": f"Quelle: {source_file or 'stdin'}. Fehler: {e}",
            "options": ["A) Meeting erneut extrahieren", "B) Manuell erfassen", "C) Ueberspringen"],
        }], source_file)
        return 2
    for r in repairs:
        print(f"[REPAIR] {r}", file=sys.stderr)

    h = payload_hash(payload)
    if already_applied(h):
        if force:
            print(f"[FORCE] Hash-Skip umgangen ({h})", file=sys.stderr)
        else:
            print(f"[SKIP] Payload bereits verarbeitet ({h})")
            return 0

    kontext = _personen_der_quelle(source_file)
    payload, warnings, clarifications = validate_and_fix(payload, vp.known_slugs(), kontext)

    # Bootstrap: unbekannte Projekte anlegen und die Validierung wiederholen,
    # damit die zugehoerigen Events nicht verloren gehen.
    unknown = payload.pop("_unknown_projects", [])
    if unknown and allow_new_projects:
        ensure_dirs()
        made = bootstrap_projects(unknown, source_file, dry_run)
        if made:
            vp.invalidate_entity_caches()
        if made and not dry_run:
            payload2, w2, c2 = validate_and_fix(json.loads(
                json.dumps(parse_json(raw, expect=dict)[0])), vp.known_slugs(), kontext)
            payload2.pop("_unknown_projects", None)
            payload, warnings, clarifications = payload2, warnings + w2, c2
    elif unknown:
        print(f"[HINT] {len(unknown)} unbekannte(s) Thema/Themen: {', '.join(unknown)}", file=sys.stderr)
        print("[HINT] Anlegen mit '2ndbrain thema-neu \"<Name>\"'", file=sys.stderr)

    for w in warnings:
        print(w, file=sys.stderr)

    ensure_dirs()
    # Entities zuerst: Projekt-Events koennen auf neue Personen verweisen.
    made_entities = apply_entities(payload.get("entities", []), dry_run)
    if made_entities:
        # Nur dann sind Whitelist/Aliasse veraltet - sonst bleibt der
        # Disk-Cache ueber den ganzen Lauf gueltig.
        vp.invalidate_entity_caches()
    apply_project_updates(payload.get("project_updates", []), dry_run, source_file)
    apply_person_facts(payload.get("person_facts", []), dry_run, source_file)
    apply_data_flows(payload.get("data_flows", []), dry_run, source_file)
    apply_action_items(payload.get("action_items", []), dry_run, source_file)
    if dry_run:
        for c in clarifications:
            print(f"[DRY] Klaerung: {c['title']}")
    else:
        record_clarifications(clarifications, source_file)

    if not dry_run:
        # Nur als erledigt markieren, wenn **nichts** verworfen wurde. Sonst
        # blockiert der Hash die Wiedervorlage: der erste Lauf verwirft einen
        # unbekannten Slug, und der Replay nach der Klaerung laeuft in [SKIP].
        if clarifications:
            print(f"[HOLD] Payload nicht als erledigt markiert - "
                  f"{len(clarifications)} offene Klaerung(en)", file=sys.stderr)
        else:
            mark_applied(h)
    # 3 = angewendet, aber es sind neue Klaerungen entstanden. Der Aufrufer
    # (rueckfragen.apply_pending) darf die Wiedervorlage dann nicht als erledigt loeschen.
    return 3 if clarifications else 0
