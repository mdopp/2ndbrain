#!/usr/bin/env python3
"""kanon.py - liest den Kanon, das fachliche Modell der Organisation, in ein allgemeines Modell.

Der Kanon ist die Quelle der Wahrheit, gegen die der Vault Fragen stellt - ein Domain-Atlas-
Repository oder eine einfache YAML-Datei. Der Vault liest ihn nur (Glossar, Begriffs-Index,
Kontext-Verzeichnis, Auflösen, MCP-Belege) und schlägt Änderungen vor
(`2ndbrain kanon-vorschlaege`) - geschrieben wird er nie vom Vault. Kein eigener Befehl;
`2ndbrain einrichten` zeigt, welcher Kanon gefunden wurde.

Allgemeines Modell (jedes Element mit id, name, aliases, quelle):
  kontexte     owner [..], subdomain, reife (Lebenszyklus), beschreibung
  subdomaenen  art (core/supporting/generic), reife, beschreibung
  objekte      Fachbegriffe (Domänenmodell): namen [..], begriff, definition, kontext, synonyme, stereotyp,
               relationen [{verb, ziel, kardinalitaet, beschreibung}]
  teams        beschreibung
  externe      kategorie (Rolle gegenüber der eigenen Organisation), beschreibung
  nachrichten  produzenten [..], konsumenten [..], typ, reife, beschreibung
  beziehungen  von, zu, typ, reife, beschreibung
  ablaeufe     betrifft [..] (Kontexte), schritte [{kontext, nachricht}] in Reihenfolge, reife, beschreibung

Formate (`kanon` in .2ndbrain/local.config.json: {"format": …, "pfad": …}):
  domain-atlas  YAML-Dateien je Element unter <repo>/canon/{contexts,subdomains,object-refs,teams,
                externals,messages,relations,processes}/ - Rückfall: paths.domain_atlas
  einfach       eine YAML-Datei (Vorlage: kanon.example.yaml), Standard <Vault>/kanon.yaml
Das Regelwerk je Format (Präfixe, Kategorien der Externen, Hinweise, wie ein Vorschlag umgesetzt
wird) steht in REGELN; `name`, `kategorien` und einzelne Regeln (`regeln`) lassen sich in der
Konfiguration überschreiben.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

_DA_DIRS = {"kontexte": "contexts", "subdomaenen": "subdomains", "objekte": "object-refs", "teams": "teams",
            "externe": "externals", "nachrichten": "messages", "beziehungen": "relations", "ablaeufe": "processes"}
ARTEN = tuple(_DA_DIRS)

REGELN = {
    "domain-atlas": {
        "name": "Domain Atlas", "kurz": "Atlas", "genitiv": "des Domain Atlas",
        "des_kurz": "des Atlas", "zum_kurz": "zum Atlas",
        "kontexte_titel": "Domain-Atlas-Kontexte", "kontexte_quelle": "`domain-atlas/canon/contexts/`",
        "element_hinweis": "canon/**/{id}.yaml", "element_beispiel": "ctx-…, msg-…, proc-…",
        "praefix": {"kontext": "ctx-", "extern": "ext-", "subdomain": "sd-", "team": "team-", "objekt": "obj-",
                    "ablauf": "proc-", "beziehung": "rel-", "nachricht": "msg-"},
        "owner_offen": "team-unresolved",
        "kategorien": [("partner", "Ja – Partner mit Schnittstelle"), ("lieferant", "Ja – Lieferant/Dienstleister"),
                       ("kunde", "Ja – als Kunde")],
        "kategorie_kunde": "kunde",
        "kategorien_text": "Partner · Lieferant · Kunde · Behörde",
        "extern_heisst": "als `ext-`", "kontext_heisst": "ein Kontext (`ctx-`)",
        "extern_fehlt": "im Kanon noch kein `ext-`.",
        "kunde_allgemein": "im Kanon gibt es bisher nur das allgemeine `ext-kunde`.",
        "kein_rel": "im Kanon keine gemeinsame Nachricht und kein `rel-`.",
        "ctx_statt_ext": "Eigenes System – Kontext statt ext-",
        "owner_hinweis": "Ein Owner-Wechsel braucht im Atlas eine zweite Person (Vier-Augen).",
        "beziehung_hinweis": ("Der Atlas typisiert Beziehungen als DDD-Grenze – der Typ wird nicht aus der bloßen "
                              "Schnittstelle geraten."),
        "ablauf_hinweis": ("Nachricht (`msg-`) = ein Datum, das eine Kontextgrenze überquert (event/command/"
                           "query); Prozess (`proc-`) = die Reihenfolge solcher Nachrichten."),
        "vormerken": "„Ja …“ merkt für den Atlas vor – das Paket `reports/atlas-review-<datum>.md` nimmst du ins Atlas-Repo.",
        "bericht_ja": ("**Ja …** merkt für den Atlas vor: das Paket `reports/atlas-review-<datum>.md` (Entscheidung + konkreter "
                       "Vorschlag + Belege) nimmst du ins Atlas-Repo."),
        "paket_kopf": ("Übergabe ans Atlas-Repo: die Vorschläge unten dort umsetzen, Owner-Wechsel mit Vier-Augen. "
                       "Belege über den Vault-MCP (`atlas_evidence`, `search_notes`)."),
        "vorschlag": {
            "ext": ("`ext-{ident}` anlegen, category `{cat}` – Beschreibung aus [[{slug}]]. Danach klären: "
                    "(1) welche Nachrichten laufen über {name}, in welche Richtung; (2) nur ein Produkt oder "
                    "produktübergreifend; (3) Beziehungstyp, z. B. ACL oder Conformist – nicht raten."),
            "ctx": "Prüfen, ob {name} ein eigener Kontext (`ctx-`) ist – Subdomäne und Owner klären.",
            "owner:ja": "Owner von `{c}` auf `{t}` ändern – Owner-Wechsel mit Vier-Augen.",
            "rel:ab": "`rel-` zwischen `{a}` und `{b}`, Typ Customer-Supplier: `{a}` liefert (Supplier), `{b}` nutzt (Customer).",
            "rel:ba": "`rel-` zwischen `{a}` und `{b}`, Typ Customer-Supplier: `{b}` liefert (Supplier), `{a}` nutzt (Customer).",
            "rel:partnership": "`rel-` `{a}` ↔ `{b}`, Typ Partnership (gegenseitig eng abgestimmt).",
            "rel:offen": "`rel-` zwischen `{a}` und `{b}` – Typ im Atlas klären (Kandidaten nennen, nicht raten).",
            "flow:msg": ("Fehlende Nachricht (`msg-`) mit `{c}`: welches Datum, producers/consumers, type "
                         "event/command/query klären."),
            "flow:proc": "Prozess (`proc-`) mit `{c}` als Reihenfolge vorhandener Nachrichten beschreiben.",
            "begriff:alias": "Bei `{t}` den Alias „{name}“ ergänzen (`aliases:`) – Belege: [[{slug}]].",
            "begriff:objekt": ("Fachbegriff „{name}“ als `obj-{ident}` anlegen – Kontext, Definition und Synonyme "
                               "klären; Belege: [[{slug}]]."),
            "team:neu": "Team `team-{ident}` („{name}“) anlegen – für welche Kontexte zuständig? Belege: [[{slug}]].",
        },
        "begriff_hinweis": ("Der Atlas ist der Wortschatz: was hier oft gesagt wird, gehört als Begriff, Alias oder "
                            "Team hinein – oder bewusst nicht."),
    },
    "einfach": {
        "name": "Kanon", "kurz": "Kanon", "genitiv": "des Kanons",
        "des_kurz": "des Kanons", "zum_kurz": "zum Kanon",
        "kontexte_titel": "Kanon-Kontexte", "kontexte_quelle": "der Kanon-Datei",
        "element_hinweis": "kanon.yaml", "element_beispiel": "IDs aus kanon.yaml",
        "praefix": {},
        "owner_offen": "",
        "kategorien": [("partner", "Ja – Partner mit Schnittstelle"), ("lieferant", "Ja – Lieferant/Dienstleister"),
                       ("kunde", "Ja – als Kunde")],
        "kategorie_kunde": "kunde",
        "kategorien_text": "Partner · Lieferant · Kunde · Behörde",
        "extern_heisst": "als Externe", "kontext_heisst": "ein Kontext",
        "extern_fehlt": "im Kanon noch nicht unter den Externen.",
        "kunde_allgemein": "im Kanon stehen Kunden bisher nur allgemein.",
        "kein_rel": "im Kanon keine gemeinsame Nachricht und keine Beziehung.",
        "ctx_statt_ext": "Eigenes System – Kontext statt Externer",
        "owner_hinweis": "",
        "beziehung_hinweis": "Der Beziehungstyp wird nicht aus der bloßen Schnittstelle geraten.",
        "ablauf_hinweis": ("Nachricht = ein Datum, das eine Kontextgrenze überquert; Ablauf = die Reihenfolge "
                           "solcher Nachrichten."),
        "vormerken": "„Ja …“ merkt für den Kanon vor – das Paket `reports/atlas-review-<datum>.md` überträgst du in die Kanon-Datei.",
        "bericht_ja": ("**Ja …** merkt für den Kanon vor: das Paket `reports/atlas-review-<datum>.md` (Entscheidung + konkreter "
                       "Vorschlag + Belege) überträgst du in die Kanon-Datei."),
        "paket_kopf": "Übernehmen: die Vorschläge unten in die Kanon-Datei eintragen (Einträge als YAML).",
        "vorschlag": {
            "ext": ("Unter `externe:` eintragen: `- {{name: {name}, kategorie: {cat}}}` – Beschreibung aus [[{slug}]]. "
                    "Danach klären: (1) welche Nachrichten laufen über {name}, in welche Richtung; (2) nur ein Produkt "
                    "oder produktübergreifend; (3) Beziehungstyp – nicht raten."),
            "ctx": "Prüfen, ob {name} ein eigener Kontext ist – unter `kontexte:` mit Subdomäne und Owner eintragen.",
            "owner:ja": "Beim Kontext `{c}` den Owner setzen: `owner: [{t}]`.",
            "rel:ab": "Unter `beziehungen:` eintragen: `- {{von: {a}, zu: {b}, typ: customer-supplier}}` – `{a}` liefert, `{b}` nutzt.",
            "rel:ba": "Unter `beziehungen:` eintragen: `- {{von: {b}, zu: {a}, typ: customer-supplier}}` – `{b}` liefert, `{a}` nutzt.",
            "rel:partnership": "Unter `beziehungen:` eintragen: `- {{von: {a}, zu: {b}, typ: partnership}}`.",
            "rel:offen": "Beziehung zwischen `{a}` und `{b}` – Typ klären (Kandidaten nennen, nicht raten).",
            "flow:msg": "Fehlende Nachricht mit `{c}`: unter `nachrichten:` mit Name, von und an eintragen.",
            "flow:proc": "Ablauf mit `{c}` unter `ablaeufe:` als Reihenfolge vorhandener Nachrichten beschreiben.",
            "begriff:alias": "Beim Eintrag `{t}` unter `aliases:` „{name}“ ergänzen – Belege: [[{slug}]].",
            "begriff:objekt": ("Unter `begriffe:` eintragen: `- {{name: {name}, kontext: …, definition: …}}` – "
                               "Belege: [[{slug}]]."),
            "team:neu": "Unter `teams:` eintragen: `- {{name: {name}}}` – zuständige Kontexte klären.",
        },
        "begriff_hinweis": "Der Kanon ist der Wortschatz: was hier oft gesagt wird, gehört als Begriff, Alias oder Team hinein.",
    },
}


def konfig() -> dict:
    """{"format", "pfad"} - `kanon` in local.config.json, sonst der Domain Atlas unter
    paths.domain_atlas / VAULT_DOMAIN_ATLAS / neben dem Vault. {} = kein Kanon."""
    c = vp.local_config().get("kanon")
    c = c if isinstance(c, dict) else {}
    extra = {k: c[k] for k in ("name", "kategorien", "regeln") if c.get(k)}
    if c.get("format") in REGELN:
        fmt = c["format"]
        pfad = c.get("pfad") or ("kanon.yaml" if fmt == "einfach" else "")
        p = Path(str(pfad)).expanduser() if pfad else vp.external_path("domain_atlas")
        if p is not None and not p.is_absolute():
            p = vp.VAULT / p
        return {"format": fmt, "pfad": p, **extra}
    p = vp.external_path("domain_atlas")
    return {"format": "domain-atlas", "pfad": p, **extra} if p else {}


def regeln(fmt: str | None = None) -> dict:
    """Regelwerk des eingestellten Formats (Konfiguration kann name/kategorien überschreiben)."""
    cfg = konfig()
    r = dict(REGELN.get(fmt or cfg.get("format") or "domain-atlas") or REGELN["domain-atlas"])
    r["vorschlag"] = dict(r["vorschlag"])
    if fmt:
        return r
    if cfg.get("name"):
        r["name"] = r["kurz"] = str(cfg["name"])
    # Hausregeln einer Organisation (Kategorien, Hinweise, Umsetzung) stehen in der Konfiguration:
    # "kanon": {"regeln": {"owner_hinweis": "…", "vorschlag": {"owner:ja": "…"}, …}}
    for key, val in (cfg.get("regeln") or {}).items():
        if key == "vorschlag" and isinstance(val, dict):
            r["vorschlag"].update(val)
        elif key in r:
            r[key] = val
    kats = cfg.get("kategorien") or (cfg.get("regeln") or {}).get("kategorien")
    if isinstance(kats, list):
        r["kategorien"] = [(str(k[0]), str(k[1])) if isinstance(k, (list, tuple)) else (str(k), f"Ja – {str(k).capitalize()}")
                           for k in kats]
    return r


def strip_prefix(eid: str, art: str | None = None, fmt: str | None = None) -> str:
    """ID ohne Format-Präfix (ctx-…, sd-…); ohne `art` jedes bekannte Präfix."""
    pre = regeln(fmt)["praefix"]
    for p in ([pre.get(art, "")] if art else pre.values()):
        if p and eid.startswith(p):
            return eid[len(p):]
    return eid


def _list(v) -> list:
    return [v] if isinstance(v, (str, dict)) else list(v or [])


def _knoten(v) -> str:
    """Ein Eintrag unter producers/consumers: die ID - auch in der Form `{node: ctx-…, lifecycle: …}`."""
    if isinstance(v, dict):
        return str(v.get("node") or v.get("id") or "").strip()
    return str(v or "").strip()


def _reife(v) -> str:
    """Reifegrad (`lifecycle`) aus `status: {lifecycle: …}` oder einem Kanten-Eintrag; "" ohne Angabe."""
    if isinstance(v, dict):
        inner = v.get("status") if isinstance(v.get("status"), dict) else v
        return str(inner.get("lifecycle") or "").strip()
    return ""


def _relationen(v) -> list[dict]:
    """Relationen eines Fachobjekts (Domänenmodell): [{verb, ziel, kardinalitaet, beschreibung}]."""
    return [{"verb": str(r.get("verb") or "").strip(), "ziel": str(r.get("ziel") or "").strip(),
             "kardinalitaet": str(r.get("kardinalitaet") or "").strip(), "beschreibung": str(r.get("beschreibung") or "").strip()}
            for r in _list(v) if isinstance(r, dict) and r.get("ziel")]


def _schritte(v, kontext_key: str, nachricht_key: str) -> list[dict]:
    """Schritte eines Ablaufs in Reihenfolge (`order`, sonst wie notiert): [{kontext, nachricht}]."""
    items = [x for x in _list(v) if isinstance(x, dict)]
    items = sorted(enumerate(items), key=lambda ix: (ix[1].get("order") if isinstance(ix[1].get("order"), int) else ix[0], ix[0]))
    return [{"kontext": str(x.get(kontext_key) or "").strip(), "nachricht": str(x.get(nachricht_key) or "").strip()}
            for _, x in items if x.get(kontext_key) or x.get(nachricht_key)]


# ------------------------------------------------------------------ Adapter

def _domain_atlas(root: Path | None) -> dict | None:
    canon = root / "canon" if root else None
    if not canon or not canon.is_dir():
        return None
    import yaml
    raw: dict[str, list[tuple[str, dict]]] = {}
    for art, d in _DA_DIRS.items():
        items = []
        for f in sorted((canon / d).glob("*.yaml")) if (canon / d).is_dir() else []:
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            if isinstance(data, dict):
                items.append((f"{d}/{f.name}", {**data, "_datei": f.stem}))
        raw[art] = items
    k: dict = {"format": "domain-atlas", "root": root}
    k["kontexte"] = [{"id": d.get("id"), "name": d.get("name"), "datei": d["_datei"],
                      "owner": [str(o) for o in _list(d.get("owner"))], "subdomain": d.get("primarySubdomain") or "",
                      "reife": _reife(d), "beschreibung": d.get("description") or "",
                      "aliases": _list(d.get("aliases")), "quelle": q}
                     for q, d in raw["kontexte"]]
    k["subdomaenen"] = [{"id": d.get("id"), "name": d.get("name"), "aliases": _list(d.get("aliases")),
                         "art": str(d.get("kind") or ""), "beschreibung": str(d.get("description") or ""),
                         "reife": str((d.get("status") or {}).get("lifecycle") or "")
                         if isinstance(d.get("status"), dict) else "", "quelle": q}
                        for q, d in raw["subdomaenen"]]
    k["objekte"] = [{"id": d.get("id"), "namen": [d.get("concept"), d.get("displayName"), d.get("conceptDe")]
                     + _list(d.get("aliases")), "begriff": d.get("displayName") or d.get("concept"),
                     "definition": d.get("definition"), "kontext": d.get("context"),
                     "synonyme": _list(d.get("aliases")), "name": d.get("displayName") or d.get("concept"),
                     "stereotyp": str(d.get("stereotyp") or ""), "relationen": _relationen(d.get("relationen")),
                     "aliases": _list(d.get("aliases")), "quelle": q} for q, d in raw["objekte"]]
    k["teams"] = [{"id": d.get("id"), "name": d.get("name"), "aliases": _list(d.get("aliases")),
                   "beschreibung": str(d.get("description") or ""), "quelle": q}
                  for q, d in raw["teams"]]
    k["externe"] = [{"id": d.get("id"), "name": d.get("name"), "kategorie": d.get("category") or "",
                     "beschreibung": str(d.get("description") or ""),
                     "aliases": _list(d.get("aliases")), "quelle": q} for q, d in raw["externe"]]
    k["nachrichten"] = [{"id": d.get("id"), "name": d.get("name"), "typ": str(d.get("type") or ""),
                         "reife": _reife(d.get("status")),
                         "beschreibung": str(d.get("description") or ""),
                         "produzenten": [_knoten(x) for x in _list(d.get("producers")) if _knoten(x)],
                         "konsumenten": [_knoten(x) for x in _list(d.get("consumers")) if _knoten(x)],
                         # eigene Reife einzelner Kanten (`{node, lifecycle}`), sonst gilt die der Nachricht
                         "kanten_reife": {_knoten(x): _reife(x) for x in
                                          _list(d.get("producers")) + _list(d.get("consumers"))
                                          if isinstance(x, dict) and _knoten(x) and _reife(x)},
                         "aliases": [], "quelle": q}
                        for q, d in raw["nachrichten"]]
    k["beziehungen"] = [{"id": d.get("id"), "von": str(d.get("from")), "zu": str(d.get("to")), "typ": d.get("type") or "",
                         "reife": _reife(d), "beschreibung": str(d.get("description") or ""),
                         "name": d.get("name"), "aliases": [], "quelle": q} for q, d in raw["beziehungen"]]
    k["ablaeufe"] = [{"id": d.get("id"), "name": d.get("name"), "reife": _reife(d),
                      "beschreibung": str(d.get("description") or ""),
                      "betrifft": [str(x) for x in _list(d.get("appliesTo")) if x],
                      "schritte": _schritte(d.get("steps"), "context", "ref"),
                      "aliases": [], "quelle": q} for q, d in raw["ablaeufe"]]
    k["_roh"] = {q.split("/")[1].rsplit(".", 1)[0]: (q, d) for items in raw.values() for q, d in items}
    return k


def _einfach(path: Path | None) -> dict | None:
    """Eine YAML-Datei mit Listen (kontexte, subdomaenen, begriffe/objekte, teams, externe,
    nachrichten, beziehungen, ablaeufe); IDs ohne Angabe aus dem Namen."""
    if path is not None and path.is_dir():
        path = path / "kanon.yaml"
    if not path or not path.is_file():
        return None
    import yaml
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"[WARN] Kanon {path.name} nicht lesbar: {type(e).__name__}", file=sys.stderr)
        return None
    if not isinstance(doc, dict):
        return None
    q = path.name

    def items(key: str) -> list[dict]:
        return [x for x in (doc.get(key) or []) if isinstance(x, dict) and (x.get("name") or x.get("id"))]

    def eid(x: dict) -> str:
        return str(x.get("id") or vp.slugify(x.get("name")))

    def al(x: dict, *keys) -> list[str]:
        return [str(a) for key in keys for a in _list(x.get(key))]
    k: dict = {"format": "einfach", "root": path, "name": doc.get("name")}
    k["kontexte"] = [{"id": eid(x), "name": x.get("name") or eid(x), "datei": eid(x),
                      "owner": [str(o) for o in _list(x.get("owner"))], "subdomain": str(x.get("subdomain") or ""),
                      "reife": str(x.get("reife") or ""), "beschreibung": str(x.get("beschreibung") or ""),
                      "aliases": al(x, "aliases"), "quelle": q}
                     for x in items("kontexte")]
    k["subdomaenen"] = [{"id": eid(x), "name": x.get("name") or eid(x), "aliases": al(x, "aliases"),
                         "art": str(x.get("art") or ""), "reife": str(x.get("reife") or ""),
                         "beschreibung": str(x.get("beschreibung") or ""), "quelle": q}
                        for x in items("subdomaenen")]
    k["objekte"] = [{"id": eid(x), "namen": [x.get("name")] + al(x, "synonyme", "aliases"), "begriff": x.get("name"),
                     "definition": x.get("definition"), "kontext": x.get("kontext"),
                     "synonyme": al(x, "synonyme", "aliases"), "name": x.get("name"),
                     "stereotyp": str(x.get("stereotyp") or ""), "relationen": _relationen(x.get("relationen")),
                     "aliases": al(x, "synonyme", "aliases"), "quelle": q}
                    for x in items("begriffe") + items("objekte")]
    k["teams"] = [{"id": eid(x), "name": x.get("name") or eid(x), "aliases": al(x, "aliases"),
                   "beschreibung": str(x.get("beschreibung") or ""), "quelle": q}
                  for x in items("teams")]
    k["externe"] = [{"id": eid(x), "name": x.get("name") or eid(x), "kategorie": str(x.get("kategorie") or ""),
                     "beschreibung": str(x.get("beschreibung") or ""),
                     "aliases": al(x, "aliases"), "quelle": q} for x in items("externe")]
    k["nachrichten"] = [{"id": eid(x), "name": x.get("name"), "typ": str(x.get("typ") or x.get("type") or ""),
                         "reife": str(x.get("reife") or ""), "beschreibung": str(x.get("beschreibung") or ""),
                         "produzenten": [_knoten(v) for v in _list(x.get("von")) if _knoten(v)],
                         "konsumenten": [_knoten(v) for v in _list(x.get("an")) if _knoten(v)],
                         "kanten_reife": {}, "aliases": [], "quelle": q}
                        for x in items("nachrichten")]
    k["beziehungen"] = [{"id": str(x.get("id") or f"{x.get('von')}-{x.get('zu')}"), "von": str(x.get("von")),
                         "zu": str(x.get("zu")), "typ": str(x.get("typ") or ""), "name": x.get("name"),
                         "reife": str(x.get("reife") or ""), "beschreibung": str(x.get("beschreibung") or ""),
                         "aliases": [], "quelle": q}
                        for x in (doc.get("beziehungen") or []) if isinstance(x, dict) and x.get("von") and x.get("zu")]
    k["ablaeufe"] = [{"id": eid(x), "name": x.get("name") or eid(x), "reife": str(x.get("reife") or ""),
                      "beschreibung": str(x.get("beschreibung") or ""), "betrifft": al(x, "betrifft"),
                      "schritte": _schritte(x.get("schritte"), "kontext", "nachricht"),
                      "aliases": [], "quelle": q} for x in items("ablaeufe")]
    return k


def lade() -> dict | None:
    """Kanon im allgemeinen Modell - oder None (keiner eingerichtet oder nicht lesbar)."""
    cfg = konfig()
    if not cfg:
        return None
    k = _domain_atlas(cfg["pfad"]) if cfg["format"] == "domain-atlas" else _einfach(cfg["pfad"])
    if k is not None:
        k["regeln"] = regeln()
        if k.get("name"):
            k["regeln"] = {**k["regeln"], "name": str(k["name"]), "kurz": str(k["name"])}
    return k


def element(k: dict | None, eid: str) -> dict | None:
    """Ein Element per ID: {"art", "id", "name", "aliases", "beschreibung", "quelle"} (für MCP-Belege)."""
    if not k:
        return None
    if k.get("format") == "domain-atlas":           # Domain Atlas: Datei <id>.yaml, Felder roh
        q, d = (k.get("_roh") or {}).get(eid, (None, None))
        if q is None:
            return None
        return {"art": next((a for a, sub in _DA_DIRS.items() if q.startswith(sub + "/")), ""), "id": eid,
                "name": str(d.get("name") or eid), "aliases": [str(a) for a in d.get("aliases") or d.get("synonyms") or []],
                "beschreibung": d.get("description") or "", "quelle": q}
    for art in ARTEN:
        for x in k.get(art) or []:
            if str(x.get("id")) == eid:
                return {"art": art, "id": eid, "name": str(x.get("name") or eid), "aliases": list(x.get("aliases") or []),
                        "beschreibung": x.get("beschreibung") or x.get("definition") or "", "quelle": x.get("quelle") or ""}
    return None
