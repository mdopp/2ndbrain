#!/usr/bin/env python3
"""test_tools.py - Regressionstests fuer die Engine-Module (engine/secondbrain).

    2ndbrain test            (oder: python engine/tests/test_tools.py)

Jeder Test sichert ein Verhalten ab, ohne das Daten beschaedigt oder still falsche Ergebnisse
geliefert werden. Die Tests arbeiten nur auf temporaeren Vaults aus Vorlage und Testdaten, nie
auf einem echten Vault.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "secondbrain"   # das Paket mit den Modulen
sys.path.insert(0, str(ENGINE))

_passed, _failed, _skipped = 0, [], []
_TEMP_VAULTS: list[Path] = []


def _grund_vault() -> Path:
    """Grund-Vault fuer alle Tests: die Vorlage (Playbooks, Templates, Cockpit-Seiten,
    Chat-Rezepte), sonst leer. Tests greifen nie auf einen echten Vault zu: auch restore_vault()
    kehrt hierher zurueck, nicht zu einem Vault im aktuellen Ordner."""
    import shutil
    d = Path(tempfile.mkdtemp(prefix="vaultbasis-"))
    _TEMP_VAULTS.append(d)
    (d / ".obsidian").mkdir()
    shutil.copytree(ENGINE / "vorlage", d, dirs_exist_ok=True)
    (d / ".2ndbrain" / "daten").mkdir(parents=True, exist_ok=True)
    return d


_BASIS = _grund_vault()
os.environ["VAULT_DIR"] = str(_BASIS)


class Skip(Exception):
    """Test ist auf dieser Plattform nicht ausfuehrbar (z.B. Symlinks ohne
    Windows-Entwicklermodus). Zaehlt weder als bestanden noch als Fehler."""


def check(name, fn):
    global _passed
    try:
        fn()
        print(f"  OK   {name}")
        _passed += 1
    except Skip as e:
        print(f"  SKIP {name}: {e}")
        _skipped.append(name)
    except AssertionError as e:
        print(f"  FAIL {name}: {e}")
        _failed.append(name)
    except Exception as e:
        print(f"  ERR  {name}: {type(e).__name__}: {e}")
        _failed.append(name)


def eq(a, b, msg=""):
    assert a == b, f"{msg} erwartet {b!r}, war {a!r}"


def ok(c, msg="falsch"):
    assert c, msg


# ─────────────────────────────────────────── temporaerer Vault

_EXTERNAL_ENV = {k: os.environ.get(k) for k in ("VAULT_LIKEC4_MODEL", "VAULT_DOMAIN_ATLAS")}


def temp_vault():
    """Frischer Vault im Temp-Ordner; Module neu laden, damit sie darauf zeigen."""
    d = Path(tempfile.mkdtemp(prefix="vaulttest-"))
    _TEMP_VAULTS.append(d)
    (d / ".obsidian").mkdir()
    for c in ("people", "teams", "companies", "systems", "projects", "forums", "glossary"):
        (d / "entities" / c).mkdir(parents=True)
    (d / ".2ndbrain" / "daten").mkdir(parents=True)      # Konfiguration + Daten des Vaults
    os.environ["VAULT_DIR"] = str(d)
    # Externe Ordner hermetisch: sonst findet die Auto-Erkennung ~/likec4-model und
    # ~/domain-atlas dieses Rechners, und ein Test ueberschreibt die echte Systemuebersicht.
    os.environ["VAULT_LIKEC4_MODEL"] = str(d / "likec4-model")
    os.environ["VAULT_DOMAIN_ATLAS"] = str(d / "domain-atlas")
    import vault_paths
    importlib.reload(vault_paths)
    for m in ("ausgabe_pruefen", "agenda", "reihen", "briefing", "rueckfragen",
              "uebernehmen", "aufloesen", "playbook", "vorbereiten", "anlegen",
              "glossar", "selbsttest",
              "aufgaben", "ampel",
              "personen", "begriffsindex", "nachbereiten_modell", "nachbereiten", "stand",
              "auto", "verdichten", "systemuebersicht", "kanon_vorschlaege",
              "einrichten", "kanon", "schreibweisen", "umbenennen", "zusammenfuehren"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])
    return d


def restore_vault():
    os.environ["VAULT_DIR"] = str(_BASIS)
    for k, v in _EXTERNAL_ENV.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    import vault_paths
    importlib.reload(vault_paths)
    for m in ("ausgabe_pruefen", "agenda", "reihen", "briefing", "rueckfragen",
              "uebernehmen", "aufloesen", "playbook", "vorbereiten", "anlegen",
              "glossar", "selbsttest",
              "aufgaben", "ampel",
              "personen", "begriffsindex", "nachbereiten_modell", "nachbereiten", "stand",
              "auto", "verdichten", "systemuebersicht", "kanon_vorschlaege",
              "einrichten", "kanon", "schreibweisen", "umbenennen", "zusammenfuehren"):
        if m in sys.modules:
            importlib.reload(sys.modules[m])


# ─────────────────────────────────────────── vault_paths

def t_root_from_env_or_cwd():
    """Der Code liegt nicht im Vault: VAULT_DIR (Plugin, MCP-Befehl) geht vor, sonst die Suche ab
    dem aktuellen Ordner aufwaerts nach .2ndbrain/ oder .obsidian/. Ohne Treffer gibt es keinen
    Vault - dann bricht befehle.py ab, statt im aktuellen Ordner (etwa im Home-Ordner) zu schreiben.
    ENGINE_DIR ist der Paket-Ordner samt Vorlage."""
    import vault_paths as vp
    d = Path(tempfile.mkdtemp(prefix="roottest-"))
    _TEMP_VAULTS.append(d)
    (d / "v" / ".2ndbrain").mkdir(parents=True)
    (d / "v" / "sub").mkdir()
    (d / "leer").mkdir()
    try:
        os.environ.pop("VAULT_DIR", None)
        eq(vp.find_vault_root(d / "v" / "sub"), (d / "v").resolve(), "Suche aufwaerts:")
        eq(vp.find_vault_root(d / "leer"), None, "kein Vault:")
        os.environ["VAULT_DIR"] = str(d / "v")
        eq(vp.find_vault_root(d / "leer"), (d / "v").resolve(), "VAULT_DIR geht vor:")
        ok(vp.ENGINE_DIR == Path(vp.__file__).resolve().parent and (vp.VORLAGE_DIR / ".templates").is_dir(),
           vp.ENGINE_DIR)
    finally:
        restore_vault()


def t_frontmatter_upsert():
    """update_frontmatter legt einen fehlenden Key an (ein re.sub nur ueber vorhandene Keys waere
    ein stilles No-op), laesst den Body stehen und meldet beim zweiten Lauf keine Aenderung."""
    d = temp_vault()
    try:
        import vault_paths as vp
        f = d / "x.md"
        f.write_text("---\ntype: project\n---\n\n# X\n", encoding="utf-8", newline="\n")
        eq(vp.update_frontmatter(f, {"health": "green"}), True, "muss aendern")
        eq(vp.read_frontmatter(f).get("health"), "green", "neuer Key fehlt")
        eq(vp.update_frontmatter(f, {"health": "green"}), False, "zweiter Lauf = No-op")
        ok("# X" in f.read_text(encoding="utf-8"), "Body verloren")
    finally:
        restore_vault()


def t_broken_symlinks_filtered():
    """Kaputte Alias-Symlinks kommen nicht als Geister-Slugs in die Whitelist, sondern werden als
    kaputte Links gemeldet."""
    d = temp_vault()
    try:
        import vault_paths as vp
        (vp.PEOPLE_DIR / "real.md").write_text("---\ntype: person\n---\n", encoding="utf-8", newline="\n")
        try:
            (vp.PEOPLE_DIR / "Ghost.md").symlink_to("nicht-da.md")
        except OSError as e:
            raise Skip(f"Symlinks auf dieser Plattform nicht erlaubt ({type(e).__name__})")
        slugs = vp.entity_slugs("people")
        ok("real" in slugs, "echte Person fehlt")
        ok("Ghost" not in slugs, "kaputter Symlink ist in der Whitelist")
        eq(len(vp.broken_links("people")), 1, "kaputter Link nicht gemeldet")
    finally:
        restore_vault()


# ─────────────────────────────────────────── modell_ausgabe

def t_llm_json_repair():
    """parse_json repariert typische Modell-Ausgaben (Fence, <think>-Block, Vortext, trailing comma,
    Klammer im String) und weist Text ohne JSON mit LLMOutputError ab."""
    from modell_ausgabe import LLMOutputError, parse_json
    eq(parse_json('{"a":1}')[0], {"a": 1})
    eq(parse_json('```json\n{"a":1}\n```')[0], {"a": 1}, "Fence")
    eq(parse_json('<think>hm</think>\n{"a":1}')[0], {"a": 1}, "think-Block")
    eq(parse_json('Hier:\n{"a":1}\nfertig')[0], {"a": 1}, "Vortext")
    eq(parse_json('{"a":1,}')[0], {"a": 1}, "trailing comma")
    eq(parse_json('{"a":"} in string","b":2}')[0], {"a": "} in string", "b": 2},
       "Klammer im String")
    try:
        parse_json("Ich kann das nicht.")
        raise AssertionError("Muell muesste abgewiesen werden")
    except LLMOutputError:
        pass


# ─────────────────────────────────────────── ausgabe_pruefen

def _known():
    return {"projects": ["project-qrs", "at-schnittstellen-abloesung"],
            "people": ["daniel-mohr"], "systems": ["system-lfs"],
            "teams": [], "companies": [], "forums": []}


def t_validate_drops_unknown_project():
    """Ein erfundener Projekt-Slug wird nicht angewendet, sondern eine Klaerung, die den Payload
    aufbewahrt - sonst gehen seine Events verloren."""
    from ausgabe_pruefen import validate_and_fix
    p, w, c = validate_and_fix(
        {"project_updates": [{"slug": "erfunden", "events": ["[RISK] x"]}]}, _known())
    eq(len(p["project_updates"]), 0, "erfundener Slug wurde angewendet")
    eq(len(c), 1, "keine Klaerung angelegt")
    ok(c[0].get("payload"), "Klaerung ohne aufbewahrten Payload - Events wuerden verloren")


def t_validate_fuzzy_and_enums():
    """Ein fast passender Projekt-Slug wird per Fuzzy-Match korrigiert, ein ungueltiger Enum-Wert
    (health) genullt, ein Event ohne Praefix verworfen."""
    from ausgabe_pruefen import validate_and_fix
    p, w, c = validate_and_fix({"project_updates": [
        {"slug": "project-ep", "health": "gruen",
         "events": ["[RISK] ok", "ohne prefix"]}]}, _known())
    eq(p["project_updates"][0]["slug"], "project-qrs", "Fuzzy-Match")
    eq(p["project_updates"][0]["health"], None, "ungueltiges Enum nicht genullt")
    eq(p["project_updates"][0]["events"], ["[RISK] ok"], "Event ohne Prefix behalten")


def t_validate_accepts_project_declared_in_payload():
    """Ein Projekt, das im selben Payload neu angelegt wird, gilt als bekannt - sonst verliert ein
    Meeting zu einem neuen Projekt seine Events."""
    from ausgabe_pruefen import validate_and_fix
    p, w, c = validate_and_fix({
        "new_entities": [{"category": "projects", "slug": "neu-x", "name": "Neu X"}],
        "project_updates": [{"slug": "neu-x", "events": ["[DECISION] y"]}]}, _known())
    eq(len(p["project_updates"]), 1, "im Payload deklariertes Projekt wurde verworfen")
    eq(len(c), 0, "unnoetige Klaerung")


def t_validate_holds_action_with_unknown_owner():
    """Eine Action mit unbekanntem Owner wird zurueckgehalten und nur als Klaerung angelegt, nicht
    zusaetzlich ohne Person angewendet - sonst entsteht eine Dublette."""
    from ausgabe_pruefen import validate_and_fix
    p, w, c = validate_and_fix({"action_items": [
        {"owner": "Niemand Da", "project": "project-qrs", "task": "T"}]}, _known())
    eq(len(p["action_items"]), 0, "Action mit unbekanntem Owner wurde angewendet")
    eq(len(c), 1, "keine Klaerung")


def t_validate_resolves_person_via_alias():
    """Ein Vorname wird ueber den Alias exakt der richtigen Person zugeordnet - nicht per
    Fuzzy-Match ueber den ganzen String einer anderen Person, deren Name sich nur in einem
    Buchstaben unterscheidet. Ein eindeutiger Alias-Treffer braucht keine Klaerung."""
    d = temp_vault()
    try:
        import vault_paths as vp
        from ausgabe_pruefen import validate_and_fix
        for slug, name in (("daniel-mohr", "Daniel Mohr"),
                           ("danil-kowalski", "Danil Kowalski"),
                           ("veit-pohl", "Veit Pohl"),
                           ("veith-schmitz", "Veith Schmitz")):
            (vp.PEOPLE_DIR / f"{slug}.md").write_text(
                f"---\ntype: person\nname: {name}\n---\n", encoding="utf-8", newline="\n")
        known = _known()
        known["people"] = ["daniel-mohr", "danil-kowalski",
                           "veit-pohl", "veith-schmitz"]
        p, w, c = validate_and_fix({"action_items": [
            {"owner": "daniel", "project": "project-qrs", "task": "t1"},
            {"owner": "veit", "project": "project-qrs", "task": "t2"}]}, known)
        owners = {a["task"]: a["owner"] for a in p["action_items"]}
        eq(owners.get("t1"), "daniel-mohr", "daniel falsch aufgeloest")
        eq(owners.get("t2"), "veit-pohl", "veit falsch aufgeloest")
        eq(len(c), 0, "keine Klaerung noetig bei eindeutigem Alias-Treffer")
    finally:
        restore_vault()


def t_validate_ambiguous_person_lists_candidates():
    """Ein Vorname, der auf vier Personen passt, wird eine Klaerung mit allen vier Kandidaten als
    Optionen; 'neu anlegen' ist nicht Option A."""
    d = temp_vault()
    try:
        import vault_paths as vp
        from ausgabe_pruefen import validate_and_fix
        for slug, name in (("kuno-a", "Kuno A"), ("kuno-b", "Kuno B"),
                           ("kuno-c", "Kuno C"), ("kuno-d", "Kuno D")):
            (vp.PEOPLE_DIR / f"{slug}.md").write_text(
                f"---\ntype: person\nname: {name}\n---\n", encoding="utf-8", newline="\n")
        known = _known()
        known["people"] = ["kuno-a", "kuno-b", "kuno-c", "kuno-d"]
        p, w, c = validate_and_fix({"action_items": [
            {"owner": "kuno", "project": "project-qrs", "task": "t"}]}, known)
        eq(len(p["action_items"]), 0, "mehrdeutiger Owner wurde angewendet")
        eq(len(c), 1, "keine Klaerung angelegt")
        opts = c[0]["options"]
        ok(sum(1 for o in opts if any(s in o for s in known["people"])) == 4,
           "nicht alle 4 Kandidaten in den Optionen")
        ok("neu anlegen" not in opts[0].lower(), "Option A darf nicht 'neu anlegen' sein")
    finally:
        restore_vault()


def t_validate_forums_allowed():
    """'forums' ist eine gueltige Entity-Kategorie."""
    from ausgabe_pruefen import VALID_CATEGORIES
    ok("forums" in VALID_CATEGORIES, "Kategorie forums fehlt")


# ─────────────────────────────────────────── uebernehmen

def t_event_date_from_source_not_today():
    """Ein Event traegt das Datum seiner Quelle (Frontmatter `date`), nicht das heutige, und
    verweist auf die Quelle."""
    d = temp_vault()
    try:
        import vault_paths as vp
        import uebernehmen as hs
        src = d / "2026-08-03---checkin---nachtsprung.md"
        src.write_text("---\ndate: 2026-08-03\n---\n# Checkin\n", encoding="utf-8", newline="\n")
        proj = vp.project_path("zoll-portugal")
        proj.write_text("---\ntype: project\nname: ZOLL Portugal\n---\n\n"
                        "## Event Log\n", encoding="utf-8", newline="\n")
        hs.apply_project_updates(
            [{"slug": "zoll-portugal", "events": ["[STATUS] Testereignis"]}],
            dry_run=False, source_file=str(src))
        content = proj.read_text(encoding="utf-8")
        ok("[2026-08-03]" in content, "Quelldatum nicht uebernommen")
        ok(f"[{date.today().isoformat()}]" not in content,
           "heutiges Datum statt Quelldatum")
        ok("2026-08-03---checkin---nachtsprung" in content, "Quellenverweis fehlt")
    finally:
        restore_vault()


def t_payload_hash_canonical():
    """Der Payload-Hash ist kanonisch: umformatiertes JSON ergibt denselben Hash - sonst wird
    derselbe Payload doppelt angewendet."""
    import uebernehmen as hs
    a = {"b": 1, "a": [1, 2]}
    b = json.loads(json.dumps(a, indent=4, sort_keys=True))
    eq(hs.payload_hash(a), hs.payload_hash(b), "Hash nicht kanonisch")


def t_no_hash_when_clarifications():
    """Bei offenen Klaerungen (Exit-Code 3) wird der Payload-Hash nicht gesetzt - sonst laeuft die
    Wiedervorlage in den Idempotenz-Skip."""
    d = temp_vault()
    try:
        import uebernehmen as hs
        raw = json.dumps({"project_updates": [{"slug": "gibts-nicht",
                                               "events": ["[RISK] x"]}]})
        rc = hs.sync(raw, source_file="t.md")
        eq(rc, 3, "Exit-Code 3 bei offenen Klaerungen erwartet")
        ok(not hs.already_applied(hs.payload_hash(json.loads(raw))),
           "Hash wurde trotz Klaerung gesetzt")
    finally:
        restore_vault()


# ─────────────────────────────────────────── agenda / briefing

def t_clarifications_deduplicate_same_person():
    """Zweimal dieselbe unbekannte Person -> eine Klaerungskarte, nicht zwei; Quellen und
    Payload-Eintraege werden zusammengefuehrt."""
    d = temp_vault()
    try:
        import uebernehmen as hs
        c1 = [{"kind": "unknown_person", "raw_slug": "ottokar",
               "title": "Unbekannte Person 'ottokar'", "context": "c1",
               "options": ["A", "B", "C"],
               "payload": {"action_items": [{"owner": "__RESOLVE__", "project": "p", "task": "t1"}]}}]
        hs.record_clarifications(c1, source_file="a.md")
        c2 = [{"kind": "unknown_person", "raw_slug": "ottokar",
               "title": "Unbekannte Person 'ottokar'", "context": "c2",
               "options": ["A", "B", "C"],
               "payload": {"action_items": [{"owner": "__RESOLVE__", "project": "p", "task": "t2"}]}}]
        hs.record_clarifications(c2, source_file="b.md")
        content = (Path(hs.VAULT) / "04_Clarifications.md").read_text(encoding="utf-8")
        eq(content.count("Unbekannte Person 'ottokar'"), 1, "Dublette statt Ergaenzung")

        from rueckfragen import find_open, load_pending
        cid = find_open("unknown_person", "ottokar")
        ok(cid, "Karte ueber find_open nicht wiedergefunden")
        data = load_pending(cid)
        eq(sorted(data.get("sources") or []), ["a.md", "b.md"], "Quellen nicht zusammengefuehrt")
        tasks = {a["task"] for a in data["payload"]["action_items"]}
        eq(tasks, {"t1", "t2"}, "Payload-Eintraege nicht zusammengefuehrt")
    finally:
        restore_vault()


def t_series_key_strips_dates():
    """series_key erkennt dieselbe Reihe unabhaengig von Datum und Trennzeichen im Titel."""
    from agenda import series_key
    eq(series_key("2026-07-16 --- Jourfix --- Delta Themen Quirin und Kasimir"),
       series_key("2026-08-20 Jourfix Delta Themen Quirin und Kasimir"),
       "gleiche Reihe nicht erkannt")
    eq(series_key("Workshop NoLa Days 2026-09-03"), "workshop-nola-days")


def t_owner_split_survives_hyphens_and_wikilinks():
    """'@Owner: Titel: Beschreibung' wird zerlegt; der Owner endet am ersten Trenner - Bindestriche
    und Doppelpunkte im Titel ziehen nichts in den Owner (ein gieriger Regex tut das und erzeugt
    Dubletten). Ein Wikilink als Owner zerlegt den Titel nicht."""
    from briefing import _split_item
    o, l, _ = _split_item("@Felix: Bereitstellung einer Shipper-zu-Freight-Payer-Liste: Erstelle.")
    eq(o, "Felix")
    ok(l.startswith("Bereitstellung einer Shipper"), f"Label falsch: {l!r}")
    o2, l2, _ = _split_item("@[[jan-marx|Jan]] — Monitoring Der Abos: Stimmt euch ab.")
    eq(l2, "Monitoring Der Abos", "Wikilink-Owner zerlegt das Label")


def t_agenda_user_edit_is_sticky():
    """Eine vom Benutzer bearbeitete Agenda bleibt in allen weiteren Laeufen stehen: die Markierung
    ist dauerhaft (sticky), sonst generiert ein spaeterer Lauf die Agenda des Benutzers weg."""
    d = temp_vault()
    try:
        import agenda as ag
        f = d / "m.md"
        f.write_text("---\ntype: meeting\n---\n\n# M\n\n## Agenda\n\n1. A\n2. B\n",
                     encoding="utf-8", newline="\n")
        ag.apply_agenda(f, ["A", "B"])
        t = f.read_text(encoding="utf-8")
        f.write_text(t.replace("1. A", "1. MEIN TEXT"), encoding="utf-8", newline="\n")
        for _ in range(3):
            ag.apply_agenda(f, ["A", "B"])
        ok("MEIN TEXT" in f.read_text(encoding="utf-8"),
           "Benutzer-Edit wurde ueberschrieben")
    finally:
        restore_vault()


def t_briefing_tiers_are_relative():
    """Die Briefing-Stufen sind relativ begrenzt: auch wenn alle Themen alt sind, sind hoechstens
    MAX_CRITICAL kritisch - absolute Altersschwellen machen bei Altdaten sonst alles kritisch."""
    import briefing as bf
    topics = [{"kind": "action", "label": f"T{i}", "context": "c", "owners": [],
               "first_seen": "2026-01-01", "last_seen": "2026-01-01", "seen_in": [],
               "times_seen": 1, "deadline": "", "age_days": 300, "overdue": False}
              for i in range(12)]
    for t in topics:
        t["why"] = "alt"
    bf.assign_tiers(topics, None)
    crit = sum(1 for t in topics if t["priority"] == bf.PRIO_CRITICAL)
    ok(crit <= bf.MAX_CRITICAL, f"{crit} kritische Themen - Obergrenze verletzt")


def t_briefing_stale_risk_is_info_not_critical():
    """Ein seit ueber 30 Tagen nicht mehr erwaehntes Risiko ist nur INFO ("nicht mehr erwaehnt",
    Rueckfrage, ob es erledigt ist), nicht kritisch; ein erneut erwaehntes bleibt kritisch und
    steht davor."""
    import briefing as bf
    today = date(2026, 9, 16)
    base = {"kind": "risk", "context": "c", "owners": [], "seen_in": [], "times_seen": 1,
            "deadline": "", "overdue": False}
    old = dict(base, label="Alt", first_seen="2026-07-01", last_seen="2026-07-10")
    new = dict(base, label="Neu", first_seen="2026-07-01", last_seen="2026-09-10")
    for t in (old, new):
        t["age_days"] = bf._age(t["first_seen"], today)
        bf._mark_silence(t, today)
    ok(old["stale"] and not new["stale"], "stale falsch gesetzt")
    prio, why = bf.classify(old, None, today=today)
    eq(prio, bf.PRIO_INFO, "altes Risiko nicht INFO")
    ok("nicht mehr erwähnt" in why, f"Begruendung falsch: {why}")
    eq(bf.classify(new, None, today=today)[0], bf.PRIO_CRITICAL, "erneut erwaehntes Risiko nicht kritisch")
    ok(bf.urgency(old, None) < 10 <= bf.urgency(new, None), "Rangfolge falsch")
    ok("erledigt" in bf.default_question(old), "Frage passt nicht")


def t_briefing_source_link_date_is_no_deadline():
    """Das Datum im Quellen-Link `(→ [[2026-09-11-quelle]])` ist keine Frist - sonst gilt jedes
    Risiko mit Quelle als ueberfaellig."""
    import briefing as bf
    text = "- [2026-09-11] [RISK] Payment Terms fehlen (→ [[2026-09-11-nola-payment-terms]])\n"
    topics = bf._topics_from_events(text, "p", today=date(2026, 9, 16))
    risk = next(t for t in topics if t["kind"] == "risk")
    eq(risk["deadline"], "", "Quelldatum als Frist gelesen")
    ok(not risk["overdue"], "Risiko faelschlich ueberfaellig")


def t_briefing_shortens_at_word_and_link_boundaries():
    """Gekuerzt wird an einer Wortgrenze und nie mitten in einem [[Link]]: ein harter Schnitt machte
    aus "(Otto, Rita)" ein "(Ott" und aus der Quelle einen kaputten Link "(→ [[2…", der die Tabelle
    der Vorbereitung zerlegt."""
    import briefing as bf
    lang = ("Vier Jahresziel-Workshops mit den Teams werden durchgefuehrt und ausgewertet. "
            "(Otto, Rita, 2026-09-21)")
    _o, label, _c = bf._split_item(lang)
    ok(label.endswith("…") and "(Ott" not in label and len(label) <= 70, f"Label: {label!r}")
    ok(label.startswith("Vier Jahresziel-Workshops"), label)
    q = bf.default_question({"kind": "decision", "label": label, "owners": [], "stale": False})
    ok("„Vier Jahresziel-Workshops" in q and "(Ott" not in q, q)
    zelle = bf._cell("Zielbild fehlt; Prioritaet mit Otto klaeren (→ [[2026-09-02---runde---zahlungsabgleich]])", 60)
    ok("[[" not in zelle and zelle.endswith("…"), f"angeschnittener Link: {zelle!r}")
    eq(bf._cell("kurz | knapp", 60), "kurz \\| knapp")
    ganz = bf._cell("Quelle (→ [[2026-09-02---runde]]) und noch sehr viel mehr Text danach, bis es zu lang ist", 60)
    ok("[[2026-09-02---runde]]" in ganz, f"ganzer Link verloren: {ganz!r}")
    nur_link = bf.kuerzen("[[2026-09-11-ein-sehr-langer-link-auf-eine-quelle|Ergebnisse der Runde]] mit Zusatz", 25)
    ok("[[" not in nur_link and nur_link.startswith("Ergebnisse"), nur_link)


def t_briefing_project_topics_use_tasks_vault_wide_once():
    """Projekt-Themen kommen aus aufgaben.py: auch Punkte aus Meeting-Notizen
    anderer Reihen und aus `## Offene Punkte`; erledigte bleiben draussen; ein Punkt
    in Kurzform zaehlt genau einmal; eine Frage ist ihre eigene Ausgangsfrage."""
    d = temp_vault()
    try:
        import briefing as bf
        (d / "entities" / "projects" / "p.md").write_text(
            "---\ntype: project\ntitle: P\n---\n# P\n\n## Offene Punkte\n"
            "- [ ] ❓ Steht der Go-live-Termin? — an Robert (?) ➕ 2026-09-01\n"
            "- [ ] Angebot pruefen — @anna — 2026-10-01\n\n## Event Log\n"
            "- [2026-09-14] [RISK] Freigaberunde blockiert\n",
            encoding="utf-8", newline="\n")
        m = d / "active-meetings" / "2026" / "09"
        m.mkdir(parents=True)
        (m / "2026-09-20 - review - Andere Reihe.md").write_text(
            "---\ntype: meeting\ndate: '2026-09-20'\nthemen: [p]\n---\n## Actions\n"
            "- [ ] Magnus informieren — ? · [[p]] ➕ 2026-09-20\n"
            "- [x] Schon erledigt — ? · [[p]]\n", encoding="utf-8", newline="\n")
        topics = bf.project_topics({"slug": "p"}, today=date(2026, 9, 27))
        labels = sorted(t["label"] for t in topics)
        eq(labels, ["Angebot pruefen", "Freigaberunde blockiert", "Magnus informieren",
                    "Steht der Go-live-Termin?"], "falsche Themen:")
        q = next(t for t in topics if t["kind"] == "question")
        eq(bf.default_question(q), "Steht der Go-live-Termin?", "Frage nicht uebernommen:")
        act = next(t for t in topics if t["label"] == "Angebot pruefen")
        eq((act["deadline"], act["owners"]), ("2026-10-01", ["anna"]), "Kurzform:")
    finally:
        restore_vault()


def t_agenda_open_items_read_new_task_format_cleanly():
    """Kanonische Punkte in `## Actions` kommen als Kurzform in die Agenda: ohne Links, ohne
    ➕-Entstehungsdatum (sonst als Frist gelesen), erledigte gar nicht."""
    import agenda as ag
    importlib.reload(ag)
    note = ("## Actions\n"
            "- [ ] Lizenzen klaeren — [[daniel-mohr|Daniel Mohr]] · [[blue-cargo|Blue Cargo]]"
            " 📅 2026-10-03 ➕ 2026-09-21\n"
            "- [x] Erledigt — [[daniel-mohr]]\n")
    eq(ag.extract_open_items(note)["actions"],
       ["@daniel-mohr: Lizenzen klaeren -> Deadline: 2026-10-03"])


# ─────────────────────────────────────────── dates / keywords

def t_german_dates():
    """Deutsche Zeitangaben ('bis Freitag', 'naechsten Freitag', 'in 2 Wochen', 'Ende des Monats',
    'KW 42') werden relativ zum Basisdatum aufgeloest; Undeutbares ergibt None."""
    from zeitangaben import resolve
    base = date(2026, 9, 15)          # Dienstag
    eq(resolve("bis Freitag", base).isoformat(), "2026-09-18")
    eq(resolve("naechsten Freitag", base).isoformat(), "2026-09-25")
    eq(resolve("in 2 Wochen", base).isoformat(), "2026-09-29")
    eq(resolve("Ende des Monats", base).isoformat(), "2026-09-30")
    eq(resolve("KW 42", base).isoformat(), "2026-10-16")
    eq(resolve("irgendwann spaeter", base), None, "Undeutbares muss None sein")
    # Wochen = deren Freitag, auch gebeugt ("noch in dieser Woche", "der kommenden Woche")
    for text, want in (("noch in dieser Woche", "2026-09-18"), ("Ende dieser Woche", "2026-09-18"),
                       ("naechste Woche", "2026-09-25"), ("fuer die Arbeiten der kommenden Woche", "2026-09-25")):
        eq(resolve(text, base).isoformat(), want, f"{text}:")


def t_apply_entities_uses_company_template():
    """Automatisch angelegte Firmen bekommen das company.md-Template (Vertraege, SLAs, Dataview),
    nicht den generischen Fallback - der Singular von 'companies' ist 'company', nicht das
    'companie' eines rstrip('s')."""
    d = temp_vault()
    try:
        import vault_paths as vp
        import uebernehmen as hs
        tmpl_dir = d / ".templates"
        tmpl_dir.mkdir(exist_ok=True)
        (tmpl_dir / "company.md").write_text(
            "---\ntype: company\nname: {{title}}\ncontract_status: active\n"
            "last_updated: {{date:YYYY-MM-DD}}\n---\n# {{title}}\n\n"
            "## Vereinbarungen, SLAs & Vertraege\n- \n", encoding="utf-8", newline="\n")
        eq(hs.TEMPLATES, tmpl_dir, "TEMPLATES zeigt nicht auf den Test-Vault")
        created = hs.apply_entities(
            [{"category": "companies", "slug": "acme", "name": "Acme", "meta": {}}],
            dry_run=False)
        ok(created, "Firma wurde nicht angelegt")
        content = (vp.COMPANIES_DIR / "acme.md").read_text(encoding="utf-8")
        ok("Vereinbarungen, SLAs" in content,
           "company.md-Template nicht verwendet - generischer Fallback aktiv")
    finally:
        restore_vault()


def t_apply_entities_writes_description_and_stub_status():
    """`description` aus dem Payload landet im Rumpf; automatisch angelegte Entities bekommen
    `status: stub` und bleiben so als ungeprueft erkennbar, bis ein Mensch sie prueft."""
    d = temp_vault()
    try:
        import vault_paths as vp
        import uebernehmen as hs
        hs.apply_entities(
            [{"category": "systems", "slug": "orion", "name": "Orion",
              "meta": {"description": "Zentrales Rating-System."}}],
            dry_run=False)
        content = (vp.SYSTEMS_DIR / "orion.md").read_text(encoding="utf-8")
        ok("Zentrales Rating-System." in content, "Beschreibung fehlt im Rumpf")
        fm = vp.read_frontmatter(vp.SYSTEMS_DIR / "orion.md")
        eq(fm.get("status"), "stub", "automatisch angelegte Entity ohne status: stub")
    finally:
        restore_vault()


def t_atlas_team_slug_goes_to_teams_not_projects():
    """Ein unbekannter Slug, der im Vault schon als Team existiert, wird als 'teams' klassifiziert,
    nicht blind als Projekt angelegt - sonst gibt es dieselbe Einheit doppelt."""
    d = temp_vault()
    try:
        import vault_paths as vp
        import uebernehmen as hs
        import aufloesen as re_
        (vp.TEAMS_DIR / "qxt.md").write_text(
            "---\ntype: team\nname: QXT\n---\n", encoding="utf-8", newline="\n")
        cat, why = hs.classify_unknown_slug("qxt")
        eq(cat, "teams", "qxt haette als Team klassifiziert werden muessen: " + why)
    finally:
        restore_vault()


def t_curated_keywords_keep_short_terms():
    """Kuratierte Keywords gehen an keinem Laengenfilter verloren: Begriffe mit drei Buchstaben
    bleiben, Mehrwort-Keywords als Ganzes und je Wort - sonst faellt die Zuordnung ueber sie aus."""
    import vorbereiten
    toks = vorbereiten._curated_tokens(["cdp", "bxa", "one delta"])
    for w in ("cdp", "bxa", "delta", "one delta"):
        ok(w in toks, f"{w!r} fehlt in {sorted(toks)}")


# ─────────────────────────────────────────── glossar

def t_glossary_finds_shadowed_person_term():
    """Ein Glossar-Begriff mit demselben Dateinamen wie eine spaeter angelegte Person gilt als
    'ueberdeckt' - auch wenn Slug und Dateiname identisch sind (ein reiner Vergleich
    `slug != f.stem` uebersieht genau diesen Fall)."""
    d = temp_vault()
    try:
        import vault_paths as vp
        import glossar as gs
        (vp.GLOSSARY_DIR / "veit-pohl.md").write_text(
            "---\ntype: glossary_term\nterm: veit-pohl\nstatus: candidate\n---\n",
            encoding="utf-8", newline="\n")
        shadowed = gs.find_shadowed_terms()
        eq(shadowed, [], "vor Anlegen der Person darf nichts ueberdeckt sein")
        (vp.PEOPLE_DIR / "veit-pohl.md").write_text(
            "---\ntype: person\nname: Veit Pohl\n---\n", encoding="utf-8", newline="\n")
        shadowed = gs.find_shadowed_terms()
        eq(len(shadowed), 1, "Ueberdeckung nicht erkannt")
        eq(shadowed[0][1], "veit-pohl")
    finally:
        restore_vault()


def t_glossary_finds_shadowed_term_via_filename_fallback():
    """Ein Glossar-Begriff aus Vor- und Nachname trifft keinen Alias, wenn die Personen-Datei nur
    den Vornamen als `name` fuehrt. Dann entscheidet der Dateiname: ist er in beiden Kategorien
    gleich, gilt der Begriff als ueberdeckt."""
    d = temp_vault()
    try:
        import vault_paths as vp
        import glossar as gs
        (vp.GLOSSARY_DIR / "wiebke-winter.md").write_text(
            "---\ntype: glossary_term\nterm: wiebke winter\nstatus: candidate\n---\n",
            encoding="utf-8", newline="\n")
        (vp.PEOPLE_DIR / "wiebke-winter.md").write_text(
            "---\ntype: person\nname: Wiebke\n---\n", encoding="utf-8", newline="\n")
        shadowed = gs.find_shadowed_terms()
        eq(len(shadowed), 1, "Fallback ueber Dateinamen greift nicht")
        eq(shadowed[0][1], "wiebke-winter")
    finally:
        restore_vault()


def t_contexts_index_is_readonly_reference_list():
    """`entities/contexts/_index.md` ist eine generierte Verweisliste - kein
    Spiegeln einzelner Kontext-Dateien."""
    import kontexte as ci
    contexts = [{"id": "ctx-test", "name": "Test-Kontext", "subdomain": "sd-x",
                "owner": "team-x", "description": "Ein Testkontext."}]
    content = ci.build_content(contexts)
    ok("generated: true" in content, "Frontmatter-Markierung fehlt")
    ok("Nicht von Hand editieren" in content, "Read-only-Hinweis fehlt")
    ok("ctx-test" in content and "Test-Kontext" in content, "Kontext fehlt in der Tabelle")
    ok("count: 1" in content, "count-Feld fehlt/falsch")


def t_kanon_nachrichten_und_landkarte():
    """Nachrichten aus dem Domain Atlas kommen vollstaendig an: Typ, Reife, und Empfaenger in der Form
    `{node: …, lifecycle: …}` als ID mit eigener Reife - frueher wurde daraus der Text "{'node': …}".
    Das Kontext-Verzeichnis fuehrt Subdomaenen, Kontexte und Nachrichten mit Reife und Beschreibung,
    dazu Fachobjekte, Teams, Externe, Beziehungen und Ablaeufe (Schritte in Reihenfolge) - fuer das
    Plugin (Bild im Chat, Graph der Chat-Werkzeuge, auch am Handy)."""
    d = temp_vault()
    try:
        canon = d / "domain-atlas" / "canon"
        for sub, name, body in (
                ("subdomains", "sd-lagerhof", "id: sd-lagerhof\nname: Lagerhof\nkind: core\ndescription: Hof und Halle.\n"
                 "status:\n  lifecycle: agreed\n"),
                ("subdomains", "sd-auftragswesen", "id: sd-auftragswesen\nname: Auftragswesen\n"),
                ("contexts", "ctx-wareneingang", "id: ctx-wareneingang\nname: Wareneingang\nprimarySubdomain: sd-lagerhof\n"),
                ("contexts", "ctx-verladung", "id: ctx-verladung\nname: Verladung\nprimarySubdomain: sd-lagerhof\n"
                 "description: |\n  Lädt Paletten\n  auf den Lkw.\nstatus:\n  lifecycle: proposed\n"),
                ("contexts", "ctx-auftragsannahme", "id: ctx-auftragsannahme\nname: Auftragsannahme\n"
                                                    "primarySubdomain: sd-auftragswesen\nowner: [team-auftrag]\n"),
                ("messages", "msg-sendung-suchen", "id: msg-sendung-suchen\nname: finde \"Sendung\" nach Nummer\n"
                 "type: query\nproducers: [ctx-wareneingang, ctx-verladung]\nconsumers: [ctx-auftragsannahme]\n"
                 "status:\n  lifecycle: review\n"),
                ("messages", "msg-palette-gebildet", "id: msg-palette-gebildet\nname: Palette gebildet\ntype: event\n"
                 "producers:\n  - ctx-verladung\nconsumers:\n  - ctx-auftragsannahme\n"
                 "  - node: ctx-wareneingang\n    lifecycle: proposed\nstatus:\n  lifecycle: agreed\n"
                 "description: Palette fertig | verladebereit.\n"),
                ("object-refs", "obj-palette", "id: obj-palette\nconcept: Palette\ndisplayName: Palette\n"
                 "context: ctx-verladung\ndefinition: Ladungsträger.\naliases: [Pallet]\nstereotyp: entity\n"
                 "relationen:\n  - verb: liegt-auf\n    ziel: obj-ladeeinheit\n    kardinalitaet: 0..n\n"),
                ("teams", "team-auftrag", "id: team-auftrag\nname: Team Auftrag\ndescription: Nimmt Aufträge an.\n"),
                ("externals", "ext-spediteur", "id: ext-spediteur\nname: Spediteur\ncategory: partner\ndescription: Fährt.\n"),
                ("relations", "rel-verladung-auftrag", "id: rel-verladung-auftrag\nfrom: ctx-verladung\n"
                 "to: ctx-auftragsannahme\ntype: Customer-Supplier\ndescription: Liefert Paletten.\n"
                 "status:\n  lifecycle: proposed\n"),
                ("processes", "proc-verladen", "id: proc-verladen\nname: Verladen\nappliesTo: [ctx-verladung]\nsteps:\n"
                 "  - order: 1\n    context: ctx-auftragsannahme\n    ref: msg-sendung-suchen\n"
                 "  - order: 0\n    context: ctx-verladung\n    ref: msg-palette-gebildet\n"
                 "description: Erst Palette, dann Suche.\n")):
            (canon / sub).mkdir(parents=True, exist_ok=True)
            (canon / sub / f"{name}.yaml").write_text(body, encoding="utf-8", newline="\n")
        import kanon
        import kontexte as ci
        import kanon_vorschlaege as kv
        for m in (kanon, ci, kv):
            importlib.reload(m)
        k = kanon.lade()
        pal = next(m for m in k["nachrichten"] if m["id"] == "msg-palette-gebildet")
        eq((pal["typ"], pal["reife"], pal["produzenten"], pal["konsumenten"], pal["kanten_reife"]),
           ("event", "agreed", ["ctx-verladung"], ["ctx-auftragsannahme", "ctx-wareneingang"],
            {"ctx-wareneingang": "proposed"}))
        linked = kv.load_canon()["linked"]
        ok(("ctx-verladung", "ctx-wareneingang") in linked and not any("{" in a + b for a, b in linked), linked)
        text = ci.build_content(ci.load_contexts(), *ci.load_landkarte())
        ok("| `sd-lagerhof` | Lagerhof | 2 |" in text and "## Kontexte" in text, text)
        ok("| `msg-palette-gebildet` Palette gebildet | event | agreed | `ctx-verladung` "
           "| `ctx-auftragsannahme`, `ctx-wareneingang` (proposed) |" in text, text)
        ok("| `msg-sendung-suchen` finde \"Sendung\" nach Nummer | query | review "
           "| `ctx-wareneingang`, `ctx-verladung` | `ctx-auftragsannahme` |" in text, text)
        # Reife und Beschreibung (einzeilig, ohne Tabellen-Strich), der Rest des Kanons
        ok("| `sd-lagerhof` | Lagerhof | 2 | core | agreed | Hof und Halle. |" in text, text)
        ok("| `ctx-verladung` Verladung | sd-lagerhof |  | proposed | Lädt Paletten auf den Lkw. |" in text, text)
        ok("(proposed) | Palette fertig / verladebereit. |" in text, text)
        ok("## Fachobjekte" in text and "| `obj-palette` Palette | `ctx-verladung` | entity | Pallet "
           "| liegt-auf `obj-ladeeinheit` (0..n) | Ladungsträger. |" in text, text)
        ok("| `team-auftrag` Team Auftrag | Nimmt Aufträge an. |" in text, text)
        ok("| `ext-spediteur` Spediteur | partner | Fährt. |" in text, text)
        ok("| `rel-verladung-auftrag` rel-verladung-auftrag | Customer-Supplier | proposed | `ctx-verladung` "
           "| `ctx-auftragsannahme` | Liefert Paletten. |" in text, text)
        ok("| `proc-verladen` Verladen |  | `ctx-verladung` | `ctx-verladung`: `msg-palette-gebildet` → "
           "`ctx-auftragsannahme`: `msg-sendung-suchen` | Erst Palette, dann Suche. |" in text, text)
    finally:
        restore_vault()


def t_kontext_systeme_vorschlaege_und_haken():
    """Welches System setzt welchen Kontext um: Vorschlaege nur mit Beleg (Name, Daten laut
    Migrationstabellen, Team); Haken setzen ordnet zu (`atlas_kontexte:` auf der System-Seite), Haken
    weg nimmt die Zuordnung zurueck, eine eigene Zeile ordnet ein System ohne Vorschlag zu."""
    d = temp_vault()
    try:
        canon = d / "domain-atlas" / "canon"
        for sub, name, body in (
                ("subdomains", "sd-lagerhof", "id: sd-lagerhof\nname: Lagerhof\n"),
                ("teams", "team-halle", "id: team-halle\nname: Halle\n"),
                ("contexts", "ctx-verladung", "id: ctx-verladung\nname: Verladung\nprimarySubdomain: sd-lagerhof\n"
                                              "owner: [team-halle]\n"),
                ("contexts", "ctx-rampenplaner", "id: ctx-rampenplaner\nname: Rampenplaner\nprimarySubdomain: sd-lagerhof\n"),
                ("contexts", "ctx-wareneingang", "id: ctx-wareneingang\nname: Wareneingang\nprimarySubdomain: sd-lagerhof\n"),
                ("object-refs", "obj-palette", "id: obj-palette\nconcept: Palette\ncontext: ctx-verladung\n"),
                ("migration-tables", "mt-alt-pal", "id: mt-alt-pal\nsourceSystem: Altlager\nsourceId: PAL\n"
                 "migratingToObjectRef: obj-palette\ndescription: 'Eigentümer: Altlager → geplant: Hallenfunk'\n")):
            (canon / sub).mkdir(parents=True, exist_ok=True)
            (canon / sub / f"{name}.yaml").write_text(body, encoding="utf-8", newline="\n")
        S = d / "entities" / "systems"
        (S / "altlager.md").write_text("---\ntype: system\nname: Altlager\n---\n", encoding="utf-8", newline="\n")
        (S / "rampenplaner.md").write_text("---\ntype: system\nname: Rampenplaner\n---\n", encoding="utf-8", newline="\n")
        (S / "funkbox.md").write_text("---\ntype: system\nname: Funkbox\nowner_team: '[[halle-team]]'\n---\n",
                                      encoding="utf-8", newline="\n")
        (S / "scanner.md").write_text("---\ntype: system\nname: Scanner\n---\n", encoding="utf-8", newline="\n")
        (d / "entities" / "teams" / "halle-team.md").write_text("---\ntype: team\nname: Halle\n---\n",
                                                                encoding="utf-8", newline="\n")
        import kanon
        import kontext_systeme as ks
        for m in (kanon, ks):
            importlib.reload(m)
        v = ks.vorschlaege()
        by = {c["id"]: {x["system"]: x["gruende"] for x in c["vorschlaege"]} for c in v["kontexte"]}
        eq(by["ctx-verladung"], {"altlager": ["Daten heute in Altlager (1 Tabelle)"], "funkbox": ["Team [[halle-team]]"]})
        eq(by["ctx-rampenplaner"], {"rampenplaner": ["Name"]})
        eq(by["ctx-wareneingang"], {}, "ohne Beleg kein Vorschlag:")
        r = ks.automatik()
        text = ks.BERICHT.read_text(encoding="utf-8")
        ok("## Lagerhof `sd-lagerhof`" in text and "### Verladung `ctx-verladung`" in text, text)
        ok("- [ ] [[altlager|Altlager]] – Daten heute in Altlager (1 Tabelle) <!-- ks:ctx-verladung:altlager:0 -->" in text, text)
        ok("Wareneingang `ctx-wareneingang`" in text.split("## Ohne Vorschlag")[1], "Ohne Vorschlag fehlt")
        ok(r["changed"] and not (S / "altlager.md").read_text(encoding="utf-8").count("atlas_kontexte"),
           "nichts zugeordnet ohne Haken")
        # Haken setzen + eigene Zeile fuer einen Kontext ohne Vorschlag
        text = text.replace("- [ ] [[altlager|Altlager]]", "- [x] [[altlager|Altlager]]")
        text = text.replace("## Ohne Vorschlag", "### Wareneingang `ctx-wareneingang`\n- [x] [[scanner]]\n\n## Ohne Vorschlag")
        ks.BERICHT.write_text(text, encoding="utf-8", newline="\n")
        r = ks.automatik()
        eq(vp_fm(S / "altlager.md").get("atlas_kontexte"), ["ctx-verladung"])
        eq(vp_fm(S / "scanner.md").get("atlas_kontexte"), ["ctx-wareneingang"])
        ok("2 Zuordnung(en) übernommen" in " ".join(r["detail"]), r)
        text = ks.BERICHT.read_text(encoding="utf-8")
        ok("- [x] [[altlager|Altlager]]" in text and "<!-- ks:ctx-verladung:altlager:1 -->" in text, text)
        ok("- [x] [[scanner|Scanner]] – von Hand" in text, text)
        # Haken weg: Zuordnung zurueck, das Feld verschwindet
        ks.BERICHT.write_text(text.replace("- [x] [[altlager|Altlager]]", "- [ ] [[altlager|Altlager]]"),
                              encoding="utf-8", newline="\n")
        ks.automatik()
        ok("atlas_kontexte" not in (S / "altlager.md").read_text(encoding="utf-8"), "Zuordnung nicht entfernt")
        eq(vp_fm(S / "scanner.md").get("atlas_kontexte"), ["ctx-wareneingang"], "andere Zuordnung bleibt:")
    finally:
        restore_vault()


def vp_fm(p):
    import vault_paths as vp
    return vp.read_frontmatter(p)


# ─────────────────────────────────────────── aufloesen

def t_person_resolution():
    """Personen-Aufloesung: Vorname und voller Name treffen die Person, ein mehrdeutiger Vorname
    meldet alle Kandidaten, Unbekanntes ergibt None statt eines Fuzzy-Treffers auf Fremdes."""
    d = temp_vault()
    try:
        import vault_paths as vp
        import aufloesen as re_
        for slug, name in (("veit-pohl", "Veit Pohl"),
                           ("daniel-mohr", "Daniel Mohr"),
                           ("daniel-kranz", "Daniel Kranz")):
            (vp.PEOPLE_DIR / f"{slug}.md").write_text(
                f"---\ntype: person\nname: {name}\n---\n", encoding="utf-8", newline="\n")
        eq(re_._resolve_person("Veit")["slug"], "veit-pohl", "Vorname")
        eq(re_._resolve_person("Veit Pohl")["slug"], "veit-pohl", "Vollname")
        amb = re_._resolve_person("Daniel")
        eq(amb["resolved"], "ambiguous", "Mehrdeutigkeit muss gemeldet werden")
        eq(len(amb["candidates"]), 2, "Kandidaten fehlen")
        eq(re_._resolve_person("Unsinn"), None)
    finally:
        restore_vault()


# ─────────────────────────────────────────── rueckfragen






def t_clarification_ids_unique_within_same_second():
    """Klaerungs-IDs sind eindeutig, auch wenn zwei Klaerungen in derselben Sekunde entstehen (die
    CID ist nur sekundengenau, `%m%d-%H%M%S`) - sonst ueberschreibt save_pending() den ersten
    aufbewahrten Payload still mit dem zweiten."""
    d = temp_vault()
    try:
        import rueckfragen as ce
        cid1 = ce.add_clarification("Unbekannte Person 'x'", "c1", ["A", "B"])
        cid2 = ce.add_clarification("Unbekannte Person 'x'", "c2", ["A", "B"])
        ok(cid1 != cid2, f"CIDs kollidieren: {cid1} == {cid2}")
        ce.save_pending(cid1, {"payload": {"a": 1}})
        ce.save_pending(cid2, {"payload": {"a": 2}})
        eq(ce.load_pending(cid1)["payload"], {"a": 1}, "erster Payload wurde ueberschrieben")
        eq(ce.load_pending(cid2)["payload"], {"a": 2}, "zweiter Payload fehlt")
    finally:
        restore_vault()


def t_clarify_preflight_blocks_loop():
    """Die Vorabpruefung bricht eine Aufloesung auf eine nicht vorhandene Person ab und laesst die
    Wiedervorlage stehen - sonst erzeugt jeder Aufloesungsversuch eine neue Klaerung."""
    d = temp_vault()
    try:
        import rueckfragen as ce
        cid = "CLARIFY-TEST"
        ce.save_pending(cid, {"title": "Unbekannte Person 'X'", "kind": "unknown_person",
                              "payload": {"action_items": [
                                  {"owner": "__RESOLVE__", "project": "p", "task": "t"}]}})
        eq(ce.apply_pending(cid, "gibts-nicht"), False, "muss abbrechen")
        ok(ce.load_pending(cid) is not None, "Wiedervorlage wurde geloescht!")
    finally:
        restore_vault()


def t_sync_action_items_become_open_points_not_log_lines():
    """Aufgaben werden kanonische Punkte in `## Offene Punkte` (vor Beschreibung und Log angelegt),
    mit dem Datum der Quelle, ohne Dublette - auch nicht zu einem Punkt, der schon anderswo in der
    Datei steht; nie eine Zeile im Event Log."""
    d = temp_vault()
    try:
        import uebernehmen as hs
        import aufgaben as tk
        (d / "entities" / "people" / "anna-berg.md").write_text(
            "---\ntype: person\nname: Anna Berg\n---\n", encoding="utf-8", newline="\n")
        p = d / "entities" / "projects" / "p.md"
        p.write_text("---\ntype: project\ntitle: P\n---\n# P\n\n## Beschreibung\nText\n"
                     "- [ ] Alte Aufgabe — [[anna-berg]]\n\n## Event Log\n"
                     "- [2026-09-01] [STATUS] Start\n",
                     encoding="utf-8", newline="\n")
        src = "archive/meetings/2026-09/2026-09-21-review-p.md"
        acts = [{"task": "Angebot pruefen", "owner": "anna-berg", "project": "p",
                 "deadline": "2026-10-01"},
                {"task": "Alte  Aufgabe", "owner": "anna-berg", "project": "p", "deadline": "TBD"}]
        hs.apply_action_items(acts, source_file=src)
        hs.apply_action_items(acts, source_file=src)
        text = p.read_text(encoding="utf-8")
        eq(text.count("Angebot pruefen"), 1, "Dublette nach zweitem Lauf:")
        eq(text.count("lte Aufgabe"), 1, "vorhandener Punkt wurde verdoppelt:")
        ok(text.index("## Offene Punkte") < text.index("## Beschreibung") < text.index("## Event Log"),
           "Abschnitt falsch platziert")
        eq(text.count("[ACTION]"), 0, "neue Aufgabe landete im Event Log")
        line = next(l for l in text.splitlines() if "Angebot pruefen" in l)
        eq(line, "- [ ] Angebot pruefen — [[anna-berg|Anna Berg]] 📅 2026-10-01 ➕ 2026-09-21"
                 " (→ [[2026-09-21-review-p]])")
        t = next(t for t in tk.scan() if t.text == "Angebot pruefen")
        eq((t.owner, t.topics, t.is_open), ("anna-berg", ["p"], True))
    finally:
        restore_vault()


def t_wrapup_actions_canonical_with_context_owner():
    """Die Nachbereitung schreibt kanonische Punkte; ein mehrdeutiger Vorname wird nur ueber den
    Termin-/Themen-Kontext eindeutig; 'the team' ist keine Rueckfrage; der zweite Lauf ist
    idempotent; in den Sync gehen nur Entscheidungen, keine Aufgaben."""
    d = temp_vault()
    try:
        import nachbereiten
        importlib.reload(nachbereiten)
        for slug, name in (("robert-senger", "Robert Senger"), ("robert-keller", "Robert Keller"),
                           ("daniel-mohr", "Daniel Mohr")):
            (d / "entities" / "people" / f"{slug}.md").write_text(
                f"---\ntype: person\nname: {name}\n---\n", encoding="utf-8", newline="\n")
        (d / "entities" / "projects" / "blue-cargo.md").write_text(
            "---\ntype: project\ntitle: Blue Cargo\n---\n# Blue Cargo\n\n## Event Log\n"
            "- [2026-09-14] [STATUS] mit [[robert-senger]] besprochen\n", encoding="utf-8", newline="\n")
        fm = {"date": "2026-09-21", "themen": ["blue-cargo"], "key_persons": ["Daniel Mohr"]}
        meta = {"topic": "blue-cargo", "created": "2026-09-21",
                "persons": nachbereiten._person_context(fm)}
        text = "---\ntype: meeting\n---\n## Meine Notizen\nx\n\n## Actions\n"
        result = {"actions": [{"was": "Termin abstimmen", "wer": "Robert", "bis": ""},
                              {"was": "Symbol ergaenzen", "wer": "the team", "bis": ""},
                              {"was": "Lizenzen klaeren", "wer": "Daniel", "bis": "2026-10-03"}]}
        new, counts = nachbereiten.write_extract(text, result, {"kernteil": []}, None, meta)
        eq(counts["actions_neu"], 3)
        dl = "[[blue-cargo|Blue Cargo]]"
        for line in (f"- [ ] Termin abstimmen — [[robert-senger|Robert Senger]] · {dl} ➕ 2026-09-21",
                     f"- [ ] Symbol ergaenzen — ? · {dl} ➕ 2026-09-21",
                     f"- [ ] Lizenzen klaeren — [[daniel-mohr|Daniel Mohr]] · {dl} "
                     "📅 2026-10-03 ➕ 2026-09-21"):
            ok(line in new, f"Zeile fehlt: {line}\n--- war:\n{new}")
        again, c2 = nachbereiten.write_extract(new, result, {"kernteil": []}, None, meta)
        eq((again == new, c2["actions_neu"]), (True, 0), "zweiter Lauf nicht idempotent:")
        payload = nachbereiten.build_sync_payload([{"project": "blue-cargo", "result": {
            "actions": result["actions"], "entscheidungen": [{"was": "X", "wer": "", "datum": ""}]}}])
        eq(payload["action_items"], [], "Aufgaben gehen in den Sync (Kopie):")
        eq(payload["project_updates"][0]["events"], ["[DECISION] X"])
    finally:
        restore_vault()


def t_extract_assigns_topic_per_item_from_candidates_only():
    """Thema pro Punkt: das Modell waehlt nur aus den vom Code vorgewaehlten
    Kandidaten (Grammatik-Enum), Fremdes wird verworfen; Entscheidungen landen
    im Log des gewaehlten Themas, Aufgaben verlinken es, offene Fragen werden ❓."""
    d = temp_vault()
    try:
        import nachbereiten_modell as ml
        import nachbereiten
        importlib.reload(ml)
        importlib.reload(nachbereiten)
        seen = {}

        def fake_complete_json(messages, schema, **kw):
            seen["schema"] = schema
            seen["prompt"] = messages[1]["content"]
            return {"entscheidungen": [
                        {"was": "Routing-Regeln gelten ab Oktober", "wer": "", "datum": "", "thema": "produkt-odi"},
                        {"was": "Budget bleibt", "wer": "", "datum": "", "thema": "erfunden"}],
                    "actions": [{"was": "Gebiete klaeren", "wer": "", "bis": "", "thema": "blue-cargo"}],
                    "kernteil": [], "parkplatz": [],
                    "offene_fragen": ["Wer entscheidet ueber FTL/LTL?"]}, []

        orig = ml.modell.complete_json
        ml.modell.complete_json = fake_complete_json
        try:
            res = ml.extract("Material " * 30, {"kernteil": [], "meeting_type": "other"},
                             {"title": "T", "topics": [("produkt-odi", "Order Router"),
                                                       ("blue-cargo", "Blue Cargo")],
                              "default_topic": "produkt-odi"})
        finally:
            ml.modell.complete_json = orig
        enum = seen["schema"]["properties"]["actions"]["items"]["properties"]["thema"]["enum"]
        eq(enum, ["", "produkt-odi", "blue-cargo"], "Kandidaten nicht im Schema:")
        ok("produkt-odi = Order Router" in seen["prompt"], "Kandidaten nicht im Prompt")
        eq([e["thema"] for e in res["entscheidungen"]], ["produkt-odi", ""], "Fremdes Thema:")

        meta = {"topic": "produkt-odi", "created": "2026-09-25", "persons": set()}
        new, counts = nachbereiten.write_extract("## Actions\n", res, {"kernteil": []}, None, meta)
        ok("- [ ] Gebiete klaeren — ? · [[blue-cargo]] ➕ 2026-09-25" in new, new)
        ok("- [ ] ❓ Wer entscheidet ueber FTL/LTL? — ? · [[produkt-odi]] ➕ 2026-09-25" in new, new)
        payload = nachbereiten.build_sync_payload([{"project": "", "result": res}])
        eq({u["slug"]: u["events"] for u in payload["project_updates"]},
           {"produkt-odi": ["[DECISION] Routing-Regeln gelten ab Oktober"]},
           "Entscheidung ohne Meeting-Projekt nicht per thema geroutet:")
    finally:
        restore_vault()


# ─────────────────────────────────────────── reihen

def t_forum_needs_distinct_days():
    """Eine Reihe braucht Termine an verschiedenen Tagen: zwei Dateien vom selben Tag sind
    Dubletten, kein wiederkehrendes Format."""
    d = temp_vault()
    try:
        import reihen as fo
        same_day = [{"title": "Checkin EDI", "date": "2026-08-03", "type": "checkin"},
                    {"title": "Checkin EDI", "date": "2026-08-03", "type": "checkin"}]
        eq(len(fo.derive_candidates(same_day)), 0, "Dublette als Forum erkannt")
        two_days = [{"title": "Checkin EDI", "date": "2026-08-03", "type": "checkin"},
                    {"title": "Checkin EDI", "date": "2026-08-17", "type": "checkin"}]
        eq(len(fo.derive_candidates(two_days)), 1, "echtes Format nicht erkannt")
    finally:
        restore_vault()


# ─────────────────────────────────────────── Eingang: Mails, Kalender, Dokumente

def t_email_frontmatter_is_valid_yaml():
    """Das Frontmatter einer Mail-Notiz ist gueltiges YAML: gefaltete Header werden flachgelegt,
    Doppelpunkte im Titel brechen es nicht, kodierte Betreffs ergeben lesbare Slugs - sonst ist die
    Notiz fuer alle weiteren Schritte unlesbar."""
    import importlib.util
    import yaml
    sp = importlib.util.spec_from_file_location("ie", ENGINE / "mails.py")
    ie = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(ie)
    eq(ie.slugify_subject("=?windows-1252?Q?AW=3A_Plan_und_Stand?="), "plan-und-stand")
    eq(ie.slugify_subject("Subject\r\n mit Umbruch"), "subject-mit-umbruch")
    val = ie._fm_safe("Kilian <a@b.de>,\n\tQuentin <c@d.de>")
    ok("\n" not in val and "\t" not in val, "Header nicht flachgelegt")
    doc = f'title: "{ie._fm_safe("WG: NoLa - Payment Terms")}"\nto: "{val}"\n'
    parsed = yaml.safe_load(doc)
    eq(parsed["title"], "WG: NoLa - Payment Terms", "Doppelpunkt bricht YAML")


def t_extract_participants_handles_lastname_comma_firstname():
    """Teilnehmer aus Mail-Headern: bei 'Nachname, Vorname <email>' geht kein Namensteil verloren,
    Adressen ohne spitze Klammern und Namen mit Umlaut oder Bindestrich werden erkannt.
    Unquotiertes 'Nachname, Vorname' zerlegt getaddresses() RFC-konform in zwei Adress-Tokens -
    eine Grenze des Formats; geprueft wird, dass beide Teile ankommen."""
    import importlib.util
    sp = importlib.util.spec_from_file_location("ie2", ENGINE / "mails.py")
    ie = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(ie)
    headers = {
        "from": "Pohl, Veit <veit.pohl@firma.example>",
        "to": "daniel.mohr@firma.example",
        "cc": "Jörg Weber-Linde <joerg.weber-linde@firma.example>",
    }
    got = ie.extract_participants(headers)
    ok(any("Pohl" in g for g in got), f"Nachname vorher stillschweigend verloren: {got}")
    ok(any("Veit" in g for g in got), f"Vorname verloren: {got}")
    ok(any("Daniel" in g or "Mohr" in g for g in got), f"Adresse ohne Namen verloren: {got}")
    ok(any("Jörg" in g or "Weber-Linde" in g for g in got), f"Umlaut/Bindestrich-Name verloren: {got}")


def t_company_from_email_ignores_internal_domain():
    """Interne Domain kommt aus der Vault-Konfiguration (`interne_domains`) - nicht aus dem Code."""
    d = temp_vault()
    try:
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps({"interne_domains": ["firma.example"]}),
                                                        encoding="utf-8", newline="\n")
        import importlib.util
        sp = importlib.util.spec_from_file_location("ie3", ENGINE / "mails.py")
        ie = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(ie)
        eq(ie.company_from_email("kontakt@vendrix.example"), "vendrix")
        eq(ie.company_from_email("daniel.mohr@firma.example"), None, "interne Domain darf keine Firma sein")
        eq(ie.company_from_email("nicht-valide"), None)
        (d / ".2ndbrain" / "local.config.json").write_text("{}", encoding="utf-8", newline="\n")
        eq(ie.company_from_email("daniel.mohr@firma.example"), "firma", "ohne Konfiguration ist niemand intern:")
    finally:
        restore_vault()


def t_ical_unescape_and_unfold():
    """iCal-Escapes werden aufgeloest (`\\,` -> Komma, `\\n` -> Zeilenumbruch statt 'n') und
    gefaltete Zeilen verbunden - sonst werden lange DESCRIPTION/SUMMARY-Werte abgeschnitten."""
    import importlib.util
    sp = importlib.util.spec_from_file_location("ec", ENGINE / "kalender.py")
    # Import ohne Kalender-Adresse: kalender.py liest sie erst beim Abrufen
    ec = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(ec)
    eq(ec._unescape_ical("Hallo zusammen\\, wie geht's\\n\\nGruss"),
       "Hallo zusammen, wie geht's\n\nGruss")
    folded = "BEGIN:VEVENT\nSUMMARY:Ein sehr langer Titel der \n umgebrochen wurde\nEND:VEVENT"
    import ical
    unfolded = ical.unfold(folded)
    ok("Titel der umgebrochen wurde" in unfolded, "Zeilenfaltung nicht aufgeloest")


def t_ical_attendees_parsed():
    """ATTENDEE und ORGANIZER werden mit Name und Rolle gelesen."""
    import importlib.util
    sp = importlib.util.spec_from_file_location("ec2", ENGINE / "kalender.py")
    ec = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(ec)
    ev = ('DTSTART:20260901T090000\nSUMMARY:Jourfix\n'
          'ORGANIZER;CN="Daniel Mohr":mailto:daniel.mohr@firma.example\n'
          'ATTENDEE;CN="Veit Pohl";ROLE=REQ-PARTICIPANT:mailto:veit.pohl@firma.example\n')
    people = ec._parse_attendees(ev)
    roles = {p["role"] for p in people}
    names = {p["name"] for p in people}
    eq(roles, {"organizer", "attendee"})
    ok("Daniel Mohr" in names and "Veit Pohl" in names, f"Namen fehlen: {names}")


_VTZ_WEST = """BEGIN:VTIMEZONE
TZID:W. Europe Standard Time
BEGIN:STANDARD
DTSTART:16010101T030000
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=10
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:16010101T020000
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
RRULE:FREQ=YEARLY;INTERVAL=1;BYDAY=-1SU;BYMONTH=3
END:DAYLIGHT
END:VTIMEZONE
"""


def _kal(*teile):
    return "BEGIN:VCALENDAR\nVERSION:2.0\n" + "".join(teile) + "END:VCALENDAR\n"


def _west_local():
    import ical
    importlib.reload(ical)
    tz = ical.VTimezone(next(ical.walk(ical.parse(_kal(_VTZ_WEST)), "VTIMEZONE")))
    return ical, tz.from_utc


def t_calendar_any_ical_series_timezones_and_exceptions():
    """Jeder iCal-Kalender (Outlook, Google, iCloud; Adresse oder lokale Datei): Serien werden
    aufgefaltet (WEEKLY/MONTHLY/YEARLY/DAILY, INTERVAL, UNTIL, COUNT, BYDAY "2TU"), EXDATE faellt
    weg, ein verschobener Einzeltermin (RECURRENCE-ID) ersetzt seinen Serientermin statt ihn zu
    verdoppeln, Zeiten aus VTIMEZONE und UTC ("…Z") landen in Ortszeit; Absagen und Ablehnungen
    sind ein Status. Eine unbekannte Regel liefert nur den ersten Termin, mit Warnung."""
    from datetime import date as _d, datetime as _dt
    ical, west = _west_local()
    import kalender as ec
    importlib.reload(ec)
    outlook = _kal(_VTZ_WEST,
                   "BEGIN:VEVENT\nUID:serie-1\nSUMMARY:Jourfix Nord\n"
                   "DTSTART;TZID=W. Europe Standard Time:20260907T090000\n"
                   "RRULE:FREQ=WEEKLY;UNTIL=20261130T080000Z;INTERVAL=2;BYDAY=MO;WKST=MO\n"
                   "EXDATE;TZID=W. Europe Standard Time:20261005T090000\nEND:VEVENT\n",
                   "BEGIN:VEVENT\nUID:serie-1\nRECURRENCE-ID;TZID=W. Europe Standard Time:20260921T090000\n"
                   "SUMMARY:Jourfix Nord\nDTSTART;TZID=W. Europe Standard Time:20260921T110000\nEND:VEVENT\n",
                   "BEGIN:VEVENT\nUID:serie-1\nRECURRENCE-ID;TZID=W. Europe Standard Time:20261019T090000\n"
                   "SUMMARY:Declined: Jourfix Nord\nDTSTART;TZID=W. Europe Standard Time:20261019T090000\nEND:VEVENT\n",
                   "BEGIN:VEVENT\nUID:einzel-1\nSUMMARY;LANGUAGE=de-DE:Workshop\\, Teil 1\n"
                   "DTSTART;TZID=W. Europe Standard Time:20260915T140000\n"
                   "DESCRIPTION:Hallo zusammen\\,\\nBesprechungs-ID: 123 456 789\n"
                   'ATTENDEE;CN="Weber, Anna";PARTSTAT=ACCEPTED:mailto:anna@firma.example\nEND:VEVENT\n',
                   "BEGIN:VEVENT\nUID:ganztag-1\nSUMMARY:Feiertag\nDTSTART;VALUE=DATE:20261003\nEND:VEVENT\n")
    evs = ec.parse_events(outlook, "2026-09-01", "2026-11-30", own_emails=set(), local=west)
    got = sorted((e["date"], e["summary"], e["status"]) for e in evs)
    eq(got, [("20260907T090000", "Jourfix Nord", ""), ("20260915T140000", "Workshop, Teil 1", ""),
             ("20260921T110000", "Jourfix Nord", ""), ("20261003", "Feiertag", ""),
             ("20261019T090000", "Declined: Jourfix Nord", "abgelehnt"), ("20261102T090000", "Jourfix Nord", ""),
             ("20261116T090000", "Jourfix Nord", ""), ("20261130T090000", "Jourfix Nord", "")],
       "Outlook-Serie (Ausnahme 05.10., verschoben 21.09., abgelehnt 19.10., Sommerzeit-Ende 25.10.):")
    w = next(e for e in evs if e["summary"].startswith("Workshop"))
    eq((w["time"], w["attendees"][0]["name"], w["attendees"][0]["partstat"], w["uid"]),
       ("14:00", "Weber, Anna", "ACCEPTED", "einzel-1"), "Einzeltermin:")
    ok(next(e for e in evs if e["summary"] == "Feiertag")["all_day"], "ganztaegig")

    google = _kal("BEGIN:VEVENT\nUID:g-1\nSUMMARY:Standup\nDTSTART:20260928T070000Z\n"
                  "RRULE:FREQ=DAILY;COUNT=5;BYDAY=MO,TU,WE,TH,FR\nEND:VEVENT\n",
                  "BEGIN:VEVENT\nUID:g-2\nSUMMARY:Planung\nDTSTART:20260929T120000Z\nSTATUS:CANCELLED\nEND:VEVENT\n",
                  "BEGIN:VEVENT\nUID:g-3\nSUMMARY:Review\nDTSTART:20260930T130000Z\n"
                  "ATTENDEE;CN=Ich;PARTSTAT=DECLINED:mailto:ich@firma.example\nEND:VEVENT\n")
    evs = ec.parse_events(google, "2026-09-26", "2026-10-10", own_emails={"ich@firma.example"}, local=west)
    eq([e["date"] for e in sorted(evs, key=lambda e: e["date"]) if e["summary"] == "Standup"],
       ["20260928T090000", "20260929T090000", "20260930T090000", "20261001T090000", "20261002T090000"],
       "UTC in Ortszeit, COUNT zaehlt nur Werktage:")
    eq({e["summary"]: e["status"] for e in evs if e["summary"] != "Standup"},
       {"Planung": "abgesagt", "Review": "abgelehnt"}, "Absage als Status:")

    icloud = _kal("BEGIN:VTIMEZONE\nTZID:Europe/Berlin\nBEGIN:DAYLIGHT\nTZOFFSETFROM:+0100\nTZOFFSETTO:+0200\n"
                  "DTSTART:19810329T020000\nRRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU\nEND:DAYLIGHT\n"
                  "BEGIN:STANDARD\nTZOFFSETFROM:+0200\nTZOFFSETTO:+0100\nDTSTART:19961027T030000\n"
                  "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU\nEND:STANDARD\nEND:VTIMEZONE\n",
                  "BEGIN:VEVENT\nUID:c-1\nSUMMARY:Steering\nDTSTART;TZID=Europe/Berlin:20260908T100000\n"
                  "RRULE:FREQ=MONTHLY;BYDAY=2TU;UNTIL=20261231T235959Z\nEND:VEVENT\n",
                  "BEGIN:VEVENT\nUID:c-2\nSUMMARY:Jahrestag\nDTSTART;VALUE=DATE:20250206\n"
                  "RRULE:FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=6\nEND:VEVENT\n",
                  "BEGIN:VEVENT\nUID:c-3\nSUMMARY:Seltsam\nDTSTART;TZID=Europe/Berlin:20260901T080000\n"
                  "RRULE:FREQ=MONTHLY;BYDAY=MO,TU;BYSETPOS=-1\nEND:VEVENT\n")
    occ, warn = ical.events(icloud, _d(2026, 9, 1), _d(2027, 2, 28), local=west)
    eq([(o["comp"]["props"][1][2], o["start"]) for o in occ],
       [("Seltsam", _dt(2026, 9, 1, 8, 0)), ("Steering", _dt(2026, 9, 8, 10, 0)),
        ("Steering", _dt(2026, 10, 13, 10, 0)), ("Steering", _dt(2026, 11, 10, 10, 0)),
        ("Steering", _dt(2026, 12, 8, 10, 0)), ("Jahrestag", _d(2027, 2, 6))],
       "2. Dienstag im Monat, Jahrestag, unbekannte Regel nur erster Termin:")
    ok(len(warn) == 1 and "BYSETPOS" in warn[0] and "Seltsam" in warn[0], warn)

    eq([ec.source_kind(u) for u in ("webcal://p01.icloud.com/published/2/abc",
                                    "https://calendar.google.com/calendar/ical/x/private-y/basic.ics",
                                    "C:\\kal\\mein.ics", "~/kal.ics", "kalender", "http://kein-kalender")],
       ["web", "web", "datei", "datei", "", ""], "Quellen:")
    d = temp_vault()
    try:
        f = d / "kal.ics"
        f.write_text(google, encoding="utf-8", newline="\n")
        eq(ec.fetch_ics(str(f)), google, "lokale Datei:")
    finally:
        restore_vault()


def t_kanon_simple_yaml_instead_of_domain_atlas():
    """Der Kanon kann eine einfache YAML-Datei sein (Vorlage kanon.example.yaml) statt eines Domain
    Atlas: dieselben Fragen, Begriffe, Glossar-Eintraege, Kontexte und Namensaufloesung - mit
    neutralem Regelwerk: kein `ext-`/`ctx-`, keine Vier-Augen-Regel, Vorschlaege als YAML-Eintrag,
    Paket "Kanon-Review"."""
    from datetime import date as _date
    d = temp_vault()
    old_env = os.environ.pop("VAULT_DOMAIN_ATLAS", None)
    try:
        nl = chr(10)
        (d / "kanon.yaml").write_text((ENGINE / "kanon.example.yaml").read_text(encoding="utf-8"),
                                      encoding="utf-8", newline=nl)
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps(
            {"ich": "anna-muster", "kanon": {"format": "einfach", "pfad": "kanon.yaml"}}), encoding="utf-8", newline=nl)
        (d / "entities" / "people" / "anna-muster.md").write_text(
            "---\ntype: person\nname: Anna Muster\n---\n", encoding="utf-8", newline=nl)
        P = d / "entities" / "projects"
        (P / "disposition.md").write_text(
            "---\ntype: project\ntitle: Disposition\n---\n# Disposition\n\n## Event Log\n"
            "- [2026-09-20] [DECISION] Die Disposition geht an das Team Vertrieb (Owner)\n",
            encoding="utf-8", newline=nl)
        import kanon
        importlib.reload(kanon)
        k = kanon.lade()
        eq((k["format"], k["regeln"]["name"], len(k["kontexte"]), len(k["objekte"])), ("einfach", "Kanon", 2, 2), "Kanon:")
        eq(kanon.element(k, "disposition")["quelle"], "kanon.yaml", "Element:")
        import kanon_vorschlaege as av
        importlib.reload(av)
        today = _date(2026, 9, 28)
        qs, note, _st = av.collect(today)
        q = next(x for x in qs if x["typ"] == "Zuständigkeit")
        eq(q["titel"], "Zuständigkeit: Disposition → Vertrieb", "Frage:")
        ok(not q.get("erklaerung") and "ext-" not in av.EXT_HINT and av.EXT_HINT.startswith("Der Kanon führt"), av.EXT_HINT)
        r = av.answer(q["id"], "owner:ja", today=today, qs=qs, regen=False)
        pkg = (d / "reports" / f"atlas-review-{today.isoformat()}.md").read_text(encoding="utf-8")
        ok("# Kanon-Review" in pkg and "Beim Kontext `disposition` den Owner setzen: `owner: [team-vertrieb]`." in pkg
           and "resolve-intent" not in pkg and "ADR" not in pkg, pkg)
        import begriffsindex as ti
        importlib.reload(ti)
        ents = {(e["term"], e["kind"], e["topic"]) for e in ti.atlas_entries(k)}
        ok({("Disposition", "atlas-context", "disposition"), ("Pickup", "atlas-object", "disposition"),
            ("Auftragsabwicklung", "atlas-process", None)} <= ents, ents)
        import glossar as gb
        importlib.reload(gb)
        eq([(a["term"], a["context"], a["synonyms"]) for a in gb.atlas_terms(k)],
           [("Abholauftrag", "Disposition", ["Pickup"]), ("Lieferschein", "Auftragsannahme", [])], "Glossar:")
        import kontexte as ci
        importlib.reload(ci)
        content = ci.build_content(ci.load_contexts())
        ok("# Kanon-Kontexte" in content and "source: einfach" in content and "`disposition` Disposition" in content, content)
        # der Befehl `2ndbrain kontexte` selbst laeuft durch und meldet seine Quelle
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            eq(ci.run(as_json=False, dry_run=True), 0, "contexts-sync:")
        ok("Kontext(e) aus" in out.getvalue(), out.getvalue())
        import aufloesen as re_
        importlib.reload(re_)
        ok({"id": "disposition", "kind": "context", "name": "Disposition", "lifecycle": ""} in re_._kanon_items(),
           "Namensaufloesung")
    finally:
        if old_env is not None:
            os.environ["VAULT_DOMAIN_ATLAS"] = old_env
        restore_vault()


def t_svg_text_without_ocr():
    """Architekturskizzen tragen Labels als <text> im XML: sie werden ohne OCR gelesen, Entities
    dekodiert, doppelte Labels nur einmal uebernommen."""
    import dokumente as de
    d = Path(tempfile.mkdtemp())
    f = d / "a.svg"
    f.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<text x="10" y="10">Altsys</text>'
        '<text x="10" y="40">EDI/ESB</text>'
        '<text x="10" y="70">Luftfracht &lt;</text>'
        '<text x="10" y="70">Altsys</text>'
        '</svg>', encoding="utf-8", newline="\n")
    typ, content = de.extract_content(f)
    eq(typ, "Grafik / Diagramm")
    ok("Altsys" in content and "EDI/ESB" in content, "Labels fehlen")
    ok("Luftfracht <" in content, "HTML-Entity nicht dekodiert")
    eq(content.count("- Altsys"), 1, "Duplikat nicht entfernt")


def t_vtt_speaker_and_condense():
    """Transkripte (.vtt): Sprecher bleiben, Cue-IDs und Fuellzeilen fallen weg, aufeinanderfolgende
    Saetze desselben Sprechers werden zusammengefasst - sonst sprengt ein langes Transkript jedes
    Kontextfenster."""
    import dokumente as de
    d = Path(tempfile.mkdtemp())
    f = d / "t.vtt"
    f.write_text(
        "WEBVTT\n\n"
        "1dbc525b-9cb6-4167-b160-bad91a17edb0/6-0\n"
        "00:00:01.000 --> 00:00:03.000\n<v Daniel Mohr>Erster Satz.</v>\n\n"
        "00:00:03.000 --> 00:00:05.000\n<v Daniel Mohr>Zweiter Satz.</v>\n\n"
        "00:00:06.000 --> 00:00:07.000\n<v Timo>Mm.</v>\n\n"
        "00:00:08.000 --> 00:00:09.000\n<v Timo>Echte Aussage.</v>\n",
        encoding="utf-8", newline="\n")
    typ, content = de.extract_content(f)
    eq(typ, "Transkript")
    ok("Daniel Mohr" in content, "Sprecher fehlt")
    ok("1dbc525b" not in content, "Teams-Cue-ID durchgelassen")
    ok("Mm." not in content, "Fuellzeile nicht gefiltert")
    ok("Erster Satz. Zweiter Satz." in content, "gleicher Sprecher nicht zusammengefasst")


def t_zip_safety():
    """ZIP-Auspacken weist Path-Traversal, absolute Pfade und Zip-Bomben ab und ueberspringt
    verschachtelte Archive und Signaturbilder."""
    import zipfile
    import auspacken as co
    d = Path(tempfile.mkdtemp())
    z = d / "2026-01-01-test.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Workshop/Gruppe 1/Ergebnis.txt", "Inhalt\n" * 50)
        zf.writestr("Agenda.txt", "kurze Agenda")
        zf.writestr("../../etc/boese.txt", "traversal")
        zf.writestr("/absolut/boese.txt", "absolut")
        zf.writestr("innen.zip", b"PK\x03\x04" + b"\x00" * 50)
        zf.writestr("bombe.txt", "A" * 5_000_000)
        zf.writestr("image001.png", b"\x89PNG\r\n\x1a\n" + b"x" * 200)
    st = co.unpack_zip(z, dry_run=True)
    eq(st["members"], 2, "erwartet 2 verwertbare Mitglieder")
    eq(st["skipped_unsafe"], 3, "Traversal/absolut/Bombe nicht abgewiesen")
    eq(st["skipped_unsupported"], 1, "verschachteltes Archiv nicht uebersprungen")
    eq(st["skipped_noise"], 1, "Signaturbild nicht gefiltert")


def t_noise_filter_keeps_small_text():
    """Der Rauschfilter verwirft Signatur- und kleine Bilder sowie leere Dateien, aber keine kleinen
    Textdateien - eine kurze Agenda.txt aus einem Workshop traegt Bedeutung."""
    import auspacken as co
    ok(co._is_noise("image001.png", 5000, True), "Signaturbild nicht erkannt")
    ok(co._is_noise("logo.gif", 900, False), "kleines Bild nicht erkannt")
    ok(not co._is_noise("Agenda.txt", 68, False), "kleine Textdatei verworfen")
    ok(not co._is_noise("Notizen.md", 40, False), "kleine Notiz verworfen")
    ok(co._is_noise("leer.txt", 0, False), "leere Datei nicht erkannt")


def t_provenance_roundtrip():
    """Die Herkunft eines ausgepackten Anhangs (Container, Mitglied, Eltern-Notiz) wird vermerkt und
    genau einmal abgerufen - ohne sie haengt eine Anhang-Notiz an nichts."""
    d = temp_vault()
    try:
        import auspacken as co
        importlib.reload(co)
        co.record_provenance({"x.pdf": {"container": "mail.eml", "container_type": "email",
                                        "member": "Angebot.pdf", "parent": "mail-notiz"}})
        got = co.pop_provenance("x.pdf")
        eq(got["parent"], "mail-notiz")
        eq(co.pop_provenance("x.pdf"), None, "Eintrag muss danach weg sein")
    finally:
        restore_vault()


def t_container_member_name_has_no_double_date():
    """Ein ausgepacktes Mitglied traegt das Datum nur einmal im Namen: _slug fuegt keines hinzu,
    nach dem Abstreifen des fuehrenden Datums bleibt der Rest."""
    import auspacken as co
    eq(co._slug("2026-09-03-nola-days-workshop"), "2026-09-03-nola-days-workshop")
    import re as _re
    stripped = _re.sub(r"^\d{4}[-_]\d{2}[-_]\d{2}[-_]?", "", "2026-09-03-nola-days-workshop")
    eq(co._slug(stripped, 32), "nola-days-workshop")



# ─────────────────────────────────────────── Einarbeiten: arbeitspaket / eingang_abschluss

import subprocess as _sp

_TOOLS = ENGINE


def _next(**kw):
    """Naechstes Einarbeiten-Paket: (Code, Paket als JSON-Daten, stderr)."""
    import arbeitspaket as wp
    err = io.StringIO()
    with contextlib.redirect_stdout(err), contextlib.redirect_stderr(err):
        obj, rc = wp.next_packet(**kw)
    return rc, json.loads(json.dumps(obj, default=str)), err.getvalue()


def _mark(fn, *args, **kw):
    """eingang_abschluss.mark_done/mark_reset/mark_defer: (Code, Ergebnis-JSON, stderr)."""
    import eingang_abschluss as mm
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = getattr(mm, fn)(*args, **kw)
    return rc, (json.loads(out.getvalue()) if out.getvalue().strip() else None), err.getvalue()


def _mit_altbestand(text, new, *, day):
    """Test-Hilfe: Altbestand-Unterabschnitt in `## Offene Punkte` anlegen (Ueberschrift, Einleitung
    mit Datum, Punkte mit Hinweisen), im Format von aufgaben.py."""
    import aufgaben as tk
    lines = text.split("\n")
    block = []
    for t in new:
        block.append(tk.render(t))
        block += [tk.NOTE_PREFIX + n for n in t.notes]
    de = f"{day[8:10]}.{day[5:7]}.{day[0:4]}"
    head = [tk.ALTBESTAND_HEADING, "", tk.ALTBESTAND_INTRO.format(date=de), ""]
    idx = next(i for i, l in enumerate(lines) if l.strip() == tk.TOPIC_SECTION)
    end = next((j for j in range(idx + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    last = max([idx] + [j for j in range(idx + 1, end) if lines[j].strip()])
    insert = ["", *head, *block]
    lines[last + 1:last + 1] = insert
    after = last + 1 + len(insert)
    if after < len(lines) and lines[after].startswith(("## ", "### ")):
        lines.insert(after, "")
    return "\n".join(lines), len(new)


def _note(d, name, fm_lines, body):
    f = d / "inbox" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("---\n" + "\n".join(fm_lines) + "\n---\n" + body, encoding="utf-8", newline="\n")
    return f


def t_repair_leaked_keys_strips_only_leading_run():
    """Nackte Frontmatter-Keys direkt nach dem schliessenden --- werden entfernt; der Body bleibt,
    auch 'key: wert' im Fliesstext; der zweite Lauf ist ein No-op."""
    d = temp_vault()
    try:
        import vault_paths as vp
        f = d / "x.md"
        f.write_text("---\ntitle: T\n---\nnotes: leak\ntimestamp: leak\n"
                     "entities_created:\n- a\n\n# Real\nstatus: im Fliesstext ok\n",
                     encoding="utf-8", newline="\n")
        eq(vp.repair_leaked_keys(f), True, "muss reparieren")
        body = f.read_text(encoding="utf-8")
        ok("notes: leak" not in body and "- a" not in body, "Leak nicht entfernt")
        ok("# Real" in body and "status: im Fliesstext ok" in body, "Body beschaedigt")
        eq(vp.repair_leaked_keys(f), False, "zweiter Lauf = No-op")
    finally:
        restore_vault()


def t_update_frontmatter_remove_keys():
    """update_frontmatter(remove=...) entfernt Keys (fehlende werden ignoriert) und setzt im selben
    Schritt neue."""
    d = temp_vault()
    try:
        import vault_paths as vp
        f = d / "x.md"
        f.write_text("---\ntitle: T\nprocessed_at: gestern\n---\nBody\n", encoding="utf-8", newline="\n")
        eq(vp.update_frontmatter(f, {"status": "open"}, remove=("processed_at", "fehlt")),
           True, "muss aendern")
        fm = vp.read_frontmatter(f)
        ok("processed_at" not in fm and fm["status"] == "open", "remove wirkt nicht")
    finally:
        restore_vault()










def t_preparser_actions_first_word_is_no_owner():
    """Checkbox-Zeilen liest zerlegen.py ueber aufgaben.py: das erste Wort ist kein Owner
    ('[ ] Angebot pruefen' bleibt eine Aufgabe ohne Person); '@owner:' und 'bis <Datum>' aus
    Eingangs-Notizen gelten weiter; kanonische Punkte behalten Person, Frist und Erledigt-Status."""
    import zerlegen as mpp
    importlib.reload(mpp)
    acts = mpp.parse_action_items([
        "[ ] Angebot pruefen",
        "[ ] @felix: Liste bereitstellen bis 2026-10-02",
        "[x] Erledigtes — [[daniel-mohr]]",
        "[ ] Lizenzen klaeren — [[daniel-mohr|Daniel Mohr]] 📅 2026-10-03",
    ], date(2026, 9, 21))
    eq([(a["owner"], a["task"], a["deadline"], a["done"]) for a in acts], [
        ("unassigned", "Angebot pruefen", "TBD", False),
        ("felix", "Liste bereitstellen", "2026-10-02", False),
        ("daniel-mohr", "Erledigtes", "TBD", True),
        ("daniel-mohr", "Lizenzen klaeren", "2026-10-03", False)])


def t_validate_action_events_become_items_and_empty_owner_is_kept():
    """[ACTION]-Events des Modells werden Aufgaben (Personen-Pruefung, Offene Punkte) und verlassen
    das Log; eine Aufgabe ohne Namen wird ohne Person uebernommen statt still verworfen und erzeugt
    keine Rueckfrage."""
    import ausgabe_pruefen
    importlib.reload(ausgabe_pruefen)
    out, warnings, clar = ausgabe_pruefen.validate_and_fix({"project_updates": [{
        "slug": "p", "events": ["[DECISION] X",
                                "[ACTION] @unassigned: Angebot pruefen -> Deadline: 2026-10-01"]}]},
        {"projects": ["p"], "people": []})
    eq(out["project_updates"][0]["events"], ["[DECISION] X"], "ACTION blieb im Log:")
    eq([(a["task"], a["owner"], a["deadline"]) for a in out["action_items"]],
       [("Angebot pruefen", "", "2026-10-01")], "Aufgabe ohne Person verloren:")
    eq(clar, [], "leerer Owner darf keine Rueckfrage erzeugen")




def t_preparser_joins_wrapped_bullets_and_keeps_rich_notes_for_llm():
    """Umbrochene Beschluss-Bullets werden zu je einem Event verbunden, nicht in Fragmente zerlegt.
    Eine Notiz mit viel Inhalt oder ohne Zielprojekt geht ans Modell, statt automatisch
    abgeschlossen im Archiv zu landen; 'Entscheidungsvorlage' ist kein Beschluss-Abschnitt."""
    d = temp_vault()
    try:
        import zerlegen as mpp
        importlib.reload(mpp)
        wrapped = _note(d, "2026-01-11-board.md",
                        ["type: meeting", "date: 2026-01-11", "themen: [p]"],
                        "# Board\n\n## Beschlüsse und nächste Schritte\n"
                        "- Pilot startet im Februar,\n  Owner ist das Team A.\n"
                        "- Budget wird im März\n  neu bewertet.\n")
        pre = mpp.parse_meeting(str(wrapped))
        eq(pre["deterministic"]["events_by_project"]["p"],
           ["[DECISION] Pilot startet im Februar, Owner ist das Team A.",
            "[DECISION] Budget wird im März neu bewertet."], "Folgezeilen nicht verbunden")
        rich = _note(d, "2026-01-12-runde.md",
                     ["type: meeting", "date: 2026-01-12", "themen: [p]"],
                     "# Runde\n\n## 1. Thema\n" + ("Diskussion mit Zahlen. " * 120)
                     + "\n\n## Beschlüsse\n- A\n")
        eq(mpp.parse_meeting(str(rich))["needs_semantic_extraction"], True,
           "Notiz mit viel Inhalt darf nicht auto-completed werden")
        no_proj = _note(d, "2026-01-13-entscheidung.md", ["type: meeting"],
                        "# X\n\n## Entscheidung\nOption 3 gewaehlt.\n")
        eq(mpp.parse_meeting(str(no_proj))["needs_semantic_extraction"], True,
           "ohne Zielprojekt kein Auto-Complete")
        vorlage = _note(d, "2026-01-14-deck.md", ["type: meeting", "themen: [p]"],
                        "# Deck\n\n## Entscheidungsvorlage · X\nText\n")
        eq(mpp.find_sections(vorlage.read_text(encoding="utf-8"))["decisions"], [],
           "'Entscheidungsvorlage' ist kein Beschluss-Abschnitt")
    finally:
        restore_vault()


def t_rename_links_keeps_alias_and_whole_token_mentions():
    """Umbenennen schreibt alle Link-Formen um ([[x]], [[x|Alias]], [[x#Abschnitt]]) und
    @-Erwaehnungen nur als ganzes Token; ein laengerer Slug mit gleichem Anfang bleibt stehen."""
    d = temp_vault()
    try:
        import umbenennen as ren
        importlib.reload(ren)
        n = d / "note.md"
        n.write_text("[[timo]] [[timo|Timo]] [[timo#Rolle]] [[timo-martin]] "
                     "@timo: x @timo-martin: y", encoding="utf-8", newline="\n")
        ren.update_links_only("timo", "timo-martin")
        eq(n.read_text(encoding="utf-8"),
           "[[timo-martin]] [[timo-martin|Timo]] [[timo-martin#Rolle]] [[timo-martin]] "
           "@timo-martin: x @timo-martin: y")
    finally:
        restore_vault()


def t_eml_body_decodes_quoted_printable_without_cap():
    """Der Mail-Text wird aus quoted-printable dekodiert, nicht gekappt und nicht doppelt
    uebernommen (Text- und HTML-Teil)."""
    import importlib.util
    from email.message import EmailMessage
    sp = importlib.util.spec_from_file_location("ie4", ENGINE / "mails.py")
    ie = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(ie)
    msg = EmailMessage()
    msg["Subject"] = "Test"
    long_text = "Grüße für das Team. " * 400
    msg.set_content(long_text, charset="iso-8859-1", cte="quoted-printable")
    msg.add_alternative(f"<p>{long_text}</p>", subtype="html")
    body = ie.decode_body(msg)
    ok("Grüße für" in body, "quoted-printable nicht dekodiert")
    ok("=FC" not in body, "Rohkodierung im Text")
    ok(body.count("Grüße") == 400, "HTML-Dublette oder Kappung im Text")


def t_eml_decodes_encoded_word_names_and_attachments():
    """Encoded-Word-Header (RFC 2047) werden in Absender, Teilnehmern und Anhangnamen dekodiert;
    gefaltete Header stehen nicht roh im Text."""
    import email as _email
    import importlib.util
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    sp = importlib.util.spec_from_file_location("ie5", ENGINE / "mails.py")
    ie = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(ie)
    msg = MIMEMultipart()
    msg["From"] = "=?windows-1250?Q?T=EDmo_Kranich?= <Timo.Kranich@example.com>"
    msg["To"] = "Anna Beispiel <anna@example.com>,\n\t=?windows-1250?Q?S=F6nke_Stellmach?= <jw@example.com>"
    msg["Subject"] = "Test"
    msg["Date"] = "Tue, 15 Sep 2026 10:00:00 +0000"
    msg.attach(MIMEText("Hallo", "plain", "utf-8"))
    att = MIMEApplication(b"x" * 10)
    att.add_header("Content-Disposition", "attachment",
                   filename="=?Windows-1252?Q?=DCbersicht.xlsx?=")
    msg.attach(att)
    parsed = _email.message_from_bytes(msg.as_bytes())
    h = ie.extract_headers(parsed)
    participants = ie.extract_participants(h)
    ok("Tímo Kranich" in participants and "Sönke Stellmach" in participants,
       f"Namen nicht dekodiert: {participants}")
    _, md = ie.generate_vault_note(h, ie.decode_body(parsed), participants,
                                   ie.extract_attachments(parsed))
    ok("**Von:** Tímo Kranich <" in md, "Von-Zeile nicht dekodiert")
    ok("`Übersicht.xlsx`" in md, "Anhangname nicht dekodiert")
    ok("=?" not in md, "Encoded-Word im Text")
    ok("\n\t" not in md, "gefalteter Header im Text")


def _ausfuehrbare_zeilen(md: str) -> list[str]:
    """Zeilen, die Obsidian als ausfuehrbaren Codeblock liest: ein Zaun mit ausfuehrbarer
    Sprache (dataviewjs ...) ausserhalb eines aeusseren Codeblocks - auch im Zitat oder hinter
    einem Listenpunkt. Aeussere Bloecke nach CommonMark: schliessen nur mit gleich langem oder
    laengerem Zaun ohne Sprache."""
    import re
    import fremdtext
    offen, treffer = None, []
    for line in md.splitlines():
        m = re.match(r"^(`{3,}|~{3,})(.*)$", line)
        if offen:
            if m and m.group(1)[0] == offen[0] and len(m.group(1)) >= len(offen) and not m.group(2).strip():
                offen = None
            continue
        z = fremdtext._ZAUN.match(line)
        if z and fremdtext.ausfuehrbar(z.group("sprache")):
            treffer.append(line)
        elif m:
            offen = m.group(1)
    return treffer


def t_foreign_text_never_becomes_executable_code():
    """Mail, Dokument, Anhang und LLM-Antwort sind Fremdtext und werden nie ausfuehrbarer Code:
    Dataview fuehrt ```dataviewjs beim Anzeigen als JavaScript aus (am Desktop mit Zugriff auf
    Dateien und Prozesse). Ausfuehrbare Zaeune werden in jeder Verschachtelung entschaerft,
    harmloser Text bleibt; ein ``` in der Mail bricht nicht aus dem Thread-Block aus, die
    Zusammenfassung ist durchgehend zitiert; Markdown-Anhaenge und Modell-Antworten (Text und
    JSON) werden ebenfalls entschaerft."""
    import importlib.util
    import fremdtext as ft
    F = "`" * 3
    nl = chr(10)
    code = nl.join([F + "dataviewjs", "dv.paragraph('boese')", F])

    # 1) Baustein: nur ausfuehrbare Sprachen werden neutral, in jeder Verschachtelung
    for zeile in (F + "dataviewjs", "~~~dataviewjs", "   " + F + " DataviewJS x", "> " + F + "dataviewjs",
                  "- " + F + "dataviewjs", "1. > " + F + "dataviewjs", F + "js-engine", F + "run-python"):
        eq(_ausfuehrbare_zeilen(ft.entschaerfen(zeile)), [], f"nicht entschaerft: {zeile!r}")
        ok("text " in ft.entschaerfen(zeile), ft.entschaerfen(zeile))
    for harmlos in ("Hallo Welt", F + "mermaid" + nl + "graph TD" + nl + F, F + "dataview" + nl + "LIST" + nl + F,
                    F + "python" + nl + "x = 1" + nl + F, "Preis ~~~ circa"):
        eq(ft.entschaerfen(harmlos), harmlos, "harmloser Text veraendert:")
    eq(ft.entschaerfen_daten({"a": [code], "b": 3})["b"], 3)
    eq(_ausfuehrbare_zeilen(ft.entschaerfen_daten({"a": [code]})["a"][0]), [])
    eq(ft.zaun("Hallo"), F + nl + "Hallo" + nl + F, "normaler Text: Zaun wie bisher")
    eq(ft.zaun("a" + nl + F + F[:1] + nl + "b")[:5], F + F[:1] + F[:1], "Zaun laenger als Inhalt:")

    # 2) Mail: Ausbruch aus dem Thread-Block und ungequotete Zusammenfassung
    sp = importlib.util.spec_from_file_location("ie_ft", ENGINE / "mails.py")
    ie = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(ie)
    h = {"subject": "Angebot", "from": "x@example.com", "to": "y@example.com",
         "date": "Tue, 15 Sep 2026 10:00:00 +0000"}
    for body in ("Hallo," + nl + F + nl + code + nl + "Gruss",      # Ausbruch
                 code + nl + "Gruss"):                               # in der Zusammenfassung
        _, md = ie.generate_vault_note(h, body, [], [])
        eq(_ausfuehrbare_zeilen(md), [], "Mail wird Code:")
        ok("dv.paragraph('boese')" in md, "Mailtext fehlt")
    _, md = ie.generate_vault_note(h, "Hallo Anna," + nl + "anbei die Zahlen.", [], [])
    ok(nl.join(["> Hallo Anna,", "> anbei die Zahlen."]) in md, md)
    ok(nl.join([F, "Hallo Anna,", "anbei die Zahlen.", F]) in md, "normaler Thread-Block veraendert")

    # 3) Dokument aus dem Eingang
    import dokumente as de
    d = Path(tempfile.mkdtemp(prefix="vaulttest-"))
    _TEMP_VAULTS.append(d)
    (d / "inbox").mkdir()
    doc = d / "inbox" / "2026-09-20 Protokoll.txt"
    doc.write_text("Protokoll" + nl + code + nl, encoding="utf-8", newline=nl)
    note = de.process_inbox_document(doc, str(d))
    md = note.read_text(encoding="utf-8")
    eq(_ausfuehrbare_zeilen(md), [], "Dokument wird Code:")
    ok("dv.paragraph('boese')" in md and "Protokoll" in md, md)

    # 3b) Markdown-Anhang (Mail oder ZIP) - landet sonst unveraendert im Eingang
    temp_vault()
    try:
        import auspacken as co
        importlib.reload(co)
        md_anhang = co._write_member(("Notizen" + nl + code + nl).encode("utf-8"), "notizen.md", "2026-09-20", False)
        eq(_ausfuehrbare_zeilen(md_anhang.read_text(encoding="utf-8")), [], "Markdown-Anhang wird Code:")
        roh = b"Nur Text \xe4 ohne Codeblock"   # kein UTF-8 und nichts zu tun: Bytes bleiben
        eq(co._write_member(roh, "alt.md", "2026-09-20", False).read_bytes(), roh, "harmloser Anhang veraendert:")
    finally:
        restore_vault()

    # 4) LLM-Antwort (das Modell liest fremde Mails mit) - Text und JSON
    import modell
    alt = {k: os.environ.get(k) for k in ("VAULT_LLM_URL", "VAULT_LLM_OFFLINE", "VAULT_LLM_LOG")}
    post = modell._http_post
    os.environ.update({"VAULT_LLM_URL": "http://llm.test", "VAULT_LLM_OFFLINE": "0",
                       "VAULT_LLM_LOG": str(d / "llm.jsonl")})
    try:
        antwort = {"text": "Zusammenfassung:" + nl + code}
        modell._http_post = lambda url, payload, to: {"choices": [{"message": {"content": antwort["text"]}}]}
        eq(_ausfuehrbare_zeilen(modell.complete([{"role": "user", "content": "x"}])), [], "LLM-Text wird Code:")
        antwort["text"] = json.dumps({"stand": "ok" + nl + code})
        payload, _ = modell.complete_json([{"role": "user", "content": "x"}], {"type": "object"})
        eq(_ausfuehrbare_zeilen(payload["stand"]), [], "LLM-JSON wird Code:")
    finally:
        modell._http_post = post
        for k, v in alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v












def t_sync_force_bypasses_hash():
    """sync(force=True) wendet einen schon angewendeten Payload erneut an; ohne force blockiert der
    Payload-Hash die Wiederholung."""
    d = temp_vault()
    try:
        import uebernehmen as hs
        import vault_paths as vp
        vp.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        pf = vp.PROJECTS_DIR / "p1.md"
        pf.write_text("---\ntype: project\nname: P1\n---\n# P1\n\n## Event Log\n",
                      encoding="utf-8", newline="\n")
        raw = json.dumps({"project_updates": [{"slug": "p1", "events": ["[STATUS] la"]}]})
        eq(hs.sync(raw, source_file="t.md"), 0, "Erstlauf")
        ok("[STATUS] la" in pf.read_text(encoding="utf-8"), "Event fehlt")
        # Event manuell entfernen; ohne force blockiert der Hash den Re-Apply
        pf.write_text(pf.read_text(encoding="utf-8").replace("[STATUS] la", "").strip() + "\n",
                      encoding="utf-8", newline="\n")
        hs.sync(raw, source_file="t.md")
        ok("[STATUS] la" not in pf.read_text(encoding="utf-8"), "Hash-Skip griff nicht")
        hs.sync(raw, source_file="t.md", force=True)
        ok("[STATUS] la" in pf.read_text(encoding="utf-8"), "force hat nicht re-applied")
    finally:
        restore_vault()


def _mail_note(d, stem, body="Hallo Daniel,\nanbei das Angebot fuer den 08.10.\n"):
    return _note(d, f"{stem}.md",
                 ["type: email-thread", f"title: {stem}", "from: Merten <b@example.com>"],
                 f"# Mail\n\n**Datum:** 2026-09-15\n\n## Vollständiger Thread\n\n```\n{body}```\n")


def _attachment_note(d, name, parent, text):
    return _note(d, name,
                 ["type: meeting", "date: 2026-09-15", "container_type: email",
                  'source_container: "WG- Angebot.eml"', f"source_member: \"{name}.pdf\"",
                  f"parent: '[[{parent}]]'"],
                 f"# Anhang\n\n## Dokumenten-Inhalt\n\n{text}\n")








def t_validate_maps_system_slug_to_product():
    """Systeme sind keine Projekte: ein System-Slug landet beim Produkt zum System
    ('x' -> 'produkt-x'), ein Firmenname bei der Firma ('firma-x') - mit Hinweis, ohne Klaerung."""
    import ausgabe_pruefen
    payload = {"project_updates": [{"slug": "nola", "events": ["[STATUS] x"]}],
               "action_items": [{"owner": "", "project": "nola", "task": "t"}]}
    out, warnings, clar = ausgabe_pruefen.validate_and_fix(
        payload, {"projects": ["produkt-nola", "linkone"], "people": []})
    eq(out["project_updates"][0]["slug"], "produkt-nola", "Produkt-Zuordnung fehlt")
    eq(clar, [], "darf keine Klaerung erzeugen")
    ok(any("Produkt zum System" in w for w in warnings), "Hinweis fehlt")
    out, warnings, clar = ausgabe_pruefen.validate_and_fix(
        {"project_updates": [{"slug": "Brixwerk", "events": ["[STATUS] y"]}]},
        {"projects": ["firma-brixwerk"], "people": []})
    eq(out["project_updates"][0]["slug"], "firma-brixwerk", "Firmen-Zuordnung fehlt")


def t_ingest_unpacks_attachments_before_archiving_mail():
    """Mit keep_source bleibt die .eml nach dem Einlesen liegen, bis auspacken.py ihre Anhaenge
    ausgepackt hat; erst dann kommt sie ins Archiv - sonst findet das Auspacken die Mail nicht mehr.
    Der Anhang verweist auf die Mail-Notiz."""
    d = temp_vault()
    try:
        import importlib
        from email.message import EmailMessage
        import vault_paths as vp
        import auspacken
        importlib.reload(auspacken)
        import mails as ie
        msg = EmailMessage()
        msg["From"] = "Merten <b@example.com>"
        msg["To"] = "Daniel <m@example.com>"
        msg["Subject"] = "WG: ZEBRA-Migrations-Angebot"
        msg["Date"] = "Tue, 15 Sep 2026 10:00:00 +0200"
        msg.set_content("Anbei das Angebot.")
        msg.add_attachment(b"Angebot Zelmar 12 PT\n" * 20, maintype="text", subtype="plain",
                           filename="Angebot.txt")
        (d / "inbox").mkdir(exist_ok=True)
        eml = d / "inbox" / "WG- ZEBRA-Migrations-Angebot.eml"
        eml.write_bytes(msg.as_bytes())
        ie.process_eml(str(eml), str(d / "inbox"), keep_source=True)
        ok(eml.is_file(), "--keep-source hat die .eml trotzdem verschoben")
        auspacken.run()
        members = [f for f in (d / "inbox").iterdir() if f.suffix == ".txt"]
        eq(len(members), 1, "Anhang nicht ausgepackt")
        prov = auspacken.load_provenance().get(members[0].name, {})
        eq(prov.get("parent"), "2026-09-15-zebra-migrations-angebot", "Mail-Bezug falsch")
        ok(not eml.exists(), ".eml nicht archiviert")
        ok((vp.SOURCES_DIR / "emails" / "2026-09" / eml.name).is_file(), "Archivpfad falsch")
    finally:
        restore_vault()


def t_mail_same_subject_same_day_gets_own_note():
    """Mehrere Mails mit gleichem Betreff am selben Tag bekommen je eine eigene Notiz (Uhrzeit im
    Namen) - sonst ueberschreiben sie sich, und alle Anhaenge haengen an der letzten. Ein erneuter
    Import derselben Mail behaelt ihren Namen, jeder Anhang zeigt auf seine Mail."""
    d = temp_vault()
    try:
        from email.message import EmailMessage
        import vault_paths as vp
        import auspacken
        importlib.reload(auspacken)
        import mails as ie
        (d / "inbox").mkdir(exist_ok=True)
        emls = []
        for i, zeit in enumerate(("12:16:53", "12:33:40", "12:37:58")):
            msg = EmailMessage()
            msg["From"] = "Merten <b@example.com>"
            msg["To"] = "Daniel <m@example.com>"
            msg["Subject"] = ("AW: " if i != 1 else "RE: ") + "Server gesperrt"
            msg["Date"] = f"Tue, 22 Sep 2026 {zeit} +0000"
            msg["Message-ID"] = f"<mail-{i}@example.com>"
            msg.set_content(f"Antwort {i}")
            msg.add_attachment((f"Log {i}\n" * 30).encode(), maintype="text", subtype="plain",
                               filename=f"log-{i}.txt")
            eml = d / "inbox" / f"AW- Server gesperrt {i}.eml"
            eml.write_bytes(msg.as_bytes())
            emls.append(eml)
            ie.process_eml(str(eml), str(d / "inbox"), keep_source=True)
        notes = sorted(f.stem for f in (d / "inbox").glob("*.md"))
        eq(notes, ["2026-09-22-server-gesperrt", "2026-09-22-server-gesperrt-1233",
                   "2026-09-22-server-gesperrt-1237"], "Notizen:")
        ok("Antwort 0" in (d / "inbox" / "2026-09-22-server-gesperrt.md").read_text(encoding="utf-8"),
           "erste Mail ueberschrieben")
        ie.process_eml(str(emls[2]), str(d / "inbox"), keep_source=True)       # erneuter Import
        eq(len(list((d / "inbox").glob("*.md"))), 3, "erneuter Import legt eine weitere Notiz an")
        auspacken.run()
        prov = auspacken.load_provenance()
        parents = {prov[f.name]["member"]: prov[f.name]["parent"] for f in (d / "inbox").glob("*.txt")}
        eq(parents, {"log-0.txt": "2026-09-22-server-gesperrt", "log-1.txt": "2026-09-22-server-gesperrt-1233",
                     "log-2.txt": "2026-09-22-server-gesperrt-1237"}, "Anhang an falscher Mail:")
        eq([e.exists() for e in emls], [False] * 3, "Mails nicht archiviert")
        eq(len(list((vp.SOURCES_DIR / "emails" / "2026-09").glob("*.eml"))), 3, "Archiv:")
    finally:
        restore_vault()


def t_auto_imports_mails_and_inbox_files():
    """Die Automatik liest den Eingang ein: die Mail wird Notiz, ihr Anhang wird Notiz, die Mail kommt
    ins Archiv. Was du selbst in inbox/ ablegst, wird ebenso Notiz (das Original nach .attachments/);
    was sich nicht lesen laesst, bleibt mit Grund liegen, ohne dass der Lauf scheitert. Was im
    Vault-Ordner selbst liegt (etwa ein Handbuch), bleibt unberuehrt."""
    d = temp_vault()
    try:
        from email.message import EmailMessage
        import vault_paths as vp
        import auto
        importlib.reload(auto)
        msg = EmailMessage()
        msg["From"] = "Merten <b@example.com>"
        msg["To"] = "Daniel <m@example.com>"
        msg["Subject"] = "Protokoll Lenkungskreis"
        msg["Date"] = "Tue, 22 Sep 2026 09:41:41 +0000"
        msg["Message-ID"] = "<lk-1@example.com>"
        msg.set_content("Anbei das Protokoll.")
        msg.add_attachment(("Beschluss: Go-Live im Oktober\n" * 5).encode(), maintype="text", subtype="plain",
                           filename="Protokoll.txt")
        eml = d / "Gemeinsam-Eins- Protokoll.eml"
        eml.write_bytes(msg.as_bytes())
        eigenes = d / "Handbuch.txt"
        eigenes.write_text("Selbst abgelegt\n", encoding="utf-8", newline="\n")
        vp.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        (vp.INBOX_DIR / "Notizen Portal.txt").write_text("Eigene Notizen zum Portal: Rampe pruefen.\n" * 3,
                                                          encoding="utf-8", newline="\n")
        alt = vp.INBOX_DIR / "Alt.doc"
        alt.write_bytes(b"kein Word-Dokument")
        r = auto.run(only={"mails"}, llm_status=(False, "aus"))
        st = r["steps"][0]
        ok(st["ok"] and st["changed"] == 3, st)
        notes = sorted(f.name for f in vp.INBOX_DIR.glob("*.md"))
        ok("2026-09-22-protokoll-lenkungskreis.md" in notes, notes)
        anhang = [n for n in notes if "protokoll" in n and "lenkungskreis" not in n]
        eq(len(anhang), 1, f"Anhang-Notiz fehlt: {notes}")
        ok("Go-Live im Oktober" in (vp.INBOX_DIR / anhang[0]).read_text(encoding="utf-8"), "Anhang-Inhalt")
        ok(not eml.exists() and (vp.SOURCES_DIR / "emails" / "2026-09" / eml.name).is_file(), "Mail nicht archiviert")
        ok(any("Rampe pruefen" in (vp.INBOX_DIR / n).read_text(encoding="utf-8") for n in notes),
           f"eigene Datei nicht eingelesen: {notes}")
        ok(not (vp.INBOX_DIR / "Notizen Portal.txt").exists() and list((d / ".attachments").rglob("Notizen Portal.txt")),
           "Original nicht nach .attachments/")
        ok(alt.is_file() and "Alt.doc (altes Format, bitte als .docx speichern)" in st["detail"], st["detail"])
        ok(eigenes.is_file(), "Datei im Vault-Ordner angefasst")
        zweiter = auto.run(only={"mails"}, llm_status=(False, "aus"))["steps"][0]
        eq((zweiter["ok"], zweiter["changed"]), (True, 0), f"zweiter Lauf: {zweiter}")
        alt.unlink()
        eq(auto.run(only={"mails"}, llm_status=(False, "aus"))["steps"][0]["detail"], "nichts im Eingang")
    finally:
        restore_vault()


def t_nachbereiten_in_arbeit_und_waehrenddessen_geaendert():
    """Waehrend das Modell einen Termin nachbereitet, steht er als in Arbeit (inarbeit.py) - das Plugin
    schreibt andere Notizen weiter, diese erst danach. Aendert sich der Termin trotzdem, waehrend das
    Modell rechnet (im Editor getippt), ueberschreibt die Nachbereitung nichts; in der Automatik bleibt
    die Vormerkung fuer den naechsten Lauf."""
    d = temp_vault()
    import modell
    orig = (modell.complete_json, modell.available)
    try:
        import vault_paths as vp
        import inarbeit
        import nachbereiten as nb
        import auto
        for mod in (inarbeit, nb, auto):
            importlib.reload(mod)
        m = d / "active-meetings"
        m.mkdir(parents=True, exist_ok=True)
        mitschrift = "Wir haben A beschlossen. Otto erledigt X bis Freitag. " * 6
        eins, zwei = m / "2026-09-21 - review - Runde.md", m / "2026-09-22 - review - Runde.md"
        for note, tag in ((eins, "21"), (zwei, "22")):
            note.write_text(f"---\ntype: meeting\ntitle: Runde\ndate: '2026-09-{tag}'\n---\n## Mitschrift\n\n{mitschrift}\n",
                            encoding="utf-8", newline="\n")
        antwort = {"entscheidungen": [{"was": "A beschlossen", "wer": "", "datum": "", "thema": ""}],
                   "actions": [], "kernteil": [], "parkplatz": []}
        gesehen = []

        def fake(messages, schema, **kw):
            gesehen.append(inarbeit.aktuell())
            return antwort, []
        modell.complete_json, modell.available = fake, lambda *a, **k: (True, "test")
        r = nb.process_note(eins, min_chars=30)
        eq((gesehen[0], inarbeit.aktuell(), r["changed"]),
           (["active-meetings/2026-09-21 - review - Runde.md"], [], True), "in Arbeit nur waehrend des Modells:")

        def tippt(messages, schema, **kw):
            zwei.write_text(zwei.read_text(encoding="utf-8") + "\nNachtrag im Editor.\n", encoding="utf-8", newline="\n")
            return antwort, []
        modell.complete_json = tippt
        vp.update_frontmatter(zwei, {auto.WRAPUP_FLAG: auto.WRAPUP_REQUESTED})
        auto.run(only={"nachbereiten"}, llm_status=(True, "test"))
        text = zwei.read_text(encoding="utf-8")
        ok("Nachtrag im Editor." in text and "## Entscheidungen" not in text, text)
        eq((vp_read(zwei).get(auto.WRAPUP_FLAG), vp_read(zwei).get("status"), inarbeit.aktuell()),
           (auto.WRAPUP_REQUESTED, None, []), "Vormerkung bleibt, nichts nachbereitet:")
        eq(nb.process_note(zwei, dry_run=True, min_chars=30)["changed"] is not None and inarbeit.aktuell(), [],
           "Probelauf markiert nichts")
    finally:
        modell.complete_json, modell.available = orig
        restore_vault()


def t_stand_haken_waehrend_des_modells_bleibt():
    """Setzt jemand einen Haken in der Themen-Datei, waehrend das Modell den Stand schreibt (Plugin,
    Editor), bleibt er: der Stand-Block kommt in den aktuellen Text."""
    d = temp_vault()
    try:
        import stand as st
        importlib.reload(st)
        p = d / "entities" / "projects" / "p.md"
        p.write_text("---\ntype: project\ntitle: P\nstatus: active\n---\n# P\n\n## Offene Punkte\n- [ ] Rampe pruefen\n\n"
                     "## Event Log\n- [2026-09-14] [RISK] Freigaberunde blockiert Rollout\n", encoding="utf-8", newline="\n")

        def hakt_ab(messages, schema, **kw):
            p.write_text(p.read_text(encoding="utf-8").replace("- [ ] Rampe pruefen", "- [x] Rampe pruefen ✅ 2026-09-27"),
                         encoding="utf-8", newline="\n")
            return {"stand": "Die Freigaberunde blockiert den Rollout weiterhin, eine Loesung ist noch nicht in "
                             "Sicht (Stand 2026-09-14).", "fremde_eintraege": []}, []

        st.run(llm_call=hakt_ab, today=date(2026, 9, 27))
        text = p.read_text(encoding="utf-8")
        ok("- [x] Rampe pruefen ✅ 2026-09-27" in text and st.MARK_START in text
           and "Die Freigaberunde blockiert den Rollout" in text, text)
    finally:
        restore_vault()


def t_calendar_url_from_keychain_env_before_file():
    """Die Kalender-Adresse kommt aus dem Obsidian-Schluesselbund: das Plugin reicht sie als
    VAULT_CALENDAR_URL herein. Die Datei bleibt Rueckfall (Aufrufe ohne Plugin); die Adresse
    erscheint nie in `pfade`."""
    import kalender as ec
    import einrichten
    alt = os.environ.pop("VAULT_CALENDAR_URL", None)
    try:
        os.environ["VAULT_CALENDAR_URL"] = "https://kalender.example.com/geheim.ics"
        eq(ec.load_calendar_config(), {"ical_url": "https://kalender.example.com/geheim.ics"})
        p = einrichten.paths()
        eq((p["kalender"], p["kalender_quelle"]), (True, "schluesselbund"))
        ok("geheim" not in json.dumps(p), "Adresse in den Pfaden")
    finally:
        os.environ.pop("VAULT_CALENDAR_URL", None)
        if alt is not None:
            os.environ["VAULT_CALENDAR_URL"] = alt


def t_active_meetings_flat_new_notes():
    """Die Vorbereitung legt neue Termin-Notizen direkt in active-meetings/ an, ohne Unterordner
    fuer Jahr und Monat."""
    d = temp_vault()
    try:
        import vorbereiten
        eq(vorbereiten.target_path({"date": "2026-10-01", "title": "Weekly Demo", "type": "weekly"}),
           d / "active-meetings" / "2026-10-01 - weekly - Weekly Demo.md", "neue Notiz:")
    finally:
        restore_vault()


def t_next_claims_and_emits_packet():
    """next_packet setzt die Notiz auf in_progress und liefert ein kompaktes Paket mit Wikilinks und
    Projekt-Pfeilen - ohne die volle Alias-Map, die den Kontext verschmutzt."""
    d = temp_vault()
    try:
        import vault_paths as vp
        _note(d, "2026-01-05-jourfix.md",
              ["type: meeting", "title: Jourfix", "date: 2026-01-05"],
              "# Jourfix\n\n## Notizen\nWir sprachen ueber [[Agent Platform]].\n"
              "→ Projekt: Middleware\n")
        rc, pkt, err = _next()
        eq(rc, 0, f"Exit 0 erwartet (stderr: {err[:200]})")
        eq(pkt["kind"], "packet", "kein Paket")
        eq(pkt["needs_semantic_extraction"], True, "unstrukturiert erwartet")
        ok("Agent Platform" in pkt["all_wikilinks"], "Wikilink fehlt")
        ok("Middleware" in pkt["project_arrows"], "Arrow fehlt")
        ok("known_aliases" not in pkt, "volle Alias-Map im Paket (Kontext-Verschmutzung)")
        fm = vp.read_frontmatter(d / "inbox" / "2026-01-05-jourfix.md")
        eq(fm.get("status"), "in_progress", "nicht geclaimt")
    finally:
        restore_vault()


def t_next_reoffers_in_progress_with_resumed_flag():
    """Geclaimt wird nur der chronologische Kopf - eine haengende in_progress-Datei ist also der
    Kopf und kommt mit resumed: true zurueck."""
    d = temp_vault()
    try:
        _note(d, "2026-01-01-haengt.md",
              ["type: meeting", "date: 2026-01-01", "status: in_progress", "processed: false"],
              "# B\nText\n")
        _note(d, "2026-02-01-neu.md", ["type: meeting", "date: 2026-02-01"], "# A\nText\n")
        rc, pkt, err = _next()
        eq(rc, 0, f"Exit 0 erwartet ({err[:120]})")
        eq(pkt["file"], "2026-01-01-haengt.md", "Kopf muss zuerst kommen")
        eq(pkt["resumed"], True, "resumed-Flag fehlt")
    finally:
        restore_vault()


def t_next_skips_deferred_and_cockpit_prefixes():
    """Zurueckgelegte (deferred) Notizen und Cockpit-Dateien (auch mit Praefix wie 07_) sind kein
    Eingang; zurueckgelegte werden gezaehlt."""
    d = temp_vault()
    try:
        (d / "07_Glossar.md").write_text("---\nprocessed: false\n---\nCockpit\n",
                                         encoding="utf-8", newline="\n")
        _note(d, "2026-01-01-gift.md",
              ["type: meeting", "date: 2026-01-01", "deferred: true"], "# G\n")
        rc, out, err = _next()
        eq(rc, 1, "Eingang muss als leer gelten")
        eq(out["kind"], "empty", "kind empty erwartet")
        eq(out["stats"]["deferred"], 1, "deferred nicht gezaehlt")
    finally:
        restore_vault()


def t_next_auto_completes_structured_file():
    """Eine strukturierte Notiz mit Zielprojekt wird ohne Modell angewendet, abgeschlossen
    (status: done, processed: true) und ins Monats-Archiv verschoben."""
    d = temp_vault()
    try:
        import vault_paths as vp
        vp.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        (vp.PROJECTS_DIR / "test-proj.md").write_text(
            "---\ntype: project\nname: Test\nstatus: active\n---\n# Test\n\n## Event Log\n",
            encoding="utf-8", newline="\n")
        _note(d, "2026-01-10-board.md",
              ["type: meeting", "date: 2026-01-10", "themen: [test-proj]"],
              "# Board\n\n## Entscheidungen\n- REST statt gRPC\n")
        rc, out, err = _next()
        eq(rc, 0, f"Exit 0 erwartet ({err[:200]})")
        eq(len(out.get("auto_completed", [])), 1, "auto_completed fehlt")
        dest = d / "archive" / "meetings" / "2026-01" / "2026-01-10-board.md"
        ok(dest.is_file(), "Datei nicht archiviert")
        fm = vp.read_frontmatter(dest)
        eq(fm.get("status"), "done", "status nicht kanonisch")
        eq(fm.get("processed"), True, "processed nicht gesetzt")
        proj = (vp.PROJECTS_DIR / "test-proj.md").read_text(encoding="utf-8")
        ok("[DECISION] REST statt gRPC" in proj, "Event nicht angewendet")
    finally:
        restore_vault()


def t_next_structured_file_actions_become_open_points():
    """Aufgaben einer strukturierten Eingangs-Notiz werden ohne Modell Offene Punkte im Thema -
    keine Zeile im Log, keine Dublette."""
    d = temp_vault()
    try:
        import vault_paths as vp
        (vp.PROJECTS_DIR / "test-proj.md").write_text(
            "---\ntype: project\nname: Test\nstatus: active\n---\n# Test\n\n## Event Log\n",
            encoding="utf-8", newline="\n")
        _note(d, "2026-01-12-board.md",
              ["type: meeting", "date: 2026-01-12", "themen: [test-proj]"],
              "# Board\n\n## Entscheidungen\n- REST statt gRPC\n\n"
              "## Aufgaben\n- [ ] Angebot pruefen\n")
        rc, out, err = _next()
        eq(rc, 0, f"Exit 0 erwartet ({err[:300]})")
        proj = (vp.PROJECTS_DIR / "test-proj.md").read_text(encoding="utf-8")
        ok("[ACTION]" not in proj, f"Aufgabe landete im Log:\n{proj}")
        eq(proj.count("Angebot pruefen"), 1, "Punkt fehlt oder doppelt:")
        ok("## Offene Punkte\n- [ ] Angebot pruefen ➕ 2026-01-12" in proj, f"Format:\n{proj}")
    finally:
        restore_vault()


def t_next_blocks_on_eml_with_exit_4():
    """Liegt eine .eml im Eingang, liefert next kein Paket, sondern Exit 4 (needs_ingest) mit der
    Datei - erst einlesen, dann einarbeiten."""
    d = temp_vault()
    try:
        (d / "inbox").mkdir(exist_ok=True)
        (d / "inbox" / "mail.eml").write_text("From: a@b\n\nHi", encoding="utf-8", newline="\n")
        rc, out, err = _next()
        eq(rc, 4, "Exit 4 erwartet")
        eq(out["kind"], "needs_ingest", "kind needs_ingest erwartet")
        ok("mail.eml" in out["pending_non_md"], "eml nicht gelistet")
    finally:
        restore_vault()


def t_mark_done_writes_canonical_vocab_and_moves():
    """mark_done schreibt das kanonische Vokabular (status: done, entities_updated, processed_at)
    und verschiebt die Notiz ins Monats-Archiv."""
    d = temp_vault()
    try:
        import vault_paths as vp
        f = _note(d, "2026-03-01-x.md", ["type: meeting", "date: 2026-03-01"], "# X\n")
        rc, out, err = _mark("mark_done", str(f), notes="test", updated=["a", "b"])
        eq(rc, 0, f"Exit 0 erwartet ({err[:120]})")
        dest = d / "archive" / "meetings" / "2026-03" / "2026-03-01-x.md"
        ok(dest.is_file() and not f.exists(), "Move fehlt")
        fm = vp.read_frontmatter(dest)
        eq(fm.get("status"), "done", "Vokabular nicht kanonisch")
        eq(fm.get("entities_updated"), ["a", "b"], "updated-Liste falsch")
        ok(fm.get("processed_at"), "processed_at fehlt")
    finally:
        restore_vault()


def t_mark_done_overwrites_twin_and_logs():
    """Die Eingangs-Kopie gilt: ihr Zwilling im Archiv wird ueberschrieben (Meldung [OVERWROTE])."""
    d = temp_vault()
    try:
        f = _note(d, "2026-03-02-y.md", ["type: meeting", "date: 2026-03-02"], "# NEU\n")
        dest = d / "archive" / "meetings" / "2026-03" / "2026-03-02-y.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("# ALT\n", encoding="utf-8", newline="\n")
        rc, out, err = _mark("mark_done", str(f))
        eq(rc, 0, "Exit 0 erwartet")
        eq(out["overwrote"], True, "overwrote-Flag fehlt")
        ok("OVERWROTE" in err, "[OVERWROTE] nicht gemeldet")
        ok("# NEU" in dest.read_text(encoding="utf-8"), "Root-Kopie hat nicht gewonnen")
    finally:
        restore_vault()


def t_mark_reset_and_defer():
    """mark_reset setzt eine haengende Notiz zurueck (status: open, processed_at weg); mark_defer
    legt sie zurueck (deferred: true), danach bietet next sie nicht mehr an."""
    d = temp_vault()
    try:
        import vault_paths as vp
        f = _note(d, "2026-03-03-z.md",
                  ["type: meeting", "date: 2026-03-03", "status: in_progress",
                   "processed_at: gestern"], "# Z\n")
        rc, out, err = _mark("mark_reset", str(f))
        eq(rc, 0, "reset Exit 0")
        fm = vp.read_frontmatter(f)
        eq(fm.get("status"), "open", "reset: status nicht open")
        ok("processed_at" not in fm, "reset: processed_at nicht entfernt")
        rc, out, err = _mark("mark_defer", str(f), "kaputt")
        eq(rc, 0, "defer Exit 0")
        fm = vp.read_frontmatter(f)
        eq(fm.get("deferred"), True, "defer: Flag fehlt")
        rc, out, err = _next()
        eq(rc, 1, "deferred Datei darf nicht angeboten werden")
    finally:
        restore_vault()


def t_next_bundles_mail_with_attachment_and_mark_closes_both():
    """Mail + kleiner Anhang = ein Paket; mark done auf der Mail schliesst beide."""
    d = temp_vault()
    try:
        import vault_paths as vp
        mail = _mail_note(d, "2026-09-15-zebra-angebot")
        # Anhang sortiert VOR der Mail - darf trotzdem nicht allein kommen
        att = _attachment_note(d, "2026-09-15-angebot-app.md", "2026-09-15-zebra-angebot",
                               "Angebot Zelmar: Migration App-User, 12 PT.")
        rc, pkt, err = _next()
        eq(rc, 0, f"Exit 0 erwartet ({err[:200]})")
        eq(pkt["file"], mail.name, "Mail muss das Paket fuehren")
        eq([a["file"] for a in pkt["attachments"]], [att.name], "Anhang nicht gebuendelt")
        ok("12 PT" in pkt["attachments"][0]["text"], "Anhangtext fehlt")
        eq(vp.read_frontmatter(att).get("bundled_into"), mail.stem, "Anhang nicht geclaimt")
        rc, out, err = _mark("mark_done", str(mail), notes="x")
        eq(rc, 0, f"mark done ({err[:200]})")
        eq(len(out.get("bundled", [])), 1, "Anhang nicht mit abgeschlossen")
        dest = d / "archive" / "meetings" / "2026-09" / att.name
        ok(dest.is_file() and not att.exists(), "Anhang nicht archiviert")
        fm = vp.read_frontmatter(dest)
        ok(fm.get("processed") is True and "bundled_into" not in fm, "Anhang-Frontmatter falsch")
        rc, out, err = _next()
        eq(rc, 1, "Eingang muss leer sein")
    finally:
        restore_vault()


def t_next_large_attachment_gets_own_packet_with_parent_context():
    """Anhang ueber dem Budget: eigenes Paket, aber mit Betreff/Anfang der Mail."""
    d = temp_vault()
    try:
        mail = _mail_note(d, "2026-09-15-zebra-angebot")
        big = _attachment_note(d, "2026-09-15-z-angebot-fahrzeug.md", "2026-09-15-zebra-angebot",
                               "Leistungsbeschreibung. " * 400)
        rc, pkt, err = _next(attach_chars=2000)
        eq(pkt["attachments"], [], "zu grosser Anhang wurde gebuendelt")
        eq(pkt["attachments_followup"], [big.name], "Folgepaket nicht angekuendigt")
        _mark("mark_done", str(mail), notes="x")
        rc, pkt, err = _next(attach_chars=2000)
        eq(pkt["file"], big.name, "Anhang muss jetzt einzeln kommen")
        ctx = pkt["parent_context"] or {}
        eq(ctx.get("title"), "2026-09-15-zebra-angebot", "Mail-Kontext fehlt")
        ok("08.10." in ctx.get("excerpt", ""), "Mail-Anfang fehlt im Kontext")
    finally:
        restore_vault()


def t_strip_mail_noise_removes_boilerplate_only():
    """Mail-Rauschen (Safelinks, cid-Bilder, mailto, Rechtshinweis, Leerzeilen-Serien) faellt aus
    dem Paket, der Inhalt bleibt."""
    import arbeitspaket as wp
    raw = ("Hallo,\nbitte pruefen <https://eur03.safelinks.protection.outlook.com/?url=x&data=1>\n"
           "[cid:image001.png@01DC]\n"
           "Wir arbeiten ausschließlich auf Grundlage der Allgemeinen Deutschen Spediteurbedingungen 2017\n"
           "\n\n\nGruss Merten <mailto:b@example.com>\n")
    out = wp.strip_mail_noise(raw)
    ok("safelinks" not in out and "cid:" not in out and "mailto" not in out, f"Rauschen blieb: {out}")
    ok("Spediteurbedingungen" not in out, "Rechtshinweis blieb")
    ok("bitte pruefen" in out and "Gruss Merten" in out, "Inhalt verloren")
    ok("\n\n\n" not in out, "Leerzeilen nicht zusammengefasst")


def t_packet_whitelist_only_named_people():
    """Das Paket nennt nur Personen, deren voller Name im Text steht (Umlaut/Akzent egal) oder die
    als Kandidat vorgeschlagen sind - alle Personen-Slugs sprengen den Kontext; ein Vorname allein
    zaehlt nicht."""
    import arbeitspaket as wp
    slugs = ["carlo-kessler", "carlo", "ivo-moeller", "timo-kranich"]
    amap = {"carlo kessler": "carlo-kessler", "ivo möller": "ivo-moeller",
            "carlo": "carlo", "tímo kranich": "timo-kranich"}
    text = "Carlo klaert mit Ivo Möller und Timo Kranich den Termin."
    eq(wp.filter_entity_slugs(slugs, amap, text, [], 2), ["ivo-moeller", "timo-kranich"],
       "nur volle Namen (Umlaut/Akzent egal)")
    cands = [{"term": "Carlo", "candidates": [{"slug": "carlo-kessler"}]}]
    eq(wp.filter_entity_slugs(slugs, amap, text, cands, 2),
       ["carlo-kessler", "ivo-moeller", "timo-kranich"], "Kandidaten bleiben in der Liste")


def t_einarbeiten_probelauf_run_and_undo():
    """Eingang einarbeiten mit dem Modell (hier ein Ersatz): der Probelauf schreibt nichts; das
    Einarbeiten schreibt Log-Eintrag, Aufgabe, neue Person, Personen-Fakt, Rueckfrage und legt die
    Mail ins Archiv; Rueckgaengig stellt alles wieder her. Ohne Modell bleibt die Notiz offen."""
    d = temp_vault()
    try:
        import hashlib as _h
        import vault_paths as vp
        import anlegen
        import thema_anlegen
        import mails as ie
        import einarbeiten as ea
        import modell
        for m in (anlegen, thema_anlegen, ea):
            importlib.reload(m)
        thema_anlegen.create("Portal", ["portal"])
        anlegen.create("people", "Anna Berg")
        (d / "inbox").mkdir(exist_ok=True)
        h = {"subject": "Portal Go-Live", "from": "Anna Berg <anna@example.com>", "to": "m@example.com",
             "date": "Tue, 22 Sep 2026 10:00:00 +0000", "message_id": "<golive@example.com>"}
        stem = ie.note_stem(h, [d / "inbox"])
        _, md = ie.generate_vault_note(h, "Wir gehen im Oktober mit dem Portal live. Anna schickt den "
                                          "Testplan bis 5.10. Gernot Meier hilft beim Test.", ["Anna Berg"], [], stem=stem)
        note = d / "inbox" / f"{stem}.md"
        note.write_text(md, encoding="utf-8", newline="\n")
        antwort = {"project_updates": [{"slug": "portal", "health": "",
                                        "events": ["[DECISION] Go-Live im Oktober", "ohne Praefix fliegt raus",
                                                   "[STATUS] Gernot Meier unterstützt den Test"]}],
                   "action_items": [{"owner": "anna-berg", "project": "portal", "task": "Testplan schicken",
                                     "deadline": "2026-10-05"}],
                   "new_entities": [{"category": "people", "slug": "gernot-meier", "name": "Gernot Meier"},
                                    {"category": "people", "slug": "carla-kopie", "name": "Carla Kopie"}],
                   "person_facts": [{"person": "anna-berg", "kind": "role", "fact": "Testmanagerin im Portal"}],
                   "offen": ["Unklar, ob das Thema Rechnung mitgemeint ist"], "notes": "Go-Live und Testplan"}
        gesehen = []

        def fake_modell(messages, schema, **kw):
            gesehen.append(messages[1]["content"])
            return json.loads(json.dumps(antwort)), []

        def stand():
            return {p.relative_to(d).as_posix(): _h.sha1(p.read_bytes()).hexdigest()
                    for p in d.rglob("*") if p.is_file() and not p.relative_to(d).as_posix().startswith((".2ndbrain", "reports"))}

        vorher = stand()
        r = ea.probelauf(llm_call=fake_modell)
        eq(stand(), vorher, "Probelauf hat geschrieben:")
        bericht = (d / r["bericht"]).read_text(encoding="utf-8")
        for teil in ("[DECISION] Go-Live im Oktober", "Testplan schicken", "Gernot Meier", "Rückfragen",
                     "Testmanagerin"):
            ok(teil in bericht, f"Bericht ohne {teil}: {bericht}")
        ok("Portal" in gesehen[0] and '"portal"' in gesehen[0], "Paket ohne Themen-Liste")

        thema = d / "entities" / "projects" / "portal.md"
        anna = d / "entities" / "people" / "anna-berg.md"
        thema_vorher, anna_vorher = thema.read_text(encoding="utf-8"), anna.read_text(encoding="utf-8")
        r = ea.run(llm_call=fake_modell)
        eq((len(r["eingearbeitet"]), r["fehler"]), (1, []), "Lauf:")
        t = thema.read_text(encoding="utf-8")
        ok("[DECISION] Go-Live im Oktober" in t and "ohne Praefix" not in t and f"[[{stem}]]" in t, t)
        ok("Testplan schicken" in t and "2026-10-05" in t, "Aufgabe fehlt im Thema")
        ok((d / "entities" / "people" / "gernot-meier.md").is_file(), "neue Person fehlt")
        ok(not (d / "entities" / "people" / "carla-kopie.md").exists(), "Person nur in Kopie angelegt")
        ok("Testmanagerin im Portal" in anna.read_text(encoding="utf-8"), "Personen-Fakt fehlt")
        ok("Rechnung mitgemeint" in (d / "04_Clarifications.md").read_text(encoding="utf-8"), "Rueckfrage fehlt")
        ok(not note.exists() and (d / r["eingearbeitet"][0]["archiv"]).is_file(), "nicht archiviert")

        # ein zweites Paket schreibt spaeter in dasselbe Thema - Rueckgaengig des ersten laesst es stehen
        spaeter = "- [2026-09-23] [STATUS] Spaeterer Eintrag aus einer anderen Mail (→ [[andere]])"
        t2 = thema.read_text(encoding="utf-8").replace("## Offene Punkte", spaeter + "\n\n## Offene Punkte", 1) \
            if "## Offene Punkte" in t else thema.read_text(encoding="utf-8") + "\n" + spaeter + "\n"
        thema.write_text(t2, encoding="utf-8", newline="\n")
        u = ea.undo(stem)
        ok(u["ok"], u)
        ok(spaeter in thema.read_text(encoding="utf-8"), "spaeterer Eintrag mit zurueckgenommen")
        thema.write_text(thema.read_text(encoding="utf-8").replace(spaeter + "\n\n", "", 1).replace("\n" + spaeter + "\n", "", 1),
                         encoding="utf-8", newline="\n")
        eq(thema.read_text(encoding="utf-8"), thema_vorher, "Thema nicht zurueck:")
        eq(anna.read_text(encoding="utf-8"), anna_vorher, "Person nicht zurueck:")
        ok(not (d / "entities" / "people" / "gernot-meier.md").exists(), "neue Person noch da")
        fm = vp.read_frontmatter(note)
        eq((fm.get("status"), fm.get("processed")), ("open", False), "Notiz nicht wieder offen:")

        def weg(messages, schema, **kw):
            raise modell.LLMUnavailableError("Server aus")
        r = ea.run(llm_call=weg)
        eq((r["eingearbeitet"], r["wartet"]), ([], "Server aus"), "ohne Modell:")
        fm = vp.read_frontmatter(note)
        ok(note.is_file() and fm.get("status") == "open" and not fm.get("deferred"), fm)
    finally:
        restore_vault()


def t_mail_thread_is_one_packet_newest_mail_wins():
    """Antworten eines Mail-Verlaufs zitieren einander - einzeln verarbeitet kaeme derselbe Inhalt
    mehrfach, jeweils anders formuliert, ins Themen-Log. Deshalb ist die neueste Mail das Paket; die
    aelteren (samt Anhaengen) werden mitgebuendelt und mit ihr abgeschlossen."""
    d = temp_vault()
    try:
        from email.message import EmailMessage
        import arbeitspaket as wp
        import eingang_abschluss as mm
        import mails as ie
        for m in (wp, mm):
            importlib.reload(m)
        (d / "inbox").mkdir(exist_ok=True)
        for i, zeit in enumerate(("12:16:53", "12:33:40", "12:37:58")):
            msg = EmailMessage()
            msg["From"] = "Merten <b@example.com>"
            msg["To"] = "Daniel <m@example.com>"
            msg["Subject"] = ("AW: " if i != 1 else "RE: ") + "Server gesperrt"
            msg["Date"] = f"Tue, 22 Sep 2026 {zeit} +0000"
            msg["Message-ID"] = f"<v-{i}@example.com>"
            msg.set_content(f"Antwort {i}")
            eml = d / "inbox" / f"v{i}.eml"
            eml.write_bytes(msg.as_bytes())
            ie.process_eml(str(eml), str(d / "inbox"), keep_source=True)
            eml.unlink()
        alt = d / "inbox" / "2026-09-22-server-gesperrt.md"
        anhang = d / "inbox" / "2026-09-22-log.md"
        anhang.write_text("---\ntype: meeting\ncontainer_type: email\nparent: \"[[2026-09-22-server-gesperrt]]\"\n"
                          "source_member: log.txt\n---\n# Log\n\n## Dokumenten-Inhalt\nFehler 4551\n",
                          encoding="utf-8", newline="\n")
        pkt, rc = wp.next_packet()
        eq((rc, pkt["kind"], pkt["file"]), (0, "packet", "2026-09-22-server-gesperrt-1237.md"), "Paket:")
        eq(sorted(pkt["thread"]), ["2026-09-22-server-gesperrt-1233.md", "2026-09-22-server-gesperrt.md"], "Verlauf:")
        ok(any("Fehler 4551" in a["text"] for a in pkt["attachments"]), "Anhang der aelteren Mail fehlt")
        with contextlib.redirect_stdout(io.StringIO()):
            res = mm.done(pkt["path"], notes="test")
        eq(len(res.get("bundled") or []), 3, f"nicht alles abgeschlossen: {res}")
        eq(sorted(f.name for f in (d / "inbox").glob("*.md")), [], "Eingang nicht leer:")
        eq(wp.next_packet()[0]["kind"], "empty", "zweites Paket:")
        ok(not alt.exists() and not anhang.exists(), "aeltere Mail/Anhang noch im Eingang")
    finally:
        restore_vault()


def t_einarbeiten_rules_checked_in_code():
    """Regeln, die das Modell nicht verlaesslich einhaelt, prueft der Code: hoechstens 5 Ereignisse
    je Thema, jede Zusage einmal (nicht je Person), keine Aufgabe mit Frist vor der Quelle, keine
    Firma in zwei Schreibweisen, nicht anlegen und zugleich nachfragen, Personen-Fakten ohne
    Termine; bei einer Rundmail nur Themen des Absenders oder ausdruecklich genannte."""
    import einarbeiten as ea
    p = {"project_updates": [{"slug": "t", "events": ["[STATUS] a", "[STATUS] a", "ohne Praefix", "[RISK] c",
                                                     "[STATUS] d", "[STATUS] e", "[STATUS] f", "[STATUS] g"]}],
         "action_items": [{"owner": "x", "project": "t", "task": "Klären!", "deadline": "2026-09-25"},
                          {"owner": "y", "project": "t", "task": "klären", "deadline": "2026-09-25"},
                          {"owner": "z", "project": "t", "task": "Alt", "deadline": "2026-09-01"}],
         "new_entities": [{"category": "companies", "slug": "nordwind", "name": "Nordwind"},
                          {"category": "companies", "slug": "nordwind-logistik", "name": "Nordwind Logistik"},
                          {"category": "people", "slug": "kai-x", "name": "Kai X"}],
         "person_facts": [{"person": "d", "kind": "contact", "fact": "Noch zu prüfen, Daniel, 7.9."},
                          {"person": "e", "kind": "role", "fact": "Head of IT"}],
         "offen": ["Ist Kai X gemeint?"], "notes": "n"}
    c = ea._clean(p, "2026-09-21")
    eq(c["project_updates"][0]["events"], ["[STATUS] a", "[RISK] c", "[STATUS] d", "[STATUS] e", "[STATUS] f"])
    eq([(a["owner"], a["task"]) for a in c["action_items"]], [("x", "Klären!")])
    eq([e["name"] for e in c["new_entities"]], ["Nordwind Logistik"])
    eq([f["fact"] for f in c["person_facts"]], ["Head of IT"])
    # Rundmail: ein Thema nur, wenn es zum Absender gehoert oder ausdruecklich genannt ist
    pkt = {"rundmail": True, "absender": {"name": "S", "slug": "s", "themen": ["lizenzen"]},
           "relevant_aliases": {}, "projekte": [], "all_wikilinks": [], "project_arrows": []}
    q = ea._clean({"project_updates": [{"slug": "kundenerlebnis", "events": ["[STATUS] Dashboard verfuegbar"]},
                                       {"slug": "lizenzen", "events": ["[STATUS] Neue Liste"]}],
                   "action_items": [], "new_entities": [], "person_facts": [], "offen": [], "notes": ""})
    r = ea._pruefe_themen(q, pkt)
    eq([u["slug"] for u in r["project_updates"]], ["lizenzen"], "Rundmail:")
    ok(r["hinweise"] and "kundenerlebnis" in r["hinweise"][0], r["hinweise"])
    eq(ea._pruefe_themen(ea._clean({"project_updates": [{"slug": "x", "events": ["[STATUS] y"]}]}),
                         {"rundmail": False})["project_updates"][0]["slug"], "x", "keine Rundmail:")


def t_glossar_new_terms_only_relevant_and_not_asked_twice():
    """Neue haeufige Begriffe: das Modell ordnet ein, bevor eine Seite entsteht - Rauschen wird
    keine Seite. Was eingeordnet ist, fragt es erst wieder, wenn sich die Fundstellen aendern. Ohne
    Modell entsteht nichts Neues."""
    d = temp_vault()
    try:
        import glossar as g
        importlib.reload(g)
        src = d / "archive" / "meetings" / "2026-09"
        src.mkdir(parents=True)
        for i in range(12):
            (src / f"2026-09-{10 + i:02d}-m.md").write_text(
                f"Die **Frachtboerse** vermittelt Ladungen. Der **Kaffeeautomat** ist kaputt, Runde {i}.\n",
                encoding="utf-8", newline="\n")
        gefragt = []

        def fake_modell(messages, schema, **kw):
            text = messages[1]["content"]
            gefragt.append(text)
            return {"begriffe": [
                {"begriff": "frachtboerse", "art": "fachbegriff", "langform": "",
                 "definition": "Plattform, die Ladungen vermittelt."},
                {"begriff": "kaffeeautomat", "art": "rauschen", "langform": "", "definition": ""}]}, []

        eq(g.run(apply=True, llm_call=None).get("wartet_auf_modell"), 2, "ohne Modell:")
        ok(not list((d / "entities" / "glossary").glob("*.md")), "ohne Modell angelegt")
        r = g.run(apply=True, llm_call=fake_modell)
        eq((r.get("vorschlag_created"), r.get("nicht_angelegt")), (1, 1), f"Lauf: {r}")
        fb = (d / "entities" / "glossary" / "frachtboerse.md").read_text(encoding="utf-8")
        ok("Plattform, die Ladungen vermittelt." in fb and "occurrences: 12" in fb and "status: candidate" in fb, fb)
        ok(not (d / "entities" / "glossary" / "kaffeeautomat.md").exists(), "Rauschen angelegt")
        n = len(gefragt)
        r = g.run(apply=True, llm_call=fake_modell)
        eq((len(gefragt), r.get("wartet_auf_modell")), (n, 0), "zweiter Lauf fragt erneut:")
    finally:
        restore_vault()


def t_wissen_runs_only_when_sources_changed():
    """Begriffs-Index, Kontext-Verzeichnis und Glossar laufen in der Automatik von selbst, aber nur,
    wenn sich ihre Quellen geaendert haben - sonst kostet der Schritt nichts."""
    d = temp_vault()
    try:
        import wissen
        import begriffsindex as ti
        for m in (wissen, ti):
            importlib.reload(m)
        r1 = wissen.aktualisieren(llm_ok=False)
        ok(ti.INDEX_FILE.is_file() and any("Begriffs-Index" in x for x in r1["detail"]), r1)
        r2 = wissen.aktualisieren(llm_ok=False)
        eq(r2["detail"], ["nichts zu tun"], "zweiter Lauf ohne Aenderung:")
        (d / "entities" / "projects" / "neu.md").write_text("---\ntype: project\ntitle: Neu\n---\n# Neu\n",
                                                          encoding="utf-8", newline="\n")
        import os as _os, time as _time
        _os.utime(d / "entities" / "projects" / "neu.md", (_time.time() + 5, _time.time() + 5))
        r3 = wissen.aktualisieren(llm_ok=False)
        ok(any("Begriffs-Index" in x for x in r3["detail"]), r3)
    finally:
        restore_vault()


def t_glossar_counts_only_content():
    """Gezaehlt wird nur Inhalt: keine Kalender-Exporte (iCal-UID), keine fetten Beschriftungen
    ("**Playbook:**"), keine Link-Ziele ("[[… - checkin - Reihe]]"), keine Ueberschriften, die die
    Engine selbst schreibt ("## Offene Punkte"), keine Termintitel - sonst werden genau diese zu
    Glossar-Eintraegen. Eine vorhandene Seite bekommt die neue Zahl."""
    d = temp_vault()
    try:
        import glossar as g
        importlib.reload(g)
        (d / "archive" / "calendar").mkdir(parents=True)
        (d / "archive" / "calendar" / "kalender.md").write_text("UID UID UID UID UID UID UID UID UID UID UID\n",
                                                               encoding="utf-8", newline="\n")
        m = d / "archive" / "meetings" / "2026-09"
        m.mkdir(parents=True)
        for i in range(12):
            (m / f"2026-09-{10 + i:02d}-n.md").write_text(
                "## Offene Punkte\n**Playbook:** checkin\nVorher: [[2026-08-31 - checkin - Reihe Nord Checkin]]\n"
                "Die **Frachtboerse** vermittelt Ladungen.\n" + ("Das **Nordlicht** leuchtet.\n" if i < 3 else ""),
                encoding="utf-8", newline="\n")
        idx = g.scan()
        kept, reasons = g.filter_candidates(idx["terms"], 10)
        ok("uid" not in idx["terms"] and "playbook" not in idx["terms"], sorted(idx["terms"])[:20])
        ok("reihe nord checkin" not in idx["terms"], "Link-Ziel gezaehlt")
        ok("frachtboerse" in kept and "offene punkte" not in kept, (sorted(kept), reasons))
        # Eine vorhandene Seite bekommt die neue Zahl, auch unter der Mindestzahl
        gl = d / "entities" / "glossary"
        gl.mkdir(parents=True, exist_ok=True)
        (gl / "nordlicht.md").write_text("---\ntype: glossary_term\nterm: Nordlicht\nslug: nordlicht\n"
                                         "status: candidate\noccurrences: 50\n---\n# Nordlicht\n",
                                         encoding="utf-8", newline="\n")
        g.run(apply=True, llm_call=None)
        eq(g.vp.read_frontmatter(gl / "nordlicht.md").get("occurrences"), 3, "Messwert Nordlicht:")
    finally:
        restore_vault()
    # Nur Inhalt: Vorlage der Vorbereitung, Diagramme, Log-Markierungen, Stand-Block fallen weg -
    # die Mail im schlichten Zaun (fremdtext.zaun) bleibt
    body = ("## Vorbereitung\n| Bis nächstes Mal | Konkrete Zusagen |\n\n## Meine Notizen\nDie **Frachtboerse** läuft.\n"
            "```mermaid\nflowchart LR\n```\n- [2026-09-01] [RISK] Lager voll\n<!-- stand-auto:start -->\nAufgaben-Zeilen\n"
            "<!-- stand-auto:end -->\n```\nMail: SECTEAM liefert.\n```\n")
    rein = g.inhalt(body)
    ok("Frachtboerse" in rein and "SECTEAM" in rein and "Lager voll" in rein, rein)
    ok(not any(x in rein for x in ("Konkrete Zusagen", "flowchart", "[RISK]", "Aufgaben-Zeilen")), rein)
    # Termintitel aus Typ + Vorname sind kein Begriff (Typ-Erkennung der Termine, Playbooks des Vaults)
    import playbook
    importlib.reload(playbook)
    ok(g.looks_like_meeting_title("weekly otto", {"otto"}), "weekly otto")
    ok(not g.looks_like_meeting_title("weekly report", {"otto"}), "weekly report")
    ok(not g.looks_like_meeting_title("release tag", {"otto"}), "release tag")


def t_health_counts_only_recent_risks():
    """Die Ampel zaehlt nur Risiken der letzten 30 Tage - ein altes [RISK] haelt ein Thema sonst
    fuer immer auf Gelb; ein neuer Eintrag zaehlt wieder. Die Risiken-Liste fuers Plugin zeigt
    dieselben Zeilen mit Aktiv-Flag und Quelle."""
    d = temp_vault()
    try:
        from datetime import date
        import ampel as he
        importlib.reload(he)
        f = d / "entities" / "projects" / "p.md"
        f.write_text("---\ntype: project\nstatus: active\n---\n# P\n\n## Event Log\n"
                     "- [2026-08-01] [RISK] Alt, nie wieder erwaehnt (→ [[q]])\n", encoding="utf-8", newline="\n")
        eq(he.assess(f, today=date(2026, 9, 16))[0], "green", "altes Risiko zaehlt noch")
        eq(he.assess(f, today=date(2026, 8, 20))[0], "yellow", "frisches Risiko zaehlt nicht")
        f.write_text(f.read_text(encoding="utf-8")
                     + "- [2026-09-10] [RISK] Wieder genannt (→ [[q]])\n", encoding="utf-8", newline="\n")
        eq(he.assess(f, today=date(2026, 9, 16))[0], "yellow", "erneute Nennung frischt nicht auf")
        # Risiken-Liste fuers Plugin: dieselben Zeilen, aktiv = im Fenster, Quelle getrennt
        rows = he.risk_rows(date(2026, 9, 16))
        eq([(r["datum"], r["aktiv"], r["art"], r["text"], r["quelle"]) for r in rows],
           [("2026-09-10", True, "Projekt", "Wieder genannt", "q"),
            ("2026-08-01", False, "Projekt", "Alt, nie wieder erwaehnt", "q")], "Risiken-Liste:")
    finally:
        restore_vault()


def t_health_counts_overdue_tasks_vault_wide_with_reasons():
    """Ueberfaellige Punkte zaehlen vault-weit (auch aus Meeting-Notizen), nicht
    nur die der eigenen Datei; assess() begruendet die Ampel."""
    d = temp_vault()
    try:
        from datetime import date
        import ampel as he
        f = d / "entities" / "projects" / "p.md"
        f.write_text("---\ntype: project\nstatus: active\n---\n# P\n\n## Offene Punkte\n"
                     "- [ ] Alt — @x — 2026-09-10\n", encoding="utf-8", newline="\n")
        eq(he.assess(f, today=date(2026, 9, 27)), ("yellow", ["1 überfällige Aufgabe"]))
        m = d / "active-meetings" / "2026" / "09"
        m.mkdir(parents=True)
        (m / "2026-09-20 - checkin - P.md").write_text(
            "---\ntype: meeting\ndate: '2026-09-20'\nthemen: [p]\n---\n## Actions\n"
            "- [ ] Neu — ? 📅 2026-09-25\n- [x] Erledigt — ? 📅 2026-09-01\n", encoding="utf-8", newline="\n")
        import aufgaben as tk
        by_topic = tk.open_by_topic()
        eq(len(by_topic.get("p", [])), 2, "offene Punkte zum Thema:")
        eq(he.assess(f, today=date(2026, 9, 27), open_tasks=by_topic["p"]),
           ("red", ["2 überfällige Aufgaben"]), "Punkt aus Meeting-Notiz zaehlt nicht:")
    finally:
        restore_vault()


def t_people_profile_full_name_only_and_idempotent():
    """Der Personen-Ueberblick fuellt Aufgaben, Themen, Quellen und E-Mail - zugeordnet nur ueber
    den vollen Namen, nie ueber den Vornamen; eigener Inhalt bleibt, zweiter Lauf byte-gleich."""
    d = temp_vault()
    try:
        import importlib
        import vault_paths as vp
        import personen as pp
        importlib.reload(pp)
        (vp.PEOPLE_DIR / "timo-kranich.md").write_text(
            "---\ntype: person\nname: Tímo Kranich\naliases: []\nemail: ''\n---\n# Tímo Kranich\n\n"
            "## Expertise & Verantwortung\n- Eigene Notiz bleibt\n", encoding="utf-8", newline="\n")
        (vp.PEOPLE_DIR / "timo.md").write_text(
            "---\ntype: person\nname: Timo\n---\n# Timo\n", encoding="utf-8", newline="\n")
        (vp.PROJECTS_DIR / "edi.md").write_text(
            "---\ntype: project\ntitle: EDI\n---\n# EDI\n\n## Offene Punkte\n"
            "- [ ] Upgrade planen — [[timo-kranich]] 📅 2026-09-01 ➕ 2026-09-15 (→ [[m1]])\n\n## Event Log\n"
            "- [2026-09-14] [STATUS] Timo Kranich meldet Upgrade on track (→ [[m1]])\n"
            "- [2026-09-13] [STATUS] Timo hat Urlaub (→ [[m1]])\n", encoding="utf-8", newline="\n")
        src = vp.MEETINGS_DIR / "2026-09"
        src.mkdir(parents=True)
        (src / "2026-09-15-mail.md").write_text(
            "---\ntype: email-thread\ntitle: Upgrade\n---\n**Von:** Tímo Kranich <Timo.Kranich@example.com>\n",
            encoding="utf-8", newline="\n")
        (src / "2026-09-10-jourfix.md").write_text(
            "---\ntype: meeting\ntitle: Jourfix | EDI\ndate: 2026-09-10\n---\nTamas war da.\n", encoding="utf-8", newline="\n")
        report = pp.run(today=date(2026, 9, 16))
        full = (vp.PEOPLE_DIR / "timo-kranich.md").read_text(encoding="utf-8")
        ok("Eigene Notiz bleibt" in full, "manueller Inhalt verloren")
        ok("1 als Verantwortliche(r), davon 1 überfällig" in full, "Aufgabe/Frist fehlt")
        ok(pp.TASK_QUERY in full, "Live-Abfrage der offenen Punkte fehlt")
        ok("[[edi|EDI]] (1," in full, f"Projektzaehlung falsch (Vorname zaehlt nicht): {full}")
        ok("1 Mails" in full and "0 Meeting-Notizen" in full, "Quellen falsch gezaehlt (Vorname zaehlt nicht)")
        eq(vp.read_frontmatter(vp.PEOPLE_DIR / "timo-kranich.md").get("email"), "timo.kranich@example.com",
           "E-Mail nicht uebernommen")
        eq(report["without_mention"], ["timo"], "Vornamen-Stub darf nichts zugeordnet bekommen")
        first = full
        pp.run(today=date(2026, 9, 16))
        eq((vp.PEOPLE_DIR / "timo-kranich.md").read_text(encoding="utf-8"), first, "zweiter Lauf nicht idempotent")
        eq(first.count(pp.MARK_START), 1, "Block doppelt eingefuegt")
    finally:
        restore_vault()


def t_sync_person_facts_appends_role_and_dedupes():
    """Personen-Fakten aus dem Sync landen mit Datum und Quelle unter Expertise & Verantwortung,
    eine Rolle auch im Frontmatter; ein Vorname allein wird nicht zugeordnet, ein zweiter Lauf
    verdoppelt nichts."""
    d = temp_vault()
    try:
        import uebernehmen as hs
        import vault_paths as vp
        (vp.PEOPLE_DIR / "hauke-kurz.md").write_text(
            "---\ntype: person\nname: Hauke Kurz\nrole: Unbekannt\n---\n# Hauke Kurz\n\n"
            "## Expertise & Verantwortung\n<!-- Platzhalter -->\n\n## Projekte & Beteiligungen\n-\n",
            encoding="utf-8", newline="\n")
        (vp.PEOPLE_DIR / "hauke.md").write_text("---\ntype: person\nname: Hauke\n---\n# Hauke\n",
                                               encoding="utf-8", newline="\n")
        src = d / "2026-07-17-kickoff1.md"
        src.write_text("---\ndate: 2026-07-17\n---\n# X\n", encoding="utf-8", newline="\n")
        raw = json.dumps({"person_facts": [
            {"person": "Hauke Kurz", "kind": "role", "fact": "Ops Luftfracht"},
            {"person": "Hauke", "kind": "role", "fact": "falsch zugeordnet"}]})
        hs.sync(raw, source_file=str(src))
        text = (vp.PEOPLE_DIR / "hauke-kurz.md").read_text(encoding="utf-8")
        ok("- [2026-07-17] Ops Luftfracht (→ [[2026-07-17-kickoff1]])" in text, f"Fakt fehlt: {text}")
        ok(text.index("Ops Luftfracht") < text.index("## Projekte"), "Fakt im falschen Abschnitt")
        eq(vp.read_frontmatter(vp.PEOPLE_DIR / "hauke-kurz.md").get("role"), "Ops Luftfracht", "Rolle nicht gesetzt")
        ok("falsch zugeordnet" not in (vp.PEOPLE_DIR / "hauke.md").read_text(encoding="utf-8"),
           "Vorname allein wurde zugeordnet")
        hs.sync(raw, source_file=str(src), force=True)
        eq((vp.PEOPLE_DIR / "hauke-kurz.md").read_text(encoding="utf-8").count("Ops Luftfracht ("), 1,
           "Fakt doppelt")
    finally:
        restore_vault()



_ORG_YAML = """
schema: orgchart/1
slides:
  1: {title: Core, stand: 2026-07-29}
  8: {title: Delta, stand: 2025-07-23}
sources:
  m365: {snapshot: 2026-09-16}
units:
- id: bu-delta
  name: BU Delta
  parent: null
  leads:
    - {name: Daniel Mohr, role: VP, slide: 1}
- id: altsys-team
  name: Altsys Team
  parent: bu-delta
  systems: [altsys]
  leads:
    - {name: Carlo Kessler, role: Delta Altsys, slide: 8}
  groups:
    - name: Altsys Development
      slide: 8
      vacancies: 1
      members:
        - {name: Karl Brandt, role: Consultant}
        - {name: Leo Rüdiger, role: Programmer}
        - {name: Anna Beispiel}
        - {name: Mika Thal, source: Klaerung 17.09.2026, stand: 2026-09-17, manager: Daniel Mohr}
people:
  - name: Paul Dorn
    status: left
    former:
      - {unit: altsys-team, role: Programmer GSSC, slide: 8}
  - name: Karl Brandt
    aliases: [Karl Brandte]
  - name: Carlo Kessler
    m365: {title: IT Applications Director, manager: Daniel Mohr, reports: [Karl Brandt]}
"""






def t_validate_drops_first_name_new_person():
    """Eine neue Person nur mit Vornamen wird verworfen (mit Warnung) - sonst entstehen
    Vornamen-Dateien; mit vollem Namen wird sie angelegt."""
    import ausgabe_pruefen
    payload = {"new_entities": [{"category": "people", "name": "Gustav"},
                                {"category": "people", "name": "Gustav Kopp"}]}
    out, warnings, _ = ausgabe_pruefen.validate_and_fix(payload, {"projects": [], "people": []})
    eq([e["slug"] for e in out["entities"]], ["gustav-kopp"], "Vorname allein angelegt")
    ok(any("nur mit Vorname" in w for w in warnings), "keine Warnung")


# ─────────────────────────────────────────── playbook

def t_playbook_schema_valid():
    """Alle sieben Playbooks parsen, Anteile summieren auf 100, Prioritaeten sind eindeutig, keine
    Keyword-Kollision, die neun Pflicht-Abschnitte sind immer im Ergebnis."""
    import playbook
    importlib.reload(playbook)
    files = playbook._playbook_files()
    eq(len(files), 7, "sieben Playbook-Dateien erwartet (sechs Typen + other)")
    required = ("goal", "abgrenzung", "questions", "risks", "framing",
                "checklist", "abbruch", "typischer_fehler", "nachbereitung")
    priorities, all_keywords = [], []
    for f in files:
        typ = f.stem
        entry = playbook.load(typ)
        eq(entry.get("meeting_type"), typ, f"{f.name}: meeting_type != Dateiname")
        eq(entry.get("type"), "meeting-playbook", f"{f.name}: type falsch")
        blocks = entry.get("blocks") or []
        if blocks:
            eq(sum(b.get("anteil", 0) for b in blocks), 100, f"{typ}: Anteile != 100")
        for vname, v in (entry.get("varianten") or {}).items():
            if v.get("blocks"):
                eq(sum(b.get("anteil", 0) for b in v["blocks"]), 100,
                   f"{typ}/{vname}: Varianten-Anteile != 100")
        for key in required:
            ok(key in entry, f"{typ}: Pflicht-Abschnitt {key} fehlt")
        match = entry.get("match") or {}
        priorities.append(match.get("priority"))
        all_keywords.extend(str(k).lower() for k in (match.get("keywords") or []))
    eq(len(priorities), len(set(priorities)), "match.priority nicht eindeutig")
    eq(len(all_keywords), len(set(all_keywords)), "Keyword-Kollision ueber Playbooks hinweg")


def t_playbook_block_keys_exact():
    """Jeder Block hat genau die Schluessel block/anteil/inhalt.

    In einer YAML-Flow-Map `- {block: X, anteil: 10, inhalt: Text mit, Komma}` beendet das Komma
    den Wert: `inhalt` wird zu "Text mit", der Rest landet als Schluessel ohne Wert im selben Dict.
    Beides faellt nicht auf - die Anteilsumme stimmt weiter, die Datei sieht im Editor richtig aus.
    Deshalb prueft der Test die Schluesselmenge, nicht nur die Summe."""
    import playbook
    importlib.reload(playbook)
    expected = {"block", "anteil", "inhalt"}
    for f in playbook._playbook_files():
        entry = playbook.load(f.stem)
        groups = [(f.stem, entry.get("blocks") or [])]
        for vname, v in (entry.get("varianten") or {}).items():
            if v.get("blocks"):
                groups.append((f"{f.stem}/{vname}", v["blocks"]))
        for wo, blocks in groups:
            for b in blocks:
                eq(set(b), expected, f"{wo}: Block hat falsche Schluessel (Flow-Map?)")
                ok(str(b["inhalt"]).strip(), f"{wo}/{b['block']}: inhalt leer")


def t_playbook_keyword_inflection():
    """Flexionsformen treffen ihr Keyword - aber nicht zu viel.

    "… Workshops …" wird `abstimmung`, "Sprint Reviews Q3" wird `review` (nicht ueber `sprint`
    zu `projekt`). Eine falsche Einstufung ist teurer als gar keine, deshalb eine geschlossene
    Endungsliste statt eines Praefix-Matches - sonst wird "Reviewer-Runde" zum Review."""
    import playbook
    importlib.reload(playbook)
    for title, expected in [
        ("Kanon - Workshops und Arbeit", "abstimmung"),
        ("Sprint Reviews Q3", "review"),
        ("Zwei Abstimmungen Portfolio", "abstimmung"),
        ("Meilensteine Q4", "projekt"),
        ("Reviewer-Runde", "other"),          # Praefix-Match waere hier falsch
        ("Abnahmekriterien besprechen", "other"),
    ]:
        eq(playbook.detect(title)[0], expected, f"detect({title!r})")


def t_playbook_variant_line_filter():
    """Ein Playbook beschreibt alle Varianten in einem Body.

    Ohne Filter stehen bei Variante `down` auch die "Nach oben"-Zeilen in der
    Notiz - fuer ein kleines Modell nicht nur Rauschen, sondern eine falsche
    Anweisung. Die Basis-Sicht (ohne Variante) muss dagegen alles zeigen."""
    import playbook
    importlib.reload(playbook)

    down = playbook.view("oneonone", "down")
    up = playbook.view("oneonone", "up")
    basis = playbook.view("oneonone")
    ok(any("wegräumen" in x for x in down["framing"]), "down: eigene Zeile fehlt")
    ok(not any("Ich empfehle A" in x for x in down["framing"]),
       "down: 'Nach oben'-Zeile nicht gefiltert")
    ok(any("Ich empfehle A" in x for x in up["framing"]), "up: eigene Zeile fehlt")
    ok(not any("wegräumen" in x for x in up["framing"]),
       "up: 'Nach unten'-Zeile nicht gefiltert")
    ok(not any(x.startswith("Nach ") for x in down["framing"] + down["checklist"]),
       "Marke wurde nicht abgestreift")
    ok(any("Nach oben" in x for x in basis["framing"]),
       "Basis-Sicht darf nicht filtern")

    # Backtick-Schreibweise: "Variante `quartal`/`jahr`: ..."
    q = playbook.view("steering", "quartal")
    m = playbook.view("steering", "monatlich")
    ok(any("Netto-Kapazität gegengerechnet" in x for x in q["questions"]),
       "quartal: eigene Leitfrage fehlt")
    ok(not any("Netto-Kapazität gegengerechnet" in x for x in m["questions"]),
       "monatlich: Quartals-Leitfrage nicht gefiltert")
    ok(any("Streichliste" in x for x in q["checklist"]), "quartal: Streichliste fehlt")
    ok(not any("Streichliste" in x for x in m["checklist"]),
       "monatlich: Streichliste nicht gefiltert")


def t_playbook_detect_priority_table():
    """Die Reihenfolge nach `match.priority` ist Absicht - 'Roadmap Review' muss
    `steering` werden statt `review`, 'oneonone' steht vor 'checkin'."""
    import playbook
    importlib.reload(playbook)
    cases = [
        ("Jourfix Daniel / Ali", "oneonone", None),
        ("1:1 Kuno", "oneonone", None),
        ("Weekly Delta Portfolio", "checkin", "weekly"),
        ("Monthly Delta Portfolio", "steering", "monatlich"),
        ("Q3 Roadmap Review", "steering", "quartal"),
        ("Sprint Review EDI", "review", None),
        ("Sprint Planning EDI", "projekt", None),
        ("Abstimmung zum Delta Portfolio WS", "abstimmung", None),
        ("Workshop Zielbild Partnerkommunikation", "abstimmung", "erarbeitend"),
        ("Lenkungskreis NoLa", "steering", None),
        ("Kaffee", "other", None),
    ]
    for title, want_type, want_variant in cases:
        typ, variante = playbook.detect(title)
        eq(typ, want_type, f"{title!r}: Typ")
        if want_variant is not None:
            eq(variante, want_variant, f"{title!r}: Variante")


def t_playbook_resolve_direction_from_orgchart():
    """Die Richtung kommt aus dem Organigramm-Block, nie aus einer Namensliste im Code. Ein Name,
    der auf zwei Personen passt, ergibt `peer` - nicht die erstbeste Person."""
    d = temp_vault()
    try:
        import vault_paths as vp
        # wessen Organigramm: "ich" aus der Konfiguration - kein Name als Rueckfall im Code
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps({"ich": "daniel-mohr"}),
                                                        encoding="utf-8", newline="\n")
        (vp.PEOPLE_DIR / "daniel-mohr.md").write_text(
            "---\ntype: person\nname: Daniel Mohr\n---\n"
            "# Daniel Mohr\n\n"
            "<!-- orgchart-auto:start -->\n"
            "- **Berichtet fachlich an (Organigramm):** [[ali-berg-hofmann|Ali Berg-Hofmann]]\n"
            "- **Direct Reports (M365):** [[carlo-kessler|Carlo Kessler]] "
            "· [[kuno-weber-linde|Kuno Weber-Linde]]\n"
            "<!-- orgchart-auto:end -->\n", encoding="utf-8", newline="\n")
        for slug, name in (("ali-berg-hofmann", "Ali Berg-Hofmann"),
                           ("carlo-kessler", "Carlo Kessler"),
                           ("kuno-weber-linde", "Kuno Weber-Linde"),
                           ("anna-eins", "Anna Eins"), ("anna-zwei", "Anna Zwei"),
                           ("peer-person", "Peer Person")):
            (vp.PEOPLE_DIR / f"{slug}.md").write_text(
                f"---\ntype: person\nname: {name}\n---\n# {name}\n", encoding="utf-8", newline="\n")

        import playbook
        importlib.reload(playbook)
        eq(playbook.resolve_direction(None, "1:1 Ali"), "up", "Vorgesetzter nicht erkannt")
        eq(playbook.resolve_direction(None, "1:1 Carlo"), "down", "Direct Report nicht erkannt")
        eq(playbook.resolve_direction(None, "1:1 Peer Person"), "peer", "unbeteiligte Person")
        eq(playbook.resolve_direction(None, "1:1 Anna"), "peer",
           "mehrdeutiger Name darf nicht auf die erstbeste Person raten")
        eq(playbook.resolve_direction(["[[kuno-weber-linde|Kuno Weber-Linde]]"], "1:1"),
           "down", "Teilnehmerliste muss ausgewertet werden")
    finally:
        restore_vault()


def t_no_circular_import_between_playbook_and_agenda():
    """`playbook` importiert `agenda` auf Modulebene, `agenda` importiert
    `playbook` nur lokal in den Funktionen - in beiden Importreihenfolgen
    darf das nicht zu einem Zirkelimport-Fehler fuehren (frischer Prozess,
    damit `sys.modules` nicht schon vorbelegt ist)."""
    for code in ("import agenda, playbook", "import playbook, agenda"):
        cp = _sp.run([sys.executable, "-c", code], cwd=str(_TOOLS),
                     capture_output=True, text=True, timeout=20)
        eq(cp.returncode, 0, f"{code!r} schlug fehl: {cp.stderr[-800:]}")


def t_prep_stub_skeleton_order_and_no_duplicate_on_second_run():
    """Eine neu erzeugte Notiz enthaelt alle Skelett-Abschnitte in der richtigen Reihenfolge und den
    Status 'vorbereitet'; ein zweiter Lauf der Vorbereitung ueber denselben Termin verdoppelt keinen
    Abschnitt (die Datei existiert schon -> `ensure_file` schreibt nichts)."""
    d = temp_vault()
    try:
        import vault_paths as vp
        pb_dir = d / "entities" / "meeting-playbooks"
        pb_dir.mkdir(parents=True, exist_ok=True)
        (pb_dir / "other.md").write_text(
            "---\ntype: meeting-playbook\nmeeting_type: other\nlabel: Sonstiges\n"
            "leitfrage: Warum findet dieser Termin statt?\n"
            "vorbereitung_vorlauf: 1 Tag\nentscheidung_erforderlich: offen\n"
            "kernteil: [Sachstand]\n"
            "blocks:\n- {block: Sachstand, anteil: 100, inhalt: frei}\n"
            "match: {priority: 999, keywords: []}\n"
            "---\n\n# Sonstiges\n## Ziel\nx\n", encoding="utf-8", newline="\n")

        import playbook
        importlib.reload(playbook)
        import vorbereiten
        importlib.reload(vorbereiten)

        ev = {"title": "Kaffee", "date": "2026-09-23", "time": "10:00",
              "series": "kaffee", "type": "other", "participants": []}
        path, action = vorbereiten.ensure_file(ev, None, False, None)
        eq(action, "created")
        text = path.read_text(encoding="utf-8")
        order = ["## Ziel", "## Vorbereitung", "## Agenda", "## Sachstand",
                 "## Meine Notizen", "## Entscheidungen", "## Actions",
                 "## Parkplatz", "## Verweise"]
        for h in order:
            ok(h in text, f"Abschnitt {h} fehlt im Skelett")
        positions = [text.index(h) for h in order]
        eq(positions, sorted(positions), "Skelett-Reihenfolge falsch")
        eq(vp.read_frontmatter(path).get("status"), "vorbereitet", "Status muss 'vorbereitet' sein")

        # Zweiter Lauf ueber denselben Termin (Datei existiert bereits)
        ev2 = dict(ev, path=path)
        path2, action2 = vorbereiten.ensure_file(ev2, None, False, None)
        eq(path2, path, "zweiter Lauf legt eine neue Datei an statt die bestehende zu nutzen")
        eq(action2, "exists", "zweiter Lauf haette die Datei neu schreiben duerfen")
        text2 = path2.read_text(encoding="utf-8")
        for h in order:
            eq(text2.count(h), 1, f"Abschnitt {h} wurde verdoppelt")
    finally:
        restore_vault()




# ─────────────────────────────────────────── aufgaben (Offene Punkte)

def t_tasks_parse_canonical_question_and_unresolved():
    """Kanonisches Format (KONZEPT §4.1): Person, Themen, Frist, Entstehung,
    Quelle; ❓ = Frage; 'Name (?)' = unaufgeloest, nie geraten."""
    import aufgaben as tk
    importlib.reload(tk)
    t = tk.parse_line("- [ ] Freigaberunde-Entscheidung einfordern — [[kasimir-kempf|Kasimir Kempf]]"
                      " · [[blue-cargo|Blue Cargo]] 📅 2026-10-03 ➕ 2026-09-14"
                      " (→ [[2026-09-14 - Checkin - BlueCargo]])")
    eq((t.text, t.owner, t.topics, t.due, t.created, t.source, t.fmt, t.is_open),
       ("Freigaberunde-Entscheidung einfordern", "kasimir-kempf", ["blue-cargo"],
        "2026-10-03", "2026-09-14", "2026-09-14 - Checkin - BlueCargo", "neu", True))
    q = tk.parse_line("- [ ] ❓ Steht der Frankreich-Termin? — an [[robert-senger|Robert Senger]] ➕ 2026-08-03")
    eq((q.kind, q.text, q.owner), ("frage", "Steht der Frankreich-Termin?", "robert-senger"))
    u = tk.parse_line("- [x] Lizenzfrage klaeren — Robert (?) · [[blue-cargo]] ✅ 2026-09-30")
    eq((u.owner, u.owner_raw, u.is_open, u.done), (None, "Robert", False, "2026-09-30"))


def t_tasks_parse_short_form_and_dash_in_text():
    """Die Kurzform zum Eintippen ist lesbar; Log-Zeilen (auch `[ACTION]`) sind keine Punkte; ein
    Gedankenstrich im Text ist keine Person."""
    import aufgaben as tk
    importlib.reload(tk)
    a = tk.parse_line("- [ ] Plan abstimmen — @Felix — 2026-10-01")
    eq((a.text, a.owner_raw, a.due, a.fmt), ("Plan abstimmen", "Felix", "2026-10-01", "kurz"))
    b = tk.parse_line("- [ ] Plan abstimmen — @Felix — —")
    eq((b.owner_raw, b.due), ("Felix", None), "Platzhalter-Datum:")
    ok(tk.parse_line("- [2026-08-31] [ACTION] @unassigned: Felix - LOI klaeren -> Deadline: TBD") is None,
       "[ACTION]-Zeile als Punkt gelesen")
    d = tk.parse_line("- [ ] Daten **vorab** einsammeln — im Termin wird ausgewertet, nicht erhoben")
    eq((d.text.endswith("nicht erhoben"), d.owner, d.owner_raw), (True, None, None),
       "Gedankenstrich im Text als Person gelesen:")
    ok(tk.parse_line("- [2026-09-14] [DECISION] Kein Punkt") is None, "Entscheidung ist kein Punkt")


def t_tasks_render_roundtrip_and_key():
    """render() erzeugt das kanonische Format; parse(render(t)) verliert nichts;
    key() ist status- und schreibweisen-unabhaengig (Dublettenschutz)."""
    import aufgaben as tk
    importlib.reload(tk)
    t = tk.Task(status=" ", text="Frage klaeren", kind="frage", owner="robert-senger",
                topics=["blue-cargo"], due="2026-10-15", created="2026-08-03", source="q")
    line = tk.render(t)
    eq(line, "- [ ] ❓ Frage klaeren — an [[robert-senger]] · [[blue-cargo]] 📅 2026-10-15"
             " ➕ 2026-08-03 (→ [[q]])")
    back = tk.parse_line(line)
    eq((back.kind, back.text, back.owner, back.topics, back.due, back.created, back.source),
       ("frage", "Frage klaeren", "robert-senger", ["blue-cargo"], "2026-10-15", "2026-08-03", "q"))
    eq(tk.render(tk.Task(status=" ", text="Ohne alles")), "- [ ] Ohne alles")
    eq(tk.render(tk.Task(status=" ", text="Nur Thema", topics=["x"])), "- [ ] Nur Thema — ? · [[x]]")
    eq(tk.key("- Lizenzen klären!"), tk.key("lizenzen  KLÄREN"), "key nicht normalisiert:")


def t_tasks_scan_sections_owner_and_defaults():
    """Nur `## Actions` (Meeting) und `## Offene Punkte` (Thema); Checklisten in
    `## Vorbereitung` und Zeilen im Log sind keine Aufgaben. `@slug` wird nur bei
    exaktem Personen-Slug aufgeloest, ein Vorname bleibt Rohtext."""
    d = temp_vault()
    try:
        import aufgaben as tk
        importlib.reload(tk)
        (d / "entities" / "people" / "daniel-mohr.md").write_text(
            "---\ntype: person\nname: Daniel Mohr\n---\n", encoding="utf-8", newline="\n")
        (d / "entities" / "projects" / "blue-cargo.md").write_text(
            "---\ntype: project\ntitle: Blue Cargo\n---\n# Blue Cargo\n\n"
            "## Offene Punkte\n- [ ] Migrierter Punkt — [[daniel-mohr]] ➕ 2026-09-01\n\n"
            "## Event Log\n- [2026-09-14] [ACTION] @daniel-mohr: Kein Punkt -> Deadline: 2026-09-20\n"
            "- [2026-09-14] [DECISION] Keine Aufgabe\n", encoding="utf-8", newline="\n")
        mdir = d / "active-meetings" / "2026" / "09"
        mdir.mkdir(parents=True)
        (mdir / "2026-09-21 - review - Review Blue Cargo.md").write_text(
            "---\ntype: meeting\ndate: '2026-09-21'\nthemen: [blue-cargo]\n---\n"
            "## Vorbereitung\n- [ ] Daten vorab einsammeln — im Termin wird ausgewertet\n\n"
            "## Actions\n- [ ] Magnus informieren — [[daniel-mohr]]\n"
            "- [ ] Terrorcheck — @daniel-mohr — 2026-09-20\n- [ ] Irgendwas — @kuno — TBD\n",
            encoding="utf-8", newline="\n")
        found = tk.scan()
        texts = sorted(t.text for t in found)
        eq(texts, ["Irgendwas", "Magnus informieren", "Migrierter Punkt", "Terrorcheck"],
           "falsche Punkte gefunden:")
        by = {t.text: t for t in found}
        eq(by["Terrorcheck"].owner, "daniel-mohr", "@slug nicht aufgeloest:")
        eq((by["Irgendwas"].owner, by["Irgendwas"].owner_raw), (None, "kuno"), "Vorname geraten:")
        eq(by["Magnus informieren"].topics, ["blue-cargo"], "Meeting-Thema fehlt:")
        eq(by["Magnus informieren"].created, "2026-09-21", "Meeting-Datum fehlt:")
        eq(by["Migrierter Punkt"].topics, ["blue-cargo"], "Themen-Datei als Thema fehlt:")
        s = tk.summary(found, today="2026-09-27")["blue-cargo"]
        eq((s["offen"], s["ueberfaellig"], s["ohne_person"]), (4, 1, 1))
    finally:
        restore_vault()




def t_stand_block_facts_from_code_prose_only_on_change():
    """Stand-Block: unter der H1, Ampel/Zahlen/Termin aus Code, Prosa vom
    Modell nur bei Log-Aenderung (zweiter Lauf ohne Modellaufruf, byte-gleich);
    Prosa mit erfundenem Datum wird verworfen; offene Punkte sind kein Prosa-Eingang."""
    d = temp_vault()
    try:
        import stand as st
        importlib.reload(st)
        p = d / "entities" / "projects" / "p.md"
        p.write_text("---\ntype: project\ntitle: P\nstatus: active\n---\n# P\n\nEigene Notiz.\n\n"
                     "## Offene Punkte\n- [ ] Alt — @x — 2026-09-10\n\n"
                     "## Event Log\n- [2026-09-14] [RISK] Freigaberunde blockiert Rollout\n"
                     "- [2026-09-02] [STATUS] Laderaum-Abgleich in DE live\n", encoding="utf-8", newline="\n")
        m = d / "active-meetings" / "2026" / "10"
        m.mkdir(parents=True)
        (m / "2026-10-02 - review - P Review.md").write_text(
            "---\ntype: meeting\ndate: '2026-10-02'\nthemen: [p]\n---\n", encoding="utf-8", newline="\n")
        calls = []

        def fake_llm(messages, schema, **kw):
            calls.append(messages[1]["content"])
            return {"stand": "Laderaum-Abgleich ist in Deutschland live. Der Rollout haengt am "
                             "Freigaberunde (Stand 2026-09-14).", "fremde_eintraege": [2]}, []

        r = st.run(llm_call=fake_llm, today=date(2026, 9, 27))[0]
        text = p.read_text(encoding="utf-8")
        ok(text.index("# P") < text.index(st.MARK_START) < text.index("Eigene Notiz"), "Position")
        ok("> [!abstract] Stand 27.09.2026 · 🟡 gelb" in text, text)
        ok("**Offen:** 1 Punkt(e) (1 überfällig) · **Risiken (30 Tage):** 1" in text, text)
        ok("[[2026-10-02 - review - P Review|02.10.2026]]" in text, "naechster Termin fehlt")
        ok("Laderaum-Abgleich ist in Deutschland live" in text, text)
        # Nur Punkte in der eigenen Datei: keine (leere) Abfrage im Block
        ok(st.TASK_QUERY not in text, text)
        ok("@x" not in calls[0], "Aufgabe als Prosa-Eingang")
        eq(r["foreign"][0]["text"], "Laderaum-Abgleich in DE live", "fremde Eintraege:")
        st.run(llm_call=fake_llm, today=date(2026, 9, 27))
        eq((len(calls), p.read_text(encoding="utf-8")), (1, text), "zweiter Lauf:")
        # Ein Punkt aus einem Meeting verlinkt das Thema -> die Abfrage erscheint
        (m / "2026-10-01 - checkin - P.md").write_text(
            "---\ntype: meeting\ndate: '2026-10-01'\n---\n## Actions\n"
            "- [ ] Rollout freigeben — ? · [[p]] ➕ 2026-10-01\n", encoding="utf-8", newline="\n")
        st.run(llm_call=fake_llm, today=date(2026, 9, 27))
        ok(st.TASK_QUERY in p.read_text(encoding="utf-8"), "Abfrage fehlt trotz Meeting-Punkt")
        eq(len(calls), 1, "Prosa ohne Log-Aenderung neu geschrieben")

        bad = lambda *a, **k: ({"stand": "Go-live ist am 2027-02-01 fest geplant und bestaetigt.",
                                "fremde_eintraege": []}, [])
        eq(st.validate_prose(bad()[0]["stand"], st.prose_events(text)), None,
           "erfundenes Datum nicht verworfen")
    finally:
        restore_vault()


def t_term_index_sources_topics_and_candidates():
    """Begriffs-Index: Vault-Namen/Aliasse, Atlas-Objekte (Thema ueber Kontext -> Subdomaene) und
    LikeC4-Systeme; laengster Begriff gewinnt; ein in der Konfiguration ignoriertes Einzelwort ist
    kein Begriff; das Meeting-Thema bleibt Kandidat 1."""
    d = temp_vault()
    saved = os.environ.get("VAULT_DOMAIN_ATLAS"), os.environ.get("VAULT_LIKEC4_MODEL")
    try:
        # welche Einzelwoerter in diesem Vault nichts unterscheiden, sagt die Konfiguration
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps({"begriffe": {"ignorieren": ["delta"]}}),
                                                        encoding="utf-8", newline="\n")
        import begriffsindex as ti
        importlib.reload(ti)
        (d / "entities" / "projects" / "blue-cargo.md").write_text(
            "---\ntype: project\ntitle: Blue Cargo\nkeywords: [delta]\n---\n", encoding="utf-8", newline="\n")
        (d / "entities" / "projects" / "produkt-order-router.md").write_text(
            "---\ntype: project\ntitle: Order Router (Produkt)\n---\n", encoding="utf-8", newline="\n")
        (d / "entities" / "systems" / "order-router.md").write_text(
            "---\ntype: system\nname: Order Router\naliases: [ODI]\n---\n", encoding="utf-8", newline="\n")
        atlas = d / "atlas"
        for sub, name, body in (
                ("subdomains", "sd-blue-cargo", "id: sd-blue-cargo\nname: Blue Cargo\n"),
                ("contexts", "ctx-dl-auftrag", "id: ctx-dl-auftrag\nname: DL Auftrag\n"
                                               "primarySubdomain: sd-blue-cargo\n"),
                ("object-refs", "obj-abholauftrag",
                 "id: obj-abholauftrag\nconcept: Abholauftrag\ncontext: ctx-dl-auftrag\n"
                 "definition: Auftrag, Ware abzuholen.\naliases: [Pickup Order]\n")):
            (atlas / "canon" / sub).mkdir(parents=True, exist_ok=True)
            (atlas / "canon" / sub / f"{name}.yaml").write_text(body, encoding="utf-8", newline="\n")
        c4 = d / "c4"
        c4.mkdir()
        (c4 / "model.c4").write_text(
            "model {\n  odi = softwareSystem 'Order Router' {\n"
            "    description 'Verteilt Auftraege auf Niederlassungen'\n  }\n"
            "  kunde = person 'Kunde'\n}\n", encoding="utf-8", newline="\n")
        os.environ["VAULT_DOMAIN_ATLAS"], os.environ["VAULT_LIKEC4_MODEL"] = str(atlas), str(c4)
        idx = ti.load(rebuild=True)
        kinds = {(e["target"], e["kind"]) for e in idx["index"]["entries"]}
        ok(("obj-abholauftrag", "atlas-object") in kinds, "Atlas-Objekt fehlt")
        ok(("order-router", "c4-softwareSystem") in kinds, "LikeC4-System fehlt")
        ok(not any(e["norm"] == "delta" for e in idx["index"]["entries"]), "'delta' ist Begriff")
        hits = ti.find("Die Pickup Order im Order Router abstimmen", idx)
        eq({h["target"] for h in hits}, {"obj-abholauftrag", "order-router"}, "Treffer:")
        pick = next(h for h in hits if h["target"] == "obj-abholauftrag")
        eq((pick["topic"], pick["definition"]), ("blue-cargo", "Auftrag, Ware abzuholen."))
        eq(ti.candidate_topics("Pickup Order im Order Router", "x-meeting", idx=idx),
           ["x-meeting", "produkt-order-router", "blue-cargo"], "Kandidaten:")
    finally:
        for k, v in zip(("VAULT_DOMAIN_ATLAS", "VAULT_LIKEC4_MODEL"), saved):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        restore_vault()




def t_md_sections_replace_and_insert():
    """replace_section ersetzt einen vorhandenen Abschnitt statt ihn zu verdoppeln und fuegt einen
    neuen vor dem Ziel-Abschnitt ein."""
    import abschnitte as ms
    importlib.reload(ms)
    text = "# T\n\n## Meine Notizen\nx\n\n## Entscheidungen\n- [E] a\n"
    once = ms.replace_section(text, "## Teams", "neu", ("## Entscheidungen",))
    eq(once, "# T\n\n## Meine Notizen\nx\n\n## Teams\n\nneu\n\n## Entscheidungen\n- [E] a\n")
    twice = ms.replace_section(once, "## Teams", "neuer", ("## Entscheidungen",))
    eq(twice.count("## Teams"), 1, "Abschnitt verdoppelt")
    ok("neuer" in twice and "\nneu\n" not in twice, "nicht ersetzt")
    eq(ms.section_body(twice, "## Teams"), "neuer")


def t_no_empty_frontmatter_from_any_creator():
    """Leere Felder (`atlas_id: ''`, `company: "[[]]"`, `aliases: []`) sind Rauschen: kein Erzeuger
    schreibt sie, beim Aktualisieren verschwinden vorhandene (ein leerer Wert entfernt das Feld),
    das Aufraeumen ist zeilengenau."""
    d = temp_vault()
    try:
        import vault_paths as vp
        (d / ".templates").mkdir(exist_ok=True)
        import shutil
        for t in ("person", "system", "team", "company", "project", "forum"):
            src = ENGINE / "vorlage" / ".templates" / f"{t}.md"
            if src.is_file():
                shutil.copy(src, d / ".templates" / src.name)
        import anlegen, thema_anlegen, reihen, uebernehmen
        for m in (anlegen, thema_anlegen, reihen, uebernehmen):
            importlib.reload(m)
        anlegen.create("people", "Anna Berg")
        anlegen.create("teams", "Team Nord")
        anlegen.create("companies", "Muster GmbH")
        thema_anlegen.create("Neues Projekt", ["neu"])
        reihen.create("Weekly Test")
        uebernehmen.apply_entities([{"category": "systems", "slug": "sys-x", "name": "Sys X"},
                                     {"category": "people", "slug": "tom-klein", "name": "Tom Klein"}])
        dirty = []
        for f in (d / "entities").rglob("*.md"):
            fm = vp.read_frontmatter(f)
            dirty += [f"{f.parent.name}/{f.name}:{k}" for k, v in fm.items() if vp.is_empty_value(v)]
        eq(dirty, [], "leere Felder geschrieben:")

        f = d / "x.md"
        f.write_text("---\ntype: person\nemail: ''\ncompany: \"[[]]\"\naliases: []\nrole: Lead\n"
                     "tags:\n- a\nnotes:\n---\n# X\n", encoding="utf-8", newline="\n")
        eq(vp.strip_empty_frontmatter(f.read_text(encoding="utf-8")),
           "---\ntype: person\nrole: Lead\ntags:\n- a\n---\n# X\n", "zeilengenau:")
        f.write_text("---\ntype: person\nteam: x\n---\n", encoding="utf-8", newline="\n")
        vp.update_frontmatter(f, {"role": "Lead", "team": ""})
        eq(vp.read_frontmatter(f), {"type": "person", "role": "Lead"},
           "leerer Wert muss das Feld entfernen:")
    finally:
        restore_vault()


def t_wrapup_request_from_phone():
    """Am Handy vorgemerkt (`nachbereiten: angefordert`): die Automatik am Desktop bereitet nach,
    obwohl sonst nur auf Ansage - danach ist die Vormerkung weg. Ohne Modell bleibt sie stehen;
    ohne Material wird sie zum Hinweis statt zur Dauer-Vormerkung."""
    d = temp_vault()
    import modell
    orig = (modell.complete_json, modell.available)
    try:
        import auto
        importlib.reload(auto)
        m = d / "active-meetings"
        m.mkdir(parents=True, exist_ok=True)
        note = m / "2026-09-21 - review - Handy.md"
        note.write_text("---\ntype: meeting\ntitle: Handy\ndate: '2026-09-21'\nnachbereiten: angefordert\n---\n"
                        "## Meine Notizen\n\nRollout im Oktober beschlossen, Anna verteilt die Checkliste.\n",
                        encoding="utf-8", newline="\n")
        thin = m / "2026-09-22 - review - Wenig.md"
        thin.write_text("---\ntype: meeting\ntitle: Wenig\ndate: '2026-09-22'\nnachbereiten: angefordert\n---\n"
                        "## Meine Notizen\n\nkurz\n", encoding="utf-8", newline="\n")
        other = m / "2026-09-23 - review - Anderer.md"
        other.write_text("---\ntype: meeting\ntitle: Anderer\ndate: '2026-09-23'\n---\n## Meine Notizen\n\n"
                         + "Viel Text, aber nicht vorgemerkt. " * 10 + "\n", encoding="utf-8", newline="\n")

        def fake(messages, schema, **kw):
            return {"entscheidungen": [{"was": "Rollout im Oktober", "wer": "", "datum": "", "thema": ""}],
                    "actions": [], "kernteil": [], "parkplatz": []}, []
        modell.complete_json, modell.available = fake, lambda *a, **k: (True, "test")
        r0 = auto.run(only={"nachbereiten"}, llm_status=(False, "aus"))
        ok(r0["steps"][0].get("skipped") and "2 vorgemerkt" in r0["steps"][0]["detail"], r0)
        ok("nachbereiten: angefordert" in note.read_text(encoding="utf-8"), "Vormerkung ohne Modell verloren")
        r = auto.run(only={"nachbereiten"}, llm_status=(True, "test"))
        ok(r["steps"][0].get("changed") == 1, r)
        fm = vp_read(note)
        eq((fm.get("status"), fm.get("nachbereiten")), ("nachbereitet", None), "Vormerkung nicht erledigt:")
        eq(vp_read(thin).get("nachbereiten"), "zu wenig Text", "ohne Material:")
        ok("nachbereitet" not in other.read_text(encoding="utf-8"), "nicht Vorgemerktes nachbereitet")
        # vorgemerkt, aber einzeln nachbereitet (Knopf am Desktop): die Vormerkung ist trotzdem erledigt
        knopf = m / "2026-09-24 - review - Knopf.md"
        knopf.write_text("---\ntype: meeting\ntitle: Knopf\ndate: '2026-09-24'\nnachbereiten: angefordert\n---\n"
                         "## Meine Notizen\n\nRollout im Oktober beschlossen, Anna verteilt die Checkliste.\n",
                         encoding="utf-8", newline="\n")
        auto.run(only={"nachbereiten"}, llm_status=(True, "test"), note=knopf)
        eq((vp_read(knopf).get("status"), vp_read(knopf).get("nachbereiten")), ("nachbereitet", None),
           "Vormerkung nach dem Knopf:")
    finally:
        modell.complete_json, modell.available = orig
        restore_vault()


def vp_read(path):
    import vault_paths as vp
    return vp.read_frontmatter(path)


def t_auto_chain_sync_per_note_waits_without_model_and_locks():
    """Automatik-Kette nachbereiten -> themenlog -> stand: nachbereitet wird nur auf Ansage (oder
    mit `auto.wrapup_automatisch`); Entscheidungen kommen je Notiz ins Themen-Log, mit Datum und
    Link des Termins, und Rueckgaengig kennt diese Zeilen; der zweite Lauf fragt das Modell nicht
    erneut; ohne Modell wartet die Nachbereitung (kein Notfallmodus); die Sperre verhindert einen
    Parallellauf."""
    d = temp_vault()
    saved = os.environ.get("VAULT_DOMAIN_ATLAS")
    os.environ["VAULT_DOMAIN_ATLAS"] = str(d / "kein-atlas")     # hermetisch
    import modell
    orig = (modell.complete_json, modell.available)
    try:
        import auto
        (d / "entities" / "projects" / "p.md").write_text(
            "---\ntype: project\ntitle: P\nstatus: active\n---\n# P\n\n## Event Log\n"
            "- [2026-09-01] [STATUS] Start\n", encoding="utf-8", newline="\n")
        m = d / "active-meetings" / "2026" / "09"
        m.mkdir(parents=True)
        note = m / "2026-09-21 - review - P Review.md"
        note.write_text("---\ntype: meeting\ntitle: P Review\ndate: '2026-09-21'\nthemen: [p]\n"
                        "---\n## Meine Notizen\n\n## Teams-Zusammenfassung\n"
                        + "Gefahrgutmaske gezeigt, Rollout besprochen. " * 8
                        + "\n\n## Entscheidungen\n\n## Actions\n", encoding="utf-8", newline="\n")
        calls = []

        def fake_complete_json(messages, schema, **kw):
            calls.append(kw.get("task"))
            if kw.get("task") == "stand":
                return {"stand": "P ist gestartet, der Rollout ist besprochen und fuer Oktober geplant.",
                        "fremde_eintraege": []}, []
            return {"entscheidungen": [{"was": "Rollout im Oktober", "wer": "", "datum": "",
                                        "thema": ""}],
                    "actions": [{"was": "Checkliste verteilen", "wer": "", "bis": "", "thema": ""}],
                    "kernteil": [], "parkplatz": []}, []

        modell.complete_json, modell.available = fake_complete_json, lambda *a, **k: (True, "test")
        only = {"nachbereiten", "themenlog", "stand"}
        # Standard: nachbereitet wird nur auf Ansage - vorher erfasst der Benutzer nach
        r0 = auto.run(only={"nachbereiten"}, llm_status=(True, "test"))
        ok(r0["steps"][0].get("skipped") and "Ansage" in r0["steps"][0]["detail"], r0)
        ok("nachbereitet" not in note.read_text(encoding="utf-8"), "ohne Ansage nachbereitet")
        (d / ".2ndbrain" / "local.config.json").write_text(
            '{"auto": {"wrapup_automatisch": true}}', encoding="utf-8", newline="\n")
        r = auto.run(only=only, llm_status=(True, "test"))
        eq([s["step"] for s in r["steps"]], ["nachbereiten", "themenlog", "stand"])
        ok(all(s["ok"] for s in r["steps"]), r)
        log = (d / "entities" / "projects" / "p.md").read_text(encoding="utf-8")
        line = "- [2026-09-21] [DECISION] Rollout im Oktober (→ [[2026-09-21 - review - P Review]])"
        ok(line in log, f"Sync ohne Termin-Datum/Quelle:\n{log}")
        import nachbereiten
        eq((nachbereiten.load_undo(note) or {}).get("sync", {}).get("events"), {"p": [line]},
           "Rueckgaengig kennt die Log-Zeile nicht:")
        ok("- [ ] Checkliste verteilen — ? · [[p|P]] ➕ 2026-09-21" in note.read_text(encoding="utf-8"),
           "Punkt fehlt in der Notiz")
        ok("- [E] Rollout im Oktober — ?" + chr(10) in note.read_text(encoding="utf-8"), "Entscheidung")
        ok("<!-- stand-auto:start -->" in log, "Stand-Block fehlt")
        n_calls = len(calls)
        auto.run(only=only, llm_status=(True, "test"))
        eq(len(calls), n_calls, "zweiter Lauf hat das Modell erneut gefragt")

        note2 = m / "2026-09-22 - checkin - P Checkin.md"
        note2.write_text("---\ntype: meeting\ntitle: P Checkin\ndate: '2026-09-22'\nthemen: [p]\n---\n"
                         "## Meine Notizen\n" + "Neuer Stand besprochen. " * 12 + "\n",
                         encoding="utf-8", newline="\n")
        r3 = auto.run(only={"nachbereiten"}, llm_status=(False, "aus"))
        ok(r3["steps"][0].get("skipped") and "wartet" in r3["steps"][0]["detail"], r3)
        ok("nachbereitet" not in note2.read_text(encoding="utf-8"), "Notfallmodus lief ohne Modell")

        auto.LOCK_FILE.write_text("x", encoding="utf-8", newline="\n")
        eq(auto.run(only={"stand"}, llm_status=(True, "t"))["steps"], [], "Sperre ignoriert")
        auto.release_lock()
    finally:
        modell.complete_json, modell.available = orig
        if saved is None:
            os.environ.pop("VAULT_DOMAIN_ATLAS", None)
        else:
            os.environ["VAULT_DOMAIN_ATLAS"] = saved
        restore_vault()


def t_glossary_build_atlas_and_grounded_proposals():
    """Glossar: Atlas-Fachobjekt mit offizieller Definition; Modell-Vorschlaege
    nur mit Fundstellen - eine nicht belegte Langform wird verworfen; eine
    vorhandene Definition bleibt; Rauschen wird nicht neu angelegt."""
    d = temp_vault()
    saved = os.environ.get("VAULT_DOMAIN_ATLAS")
    try:
        import glossar as gb
        import vault_paths as vp
        importlib.reload(gb)
        atlas = d / "atlas" / "canon"
        (atlas / "object-refs").mkdir(parents=True)
        (atlas / "contexts").mkdir(parents=True)
        (atlas / "contexts" / "ctx-pickup.yaml").write_text("id: ctx-pickup\nname: Pickup\n",
                                                           encoding="utf-8", newline="\n")
        (atlas / "object-refs" / "obj-abholauftrag.yaml").write_text(
            "id: obj-abholauftrag\nconcept: Abholauftrag\ncontext: ctx-pickup\n"
            "definition: Auftrag, Ware an einer Beladestelle abzuholen.\naliases: [Pickup Order]\n",
            encoding="utf-8", newline="\n")
        os.environ["VAULT_DOMAIN_ATLAS"] = str(d / "atlas")
        G = d / "entities" / "glossary"
        (G / "cdp.md").write_text("---\ntype: glossary_term\nterm: cdp\nstatus: candidate\n---\n# cdp\n\n"
                                  f"{gb.DEF_HEADING}\n\n<!-- Platzhalter -->\n", encoding="utf-8", newline="\n")
        (G / "eta.md").write_text("---\ntype: glossary_term\nterm: ETA\n---\n# ETA\n\n"
                                  f"{gb.DEF_HEADING}\n\nMeine eigene Definition.\n", encoding="utf-8", newline="\n")
        (G / "http.md").write_text("---\ntype: glossary_term\nterm: HTTP\nstatus: candidate\n---\n# HTTP\n\n"
                                   f"{gb.DEF_HEADING}\n\n<!-- x -->\n", encoding="utf-8", newline="\n")
        src = d / "archive" / "meetings" / "2026-09"
        src.mkdir(parents=True)
        for i in range(3):
            (src / f"2026-09-1{i}-m.md").write_text(
                f"Die CDP (Customer Data Platform) liefert Daten. TPRM wird geprueft, Runde {i}. "
                "TPRM bleibt Thema. TPRM ist wichtig.\n", encoding="utf-8", newline="\n")

        def fake(messages, schema, **kw):
            return {"begriffe": [
                {"begriff": "CDP", "art": "system", "langform": "Customer Data Platform",
                 "definition": "Zentrale Datenplattform."},
                {"begriff": "TPRM", "art": "abkuerzung", "langform": "Third Party Risk Management",
                 "definition": "Pruefung von Transportpartnern."},
                {"begriff": "HTTP", "art": "allgemein", "langform": "", "definition": ""},
            ]}, []

        r = gb.run(apply=True, llm_call=fake)
        ab = (G / "abholauftrag.md").read_text(encoding="utf-8")
        ok("Auftrag, Ware an einer Beladestelle abzuholen." in ab and "status: atlas" in ab, ab)
        cdp = (G / "cdp.md").read_text(encoding="utf-8")
        ok("Customer Data Platform: Zentrale Datenplattform." in cdp and "[[2026-09-12-m]]" in cdp, cdp)
        # gleicher Satz in drei Quellen -> eine Fundstelle; Schreibweise aus dem Text
        ok("[[2026-09-11-m]]" not in cdp, "Dubletten-Fundstelle")
        ok("term: CDP" in cdp and "\n# CDP\n" in cdp, "Schreibweise nicht angepasst")
        tprm = (G / "tprm.md").read_text(encoding="utf-8")
        ok("Third Party" not in tprm and "Pruefung von Transportpartnern." in tprm,
           "nicht belegte Langform uebernommen")
        ok("Meine eigene Definition." in (G / "eta.md").read_text(encoding="utf-8"), "Definition ueberschrieben")
        eq(r.get("neue_abkuerzungen"), 1, "Abkuerzungs-Kandidaten:")
        # Bestehender Eintrag, vom Modell als "allgemein" eingeordnet: nur Hinweis,
        # zurueckweisen entscheidet der Mensch.
        http = vp.read_frontmatter(G / "http.md")
        eq((http.get("status"), http.get("art")), ("candidate", "allgemein"), "HTTP-Eintrag:")
    finally:
        if saved is None:
            os.environ.pop("VAULT_DOMAIN_ATLAS", None)
        else:
            os.environ["VAULT_DOMAIN_ATLAS"] = saved
        restore_vault()


def t_glossary_snippets_whole_sentences_no_links_no_twins():
    """Fundstellen: hart umbrochene Absaetze werden zusammengefuegt, Ueberschriften
    bleiben fuer sich; ein Begriff nur im Link/Dateinamen ist keine Fundstelle;
    derselbe Satz aus Notiz und Archivkopie zaehlt einmal (neueste zuerst);
    Langform nur mit passenden Anfangsbuchstaben."""
    import glossar as gb
    importlib.reload(gb)
    wrapped = ("## Warum klassifizieren?\nVier Klassen (K1-K4) nach Lebensdauer, Ziel: die richtige\n"
               "Governance fuer den Zweck, von Wegwerf-\nPrototypen bis Enterprise Core.\n")
    paras = list(gb._paragraphs(wrapped))
    eq(paras[0], "## Warum klassifizieren?", "Ueberschrift:")
    ok(paras[1].endswith("von Wegwerf- Prototypen bis Enterprise Core."), paras)
    docs = [
        ("2026-09-14 - Weekly - Winter", "Tour Matching gleicht Angebot und Nachfrage im Blue Cargo ab.\n"),
        ("2026-09-14---weekly---winter", "Tour Matching gleicht Angebot und Nachfrage im Blue Cargo ab.\n"),
        ("2026-08-01-alt", "Beim Tour Matching fehlen noch die Regeln fuer Teilladungen.\n"),
        ("2026-09-20-import", "> Automatisch importiert aus [[attachments/Tour Matching Deck.pptx|Tour Matching Deck.pptx]]\n"),
    ]
    got = gb.snippets("Tour Matching", docs)
    eq([s for s, _ in got], ["2026-09-14 - Weekly - Winter", "2026-08-01-alt"], "Fundstellen:")
    eq(gb.expansion("CDP", "Operational Data via Customer Data Pool (CDP) live"), "Customer Data Pool",
       "Langform davor:")
    eq(gb.expansion("CDP", "Die CDP (Customer Data Platform) liefert."), "Customer Data Platform",
       "Langform danach:")
    eq(gb.expansion("TPA", "Transport Assignment (TPA)"), "", "Initialen passen nicht:")
    eq(gb.display_form("tour matching", docs), "Tour Matching", "Schreibweise:")
    eq(gb.display_form("xyz", docs), "xyz", "unbekannt bleibt:")
    rest = [("a", "Der Rest kommt spaeter, der Rest ist offen, Rest egal. Die REST-API und REST sind da, "
                  "REST bleibt. Siehe http://x.de/rest und http://y.de/http")]
    eq(gb.display_form("rest", rest), "REST", "kurzes Wort, belegte Grossschreibung:")
    eq(gb.display_form("http", rest), "http", "URL zaehlt nicht als Erwaehnung:")
    shout = [(f"d{i}", "Das TMS ist NICHT fertig. TMS und TMS, nicht jetzt, nicht so, nicht dort, "
                       "nicht hier.") for i in range(3)]
    eq(gb.acronym_candidates(shout, set()), ["TMS"], "Hervorhebung ist keine Abkuerzung:")


def t_glossar_schwellen_notizen_stopplisten_kuerzel():
    """Neue Glossar-Seiten nur fuer Sprache des Vaults: aus mindestens 3 Notizen (Woerter aus einer
    einzigen Liste oder Spezifikation zaehlen nicht), beide Stopplisten auf beiden Wegen (dev, sso
    ueber Begriffe; SDR, SZR ueber Abkuerzungen), Kuerzel mit zwei Buchstaben nur mit
    ausgeschriebener Langform - sonst werden sie geraten."""
    d = temp_vault()
    try:
        import glossar as g
        importlib.reload(g)
        terms = {"frachtboerse": {"count": 12, "files": ["a.md"]},
                 "tarifwerk": {"count": 12, "files": ["a.md", "b.md", "c.md"]},
                 "dev": {"count": 12, "files": ["a.md", "b.md", "c.md"]}}
        kept, reasons = g.filter_candidates(terms, 10)
        eq(sorted(kept), ["tarifwerk"], "behalten:")
        eq((reasons["zu_wenig_notizen"], reasons["stoppwort"]), (1, 1), "Gruende:")
        docs = [(f"n{i}", "Heute: TC und CR und FMB und SZR. Danach TC, CR, FMB, SZR.") for i in range(3)]
        docs[0] = ("n0", "Change Request (CR) heisst der Antrag auf eine Aenderung. " + docs[0][1])
        eq(g.acronym_candidates(docs, set()), ["CR", "FMB"], "Abkuerzungen:")
    finally:
        restore_vault()


def t_tasks_altbestand_append_insert_dissolve():
    """Altbestand: eigener Unterabschnitt am Ende von 'Offene Punkte' (mit Belegen
    und Hinweisen); neue Punkte aus Nachbereitungen landen darueber, nicht darin;
    Aufloesen nach dem Termin: Ueberschrift, Einleitung und Pruef-Hinweise weg,
    Belege bleiben, abgehakt ohne ✅ bekommt das Termindatum, Liste haengt zusammen."""
    import aufgaben as tk
    importlib.reload(tk)
    text = ("# Thema\n\n## Offene Punkte\n- [ ] Neu aus Wrapup — [[a|A]] ➕ 2026-09-20\n\n"
            "## Event Log\n- [2026-09-20] [STATUS] x\n")
    alt = [tk.Task(status=" ", text="Offen alt", owner_raw="Jan", due="2026-08-26",
                   created="2026-08-17", source="q1", notes=["Hinweis: Termin 26.08. verstrichen"]),
           tk.Task(status="x", text="Erledigt alt", created="2026-08-31", done="2026-09-14",
                   source="q2", notes=["Beleg 14.09.: „erledigt“ ([[m1]])"]),
           tk.Task(status="x", text="Vom Menschen abgehakt", created="2026-08-31", source="q3"),
           tk.Task(status="-", text="Verworfen alt", created="2026-08-31")]
    out, n = _mit_altbestand(text, alt, day="2026-09-27")
    eq(n, 4, "Altbestand geschrieben:")
    ok(out.index("- [ ] Neu aus Wrapup") < out.index(tk.ALTBESTAND_HEADING) < out.index("## Event Log"), out)
    ok("    - Beleg 14.09.: „erledigt“ ([[m1]])" in out and "(27.09.2026)" in out, out)
    ok("[ACTION]" not in out, "Literal [ACTION] im Thema (andere Werkzeuge suchen danach)")
    flags = {t.text: t.pruefen for t in tk.tasks_in_text(out, "topic", stem="thema")}
    eq(flags, {"Neu aus Wrapup": False, "Offen alt": True, "Erledigt alt": True,
               "Vom Menschen abgehakt": True, "Verworfen alt": True}, "pruefen-Flag:")

    out2, _ = tk.append_to_section(out, tk.TOPIC_SECTION, [tk.Task(status=" ", text="Noch neuer")])
    ok(out2.index("- [ ] Noch neuer") < out2.index(tk.ALTBESTAND_HEADING), out2)
    eq({t.text: t.pruefen for t in tk.tasks_in_text(out2, "topic")}["Noch neuer"], False,
       "neuer Punkt im Altbestand gelandet:")

    done, c = tk.dissolve_altbestand(out2, "2026-09-29")
    eq(c, {"offen": 1, "erledigt": 2, "verworfen": 1}, "Zaehler:")
    ok(tk.ALTBESTAND_HEADING not in done and "Übernommen aus" not in done
       and "Hinweis:" not in done, done)
    ok("    - Beleg 14.09.: „erledigt“ ([[m1]])" in done, "Beleg verloren")
    ok("- [x] Vom Menschen abgehakt ➕ 2026-08-31 ✅ 2026-09-29 (→ [[q3]])" in done, done)
    ok("✅ 2026-09-14 (→ [[q2]])" in done, "vorhandenes ✅ ueberschrieben")
    ok(not any(t.pruefen for t in tk.tasks_in_text(done, "topic")), "pruefen nach dem Aufloesen")
    sec = done.split("## Offene Punkte\n", 1)[1].split("## Event Log", 1)[0]
    eq(sec.strip().count("\n\n"), 0, "Leerzeile mitten in der Liste:")
    ok(done.endswith("## Event Log\n- [2026-09-20] [STATUS] x\n"), done)
    eq(tk.dissolve_altbestand(done, "2026-09-30"),
       (done, {"offen": 0, "erledigt": 0, "verworfen": 0}), "zweites Aufloesen:")


def t_altbestand_prep_block_settle_after_wrapup():
    """Altbestand im Termin: die Vorbereitung legt ihn als Live-Liste vor (nur fuer
    das Thema des Termins); Stand und Ampel nennen ihn. Erst nach der Nachbereitung
    gilt der Rest als geprueft: Thema aufgeloest, Event-Log-Eintrag mit Link, in der
    Notiz das Ergebnis statt der Liste. Vor dem Termin oder ohne Nachbereitung
    passiert nichts; der zweite Lauf ist leer."""
    d = temp_vault()
    try:
        import aufgaben as tk
        import altbestand as ab
        import vorbereiten
        import stand
        importlib.reload(ab)
        p = d / "entities" / "projects" / "demo.md"
        base = ("---\ntype: project\nname: Demo\n---\n# Demo\n\n## Offene Punkte\n\n"
                "## Event Log\n- [2026-09-01] [STATUS] Start\n")
        text, _ = _mit_altbestand(base, [
            tk.Task(status=" ", text="Angebot pruefen", created="2026-08-10", due="2026-08-20"),
            tk.Task(status="x", text="Mail schicken", created="2026-08-10", done="2026-08-12")],
            day="2026-09-27")
        p.write_text(text, encoding="utf-8", newline="\n")
        c = ab.pending("2026-09-27")["demo"]
        eq((c["offen"], c["erledigt"], c["ueberfaellig"]), (1, 1, 1), "Zaehler:")
        block = "\n".join(ab.prep_block("demo", p, c, "Demo"))
        ok('FROM "entities/projects"' in block and 'file.name = "demo"' in block
           and tk.ALTBESTAND_DV in block
           and block.startswith("<!-- altbestand:demo -->") and "[ACTION]" not in block, block)
        ev = {"title": "Demo Weekly", "type": "checkin", "series": "demo-weekly", "participants": []}
        proj = {"slug": "demo", "name": "Demo", "path": p, "altbestand": c, "health": ""}
        ok("### Altbestand klären (2 Punkte, 1 mit verstrichener Frist)"
           in vorbereiten.build_prep(ev, None, proj), "Block fehlt in der Vorbereitung")
        ok("Altbestand" not in vorbereiten.build_prep(ev, None, {**proj, "altbestand": None}),
           "Block ohne Altbestand")

        today = date(2026, 9, 27)
        f = stand.facts(p, tk.open_by_topic().get("demo", []), None, today)
        eq(f["altbestand"], 2, "Stand-Fakt:")
        ok("ungeprüfter Altbestand" in "; ".join(f["health_reasons"]), f["health_reasons"])
        ok("**Altbestand:** 2 ungeprüft" in stand.render_block(f, "x" * 80, today), "Stand-Block")

        mdir = d / "active-meetings" / "2026" / "09"
        mdir.mkdir(parents=True)

        def meeting(name, day, status):
            m = mdir / f"{name}.md"
            m.write_text(f"---\ntype: meeting\ntitle: {name}\ndate: '{day}'\nthemen: [demo]\n"
                         f"status: {status}\n---\n# {name}\n\n## Vorbereitung\n\n{block}\n\n"
                         "## Meine Notizen\n\nx\n", encoding="utf-8", newline="\n")
            return m

        meeting("2026-09-30 - checkin - Demo", "2026-09-30", "vorbereitet")
        missed = meeting("2026-09-25 - checkin - Demo", "2026-09-25", "vorbereitet")
        eq(ab.settle(today), [], "vor dem Termin/ohne Nachbereitung:")
        ok(tk.ALTBESTAND_HEADING in p.read_text(encoding="utf-8"), "zu frueh aufgeloest")

        held = meeting("2026-09-26 - checkin - Demo", "2026-09-26", "nachbereitet")
        # am Tag der Nachbereitung noch nicht (dann ist Rueckgaengig noch sauber)
        vp_ = importlib.import_module("vault_paths")
        vp_.update_frontmatter(held, {"wrapped_at": "2026-09-27T10:00:00"})
        eq(ab.settle(today), [], "am Tag der Nachbereitung:")
        today = date(2026, 9, 28)
        r = ab.settle(today)
        eq([(x["slug"], x["meeting"]) for x in r], [("demo", "2026-09-26 - checkin - Demo")],
           "ausgewertet:")
        t = p.read_text(encoding="utf-8")
        ok(tk.ALTBESTAND_HEADING not in t and "- [ ] Angebot pruefen" in t, t)
        ok("- [2026-09-26] [STATUS] Altbestand geklärt: 1 weiter offen, 1 erledigt, 0 verworfen"
           " (→ [[2026-09-26 - checkin - Demo]])" in t, t)
        n = held.read_text(encoding="utf-8")
        ok("```dataview" not in n and "### Altbestand geklärt — [[demo|Demo]]" in n
           and "- ⏳ Angebot pruefen" in n and "- ✅ Mail schicken" in n
           and "## Meine Notizen\n\nx" in n, n)
        eq(ab.settle(today), [], "zweiter Lauf:")
        ok("```dataview" in missed.read_text(encoding="utf-8"), "verpasster Termin veraendert")
        # wird der verpasste Termin spaeter doch nachbereitet: nur ein Hinweis
        missed.write_text(missed.read_text(encoding="utf-8").replace(
            "status: vorbereitet", "status: nachbereitet"), encoding="utf-8", newline="\n")
        eq(ab.settle(today), [], "schon geklaert:")
        ok("war schon geklärt" in missed.read_text(encoding="utf-8"), "Hinweis fehlt")
    finally:
        restore_vault()


def t_capture_notes_entfallen_and_undo_wrapup():
    """Nacherfassen: Notizen landen in 'Meine Notizen' (Nachgetragenes gekennzeichnet), ein Termin
    wird 'entfallen' (neue Notizen heben das auf) oder uebersprungen. Eine Nachbereitung laesst
    sich zuruecknehmen: Notiz wie davor, ihre Log-Zeilen und der Doppelt-Schutz weg - wurde die
    Notiz danach geaendert, nur mit force."""
    d = temp_vault()
    try:
        import nacherfassen
        import uebernehmen as hs
        import vault_paths as vp
        import nachbereiten
        importlib.reload(nacherfassen)
        importlib.reload(nachbereiten)
        ok(str(hs.PROCESSED_LOG).startswith(str(d)) and str(nachbereiten.UNDO_DIR).startswith(str(d)),
           "Pfade zeigen nicht in den Test-Vault")
        mdir = d / "active-meetings" / "2026" / "09"
        mdir.mkdir(parents=True)
        note = mdir / "2026-09-22 - checkin - Demo.md"
        note.write_text("---\ntype: meeting\ntitle: Demo\ndate: '2026-09-22'\nthemen: [demo]\n"
                        "status: vorbereitet\n---\n# Demo\n\n## Vorbereitung\n\nx\n\n"
                        "## Meine Notizen\n\n<!-- Mitschrift -->\n\n## Entscheidungen\n\n"
                        "## Actions\n\n## Verweise\n", encoding="utf-8", newline="\n")
        r = nacherfassen.append_notes(note, "Englisch als Arbeitssprache.\r\nAnne liefert die Liste.",
                                 today="2026-09-27")
        t = note.read_text(encoding="utf-8")
        ok(r["ok"] and "Englisch als Arbeitssprache.\nAnne liefert die Liste.\n\n## Entscheidungen"
           in t and "Nachgetragen" not in t, t)
        nacherfassen.append_notes(note, "Noch etwas.", today="2026-09-27")
        ok("**Nachgetragen am 27.09.2026:**\n\nNoch etwas.\n\n## Entscheidungen"
           in note.read_text(encoding="utf-8"), "Kennzeichnung fehlt")
        ok(nacherfassen.set_entfallen(note, True, "krank")["ok"], "entfallen")
        fm = vp.read_frontmatter(note)
        eq((fm.get("status"), fm.get("entfallen_grund")), ("entfallen", "krank"), "entfallen:")
        nacherfassen.append_notes(note, "Doch da gewesen.", today="2026-09-27")
        fm = vp.read_frontmatter(note)
        eq((fm.get("status"), fm.get("entfallen_grund")), ("vorbereitet", None),
           "Notizen heben 'entfallen' auf:")
        # Ueberspringen (privat, gesellig): skip_meeting - wird nie nachbereitet
        nacherfassen.set_skip(note, True)
        ok(vp.read_frontmatter(note).get("skip_meeting") is True, "skip_meeting fehlt")
        ok(note not in list(nachbereiten.iter_notes()), "uebersprungener Termin wird nachbereitet")
        nacherfassen.set_skip(note, False)
        ok("skip_meeting" not in vp.read_frontmatter(note), "skip_meeting nicht entfernt")

        topic = d / "entities" / "projects" / "demo.md"
        topic.write_text("---\ntype: project\n---\n# Demo\n\n## Event Log\n- [2026-09-01] [STATUS] Alt\n",
                         encoding="utf-8", newline="\n")
        before = note.read_text(encoding="utf-8")
        nachbereiten.save_undo(note, before)
        note.write_text(before.replace("## Entscheidungen\n", "## Entscheidungen\n- [E] Englisch — ?\n"),
                        encoding="utf-8", newline="\n")
        vp.update_frontmatter(note, {"status": "nachbereitet"})
        nachbereiten.finish_undo(note)
        line = f"- [2026-09-22] [DECISION] Englisch (→ [[{note.stem}]])"
        topic.write_text(topic.read_text(encoding="utf-8").replace("## Event Log\n", f"## Event Log\n{line}\n"),
                         encoding="utf-8", newline="\n")
        eq(nachbereiten.linked_log_lines(note.stem), {"demo": [line]}, "Log-Zeilen mit Link:")
        hs.mark_applied("abc123")
        nachbereiten.record_sync(note, "abc123", {"demo": [line]})
        note.write_text(note.read_text(encoding="utf-8") + "\nNachtrag\n", encoding="utf-8", newline="\n")
        r = nachbereiten.undo(note)
        ok(not r["ok"] and r.get("geaendert"), r)
        r = nachbereiten.undo(note, force=True)
        ok(r["ok"] and r["log_entfernt"] == {"demo": 1}, r)
        eq(note.read_text(encoding="utf-8"), before, "Notiz nicht wie davor:")
        t = topic.read_text(encoding="utf-8")
        ok(line not in t and "[STATUS] Alt" in t, t)
        ok(not hs.already_applied("abc123"), "Doppelt-Schutz nicht entfernt")
        ok(not nachbereiten.undo(note)["ok"], "zweites Rueckgaengig ohne Sicherung")
    finally:
        restore_vault()


def t_tasks_complete_only_the_expected_line():
    """Abhaken aus der Seitenleiste: [x] und ✅ vor der Quelle; hat sich die Zeile
    verschoben oder geaendert, wird nichts geschrieben; Erledigtes bleibt erledigt."""
    import aufgaben as tk
    d = Path(tempfile.mkdtemp(prefix="donetest-"))
    try:
        p = d / "t.md"
        p.write_text("## Offene Punkte\n"
                     "- [ ] Angebot pruefen — [[anna|Anna]] 📅 2026-10-01 ➕ 2026-09-14 (→ [[q1]])\n"
                     "- [x] Schon da ➕ 2026-09-01 ✅ 2026-09-10\n", encoding="utf-8", newline="\n")
        eq(tk.complete(p, 1, "Anderer Text")["ok"], False, "fremde Zeile abgehakt:")
        eq(tk.complete(p, 9, "Angebot pruefen")["ok"], False, "Zeile ausserhalb:")
        r = tk.complete(p, 1, "angebot pruefen!", today="2026-09-28")   # key: ohne Satzzeichen/Gross-klein
        ok(r["ok"], r)
        eq(p.read_text(encoding="utf-8").split("\n")[1],
           "- [x] Angebot pruefen — [[anna|Anna]] 📅 2026-10-01 ➕ 2026-09-14 ✅ 2026-09-28 (→ [[q1]])",
           "abgehakt:")
        eq(tk.complete(p, 2, "Schon da")["aktion"], "schon erledigt", "zweimal:")
        eq(tk.complete(p, 0, None)["ok"], False, "Ueberschrift abgehakt:")
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def t_themen_rules_series_title_and_recompute():
    """Termin -> Thema: automatisch nur Sicheres (Hand > Reihe > Name im Titel, auch Namensteile,
    Zusatz in Klammern, Abkuerzung, zusammengeschrieben; mehrere Themen). Generische Schlagwoerter
    (it, operations, support) ordnen nicht zu. Fuer die Reihe bestaetigt = Forum, der naechste
    Termin erbt die Themen; Neuberechnen korrigiert automatische Zuordnungen und laesst
    Hand-Zuordnungen (`themen_von_hand`) stehen."""
    d = temp_vault()
    try:
        import themen as th
        import vault_paths as vp
        import vorbereiten
        importlib.reload(th)
        P = d / "entities" / "projects"
        for slug, fm in (("fuhrpark-management", "name: Fuhrpark Management (Bereich)"),
                         ("taxonomie-und-domain-atlas", "title: Taxonomie und Domain Atlas"),
                         ("tl-betrieb", "title: TL Betrieb\nkeywords: [it, operations, support]"),
                         ("produkt-esb", "name: EDI/ESB-Plattform (Produkt)"),
                         ("bxa", "title: BXA"), ("it-management", "title: IT Management")):
            (P / f"{slug}.md").write_text(f"---\ntype: project\n{fm}\n---\n# {slug}\n",
                                          encoding="utf-8", newline="\n")
        projects, aliases = vorbereiten.load_projects(), vp.alias_map()

        def res(title, fm=None, key=None):
            return th.resolve(title, fm or {}, key or "x", projects, aliases)[0]
        eq(res("Fuhrpark Mgmt Checkin"), ["fuhrpark-management"], "Abkuerzung:")
        eq(res("Review FuhrparkManagement"), ["fuhrpark-management"], "zusammengeschrieben:")
        eq(res("Domain Atlas - CrossDock"), ["taxonomie-und-domain-atlas"], "Namensteil:")
        eq(sorted(res("Checkin EDI / BXA")), ["bxa", "produkt-esb"], "zwei Themen, Klammer-Zusatz:")
        eq(res("Operative IT Support weekly"), [], "generische Schlagwoerter ordnen zu:")
        eq(res("Egal", {"themen_von_hand": True, "themen": ["bxa"]}), ["bxa"], "Hand vor Titel:")

        mdir = d / "active-meetings" / "2026" / "09"
        mdir.mkdir(parents=True)
        note = mdir / "2026-09-28 - checkin - Jourfix Anna.md"
        note.write_text("---\ntype: meeting\ntitle: 'Jourfix: Anna'\ndate: '2026-09-28'\n"
                        "meeting_type: jourfix\n---\n# J\n", encoding="utf-8", newline="\n")
        key = vp.read_frontmatter(note).get("series") or th.ag.series_key("Jourfix: Anna")
        r = th.assign_note(note, ["bxa", "unbekannt", "tl-betrieb"], series=True)
        eq(r["themen"], ["bxa", "tl-betrieb"], "gesetzt (unbekanntes Thema fliegt raus):")
        fm = vp.read_frontmatter(note)
        eq((fm.get("themen"), fm.get("themen_von_hand"), fm.get("project")), (["bxa", "tl-betrieb"], True, None), "Notiz:")
        eq(th.series_topics(key), ["bxa", "tl-betrieb"], "Reihe (Forum):")
        ok((d / "entities" / "forums" / f"{key}.md").is_file(), "Forum nicht angelegt")
        eq(res("Jourfix: Anna", {}, key), ["bxa", "tl-betrieb"], "naechster Termin erbt die Reihe:")
        th.assign_series(key, [], title="Jourfix: Anna")
        ok(th.series_without_topic(key) and res("Jourfix: Anna BXA", {}, key) == [], "kein Thema fuer die Reihe")

        stale = mdir / "2026-09-22 - checkin - Operative IT Mgmt Meeting.md"
        stale.write_text("---\ntype: meeting\ntitle: Operative IT Mgmt Meeting\ndate: '2026-09-22'\n"
                         "themen: [tl-betrieb]\n---\n# O\n", encoding="utf-8", newline="\n")
        changes = th.recompute(apply=True)
        eq([(c["alt"], c["neu"]) for c in changes], [(["tl-betrieb"], ["it-management"])],
           "Neuberechnung:")
        eq(vp.read_frontmatter(stale).get("themen"), ["it-management"], "angewandt:")
        eq(vp.read_frontmatter(note).get("themen"), ["bxa", "tl-betrieb"], "Hand-Zuordnung angefasst:")
        sug = th.suggest("Operative IT Mgmt Meeting", {}, "x", projects, aliases)
        ok(sug and sug[0]["slug"] == "it-management" and "im Titel" in sug[0]["gruende"][0], sug)
    finally:
        restore_vault()


def t_beteiligte_from_tasks_meetings_and_log():
    """Beteiligte je Thema aus Belegen der letzten 90 Tage: Aufgaben (offen zaehlt
    mehr), Termine zum Thema, Nennungen im Log (Link, @kuerzel, voller Name - nie der
    Vorname allein). Ich zaehle nicht; zu wenig Belege = nicht beteiligt."""
    d = temp_vault()
    try:
        import beteiligte as bt
        importlib.reload(bt)
        (d / ".2ndbrain" / "local.config.json").write_text('{"ich": "ich-selbst"}', encoding="utf-8",
                                                          newline="\n")
        people = d / "entities" / "people"
        for slug, name in (("anna-berg", "Anna Berg"), ("tom-riebe", "Tom Riebe"),
                           ("ich-selbst", "Ich Selbst"), ("lisa-kurz", "Lisa Kurz")):
            (people / f"{slug}.md").write_text(f"---\ntype: person\nname: {name}\n---\n",
                                                encoding="utf-8", newline="\n")
        (d / "entities" / "projects" / "demo.md").write_text(
            "---\ntype: project\ntitle: Demo\n---\n# Demo\n\n## Offene Punkte\n"
            "- [ ] Angebot pruefen — [[anna-berg|Anna Berg]] ➕ 2026-09-20\n"
            "- [ ] Plan machen — [[ich-selbst|Ich Selbst]] ➕ 2026-09-20\n\n## Event Log\n"
            "- [2026-09-21] [DECISION] Tom Riebe uebernimmt den Rollout\n"
            "- [2026-09-10] [STATUS] Abstimmung mit @tom-riebe und Anna\n"
            "- [2026-09-05] [STATUS] Lisa hat angerufen\n"
            "- [2026-01-05] [STATUS] Lisa Kurz war dabei (zu alt)\n", encoding="utf-8", newline="\n")
        m = d / "active-meetings" / "2026" / "09"
        m.mkdir(parents=True)
        (m / "2026-09-22 - checkin - Demo.md").write_text(
            "---\ntype: meeting\ntitle: Demo\ndate: '2026-09-22'\nthemen: [demo]\n"
            "key_persons: [Tom Riebe, Ich Selbst]\n---\n", encoding="utf-8", newline="\n")
        got = dict(bt.compute(date(2026, 9, 27)).get("demo", []))
        eq(sorted(got), ["anna-berg", "tom-riebe"], "Beteiligte:")
        ok(got["anna-berg"] >= 4.5 and got["tom-riebe"] >= 4.5, got)   # Aufgabe 3x1.5 / Log+Termin
        eq(bt.links([("anna-berg", 4.5)]), ["[[anna-berg|Anna Berg]]"], "Links:")
    finally:
        restore_vault()


def t_jourfix_person_resolution_block_and_settle():
    """Jourfix als Personen-Termin: das Gegenueber wird nie geraten (zwei Personen mit demselben
    Vornamen -> keine); ein eindeutiger Vorname oder eine fuer die Reihe bestaetigte Person -> ja.
    Die Vorbereitung legt Zusagen und Altbestand der Person vor; nach der Nachbereitung wandern NUR
    ihre Altbestand-Punkte in die Liste, der Rest bleibt fuer andere Termine."""
    d = temp_vault()
    try:
        import altbestand as ab
        import aufgaben as tk
        import themen as th
        import vault_paths as vp
        importlib.reload(th)
        importlib.reload(ab)
        (d / ".2ndbrain" / "local.config.json").write_text('{"ich": "ich-selbst"}', encoding="utf-8",
                                                          newline="\n")
        people = d / "entities" / "people"
        for slug, name in (("kuno-alpha", "Kuno Alpha"), ("kuno-beta", "Kuno Beta"),
                           ("ich-selbst", "Ich Selbst"), ("tom-unik", "Tom Unik")):
            (people / f"{slug}.md").write_text(f"---\ntype: person\nname: {name}\n---\n",
                                                encoding="utf-8", newline="\n")
        aliases = vp.alias_map()
        eq(th.resolve_persons("Jourfix: Kuno/Ich", {}, "jf-m", aliases, "ich-selbst")[0], [],
           "zwei Kunos - geraten:")
        eq(th.resolve_persons("Jourfix Tom", {}, "jf-t", aliases, "ich-selbst")[0], ["tom-unik"],
           "eindeutiger Vorname:")
        th.assign_persons("jf-m", ["kuno-alpha"], title="Jourfix: Kuno/Ich", meeting_type="oneonone")
        eq(th.resolve_persons("Jourfix: Kuno/Ich", {}, "jf-m", aliases, "ich-selbst"),
           (["kuno-alpha"], "für die Reihe bestätigt"), "Reihe:")

        topic = d / "entities" / "projects" / "demo.md"
        base = "---\ntype: project\ntitle: Demo\n---\n# Demo\n\n## Offene Punkte\n\n## Event Log\n"
        text, _ = _mit_altbestand(base, [
            tk.Task(status=" ", text="Kunos Punkt", owner="kuno-alpha", created="2026-08-01"),
            tk.Task(status=" ", text="Toms Punkt", owner="tom-unik", created="2026-08-01")],
            day="2026-09-27")
        topic.write_text(text, encoding="utf-8", newline="\n")
        block = "\n".join(ab.person_block("kuno-alpha", "Kuno Alpha", [("demo", "Demo", "yellow")]))
        ok("### Mit Kuno Alpha" in block and "🟡 [[demo|Demo]]" in block
           and 'contains(text, "— [[kuno-alpha")' in block
           and "<!-- altbestand-person:kuno-alpha -->" in block and "Altbestand bei Kuno (1)" in block, block)

        m = d / "active-meetings" / "2026" / "09"
        m.mkdir(parents=True)
        note = m / "2026-09-25 - oneonone - Jourfix.md"
        note.write_text(f"---\ntype: meeting\ntitle: Jourfix\ndate: '2026-09-25'\nstatus: nachbereitet\n"
                        f"wrapped_at: '2026-09-25T18:00:00'\n---\n# J\n\n## Vorbereitung\n\n{block}\n\n"
                        "## Meine Notizen\n\nx\n", encoding="utf-8", newline="\n")
        r = ab.settle(date(2026, 9, 27))
        eq([x["slug"] for x in r], ["person:kuno-alpha"], "ausgewertet:")
        after = topic.read_text(encoding="utf-8")
        before_sub, _, sub = after.partition(tk.ALTBESTAND_HEADING)
        ok("Kunos Punkt" in before_sub and "Toms Punkt" in sub, after)
        ok("[STATUS] Altbestand von Kuno Alpha geklärt: 1 weiter offen, 0 erledigt, 0 verworfen"
           " (→ [[2026-09-25 - oneonone - Jourfix]])" in after, after)
        n = note.read_text(encoding="utf-8")
        ok("**Altbestand bei Kuno Alpha geklärt:**" in n and "- ⏳ Kunos Punkt · [[demo]]" in n
           and "### Mit Kuno Alpha" in n and "```dataview" in n, n)     # Zusagen bleiben live
        eq(ab.settle(date(2026, 9, 27)), [], "zweiter Lauf:")
    finally:
        restore_vault()


def t_writes_are_lf_on_every_platform():
    """Unter Windows uebersetzt Python beim Schreiben '\\n' in '\\r\\n' - der Vault (auch auf
    anderen Rechnern synchronisiert) bekaeme gemischte Zeilenenden, und jede Datei erschiene im Diff
    komplett geaendert. Deshalb erzwingt jeder Schreibaufruf LF (newline=...) - hier per AST fuer
    alle Engine-Module geprueft."""
    import ast
    missing = []
    for f in sorted(_TOOLS.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or any(k.arg == "newline" for k in node.keywords):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "write_text":
                missing.append(f"{f.name}:{node.lineno}")
            elif isinstance(node.func, ast.Name) and node.func.id == "open":
                mode = node.args[1].value if len(node.args) > 1 and isinstance(
                    node.args[1], ast.Constant) else ""
                if isinstance(mode, str) and ("w" in mode or "a" in mode) and "b" not in mode:
                    missing.append(f"{f.name}:{node.lineno}")
    eq(missing, [], "Schreibaufrufe ohne newline=:")
    d = temp_vault()
    try:
        import vault_paths as vp
        f = d / "x.md"
        f.write_text("---\ntype: project\n---\n# X\n", encoding="utf-8", newline="\n")
        vp.update_frontmatter(f, {"health": "green"})
        ok(b"\r\n" not in f.read_bytes(), "update_frontmatter schreibt CRLF")
    finally:
        restore_vault()


# ─────────────────────────────────────────── externe Quellen

def t_selfcheck_dead_module_not_saved_by_own_docstring():
    """Selbsttest, toter Code: ein Modul, das sich nur im eigenen Hilfetext nennt ("python x.py"),
    gilt nicht als benutzt - nur ein anderer Aufrufer zaehlt, sonst bleibt toter Code liegen.
    Ein Modul, das ein Befehl der Befehlsliste startet, ist verdrahtet."""
    d = temp_vault()
    try:
        nl = chr(10)
        t = d / "engine"
        t.mkdir()
        (t / "befehle.py").write_text("import genutzt" + nl + 'GRUPPEN = [("X", [("start", "gestartet", [], "Hilfe")])]'
                                      + nl, encoding="utf-8", newline=nl)
        (t / "genutzt.py").write_text('"""genutzt."""' + nl, encoding="utf-8", newline=nl)
        (t / "gestartet.py").write_text('"""nur ueber den Befehl."""' + nl, encoding="utf-8", newline=nl)
        (t / "selbst.py").write_text('"""Aufruf: python selbst.py --json"""' + nl, encoding="utf-8", newline=nl)
        (t / "doku.md").write_text("", encoding="utf-8", newline=nl)
        import selbsttest
        importlib.reload(selbsttest)
        selbsttest.vp.ENGINE_DIR = t            # restore_vault laedt vault_paths neu
        dead = selbsttest.check_dead_modules()
        eq([x.split(":")[0] for x in dead], ["selbst.py"], "tot:")
    finally:
        restore_vault()


def t_glossary_examples_from_vault_not_code():
    """Beispiele im Glossar-Prompt kommen aus dem, was der Vault bestaetigt - Systeme der
    Systemuebersicht, Teams/Reihen/Firmen, Atlas-Fachobjekte, die meistgenannten zuerst. Eine
    Themen-Seite ist kein System, ein Name in zwei Pools (Team wie sein Produkt) ist mehrdeutig,
    ein ausgeschlossener Begriff (Stichprobe) erscheint nie als Beispiel. Feste Beispiele aus der
    Konfiguration gehen vor; "auto" heisst ableiten."""
    d = temp_vault()
    try:
        nl = chr(10)
        P, S, T, G = (d / "entities" / c for c in ("projects", "systems", "teams", "glossary"))
        G.mkdir(parents=True, exist_ok=True)
        (P / "nord.md").write_text("---\ntype: project\ntitle: Nord\nkind: area\n---\n# Nord\n", encoding="utf-8", newline=nl)
        for slug, name in (("altsys", "Altsys"), ("tarom", "Tarom"), ("nord", "Nord"), ("dxq", "DXQ")):
            (S / f"{slug}.md").write_text(f"---\ntype: system\nname: {name}\nbereich: '[[nord]]'\n---\n# {name}\n",
                                          encoding="utf-8", newline=nl)
        for slug, name in (("team-lager", "Lagerteam"), ("dxq-team", "DXQ")):
            (T / f"{slug}.md").write_text(f"---\ntype: team\nname: {name}\n---\n", encoding="utf-8", newline=nl)
        (G / "abholauftrag.md").write_text("---\ntype: glossary_term\nterm: Abholauftrag\nstatus: atlas\n---\n",
                                          encoding="utf-8", newline=nl)
        m = d / "active-meetings" / "2026" / "09"
        m.mkdir(parents=True)
        for i in range(3):
            (m / f"2026-09-1{i} - checkin - T{i}.md").write_text(
                "---\ntype: meeting\n---\nAltsys und Tarom, dazu DXQ und Nord. Lagerteam prueft den Abholauftrag."
                + (" Altsys noch einmal." if i else "") + nl, encoding="utf-8", newline=nl)
        import glossar as gb
        importlib.reload(gb)
        docs = gb.corpus()
        ex = gb.derived_examples(docs)
        eq(ex, {"system": "Altsys, Tarom", "organisation": "Lagerteam", "fachbegriff": "Abholauftrag"},
           "abgeleitet (Themen-Seite 'Nord' kein System, 'DXQ' mehrdeutig):")
        eq(gb.derived_examples(docs, exclude={"altsys"})["system"], "Tarom", "Stichprobe nie als Beispiel:")
        ok("(z.B. Altsys, Tarom)" in gb.build_prompt(ex) and "(z.B." not in gb.build_prompt({}), "Prompt")
        eq(gb.configured_examples(), None, "ohne Konfiguration: ableiten")
        (d / ".2ndbrain" / "local.config.json").write_text(
            json.dumps({"glossar": {"beispiele": "auto"}}), encoding="utf-8", newline=nl)
        eq(gb.configured_examples(), None, "auto: ableiten")
        (d / ".2ndbrain" / "local.config.json").write_text(
            json.dumps({"glossar": {"beispiele": {"system": "X1"}}}), encoding="utf-8", newline=nl)
        eq(gb.configured_examples(), {"system": "X1"}, "fest vorgegeben:")
    finally:
        restore_vault()


def t_external_path_env_config_and_autodetect():
    """Externe Ordner (Domain Atlas, LikeC4-Modell) haben keinen festen Pfad: Umgebungsvariable >
    local.config.json > Auto-Erkennung unter ~/code und ~/, sonst None - ein fester Pfad passt nur
    auf einem Rechner, anderswo liefe die Aufloesung still nur gegen den Vault."""
    d = temp_vault()
    saved = {k: os.environ.get(k) for k in ("VAULT_DOMAIN_ATLAS", "VAULT_LIKEC4_MODEL", "HOME", "USERPROFILE")}
    try:
        import vault_paths as vp
        home = d / "home"
        (home / "code" / "domain-atlas").mkdir(parents=True)
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
        os.environ.pop("VAULT_DOMAIN_ATLAS", None)
        os.environ.pop("VAULT_LIKEC4_MODEL", None)
        eq(vp.external_path("domain_atlas"), home / "code" / "domain-atlas", "Auto-Erkennung:")
        eq(vp.external_path("likec4_model"), None, "nichts gefunden muss None sein:")
        vp.LOCAL_CONFIG_FILE.write_text(
            json.dumps({"paths": {"domain_atlas": str(d / "cfg")}}), encoding="utf-8", newline="\n")
        eq(vp.external_path("domain_atlas"), d / "cfg", "local.config.json:")
        os.environ["VAULT_DOMAIN_ATLAS"] = str(d / "env")
        eq(vp.external_path("domain_atlas"), d / "env", "Umgebungsvariable:")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        restore_vault()






def t_prep_window_until_next_workday():
    """Notizen entstehen heute bis zum naechsten Werktag (freitags bis Montag),
    mit Vorlauf frueher - eine Regel fuer Anlegen und Aufraeumen."""
    import vorbereiten
    D = date.fromisoformat
    eq([vorbereiten.window_days(D(s)) for s in ("2026-09-27", "2026-09-28", "2026-10-02", "2026-10-03")],
       [2, 2, 4, 3], "Fenster So/Mo/Fr/Sa:")
    ok(vorbereiten.due_for_prep(D("2026-10-05"), 1, D("2026-10-02")), "Montag am Freitag fehlt")
    ok(not vorbereiten.due_for_prep(D("2026-10-06"), 1, D("2026-10-02")), "Dienstag schon am Freitag")
    ok(vorbereiten.due_for_prep(D("2026-10-01"), 3, D("2026-09-28")), "Vorlauf 3 Tage greift nicht")
    ok(not vorbereiten.due_for_prep(D("2026-10-02"), 3, D("2026-09-28")), "Vorlauf zu frueh")
    ok(not vorbereiten.due_for_prep(D("2026-09-27"), 1, D("2026-09-28")), "Vergangenes faellig")
    eq(vorbereiten.prep_start(D("2026-10-20"), 3), D("2026-10-16"), "Review Di, Beginn Sa -> Fr:")
    for today in (D("2026-09-26"), D("2026-09-28"), D("2026-10-02")):   # Sa, Mo, Fr
        days = {today + timedelta(days=i) for i in range(vorbereiten.window_days(today))}
        eq({e for e in (today + timedelta(days=i) for i in range(10)) if vorbereiten.due_for_prep(e, 1, today)},
           days, f"Fenster = Regel mit 1 Tag Vorlauf ({today}):")


def t_mail_already_processed_is_not_imported_twice():
    """Eine Mail, deren Notiz schon im Archiv liegt, wird nicht noch einmal eingelesen: keine neue
    Notiz, die .eml liegt im Papierkorb; eine neue Mail schon. Erkannt an der Message-ID - mit oder
    ohne Anfuehrungszeichen (eingearbeitete Notizen schreibt YAML neu) -, bei aelteren Mail-Notizen
    ohne Message-ID am Zeitstempel (Date-Header)."""
    d = temp_vault()
    try:
        import mails as ie
        importlib.reload(ie)
        arch = d / "archive" / "meetings" / "2026-09"
        arch.mkdir(parents=True)
        (arch / "2026-09-22-angebot.md").write_text(
            '---\ntype: email-thread\nmessage_id: "<a1@example.com>"\n---\n# Angebot\n',
            encoding="utf-8", newline="\n")
        (arch / "2026-09-21-termin.md").write_text(
            "---\ntype: email-thread\nmessage_id: <c3@example.com>\n---\n# Termin\n",
            encoding="utf-8", newline="\n")
        (arch / "2026-09-20-rechnung.md").write_text(
            "---\ntype: email-thread\ntimestamp: Sun, 20 Sep 2026 09:15:00 +0200\n---\n# Rechnung\n",
            encoding="utf-8", newline="\n")
        inbox = d / "inbox"
        inbox.mkdir(exist_ok=True)

        def eml(name, mid, subject, datum="Tue, 22 Sep 2026 10:00:00 +0200"):
            p = inbox / name
            p.write_bytes((f"From: Anna Beispiel <anna@example.com>\r\nTo: ich@example.com\r\n"
                           f"Subject: {subject}\r\nDate: {datum}\r\n"
                           f"Message-ID: {mid}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
                           "Hallo, anbei das Angebot.\r\n").encode("utf-8"))
            return p
        alt = eml("alt.eml", "<a1@example.com>", "Angebot")
        ohne = eml("ohne.eml", "<c3@example.com>", "Termin")
        frueher = eml("frueher.eml", "<d4@example.com>", "Rechnung", "Sun, 20 Sep 2026 09:15:00 +0200")
        neu = eml("neu.eml", "<b2@example.com>", "Rueckfrage")
        for p in (alt, ohne, frueher):
            eq(ie.process_eml(str(p), str(inbox), keep_source=True), None, f"doppelte Mail eingelesen: {p.name}")
            ok(not p.exists() and (d / ".trash" / "doppelte-mails" / p.name).is_file(),
               f"doppelte Mail nicht im Papierkorb: {p.name}")
        out = ie.process_eml(str(neu), str(inbox), keep_source=True)
        ok(out is not None and Path(out).is_file(), "neue Mail nicht eingelesen")
        eq(sorted(p.name for p in inbox.glob("*.md")), [Path(out).name], "falsche Notizen im Eingang:")
    finally:
        restore_vault()


def t_clarify_checked_cards_are_applied_and_archived():
    """Rueckfragen: ein Haken genuegt. Die Person kommt in die VORHANDENE Aufgabe
    (kein zweites Einspielen), ein frei eingetragener Name legt die Person an und
    fuehrt die Vornamen-Datei zusammen, "Unklar" wird abgeschlossen; Erledigtes
    wandert ins Archiv, ungehakte Karten bleiben."""
    d = temp_vault()
    try:
        import rueckfragen as ce
        importlib.reload(ce)
        people = d / "entities" / "people"
        for slug, name in (("anna-berg", "Anna Berg"), ("anna-bauer", "Anna Bauer")):
            (people / f"{slug}.md").write_text(f"---\ntype: person\nname: {name}\n---\n", encoding="utf-8", newline="\n")
        (people / "tom.md").write_text("---\ntype: person\nname: Tom\n---\n", encoding="utf-8", newline="\n")
        topic = d / "entities" / "projects" / "demo.md"
        topic.write_text("---\ntype: project\ntitle: Demo\n---\n# Demo\n\n## Offene Punkte\n"
                         "- [ ] Angebot pruefen — Anna (?) ➕ 2026-09-20\n\n## Event Log\n",
                         encoding="utf-8", newline="\n")
        pend = d / ".2ndbrain" / "daten" / ".pending"
        pend.mkdir(parents=True)
        (pend / "CLARIFY-1.json").write_text(json.dumps({"kind": "unknown_person", "payload": {"action_items": [
            {"owner": "__RESOLVE__", "project": "demo", "task": "Angebot prüfen", "deadline": "TBD"}]}}),
            encoding="utf-8", newline="\n")
        (pend / "CLARIFY-2.json").write_text(json.dumps({"kind": "ambiguous_person_file", "raw_slug": "tom",
                                                          "candidates": []}), encoding="utf-8", newline="\n")
        (d / "04_Clarifications.md").write_text(
            "# Rückfragen\n\n---\n\n"
            "### ❓ [CLARIFY-1] Mehrdeutige Person 'Anna'\n\n- [ ] A) Anna Bauer (anna-bauer)\n- [x] B) Anna Berg (anna-berg)\n\n---\n"
            "### ❓ [CLARIFY-2] Wer ist 'Tom'?\n\n- [ ] A) Unklar – Datei bleibt\n- [x] Tom Naumann\n\n---\n"
            "### ❓ [CLARIFY-3] Wer ist 'Ute'?\n\n- [x] B) Unklar – Datei bleibt\n\n---\n"
            "### ❓ [CLARIFY-4] Wer ist 'Eva'?\n\n- [ ] A) Unklar – Datei bleibt\n\n---\n",
            encoding="utf-8", newline="\n")
        r = {x["id"]: x for x in ce.apply_checked()}
        ok(all(r[k]["ok"] for k in ("CLARIFY-1", "CLARIFY-2", "CLARIFY-3")) and "CLARIFY-4" not in r, r)
        text = topic.read_text(encoding="utf-8")
        ok("— [[anna-berg|Anna Berg]]" in text and text.count("Angebot pruefen") == 1, text)
        ok((people / "tom-naumann.md").exists() and not (people / "tom.md").exists(), "Tom nicht zusammengefuehrt")
        eq(ce.archive_resolved(), 3, "archiviert:")
        rest = (d / "04_Clarifications.md").read_text(encoding="utf-8")
        ok("CLARIFY-4" in rest and "CLARIFY-1" not in rest and "✅" not in rest, rest)
        ok(not (pend / "CLARIFY-1.json").exists(), "Payload nicht entfernt")
    finally:
        restore_vault()


def t_topic_cards_discard_and_assign():
    """Rueckfragen zu unbekannten Themen: "Verwerfen" legt die aufbewahrten Ereignisse ab,
    "zuordnen" mit [[thema]] in der Zeile spielt sie dort ein; ohne Ziel bleibt die Karte offen."""
    d = temp_vault()
    try:
        import rueckfragen as ce
        importlib.reload(ce)
        topic = d / "entities" / "projects" / "demo.md"
        topic.write_text("---\ntype: project\ntitle: Demo\n---\n# Demo\n\n## Event Log\n", encoding="utf-8", newline="\n")
        pend = d / ".2ndbrain" / "daten" / ".pending"
        pend.mkdir(parents=True)
        for cid in ("CLARIFY-A", "CLARIFY-B", "CLARIFY-C"):
            (pend / f"{cid}.json").write_text(json.dumps({"kind": "unknown_project", "raw_slug": "reihe-x", "payload": {
                "project_updates": [{"slug": "__RESOLVE__", "events": [f"[DECISION] Beschluss {cid[-1]}"]}]}}),
                encoding="utf-8", newline="\n")
        (d / "04_Clarifications.md").write_text(
            "# Rückfragen\n\n---\n\n"
            "### ❓ [CLARIFY-A] Unbekanntes Projekt 'reihe-x'\n\n- [ ] A) Neues Projekt anlegen\n"
            "- [ ] B) Einem bestehenden Projekt zuordnen\n- [x] C) Verwerfen\n\n---\n"
            "### ❓ [CLARIFY-B] Unbekanntes Projekt 'reihe-x'\n\n- [ ] A) Neues Projekt anlegen\n"
            "- [x] B) Einem bestehenden Projekt zuordnen: [[demo]]\n- [ ] C) Verwerfen\n\n---\n"
            "### ❓ [CLARIFY-C] Unbekanntes Projekt 'reihe-x'\n\n- [ ] A) Neues Projekt anlegen\n"
            "- [x] B) Einem bestehenden Projekt zuordnen\n- [ ] C) Verwerfen\n\n---\n",
            encoding="utf-8", newline="\n")
        r = {x["id"]: x for x in ce.apply_checked()}
        ok(r["CLARIFY-A"]["ok"] and r["CLARIFY-B"]["ok"] and not r["CLARIFY-C"]["ok"], r)
        text = topic.read_text(encoding="utf-8")
        ok("Beschluss B" in text and "Beschluss A" not in text and "Beschluss C" not in text, text)
        ok("Ziel fehlt" in r["CLARIFY-C"]["grund"], r["CLARIFY-C"])
        ok(not (pend / "CLARIFY-A.json").exists() and (pend / "CLARIFY-C.json").exists(), "Payloads")
    finally:
        restore_vault()


def t_topic_candidates_only_topics():
    """Die Nachbereitung bietet dem Modell nur Themen an: eine Reihe aus dem Begriffs-Index steht
    fuer ihre Themen (Forum `project`), Unbekanntes faellt weg - sonst ordnet das Modell einer
    Reihe zu und das Einarbeiten macht daraus eine Rueckfrage statt eines Log-Eintrags."""
    d = temp_vault()
    try:
        (d / "entities" / "projects" / "thema-a.md").write_text("---\ntype: project\ntitle: Thema A\n---\n# Thema A\n",
                                                               encoding="utf-8", newline="\n")
        (d / "entities" / "forums" / "reihe-x.md").write_text("---\ntype: forum\nname: Reihe X\nproject: thema-a\n---\n",
                                                             encoding="utf-8", newline="\n")
        import begriffsindex
        import nachbereiten as nb
        importlib.reload(nb)
        alt = begriffsindex.candidate_topics
        begriffsindex.candidate_topics = lambda text, default=None, **kw: ["reihe-x", "unbekannt", "thema-a"]
        try:
            eq([s for s, _ in nb._topic_candidates("Material", "")], ["thema-a"], "Kandidaten:")
        finally:
            begriffsindex.candidate_topics = alt
    finally:
        restore_vault()


def t_atlas_subdomain_to_topic_via_atlas_id():
    """Kanon -> Thema: gleicher Name reicht (sd-linie -> linie); heisst das Thema anders
    ("Rechnung und Zahlung" fuer sd-rechnung), nennt es Subdomaene und Team in `atlas_id:` -
    sonst landen Kontexte wie "Zahlungsabgleich" bei keinem Thema."""
    d = temp_vault()
    try:
        P = d / "entities" / "projects"
        (P / "linie.md").write_text("---\ntype: project\ntitle: Linie\n---\n# Linie\n", encoding="utf-8", newline="\n")
        (P / "rechnung-und-zahlung.md").write_text(
            "---\ntype: project\ntitle: Rechnung und Zahlung\natlas_id:\n- sd-rechnung\n- team-rechnung\n---\n"
            "# Rechnung und Zahlung\n", encoding="utf-8", newline="\n")
        (P / "vertrieb.md").write_text("---\ntype: project\ntitle: Vertrieb\natlas_id: sd-vertrieb\n---\n# Vertrieb\n",
                                       encoding="utf-8", newline="\n")
        import begriffsindex as ti
        importlib.reload(ti)
        k = {"format": "domain-atlas",
             "subdomaenen": [{"id": "sd-linie", "name": "Linie"}, {"id": "sd-rechnung", "name": "Rechnung"},
                             {"id": "sd-vertrieb", "name": "Vertrieb"}, {"id": "sd-lager", "name": "Lager"}],
             "kontexte": [{"id": "ctx-abgleich", "name": "Zahlungsabgleich", "subdomain": "sd-rechnung"},
                          {"id": "ctx-tarife", "name": "Tarifpflege", "subdomain": "sd-vertrieb"},
                          {"id": "ctx-linienfahrt", "name": "Linienfahrt", "subdomain": "sd-linie"},
                          {"id": "ctx-rampe", "name": "Rampe", "subdomain": "sd-lager"}],
             "objekte": [{"id": "obj-gutschrift", "namen": ["Gutschrift"], "kontext": "ctx-abgleich"}],
             "teams": [{"id": "team-rechnung", "name": "Abrechnungsteam"}],
             "ablaeufe": []}
        topic = {e["term"]: e["topic"] for e in ti.atlas_entries(k)}
        eq([topic.get(t) for t in ("Linienfahrt", "Zahlungsabgleich", "Gutschrift", "Abrechnungsteam", "Tarifpflege", "Rampe")],
           ["linie", "rechnung-und-zahlung", "rechnung-und-zahlung", "rechnung-und-zahlung", "vertrieb", None],
           "Thema je Kanon-Begriff:")
    finally:
        restore_vault()


def t_first_name_resolved_via_series():
    """Ein mehrdeutiger Vorname wird ueber die Reihe eindeutig: wer in frueheren Terminen der
    Reihe Punkte hatte (auch im Archiv) oder dort Teilnehmer war, zaehlt zum Kontext. Stehen
    beide Kandidaten in der Reihe, bleibt es eine Rueckfrage."""
    d = temp_vault()
    try:
        import nachbereiten
        importlib.reload(nachbereiten)
        for slug, name in (("otto-kranich", "Otto Kranich"), ("otto-falke", "Otto Falke"),
                           ("lena-reiher", "Lena Reiher")):
            (d / "entities" / "people" / f"{slug}.md").write_text(
                f"---\ntype: person\nname: {name}\n---\n", encoding="utf-8", newline="\n")
        alt = d / "archive" / "meetings" / "2026-09"
        alt.mkdir(parents=True)
        (alt / "2026-09-07 - weekly - Team-Runde.md").write_text(
            "---\ntype: meeting\ntitle: Team-Runde\ndate: '2026-09-07'\nseries: team-runde\n---\n\n## Actions\n\n"
            "- [ ] Liste schicken — [[otto-falke|Otto Falke]] ➕ 2026-09-07\n", encoding="utf-8", newline="\n")
        (d / "active-meetings").mkdir(exist_ok=True)
        heute = d / "active-meetings" / "2026-09-21 - weekly - Team-Runde.md"
        heute.write_text("---\ntype: meeting\ntitle: Team-Runde\ndate: '2026-09-21'\nseries: team-runde\n---\n",
                         encoding="utf-8", newline="\n")
        fm = {"title": "Team-Runde", "date": "2026-09-21", "series": "team-runde"}
        ctx = nachbereiten._person_context(fm, heute)
        eq(nachbereiten._resolve_owner("Otto", ctx), ("otto-falke", None), "Otto ueber die Reihe:")
        # andere Reihe: kein Kontext -> Rueckfrage (Rohname bleibt)
        eq(nachbereiten._resolve_owner("Otto", nachbereiten._person_context(
            {"title": "Anderes", "date": "2026-09-21", "series": "anderes"})), (None, "Otto"), "ohne Reihe:")
        # beide Otto in der Reihe (Teilnehmer des frueheren Termins) -> mehrdeutig
        (alt / "2026-09-14 - weekly - Team-Runde.md").write_text(
            "---\ntype: meeting\ntitle: Team-Runde\ndate: '2026-09-14'\nseries: team-runde\nteilnehmer:\n"
            "- '[[otto-kranich|Otto Kranich]]'\n---\n", encoding="utf-8", newline="\n")
        ctx = nachbereiten._person_context(fm, heute)
        eq(nachbereiten._resolve_owner("Otto", ctx), (None, "Otto"), "beide in der Reihe:")
    finally:
        restore_vault()


def t_intake_first_name_resolved_via_topic_and_source():
    """Einarbeiten aus dem Eingang: ein mehrdeutiger Vorname wird eindeutig, wenn genau ein
    Kandidat im Thema der Aufgabe oder in der Quelle verlinkt ist - sonst Rueckfrage."""
    d = temp_vault()
    try:
        import vault_paths as vp
        import ausgabe_pruefen
        importlib.reload(ausgabe_pruefen)
        for slug, name in (("otto-kranich", "Otto Kranich"), ("otto-falke", "Otto Falke")):
            (vp.PEOPLE_DIR / f"{slug}.md").write_text(
                f"---\ntype: person\nname: {name}\n---\n", encoding="utf-8", newline="\n")
        (vp.PROJECTS_DIR / "project-qrs.md").write_text(
            "---\ntype: project\ntitle: QRS\n---\n# QRS\n\n## Offene Punkte\n\n"
            "- [ ] Angebot pruefen — [[otto-kranich|Otto Kranich]] ➕ 2026-09-01\n", encoding="utf-8", newline="\n")
        (vp.PROJECTS_DIR / "at-schnittstellen-abloesung.md").write_text(
            "---\ntype: project\ntitle: AT\n---\n# AT\n", encoding="utf-8", newline="\n")
        known = _known()
        known["people"] = ["otto-kranich", "otto-falke"]

        def owner(project, context=None):
            p, w, c = ausgabe_pruefen.validate_and_fix(
                {"action_items": [{"owner": "Otto", "project": project, "task": "t"}]}, known, context)
            return (p["action_items"][0]["owner"] if p["action_items"] else None), len(c)
        eq(owner("project-qrs"), ("otto-kranich", 0), "ueber das Thema:")
        eq(owner("at-schnittstellen-abloesung"), (None, 1), "ohne Kontext:")
        eq(owner("at-schnittstellen-abloesung", {"otto-falke"}), ("otto-falke", 0), "ueber die Quelle:")
        eq(owner("project-qrs", {"otto-falke"}), (None, 1), "beide im Kontext:")
    finally:
        restore_vault()


def t_stand_new_topic_without_model():
    """Ein frisch angelegtes Thema (im Log nur der Anlage-Eintrag der Vorlage) bekommt den Leer-Text
    ohne Modell; kommt ein echter Eintrag dazu, schreibt das Modell den Stand."""
    d = temp_vault()
    try:
        import stand
        importlib.reload(stand)
        (d / ".templates").mkdir(exist_ok=True)
        (d / ".templates" / "project.md").write_text(
            "---\ntype: project\n---\n# {{title}}\n\n## Event Log\n- [{{date:YYYY-MM-DD}}] [STATUS] Thema neu\n",
            encoding="utf-8", newline="\n")
        p = d / "entities" / "projects" / "tarifwerk.md"
        p.write_text("---\ntype: project\ntitle: Tarifwerk\n---\n# Tarifwerk\n\n## Event Log\n"
                     "- [2026-09-29] [STATUS] Thema neu\n", encoding="utf-8", newline="\n")
        gerufen = []

        def modell(*a, **kw):
            gerufen.append(1)
            return {"stand": "Neue Tarife gelten ab Januar.", "fremde_eintraege": []}, None
        stand.update_topic(p, [], None, date(2026, 9, 29), modell)
        ok(stand.EMPTY_TEXT in p.read_text(encoding="utf-8") and not gerufen, p.read_text(encoding="utf-8"))
        t = p.read_text(encoding="utf-8").replace(
            "## Event Log\n", "## Event Log\n- [2026-09-30] [DECISION] Neue Tarife ab Januar\n")
        p.write_text(t, encoding="utf-8", newline="\n")
        stand.update_topic(p, [], None, date(2026, 9, 30), modell)
        ok(gerufen, "Modell nicht gefragt, obwohl ein echter Eintrag dazukam")
    finally:
        restore_vault()


def t_protokolle_aus_dem_eingang_zum_termin():
    """Protokolle im Eingang kommen in ihre Termin-Notiz: Teams-Zusammenfassung, Transkript und
    Protokoll je in ihren Abschnitt, mit Vormerkung zum Nachbereiten; eine archivierte Notiz kommt
    zurueck, zu einem Kalendertermin ohne Notiz entsteht sie; die Datei geht nach
    archive/protokolle/. Passen zwei Termine, wird es eine Rueckfrage (die Datei wartet, kein zweites
    Mal gefragt); die Antwort ordnet zu oder gibt die Datei dem Einarbeiten frei. Mails und andere
    Dokumente bleiben unberuehrt."""
    import re
    d = temp_vault()
    try:
        import vault_paths as vp
        import protokolle
        import rueckfragen as ce
        for m in (protokolle, ce):
            importlib.reload(m)
        nl = "\n"

        def notiz(ordner, name, title, tag):
            ordner.mkdir(parents=True, exist_ok=True)
            p = ordner / f"{name}.md"
            p.write_text(f"---\ntype: meeting\ntitle: {title}\ndate: '{tag}'\ntags:\n- meeting\n---\n\n"
                         "## Meine Notizen\n\n## Entscheidungen\n\n## Actions\n", encoding="utf-8", newline=nl)
            return p
        aktiv, archiv = d / "active-meetings", d / "archive" / "meetings" / "2026-09"
        team = notiz(aktiv, "2026-09-21 - weekly - Team-Runde", "Team-Runde", "2026-09-21")
        notiz(archiv, "2026-09-14 - review - Lager Review", "Lager Review", "2026-09-14")
        notiz(aktiv, "2026-09-22 - other - Planung Nord", "Planung Nord", "2026-09-22")
        sued = notiz(aktiv, "2026-09-22 - other - Planung Sued", "Planung Sued", "2026-09-22")
        kal = d / "archive" / "calendar"
        kal.mkdir(parents=True)
        (kal / "events.json").write_text(json.dumps([{"summary": "Budget Klausur", "date_iso": "2026-09-23",
                                                      "time": "10:00", "outlook_uid": "u-1"}]),
                                         encoding="utf-8", newline=nl)
        ein = d / "inbox"
        ein.mkdir(exist_ok=True)
        teams = "Generated by AI. Be sure to check for accuracy.\n\nMeeting notes:\n\n- **Rollout:** Anna verteilt die Liste.\n"
        (ein / "2026-09-21 - Team-Runde.md").write_text(teams, encoding="utf-8", newline=nl)
        (ein / "2026-09-14 - Lager Review.md").write_text(
            "# Lager Review\n\n## Teilnehmer\n- Anna, Otto\n\n## Entscheidungen\n- Regale bleiben\n", encoding="utf-8", newline=nl)
        (ein / "2026-09-22 - Planung.md").write_text(teams, encoding="utf-8", newline=nl)
        (ein / "2026-09-22 - Planung Rueckblick.md").write_text(teams, encoding="utf-8", newline=nl)
        (ein / "Budget Klausur.md").write_text(
            "---\ntype: meeting\ndate: 2026-09-23\nsource_type: \"Transkript\"\ntags: [inbox, document-import]\n---\n"
            "# Budget Klausur\n\n![[.attachments/2026/budget.vtt|budget.vtt]]\n\n## Dokumenten-Inhalt\n"
            "**Anna:** Wir nehmen Variante B.\n", encoding="utf-8", newline=nl)
        (ein / "2026-09-21 - Angebot Regale.md").write_text("Angebot fuer Regale, Preis 500 EUR.\n",
                                                           encoding="utf-8", newline=nl)
        # aeltere Notiz ohne `date:` (nur `timestamp:`), Transkript mit entstelltem Dateinamen als Ueberschrift
        alt8 = d / "archive" / "meetings" / "2026-08"
        alt8.mkdir(parents=True)
        (alt8 / "2026-08-07---sonstiges---monatsrunde.md").write_text(
            "---\ntype: meeting\ntitle: Sonstiges - Monatsrunde\ntimestamp: 2026-08-07 00:00:00+02:00\ntags:\n- meeting\n"
            "---\n\n## Meine Notizen\n", encoding="utf-8", newline=nl)
        (ein / "2026-08-07 - transcript - Monatsrunde.md").write_text(
            "---\ntype: meeting\ndate: 2026-08-07\nsource_type: Transkript\ntags: [inbox, document-import]\n---\n"
            "# 2026 08 07   Transcript   Monatsrunde\n\n## Dokumenten-Inhalt\n**Otto:** Budget steht.\n",
            encoding="utf-8", newline=nl)
        (ein / "2026-09-21 - AW Team-Runde.md").write_text(
            "---\ntype: email-thread\n---\nMeeting notes:\n- weitergeleitet\n", encoding="utf-8", newline=nl)

        r = protokolle.run()
        eq(sorted((x["datei"], x["notiz"], x["art"]) for x in r["zugeordnet"]),
           [("2026-08-07 - transcript - Monatsrunde.md", "2026-08-07---sonstiges---monatsrunde", "transkript"),
            ("2026-09-14 - Lager Review.md", "2026-09-14 - review - Lager Review", "protokoll"),
            ("2026-09-21 - Team-Runde.md", "2026-09-21 - weekly - Team-Runde", "teams"),
            ("Budget Klausur.md", "2026-09-23 - other - Budget Klausur", "transkript")], "zugeordnet:")
        t = team.read_text(encoding="utf-8")
        ok("## Teams-Zusammenfassung" in t and "Anna verteilt die Liste" in t
           and "Quelle: 2026-09-21 - Team-Runde.md" in t and t.index("## Teams-Zusammenfassung") < t.index("## Entscheidungen"), t)
        eq(vp_read(team).get("nachbereiten"), "angefordert", "Vormerkung:")
        lager = aktiv / "2026-09-14 - review - Lager Review.md"
        ok(lager.is_file() and not (archiv / lager.name).exists(), "archivierte Notiz nicht zurueckgeholt")
        ok("## Mitschrift" in lager.read_text(encoding="utf-8") and "#### Teilnehmer" in lager.read_text(encoding="utf-8"),
           lager.read_text(encoding="utf-8"))
        budget = aktiv / "2026-09-23 - other - Budget Klausur.md"
        b = budget.read_text(encoding="utf-8")
        ok("## Transkript" in b and "Variante B" in b and "Dokumenten-Inhalt" not in b and "budget.vtt" not in b, b)
        eq(vp_read(budget).get("outlook_uid"), "u-1", "Notiz zum Kalendertermin:")
        abl = d / "archive" / "protokolle" / "2026-09"
        ok((abl / "2026-09-21 - Team-Runde.md").is_file() and not (ein / "2026-09-21 - Team-Runde.md").exists(), "Ablage")
        eq(vp_read(abl / "2026-09-21 - Team-Runde.md").get("processed"), True, "abgeschlossen:")
        ok((ein / "2026-09-21 - Angebot Regale.md").is_file() and (ein / "2026-09-21 - AW Team-Runde.md").is_file(),
           "Dokument oder Mail angefasst")

        # zwei passende Termine -> je eine Rueckfrage, die Datei wartet; kein zweites Mal gefragt
        eq(len(r["rueckfragen"]), 2, "Rueckfragen:")
        planung = ein / "2026-09-22 - Planung.md"
        fm = vp_read(planung)
        ok(fm.get("deferred") is True and fm.get("protokoll_termin"), fm)
        ok(not protokolle.run()["rueckfragen"], "zweimal gefragt")
        karten = (d / "04_Clarifications.md").read_text(encoding="utf-8")
        ok("[[2026-09-22 - other - Planung Nord]]" in karten and "Kein Termin – normal einarbeiten" in karten, karten)

        # Antworten: B) Sued fuer "Planung", "Kein Termin" fuer den Rueckblick
        cid_p = fm["protokoll_termin"]
        cid_r = vp_read(ein / "2026-09-22 - Planung Rueckblick.md")["protokoll_termin"]
        teile = karten.split("### ")
        for i, teil in enumerate(teile):
            if f"[{cid_p}]" in teil:
                teile[i] = teil.replace("- [ ] B)", "- [x] B)")
            elif f"[{cid_r}]" in teil:
                teile[i] = re.sub(r"- \[ \] ([A-Z]\) Kein Termin)", r"- [x] \1", teil)
        (d / "04_Clarifications.md").write_text("### ".join(teile), encoding="utf-8", newline=nl)
        erg = {x["id"]: x for x in ce.apply_checked()}
        ok(erg[cid_p]["ok"] and erg[cid_r]["ok"], erg)
        ok("Anna verteilt die Liste" in sued.read_text(encoding="utf-8") and not planung.exists(), "Antwort B")
        fr = vp_read(ein / "2026-09-22 - Planung Rueckblick.md")
        eq((fr.get("protokoll"), fr.get("deferred"), fr.get("protokoll_termin")), ("kein_termin", None, None),
           "kein Termin:")
        ok(not protokolle.run()["rueckfragen"], "nach 'kein Termin' erneut gefragt")
        # die zurueckgeholte aeltere Notiz (nur `timestamp:`) kommt nach dem Nachbereiten wieder ins Archiv
        import archivieren as ar
        importlib.reload(ar)
        fm_alt = {"timestamp": "2026-08-07 00:00:00+02:00", "status": "nachbereitet", "nachbereitet_von": "modell",
                  "eingearbeitet": "2026-09-29"}
        eq(ar.grund(fm_alt, "2026-09-29"), ar.ERLEDIGT, "aeltere Notiz ohne date:")
        eq(ar.ziel(Path("x.md"), fm_alt).parent.name, "2026-08", "Monat aus timestamp:")
    finally:
        restore_vault()


def t_glossar_kanon_als_wortschatz():
    """Der Kanon als Wortschatz im Glossar: Subdomaenen, Teams, Kontexte und Fachobjekte ohne eigene
    Seite werden Begriffe (`status: atlas`, Beschreibung als Definition); vorhandene Glossar-Seiten
    bekommen den Kanon-Block dazu, ihr Text bleibt; ein Begriff mit Themen-Seite bekommt keine zweite
    Seite; ein Synonym auch nicht. Der zweite Lauf aendert nichts."""
    d = temp_vault()
    old_env = os.environ.pop("VAULT_DOMAIN_ATLAS", None)
    try:
        nl = "\n"
        (d / "kanon.yaml").write_text(
            "subdomaenen:\n  - {id: lagerwesen, name: Lagerwesen, art: supporting, reife: review}\n"
            "  - {id: zollwesen, name: Zollwesen}\n  - {id: rechnung, name: Rechnung & Zahlung}\n"
            "teams:\n  - {id: team-lager, name: Lagerteam}\n"
            "kontexte:\n  - {id: rampenplanung, name: Rampenplanung, subdomain: lagerwesen, owner: [team-lager],"
            " beschreibung: Plant die Rampen im Lager.}\n"
            "begriffe:\n  - {name: Rampe, kontext: rampenplanung, definition: Tor zum Be- und Entladen.,"
            " synonyme: [Ladetor]}\n", encoding="utf-8", newline=nl)
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps(
            {"kanon": {"format": "einfach", "pfad": "kanon.yaml"}}), encoding="utf-8", newline=nl)
        (d / "entities" / "projects" / "lagerwesen.md").write_text(
            "---\ntype: project\ntitle: Lagerwesen\n---\n# Lagerwesen\n", encoding="utf-8", newline=nl)
        (d / "entities" / "projects" / "rechnung-und-zahlung.md").write_text(       # Thema unter anderem Namen
            "---\ntype: project\ntitle: Rechnung und Zahlung\natlas_id: [rechnung]\n---\n", encoding="utf-8", newline=nl)
        alt = d / "entities" / "glossary" / "zollwesen.md"
        alt.write_text("---\ntype: glossary_term\nterm: Zollwesen\nstatus: candidate\n---\n\n# Zollwesen\n\n"
                       "## Definition (Ubiquitous Language)\n\nEigener Text.\n", encoding="utf-8", newline=nl)
        import kanon
        import glossar
        for m in (kanon, glossar):
            importlib.reload(m)
        k = kanon.lade()
        r = glossar.run(apply=True, llm_call=None)
        G = d / "entities" / "glossary"
        eq(sorted(p.stem for p in G.glob("*.md")), ["lagerteam", "rampe", "rampenplanung", "zollwesen"], "Seiten:")
        ctx = (G / "rampenplanung.md").read_text(encoding="utf-8")
        ok("**Kontext** `rampenplanung` in der Subdomäne Lagerwesen · Owner: Lagerteam · Thema: [[lagerwesen|Lagerwesen]]"
           in ctx and "Plant die Rampen im Lager." in ctx and "status: atlas" in ctx, ctx)
        ok(ctx.index("kanon-auto:start") < ctx.index("## Definition"), "Block nicht unter der Ueberschrift")
        ok("**Team** `team-lager` · zuständig für: Rampenplanung (Subdomäne Lagerwesen)"
           in (G / "lagerteam.md").read_text(encoding="utf-8"), (G / "lagerteam.md").read_text(encoding="utf-8"))
        rampe = (G / "rampe.md").read_text(encoding="utf-8")
        ok("Tor zum Be- und Entladen." in rampe and "Synonyme: Ladetor" in rampe, rampe)
        z = alt.read_text(encoding="utf-8")
        ok("Eigener Text." in z and "**Subdomäne** `zollwesen`" in z and "status: candidate" in z
           and "atlas_id: zollwesen" in z, z)
        ok(r.get("kanon_entity") == 2 and not (G / "ladetor.md").exists()
           and not (G / "rechnung-zahlung.md").exists(), dict(r))
        vorher = {p.name: p.read_text(encoding="utf-8") for p in G.glob("*.md")}
        glossar.run(apply=True, llm_call=None)
        eq({p.name: p.read_text(encoding="utf-8") for p in G.glob("*.md")}, vorher, "zweiter Lauf:")
    finally:
        if old_env is not None:
            os.environ["VAULT_DOMAIN_ATLAS"] = old_env
        restore_vault()


def t_thema_neu_aus_dem_kanon():
    """Steht ein Begriff des Kanons im Termintitel (Subdomaene, auch ueber Kontext oder Fachobjekt),
    zu dem es noch kein Thema gibt, schlaegt die Zuordnung "neu aus dem Kanon" vor. Setzen legt das
    Thema an: Name aus dem Kanon, Bereich, verknuepft (atlas_id), eingeordnet wie die uebrigen
    Subdomaenen-Themen; danach fuehrt der Begriffs-Index den Kontext zum neuen Thema. Mit Thema gibt
    es keinen solchen Vorschlag."""
    d = temp_vault()
    old_env = os.environ.pop("VAULT_DOMAIN_ATLAS", None)
    try:
        nl = "\n"
        (d / "kanon.yaml").write_text(
            "subdomaenen:\n  - {id: lagerwesen, name: Lagerwesen}\n"
            "  - {id: zollwesen, name: Zollwesen, beschreibung: Alles rund um Ein- und Ausfuhr.}\n"
            "kontexte:\n  - {id: zollabfertigung, name: Zollabfertigung, subdomain: zollwesen}\n",
            encoding="utf-8", newline=nl)
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps(
            {"kanon": {"format": "einfach", "pfad": "kanon.yaml"}}), encoding="utf-8", newline=nl)
        P = d / "entities" / "projects"
        (P / "dach.md").write_text("---\ntype: project\ntitle: Dach\n---\n# Dach\n", encoding="utf-8", newline=nl)
        (P / "lagerwesen.md").write_text("---\ntype: project\ntitle: Lagerwesen\nparent: '[[dach]]'\n---\n# Lagerwesen\n",
                                         encoding="utf-8", newline=nl)
        (d / "active-meetings").mkdir(exist_ok=True)
        note = d / "active-meetings" / "2026-09-21 - other - Workshop Zollabfertigung.md"
        note.write_text("---\ntype: meeting\ntitle: Workshop Zollabfertigung\ndate: '2026-09-21'\n---\n",
                        encoding="utf-8", newline=nl)
        import kanon
        import begriffsindex as bi
        import thema_anlegen
        import themen as th
        import vorbereiten
        for m in (kanon, bi, thema_anlegen, th):
            importlib.reload(m)
        bi.save(bi.build())
        projects, aliases = vorbereiten.load_projects(), {}
        vs = th.suggest("Workshop Zollabfertigung", {}, "", projects, aliases)
        neu = [v for v in vs if v["slug"].startswith(th.NEU_AUS_KANON)]
        eq([(v["slug"], v["titel"]) for v in neu], [("neu:zollwesen", "Zollwesen (neu aus dem Kanon)")], "Vorschlag:")
        ok("„Zollabfertigung“ im Titel" in neu[0]["gruende"][0] and neu[0]["score"] >= 0.5, neu)
        ok(not [v for v in th.suggest("Lagerwesen Weekly", {}, "", projects, aliases)
                if v["slug"].startswith(th.NEU_AUS_KANON)], "Vorschlag trotz Thema")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            th.main(["--note", note.relative_to(d).as_posix(), "--set", "neu:zollwesen", "--json"])
        eq(json.loads(out.getvalue()).get("themen"), ["zollwesen"], "gesetzt:")
        fm = vp_read(P / "zollwesen.md")
        eq((fm.get("name"), fm.get("kind"), fm.get("parent"), fm.get("atlas_id")),
           ("Zollwesen (Bereich)", "area", "[[dach]]", ["zollwesen"]), "neues Thema:")
        ok("Alles rund um Ein- und Ausfuhr." in (P / "zollwesen.md").read_text(encoding="utf-8"), "Beschreibung")
        eq(vp_read(note).get("themen"), ["zollwesen"], "Notiz:")
        ok("zollwesen" in bi.candidate_topics("Zollabfertigung im Hafen"), "Index kennt das Thema nicht")
        eq(thema_anlegen.aus_kanon("zollwesen"), "zollwesen", "zweites Mal:")
        eq(thema_anlegen.aus_kanon("gibt-es-nicht"), None, "unbekannt:")
    finally:
        if old_env is not None:
            os.environ["VAULT_DOMAIN_ATLAS"] = old_env
        restore_vault()


def t_kanon_vorschlaege_wortschatz():
    """Der Kanon waechst mit dem Wortschatz der Termine: ein Glossar-Begriff, oft in Terminen des
    Bereichs genannt und im Kanon unbekannt, wird eine Frage - Alias (die Langform kennt der Kanon),
    neuer Fachbegriff oder, bei "…-Team", neues Team. Nicht gefragt: Bekanntes, Seltenes, Begriffe
    ausserhalb des Bereichs, Firmen ohne "Team", Protokoll-Floskeln. "Ja" kommt ins Review-Paket,
    "Nein" wird nicht wieder gefragt."""
    from datetime import date as _date
    d = temp_vault()
    old_env = os.environ.pop("VAULT_DOMAIN_ATLAS", None)
    try:
        nl = "\n"
        (d / "kanon.yaml").write_text(
            "subdomaenen:\n  - {id: zollwesen, name: Zollwesen}\n"
            "teams:\n  - {id: team-lager, name: Lagerteam}\n", encoding="utf-8", newline=nl)
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps(
            {"kanon": {"format": "einfach", "pfad": "kanon.yaml"}, "atlas": {"bereich": "dach"}}),
            encoding="utf-8", newline=nl)
        P = d / "entities" / "projects"
        for slug, parent in (("dach", ""), ("lager", "dach"), ("anderes", "")):
            (P / f"{slug}.md").write_text(f"---\ntype: project\ntitle: {slug.title()}\n"
                                          + (f"parent: '[[{parent}]]'\n" if parent else "") + "---\n",
                                          encoding="utf-8", newline=nl)
        (d / "active-meetings").mkdir(exist_ok=True)
        for name, thema in (("n1", "lager"), ("n2", "lager"), ("n3", "lager"), ("x1", "anderes"),
                            ("x2", "anderes"), ("x3", "anderes")):
            (d / "active-meetings" / f"{name}.md").write_text(
                f"---\ntype: meeting\ntitle: {name}\ndate: '2026-09-21'\nthemen:\n- {thema}\n---\n",
                encoding="utf-8", newline=nl)
        G = d / "entities" / "glossary"
        drinnen, draussen = ["n1.md", "n2.md", "n3.md"], ["x1.md", "x2.md", "x3.md"]
        for slug, term, art, n, quellen, lang in (
                ("zw", "ZW", "abkuerzung", 12, drinnen, "Zollwesen"),
                ("rampenslot", "Rampenslot", "fachbegriff", 9, drinnen, ""),
                ("pack-team", "Pack-Team", "organisation", 10, drinnen, ""),
                ("speditionsfirma-x", "Speditionsfirma X", "organisation", 30, drinnen, ""),
                ("key-insights", "Key insights", "fachbegriff", 20, drinnen, ""),
                ("selten", "Selten", "fachbegriff", 3, drinnen, ""),
                ("aussen", "Aussen", "fachbegriff", 20, draussen, ""),
                ("lagerteam", "Lagerteam", "organisation", 20, drinnen, "")):
            (G / f"{slug}.md").write_text(vp_dump({"type": "glossary_term", "term": term, "status": "candidate",
                                                   "art": art, "occurrences": n, "sources": quellen,
                                                   **({"langform": lang} if lang else {})}),
                                          encoding="utf-8", newline=nl)
        import kanon
        import kanon_vorschlaege as av
        for m in (kanon, av):
            importlib.reload(m)
        qs = av.begriff_questions(kanon.lade())
        eq(sorted((q["_name"], [o["key"] for o in q["optionen"]]) for q in qs),
           [("Pack-Team", ["team:neu", "nein:begriff"]), ("Rampenslot", ["begriff:objekt", "nein:begriff"]),
            ("ZW", ["begriff:alias", "nein:begriff"])], "Fragen:")
        zw = next(q for q in qs if q["_name"] == "ZW")
        ok("Alias von Zollwesen (`zollwesen`)" in zw["optionen"][0]["label"] and "[[n3]]" in "".join(zw["belege"]), zw)
        today = _date(2026, 9, 29)
        r = av.answer(zw["id"], "begriff:alias", today=today, qs=qs)
        ok(r["ok"], r)
        pkg = (d / "reports" / f"atlas-review-{today.isoformat()}.md").read_text(encoding="utf-8")
        ok("Beim Eintrag `zollwesen` unter `aliases:` „ZW“ ergänzen" in pkg, pkg)
        ramp = next(q for q in qs if q["_name"] == "Rampenslot")
        ok(av.answer(ramp["id"], "nein:begriff", today=today, qs=qs)["ok"], "nein")
        offen = {q["_name"] for q in av.begriff_questions(kanon.lade())
                 if q["id"] not in set(av._state().get("verworfen") or []) | set(av._state().get("eingereicht") or {})}
        eq(offen, {"Pack-Team"}, "danach offen:")
    finally:
        if old_env is not None:
            os.environ["VAULT_DOMAIN_ATLAS"] = old_env
        restore_vault()


def vp_dump(fm: dict) -> str:
    import vault_paths as vp
    return vp.dump_frontmatter(fm, "\n# " + str(fm.get("term")) + "\n")


def t_nachbereiten_pruefstufe():
    """Zwei Stufen: das eingestellte Modell entwirft (Prompt mit Termin-Datum), das Pruefmodell
    (`model_pruefung`) gleicht den Entwurf mit dem ganzen Material ab - Abschnitt fuer Abschnitt,
    Antwortgrenze nach Materiallaenge - und sein Ergebnis gilt (`geprueft_von`). Ohne Pruefmodell
    eine Stufe; scheitert die Pruefung oder liefert sie nichts, gilt der Entwurf."""
    d = temp_vault()
    import modell
    import nachbereiten_modell as nm
    alt = (modell.CONFIG_PATH, modell.complete_json)
    try:
        importlib.reload(nm)
        cfg = d / ".2ndbrain" / "llm.config.json"
        modell.CONFIG_PATH = cfg
        aufrufe = []
        antwort = {"pruefen": None}

        def fake(messages, schema, *, max_tokens=1024, retries=None, task="", model=None, timeout=None):
            aufrufe.append({"task": task, "model": model, "max_tokens": max_tokens,
                            "system": messages[0]["content"], "user": messages[-1]["content"]})
            if task == "pruefen":
                if isinstance(antwort["pruefen"], Exception):
                    raise antwort["pruefen"]
                return antwort["pruefen"], []
            return {"entscheidungen": [{"was": "A beschlossen", "wer": "", "datum": "", "thema": ""}],
                    "actions": [{"was": "X erledigen", "wer": "Otto", "bis": "", "thema": ""}],
                    "kernteil": [], "parkplatz": []}, []
        modell.complete_json = fake
        material = "Wir haben A beschlossen. Otto erledigt X. Ausserdem wurde B beschlossen. " * 30
        meta = {"title": "Runde", "date": "2026-09-21", "topics": []}

        cfg.write_text(json.dumps({"url": "http://x", "model": "entwurf-m", "model_pruefung": "pruefer-m"}),
                       encoding="utf-8", newline="\n")
        antwort["pruefen"] = {"entscheidungen": [{"was": "A beschlossen", "wer": "", "datum": "", "thema": ""},
                                                 {"was": "B beschlossen", "wer": "", "datum": "", "thema": ""}],
                              "actions": [{"was": "X erledigen", "wer": "Otto", "bis": "", "thema": ""}],
                              "kernteil": [], "parkplatz": []}
        r = nm.extract(material, {}, meta)
        eq([(a["task"], a["model"]) for a in aufrufe], [("extract", None), ("pruefen", "pruefer-m")], "Aufrufe:")
        ok("Datum: 2026-09-21" in aufrufe[0]["user"], aufrufe[0]["user"][:200])
        # Fristen je Aufgabe: nicht das Datum eines Punkts auf alle Aufgaben verteilen (Befund 29.09.)
        ok(all(nm.FRISTEN_REGEL in a["user"] for a in aufrufe)
           and "fuer genau diese Aufgabe" in aufrufe[1]["system"], "Fristen-Regel fehlt")
        ok("Abschnitt fuer Abschnitt" in aufrufe[1]["system"] and "Entwurf:" in aufrufe[1]["user"]
           and "A beschlossen" in aufrufe[1]["user"] and "Material:" in aufrufe[1]["user"], aufrufe[1]["user"][:300])
        eq(aufrufe[1]["max_tokens"], modell.antwort_tokens(len(material)), "Antwortgrenze:")
        eq(([e["was"] for e in r["entscheidungen"]], r.get("geprueft_von")),
           (["A beschlossen", "B beschlossen"], "pruefer-m"), "Ergebnis der Pruefung:")

        aufrufe.clear()                          # Pruefung scheitert -> Entwurf
        antwort["pruefen"] = modell.LLMUnavailableError("weg")
        r = nm.extract(material, {}, meta)
        eq(([e["was"] for e in r["entscheidungen"]], r.get("geprueft_von")), (["A beschlossen"], None), "gescheitert:")
        aufrufe.clear()                          # Pruefung liefert nichts -> Entwurf
        antwort["pruefen"] = {"entscheidungen": [], "actions": [], "kernteil": [], "parkplatz": []}
        eq(len(nm.extract(material, {}, meta)["entscheidungen"]), 1, "leere Pruefung:")

        aufrufe.clear()                          # ohne Pruefmodell: eine Stufe
        cfg.write_text(json.dumps({"url": "http://x", "model": "entwurf-m"}), encoding="utf-8", newline="\n")
        r = nm.extract(material, {}, meta)
        eq(([a["task"] for a in aufrufe], r.get("geprueft_von")), (["extract"], None), "ohne Pruefmodell:")
    finally:
        modell.CONFIG_PATH, modell.complete_json = alt
        restore_vault()


def t_modell_stuecke_an_wortgrenzen_und_antwortgrenze():
    """Langes Material ohne Leerzeilen wird an Satz- bzw. Wortgrenzen geteilt, nie mitten im Wort
    (nur ein einzelnes Riesenwort wird hart geteilt). Die Antwortgrenze waechst mit der Eingabe,
    begrenzt auf 4k..12k (Protokoll: mindestens 6000)."""
    import modell
    importlib.reload(modell)
    satz = "Das Team prueft Use-Case-Schnueffeln im Lager. "
    stuecke = modell.chunks((satz * 800).strip(), 5000)
    ok(len(stuecke) > 1 and all(len(s) <= 5000 for s in stuecke), [len(s) for s in stuecke])
    ok(all(s.startswith("Das Team") and s.endswith("im Lager.") for s in stuecke), [s[:20] + "…" + s[-12:] for s in stuecke])
    woerter = ("Transportauftragsnummer " * 400).strip()          # eine Zeile, kein Satzende
    ok(all(s.startswith("Transportauftragsnummer") and s.endswith("nummer") for s in modell.chunks(woerter, 3000)),
       "an Leerzeichen geteilt")
    eq([len(s) for s in modell.chunks("x" * 7000, 3000)], [3000, 3000, 1000], "Riesenwort:")
    eq((modell.antwort_tokens(1000), modell.antwort_tokens(25000), modell.antwort_tokens(100000),
        modell.antwort_tokens(1000, mindestens=6000)), (4096, 6500, 12288, 6000), "Antwortgrenzen:")


def t_protokoll_vorlage_ort_einstellbar():
    """Die Protokoll-Vorlage liegt in .2ndbrain/protokoll-vorlage.md - oder dort, wo
    `protokoll.vorlage` in local.config.json hinzeigt (z. B. eine sichtbare Notiz)."""
    d = temp_vault()
    try:
        import protokoll
        importlib.reload(protokoll)
        (d / ".2ndbrain" / "protokoll-vorlage.md").write_text("Standard-Vorlage", encoding="utf-8", newline="\n")
        eq(protokoll.vorlage(), "Standard-Vorlage", "Standard:")
        (d / "Vorlagen").mkdir()
        (d / "Vorlagen" / "Protokoll.md").write_text("Meine sichtbare Vorlage", encoding="utf-8", newline="\n")
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps({"protokoll": {"vorlage": "Vorlagen/Protokoll.md"}}),
                                                           encoding="utf-8", newline="\n")
        import vault_paths
        importlib.reload(vault_paths)
        importlib.reload(protokoll)
        eq((protokoll.vorlage(), protokoll.vorlage_pfad().name), ("Meine sichtbare Vorlage", "Protokoll.md"), "eigener Ort:")
    finally:
        restore_vault()


def _sw_seite(pfad, kopf, rumpf=""):
    pfad.write_text(f"---\n{kopf}\n---\n{rumpf}", encoding="utf-8", newline="\n")


def _sw_haken(text, kopf, buchstabe):
    """Option `buchstabe` im Eintrag/der Karte ab `kopf` ankreuzen."""
    j = text.index(f"- [ ] {buchstabe})", text.index(kopf))
    return text[:j] + "- [x]" + text[j + 5:]


def t_schreibweisen_karte_und_ersetzen():
    """Namen wie auf ihren Seiten: bestaetigte Schreibweisen (`schreibweisen:`, bei Dingen auch mit
    anderen Trennzeichen), Umlaut-Umschrift und Akzente (nur in Richtung des Namens der Seite), bei
    Personen Bindestriche. Die Schreibung eines Dings (gross/klein, Leerzeichen, Bindewort) erst nach
    Bestaetigung; in einem Wort mit Bindestrich bleibt die Trennung. `aliases:` ersetzt nichts,
    mehrdeutige Schreibweisen und der Name einer anderen Seite auch nicht; Link-Ziele, Code, Adressen
    und klein geschriebene Einzelwoerter bleiben."""
    d = temp_vault()
    try:
        import schreibweisen as sw
        importlib.reload(sw)
        people, projects = d / "entities" / "people", d / "entities" / "projects"
        _sw_seite(people / "otto-beispiel.md", "type: person\nname: Otto Beispiel\nschreibweisen:\n- Otto Beispil")
        _sw_seite(people / "joerg-moeller.md", "type: person\nname: Jörg Möller")
        _sw_seite(people / "anna-mueller.md", "type: person\nname: Anna Mueller")
        _sw_seite(people / "zoltan-kis.md", "type: person\nname: Zoltán Kis")
        _sw_seite(people / "kalle-blom.md", "type: person\nname: Kalle Blom\nschreibweisen:\n- Kale Blum")
        _sw_seite(people / "kari-blum.md", "type: person\nname: Kari Blum\nschreibweisen:\n- Kale Blum")
        _sw_seite(people / "ida-rot.md", "type: person\nname: Ida Rot\nschreibweisen:\n- Kalle Blom")
        _sw_seite(projects / "zettelwerk.md", "type: project\ntitle: ZettelWerk (Produkt)\naliases:\n- Zettel\n"
                                              "schreibweisen:\n- Zettel Welt")
        _sw_seite(projects / "lager-und-hof.md", "type: project\ntitle: Lager & Hof")
        text = ("Otto Beispil und Joerg Moeller mit Anna Müller und Zoltan Kis: Zettel Welt, Zettel-Welt, "
                "ZETTELWERK, Zettel Werk, Lager und Hof, Zettel. [[otto-beispiel|Otto Beispil]] `Otto Beispil` "
                "https://x.de/Otto-Beispil zettelwerk Kale Blum Kalle Blom Joerg-Moeller Jörg-Möller-Team")
        neu, z = sw.vereinheitlichen(text)
        eq(neu, "Otto Beispiel und Jörg Möller mit Anna Müller und Zoltán Kis: ZettelWerk, ZettelWerk, "
                "ZETTELWERK, Zettel Werk, Lager und Hof, Zettel. [[otto-beispiel|Otto Beispiel]] `Otto Beispil` "
                "https://x.de/Otto-Beispil zettelwerk Kale Blum Kalle Blom Jörg Möller Jörg-Möller-Team", "ersetzt:")
        sw.merken("zettelwerk", "Zettel Werk")
        eq(sw.vereinheitlichen("Zettel Werk, Zettel-Werk, der Zettel-Werk-Plan und die Zettel-Welt-Themen")[0],
           "ZettelWerk, ZettelWerk, der ZettelWerk-Plan und die ZettelWerk-Themen", "Schreibung bestaetigt:")
        eq(z[("Otto Beispil", "Otto Beispiel")], 2, "gezaehlt:")
        eq(sw.json_vereinheitlichen({"was": "Otto Beispil fragt", "thema": "zettelwerk", "quelle": "a/Otto Beispil.md",
                                     "punkte": ["Zettel Welt"], "frage": True}),
           {"was": "Otto Beispiel fragt", "thema": "zettelwerk", "quelle": "a/Otto Beispil.md",
            "punkte": ["ZettelWerk"], "frage": True}, "Modell-Ergebnis:")
        import vault_paths as vp
        vp.invalidate_entity_caches()
        eq(vp.alias_map().get("otto beispil"), "otto-beispiel", "Schreibweise beim Zuordnen:")
    finally:
        restore_vault()


def t_schreibweisen_beim_nachbereiten():
    """Nachbereiten: das Modell sieht das Material mit den bestaetigten Schreibweisen ersetzt, seine
    Antwort wird nachgezogen; die Mitschrift bleibt woertlich. Ein neuer Verschreiber einer Person des
    Termins wird Rueckfrage (einmal): A merkt ihn an der Seite, C fragt nie wieder. Schreibt das
    Material den Namen nur mit Umlaut ("Egon Hölzer" zur Seite "Egon Hoelzer"), fragt niemand: die
    Seite heisst kuenftig so."""
    d = temp_vault()
    import modell
    orig = (modell.complete_json, modell.available)
    try:
        import nachbereiten as nb
        import rueckfragen as rf
        import schreibweisen as sw
        for mod in (sw, rf, nb):
            importlib.reload(mod)
        people = d / "entities" / "people"
        _sw_seite(people / "otto-beispiel.md", "type: person\nname: Otto Beispiel\nschreibweisen:\n- Otto Beispil",
                  "# Otto Beispiel\n")
        _sw_seite(people / "berta-wimmel.md", "type: person\nname: Berta Wimmel", "# Berta Wimmel\n")
        _sw_seite(people / "carla-lind.md", "type: person\nname: Carla Lind", "# Carla Lind\n")
        _sw_seite(people / "egon-hoelzer.md", "type: person\nname: Egon Hoelzer", "# Egon Hoelzer\n")
        m = d / "active-meetings"
        m.mkdir(parents=True, exist_ok=True)
        note = m / "2026-09-21 - review - Runde.md"
        mitschrift = "Otto Beispil bringt die Liste. Berta Wimel klaert den Raum mit Carla Lint. Egon Hölzer kommt. " * 4
        _sw_seite(note, "type: meeting\ntitle: Runde\ndate: '2026-09-21'\nteilnehmer:\n"
                        "- '[[otto-beispiel|Otto Beispiel]]'\n- '[[berta-wimmel|Berta Wimmel]]'\n"
                        "- '[[carla-lind|Carla Lind]]'\n- '[[egon-hoelzer|Egon Hoelzer]]'",
                  f"## Mitschrift\n\n{mitschrift}\n")
        gesehen = []

        def fake(messages, schema, **kw):
            gesehen.append(messages[-1]["content"])
            return {"entscheidungen": [], "kernteil": [], "parkplatz": [],
                    "actions": [{"was": "Otto Beispil bringt die Liste", "wer": "Otto Beispil", "bis": "", "thema": ""}]}, []
        modell.complete_json, modell.available = fake, lambda *a, **k: (True, "test")
        nb.process_note(note)
        ok("Otto Beispiel bringt" in gesehen[0] and "Otto Beispil" not in gesehen[0], gesehen[0][:300])
        text = note.read_text(encoding="utf-8")
        ok("- [ ] Otto Beispiel bringt die Liste" in text and mitschrift.strip() in text, text)
        karten = [c for c in rf.list_clarifications() if c["title"].startswith("Schreibweise")]
        eq(sorted(c["title"] for c in karten), ["Schreibweise: „Berta Wimel“ = Berta Wimmel?",
                                                 "Schreibweise: „Carla Lint“ = Carla Lind?"], "Rueckfragen:")
        eq((vp_read(people / "egon-hoelzer.md").get("name"), vp_read(people / "egon-hoelzer.md").get("schreibweisen")),
           ("Egon Hölzer", ["Egon Hoelzer"]), "Umlaut-Regel:")
        eq(sw.rueckfragen_anlegen(nb.find_material(text), {"berta-wimmel", "carla-lind"}, note), [], "zweimal gefragt:")
        inhalt = _sw_haken(rf.CLARIFICATION_FILE.read_text(encoding="utf-8"), "„Berta Wimel“", "A")
        inhalt = _sw_haken(inhalt, "„Carla Lint“", "C")
        rf.CLARIFICATION_FILE.write_text(inhalt, encoding="utf-8", newline="\n")
        erg = rf.apply_checked()
        eq(sorted(r["ok"] for r in erg), [True, True], "Antworten:")
        eq(vp_read(people / "berta-wimmel.md").get("schreibweisen"), ["Berta Wimel"], "gemerkt:")
        eq(sw.vereinheitlichen("Berta Wimel kommt")[0], "Berta Wimmel kommt", "danach ersetzt:")
        eq(sw.verdaechtige(mitschrift, {"berta-wimmel", "carla-lind"}), [], "Nein fragt wieder:")
    finally:
        modell.complete_json, modell.available = orig
        restore_vault()


def t_schreibweisen_liste_und_antworten():
    """Startliste reports/schreibweisen-review.md: Verschreiber (A ersetzen, B die Seite heisst
    kuenftig so, C nie wieder) und doppelte Personenseiten (zusammenfuehren - die zweite Seite geht
    nach .trash/, Links zeigen auf die erste, ihr Name wird Schreibweise). Die Automatik arbeitet
    Angekreuztes ein und hakt es ab. Nur mit mehr Umlauten/Akzenten geschrieben ("Anna Müller" zur
    Seite "Anna Mueller"): die Regel beantwortet es (B), es kommt gar nicht erst auf die Liste."""
    d = temp_vault()
    try:
        import schreibweisen as sw
        importlib.reload(sw)
        people, projects = d / "entities" / "people", d / "entities" / "projects"
        _sw_seite(people / "otto-beispiel.md", "type: person\nname: Otto Beispiel", "# Otto Beispiel\n")
        _sw_seite(people / "anna-mueller.md", "type: person\nname: Anna Mueller", "# Anna Mueller\n")
        _sw_seite(people / "rita-kurz.md", "type: person\nname: Rita Kurz", "# Rita Kurz\n")
        _sw_seite(people / "karl-schmidt.md", "type: person\nname: Karl Schmidt", "# Karl Schmidt\n")
        _sw_seite(people / "karl-schmid.md", "type: person\nname: Karl Schmid", "# Karl Schmid\n")
        _sw_seite(projects / "zettelwerk.md", "type: project\ntitle: ZettelWerk", "# ZettelWerk\n")
        m = d / "active-meetings"
        m.mkdir(parents=True, exist_ok=True)
        note = m / "2026-09-21 - review - Runde.md"
        _sw_seite(note, "type: meeting\ntitle: Runde\ndate: '2026-09-21'",
                  "## Mitschrift\n\nOtto Beispil und Anna Müller treffen Karl Schmidt. Rita Kurtz bringt "
                  "Zettel Werg mit. Otto Beispil fragt nach Zettelwerk.\n\n## Verweise\n\n- [[karl-schmid]]\n")
        r = sw.liste()
        eq((r["personen"], r["dinge"], r["doppelt"], r["varianten"], r["nach_regel"]), (2, 1, 1, 4, 1), "Liste:")
        anna = people / "anna-mueller.md"
        eq((vp_read(anna).get("name"), vp_read(anna).get("schreibweisen")), ("Anna Müller", ["Anna Mueller"]), "Regel:")
        ok("# Anna Müller" in anna.read_text(encoding="utf-8"), "Titel der Seite")
        liste = d / "reports" / "schreibweisen-review.md"
        text = liste.read_text(encoding="utf-8")
        ok("Anna" not in text, "Regel-Fall auf der Liste")
        for kopf in ("### „Otto Beispil“ → Otto Beispiel", "### „Rita Kurtz“ → Rita Kurz",
                     "### ZettelWerk – 2 Schreibweisen", "### Karl Schmidt und Karl Schmid"):
            ok(kopf in text, f"{kopf} fehlt:\n{text}")
        text = _sw_haken(text, "„Otto Beispil“", "A")
        text = _sw_haken(text, "„Rita Kurtz“", "B")
        text = _sw_haken(text, "### Karl Schmidt", "A")
        text = _sw_haken(text, "### ZettelWerk", "C")
        liste.write_text(text, encoding="utf-8", newline="\n")
        r = sw.automatik()
        ok(r["changed"] == 4 and "wartet auf Freigabe" in r["detail"], r)
        eq(vp_read(people / "otto-beispiel.md").get("schreibweisen"), ["Otto Beispil"], "A:")
        rita = people / "rita-kurz.md"
        eq((vp_read(rita).get("name"), vp_read(rita).get("schreibweisen")), ("Rita Kurtz", ["Rita Kurz"]), "B:")
        ok(not (people / "karl-schmid.md").exists() and (d / ".trash" / "zusammengefuehrt" / "karl-schmid.md").exists(),
           "zusammengefuehrt, alte Seite im Papierkorb")
        ok("[[karl-schmidt]]" in note.read_text(encoding="utf-8"), "Link umgebogen")
        ok("Karl Schmid" in vp_read(people / "karl-schmidt.md").get("schreibweisen", []), "Name wird Schreibweise")
        ok(not any(e["variante"] == "Zettel Werg" for e in sw.kandidaten()["dinge"]), "C fragt wieder")
        eq(liste.read_text(encoding="utf-8").count("### ✅"), 4, "abgehakt:")
        # ein offener Eintrag, den die Regel beantwortet (Liste von frueher, nicht angekreuzt)
        _sw_seite(people / "otto-moeller.md", "type: person\nname: Otto Moeller", "# Otto Moeller\n")
        _sw_seite(people / "ute-baer.md", "type: person\nname: Ute Bär", "# Ute Bär\n")
        liste.write_text("## Personen (2)\n\n### „Otto Möller“ → Otto Moeller\n- [ ] A) Verschreiber\n"
                         "- [ ] B) richtig\n- [ ] C) Jemand anderes\n<!-- schreibweise {\"art\": \"variante\", "
                         "\"variante\": \"Otto Möller\", \"slug\": \"otto-moeller\"} -->\n\n"
                         "### „Ute Bar“ → Ute Bär\n- [ ] A) Verschreiber\n- [ ] B) richtig\n- [ ] C) Jemand anderes\n"
                         "<!-- schreibweise {\"art\": \"variante\", \"variante\": \"Ute Bar\", \"slug\": \"ute-baer\"} -->\n",
                         encoding="utf-8", newline="\n")
        eq(sw.antworten()["erledigt"], 2, "Regel in der Liste:")
        eq(vp_read(people / "otto-moeller.md").get("name"), "Otto Möller", "mehr Umlaute - umbenannt:")
        eq((vp_read(people / "ute-baer.md").get("name"), vp_read(people / "ute-baer.md").get("schreibweisen")),
           ("Ute Bär", ["Ute Bar"]), "ohne Umlaut-Punkte - Verschreiber:")
        ok(liste.read_text(encoding="utf-8").count("### ✅") == 2, "nicht abgehakt")
    finally:
        restore_vault()


def t_schreibweisen_gruppen_und_gelerntes():
    """Je Seite eine Frage mit allen ihren Schreibweisen - einzeln ankreuzen geht auch, der Rest bleibt.
    Was sich von einer frueheren Entscheidung zu derselben Seite nur in der Schreibung unterscheidet,
    bekommt dieselbe Antwort; ein Fuellwort am Rand ("… Und") macht keinen Namen. Erledigtes steht
    in der neuen Liste unten."""
    d = temp_vault()
    try:
        import schreibweisen as sw
        importlib.reload(sw)
        projects = d / "entities" / "projects"
        _sw_seite(projects / "zettelwerk.md", "type: project\ntitle: ZettelWerk", "# ZettelWerk\n")
        _sw_seite(projects / "lagerblick.md", "type: project\ntitle: LagerBlick", "# LagerBlick\n")
        (d / ".2ndbrain" / "daten" / ".schreibweisen.json").write_text(
            json.dumps({"nein": [["laker blick", "lagerblick"]]}), encoding="utf-8", newline="\n")
        m = d / "active-meetings"
        m.mkdir(parents=True, exist_ok=True)
        _sw_seite(m / "2026-09-21 - review - Runde.md", "type: meeting\ntitle: Runde\ndate: '2026-09-21'",
                  "## Mitschrift\n\nZettl Werk und Zettl Werk und Zettel Werg. Laker-Blick meldet sich. "
                  "Die Zettel Werg Und der Rest.\n")
        r = sw.liste()
        eq((r["dinge"], r["varianten"], r["nach_regel"]), (1, 2, 1), "Liste:")
        liste = d / "reports" / "schreibweisen-review.md"
        text = liste.read_text(encoding="utf-8")
        ok("### ZettelWerk – 2 Schreibweisen" in text and "Zettel Werg Und" not in text and "Laker" not in text, text)
        ok(("laker-blick", "lagerblick") in sw._nein(), "wie entschieden: Nein")
        j = text.index("- [ ] „Zettl Werk“")
        liste.write_text(text[:j] + "- [x]" + text[j + 5:], encoding="utf-8", newline="\n")
        sw.antworten()
        eq(vp_read(projects / "zettelwerk.md").get("schreibweisen"), ["Zettl Werk"], "einzeln angekreuzt:")
        ok(("zettel werg", "zettelwerk") in sw._nein(), "der Rest bleibt")
        sw.liste()
        text = liste.read_text(encoding="utf-8")
        ok("## Erledigt (1)" in text and "- ✅ ZettelWerk – 2 Schreibweisen" in text and "Zettl Werk" in text, text)
        # Name der Seite geklaert: ein weiterer aehnlicher Verschreiber ohne Nachfrage - die Schreibung
        # des Namens (hier: gross/klein) aber nicht, die entscheidet der Benutzer
        _sw_seite(m / "2026-09-22 - review - Runde.md", "type: meeting\ntitle: Runde\ndate: '2026-09-22'",
                  "## Mitschrift\n\nZETTELWERK und Zettel Werc.\n")
        r = sw.liste()
        eq((r["nach_regel"], r["varianten"]), (1, 1), "geklaerter Name:")
        eq(sorted(vp_read(projects / "zettelwerk.md").get("schreibweisen")), ["Zettel Werc", "Zettl Werk"], "gemerkt:")
        ok("### „ZETTELWERK“ → ZettelWerk" in liste.read_text(encoding="utf-8"), "Schreibung wird gefragt")
        eq(sw.vereinheitlichen("ZETTELWERK")[0], "ZETTELWERK", "ohne Antwort nicht ersetzt:")
        sw.merken("zettelwerk", "ZETTELWERK")
        eq(sw.vereinheitlichen("ZETTELWERK")[0], "ZettelWerk", "nach A ersetzt:")
        # ein Fuellwort am Rand wird nie Schreibweise - es risse ein "und" aus jedem Satz
        eq(sw.merken("zettelwerk", "Zettel Werc Und"), "„Zettel Werc Und“: kein Name – entfällt", "Fuellwort:")
        _sw_seite(projects / "lagerblick.md", "type: project\ntitle: LagerBlick\nschreibweisen:\n- Laker Blick Und",
                  "# LagerBlick\n")
        sw.neu_laden()
        eq(sw.vereinheitlichen("Laker Blick und mehr")[0], "Laker Blick und mehr", "von Hand eingetragen:")
    finally:
        restore_vault()


def t_schreibweisen_wortregel():
    """Wortregeln (`"schreibweisen": {"woerter": {...}}` in local.config.json): ein Wort immer so, auch
    mitten in einem Namen ("Lagerblick Team", "LAGERBLICK-Monitor"); Link-Ziele, Code und klein
    Geschriebenes (Slugs) bleiben."""
    d = temp_vault()
    try:
        import schreibweisen as sw
        importlib.reload(sw)
        _sw_seite(d / "entities" / "projects" / "lagerblick.md", "type: project\ntitle: LagerBlick", "# LagerBlick\n")
        _sw_seite(d / "entities" / "teams" / "lagerblick-team.md", "type: team\nname: LagerBlick Team",
                  "# LagerBlick Team\n")
        eq(sw.vereinheitlichen("Das Lagerblick Team")[0], "Das Lagerblick Team", "ohne Regel:")
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps(
            {"schreibweisen": {"woerter": {"LagerBlick": ["Lagerblick", "LAGERBLICK", "lagerblick"]}}}),
            encoding="utf-8", newline="\n")
        neu, z = sw.vereinheitlichen("Das Lagerblick Team, der LAGERBLICK-Monitor, [[lagerblick]], `Lagerblick`, lagerblick")
        eq(neu, "Das LagerBlick Team, der LagerBlick-Monitor, [[lagerblick]], `Lagerblick`, lagerblick", "Wortregel:")
        eq(sum(z.values()), 2, "gezaehlt:")
        # Glossar: Begriff, Ueberschrift und Definition; Quellen (Dateinamen) und Link-Ziele bleiben
        g = d / "entities" / "glossary" / "lagerblick-tag.md"
        _sw_seite(g, "type: glossary_term\nterm: Lagerblick Tag\nsources:\n- 2026-09-21 - Lagerblick Runde.md",
                  "\n# Lagerblick Tag\n\n## Definition\n\n> Ein Lagerblick-Termin. Fundstellen: [[2026-09-21 - Lagerblick Runde]]\n")
        sw.bereinigen()
        text = g.read_text(encoding="utf-8")
        ok("term: LagerBlick Tag" in text and "# LagerBlick Tag" in text and "Ein LagerBlick-Termin" in text
           and "- 2026-09-21 - Lagerblick Runde.md" in text and "[[2026-09-21 - Lagerblick Runde]]" in text, text)
        # Erzeuger schreiben gleich richtig - sonst schriebe jeder Lauf die alte Form zurueck
        import glossar
        importlib.reload(glossar)
        ok("Owner: LagerBlick-Team" in glossar._kanon_block({"zeilen": ["Owner: Lagerblick-Team"]}, "Kanon"), "Kanon-Block")
    finally:
        restore_vault()


def t_schreibweisen_email_als_zweite_quelle():
    """Zweitbeste Quelle fuer die Schreibung einer Person: eine E-Mail-Adresse mit dem vollen Namen
    (Personenseite, Mails, Kalender). Passt sie zur Variante, heisst die Seite kuenftig so - aber nur,
    wenn die Variante wie ein Name aussieht (keine Initialen aus der Adresse); passt sie zum Namen der
    Seite, ist die Variante ein Verschreiber. Die Adressen landen nirgends in Liste oder Bericht."""
    d = temp_vault()
    try:
        import schreibweisen as sw
        importlib.reload(sw)
        people = d / "entities" / "people"
        _sw_seite(people / "edda-falk.md", "type: person\nname: Edda Falk", "# Edda Falk\n")
        _sw_seite(people / "kuno-lind.md", "type: person\nname: Kuno Lind\nemail: kuno.lind@example.org", "# Kuno Lind\n")
        _sw_seite(people / "pierre-lee.md", "type: person\nname: Pierre Lee", "# Pierre Lee\n")
        kal = d / "archive" / "calendar"
        kal.mkdir(parents=True)
        (kal / "events.json").write_text(json.dumps([{"summary": "Runde", "description":
                                                      "Kontakt: Edda.Falck@example.org, PierreMH.Lee@example.org"}]),
                                         encoding="utf-8", newline="\n")
        m = d / "active-meetings"
        m.mkdir(parents=True, exist_ok=True)
        _sw_seite(m / "2026-09-21 - review - Runde.md", "type: meeting\ntitle: Runde\ndate: '2026-09-21'",
                  "## Mitschrift\n\nEdda Falck und Kuno Lindt sprechen mit PierreMH Lee. Edda Falck und Kuno Lindt "
                  "klaeren den Rest.\n")
        r = sw.liste()
        eq(r["nach_regel"], 2, "nach der Adresse:")
        eq((vp_read(people / "edda-falk.md").get("name"), vp_read(people / "edda-falk.md").get("schreibweisen")),
           ("Edda Falck", ["Edda Falk"]), "Adresse passt zur Variante:")
        eq(vp_read(people / "kuno-lind.md").get("schreibweisen"), ["Kuno Lindt"], "Adresse passt zur Seite:")
        text = (d / "reports" / "schreibweisen-review.md").read_text(encoding="utf-8")
        ok("### „PierreMH Lee“ → Pierre Lee" in text and "example.org" not in text, text)
    finally:
        restore_vault()


def t_schreibweisen_bestand_bereinigen():
    """Bestand: Namen in abgeleitetem Text wie auf ihren Seiten - Protokoll, Aufgaben, Log-Zeilen,
    automatische Bloecke; Mitschrift, Frontmatter, Titel und eigene Beschreibung bleiben. Vorschau
    schreibt nichts; ohne Freigabe bereinigt die Automatik nicht, danach bei jeder neuen Schreibweise
    (Sicherung in .trash/, Bericht in reports/)."""
    d = temp_vault()
    try:
        import schreibweisen as sw
        importlib.reload(sw)
        otto = d / "entities" / "people" / "otto-beispiel.md"
        _sw_seite(otto, "type: person\nname: Otto Beispiel\nschreibweisen:\n- Otto Beispil", "# Otto Beispiel\n")
        m = d / "active-meetings"
        m.mkdir(parents=True, exist_ok=True)
        note = m / "2026-09-21 - review - Runde.md"
        _sw_seite(note, "type: meeting\ntitle: Runde mit Otto Beispil\nkey_persons:\n- Otto Beispil",
                  "# Runde mit Otto Beispil\n\n## Mitschrift\n\nOtto Beispil hat berichtet.\n\n## Protokoll\n\n"
                  "### Überblick\nOtto Beispil berichtet.\n\n## Actions\n\n"
                  "- [ ] Liste liefern — [[otto-beispiel|Otto Beispil]] ➕ 2026-09-21\n")
        thema = d / "entities" / "projects" / "runde.md"
        _sw_seite(thema, "type: project\ntitle: Runde",
                  "# Runde\n\n<!-- stand-auto:start -->\nOtto Beispil treibt es.\n<!-- stand-auto:end -->\n\n"
                  "## Beschreibung\n\nOtto Beispil hat das Thema gegruendet.\n\n## Event Log\n"
                  "- [2026-09-21] [STATUS] Otto Beispil meldet Fortschritt\n")
        vorher = {p: p.read_text(encoding="utf-8") for p in (note, thema)}
        v = sw.bereinigen(vorschau=True)
        eq((v["dateien"], v["ersetzungen"]), (2, 4), "Vorschau:")
        ok(all(p.read_text(encoding="utf-8") == t for p, t in vorher.items()) and not (d / ".trash").exists(),
           "Vorschau hat geschrieben")
        r = sw.automatik()
        ok("wartet auf Freigabe" in r["detail"] and note.read_text(encoding="utf-8") == vorher[note], r)
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps({"schreibweisen": {"bereinigen": True}}),
                                                           encoding="utf-8", newline="\n")
        r = sw.automatik()
        ok("4 Ersetzung(en) in 2 Datei(en)" in r["detail"], r)
        t = note.read_text(encoding="utf-8")
        ok("title: Runde mit Otto Beispil" in t and "- Otto Beispil" in t and "# Runde mit Otto Beispil" in t
           and "Otto Beispil hat berichtet." in t, t)
        ok("Otto Beispiel berichtet." in t and "[[otto-beispiel|Otto Beispiel]]" in t, t)
        t = thema.read_text(encoding="utf-8")
        ok("Otto Beispiel treibt es." in t and "Otto Beispil hat das Thema" in t
           and "[STATUS] Otto Beispiel meldet" in t, t)
        ok(list((d / ".trash").glob("schreibweisen-*/active-meetings/*.md"))
           and list((d / "reports").glob("schreibweisen-bereinigt-*.md")), "Sicherung oder Bericht fehlt")
        ok("Bestand sauber" in sw.automatik()["detail"], "zweiter Lauf")
        sw.merken("otto-beispiel", "Otto Beispel")
        thema.write_text(thema.read_text(encoding="utf-8") + "- [2026-09-22] [RISK] Otto Beispel fehlt\n",
                         encoding="utf-8", newline="\n")
        ok("1 Ersetzung(en) in 1 Datei(en)" in sw.automatik()["detail"], "neue Schreibweise")
    finally:
        restore_vault()


def t_meeting_note_lifecycle_archive():
    """Lebenslauf einer Termin-Notiz: nachbereitet durch das Modell und eingearbeitet -> Archiv
    (status done); entfallen und uebersprungen, wenn vorbei -> Archiv mit ihrem Status. Es bleibt:
    Notbehelf, nicht eingearbeitet, Zukunft, Vormerkung, ohne Material, belegter Name im Archiv.
    Punkte im Archiv bleiben in der Aufgabenliste und lassen sich abhaken; Zuruecknehmen holt die
    Notiz zurueck nach active-meetings/."""
    d = temp_vault()
    try:
        import aufgaben as tk
        import nachbereiten as nb
        import archivieren
        for m in (tk, nb, archivieren):
            importlib.reload(m)
        am = d / "active-meetings"
        am.mkdir(exist_ok=True)

        def note(name, fm, body="## Actions\n- [ ] Liste schicken — @max ➕ 2026-09-22\n"):
            p = am / f"{name}.md"
            p.write_text("---\ntype: meeting\n" + fm + "---\n# T\n\n" + body, encoding="utf-8", newline="\n")
            return p
        fertig = note("2026-09-22 - checkin - Fertig", "date: '2026-09-22'\nstatus: nachbereitet\n"
                      "nachbereitet_von: modell\neingearbeitet: '2026-09-22'\n")
        nb.save_undo(fertig, "vorher\n")
        nb.finish_undo(fertig)
        note("2026-09-22 - checkin - Notbehelf", "date: '2026-09-22'\nstatus: nachbereitet\nnachbereitet_von: notbehelf\n")
        note("2026-09-22 - checkin - Nicht eingearbeitet", "date: '2026-09-22'\nstatus: nachbereitet\nnachbereitet_von: modell\n")
        note("2026-09-23 - checkin - Entfallen", "date: '2026-09-23'\nstatus: entfallen\n", "")
        note("2026-09-23 - checkin - Privat", "date: '2026-09-23'\nskip_meeting: true\n", "")
        note("2026-10-05 - checkin - Zukunft", "date: '2026-10-05'\nstatus: entfallen\n", "")
        note("2026-09-24 - checkin - Vorgemerkt", "date: '2026-09-24'\nstatus: nachbereitet\nnachbereitet_von: modell\n"
             "eingearbeitet: '2026-09-24'\nnachbereiten: angefordert\n")
        note("2026-09-24 - checkin - Ohne Material", "date: '2026-09-24'\nstatus: vorbereitet\n", "")
        (d / "archive" / "meetings" / "2026-09").mkdir(parents=True)
        (d / "archive" / "meetings" / "2026-09" / "2026-09-25 - checkin - Belegt.md").write_text("x\n", encoding="utf-8")
        note("2026-09-25 - checkin - Belegt", "date: '2026-09-25'\nstatus: entfallen\n", "")

        r = archivieren.run(today="2026-09-29")
        eq(sorted(x["notiz"][13:-3] for x in r["archiviert"]), ["checkin - Entfallen", "checkin - Fertig", "checkin - Privat"],
           "archiviert:")
        eq([x["notiz"][13:-3] for x in r["fehler"]], ["checkin - Belegt"], "Name belegt:")
        ok(not (am / "2026-09-22 - checkin - Fertig.md").exists(), "Notiz noch aktiv")
        arch = d / "archive" / "meetings" / "2026-09" / "2026-09-22 - checkin - Fertig.md"
        fm = vp_fm(arch)
        eq((fm.get("status"), fm.get("processed"), bool(fm.get("archiviert"))), ("done", True, True), "Abschluss:")
        eq(vp_fm(d / "archive" / "meetings" / "2026-09" / "2026-09-23 - checkin - Entfallen.md").get("status"),
           "entfallen", "Status entfallen bleibt:")
        for rest in ("Notbehelf", "Nicht eingearbeitet", "Vorgemerkt", "Ohne Material"):
            ok((am / f"2026-09-2{'4' if rest in ('Vorgemerkt', 'Ohne Material') else '2'} - checkin - {rest}.md").exists(),
               f"{rest} wurde archiviert")
        ok((am / "2026-10-05 - checkin - Zukunft.md").exists(), "Zukunft wurde archiviert")

        tasks = [t for t in tk.scan() if t.path.startswith("archive/meetings/")]
        eq([t.text for t in tasks], ["Liste schicken"], "Punkte im Archiv:")
        res = tk.complete(arch, tasks[0].line, "Liste schicken", today="2026-09-29")
        ok(res.get("ok") and "[x] Liste schicken" in arch.read_text(encoding="utf-8"), res)

        u = nb.undo(arch, force=True)
        ok(u.get("ok") and u.get("note") == "active-meetings/2026-09-22 - checkin - Fertig.md", u)
        eq((am / "2026-09-22 - checkin - Fertig.md").read_text(encoding="utf-8"), "vorher\n", "zurueckgeholt:")
        ok(not arch.exists(), "Archiv-Fassung noch da")
    finally:
        restore_vault()


def t_stand_parent_takes_worst_child_health():
    """Landkarte: ein Oberthema (`parent` der Unterthemen) zeigt die schlechteste
    Ampel seiner Unterthemen, mit Grund - ein leeres Dach steht sonst auf gruen."""
    d = temp_vault()
    try:
        import stand
        import vault_paths as vp
        importlib.reload(stand)
        P = d / "entities" / "projects"
        (P / "dach.md").write_text("---\ntype: project\ntitle: Dach\nkind: area\n---\n# Dach\n\n## Event Log\n",
                                   encoding="utf-8", newline="\n")
        (P / "kind.md").write_text(
            "---\ntype: project\ntitle: Kind\nparent: '[[dach]]'\ntarget_date: '2026-09-01'\n---\n# Kind\n\n"
            "## Event Log\n- [2026-09-20] [STATUS] laeuft\n", encoding="utf-8", newline="\n")
        (P / "enkel.md").write_text("---\ntype: project\ntitle: Enkel\nparent: '[[kind]]'\n---\n# Enkel\n\n## Event Log\n",
                                    encoding="utf-8", newline="\n")
        stand.run(today=date(2026, 9, 27))
        kid, top = vp.read_frontmatter(P / "kind.md"), vp.read_frontmatter(P / "dach.md")
        ok(kid.get("health") == "red", kid)                         # Zieltermin ueberschritten
        eq(top.get("health"), "red", "Dach:")
        ok("über Unterthemen: Kind (rot)" in str(top.get("ampel_grund")), top.get("ampel_grund"))
        eq(vp.read_frontmatter(P / "enkel.md").get("health"), "green", "Enkel bleibt:")
        # Bereichs-Seite zeigt ihre Unterthemen (sonst wirkt ein Bereich ohne eigene Eintraege leer)
        ok("> **Unterthemen:** 🔴 [[kind|Kind]] 0 offen" in (P / "dach.md").read_text(encoding="utf-8"),
           (P / "dach.md").read_text(encoding="utf-8"))
        ev = stand.prose_events((P / "kind.md").read_text(encoding="utf-8"))
        ok(ev and ev[0][2] == "laeuft", ev)
    finally:
        restore_vault()


def t_who_roles_and_subtree_participants():
    """Wer kuemmert sich: die Rolle auf der Personenseite nennt das Thema ("Product
    Ownerin Fuhrpark Management" -> Rollen-Zeile; laengster Treffer gewinnt, abgelaufene
    oder inaktive Rolle zaehlt nicht), ein Oberthema zeigt die Beteiligten seiner
    Unterthemen; der Themen-Stand fuer Claude (MCP) enthaelt beides."""
    d = temp_vault()
    try:
        import beteiligte
        importlib.reload(beteiligte)
        import frage
        importlib.reload(frage)
        import stand
        people = d / "entities" / "people"
        for slug, name, role, extra in (
                ("lena", "Lena Hesse", "One Delta / Customer Data Pool", ""),
                ("rico", "Rico Alt", "Kundenbetreuung Fuhrpark Management (bis 03.08.2026)", ""),
                ("otto", "Otto Weg", "Leiter Fuhrpark Management", "status: inactive\n"),
                ("tom", "Tom Dev", "Entwickler", "")):
            (people / f"{slug}.md").write_text(f"---\ntype: person\nname: {name}\nrole: {role}\n{extra}---\n",
                                               encoding="utf-8", newline="\n")
        (people / "wiebke.md").write_text(
            "---\ntype: person\nname: Wiebke Winter\nrole: Product Ownerin Fuhrpark Management\n---\n# Wiebke Winter\n\n"
            "## Expertise & Verantwortung\n"
            "- [2026-08-03] Datenbedarf:** Enno, Robert und Speaker 2 besprechen den (→ [[2026-08-03 - x]])\n"
            "- [2026-08-17] Wiebke (→ [[2026-08-17 - y]])\n"
            "- [2026-08-28] Product Ownerin Fuhrpark Management (→ [[2026-08-28-log]])\n\n"
            "## Notizen\nIst zu 100% in Delta.\n", encoding="utf-8", newline="\n")
        projects = d / "entities" / "projects"
        tasks = {"order-router": "- [ ] Rollout ansprechen — [[wiebke|Wiebke Winter]] 📅 2026-09-17 ➕ 2026-09-14\n"
                                     "- [ ] Thema durchsprechen — [[wiebke|Wiebke Winter]] ➕ 2026-09-14\n"
                                     "- [ ] Regeln testen — [[tom|Tom Dev]] ➕ 2026-09-20\n"}
        for slug, title, parent in (("fuhrpark-management", "Fuhrpark Management (Bereich)", ""),
                                    ("order-router", "Order Router (Produkt)", "fuhrpark-management"),
                                    ("delta", "Delta", ""), ("one-delta", "One Delta", "delta")):
            (projects / f"{slug}.md").write_text(
                f"---\ntype: project\ntitle: {title}\n" + (f"parent: '[[{parent}]]'\n" if parent else "")
                + f"---\n# {title}\n\n## Offene Punkte\n{tasks.get(slug, '')}\n## Event Log\n",
                encoding="utf-8", newline="\n")
        today = date(2026, 9, 28)
        roles = beteiligte.role_holders(today)
        eq(roles.get("fuhrpark-management"), [("wiebke", "Product Ownerin Fuhrpark Management")], "Rollen:")
        eq(roles.get("one-delta"), [("lena", "One Delta / Customer Data Pool")], "One Delta:")
        ok("delta" not in roles, f"'Delta' steckt in 'One Delta': {roles}")
        eq(beteiligte.subtree({"om": [("jan", 5.0)], "od": [("tom", 6.0), ("jan", 3.0)], "x": [("ina", 2.0)]},
                              {"od": "om", "x": "od", "om": None}),
           {"om": [("tom", 6.0), ("ina", 2.0)], "od": [("ina", 2.0)]}, "Unterthemen, auch tiefer:")
        eq(beteiligte.subtree({"a": [("x", 1.0)]}, {"a": "b", "b": "a"}), {"b": [("x", 1.0)]},
           "Kreis in der Landkarte bricht ab:")

        stand.run(today=today, llm_call=None)
        om = (projects / "fuhrpark-management.md").read_text(encoding="utf-8")
        ok("**Rollen:** [[wiebke|Wiebke Winter]] (Product Ownerin Fuhrpark Management)" in om, om)
        ok("**Beteiligt in Unterthemen:** [[wiebke|Wiebke Winter]], [[tom|Tom Dev]]" in om, om)
        eq(vp_fm(projects / "fuhrpark-management.md").get("rollen"),
           ["[[wiebke|Wiebke Winter]] (Product Ownerin Fuhrpark Management)"], "Frontmatter rollen:")

        # was Claude ueber `topic_status` bekommt: Rollen und Beteiligte der Unterthemen
        text, _ = frage.b_thema("fuhrpark-management", frage.Welt(today))
        ok("Rollen (Angaben der Personen): [[wiebke|Wiebke Winter]] (Product Ownerin Fuhrpark Management)" in text, text)
        ok("Beteiligt in Unterthemen: [[wiebke|Wiebke Winter]], [[tom|Tom Dev]]" in text, text)
    finally:
        restore_vault()


def t_systemuebersicht_and_atlas_questions():
    """Systemuebersicht (LikeC4) aus System-Seiten + Landkarte: Bereich aus Feld/Produkt-
    Thema, Abloesung, belegte Verbindung erst ab zwei Eintraegen. Fragen an den Atlas nur
    mit Beleg: Zustaendigkeit ("Team X" + Kontext + Owner-Wort), Partner nur ausserhalb des
    Kundenkontexts und nicht schon im Kanon (Frachtsys1 = Frachtsys); Review: Paket fuer
    den Atlas, Felder direkt auf die System-Seite, Trefferquote je Fragenart."""
    import tempfile as _tf
    from datetime import date as _date
    d = temp_vault()
    atlas = Path(_tf.mkdtemp(prefix="atlastest-"))
    _TEMP_VAULTS.append(atlas)
    old_env = os.environ.get("VAULT_DOMAIN_ATLAS")
    os.environ["VAULT_DOMAIN_ATLAS"] = str(atlas)
    try:
        nl = chr(10)
        # wer entscheidet: der Vorname der eigenen Personen-Seite; welchen Bereich der Atlas
        # abbildet und wo die Kunden stehen: Konfiguration (kein Name im Code). Ebenso die
        # Hausregeln (Werkzeug, Skill, Kategorien) - der Code bringt nur neutrale Regeln mit
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps(
            {"ich": "daniel-mohr", "atlas": {"bereich": "delta", "kundenkontext": "delta-kundenkontext"},
             "kanon": {"regeln": {
                 "kategorien": [["partner", "Ja – Partner mit Schnittstelle"], ["partnernetzwerk", "Ja – im Partnernetzwerk"],
                                ["unternehmer", "Ja – Unternehmer/Frachtführer"], ["kunde", "Ja – als Kunde"]],
                 "paket_kopf": "Übergabe an die Session im Atlas-Repo: Claude Code mit dem Skill `workshop-kanon-authoring`.",
                 "vorschlag": {"owner:ja": "`resolve-intent --phrase {c} --owner {t}` – Owner-Wechsel mit Vier-Augen."}}}}),
            encoding="utf-8", newline=nl)
        (d / "entities" / "people" / "daniel-mohr.md").write_text(
            "---\ntype: person\nname: Daniel Mohr\n---\n", encoding="utf-8", newline=nl)
        for sub, name, text in (
                ("contexts", "ctx-order-router", "id: ctx-order-router\nname: Order-Router\nowner:\n- team-unresolved\n"),
                ("teams", "team-fuhrpark-management", "id: team-fuhrpark-management\nname: Fuhrpark Management\n"),
                ("externals", "ext-frachtsys1", "id: ext-frachtsys1\nname: Frachtsys1 (Air/Seafreight)\n")):
            (atlas / "canon" / sub).mkdir(parents=True, exist_ok=True)
            (atlas / "canon" / sub / f"{name}.yaml").write_text(text, encoding="utf-8", newline=nl)
        P, S = d / "entities" / "projects", d / "entities" / "systems"
        S.mkdir(parents=True, exist_ok=True)

        def topic(slug, title, kind, parent="", body=""):
            (P / f"{slug}.md").write_text(
                f"---\ntype: project\ntitle: {title}\nkind: {kind}\n" + (f"parent: '[[{parent}]]'\n" if parent else "")
                + f"---\n# {title}\n\n## Beschreibung\n{body}\n\n## Event Log\n", encoding="utf-8", newline=nl)
        topic("delta", "Delta", "area")
        topic("cep", "CEP", "area", "delta")
        topic("delta-kundenkontext", "Delta Kundenkontext", "area", "delta")
        topic("firma-kunde-x", "Kunde X (Firma)", "account", "delta-kundenkontext")
        topic("firma-kunde-z", "Kunde Z (Firma)", "account", "delta-kundenkontext")
        topic("firma-partner-y", "Partner Y (Firma)", "account", "cep")
        topic("produkt-tarom", "TAROM (Produkt)", "product", "cep", "Langläufer-Produkt zum System [[tarom]].")
        log = (P / "cep.md").read_text(encoding="utf-8")
        log += ("- [2026-09-20] [STATUS] Tarom sendet Status an AltSYS über die Schnittstelle\n"
                "- [2026-09-10] [STATUS] Tarom: Schnittstelle zu AltSYS getestet\n"
                "- [2026-09-12] [DECISION] Order-Router geht an das Team Fuhrpark Management (Owner)\n"
                "- [2026-09-14] [STATUS] Kunde Z schickt Aufträge über seine EDI-Schnittstelle\n")
        (P / "cep.md").write_text(log, encoding="utf-8", newline=nl)
        for slug, fm in (("altsys", "name: AltSYS\nbereich: '[[delta]]'\ntags:\n- legacy\n"),
                         ("tarom", "name: Tarom\nersetzt:\n- '[[altsys]]'\n"),
                         ("frachtsys", "name: Frachtsys\nscope: external\nbereich: '[[delta]]'\n")):
            (S / f"{slug}.md").write_text(f"---\ntype: system\n{fm}---\n# {slug}\n\n## Rolle & Zweck\n> Ein System.\n",
                                          encoding="utf-8", newline=nl)
        m = d / "active-meetings" / "2026" / "09"
        m.mkdir(parents=True)
        for i in range(3):
            (m / f"2026-09-1{i} - checkin - Test {i}.md").write_text(
                f"---\ntype: meeting\ndate: '2026-09-1{i}'\n---\nMit Partner Y, Kunde X, Kunde Z und Frachtsys gesprochen.\n",
                encoding="utf-8", newline=nl)
        import systemuebersicht as su
        importlib.reload(su)
        import kanon_vorschlaege as av
        importlib.reload(av)
        today = _date(2026, 9, 28)
        target = d / "likec4-model"
        r = su.run(target, check=False, today=today)
        c4 = (target / "systemuebersicht.c4").read_text(encoding="utf-8")
        ok("delta = bereich 'Delta'" in c4 and "cep = bereich 'CEP'" in c4 and "tarom = system 'Tarom'" in c4, c4)
        ok("delta.cep.tarom -[abloesung]-> delta.altsys 'löst ab'" in c4, c4)
        ok("-[belegt]->" in c4 and "gemeinsam genannt (2×)" in c4, c4)
        ok("link obsidian://open?" in c4 and "view abloesung_altsys" in c4, c4)
        report_text = (d / "reports" / "systemuebersicht.md").read_text(encoding="utf-8")
        ok("```mermaid" in report_text, "Obsidian-Bild")
        # Verbindungen als Tabelle fuer den Graphen des Chats: Abloesung und belegt (mit erstem Beleg)
        ok("## Verbindungen" in report_text and "| [[tarom|Tarom]] | [[altsys|AltSYS]] | löst ab |  |" in report_text
           and "| [[altsys|AltSYS]] | [[tarom|Tarom]] | belegt 2× | 2026-09-20 [[cep]]: Tarom sendet Status an AltSYS "
           in report_text, report_text)
        eq(r["systeme"], 3, "Systeme:")

        g = av.generate(today)
        rep = (d / "reports" / "atlas-vorschlaege.md").read_text(encoding="utf-8")
        ok("Zuständigkeit: Order-Router → Fuhrpark Management" in rep, rep)
        # Kunde mit eigener Schnittstelle kommt als Frage, "als Kunde" zuerst; ohne Beleg nicht
        kz = rep.split("Extern im Atlas? Kunde Z")[1].split("### ")[0] if "Extern im Atlas? Kunde Z" in rep else ""
        ok(kz and kz.index("Ja – als Kunde") < kz.index("Ja – Partner mit Schnittstelle"), rep)
        ok("Extern im Atlas? Partner Y" in rep and "Kunde X" not in rep.split("## Systemübersicht")[0]
           and "Extern im Atlas? Frachtsys" not in rep, rep)
        ok("- [ ] Ja – Fuhrpark Management wird Owner <!-- k:owner:ja -->" in rep
           and "- [ ] Nein – keine Schnittstelle zu Delta <!-- k:nein:schnittstelle -->" in rep
           and "category" not in rep and "ins Review" not in rep, rep)
        # ankreuzen: Zustaendigkeit ja, Partner Y ohne Schnittstelle
        lines = rep.split(nl)
        out, sec = [], ""
        for line in lines:
            if line.startswith("### "):
                sec = line
            if "Zuständigkeit" in sec and line.startswith("- [ ] Ja – Fuhrpark Management wird Owner"):
                line = line.replace("- [ ]", "- [x]", 1)
            if "Partner Y" in sec and line.startswith("- [ ] Nein – keine Schnittstelle"):
                line = line.replace("- [ ]", "- [x]", 1)
            out.append(line)
        (d / "reports" / "atlas-vorschlaege.md").write_text(nl.join(out), encoding="utf-8", newline=nl)
        rv = av.review(today)
        pkg = (d / rv["paket"]).read_text(encoding="utf-8")
        ok("Zuständigkeit: Order-Router" in pkg and "**Entscheidung Daniel:** Ja – Fuhrpark Management wird Owner" in pkg
           and "resolve-intent --phrase ctx-order-router --owner team-fuhrpark-management" in pkg
           and "workshop-kanon-authoring" in pkg and "- [" not in pkg and "Partner Y" not in pkg, pkg)
        ok("Kein Element im Domain Atlas – keine Schnittstelle zu Delta" in (P / "firma-partner-y.md").read_text(encoding="utf-8"),
           "Nein nicht an der Firma notiert")
        st = json.loads(av.STATE.read_text(encoding="utf-8"))
        eq(st["statistik"], {"Zuständigkeit": {"vorgemerkt": 1}, "Extern": {"nein": 1}}, "Trefferquote:")
        av.generate(today)
        rep2 = (d / "reports" / "atlas-vorschlaege.md").read_text(encoding="utf-8")
        heads = [l for l in rep2.split(nl) if l.startswith("### ")]
        ok(not any("Partner Y" in h or "Zuständigkeit" in h for h in heads), f"erneut vorgeschlagen: {heads}")
        ok("Zuständigkeit: 1 angenommen, 0 abgelehnt" in rep2 and "Extern: 0 angenommen, 1 abgelehnt" in rep2, rep2)
        # ohne atlas.bereich: keine Extern-Fragen (niemand raet den Bereich), Hinweis ohne Beispiel
        (d / ".2ndbrain" / "local.config.json").write_text(json.dumps({"ich": "daniel-mohr"}), encoding="utf-8", newline=nl)
        (d / ".2ndbrain" / "daten" / ".atlas_vorschlaege.json").unlink()
        importlib.reload(av)
        qs, _n, _s = av.collect(today)
        ok(qs and not [q for q in qs if q["typ"] == "Extern"], [q["typ"] for q in qs])
        ok("eigener Kontext" in av.EXT_HINT and "Delta" not in av.EXT_HINT, av.EXT_HINT)
    finally:
        if old_env is None:
            os.environ.pop("VAULT_DOMAIN_ATLAS", None)
        else:
            os.environ["VAULT_DOMAIN_ATLAS"] = old_env
        restore_vault()


def t_chat_question_mode_answers_one_by_one():
    """Chat „Offene Fragen": eine Frage nach der anderen ohne Modell. Freier Text wird als
    Einordnung gespeichert (Frage bleibt offen), ein Themenname der Landkarte wird zum
    Bereich, „später" ueberspringt nur im Gespraech, ein Knopf traegt das Feld ein."""
    import tempfile as _tf
    from datetime import date as _date
    d = temp_vault()
    empty_atlas = Path(_tf.mkdtemp(prefix="atlasleer-"))
    _TEMP_VAULTS.append(empty_atlas)
    old_env = os.environ.get("VAULT_DOMAIN_ATLAS")
    os.environ["VAULT_DOMAIN_ATLAS"] = str(empty_atlas)          # kein Kanon: nur Systemfragen
    try:
        nl = chr(10)
        P, S = d / "entities" / "projects", d / "entities" / "systems"
        S.mkdir(parents=True, exist_ok=True)
        (P / "delta.md").write_text("---\ntype: project\ntitle: Delta\nkind: area\n---\n# Delta\n\n## Event Log\n",
                                   encoding="utf-8", newline=nl)
        (P / "cep.md").write_text("---\ntype: project\ntitle: CEP\nkind: area\nparent: '[[delta]]'\n---\n# CEP\n\n"
                                  "## Event Log\n- [2026-09-20] [STATUS] Werkzeug im Einsatz\n", encoding="utf-8", newline=nl)
        for slug, name in (("werkzeug", "Werkzeug"), ("geraet", "Geraet")):
            (S / f"{slug}.md").write_text(f"---\ntype: system\nname: {name}\n---\n# {name}\n\n## Rolle & Zweck\n",
                                          encoding="utf-8", newline=nl)
        import systemuebersicht as su
        importlib.reload(su)
        import kanon_vorschlaege as av
        importlib.reload(av)
        import frage
        importlib.reload(frage)
        today = _date(2026, 9, 28)
        r = frage.ask({"frage": "", "skill": "offene-fragen"}, today=today)
        k = r["karte"]
        ok(r["ok"] and "Werkzeug: Bereich?" in r["antwort"] and "Frage 1 von 2" in r["antwort"], r)
        eq([o["label"] for o in k["optionen"]],
           ["Bereich: CEP", "kein System – nicht in die Übersicht", "nicht mehr fragen", "später"], "Knöpfe:")
        r = frage.ask({"frage": "wird von der Disposition genutzt", "karte_offen": k["id"]}, today=today)
        ok("bleibt offen" in r["antwort"] and r["karte"]["id"] == k["id"], r)
        r = frage.ask({"frage": "Delta", "karte_offen": k["id"]}, today=today)
        page = (S / "werkzeug.md").read_text(encoding="utf-8")
        ok("bereich: '[[delta]]'" in page and "wird von der Disposition genutzt" in page, page)
        ok(r["karte"] and "Geraet: Bereich?" in r["antwort"], r)
        g = r["karte"]["id"]
        r = frage.ask({"skill": "offene-fragen", "karte": {"id": g, "key": "spaeter"}, "ueberspringen": []},
                      today=today)
        ok(r["karte"] is None and g in r["ueberspringen"] and "Keine offenen Fragen" in r["antwort"], r)
        r = frage.ask({"skill": "offene-fragen"}, today=today)
        eq(r["karte"]["id"], g, "nach dem Gespräch wieder da:")
        r = frage.ask({"skill": "offene-fragen", "karte": {"id": g, "key": "opt:0"}}, today=today)
        ok("uebersicht: false" in (S / "geraet.md").read_text(encoding="utf-8") and r["karte"] is None, r)
        st = json.loads(av.STATE.read_text(encoding="utf-8"))
        eq(st["statistik"], {"System-Bereich": {"uebernommen": 2}}, "Trefferquote:")
    finally:
        if old_env is None:
            os.environ.pop("VAULT_DOMAIN_ATLAS", None)
        else:
            os.environ["VAULT_DOMAIN_ATLAS"] = old_env
        restore_vault()


def t_systemuebersicht_owner_guard_and_quiet_rewrite():
    """Ein Modell-Ordner gehoert zu genau einem Vault (Kopfzeile `// Vault: …`) - sonst
    ueberschreibt ein anderer Vault, etwa ein Test-Vault, die echte Uebersicht; nur force setzt sich
    darueber hinweg. Geschrieben wird nur bei inhaltlicher Aenderung - ein neues Datum allein laedt
    den Explorer nicht neu. Die Automatik erzeugt die Uebersicht taeglich (ohne likec4-Pruefung)."""
    from datetime import date as _date
    d = temp_vault()
    try:
        nl = chr(10)
        P, S = d / "entities" / "projects", d / "entities" / "systems"
        (P / "delta.md").write_text("---\ntype: project\ntitle: Delta\nkind: area\n---\n# Delta\n\n## Event Log\n",
                                   encoding="utf-8", newline=nl)
        (S / "altsys.md").write_text("---\ntype: system\nname: AltSYS\nbereich: '[[delta]]'\n---\n# AltSYS\n",
                                     encoding="utf-8", newline=nl)
        import systemuebersicht as su
        importlib.reload(su)
        import auto
        importlib.reload(auto)
        target = d / "likec4-model"
        eq(su.target_dir(None), target, "Ziel im Test-Vault (hermetisch):")
        r = su.run(target, check=False, today=_date(2026, 9, 28))
        c4 = (target / "systemuebersicht.c4").read_text(encoding="utf-8")
        ok(r["geaendert"] and f"// Vault: {d.name}" in c4 and "altsys = system 'AltSYS'" in c4, c4)
        r = su.run(target, check=False, today=_date(2026, 9, 29))
        ok(not r["geaendert"] and "Stand: 2026-09-28" in (target / "systemuebersicht.c4").read_text(encoding="utf-8"),
           "nur das Datum neu - nichts schreiben")
        rep = (d / "reports" / "systemuebersicht.md").read_text(encoding="utf-8")
        ok("erstellt: '2026-09-28'" in rep, rep[:200])
        fremd = d / "fremd-modell"
        fremd.mkdir()
        alt = "// AUTO-GENERIERT\n// x\n// Stand: 2026-01-01\n// Vault: fremder-vault\n\nmodel {\n}\n"
        (fremd / "systemuebersicht.c4").write_text(alt, encoding="utf-8", newline=nl)
        r = su.run(fremd, check=False)
        ok(r["pruefung"].startswith("FEHLER") and "fremder-vault" in r["pruefung"], r)
        eq((fremd / "systemuebersicht.c4").read_text(encoding="utf-8"), alt, "fremdes Modell unberührt:")
        r = su.run(fremd, check=False, force=True)
        ok(r["geaendert"] and "altsys" in (fremd / "systemuebersicht.c4").read_text(encoding="utf-8"), r)
        (S / "tarom.md").write_text("---\ntype: system\nname: Tarom\nbereich: '[[delta]]'\nersetzt:\n- '[[altsys]]'\n---\n",
                                    encoding="utf-8", newline=nl)
        res = auto.run(only={"systemuebersicht"}, llm_status=(False, "aus"))
        st = res["steps"][0]
        ok(st["ok"] and st["changed"] == 1 and "2 Systeme" in st["detail"], st)
        ok("löst ab" in (target / "systemuebersicht.c4").read_text(encoding="utf-8"), "Ablösung im Modell")
        res = auto.run(only={"systemuebersicht"}, llm_status=(False, "aus"))
        ok(res["steps"][0].get("skipped"), "täglich - nicht bei jedem Lauf")
    finally:
        restore_vault()


def t_einrichten_python_paths_calendar_without_leaking_url():
    """Neuer Rechner: `2ndbrain einrichten` traegt genau das laufende Python ins Plugin ein
    (python/py/python3 egal), findet likec4-model/domain-atlas, ersetzt einen verschwundenen
    Pfad, speichert die Kalender-URL nur in ihrer eigenen Datei und gibt sie nie aus."""
    d = temp_vault()
    saved = {k: os.environ.get(k) for k in ("VAULT_DOMAIN_ATLAS", "VAULT_LIKEC4_MODEL", "HOME", "USERPROFILE")}
    try:
        nl = chr(10)
        home = d / "home"
        (home / "likec4-model").mkdir(parents=True)
        (home / "code" / "domain-atlas").mkdir(parents=True)
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
        os.environ.pop("VAULT_DOMAIN_ATLAS", None)
        os.environ.pop("VAULT_LIKEC4_MODEL", None)
        plug = d / ".obsidian" / "plugins" / "2ndbrain"
        plug.mkdir(parents=True)
        (plug / "data.json").write_text(json.dumps({"pythonPath": "python", "autoIntervalMin": 7}),
                                        encoding="utf-8", newline=nl)
        (d / ".2ndbrain" / "local.config.json").write_text(
            json.dumps({"ich": "daniel-mohr", "paths": {"domain_atlas": str(d / "weg")}}), encoding="utf-8", newline=nl)
        import vault_paths
        importlib.reload(vault_paths)
        import einrichten
        importlib.reload(einrichten)
        url = "https://outlook.office365.com/owa/calendar/abc/geheim123/reachcalendar.ics"
        before = {f: f.read_text(encoding="utf-8") for f in (plug / "data.json", d / ".2ndbrain" / "local.config.json")}
        rp = einrichten.run(url, schreiben=False)      # --nur-pruefen
        ok(all(f.read_text(encoding="utf-8") == t for f, t in before.items())
           and not (d / ".2ndbrain" / "calendar.config.json").exists(), "Prüfmodus hat geschrieben")
        ok("würde eingetragen" in {s["schritt"]: s for s in rp["schritte"]}["Pfad likec4_model"]["text"], rp)
        r0 = einrichten.run("http://kein-kalender")
        ok(not (d / ".2ndbrain" / "calendar.config.json").exists(), "falsche URL nicht gespeichert")
        fixed = {s["schritt"]: s for s in r0["schritte"]}["Pfad domain_atlas"]
        ok(fixed["ok"] and "statt" in fixed["text"], fixed)
        r = einrichten.run(url)
        data = json.loads((plug / "data.json").read_text(encoding="utf-8"))
        eq(data, {"pythonPath": sys.executable, "autoIntervalMin": 7}, "Plugin-Einstellungen:")
        cfg = json.loads((d / ".2ndbrain" / "local.config.json").read_text(encoding="utf-8"))
        eq(cfg, {"ich": "daniel-mohr", "paths": {"domain_atlas": (home / "code" / "domain-atlas").as_posix(),
                                                   "likec4_model": (home / "likec4-model").as_posix()}},
           "local.config.json:")
        eq(json.loads((d / ".2ndbrain" / "calendar.config.json").read_text(encoding="utf-8")), {"ical_url": url},
           "Kalender:")
        pf = einrichten.paths()
        out = json.dumps(r, ensure_ascii=False) + json.dumps(pf, ensure_ascii=False)
        ok("geheim123" not in out and pf["kalender"] is True, out)
        eq(pf["likec4_model"], str(home / "likec4-model"), "Modell-Ordner fürs Plugin:")
        ok(sys.executable in r["mcp"] and "-m secondbrain mcp" in r["mcp"] and d.as_posix() in r["mcp"], r["mcp"])
        # Vorlage: was fehlt, kommt dazu; der zweite Lauf ergaenzt nichts
        ok((d / "01_Aufgaben.md").is_file() and (d / ".2ndbrain" / "chat-skills" / "briefing.md").is_file()
           and (d / ".templates" / "project.md").is_file() and (d / "inbox").is_dir(), sorted(p.name for p in d.iterdir()))
        eq(einrichten.vorlage_anlegen(), [], "zweiter Lauf:")
        steps = {s["schritt"]: s for s in r["schritte"]}
        ok(steps["Python"]["ok"] and steps["Kalender"]["ok"] and steps["Pfad domain_atlas"]["ok"], steps)
        neu = "https://outlook.office365.com/owa/calendar/abc/neu456/reachcalendar.ics"
        r2 = einrichten.run(neu)       # neu veroeffentlicht: ersetzt
        eq(json.loads((d / ".2ndbrain" / "calendar.config.json").read_text(encoding="utf-8")), {"ical_url": neu},
           "Kalender ersetzt:")
        k2 = {s["schritt"]: s for s in r2["schritte"]}["Kalender"]
        ok(k2["ok"] and "ersetzt" in k2["text"] and "neu456" not in json.dumps(r2, ensure_ascii=False), k2)
        ok(einrichten.needs_shell(["C:/Program Files/nodejs/npx.CMD"]) == (os.name == "nt")
           and not einrichten.needs_shell(["/usr/bin/likec4"]), "Shell nur für .cmd/.bat unter Windows")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        restore_vault()


def vp_fm(path):
    import vault_paths
    return vault_paths.read_frontmatter(path)


def t_entity_merge_skips_auto_blocks_and_self_links():
    """Zusammenfuehren (Vornamen-Datei -> Person): automatische Bloecke und leere
    Abschnitte der alten Datei kommen nicht mit, die Sammelueberschrift verlinkt
    nicht auf die Seite selbst."""
    d = temp_vault()
    try:
        import zusammenfuehren
        importlib.reload(zusammenfuehren)
        people = d / "entities" / "people"
        keep, drop = people / "tom-naumann.md", people / "tom.md"
        keep.write_text("---\ntype: person\nname: Tom Naumann\n---\n# Tom Naumann\n\n## Beschreibung\n\n",
                        encoding="utf-8", newline="\n")
        drop.write_text("---\ntype: person\nname: Tom\n---\n# Tom\n\n<!-- people-auto:start -->\n"
                        "## Überblick (automatisch)\n- alt\n<!-- people-auto:end -->\n\n"
                        "## Expertise & Verantwortung\n\n- [2026-08-24] Tom macht X\n\n## Projekte & Beteiligungen\n\n-\n",
                        encoding="utf-8", newline="\n")
        (d / "notiz.md").write_text("Mit [[tom]] gesprochen.\n", encoding="utf-8", newline="\n")
        zusammenfuehren.merge_entity_files(keep, drop)
        text = keep.read_text(encoding="utf-8")
        ok("Tom macht X" in text and "people-auto" not in text and "Überblick (automatisch)" not in text, text)
        ok("Projekte & Beteiligungen" not in text and "[[tom-naumann]]" not in text and "„tom“" in text, text)
        ok(not drop.exists() and (d / ".trash" / "zusammengefuehrt" / "tom.md").exists(), "nicht im Papierkorb")
    finally:
        restore_vault()


def t_dataview_section_comparisons_survive_normalization():
    """Dataview macht aus Abschnittsnamen im Link nur Buchstaben/Ziffern/_/- mit Leerzeichen
    ("Altbestand – im …" -> "Altbestand im …"). Ein fester Vergleich
    `meta(section).subpath = "X"` muss X schon so schreiben - sonst bleibt die Abfrage leer, etwa
    in allen Altbestand-Bloecken."""
    import re as _re
    here = ENGINE

    def dv(s):
        return _re.sub(r"\s+", " ", _re.sub(r"[^\w\-\s]", " ", s)).strip()
    sources = list(here.glob("*.py")) + [here / "vorlage" / "01_Aufgaben.md"]
    bad = []
    for p in sources:
        text = p.read_text(encoding="utf-8")
        for m in _re.finditer(r'subpath\s*(?:=|===|==)\s*"([^"{}]+)"', text):
            if dv(m.group(1)) != m.group(1):
                bad.append(f"{p.name}: {m.group(1)}")
        if "subpath = \"{tk.ALTBESTAND_TITLE}\"" in text or 'subpath = "{ALTBESTAND_TITLE}"' in text:
            bad.append(f"{p.name}: Vergleich mit ALTBESTAND_TITLE")
    eq(bad, [], "Abschnittsvergleiche, die Dataview nie trifft:")
    import aufgaben as tk
    ok(dv(tk.ALTBESTAND_TITLE) != tk.ALTBESTAND_TITLE, "Titel enthaelt keine Sonderzeichen mehr - Test anpassen")


def t_verdichten_archives_done_and_old_log_keeps_rest():
    """Verdichten: erledigte/verworfene Punkte nach 30 (ohne Datum 90) Tagen samt
    Belegen und Log aelter 6 Monate ins Jahresarchiv. Altbestand, Beschluesse,
    Meilensteine und Frisches bleiben; je Quartal eine Zusammenfassung am Ende
    (ohne Modell Zaehlung, spaeter mit Modell ersetzt); Automatik erst Vorschau;
    zweiter Lauf aendert nichts; die Neuaufnahme erkennt archivierte Punkte."""
    from datetime import date as _date, timedelta as _td
    d = temp_vault()
    try:
        import verdichten
        importlib.reload(verdichten)
        import uebernehmen as hs
        import aufgaben as tk
        topic = d / "entities" / "projects" / "demo.md"
        src = " (→ [[2026-03-20 - weekly - Demo]])"
        body = ["---", "type: project", "title: Demo", "---", "# Demo", "", "## Offene Punkte",
                "- [ ] offen bleibt ➕ 2026-01-10",
                "- [x] alt erledigt ➕ 2026-06-01 ✅ 2026-08-01",
                "    - Beleg 01.08.: „erledigt“ ([[demo]])",
                "- [x] frisch erledigt ➕ 2026-09-01 ✅ 2026-09-20",
                "- [-] verworfen ohne Datum ➕ 2026-05-01",
                "- [-] verworfen neu ➕ 2026-08-15", "",
                "### Altbestand – im nächsten Termin prüfen", "",
                "- [x] alt im Altbestand ➕ 2026-01-01 ✅ 2026-02-01", "",
                "## Beschreibung", "Text", "", "## Event Log",
                "- [2026-09-20] [STATUS] neu",
                f"- [2026-03-20] [STATUS] alt Q1 eins{src}",
                "- [2026-03-10] [RISK] alt Q1 Risiko",
                "- [2026-03-05] [DECISION] Beschluss bleibt",
                "- [2026-02-01] [MILESTONE] Meilenstein bleibt",
                "- [2025-12-01] [STATUS] alt Q4 2025"]
        nl = chr(10)
        topic.write_text(nl.join(body) + nl, encoding="utf-8", newline=nl)
        today = _date(2026, 9, 28)
        before = topic.read_text(encoding="utf-8")
        open_before = [t.text for t in tk.tasks_in_text(before, "topic", stem="demo") if t.is_open]

        # Automatik: erst Vorschau, 30 Tage nichts, dann ohne Modell warten
        r = verdichten.auto_step(today)
        ok("Vorschau" in r["detail"] and "28.10.2026" in r["detail"], r)
        ok("[[demo]]" in verdichten.REPORT.read_text(encoding="utf-8"), "Vorschau-Bericht")
        verdichten.auto_step(today + _td(days=29))
        eq(topic.read_text(encoding="utf-8"), before, "vor Ablauf der 30 Tage verdichtet")
        ok(verdichten.auto_step(today + _td(days=30)).get("skipped"), "ohne Modell nicht warten")

        rows = verdichten.preview(today)
        eq([(x["aufgaben"], x["log"], x["quartale"]) for x in rows], [(2, 3, ["Q4 2025", "Q1 2026"])])
        verdichten.run(apply=True, today=today)
        text = topic.read_text(encoding="utf-8")
        a26 = (d / "archive" / "themen" / "demo-archiv-2026.md").read_text(encoding="utf-8")
        a25 = (d / "archive" / "themen" / "demo-archiv-2025.md").read_text(encoding="utf-8")
        for gone in ("alt erledigt", "Beleg 01.08.", "verworfen ohne Datum", "alt Q1 eins", "alt Q4 2025"):
            ok(gone not in text.split("## Verlauf")[0], f"noch im Thema: {gone}")
        for kept in ("offen bleibt", "frisch erledigt", "verworfen neu", "alt im Altbestand",
                     "Beschluss bleibt", "Meilenstein bleibt", "- [2026-09-20] [STATUS] neu"):
            ok(kept in text, f"verloren: {kept}")
        ok("alt erledigt" in a26 and "Beleg 01.08." in a26 and "verworfen ohne Datum" in a26, a26)
        ok("## Log Q1 2026" in a26 and "alt Q1 Risiko" in a26 and "alt Q4 2025" in a25, a26 + a25)
        ok(f"## Offene Punkte{nl}_Erledigte Punkte im Archiv: [[demo-archiv-2026|2026]] (2)_" in text, text)
        ok(text.index("## Event Log") < text.index("## Verlauf (verdichtet)"), "Verlauf hinter dem Log")
        ok(text.index("**Q1 2026**") < text.index("**Q4 2025**"), "neueste Quartale zuerst")
        ok("1 Statusmeldung, 1 Risiko" in text and verdichten.NO_MODEL in text, text)
        eq([t.text for t in tk.tasks_in_text(text, "topic", stem="demo") if t.is_open], open_before)

        # mit Modell: Zaehlungen werden ersetzt, das Archiv waechst nicht
        calls = []

        def fake(messages, schema, **kw):
            calls.append(messages[1]["content"])
            return {"text": "Im Quartal kamen Statusmeldungen und ein Risiko zur Sprache; "
                            "Ergebnis und Stand sind im Archiv nachzulesen."}, []
        verdichten.run(apply=True, today=today, llm_call=fake)
        text2 = topic.read_text(encoding="utf-8")
        eq(len(calls), 2, "je Quartal ein Aufruf")
        ok(verdichten.NO_MODEL not in text2 and "kamen Statusmeldungen" in text2, text2)
        eq((d / "archive" / "themen" / "demo-archiv-2026.md").read_text(encoding="utf-8"), a26)
        verdichten.run(apply=True, today=today, llm_call=fake)
        eq(topic.read_text(encoding="utf-8"), text2, "zweiter Lauf aendert nichts")
        eq(len(calls), 2)

        # Neuaufnahme: archivierter Punkt / Log-Eintrag kommt nicht zurueck
        hs.apply_action_items([{"project": "demo", "task": "alt erledigt", "owner": ""}])
        hs.apply_project_updates([{"slug": "demo", "events": ["[STATUS] alt Q1 eins"]}],
                                 source_file="active-meetings/2026/03/2026-03-20 - weekly - Demo.md")
        text3 = topic.read_text(encoding="utf-8").split("## Verlauf")[0]
        ok("alt erledigt" not in text3 and "alt Q1 eins" not in text3, text3)
    finally:
        restore_vault()


def t_mcp_vault_stdio_protocol_and_allowlist():
    """MCP-Server: echtes stdio-Protokoll (initialize, tools/list, tools/call), die Suche liefert
    Belegsaetze mit Pfad; Personen-Dateien, Pfade ausserhalb des Vaults und die Konfiguration in
    .2ndbrain/ bleiben zu."""
    import subprocess
    d = temp_vault()
    try:
        m = d / "active-meetings" / "2026" / "09"
        m.mkdir(parents=True)
        (m / "2026-09-20 - checkin - Demo.md").write_text(
            "---\ntype: meeting\ntitle: Demo Checkin\ndate: '2026-09-20'\n---\n# Demo\n\n## Meine Notizen\n"
            "Die Sendung ist kein primäres Objekt im Blue Cargo Auftrag, sagt das Team.\n",
            encoding="utf-8", newline="\n")
        (d / "entities" / "people" / "geheim.md").write_text("---\ntype: person\nexit_year: 2027\n---\n",
                                                             encoding="utf-8", newline="\n")
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "search_notes", "arguments": {"query": "Blue Cargo Auftrag"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "read_note", "arguments": {"path": "entities/people/geheim.md"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                 "params": {"name": "read_note", "arguments": {"path": "../.tools/calendar.config.json"}}},
                {"jsonrpc": "2.0", "id": 6, "method": "tools/call",       # Konfiguration des Vaults: nie lesbar
                 "params": {"name": "read_note", "arguments": {"path": ".2ndbrain/calendar.config.json"}}}]
        env = {**os.environ, "VAULT_DIR": str(d), "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run([sys.executable, str(ENGINE / "mcp_server.py")],
                           input="\n".join(json.dumps(x) for x in msgs) + "\n", capture_output=True,
                           text=True, encoding="utf-8", env=env, timeout=120)
        replies = {r["id"]: r for r in map(json.loads, p.stdout.splitlines())}
        eq(sorted(replies), [1, 2, 3, 4, 5, 6], "Antworten (Benachrichtigung ohne Antwort):")
        eq(replies[1]["result"]["protocolVersion"], "2025-06-18", "Version:")
        ok("atlas_evidence" in [t["name"] for t in replies[2]["result"]["tools"]], replies[2])
        hit = replies[3]["result"]["content"][0]["text"]
        ok("active-meetings/2026/09/2026-09-20 - checkin - Demo.md" in hit and "kein primäres Objekt" in hit, hit)
        ok("nicht in einem freigegebenen Ordner" in replies[4]["result"]["content"][0]["text"], replies[4])
        ok("exit_year" not in p.stdout and "calendar" not in replies[5]["result"]["content"][0]["text"].split("„")[0],
           replies[5])
        t6 = replies[6]["result"]["content"][0]["text"]
        ok(("nicht in einem freigegebenen Ordner" in t6 or "Keine Notiz" in t6) and "ical" not in t6, replies[6])
    finally:
        restore_vault()


def t_alias_cache_sees_edited_aliases():
    """Aliasse, die an einer bestehenden Notiz geaendert werden, kommen im naechsten Lauf an - der
    Datei-Cache haengt nicht nur an der Verzeichnis-mtime, die sich dabei nicht aendert."""
    d = temp_vault()
    try:
        import time
        import vault_paths as vp
        p = d / "entities" / "projects" / "uk.md"
        p.write_text("---\ntype: project\nname: AT Middleware Replacement\n---\n# UK\n",
                     encoding="utf-8", newline="\n")
        ok("middleware at" not in vp.alias_map(), "Alias zu frueh")
        vp.update_frontmatter(p, {"aliases": ["Middleware AT"]})
        later = time.time() + 5
        os.utime(p, (later, later))
        vp._ENTITY_CACHE["alias_map"] = None            # neuer Prozess: nur der Datei-Cache
        vp._ENTITY_CACHE["known_slugs"] = None
        eq(vp.alias_map().get("middleware at"), "uk", "geaenderter Alias:")
    finally:
        restore_vault()


def t_no_note_for_private_and_job_interviews():
    """Bewerbungsgespraeche und Privates werden keine Termin-Notiz (und stehen
    nirgends in Listen); Stakeholder-Interviews zur Anforderungsaufnahme schon."""
    d = temp_vault()
    try:
        import vorbereiten
        import vault_paths as vp
        eq([vorbereiten.no_prep_reason(t) for t in ("Interview TA IT&O: Jan Muster", "Vorstellungsgespräch Frau X",
                                             "Arzttermin", "Stakeholder-Interviews Domain Atlas",
                                             "Fuhrpark Mgmt Checkin")],
           ["Bewerbungsgespräch", "Bewerbungsgespräch", "privat/Abwesenheit", "", ""], "Gruende:")
        cal = vp.SOURCES_DIR / "calendar"
        cal.mkdir(parents=True)
        cal.joinpath("events.json").write_text(json.dumps([
            {"date_iso": "2026-09-30", "time": "10:00", "summary": "Interview TA IT&O: Jan Muster"},
            {"date_iso": "2026-09-30", "time": "11:00", "summary": "Fuhrpark Mgmt Checkin"}]),
            encoding="utf-8", newline="\n")
        eq([e["title"] for e in vorbereiten.load_calendar_events({"2026-09-30"})], ["Fuhrpark Mgmt Checkin"], "Kalender:")
    finally:
        restore_vault()


def t_themen_series_only_when_recurring():
    """Reihe = kommt an mehr als einem Tag vor (Kalender oder Notizen, auch
    Archiv). Einzeltermine stehen erst mit Notiz in "Ohne Thema" und werden nie
    als Reihe gespeichert; ein einzelnes kurzes Wort ("it") ist kein Vorschlag."""
    d = temp_vault()
    try:
        import themen as th
        import vault_paths as vp
        import vorbereiten
        importlib.reload(th)
        P = d / "entities" / "projects"
        (P / "tl-betrieb.md").write_text("---\ntype: project\ntitle: TL Betrieb\nkeywords: [it, operations]\n"
                                         "---\n# CL\n", encoding="utf-8", newline="\n")
        cal = vp.SOURCES_DIR / "calendar"
        cal.mkdir(parents=True)
        cal.joinpath("events.json").write_text(json.dumps([
            {"date_iso": "2026-09-29", "time": "09:00", "summary": "Weekly Sync"},
            {"date_iso": "2026-10-06", "time": "09:00", "summary": "Weekly Sync"},
            {"date_iso": "2026-10-01", "time": "10:00", "summary": "Workshop Zukunft"},
            {"date_iso": "2026-09-28", "time": "14:00", "summary": "Kickoff Plattform"},
            {"date_iso": "2026-09-29", "time": "08:00", "summary": "Measure | check-in"},
            {"date_iso": "2026-10-02", "time": "15:00", "summary": "Quartalsrunde"}]),
            encoding="utf-8", newline="\n")
        mdir = d / "active-meetings" / "2026" / "09"
        mdir.mkdir(parents=True)
        (mdir / "2026-09-28 - other - Kickoff Plattform.md").write_text(
            "---\ntype: meeting\ntitle: Kickoff Plattform\ndate: '2026-09-28'\n---\n", encoding="utf-8",
            newline="\n")
        # Reihen-Schluessel mit Typ-Praefix (Frontmatter series): Notiz findet trotzdem zum Termin
        (mdir / "2026-09-29 - checkin - Measure check-in.md").write_text(
            "---\ntype: meeting\ntitle: Measure | check-in\ndate: '2026-09-29'\n"
            "series: checkin-measure-check-in\n---\n", encoding="utf-8", newline="\n")
        arch = vp.MEETINGS_DIR / "2026-07"
        arch.mkdir(parents=True)
        (arch / "quartalsrunde.md").write_text("---\ntype: meeting\ntitle: Quartalsrunde\ndate: '2026-07-02'\n"
                                               "---\n", encoding="utf-8", newline="\n")
        rows = {r["reihe"]: r for r in th.open_meetings(14, today=date(2026, 9, 27))}
        eq(sorted(rows), ["kickoff-plattform", "measure-check-in", "quartalsrunde", "weekly-sync"],
           "Ohne Thema:")
        eq([rows[k]["wiederkehrend"] for k in ("kickoff-plattform", "quartalsrunde", "weekly-sync")],
           [False, True, True], "Reihe erkannt (Quartal ueber das Archiv):")
        ok(rows["kickoff-plattform"]["note"] and rows["measure-check-in"]["note"], "Einzeltermin ohne Notiz")
        projects, aliases = vorbereiten.load_projects(), vp.alias_map()
        eq(th.suggest("Abstimmung IT&O Planung", {}, "x", projects, aliases), [], "'it' allein schlaegt vor:")
        # Nachtragen: Luecken im Archiv ueber den Titel, Jourfix und Hand-Zuordnung bleiben
        (arch / "betrieb.md").write_text("---\ntype: meeting\ntitle: Abstimmung TL Betrieb\ndate: '2026-07-03'\n"
                                         "---\n", encoding="utf-8", newline="\n")
        (arch / "jf.md").write_text("---\ntype: meeting\ntitle: Jourfix TL Betrieb\ndate: '2026-07-04'\n"
                                    "---\n", encoding="utf-8", newline="\n")
        eq([c["note"].rsplit("/", 1)[1] for c in th.backfill(apply=True)], ["betrieb.md"], "nachgetragen:")
        eq(vp.read_frontmatter(arch / "betrieb.md").get("themen"), ["tl-betrieb"], "Thema:")
        eq(th.backfill(), [], "zweiter Lauf:")
        ok(any("operations" in g for s in th.suggest("Operations Runde", {}, "y", projects, aliases)
               for g in s["gruende"]), "starkes Schlagwort fehlt")
    finally:
        restore_vault()


def t_stand_next_meeting_from_calendar_without_note():
    """Naechster Termin je Thema: Notiz zuerst (entfallen zaehlt nicht), sonst der
    Kalender - Termin-Notizen entstehen ja erst kurz vorher. Privates nie."""
    d = temp_vault()
    try:
        import stand
        import vault_paths as vp
        importlib.reload(stand)
        (d / "entities" / "projects" / "demo.md").write_text(
            "---\ntype: project\ntitle: Demo\n---\n# Demo\n", encoding="utf-8", newline="\n")
        cal = vp.SOURCES_DIR / "calendar"
        cal.mkdir(parents=True)
        cal.joinpath("events.json").write_text(json.dumps([
            {"date_iso": "2026-09-29", "time": "08:00", "summary": "Urlaub Demo"},
            {"date_iso": "2026-10-01", "time": "09:00", "summary": "Demo Review"},
            {"date_iso": "2026-10-06", "time": "10:00", "summary": "Demo Checkin"}]),
            encoding="utf-8", newline="\n")
        mdir = d / "active-meetings" / "2026" / "10"
        mdir.mkdir(parents=True)
        (mdir / "2026-10-01 - review - Demo Review.md").write_text(
            "---\ntype: meeting\ntitle: Demo Review\ndate: '2026-10-01'\nthemen: [demo]\n"
            "status: entfallen\n---\n", encoding="utf-8", newline="\n")
        eq(stand.next_meetings("2026-09-27").get("demo"), ("2026-10-06", "", "Demo Checkin"),
           "aus dem Kalender:")
        (mdir / "2026-10-06 - checkin - Demo Checkin.md").write_text(
            "---\ntype: meeting\ntitle: Demo Checkin\ndate: '2026-10-06'\nthemen: [demo]\n---\n",
            encoding="utf-8", newline="\n")
        eq(stand.next_meetings("2026-09-27").get("demo"),
           ("2026-10-06", "2026-10-06 - checkin - Demo Checkin", "Demo Checkin"), "Notiz vor Kalender:")
    finally:
        restore_vault()


def t_protokoll_nach_vorlage():
    """Protokoll im 2ndBrain: nur bei Transkript oder Teams-Zusammenfassung ohne vorhandenes
    Protokoll (keine Mitschrift); Anweisung = Vorlage des Vaults (sonst die mitgelieferte) plus
    Sprache des Materials; eingefuegt als `## Protokoll` vor dem Transkript, Ueberschriften
    eingerueckt, Codebloecke unberuehrt. Der MCP-Server bietet keinen Protokoll-Prompt mehr."""
    d = temp_vault()
    try:
        import protokoll
        import mcp_server as ms
        for m in (protokoll, ms):
            importlib.reload(m)
        tr = "Wir haben besprochen, dass die Freigabe im Oktober kommt und Anna die Liste schickt. " * 4
        mit_tr = f"# T\n\n## Meine Notizen\n\n## Transkript\n\n{tr}\n\n## Entscheidungen\n"
        ok(protokoll.braucht_protokoll(mit_tr), "Transkript ohne Protokoll")
        ok(not protokoll.braucht_protokoll(mit_tr.replace("## Meine Notizen", "## Mitschrift\n\nSchon da.")),
           "Mitschrift ist schon ein Protokoll")
        ok(not protokoll.braucht_protokoll("# T\n\n## Transkript\n\nkurz\n"), "zu kurz")
        eq((protokoll.sprache(tr), protokoll.sprache("We agreed that the release will be in October and that is it.")),
           ("de", "en"), "Sprache:")
        (d / ".2ndbrain" / "protokoll-vorlage.md").write_text("Meine Vorlage.\n", encoding="utf-8", newline="\n")
        gesehen = []
        alt = protokoll.modell.complete
        protokoll.modell.complete = lambda messages, **kw: gesehen.append(messages) or (
            "# Protokoll\n## 1. Überblick\nFreigabe im Oktober.\n```mermaid\nflowchart TD\n## bleibt\n```")
        try:
            antwort = protokoll.erzeugen(mit_tr, {"title": "Portal Review", "date": "2026-09-22"})
        finally:
            protokoll.modell.complete = alt
        ok(gesehen[0][0]["content"].startswith("Meine Vorlage.") and "auf Deutsch" in gesehen[0][0]["content"],
           gesehen[0][0]["content"][:200])
        ok("Termin: Portal Review" in gesehen[0][1]["content"] and "Freigabe im Oktober" in gesehen[0][1]["content"],
           "Stoff fehlt")
        neu = protokoll.einfuegen(mit_tr, antwort)
        ok(neu.index("## Protokoll") < neu.index("## Transkript"), "Protokoll nicht vor dem Transkript")
        ok("### Protokoll" in neu and "#### 1. Überblick" in neu and "\n## bleibt\n" in neu, neu)
        init = ms.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}})
        ok("prompts" not in init["result"]["capabilities"], "MCP bietet noch Prompts an")
        ok("error" in ms.handle({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"}), "prompts/list antwortet noch")
    finally:
        restore_vault()

def t_model_dates_checked_against_text():
    """Daten des Modells in der Nachbereitung: Das Modell kennt das Jahr des Termins nicht und
    liest "may" als Mai. Eine Frist bleibt nur, wenn der Text sie belegt (auch "8.10." ohne Jahr,
    "Januar", "by Friday"); nennt der Punkt selbst eine Frist, rechnet die Engine sie aus; bei
    gleichem Tag und Monat gilt das Jahr aus dem Text; sonst entfaellt sie. Eine Entscheidung
    traegt hoechstens das Termindatum."""
    from datetime import date as _date
    import zeitangaben as za
    b = _date(2026, 9, 28)
    text = ("Anna nimmt am 8.10. am Austausch teil. Bis Ende der Woche liefert Max die Liste. "
            "Einfuehrung spaetestens ab Januar. Package-level messaging may be possible. "
            "Review by Friday, report on October 12th. Folgetermin in KW 41.")
    bel = za.belegte_daten(text, b)
    for iso, want in (("2024-10-08", "2026-10-08"), ("2027-01-01", "2027-01-01"), ("2024-01-15", "2027-01-15"),
                      ("2024-05-27", ""), ("2026-10-02", "2026-10-02"), ("2026-10-12", "2026-10-12"),
                      ("2026-10-13", ""), ("2026-10-07", "2026-10-07"), ("kein Datum", "")):
        eq(za.pruefe_datum(iso, bel), want, f"{iso}:")
    ok(not any(d.month == 5 for d in bel), "'may' als Mai gelesen")
    woche = za.belegte_daten("Frage Otto noch in dieser Woche. Zugang fuer die Arbeiten der kommenden Woche.",
                             _date(2026, 9, 23))
    eq((min(woche).isoformat(), max(woche).isoformat()), ("2026-09-21", "2026-10-04"), "diese + kommende Woche:")
    d = temp_vault()
    try:
        import nachbereiten as nb
        importlib.reload(nb)
        result = {"actions": [{"was": "Liste bis Ende der Woche liefern", "bis": "2024-05-31"},
                              {"was": "Koordinaten bestaetigen", "bis": "2024-05-27"},
                              {"was": "Am Austausch teilnehmen", "bis": "2024-10-08"},
                              {"was": "Ohne Frist", "bis": ""},
                              {"was": "Stimmt schon", "bis": "2026-10-02"}],
                  "entscheidungen": [{"was": "Teilnahme am 8.10.", "datum": "2024-10-08"},
                                     {"was": "Ohne Datum", "datum": ""}]}
        r = nb.daten_pruefen(result, text, "2026-09-28")
        eq([a["bis"] for a in r["actions"]], ["2026-10-02", "", "2026-10-08", "", "2026-10-02"], "Fristen:")
        eq([e["datum"] for e in r["entscheidungen"]], ["2026-09-28", ""], "Entscheidungen:")
        eq(nb.daten_pruefen({"actions": [{"was": "x", "bis": "2024-01-01"}]}, text, "kein-datum")["actions"][0]["bis"],
           "2024-01-01", "ohne Termindatum unveraendert:")
    finally:
        restore_vault()


def t_frist_je_aufgabe_gegen_ihre_stelle():
    """Eine Frist gilt nur, wenn die Stelle des Materials, von der die Aufgabe handelt, sie belegt:
    "noch in dieser Woche" bei Ottos Aufgabe belegt nicht Bertas Frist. Ohne klare Stelle (stark
    umformuliert) gilt wie bisher das ganze Material."""
    from datetime import date as _date
    import zeitangaben as za
    d = temp_vault()
    try:
        import nachbereiten as nb
        importlib.reload(nb)
        material = ("- **Rueckfrage:** Frage Otto Beispiel noch in dieser Woche, wer die Einrichtung der "
                    "Spiegelung unterstuetzt.\n"
                    "- **Zettelwerk:** Ueberprueft die letzten Releases, Reviews und Branches von Zettelwerk "
                    "und bringt die Ergebnisse erneut ein. (Berta)\n"
                    "- **Ausblick:** Die Einfuehrung ist fuer die kommende Woche am 29.09. geplant.\n")
        ok(_date(2026, 9, 22) in za.belegte_daten(material, _date(2026, 9, 23)), "Material belegt die Woche")
        eq(nb.fundstelle("Ueberpruefung der Releases und Branches von Zettelwerk", material).count("\n"), 0,
           "genau eine Stelle:")
        result = {"actions": [
            {"was": "Otto Beispiel fragen, wer die Einrichtung der Spiegelung unterstuetzt", "bis": "2026-09-25"},
            {"was": "Ueberprueft die letzten Releases, Reviews und Branches von Zettelwerk", "bis": "2026-09-22"},
            {"was": "Etwas ganz anderes vorbereiten", "bis": "2026-09-29"}]}
        r = nb.daten_pruefen(result, material, "2026-09-23")
        eq([a["bis"] for a in r["actions"]], ["2026-09-25", "", "2026-09-29"], "Fristen je Aufgabe:")
    finally:
        restore_vault()


def t_person_names_keep_initial_without_full_name():
    """Eine Initiale ohne passenden vollen Namen bleibt in der Liste ("M. Mustermann") - sonst fiele
    die Person aus den Teilnehmern der Vorbereitung; steht der volle Name daneben, zaehlt nur er."""
    d = temp_vault()
    try:
        import personen_namen as pn
        importlib.reload(pn)
        eq(pn.deduplicate_names(["M. Mustermann"]), ["M. Mustermann"], "Initiale verloren:")
        eq(pn.deduplicate_names(["M. Mustermann", "Max Mustermann"]), ["Max Mustermann"], "Dublette:")
        eq(pn.deduplicate_names(["E. Beispiel", "Max Mustermann"]), ["E. Beispiel", "Max Mustermann"],
           "fremde Initiale:")
    finally:
        restore_vault()


def t_prep_participants_from_note_text():
    """Teilnehmer kommen aus dem Kalender als {name, email}, aus einer Termin-Notiz als Text
    (`teilnehmer: ["[[slug|Name]]"]`): beides wird gelesen, der leere Platzhalter der Vorlage
    ("[[]]") nicht - und die Vorbereitung bricht an Text nicht ab."""
    d = temp_vault()
    try:
        import vorbereiten
        eq(vorbereiten.extract_participants({"title": "Weekly", "participants": ["[[]]"]}), [], "Platzhalter:")
        eq(vorbereiten.extract_participants({"title": "X", "participants": ["[[anna-beispiel|Anna Beispiel]]",
                                                                            "Max Mustermann"]}),
           ["Anna Beispiel", "Max Mustermann"], "Text:")
        eq(vorbereiten.extract_participants({"title": "X", "attendees": [{"name": "Erika", "email": "e@x"},
                                                                         {"email": "mailto:z@x"}]}),
           ["Erika"], "Kalender:")
    finally:
        restore_vault()


def t_documents_unreadable_file_does_not_stop_others():
    """Eine Datei, die sich nicht lesen laesst (altes .doc/.ppt/.xls, kaputte Datei), bleibt liegen und
    wird mit Grund gemeldet - die anderen Dokumente werden trotzdem eingelesen."""
    d = temp_vault()
    try:
        import dokumente
        importlib.reload(dokumente)
        inbox = d / "inbox"
        inbox.mkdir(exist_ok=True)
        (inbox / "alt.doc").write_bytes(b"kein zip")
        (inbox / "notiz.txt").write_text("Hallo Text", encoding="utf-8")
        made = dokumente.scan_and_convert_inbox(str(d))
        ok(len(made) == 1 and made[0].name.endswith("-notiz.md"), f"eingelesen: {made}")
        ok((inbox / "alt.doc").is_file(), "unlesbare Datei verschwunden")
        eq(dokumente.NICHT_LESBAR, ["alt.doc (altes Office-Format, bitte als .docx speichern)"], "gemeldet:")
    finally:
        restore_vault()


def t_glossary_engine_words_only_from_strings():
    """Engine-Woerter (Ueberschriften und fette Beschriftungen, die die Engine in Notizen schreibt)
    kommen aus den Zeichenketten des Codes - Kommentare und Docstrings zaehlen nicht, sonst
    veraenderte eine Doku-Aenderung das Glossar."""
    d = temp_vault()
    try:
        import glossar
        nl = chr(10)
        src = d / "m.py"
        src.write_text('"""Doku: ## Nur Doku und **Fett Doku**."""' + nl + "# ## Kommentar Ueberschrift" + nl
                       + 'X = "## Offene Punkte"' + nl + "def f():" + nl + '    """**Auch Doku**"""' + nl
                       + '    return "**Rolle:** " + "x"' + nl, encoding="utf-8", newline=nl)
        eq(sorted(glossar._zeichenketten(src)), sorted(["## Offene Punkte", "**Rolle:** ", "x"]), "Zeichenketten:")
        ok("offene punkte" in glossar.engine_woerter(), "Engine-Wort fehlt")
    finally:
        restore_vault()


TESTS = [
    ("Vault: VAULT_DIR, sonst Suche ab dem aktuellen Ordner, sonst keiner", t_root_from_env_or_cwd),
    ("Frontmatter-Upsert legt fehlende Keys an", t_frontmatter_upsert),
    ("kaputte Alias-Symlinks nicht in der Whitelist", t_broken_symlinks_filtered),
    ("Modell-JSON: Fences, think, trailing comma", t_llm_json_repair),
    ("Ausgabe pruefen: verwirft erfundenes Thema, bewahrt Payload", t_validate_drops_unknown_project),
    ("Ausgabe pruefen: Fuzzy-Match und Enums", t_validate_fuzzy_and_enums),
    ("Ausgabe pruefen: akzeptiert im Payload deklariertes Thema", t_validate_accepts_project_declared_in_payload),
    ("Ausgabe pruefen: haelt Aufgabe mit unbekannter Person zurueck", t_validate_holds_action_with_unknown_owner),
    ("Ausgabe pruefen: Person ueber Alias, nicht Fuzzy", t_validate_resolves_person_via_alias),
    ("Ausgabe pruefen: Kandidaten bei mehrdeutiger Person", t_validate_ambiguous_person_lists_candidates),
    ("Ausgabe pruefen: Kategorie forums (Reihen) erlaubt", t_validate_forums_allowed),
    ("Event-Datum aus der Quelle, nicht heute", t_event_date_from_source_not_today),
    ("Payload-Hash ist kanonisch", t_payload_hash_canonical),
    ("kein Hash bei offenen Klaerungen", t_no_hash_when_clarifications),
    ("Klaerungen dedupliziert bei gleicher Person", t_clarifications_deduplicate_same_person),
    ("series_key entfernt Datumsangaben", t_series_key_strips_dates),
    ("Owner-Zerlegung bei Bindestrich und Wikilink", t_owner_split_survives_hyphens_and_wikilinks),
    ("Agenda-Benutzer-Edit ist sticky", t_agenda_user_edit_is_sticky),
    ("Briefing-Stufen sind relativ begrenzt", t_briefing_tiers_are_relative),
    ("deutsche Datumsangaben", t_german_dates),
    ("kuratierte keywords behalten Kurzbegriffe", t_curated_keywords_keep_short_terms),
    ("Atlas-Team-Slug -> teams, nicht projects", t_atlas_team_slug_goes_to_teams_not_projects),
    ("apply_entities nutzt company.md-Template", t_apply_entities_uses_company_template),
    ("apply_entities schreibt Beschreibung + status: stub", t_apply_entities_writes_description_and_stub_status),
    ("Glossar erkennt ueberdeckten Personen-Begriff", t_glossary_finds_shadowed_person_term),
    ("Glossar erkennt Ueberdeckung ueber Dateinamen-Fallback", t_glossary_finds_shadowed_term_via_filename_fallback),
    ("Contexts-Index ist read-only Verweisliste", t_contexts_index_is_readonly_reference_list),
    ("Kanon: Nachrichten vollstaendig (Typ, Reife, {node}), Verzeichnis mit Beschreibungen, Objekten, Teams, "
     "Externen, Beziehungen, Ablaeufen", t_kanon_nachrichten_und_landkarte),
    ("Kontexte und Systeme: Vorschlaege mit Beleg, Haken ordnen zu und nehmen zurueck",
     t_kontext_systeme_vorschlaege_und_haken),
    ("Personen-Auflosung inkl. Mehrdeutigkeit", t_person_resolution),
    ("Klaerungs-IDs eindeutig auch innerhalb derselben Sekunde", t_clarification_ids_unique_within_same_second),
    ("Klaerungs-Vorabpruefung bricht die Schleife", t_clarify_preflight_blocks_loop),
    ("Reihe nur bei Wiederholung ueber Tage", t_forum_needs_distinct_days),
    ("Mail-Frontmatter ist gueltiges YAML", t_email_frontmatter_is_valid_yaml),
    ("Teilnehmer: Nachname-Komma-Vorname, Umlaute", t_extract_participants_handles_lastname_comma_firstname),
    ("Firma aus Mail-Domain, interne Domain ignoriert", t_company_from_email_ignores_internal_domain),
    ("Kalender: jedes iCal - Serien, Ausnahmen, verschobene/abgelehnte Termine, Zeitzonen, UTC, Quellen",
     t_calendar_any_ical_series_timezones_and_exceptions),
    ("Kanon: einfache YAML-Datei statt Domain Atlas - Fragen, Begriffe, Glossar, Verzeichnis, neutrales Regelwerk",
     t_kanon_simple_yaml_instead_of_domain_atlas),
    ("iCal-Unescape und Zeilenentfaltung", t_ical_unescape_and_unfold),
    ("iCal ATTENDEE/ORGANIZER werden geparst", t_ical_attendees_parsed),
    ("SVG-Text ohne OCR", t_svg_text_without_ocr),
    ("Transkript: Sprecher, Cue-IDs, Verdichtung", t_vtt_speaker_and_condense),
    ("ZIP-Sicherheit: Traversal, Bombe, Nesting", t_zip_safety),
    ("Rauschfilter behaelt kleine Textdateien", t_noise_filter_keeps_small_text),
    ("Herkunft wird vermerkt und einmal abgerufen", t_provenance_roundtrip),
    ("Containername ohne doppeltes Datum", t_container_member_name_has_no_double_date),
    ("repair_leaked_keys entfernt nur den Leak-Lauf", t_repair_leaked_keys_strips_only_leading_run),
    ("update_frontmatter remove= entfernt Keys", t_update_frontmatter_remove_keys),
    ("Zerlegen: Folgezeilen, reiche Notizen ans Modell", t_preparser_joins_wrapped_bullets_and_keeps_rich_notes_for_llm),
    ("Mail-Body: quoted-printable, keine Kappung", t_eml_body_decodes_quoted_printable_without_cap),
    ("Mail: Encoded-Word-Namen und Anhaenge dekodiert", t_eml_decodes_encoded_word_names_and_attachments),
    ("Fremdtext (Mail, Dokument, Anhang, Modell) wird nie ausfuehrbarer Code (dataviewjs)",
     t_foreign_text_never_becomes_executable_code),
    ("Mail: gleicher Betreff am selben Tag - eigene Notiz je Mail, Anhang an seiner Mail",
     t_mail_same_subject_same_day_gets_own_note),
    ("Automatik: Mails samt Anhaengen und eigene Dateien aus inbox/ einlesen, Unlesbares liegen lassen, "
     "Vault-Ordner unberuehrt", t_auto_imports_mails_and_inbox_files),
    ("Nachbereiten: Termin in Arbeit waehrend des Modells, Aenderung in der Zeit wird nicht ueberschrieben",
     t_nachbereiten_in_arbeit_und_waehrenddessen_geaendert),
    ("Stand: ein Haken waehrend des Modells bleibt stehen", t_stand_haken_waehrend_des_modells_bleibt),
    ("Einarbeiten: Probelauf schreibt nichts, Modell -> Log/Aufgabe/Person/Rueckfrage/Archiv, Rueckgaengig",
     t_einarbeiten_probelauf_run_and_undo),
    ("Mail-Verlauf = ein Paket: neueste Mail, aeltere samt Anhaengen mitgebuendelt und abgeschlossen",
     t_mail_thread_is_one_packet_newest_mail_wins),
    ("Einarbeiten: Regeln im Code (5 Ereignisse, Zusage einmal, alte Frist, Firmen, Nachfrage, Fakten, Rundmail)",
     t_einarbeiten_rules_checked_in_code),
    ("Glossar: neue Begriffe nur nach Einordnung, Rauschen keine Seite, nicht doppelt gefragt",
     t_glossar_new_terms_only_relevant_and_not_asked_twice),
    ("Wissen: Index/Verzeichnis/Glossar nur bei geaenderten Quellen", t_wissen_runs_only_when_sources_changed),
    ("Glossar: 3 Notizen, Stopplisten auf beiden Wegen, 2-Buchstaben-Kuerzel nur mit Langform",
     t_glossar_schwellen_notizen_stopplisten_kuerzel),
    ("Glossar zaehlt nur Inhalt (keine Kalender-Exporte, Beschriftungen, Link-Ziele, Engine-Ueberschriften, "
     "Termintitel); vorhandene Seiten bekommen die neue Zahl", t_glossar_counts_only_content),
    ("Eingang: next claimt und liefert kompaktes Paket", t_next_claims_and_emits_packet),
    ("Eingang: next bietet in_progress zuerst an (resumed)", t_next_reoffers_in_progress_with_resumed_flag),
    ("Eingang: next ueberspringt deferred + Cockpit (07_)", t_next_skips_deferred_and_cockpit_prefixes),
    ("Eingang: next wendet strukturierte Datei ohne Modell an", t_next_auto_completes_structured_file),
    ("Eingang: Aufgaben einer strukturierten Notiz werden Offene Punkte",
     t_next_structured_file_actions_become_open_points),
    ("Eingang: next blockiert bei .eml mit Exit 4", t_next_blocks_on_eml_with_exit_4),
    ("Eingang: mark done - kanonisches Vokabular + Move", t_mark_done_writes_canonical_vocab_and_moves),
    ("Eingang: mark done ueberschreibt Twin ([OVERWROTE])", t_mark_done_overwrites_twin_and_logs),
    ("Eingang: mark reset/defer + next-Skip", t_mark_reset_and_defer),
    ("Eingang: Mail + Anhang = ein Paket, mark schliesst beide", t_next_bundles_mail_with_attachment_and_mark_closes_both),
    ("Eingang: grosser Anhang einzeln mit Mail-Kontext", t_next_large_attachment_gets_own_packet_with_parent_context),
    ("Paket: Mail-Rauschen raus, Inhalt bleibt", t_strip_mail_noise_removes_boilerplate_only),
    ("Paket: Personen-Whitelist nur genannte volle Namen", t_packet_whitelist_only_named_people),
    ("Kalender-Adresse aus dem Schluesselbund (Plugin) vor der Datei, nie in den Pfaden",
     t_calendar_url_from_keychain_env_before_file),
    ("Termin-Ordner flach: neue Notizen direkt in active-meetings/", t_active_meetings_flat_new_notes),
    ("rename: Alias-Links + @mentions als ganzes Token", t_rename_links_keeps_alias_and_whole_token_mentions),
    ("Uebernehmen: --force umgeht den Payload-Hash", t_sync_force_bypasses_hash),
    ("Ausgabe pruefen: System-/Firmen-Slug -> Produkt/Firma", t_validate_maps_system_slug_to_product),
    ("Einlesen: Anhaenge vor dem Archivieren der Mail auspacken", t_ingest_unpacks_attachments_before_archiving_mail),
    ("Zerlegen: erstes Wort ist keine Person, @person/bis gelten weiter",
     t_preparser_actions_first_word_is_no_owner),
    ("Gate: [ACTION]-Events werden Aufgaben, leerer Owner bleibt erhalten",
     t_validate_action_events_become_items_and_empty_owner_is_kept),
    ("Extraktion: Thema pro Punkt nur aus Kandidaten, Fragen werden ❓",
     t_extract_assigns_topic_per_item_from_candidates_only),
    ("Nachbereiten: kanonische Punkte, Person ueber Kontext, idempotent, kein Themen-Log",
     t_wrapup_actions_canonical_with_context_owner),
    ("Uebernehmen: Aufgaben als Offene Punkte, nicht ins Event Log, ohne Dublette",
     t_sync_action_items_become_open_points_not_log_lines),
    ("Briefing: Projekt-Punkte vault-weit aus aufgaben.py, Kurzform einmal",
     t_briefing_project_topics_use_tasks_vault_wide_once),
    ("Agenda: neue Punkte als saubere Kurzform", t_agenda_open_items_read_new_task_format_cleanly),
    ("Ampel: nur Risiken der letzten 30 Tage", t_health_counts_only_recent_risks),
    ("Ampel: ueberfaellige Punkte vault-weit, mit Begruendung",
     t_health_counts_overdue_tasks_vault_wide_with_reasons),
    ("Briefing: altes Risiko nur INFO, nicht kritisch", t_briefing_stale_risk_is_info_not_critical),
    ("Briefing: Datum im Quellen-Link ist keine Frist", t_briefing_source_link_date_is_no_deadline),
    ("Briefing: kuerzen an Wort- und Link-Grenzen", t_briefing_shortens_at_word_and_link_boundaries),
    ("Personen-Ueberblick: nur voller Name, idempotent", t_people_profile_full_name_only_and_idempotent),
    ("Uebernehmen: person_facts mit Rolle, ohne Vornamen, ohne Dublette", t_sync_person_facts_appends_role_and_dedupes),
    ("Ausgabe pruefen: neue Person nur mit Vorname wird verworfen", t_validate_drops_first_name_new_person),
    ("Playbook-Schema: 7 Dateien, Anteile=100, Prioritaeten eindeutig", t_playbook_schema_valid),
    ("Playbook-Bloecke: genau block/anteil/inhalt (keine YAML-Flow-Map)",
     t_playbook_block_keys_exact),
    ("Playbook: Keyword-Flexion (Workshops/Reviews), aber kein Praefix-Match",
     t_playbook_keyword_inflection),
    ("Playbook: variantenbezogene Bullets werden gefiltert",
     t_playbook_variant_line_filter),
    ("Playbook detect(): Prioritaets-Tabelle", t_playbook_detect_priority_table),
    ("Playbook resolve_direction: Organigramm, Mehrdeutigkeit = peer", t_playbook_resolve_direction_from_orgchart),
    ("Kein Zirkelimport playbook/agenda", t_no_circular_import_between_playbook_and_agenda),
    ("Vorbereitung: Skelett-Reihenfolge, zweiter Lauf ohne Duplikat", t_prep_stub_skeleton_order_and_no_duplicate_on_second_run),
    ("Punkte: kanonisches Format, Frage, unaufgeloeste Person",
     t_tasks_parse_canonical_question_and_unresolved),
    ("Punkte: Kurzform lesbar, [ACTION]-Zeilen keine Punkte, Gedankenstrich ist keine Person",
     t_tasks_parse_short_form_and_dash_in_text),
    ("Punkte: render/parse verlustfrei, key normalisiert", t_tasks_render_roundtrip_and_key),
    ("Punkte: nur zustaendige Abschnitte, Owner nie geraten, Defaults",
     t_tasks_scan_sections_owner_and_defaults),
    ("Begriffe: Vault + Atlas + LikeC4, Themen-Kandidaten", t_term_index_sources_topics_and_candidates),
    ("Glossar: Atlas-Definitionen, belegte Vorschlaege, nichts ueberschrieben",
     t_glossary_build_atlas_and_grounded_proposals),
    ("Glossar: Fundstellen ganze Saetze, ohne Links und Dubletten, Langform belegt",
     t_glossary_snippets_whole_sentences_no_links_no_twins),
    ("Altbestand: Unterabschnitt, neue Punkte darueber, Aufloesen mit Termindatum",
     t_tasks_altbestand_append_insert_dissolve),
    ("Altbestand: Vorbereitung legt vor, erst nach der Nachbereitung geprueft",
     t_altbestand_prep_block_settle_after_wrapup),
    ("Nacherfassen: Notizen, entfallen, Nachbereitung zuruecknehmen",
     t_capture_notes_entfallen_and_undo_wrapup),
    ("Abhaken: nur die erwartete Zeile, ✅ vor der Quelle", t_tasks_complete_only_the_expected_line),
    ("Termin -> Thema: nur Sicheres automatisch, Reihe im Forum, Neuberechnen",
     t_themen_rules_series_title_and_recompute),
    ("Beteiligte: Aufgaben, Termine, Log - ohne mich, ohne Vornamen", t_beteiligte_from_tasks_meetings_and_log),
    ("Jourfix: Person nie geraten, Block, nur ihr Altbestand wird geklaert",
     t_jourfix_person_resolution_block_and_settle),
    ("Vorbereitung: heute bis naechster Werktag, Vorlauf frueher", t_prep_window_until_next_workday),
    ("Naechster Termin je Thema: Notiz, sonst Kalender, nie Privates",
     t_stand_next_meeting_from_calendar_without_note),
    ("Keine Notiz: Bewerbungsgespraeche und Privates", t_no_note_for_private_and_job_interviews),
    ("Mails: schon eingelesene (Message-ID mit/ohne Anfuehrungszeichen, sonst Zeitstempel) nicht doppelt",
     t_mail_already_processed_is_not_imported_twice),
    ("Alias-Cache: geaenderte Aliasse kommen an", t_alias_cache_sees_edited_aliases),
    ("Landkarte: Oberthema zeigt die schlechteste Ampel seiner Unterthemen", t_stand_parent_takes_worst_child_health),
    ("Rueckfragen: Haken genuegt, Person in vorhandene Aufgabe, Archiv",
     t_clarify_checked_cards_are_applied_and_archived),
    ("Wer kuemmert sich: Rolle nennt das Thema, Oberthema mit Unterthemen-Beteiligten, keine Fetzen",
     t_who_roles_and_subtree_participants),
    ("Systemuebersicht (LikeC4) + Fragen an den Atlas: Bereich, Abloesung, Belege, Verbindungstabelle, Kunden nie "
     "Partner, Review", t_systemuebersicht_and_atlas_questions),
    ("Chat: offene Fragen nacheinander, Text = Einordnung, Themenname = Bereich, später, Knopf",
     t_chat_question_mode_answers_one_by_one),
    ("Systemuebersicht: Modell-Ordner gehoert einem Vault, schreibt nur bei Aenderung, taeglich in der Automatik",
     t_systemuebersicht_owner_guard_and_quiet_rewrite),
    ("Einrichten: laufendes Python ins Plugin, Pfade finden/ersetzen, Kalender-URL nie ausgeben",
     t_einrichten_python_paths_calendar_without_leaking_url),
    ("MCP-Server: stdio-Protokoll, Belege mit Pfad, Personen/.tools zu", t_mcp_vault_stdio_protocol_and_allowlist),
    ("Dataview: Abschnittsvergleiche ueberleben die Link-Normalisierung",
     t_dataview_section_comparisons_survive_normalization),
    ("Zusammenfuehren: keine Auto-Bloecke, keine leeren Abschnitte, kein Selbst-Link",
     t_entity_merge_skips_auto_blocks_and_self_links),
    ("Verdichten: Erledigtes und altes Log ins Archiv, Beschluesse bleiben, Quartale, Dubletten",
     t_verdichten_archives_done_and_old_log_keeps_rest),
    ("Reihe nur, wenn wiederkehrend; Einzeltermin erst mit Notiz; kein 'it'-Vorschlag",
     t_themen_series_only_when_recurring),
    ("Automatik: Kette, Themen-Log je Notiz, wartet ohne Modell, Sperre",
     t_auto_chain_sync_per_note_waits_without_model_and_locks),
    ("Nachbereiten vom Handy vorgemerkt: Desktop arbeitet ab, ohne Modell bleibt es stehen, ohne Text Hinweis",
     t_wrapup_request_from_phone),
    ("Frontmatter: kein Erzeuger schreibt leere Felder, Aufraeumen zeilengenau",
     t_no_empty_frontmatter_from_any_creator),
    ("Zeilenenden: jeder Schreibaufruf erzwingt LF (auch unter Windows)",
     t_writes_are_lf_on_every_platform),
    ("Abschnitte: ersetzen statt verdoppeln, einfuegen vor Ziel", t_md_sections_replace_and_insert),
    ("Stand: Fakten aus Code, Prosa nur bei Aenderung, kein erfundenes Datum",
     t_stand_block_facts_from_code_prose_only_on_change),
    ("Externe Quellen: Env > local.config.json > Auto-Erkennung",
     t_external_path_env_config_and_autodetect),
    ("Glossar-Beispiele aus dem Vault: Systemuebersicht, Teams, Atlas; mehrdeutig raus; Konfiguration geht vor",
     t_glossary_examples_from_vault_not_code),
    ("Selbsttest: toter Code - der eigene Hilfetext zaehlt nicht als Aufrufer, ein Befehl schon",
     t_selfcheck_dead_module_not_saved_by_own_docstring),
    ("Protokoll im 2ndBrain: nur aus Transkript ohne Protokoll, Vorlage + Sprache, vor dem Transkript",
     t_protokoll_nach_vorlage),
    ("Teilnehmer: Initiale ohne vollen Namen bleibt", t_person_names_keep_initial_without_full_name),
    ("Nachbereitung: Daten des Modells nur mit Beleg im Text, Jahr aus dem Text",
     t_model_dates_checked_against_text),
    ("Nachbereiten: Frist je Aufgabe gegen ihre Stelle im Material", t_frist_je_aufgabe_gegen_ihre_stelle),
    ("Schreibweisen: Karte und Ersetzen (Seite, Umschrift, Trennzeichen; Links/Code bleiben)", t_schreibweisen_karte_und_ersetzen),
    ("Schreibweisen: beim Nachbereiten, neue Verschreiber als Rueckfrage", t_schreibweisen_beim_nachbereiten),
    ("Schreibweisen: Startliste und Antworten (ersetzen, umbenennen, zusammenfuehren, nein)", t_schreibweisen_liste_und_antworten),
    ("Schreibweisen: je Seite eine Frage, Gelerntes, Fuellwoerter", t_schreibweisen_gruppen_und_gelerntes),
    ("Schreibweisen: Wortregel (immer so, auch mitten im Namen)", t_schreibweisen_wortregel),
    ("Schreibweisen: E-Mail-Adresse als zweite Quelle", t_schreibweisen_email_als_zweite_quelle),
    ("Schreibweisen: Bestand bereinigen (Vorschau, Freigabe, Sicherung)", t_schreibweisen_bestand_bereinigen),
    ("Rueckfragen zu Themen: verwerfen, zuordnen mit [[thema]], ohne Ziel offen", t_topic_cards_discard_and_assign),
    ("Nachbereitung: dem Modell nur Themen anbieten, Reihe steht fuer ihr Thema", t_topic_candidates_only_topics),
    ("Begriffs-Index: Kanon-Subdomaene zum Thema, auch ueber atlas_id", t_atlas_subdomain_to_topic_via_atlas_id),
    ("Namen: mehrdeutiger Vorname ueber die Reihe eindeutig", t_first_name_resolved_via_series),
    ("Namen: Einarbeiten loest Vornamen ueber Thema und Quelle", t_intake_first_name_resolved_via_topic_and_source),
    ("Stand: neues Thema ohne Eintraege braucht kein Modell", t_stand_new_topic_without_model),
    ("Protokolle aus dem Eingang: zum Termin, unklar Rueckfrage", t_protokolle_aus_dem_eingang_zum_termin),
    ("Glossar: Kanon als Wortschatz (Subdomaenen, Teams, Kontexte, Fachobjekte)", t_glossar_kanon_als_wortschatz),
    ("Themen: neues Thema aus dem Kanon vorschlagen und anlegen", t_thema_neu_aus_dem_kanon),
    ("Kanon-Vorschlaege: Wortschatz (Alias, Fachbegriff, Team) aus dem Glossar", t_kanon_vorschlaege_wortschatz),
    ("Nachbereiten: Entwurf + Pruefstufe (zweites Modell, Abschnitt fuer Abschnitt)", t_nachbereiten_pruefstufe),
    ("Modell: Stuecke an Wortgrenzen, Antwortgrenze nach Eingabe", t_modell_stuecke_an_wortgrenzen_und_antwortgrenze),
    ("Protokoll: Ort der Vorlage einstellbar", t_protokoll_vorlage_ort_einstellbar),
    ("Termin-Lebenslauf: nachbereitet + eingearbeitet -> Archiv, Punkte bleiben, Zuruecknehmen holt zurueck",
     t_meeting_note_lifecycle_archive),
    ("Vorbereitung: Teilnehmer aus Notiz-Text und Kalender, Platzhalter nicht",
     t_prep_participants_from_note_text),
    ("Dokumente: unlesbare Datei bleibt liegen, die anderen kommen an",
     t_documents_unreadable_file_does_not_stop_others),
    ("Glossar: Engine-Woerter nur aus Zeichenketten, nicht aus Kommentaren",
     t_glossary_engine_words_only_from_strings),
]


def main() -> int:
    print(f"Vault-Werkzeuge — {len(TESTS)} Regressionstests\n")
    for name, fn in TESTS:
        check(name, fn)
    import shutil
    for d in _TEMP_VAULTS:
        shutil.rmtree(d, ignore_errors=True)
    skipped = f", {len(_skipped)} uebersprungen" if _skipped else ""
    print(f"\n{_passed} bestanden, {len(_failed)} fehlgeschlagen{skipped}")
    if _failed:
        print("  " + ", ".join(_failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
