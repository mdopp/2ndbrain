#!/usr/bin/env python3
"""prompt_vergleich.py - vergleicht Prompt-Varianten mit dem Modell auf einer festen Stichprobe.

Entwickler-Werkzeug: liegt nur im Code-Repo (engine/tools), nicht im installierten Paket;
`2ndbrain prompt-vergleich` gibt es nur bei einer Installation aus dem Code-Repo
(`pip install -e engine`).

Der Referenzlauf (referenzlauf.py) prüft nur Code ohne Modell. Ändert sich, was das Modell zu
sehen bekommt (hier: die Beispiele im Prompt des Glossars), braucht es einen Vergleich MIT Modell:
dieselben Begriffe, dieselben Fundstellen, nur der Prompt ist anders. Schreibt nur Bericht und
Rohdaten, nichts ins Glossar; hält währenddessen die Sperre der Automatik.

Glossar: Stichprobe mit bekannter Art, aus dem, was der Vault bestätigt - Systeme der
Systemübersicht (system), Teams/Reihen/Firmen (organisation), Fachobjekte aus dem Kanon
(fachbegriff), Personennamen (rauschen), IT-Standards (allgemein). Kein Begriff der Stichprobe steht
in einem Beispiel irgendeiner Variante (sonst läse das Modell die Antwort ab).
Varianten: hand (Beispiele aus local.config.json) · abgeleitet (die meistgenannten bestätigten
Namen, `glossar.derived_examples`) · ohne (keine Beispiele).

    2ndbrain prompt-vergleich glossar [--laeufe 2] [--je-art 8]
    2ndbrain prompt-vergleich glossar --nur-bericht     # Bericht aus den gespeicherten Rohdaten
Ergebnis: reports/prompt-vergleich-glossar.md, Rohdaten .2ndbrain/daten/prompt-vergleich-glossar.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Entwickler-Werkzeug im Code-Repo: nutzt die Module der Engine aus dem Quelltext daneben
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "secondbrain"))

import vault_paths as vp

if not vp.VAULT_FOUND:
    sys.exit("[ABBRUCH] Kein Vault gefunden - im Vault-Ordner starten oder VAULT_DIR=<Vault> setzen.")

# weltweite IT-Standards, die NICHT schon im Prompt als Beispiel fuer "allgemein" stehen
STANDARDS = ("HTTPS", "JSON", "YAML", "SFTP", "CSV", "FTP", "SOAP", "LDAP", "OAuth", "TLS", "SSH", "SMTP")
IM_PROMPT = {"http", "sql", "xml", "dns", "rest", "php"}
REPORT = vp.VAULT / "reports" / "prompt-vergleich-glossar.md"
RAW = vp.DATA_DIR / "prompt-vergleich-glossar.json"


def _count(term: str, low: list[str]) -> int:
    rx = re.compile(r"(?<![\w-])" + re.escape(term.lower()) + r"(?![\w-])")
    return sum(1 for t in low if rx.search(t))


def glossar_stichprobe(docs, pools, hand: dict[str, str], k_beispiele: int = 3, je_art: int = 8):
    """[(begriff, art)] - je Art die naechsten `je_art` nach den Beispiel-Plaetzen, ohne jedes Beispielwort."""
    ex = {w.strip().lower() for v in (hand or {}).values() for w in str(v).split(",")} | IM_PROMPT
    sample = []
    for art in ("system", "organisation", "fachbegriff"):
        rest = [n for _c, n in pools.get(art, [])[k_beispiele:] if n.lower() not in ex]
        sample += [(n, art) for n in rest[:je_art]]
    low = [t.lower() for _, t in docs]
    people = []
    for f in sorted(vp.CATEGORY_DIRS["people"].glob("*.md")):
        n = str((vp.read_frontmatter(f) or {}).get("name") or "")
        if len(n.split()) >= 2:
            people.append((_count(n, low), n))
    sample += [(n, "rauschen") for c, n in sorted(people, key=lambda x: (-x[0], x[1]))[: je_art * 3 // 4] if c >= 2]
    std = sorted(((_count(s, low), s) for s in STANDARDS), key=lambda x: (-x[0], x[1]))
    sample += [(s, "allgemein") for c, s in std[: je_art * 3 // 4] if c >= 2]
    # feste, gemischte Reihenfolge: jedes Achterpaket enthaelt verschiedene Arten (wie im echten Lauf)
    return sorted(sample, key=lambda x: hashlib.sha1(x[0].encode("utf-8")).hexdigest())


def run_glossar(laeufe: int = 2, je_art: int = 8, llm_call=None) -> dict:
    import glossar as gb
    if llm_call is None:
        import modell
        ok, why = modell.available()
        if not ok:
            raise SystemExit(f"Modell nicht erreichbar: {why}")
        llm_call = modell.complete_json
    docs = gb.corpus()
    pools = gb.example_pools(docs)
    hand = gb.configured_examples() or {}
    sample = glossar_stichprobe(docs, pools, hand, je_art=je_art)
    terms = [t for t, _ in sample]
    label = dict(sample)
    abgeleitet = gb.derived_examples(docs, exclude=set(terms), pools=pools)
    varianten = {"hand": hand, "abgeleitet": abgeleitet, "ohne": {}}
    if not hand:
        varianten.pop("hand")
    res: dict = {"stichprobe": sample, "varianten": varianten, "laeufe": defaultdict(list),
                 "gestartet": datetime.now().isoformat(timespec="seconds")}
    for lauf in range(laeufe):
        for name, bsp in varianten.items():
            t0 = time.time()
            out = gb.propose_definitions(terms, docs, llm_call, gb.build_prompt(bsp))
            arten = {t: (out.get(t) or {}).get("art", "—") for t in terms}
            res["laeufe"][name].append({"arten": arten, "sekunden": round(time.time() - t0, 1)})
            print(f"  Lauf {lauf + 1} {name:10} {sum(arten[t] == label[t] for t in terms)}/{len(terms)} richtig "
                  f"({time.time() - t0:.0f} s)", file=sys.stderr)
            RAW.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return res


def report(res: dict) -> str:
    sample = [tuple(x) for x in res["stichprobe"]]
    label = dict(sample)
    arten = ["system", "organisation", "fachbegriff", "allgemein", "rauschen"]
    per_art = Counter(a for _, a in sample)
    lines = ["---", "type: report", f"erstellt: '{res['gestartet'][:10]}'", "---",
             "# Prompt-Vergleich: Beispiele im Glossar-Prompt", "",
             f"Dieselben {len(sample)} Begriffe mit denselben Fundstellen, nur die Beispiele im Prompt sind "
             f"anders; je Variante {len(next(iter(res['laeufe'].values())))} Läufe. Richtig = die Art, die der "
             "Vault bestätigt (System der Systemübersicht, Team/Reihe/Firma, Fachobjekt aus dem Atlas, "
             "Personenname = rauschen, IT-Standard = allgemein).", "",
             "| Variante | Beispiele | richtig | " + " | ".join(f"{a} ({per_art[a]})" for a in arten) + " |",
             "|---|---|---|" + "---|" * len(arten)]
    for name, runs in res["laeufe"].items():
        bsp = res["varianten"][name]
        b = " · ".join(f"{k}: {v}" for k, v in bsp.items()) or "keine"
        tot = [sum(r["arten"][t] == label[t] for t, _ in sample) for r in runs]
        cells = []
        for a in arten:
            ts = [t for t, x in sample if x == a]
            cells.append(" / ".join(str(sum(r["arten"][t] == a for t in ts)) for r in runs))
        lines.append(f"| **{name}** | {b} | {' / '.join(map(str, tot))} von {len(sample)} | " + " | ".join(cells) + " |")
    lines += ["", "## Wo die Varianten auseinanderliegen", "",
              "| Begriff | richtig | " + " | ".join(res["laeufe"]) + " |", "|---|---|" + "---|" * len(res["laeufe"])]
    einig = []
    for t, a in sample:
        got = {n: [r["arten"][t] for r in runs] for n, runs in res["laeufe"].items()}
        alle = {x for v in got.values() for x in v}
        if len(alle) > 1 or any(x != a for v in got.values() for x in v):
            lines.append(f"| {t} | {a} | " + " | ".join(" / ".join(v) for v in got.values()) + " |")
        if len(alle) == 1 and a not in alle:
            einig.append((t, a, next(iter(alle))))
    if einig:
        lines += ["", "## Alle Varianten einig – aber anders als der Vault", "",
                  "Hier liegt es eher an der Einordnung im Vault als am Prompt (eine Seite, die kein System ist; "
                  "eine Firma, die zugleich Plattform ist). Prüfen lohnt sich:", ""]
        lines += [f"- **{t}**: im Vault {a}, das Modell sagt immer {m}" for t, a, m in einig]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prompt-Varianten mit dem Modell vergleichen")
    ap.add_argument("was", choices=["glossar"])
    ap.add_argument("--laeufe", type=int, default=2)
    ap.add_argument("--je-art", type=int, default=8)
    ap.add_argument("--nur-bericht", action="store_true", help="Bericht aus den gespeicherten Rohdaten neu schreiben")
    args = ap.parse_args(argv)
    if args.nur_bericht:
        res = json.loads(RAW.read_text(encoding="utf-8"))
    else:
        import auto                     # die Automatik soll nicht dazwischen das Modell rufen
        if not auto.acquire_lock():
            print("Die Automatik läuft gerade – gleich noch einmal.", file=sys.stderr)
            return 1
        try:
            res = run_glossar(args.laeufe, args.je_art)
        finally:
            auto.release_lock()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report(res), encoding="utf-8", newline="\n")
    print(f"Bericht: {REPORT.relative_to(vp.VAULT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
