#!/usr/bin/env python3
"""aufloesen.py - einen Begriff deterministisch aufloesen: Kanon (Atlas), C4 oder Vault.

Die Entscheidung Atlas -> C4 -> Vault ist ein reiner Lookup: kein
Interpretationsproblem, also keine Aufgabe fuers Modell; auch die Alias-Suche ist
exakte Mengenarbeit. Personen (auch ein blosser Vorname) loest `_resolve_person()`
gegen `entities/people/` auf - bei Mehrdeutigkeit wird nie geraten, die Kandidaten
kommen zurueck. Kanon und C4 werden eine Stunde gecacht (`--refresh` liest neu).

Pfade: A = Kanon/Atlas, C = C4, B = Vault. Treffer-Qualitaet und passende
Kategorie gehen vor Quellen-Prioritaet (siehe `resolve()`).

Ausgabe-Kontrakt:
    {"term", "resolved": "atlas|c4|vault|ambiguous|unknown", "path": "A|B|C|null",
     "slug", "name", "matched_on", "aliases", "candidates", "sources": {...}}

    2ndbrain aufloesen "System X" [--json] [--refresh] [--kind system]
    2ndbrain aufloesen --batch begriffe.txt --json
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

# Optionaler Structurizr-Export von c4_creator; fehlt die Datei, bleibt die C4-Quelle leer.
# (Das LikeC4-Modell der Systemuebersicht liest dieses Modul nicht.)
C4_WORKSPACE = Path.home() / "code" / "c4_creator" / "output" / "workspace.json"
CACHE_FILE = vp.DATA_DIR / ".resolve_cache.json"
CACHE_TTL = 3600
FUZZY_CUTOFF = 0.82


def norm(s: str) -> str:
    """Vergleichsform: Kleinschreibung, Umlaute, Satzzeichen weg."""
    s = str(s or "").lower().strip()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ---------------------------------------------------------------- Atlas

ATLAS_KINDS = ("context", "team", "subdomain", "object-ref", "process")


_KIND = {"kontexte": "context", "teams": "team", "subdomaenen": "subdomain", "objekte": "object-ref",
         "ablaeufe": "process"}


def _kanon_items() -> list[dict]:
    """Elemente aus dem Kanon (kanon.py) im Format der Atlas-Abfrage: id, kind, name."""
    import kanon
    k = kanon.lade()
    return [{"id": x.get("id"), "kind": kind, "name": x.get("name"), "lifecycle": ""}
            for art, kind in _KIND.items() for x in (k or {}).get(art) or []]


def _load_atlas(refresh: bool = False) -> list[dict]:
    """Kanon pro Kind abfragen. Beim Domain Atlas ueber dessen Werkzeug, sonst -
    und ohne Werkzeug - direkt aus dem Kanon (kanon.py).

    `bin/atlas.mjs` direkt aufrufen, nicht `npm run atlas` - letzteres haengt ein
    `tsc --build` vor *jeden* Aufruf. `stdin=DEVNULL` ist notwendig: mit geerbtem
    stdin blockiert der CLI (der `author`-Pfad liest von stdin).
    """
    import kanon
    cfg = kanon.konfig()
    if cfg.get("format") != "domain-atlas":
        return _kanon_items()
    repo = cfg.get("pfad")
    atlas_bin = repo / "packages" / "agent" / "bin" / "atlas.mjs" if repo else None
    if not atlas_bin or not atlas_bin.exists():
        return _kanon_items()
    items: list[dict] = []
    for kind in ATLAS_KINDS:
        try:
            proc = subprocess.run(
                ["node", str(atlas_bin), "query", "--kind", kind],
                cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
                stdin=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"[WARN] Atlas '{kind}' nicht abfragbar: {e}", file=sys.stderr)
            continue
        if proc.returncode != 0:
            print(f"[WARN] Atlas '{kind}': {proc.stderr.strip()[:160]}", file=sys.stderr)
            continue
        try:
            items.extend(json.loads(proc.stdout).get("items", []))
        except (json.JSONDecodeError, AttributeError):
            print(f"[WARN] Atlas '{kind}': Antwort kein JSON", file=sys.stderr)
    return items


# ---------------------------------------------------------------- C4

def _load_c4() -> list[dict]:
    """Structurizr-Format: .model.softwareSystems / .containers / .people.

    Nicht `.elements[]` - so sieht ein Structurizr-Export nicht aus.
    """
    if not C4_WORKSPACE.exists():
        return []
    try:
        ws = json.loads(C4_WORKSPACE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[WARN] C4-Workspace nicht lesbar: {e}", file=sys.stderr)
        return []
    model = ws.get("model", {})
    out = []
    for key, kind in (("softwareSystems", "SoftwareSystem"),
                      ("containers", "Container"),
                      ("people", "Person")):
        for el in model.get(key) or []:
            out.append({
                "id": el.get("id"),
                "name": el.get("name"),
                "kind": kind,
                "description": el.get("description", ""),
                "technology": el.get("technology", ""),
                "tags": el.get("tags", ""),
            })
        for sys_el in model.get("softwareSystems") or []:
            for c in sys_el.get("containers") or []:
                out.append({
                    "id": c.get("id"), "name": c.get("name"), "kind": "Container",
                    "description": c.get("description", ""),
                    "technology": c.get("technology", ""), "tags": c.get("tags", ""),
                    "parent": sys_el.get("name"),
                })
        break_after = key == "people"
        if break_after:
            break
    # Duplikate (Container doppelt erfasst) entfernen
    seen, uniq = set(), []
    for e in out:
        k = (e["kind"], e["name"])
        if e["name"] and k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


# ---------------------------------------------------------------- Index

def build_index(refresh: bool = False) -> dict:
    if not refresh and CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - cached.get("_built_at", 0) < CACHE_TTL:
                # Vault-Aliasse immer frisch: eine gerade angelegte Person oder
                # ein neues Thema muss sofort aufloesbar sein - aus dem Cache
                # (TTL 1h) waeren sie bis zum Refresh unsichtbar.
                cached["vault_aliases"] = vp.alias_map()
                return cached
        except (OSError, json.JSONDecodeError):
            pass

    atlas = _load_atlas(refresh)
    c4 = _load_c4()
    index = {"_built_at": time.time(), "atlas": atlas, "c4": c4}
    try:
        CACHE_FILE.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8", newline="\n")
    except OSError:
        pass
    index["vault_aliases"] = vp.alias_map()
    return index


# ---------------------------------------------------------------- Aufloesung

def _match(term: str, items: list[dict], name_keys=("name", "id")) -> tuple[dict | None, str]:
    """Exakt -> Teilstring -> Fuzzy. Gibt (treffer, matched_on) zuruck."""
    nt = norm(term)
    if not nt:
        return None, ""
    by_norm: dict[str, dict] = {}
    for it in items:
        for k in name_keys:
            v = it.get(k)
            if v:
                by_norm.setdefault(norm(v), it)
    if nt in by_norm:
        return by_norm[nt], "exact"
    for key, it in by_norm.items():
        if nt and (nt == key or (len(nt) > 3 and nt in key.split())):
            return it, "token"
    close = difflib.get_close_matches(nt, list(by_norm), n=1, cutoff=FUZZY_CUTOFF)
    if close:
        return by_norm[close[0]], f"fuzzy:{close[0]}"
    return None, ""


_PERSON_FORMS: dict = {"key": None, "rows": []}


def _person_forms() -> list[tuple]:
    """(slug, name, Namensformen, Namensteile) je Person - einmal pro Prozess.

    Ein Frontmatter-Read pro Person und aufgeloestem Begriff wuerde bei einigen
    hundert Personen (etwa aus einem Organigramm) mehrere Sekunden je Paket kosten.
    """
    try:
        mtime = vp.PEOPLE_DIR.stat().st_mtime
    except OSError:
        mtime = 0
    cache_key = (str(vp.PEOPLE_DIR), vp.cache_epoch(), mtime)
    if _PERSON_FORMS["key"] == cache_key:
        return _PERSON_FORMS["rows"]
    rows = []
    files = [vp.PEOPLE_DIR / f"{s}.md" for s in vp.entity_slugs("people")]
    for path, text in vp._read_many(files):
        fm = vp.split_frontmatter(text)[0] if text else {}
        slug = path.stem
        forms = {norm(slug), norm(str(fm.get("name", "")))}
        al = fm.get("aliases") or []
        if isinstance(al, str):
            al = [al]
        forms |= {norm(str(a)) for a in al}
        # Vor- und Nachnamensbestandteile
        parts = set()
        for f in list(forms):
            parts |= {w for w in f.split() if len(w) > 2}
        parts |= {w for w in slug.split("-") if len(w) > 2}
        rows.append((slug, fm.get("name") or slug, forms, parts))
    _PERSON_FORMS.update(key=cache_key, rows=rows)
    return rows


def _resolve_person(term: str) -> dict | None:
    """Vornamen gegen `entities/people/` aufloesen.

    In Protokollen steht "Max", nicht "max-mustermann". Der Alias-Index
    kennt nur Slug, `name` und explizite `aliases` - ein blosser Vorname liefe
    deshalb auf `unknown`, und die Atlas-Fuzzy-Suche bildete ihn auf Unsinn
    ab ("Max" -> "Maximum").

    Bei Mehrdeutigkeit wird **nicht** geraten: es kommen alle Treffer als
    Kandidaten zurueck, damit die Rueckfrage an den Benutzer geht.
    """
    nt = norm(term)
    if not nt:
        return None
    hits = []
    for slug, name, forms, parts in _person_forms():
        # Vollname, Slug, Alias oder einzelner Namensbestandteil
        if nt in forms or (" " not in nt and nt in parts):
            hits.append({"slug": slug, "name": name})
    if not hits:
        return None
    if len(hits) == 1:
        return {"resolved": "vault", "path": "B", "slug": hits[0]["slug"],
                "name": hits[0]["name"], "matched_on": "personen-namensteil",
                "category": "people"}
    return {"resolved": "ambiguous", "path": None, "slug": None, "name": None,
            "matched_on": f"{len(hits)} Personen mit diesem Namensteil",
            "candidates": [{"source": "vault", "slug": h["slug"], "name": h["name"]}
                           for h in hits]}


_PERSON_LINK_RE = re.compile(r"(?:\[\[|@)([a-z0-9][a-z0-9-]+)")


def personen_in(paths) -> set[str]:
    """Personen-Slugs, die in diesen Dateien verlinkt (`[[slug`) oder mit @ genannt sind."""
    people = set(vp.entity_slugs("people"))
    out: set[str] = set()
    for p in paths:
        try:
            text = Path(p).read_text(encoding="utf-8")
        except (OSError, TypeError):
            continue
        out |= {m.group(1) for m in _PERSON_LINK_RE.finditer(text) if m.group(1) in people}
    return out


def im_kontext(candidates: list[dict], context) -> str | None:
    """Der eine Kandidat, der im Kontext steht - sonst None (dann Rueckfrage, nie raten)."""
    ctx = set(context or ())
    in_ctx = [c for c in candidates if c.get("slug") in ctx]
    return in_ctx[0]["slug"] if len(in_ctx) == 1 else None


def resolve_person_in_context(raw: str, context) -> tuple[str | None, list[dict]]:
    """Person aufloesen; Mehrdeutigkeit entscheidet nur der Kontext.

    Kontext = Personen-Slugs, die zum Termin/Thema gehoeren (Teilnehmer,
    key_persons, im Themen-Log verlinkte Personen). "Max" mit drei Max im
    Vault, aber genau einem davon im Kontext -> dieser. Sonst
    `(None, kandidaten)` fuer die Rueckfrage - nie raten.
    """
    hit = _resolve_person(raw)
    if hit is None:
        return None, []
    if hit.get("resolved") != "ambiguous":
        return hit.get("slug"), []
    candidates = hit.get("candidates", [])
    slug = im_kontext(candidates, context)
    return (slug, []) if slug else (None, candidates)


def resolve(term: str, index: dict, kind_hint: str | None = None) -> dict:
    """Entscheidungsmatrix: Atlas -> Pfad A, sonst C4 -> C, sonst Vault -> B.
    Personen gehen vor; Treffer-Qualitaet und Kategorie siehe Ranking unten."""
    result = {
        "term": term,
        "resolved": "unknown",
        "path": None,
        "slug": None,
        "name": None,
        "matched_on": None,
        "aliases": [],
        "sources": {},
    }

    # Name oder Namensteil einer Person: Atlas/C4 duerfen hier nicht raten.
    if kind_hint in (None, "person", "people"):
        person = _resolve_person(term)
        if person:
            result.update(person)
            result.setdefault("sources", {})["vault"] = {
                "slug": person.get("slug"), "category": "people"}
            return result

    # Vault-Alias immer mit ermitteln (auch wenn Atlas gewinnt) - der Vault haelt
    # die Aliasse, die Atlas/C4 nicht kennen.
    aliases = index.get("vault_aliases", {})
    vault_slug = aliases.get(norm(term)) or aliases.get(str(term).strip().lower())
    vault_category = None
    if vault_slug:
        result["sources"]["vault"] = {"slug": vault_slug}
        fm = {}
        for cat in vp.ENTITY_CATEGORIES:
            p = vp.CATEGORY_DIRS[cat] / f"{vault_slug}.md"
            if p.exists():
                fm = vp.read_frontmatter(p)
                result["sources"]["vault"]["category"] = cat
                vault_category = cat
                break
        al = fm.get("aliases") or []
        result["aliases"] = [al] if isinstance(al, str) else [str(a) for a in al]
        # Primaername aus dem Vault mitsuchen: Kuerzel -> Primaername -> Atlas/C4
        search_terms = [term, fm.get("name") or "", *result["aliases"]]
    else:
        search_terms = [term]

    atlas_hit = c4_hit = None
    for st in [s for s in search_terms if s]:
        if atlas_hit is None:
            atlas_hit, atlas_how = _match(st, index.get("atlas", []))
            if atlas_hit:
                result["sources"]["atlas"] = {
                    "id": atlas_hit.get("id"), "kind": atlas_hit.get("kind"),
                    "name": atlas_hit.get("name"), "lifecycle": atlas_hit.get("lifecycle"),
                    "owner": atlas_hit.get("owner"), "subdomain": atlas_hit.get("subdomain"),
                    "matched_on": atlas_how, "via_term": st,
                }
        if c4_hit is None:
            c4_hit, c4_how = _match(st, index.get("c4", []))
            if c4_hit:
                result["sources"]["c4"] = {
                    "id": c4_hit.get("id"), "kind": c4_hit.get("kind"),
                    "name": c4_hit.get("name"), "technology": c4_hit.get("technology"),
                    "description": (c4_hit.get("description") or "")[:200],
                    "matched_on": c4_how, "via_term": st,
                }

    # --- Ranking -------------------------------------------------------------
    # Zwei Regeln:
    #  a) Treffer-QUALITAET schlaegt Quellen-Prioritaet. Ein exakter C4-Treffer
    #     darf nicht von einem Fuzzy-Atlas-Treffer verdraengt werden.
    #  b) KATEGORIE muss passen. Ein Altsystem ist ein Software-System; es auf ein
    #     Atlas-*Team* zu routen (Pfad A) waere ein Kategoriefehler - Systeme
    #     gehoeren nach C4.
    expected = vault_category or kind_hint
    atlas_kind = (atlas_hit or {}).get("kind", "")
    if atlas_hit and expected in ("systems", "system") and atlas_kind in (
            "context", "team", "subdomain", "process", "object-ref"):
        result["sources"]["atlas"]["demoted"] = (
            f"Kategoriekonflikt: Begriff ist ein System, Atlas-Treffer ist '{atlas_kind}'")
        atlas_hit = None

    quality = {"exact": 3, "token": 2}
    def q(how: str) -> int:
        return quality.get((how or "").split(":")[0], 1)

    ranked = []
    if atlas_hit:
        ranked.append((q(result["sources"]["atlas"]["matched_on"]), 3, "atlas"))
    if c4_hit:
        ranked.append((q(result["sources"]["c4"]["matched_on"]), 2, "c4"))
    if vault_slug:
        ranked.append((3, 1, "vault"))
    ranked.sort(reverse=True)

    winner = ranked[0][2] if ranked else None
    if winner == "atlas":
        result.update(resolved="atlas", path="A", slug=atlas_hit.get("id"),
                      name=atlas_hit.get("name"),
                      matched_on=result["sources"]["atlas"]["matched_on"])
    elif winner == "c4":
        # C4-IDs sind laufende Nummern ("27") - als Slug unbrauchbar.
        c4_slug = vault_slug or f"system-{re.sub(r'[^a-z0-9]+', '-', norm(c4_hit.get('name', ''))).strip('-')}"
        result.update(resolved="c4", path="C", slug=c4_slug,
                      name=c4_hit.get("name"),
                      matched_on=result["sources"]["c4"]["matched_on"])
    elif winner == "vault":
        result.update(resolved="vault", path="B", slug=vault_slug, name=vault_slug,
                      matched_on="vault-alias")
    else:
        result["candidates"] = _suggest(term, index)
    return result


def _suggest(term: str, index: dict, n: int = 3) -> list[dict]:
    """Bei Fehlschlag: naheste Namen aus allen Quellen, damit das LLM nicht raet."""
    pool = []
    for it in index.get("atlas", []):
        pool.append((norm(it.get("name", "")), "atlas", it.get("id"), it.get("name")))
    for it in index.get("c4", []):
        pool.append((norm(it.get("name", "")), "c4", it.get("id"), it.get("name")))
    for alias, slug in index.get("vault_aliases", {}).items():
        pool.append((norm(alias), "vault", slug, alias))
    names = [p[0] for p in pool]
    out = []
    for m in difflib.get_close_matches(norm(term), names, n=n, cutoff=0.6):
        for key, src, slug, name in pool:
            if key == m:
                out.append({"source": src, "slug": slug, "name": name})
                break
    return out


def main() -> int:
    args = sys.argv[1:]
    as_json = "--json" in args
    refresh = "--refresh" in args
    terms: list[str] = []
    if "--batch" in args:
        i = args.index("--batch")
        terms = [l.strip() for l in Path(args[i + 1]).read_text(encoding="utf-8").splitlines()
                 if l.strip()]
    else:
        terms = [a for a in args if not a.startswith("--")]
    if not terms:
        print(__doc__)
        return 1

    kind_hint = None
    if "--kind" in args:
        i = args.index("--kind")
        if i + 1 < len(args):
            kind_hint = args[i + 1]
            terms = [t for t in terms if t != kind_hint]

    index = build_index(refresh)
    results = [resolve(t, index, kind_hint) for t in terms]

    if as_json:
        json.dump(results if len(results) > 1 else results[0],
                  sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        for r in results:
            line = f"{r['term']:28} -> {r['resolved']:8} Pfad {r['path'] or '-'}"
            if r["slug"]:
                line += f"  slug={r['slug']}"
            if r["matched_on"]:
                line += f"  ({r['matched_on']})"
            print(line)
            if r["resolved"] == "unknown" and r.get("candidates"):
                for c in r["candidates"]:
                    print(f"      Vorschlag: {c['source']}:{c['slug']} ({c['name']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
