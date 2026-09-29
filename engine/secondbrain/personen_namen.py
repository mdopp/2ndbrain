#!/usr/bin/env python3
"""personen_namen.py - Personennamen normalisieren und Dubletten in Namenslisten zusammenfassen.

Dieselbe Person steht in Teilnehmerlisten oft mehrfach oder in unterschiedlicher
Schreibweise:

    Max Mustermann
    Max Mustermann
    M. Mustermann
    Mustermann, Max
    → Max Mustermann (einmal)

Genutzt von vorbereiten.py fuer `key_persons` eines Termins. Reine Funktionen: liest
hoechstens die Dateinamen in `entities/people/`, schreibt nichts.

Funktionen
----------
    normalize_name(raw)  →  normalisierter Name ("max mustermann")
    deduplicate_names(lst)  →  sortierte Liste ohne Duplikate
    match_person(raw, people_dir)  →  beste Entity-Übereinstimmung (name, score, begruendung)

Beispiele
---------
    >>> from personen_namen import deduplicate_names
    >>> deduplicate_names(["Max Mustermann", "m. mustermann", "Mustermann, Max"])
    ['Max Mustermann']
"""
from __future__ import annotations

import re
from pathlib import Path
from difflib import SequenceMatcher


def normalize_name(raw: str) -> str:
    """Namen normalisieren: klein, Leerzeichen bereinigt, Titel entfernt.

    Beispiele:
        "  Max Mustermann  " → "max mustermann"
        "Mustermann, Max"    → "max mustermann"
        "M. Mustermann"           → "m mustermann"
        "Dr. Max Mustermann" → "max mustermann"
    """
    if not raw:
        return ""
    s = raw.strip()
    # "Lastname, Firstname" → "Firstname Lastname"
    m = re.match(r"\s*([A-ZÄÖÜa-zäöüß]+)\s*,\s*([A-ZÄÖÜa-zäöüß]+)", s)
    if m:
        s = f"{m.group(2)} {m.group(1)}"

    # Titel entfernen (Dr., Prof., Ing., etc.)
    s = re.sub(r"\b(?:Dr\.?|Prof\.?|Ing\.?|Dipl\.-?Ing\.?|Ph\.?D\.?)\s+", "", s, flags=re.IGNORECASE)

    # Initialen mit Punkt: "M. Mustermann" → "m mustermann" (auch klein: "m. mustermann")
    s = re.sub(r"\b([A-Za-z])\.\s*", r"\1 ", s)

    return s.lower().strip()


def _normalize_for_matching(raw: str) -> str:
    """Normalform für den Abgleich — entspricht normalize_name() (Initialen dort schon ohne Punkt)."""
    s = normalize_name(raw)
    # "m mustermann" bleibt so; "max mustermann" bleibt so
    return s


def _similarities(a: str, b: str) -> list[tuple[float, str]]:
    """Ähnlichkeitsmetriken zwischen zwei normalisierten Namen.

    Gibt Liste von (score, begruendung) zurueck.
    """
    results = []
    aw_parts = a.split()
    bw_parts = b.split()

    # 1. Exakter Match
    if a == b:
        return [(1.0, "exact")]

    # 2. Edit-Distance (Levenshtein-basiert)
    edit_ratio = SequenceMatcher(None, a, b).ratio()
    if edit_ratio > 0.85:
        results.append((edit_ratio, f"edit_distance ({edit_ratio:.2f})"))

    # 3. Wort-Überlappung
    aw, bw = set(aw_parts), set(bw_parts)
    if aw and bw:
        overlap = len(aw & bw) / max(len(aw), len(bw))
        if overlap > 0.5:
            results.append((overlap, f"wort_overlap ({overlap:.2f})"))
        # Ein Wort identisch + Länge ähnlich
        if len(aw & bw) == 1 and max(len(a), len(b)) < 30:
            shared = aw & bw
            if len(a) < 25 or len(b) < 25:
                results.append((0.7, f"shared_word: {shared}"))

    # 4. Initial-Check: "M Mustermann" vs "Max Mustermann"
    #    gleicher Nachname + gleicher Anfangsbuchstabe des Vornamens → starkes Indiz
    if len(aw_parts) == 2 and len(bw_parts) >= 2:
        # "m mustermann" vs "max mustermann" — letzter Teil identisch, erster nur Initial
        if aw_parts[1] == bw_parts[-1]:
            # Erster Teil ist ein Buchstabe (Initial)
            if len(aw_parts[0]) == 1 and aw_parts[0] == bw_parts[0]:
                results.append((0.80, "initial_match_full_last"))
            # Erster Teil beginnt gleich (z.B. "ma" vs "max")
            elif aw_parts[0].startswith(bw_parts[0][:2]) or bw_parts[0].startswith(aw_parts[0][:2]):
                results.append((0.70, "initial_partial_match"))

    if len(bw_parts) == 2 and len(aw_parts) >= 2:
        # Umgekehrt: "max mustermann" vs "m mustermann"
        if bw_parts[1] == aw_parts[-1]:
            if len(bw_parts[0]) == 1 and bw_parts[0] == aw_parts[0]:
                results.append((0.80, "initial_match_full_last"))
            elif bw_parts[0].startswith(aw_parts[0][:2]) or aw_parts[0].startswith(bw_parts[0][:2]):
                results.append((0.70, "initial_partial_match"))

    # 5. Umgekehrte Schreibweise ("Mustermann, Max") deckt schon normalize_name() ab.

    # 6. Wenn einer nur aus einem Wort besteht und im anderen enthalten ist
    if len(aw_parts) == 1 and len(bw_parts) >= 2:
        if aw_parts[0] in bw_parts:
            results.append((0.60, f"partial: '{aw_parts[0]}' in '{b}'"))
    if len(bw_parts) == 1 and len(aw_parts) >= 2:
        if bw_parts[0] in aw_parts:
            results.append((0.60, f"partial: '{bw_parts[0]}' in '{a}'"))

    return results


def match_person(raw: str, people_dir: Path | None = None,
                 known_persons: list[str] | None = None) -> tuple[str, float, str]:
    """Personennamen mit Entities oder bekannter Liste abgleichen.

    Gibt (canonical_name, score, begruendung) zurueck.

    Parameters
    ----------
    raw : str
        Der rohe Name aus dem Kalender/Meeting.
    people_dir : Path, optional
        Verzeichnis mit Personen-Entities. Wenn gesetzt, werden die Entity-
        Dateinamen (Slug) zur Abgleichung herangezogen.
    known_persons : list[str], optional
        Bereits bekannte Personen-Namen (aus Entities geladen).

    Returns
    -------
    tuple[str, float, str]
        (Name, Score 0-1, Begründung) — '' wenn kein Match.
    """
    norm = _normalize_for_matching(raw)
    if not norm:
        return "", 0.0, "empty"

    best_name, best_score, best_why = raw, 0.0, ""

    # 1. Mit bekannter Personenliste abgleichen
    for person in (known_persons or []):
        norm_person = _normalize_for_matching(person)
        scores = _similarities(norm, norm_person)
        # Beste Similarity nehmen
        if scores:
            score, why = max(scores, key=lambda x: x[0])
            if score > best_score:
                best_name, best_score, best_why = person, score, why

    # 2. Mit Entity-Slugs abgleichen (falls angegeben)
    if people_dir and people_dir.is_dir():
        for entity_file in people_dir.glob("*.md"):
            slug = entity_file.stem  # z.B. "max-mustermann"
            # Slug in Namen umwandeln
            entity_name = slug.replace("-", " ").title()
            norm_entity = _normalize_for_matching(entity_name)
            scores = _similarities(norm, norm_entity)
            if scores:
                score, why = max(scores, key=lambda x: x[0])
                if score > best_score:
                    best_name, best_score, best_why = entity_name, score, f"entity_match({slug})"

    return best_name, best_score, best_why


def _is_initial_variant(a_norm: str, b_norm: str) -> bool:
    """Prüfen ob a_norm "Initial + Nachname" und b_norm "Vorname + Nachname" ist.

    Beispiele:
        "m mustermann" vs "max mustermann"  → True
        "a beispiel" vs "anna beispiel"  → True
        "m mustermann" vs "erika beispiel"  → False
    """
    aw = a_norm.split()
    bw = b_norm.split()
    if len(aw) != 2 or len(bw) < 2:
        return False
    # Letzter Teil (Nachname) muss identisch sein
    if aw[-1] != bw[-1]:
        return False
    # a ist eine Einzel-Initial (1 Zeichen)
    if len(aw[0]) != 1:
        return False
    # Initial muss mit Vorname von b übereinstimmen
    if bw[0] and bw[0][0] == aw[0]:
        return True
    return False


def deduplicate_names(raw_list: list[str],
                      known_persons: list[str] | None = None,
                      people_dir: Path | None = None,
                      min_match_score: float = 0.7) -> list[str]:
    """Namen deduplizieren und mit Entities abgleichen.

    Parameters
    ----------
    raw_list : list[str]
        Rohe, nicht-normalisierte Namen (kann Duplikate enthalten).
    known_persons : list[str], optional
        Bekannte Personen aus Entities.
    people_dir : Path, optional
        Verzeichnis der Personen-Entities.
    min_match_score : float
        Ab diesem Score wird der rohe Name durch den Entity-Namen ersetzt.

    Returns
    -------
    list[str]
        Normalisierte, deduplizierte Liste.
    """
    if not raw_list:
        return []

    # Schritt 1: Mit Entities abgleichen und ersetzen
    matched = []
    for raw in raw_list:
        canonical, score, why = match_person(raw, people_dir, known_persons)
        if score >= min_match_score:
            matched.append(canonical)
        else:
            matched.append(raw)

    # Schritt 2: Normalisieren und Gruppieren
    #    norm → Liste von Original-Namen
    groups: dict[str, list[str]] = {}
    for name in matched:
        norm = _normalize_for_matching(name)
        if norm:
            groups.setdefault(norm, []).append(name)

    # Schritt 3: Volle Namen identifizieren (≥ 2 Wörter, erstes > 1 Zeichen)
    full_norms: set[str] = set()
    for norm in groups:
        parts = norm.split()
        if len(parts) >= 2 and len(parts[0]) > 1:
            full_norms.add(norm)

    # Schritt 4: Initial-Varianten mit vollen Namen zusammenfuegen
    #    "m mustermann" + "max mustermann" → behalte "max mustermann"
    #    Eine Initial-Variante ohne passenden vollen Namen bleibt stehen ("M. Mustermann") -
    #    sonst fiele die Person ganz aus der Liste.
    resolved: dict[str, str] = {}  # norm → best_canonical
    for norm, names in groups.items():
        parts = norm.split()
        is_initial = len(parts) == 2 and len(parts[0]) == 1
        if is_initial and any(_is_initial_variant(norm, full_norm) for full_norm in full_norms):
            continue          # der volle Name steht schon in der Liste
        resolved[norm] = names[0]

    # Schritt 5: Duplikate entfernen (gleicher norm → nur erster)
    seen_norms: set[str] = set()
    unique: list[str] = []
    for norm in resolved:
        if norm in seen_norms:
            continue
        seen_norms.add(norm)
        unique.append(resolved[norm])

    # Schritt 6: Sortiert zurueckgeben
    return sorted(unique, key=lambda n: _normalize_for_matching(n))
