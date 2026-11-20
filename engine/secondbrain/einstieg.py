#!/usr/bin/env python3
"""einstieg.py - der Vault fuer einen Agenten (Claude, Cowork): eine Karte und ein Verzeichnis.

Ein Agent, der den Ordner zum ersten Mal sieht, liest sonst das Teure: die Haelfte des Vaults sind
archivierte Termine, die Antworten stehen auf den wenigen Themen-Seiten. Zwei Dateien richten das:

  CLAUDE.md            die Karte im Vault-Stamm: wo was steht, was zuerst zu lesen ist, was nie, wie
                       eine Aufgabenzeile und ein Log-Eintrag aussehen. Der Text ist fest - er haengt
                       nur davon ab, wer "ich" ist und welche Ordner und Berichte es gibt. Kein Datum,
                       keine Zahlen: die Datei aendert sich nur, wenn sich der Aufbau aendert.
  reports/themen.md    das Themen-Verzeichnis: eine Zeile je Thema (Dach, Rolle, Ampel, offene Punkte,
                       meine, ueberfaellig, Fragen, letzte Bewegung, naechster Termin) - der Einstieg
                       in jede inhaltliche Frage, bevor eine Themen-Seite geoeffnet wird.

Beides rechnet der Code (kein Modell). Die Karte steht zwischen zwei Marken; was ausserhalb steht
(eigene Hinweise an den Agenten), bleibt. Geschrieben wird nur, wenn sich der Inhalt aendert - das
Datum im Verzeichnis allein loest kein Schreiben aus. In der Automatik mit dem Schritt `stand`.

    2ndbrain einstieg            beide Dateien neu (--dry-run | --json)
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
import rollen
import thema_schliessen
import vault_paths as vp

KARTE = "CLAUDE.md"
VERZEICHNIS = "reports/themen.md"
START, ENDE = "<!-- 2ndbrain-karte:start -->", "<!-- 2ndbrain-karte:ende -->"
GRUND_LAENGE = 80            # der Ampel-Grund im Verzeichnis, gekuerzt - ganz steht er auf der Themen-Seite
_AMPEL = {"red": "rot", "yellow": "gelb", "green": "grün"}
_STAND_RE = re.compile(r"^_Stand \d{2}\.\d{2}\.\d{4}", re.MULTILINE)

# Berichte, die die Karte nennt, wenn es sie gibt: (Pfad, wozu)
_BERICHTE = (
    ("reports/lagebild.md", "wer schuldet mir was, wo steht etwas still"),
    ("reports/orgchart.md", "Berichtslinien"),
    ("reports/geprueft.md", "was die Automatik geparkt oder geschlossen hat"),
    ("reports/fokus-spiegel.md", "Fokus-Themen der Woche"),
)
# Was ein Agent nicht liest, wenn es das gibt
_NICHT_LESEN = (".2ndbrain", ".obsidian", "inbox", "archive/migrations", "archive/calendar")


# ------------------------------------------------------------------ Karte

def karte_text() -> str:
    """Der feste Teil der Karte (zwischen den Marken) - ohne Datum und ohne Zahlen, und so kurz wie es
    geht: die Karte steht in jedem Gespraech im Kontext. Was sich aus Ordnernamen, einem Suchmuster oder
    einem Blick in eine Seite ergibt, steht nicht darin."""
    slug = vp.ich()
    name = str(vp.ich_seite().get("name") or "").strip()
    wer = f"{name} (`[[{slug}]]`)" if slug and name else f"`[[{slug}]]`" if slug else "nicht eingetragen"
    was = vp.vault_beschreibung().strip()
    berichte = [f"`{p}` ({wozu})" for p, wozu in _BERICHTE if (vp.VAULT / p).is_file()]
    tabu = [f"`{p}/`" for p in _NICHT_LESEN if (vp.VAULT / p).is_dir()]
    out = [START, "# Karte dieses Vaults", "",
           f"2ndBrain-Vault{' (' + was.rstrip('.') + ')' if was else ''}: eine Engine arbeitet Termine, Mails und "
           f"Dokumente in Themen-Seiten ein. **Ich** = {wer}.", "",
           "## Vorgehen", "",
           f"1. Überblick: `{VERZEICHNIS}` – eine Zeile je Thema (Dach, Rolle, Ampel, offen, meine, bewegt).",
           "2. Inhalt: die Themen-Seite `entities/projects/<slug>.md` – Stand-Block, `## Offene Punkte`, "
           "`## Event Log` (jüngstes oben).",
           "3. Einzelne Punkte, Personen, Zeiträume: suchen (Muster unten), dann nur die Treffer lesen.",
           "4. Quelle hinter einem Punkt oder Eintrag: `(→ [[Notiz]])`; Notizen heißen `JJJJ-MM-TT - art - Titel`.", "",
           "`archive/` ist das Rohmaterial und etwa die Hälfte des Vaults: nie der Reihe nach lesen. "
           "Personen, Teams, Systeme, Begriffe liegen unter `entities/<art>/<slug>.md` – nach Namen öffnen."
           + (f" Weitere Übersichten: {', '.join(berichte)}." if berichte else "")
           + (f" Nicht lesen: {', '.join(tabu)}." if tabu else ""), "",
           "## Suchmuster", "",
           "Reguläre Ausdrücke; Punkte stehen in `active-meetings/`, `archive/meetings/` und `entities/projects/`.", "",
           rf"- Offene Punkte einer Person: `^\s*- \[ \] .* — (an )?\[\[SLUG[|\]]` – meine mit `{slug or 'SLUG'}`",
           r"- Offene Punkte eines Themas: `^\s*- \[ \] .*\[\[THEMA[|\]]`",
           r"- Frist: `📅 JJJJ-MM-TT` in der Zeile · entstanden `➕` · erledigt `[x]` mit `✅` · verworfen oder geparkt `[-]` · "
           "`❓` Frage · `Name (?)` Person offen",
           r"- Log eines Monats: `^- \[JJJJ-MM-\d\d\] \[DECISION\]` (auch `RISK`, `STATUS`, `MILESTONE`, `DEADLINE`)",
           r"- Themen-Frontmatter: `^health: (red|yellow)`, `^parent: .*\[\[DACH`, `^meine_rolle: (fuehre|beteiligt|beobachte)`, `^fokus:`",
           r"- Alles zu einem Namen: `\[\[SLUG[|\]]` – erst nur die Trefferliste", "",
           "Fallen: `- [ ]` ohne ` — ` und Person ist eine Checkliste, keine Aufgabe. Punkte unter "
           f"`{tk.ALTBESTAND_HEADING}` sind ungeprüft übernommen, keine Zusage – die Suche unterscheidet das nicht, "
           "das Verzeichnis schon. Fehlt `meine_rolle`, gilt die des Dachs, sonst `fuehre` (ich halte auch die Punkte "
           "anderer nach; `beteiligt` nur meine, `beobachte` nur den Stand).", "",
           "## Regeln", "",
           "- Nur aus dem Vault antworten, mit Quelle. Was nicht darin steht, nicht ergänzen.",
           "- Nichts löschen, verschieben oder umbenennen. `reports/` und Blöcke zwischen `<!-- …-auto:start/end -->` "
           "ersetzt die Engine – dort nichts ändern. Abhaken (`[x]` und ` ✅ JJJJ-MM-TT`) nur auf Wunsch.",
           "- `.2ndbrain/calendar.config.json` ist ein Zugangsschlüssel: nie öffnen. Namen und Interna aus dem "
           "Vault nicht in Websuchen oder an andere Dienste geben.",
           "", ENDE]
    return "\n".join(out)


def karte_schreiben(*, dry_run: bool = False) -> bool:
    """Den Block zwischen den Marken ersetzen (oder die Datei anlegen); alles ausserhalb bleibt."""
    f = vp.VAULT / KARTE
    block = karte_text()
    alt = f.read_text(encoding="utf-8") if f.is_file() else ""
    if START in alt and ENDE in alt.split(START, 1)[1]:
        davor, rest = alt.split(START, 1)
        neu = davor + block + rest.split(ENDE, 1)[1]
    elif alt.strip():
        neu = alt.rstrip("\n") + "\n\n" + block + "\n"
    else:
        neu = block + "\n\n## Eigene Hinweise\n\n_Was hier steht, bleibt bei jedem Lauf erhalten._\n"
    if neu == alt:
        return False
    if not dry_run:
        f.write_text(neu, encoding="utf-8", newline="\n")
    return True


# ------------------------------------------------------------ Verzeichnis

def _datum(iso) -> str:
    s = str(iso or "")[:10]
    return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else "–"


def themen_zeilen(heute: date | None = None) -> list[dict]:
    """Je Thema eine Zeile, Unterthemen direkt unter ihrem Dach (`tiefe` zaehlt die Stufen)."""
    heute_iso = (heute or date.today()).isoformat()
    ich = vp.ich()
    themen = rollen._themen()
    gilt = rollen.lade(themen)
    offen = tk.open_by_topic()
    rows: dict[str, dict] = {}
    for slug, th in themen.items():
        fm = vp.read_frontmatter_head(th["pfad"])
        if thema_schliessen.abgeschlossen(fm):           # abgeschlossen: nur noch in der Fusszeile
            continue
        ts = offen.get(slug, [])
        fokus = fm.get("fokus")
        rows[slug] = {
            "slug": slug, "titel": th["titel"], "parent": th["parent"] if th["parent"] in themen else "",
            "art": str(fm.get("kind") or ""), "status": str(fm.get("status") or ""),
            "rolle": gilt[slug], "rolle_eingetragen": bool(th["eigene"]),
            "fokus": fokus if isinstance(fokus, int) and not isinstance(fokus, bool) else (1 if th["fokus"] else 0),
            "ampel": _AMPEL.get(str(fm.get("health") or ""), ""), "grund": str(fm.get("ampel_grund") or ""),
            "offen": sum(1 for t in ts if t.kind == tk.KIND_TASK and not t.pruefen),
            "meine": sum(1 for t in ts if t.kind == tk.KIND_TASK and not t.pruefen and ich and t.owner == ich),
            "ueberfaellig": sum(1 for t in ts if not t.pruefen and t.overdue(heute_iso)),
            "fragen": sum(1 for t in ts if t.kind == tk.KIND_QUESTION),
            "altbestand": sum(1 for t in ts if t.pruefen),
            "bewegt": str(fm.get("zuletzt_bewegt") or "")[:10], "termin": str(fm.get("naechster_termin") or "")[:10],
        }
    kinder: dict[str, list[str]] = {}
    for slug, r in rows.items():
        kinder.setdefault(r["parent"], []).append(slug)
    out: list[dict] = []
    gesehen: set[str] = set()

    def lauf(slug: str, tiefe: int) -> None:
        if slug in gesehen:
            return
        gesehen.add(slug)
        out.append({**rows[slug], "tiefe": tiefe})
        for k in sorted(kinder.get(slug, []), key=lambda s: rows[s]["titel"].casefold()):
            lauf(k, tiefe + 1)

    for slug in sorted(kinder.get("", []), key=lambda s: rows[s]["titel"].casefold()):
        lauf(slug, 0)
    for slug in sorted(rows):                       # ein Kreis in `parent` haengt an keiner Wurzel
        lauf(slug, 0)
    return out


def verzeichnis_text(heute: date | None = None) -> str:
    heute = heute or date.today()
    rows = themen_zeilen(heute)
    ohne = sum(1 for t in tk.scan() if t.is_open and not t.topics)
    out = ["# Themen-Verzeichnis", "",
           f"_Stand {heute.strftime('%d.%m.%Y')} – erzeugt von `2ndbrain einstieg` und bei jedem Lauf ersetzt; gerechnet "
           "aus Themen-Seiten und offenen Punkten, ohne Modell. Eine Zeile je Thema, Unterthemen eingerückt unter "
           "ihrem Dach. Die Seite eines Themas liegt unter `entities/projects/<slug>.md`._", ""]
    if not rows:
        return "\n".join(out + ["_Noch keine Themen._"]) + "\n"
    out += ["| Thema | Art | Rolle | Ampel | offen | meine | überfällig | Fragen | bewegt | nächster Termin |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ein = "· " * r["tiefe"]
        stern = f" ★{r['fokus']}" if r["fokus"] else ""
        status = "" if r["status"] in ("", "active") else f" ({r['status']})"
        rolle = r["rolle"] + ("" if r["rolle_eingetragen"] or r["tiefe"] and r["rolle"] != rollen.FUEHRE else "*")
        grund = r["grund"] if len(r["grund"]) <= GRUND_LAENGE else r["grund"][:GRUND_LAENGE].rstrip() + " …"
        ampel = r["ampel"] + (f" – {grund.replace('|', '/')}" if grund and r["ampel"] not in ("", "grün") else "")
        z = lambda n: str(n) if n else "–"                                        # noqa: E731
        out.append(f"| {ein}[[{r['slug']}\\|{r['titel'].replace('|', '/')}]]{stern}{status} | {r['art'] or '–'} | {rolle} | "
                   f"{ampel or '–'} | {z(r['offen'])} | {z(r['meine'])} | {z(r['ueberfaellig'])} | {z(r['fragen'])} | "
                   f"{_datum(r['bewegt'])} | {_datum(r['termin'])} |")
    alt = sum(r["altbestand"] for r in rows)
    out += ["",
            "_offen: Aufgaben aller Personen ohne ungeprüften Altbestand"
            + (f" (davon gibt es {alt})" if alt else "") + " · meine: davon mit mir als Person · ★n: Fokus-Thema mit Rang · "
            "Rolle: `fuehre` ich halte alle Punkte nach, `beteiligt` nur meine, `beobachte` nur den Stand; `*` = nicht "
            "eingetragen, es gilt der Standard `fuehre`._"]
    if ohne:
        out += ["", f"_{ohne} offene Punkte gehören zu keinem Thema – sie stehen nur in ihren Termin-Notizen._"]
    zu = sorted(thema_schliessen.abgeschlossene())
    if zu:
        out += ["", "_Abgeschlossen (Seite bleibt, `status: done`): " + ", ".join(f"[[{s}]]" for s in zu) + "_"]
    return "\n".join(out).rstrip() + "\n"


def _ohne_stand(text: str) -> str:
    return _STAND_RE.sub("_Stand", text, count=1)


def verzeichnis_schreiben(*, dry_run: bool = False, heute: date | None = None) -> bool:
    """Schreiben nur, wenn sich mehr als das Datum geaendert hat."""
    f = vp.VAULT / VERZEICHNIS
    text = verzeichnis_text(heute)
    if f.is_file() and _ohne_stand(f.read_text(encoding="utf-8")) == _ohne_stand(text):
        return False
    if not dry_run:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline="\n")
    return True


def run(*, dry_run: bool = False, heute: date | None = None) -> dict:
    v = verzeichnis_schreiben(dry_run=dry_run, heute=heute)      # zuerst: die Karte nennt nur, was es gibt
    k = karte_schreiben(dry_run=dry_run)
    return {"ok": True, "karte": KARTE, "verzeichnis": VERZEICHNIS, "karte_geaendert": k, "verzeichnis_geaendert": v,
            "geaendert": k or v}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Karte (CLAUDE.md) und Themen-Verzeichnis für Agenten")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = run(dry_run=args.dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
