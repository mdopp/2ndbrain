#!/usr/bin/env python3
"""ausgabe_pruefen.py - die Ausgabe des Modells vor dem Schreiben gegen Schema und Vault pruefen.

Jede Modell-Ausgabe laeuft durch `validate_and_fix`, bevor uebernehmen.py sie anwendet -
sonst legte ein halluzinierter Themen-Slug blind eine neue Themen-Datei an. Schreibt selbst
nichts: Bereinigtes geht zurueck, Unaufloesbares als Klaerung an den Aufrufer.

Regeln:
  - Themen-Slug muss in der Whitelist sein. Fuzzy-Match (>=0.75) korrigiert
    Tippfehler; ohne Treffer wird das Update **verworfen** und als
    Klaerungsbedarf zurueckgegeben - es wird keine Datei erfunden.
  - Enums (health, category, Event-Typ) werden hart geprueft; `[ACTION]`-Ereignisse
    werden zu Aufgaben (KONZEPT §4.1).
  - Action-Item-Owner werden gegen `entities/people/` aufgeloest - **ohne**
    Fuzzy-Matching (siehe `resolve_person()` unten): `difflib` ueber den
    ganzen Personennamen ordnet nicht nur nichts zu, es ordnet aktiv falsch
    zu ("max" landet auf "maxi", eine andere Person, weil das naeher am
    ganzen String liegt als "max-muster").
  - Deadlines muessen ISO oder "TBD" sein.
"""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aufloesen import _resolve_person, im_kontext, personen_in
import aufgaben as tk
import vault_paths as vp

VALID_HEALTHS = {"green", "yellow", "red", None}
VALID_CATEGORIES = {"people", "teams", "companies", "systems", "projects", "forums"}
VALID_EVENT_TYPES = ("[STATUS]", "[MILESTONE]", "[DEADLINE]", "[RISK]", "[DECISION]", "[ACTION]")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FUZZY_CUTOFF = 0.75
VALID_FACT_KINDS = {"role", "team", "responsibility", "contact"}
MAX_FACT_CHARS = 300


def resolve_slug(slug: str, known: list[str], warnings: list[str], *,
                 kind: str = "Slug") -> str | None:
    """Slug gegen Whitelist aufloesen. None = kein Treffer (Aufrufer verwirft)."""
    if not slug:
        return None
    if slug in known:
        return slug
    lowered = {k.lower(): k for k in known}
    if slug.lower() in lowered:
        return lowered[slug.lower()]
    # Systeme und Firmen sind keine Projekte: ihr Verlauf liegt im Langlaeufer
    # `produkt-<system>` bzw. `firma-<firma>`. Das Modell nennt oft nur den Namen.
    for prefix, label in (("produkt-", "Produkt zum System"), ("firma-", "Langlaeufer zur Firma")):
        longrunner = f"{prefix}{slug.lower()}"
        if longrunner in lowered:
            warnings.append(f"[FIX] {kind} '{slug}' -> '{lowered[longrunner]}' ({label})")
            return lowered[longrunner]
    matches = difflib.get_close_matches(slug, known, n=1, cutoff=FUZZY_CUTOFF)
    if matches:
        warnings.append(f"[FIX] {kind} '{slug}' -> '{matches[0]}' (Fuzzy-Match)")
        return matches[0]
    return None


def resolve_person(raw: str, known_people: list[str],
                    warnings: list[str]) -> tuple[str | None, list[dict]]:
    """Personennamen aufloesen - **ohne** Fuzzy-Matching ueber den ganzen String.

    Reihenfolge:
      1. exakt oder gross/klein-tolerant in `known_people`
      2. `aufloesen._resolve_person()` - liest Slug/`name`/`aliases` aus
         den echten `entities/people/*.md` und findet auch einen blossen
         Vornamen ("Max" -> "max-mustermann"). Dieselbe Logik wie beim
         Aufloesen von Begriffen - **wiederverwendet**, nicht ein zweites Mal
         geschrieben.

    Rueckgabe `(slug, kandidaten)`:
      - eindeutiger Treffer: `(slug, [])`
      - kein Treffer: `(None, [])`
      - mehrdeutig (z.B. "max" -> 4 Personen): `(None, kandidatenliste)` -
        der Aufrufer baut daraus eine Klaerung mit den echten Kandidaten als
        Optionen, nicht "neu anlegen" als Option A.
    """
    if not raw:
        return None, []
    if raw in known_people:
        return raw, []
    lowered = {p.lower(): p for p in known_people}
    if raw.lower() in lowered:
        return lowered[raw.lower()], []

    hit = _resolve_person(raw)
    if hit is None:
        return None, []
    if hit.get("resolved") == "ambiguous":
        return None, hit.get("candidates", [])
    slug = hit.get("slug")
    if slug:
        return slug, []
    return None, []


def _clean_events(events, warnings) -> list[str]:
    out = []
    for ev in events or []:
        ev = str(ev).strip()
        if ev.startswith(VALID_EVENT_TYPES):
            out.append(ev)
        else:
            warnings.append(f"[DROP] Ungueltiger Event-Typ: '{ev[:40]}'")
    return out


def validate_and_fix(payload: dict, known_slugs: dict,
                     context: set[str] | None = None) -> tuple[dict, list[str], list[dict]]:
    """Returns (bereinigtes_payload, warnings, clarifications).

    `context`: Personen der Quelle (dort verlinkt). Mit den im Thema einer Aufgabe verlinkten
    Personen entscheidet er einen mehrdeutigen Vornamen - nur wenn genau ein Kandidat darin steht.

    `clarifications` sind Faelle, in denen das Modell etwas behauptet hat, das
    sich nicht gegen den Vault aufloesen liess - die gehoeren dem Benutzer
    vorgelegt, nicht geraten.
    """
    warnings: list[str] = []
    clarifications: list[dict] = []
    known_projects = list(known_slugs.get("projects", []))
    known_people = known_slugs.get("people", [])

    # Projekte, die das Modell **im selben Payload** als neue Entity deklariert,
    # gelten als bekannt. Sonst wuerde ein Meeting zu einem neuen Projekt seine
    # Events verlieren, obwohl das Projekt eine Zeile darunter angelegt wird -
    # `apply_entities` laeuft vor `apply_project_updates`.
    declared = []
    for ent in (payload.get("entities") or []) + (payload.get("new_entities") or []):
        if isinstance(ent, dict) and ent.get("category") == "projects":
            slug = ent.get("slug") or vp.slugify(ent.get("name", ""))
            if slug and slug not in known_projects:
                known_projects.append(slug)
                declared.append(slug)
    if declared:
        warnings.append(f"[NEW] Projekt(e) im Payload deklariert: {', '.join(declared)}")

    # --- project_updates ---
    valid_updates = []
    for upd in payload.get("project_updates") or []:
        if not isinstance(upd, dict):
            warnings.append("[DROP] project_update ist kein Objekt")
            continue
        raw_slug = upd.get("slug")
        if not raw_slug:
            warnings.append("[DROP] Project-Update ohne Slug")
            continue
        slug = resolve_slug(raw_slug, known_projects, warnings, kind="Projekt-Slug")
        if slug is None:
            warnings.append(f"[DROP] Unbekannter Projekt-Slug '{raw_slug}' - kein Fuzzy-Treffer")
            payload.setdefault("_unknown_projects", [])
            if raw_slug not in payload["_unknown_projects"]:
                payload["_unknown_projects"].append(raw_slug)
            clarifications.append({
                "title": f"Unbekanntes Projekt '{raw_slug}'",
                "context": ("Das Modell hat Ereignisse diesem Projekt zugeordnet, es "
                            "existiert aber nicht im Vault. Events: "
                            + "; ".join(str(e)[:80] for e in (upd.get("events") or [])[:3])),
                "options": [
                    f"A) Neues Projekt '{vp.slugify(raw_slug)}' anlegen",
                    "B) Einem bestehenden Projekt zuordnen",
                    "C) Verwerfen",
                ],
                # Der verworfene Teil-Payload wird mitgegeben, damit die Klaerung
                # spaeter **angewendet** werden kann - sonst braechte die
                # Beantwortung der Rueckfrage die Events nicht zurueck.
                "kind": "unknown_project",
                "raw_slug": raw_slug,
                "payload": {
                    "project_updates": [dict(upd, slug="__RESOLVE__")],
                    "action_items": [dict(a, project="__RESOLVE__")
                                     for a in (payload.get("action_items") or [])
                                     if a.get("project") == raw_slug],
                },
            })
            continue
        upd["slug"] = slug
        if upd.get("health") not in VALID_HEALTHS:
            warnings.append(f"[FIX] Ungueltiger Health-Wert '{upd.get('health')}' -> null")
            upd["health"] = None
        events = _clean_events(upd.get("events"), warnings)
        # [ACTION]-Events sind Aufgaben, keine Log-Eintraege (KONZEPT §4.1):
        # als action_item weiterreichen - dann laufen sie durch dieselbe
        # Personen-Pruefung und landen abhakbar unter `## Offene Punkte`.
        for ev in (e for e in events if e.startswith("[ACTION]")):
            t = tk.from_short_text(ev[len("[ACTION]"):])
            payload.setdefault("action_items", []).append(
                {"task": t.text, "owner": t.owner_raw or "", "project": slug,
                 "deadline": t.due or "TBD"})
        upd["events"] = [e for e in events if not e.startswith("[ACTION]")]
        if not upd["events"] and upd.get("health") is None:
            warnings.append(f"[DROP] Project-Update '{slug}' ohne verwertbaren Inhalt")
            continue
        valid_updates.append(upd)
    payload["project_updates"] = valid_updates

    # --- entities / new_entities: beide Schluessel werden angenommen, weiter geht es als `entities` ---
    raw_entities = (payload.get("entities") or []) + (payload.get("new_entities") or [])
    valid_entities = []
    seen = set()
    for ent in raw_entities:
        if not isinstance(ent, dict):
            warnings.append("[DROP] Entity ist kein Objekt")
            continue
        cat = ent.get("category")
        if cat not in VALID_CATEGORIES:
            warnings.append(f"[DROP] Ungueltige Kategorie: '{cat}'")
            continue
        slug = ent.get("slug") or vp.slugify(ent.get("name", ""))
        if not slug:
            warnings.append("[DROP] Entity ohne Slug und ohne Name")
            continue
        if not SLUG_RE.match(slug):
            fixed = vp.slugify(slug)
            if not fixed:
                warnings.append(f"[DROP] Slug nicht normalisierbar: '{slug}'")
                continue
            warnings.append(f"[FIX] Slug '{slug}' -> '{fixed}' (kebab-case)")
            slug = fixed
        if cat == "people" and len(re.split(r"[\s\-]+", str(ent.get("name") or slug.replace("-", " ")).strip())) < 2:
            # Wie bei person_facts: ein Vorname allein legt keine Person an -
            # sonst entstuenden Vornamen-Stubs (einzelne Vornamen als Datei).
            warnings.append(f"[DROP] Neue Person nur mit Vorname: '{ent.get('name') or slug}'")
            continue
        if (cat, slug) in seen:
            continue
        seen.add((cat, slug))
        ent["slug"] = slug
        ent.setdefault("name", slug)
        if not isinstance(ent.get("meta"), dict):
            ent["meta"] = {}
        valid_entities.append(ent)
    payload["entities"] = valid_entities
    payload.pop("new_entities", None)

    # --- action_items ---
    valid_actions = []
    for act in payload.get("action_items") or []:
        if not isinstance(act, dict):
            warnings.append("[DROP] Action-Item ist kein Objekt")
            continue
        task = str(act.get("task") or "").strip()
        if not task:
            warnings.append("[DROP] Action-Item ohne Task")
            continue
        proj = resolve_slug(act.get("project"), known_projects, warnings, kind="Projekt-Slug")
        if proj is None:
            warnings.append(f"[DROP] Action-Item '{task[:40]}' ohne aufloesbares Projekt")
            continue
        act["project"] = proj

        owner_raw = str(act.get("owner") or "").lstrip("@").strip()
        if owner_raw.casefold() in ("unassigned", "unbekannt", "tbd", "?"):
            owner_raw = ""
        if not owner_raw:
            # Ohne Namen gibt es nichts zu klaeren: als Punkt ohne Person
            # uebernehmen ("— ?") statt still zu verwerfen.
            act["owner"] = ""
            warnings.append(f"[INFO] Aufgabe '{task[:40]}' ohne Verantwortliche(n) uebernommen")
            owner, candidates = "", []
        else:
            owner, candidates = resolve_person(owner_raw, known_people, warnings)
            if owner is None and candidates:
                im_thema = personen_in([vp.project_path(proj)])
                owner = im_kontext(candidates, set(context or ()) | im_thema)
                if owner:
                    warnings.append(f"[INFO] '{owner_raw}' ueber den Kontext eindeutig: {owner}")
                    candidates = []
        if owner is None:
            if owner_raw:
                if candidates:
                    # Mehrdeutig: die echten Kandidaten als Optionen, nicht
                    # "neu anlegen" als Option A - sonst legt der Benutzer aus
                    # Versehen eine Dublette einer bereits vorhandenen Person an.
                    opts = [f"{chr(65 + i)}) {c['name']} ({c['slug']})"
                            for i, c in enumerate(candidates)]
                    opts.append(f"{chr(65 + len(candidates))}) Neue Person "
                               f"'{vp.slugify(owner_raw)}' anlegen")
                    clarifications.append({
                        "kind": "unknown_person",
                        "raw_slug": owner_raw,
                        "payload": {"action_items": [dict(act, owner="__RESOLVE__")]},
                        "title": f"Mehrdeutige Person '{owner_raw}'",
                        "context": (f"{len(candidates)} Personen passen auf '{owner_raw}': "
                                    + ", ".join(c["name"] for c in candidates)),
                        "options": opts,
                    })
                else:
                    clarifications.append({
                        "kind": "unknown_person",
                        "raw_slug": owner_raw,
                        "payload": {"action_items": [dict(act, owner="__RESOLVE__")]},
                        "title": f"Unbekannte Person '{owner_raw}'",
                        "context": f"Owner der Aufgabe '{task[:80]}' (Projekt {proj}) ist im Vault unbekannt.",
                        "options": [
                            f"A) Person '{vp.slugify(owner_raw)}' neu anlegen",
                            "B) Einer bestehenden Person zuordnen",
                            "C) Aufgabe ohne Owner uebernehmen",
                        ],
                    })
            # Nicht mit 'unassigned' anwenden: der Eintrag liegt in der
            # Wiedervorlage der Klaerung. Beides anzuwenden ergaebe eine
            # Dublette - erst "@unassigned", nach dem Aufloesen "@person".
            warnings.append(f"[HOLD] Action '{task[:40]}' zurueckgehalten - "
                            f"Owner '{owner_raw}' unbekannt")
            continue
        else:
            act["owner"] = owner

        deadline = str(act.get("deadline") or "TBD").strip()
        if deadline != "TBD" and not ISO_DATE_RE.match(deadline):
            warnings.append(f"[FIX] Deadline '{deadline}' nicht ISO -> TBD")
            deadline = "TBD"
        act["deadline"] = deadline
        valid_actions.append(act)
    payload["action_items"] = valid_actions

    # --- person_facts: ausdrueckliche Aussagen zu Rolle/Team/Zustaendigkeit ---
    # Unklare Personen werden verworfen, nicht zur Rueckfrage: ein fehlender
    # Rollen-Satz ist kein Schaden, eine falsch zugeordnete Rolle schon.
    valid_facts = []
    for fact in payload.get("person_facts") or []:
        if not isinstance(fact, dict):
            warnings.append("[DROP] person_fact ist kein Objekt")
            continue
        text = " ".join(str(fact.get("fact") or "").split())
        kind = str(fact.get("kind") or "responsibility").strip().lower()
        if not text:
            warnings.append("[DROP] person_fact ohne Text")
            continue
        if kind not in VALID_FACT_KINDS:
            warnings.append(f"[FIX] person_fact-Art '{kind}' -> responsibility")
            kind = "responsibility"
        raw_person = str(fact.get("person") or "").lstrip("@").strip()
        if raw_person not in known_people and len(re.split(r"[\s-]+", raw_person)) < 2:
            # Ein Vorname allein ist nie eindeutig - auch wenn der Vault heute
            # nur eine Person dieses Vornamens kennt.
            warnings.append(f"[DROP] person_fact nur mit Vorname '{raw_person}': {text[:50]}")
            continue
        slug, candidates = resolve_person(raw_person, known_people, warnings)
        if slug is None:
            reason = "mehrdeutig" if candidates else "unbekannt"
            warnings.append(f"[DROP] person_fact fuer '{raw_person}' ({reason}): {text[:50]}")
            continue
        valid_facts.append({"person": slug, "kind": kind, "fact": text[:MAX_FACT_CHARS]})
    payload["person_facts"] = valid_facts

    # --- data_flows ---
    known_systems = known_slugs.get("systems", [])
    valid_flows = []
    for flow in payload.get("data_flows") or []:
        if not isinstance(flow, dict):
            continue
        src = resolve_slug(flow.get("source_system"), known_systems, warnings, kind="System-Slug")
        tgt = resolve_slug(flow.get("target_system"), known_systems, warnings, kind="System-Slug")
        if src is None or tgt is None:
            warnings.append(
                f"[DROP] Data-Flow '{flow.get('source_system')}' -> "
                f"'{flow.get('target_system')}': System unbekannt")
            continue
        flow["source_system"], flow["target_system"] = src, tgt
        valid_flows.append(flow)
    payload["data_flows"] = valid_flows

    return payload, warnings, clarifications
