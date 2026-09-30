#!/usr/bin/env python3
"""auto.py - Automatik: die Engine-Schritte in der richtigen Reihenfolge (`2ndbrain auto`).

Fuer den Hintergrund gedacht (Obsidian-Plugin alle N Minuten oder die
Aufgabenplanung). Jeder Schritt ist idempotent und billig, wenn sich nichts
geaendert hat; teure Schritte haben ein Mindestintervall (.2ndbrain/daten/.auto_state.json).

  kalender  Kalender (iCal) nach archive/calendar/ (alle 6 h) deterministisch
  mails     .eml im Root/inbox: Notiz, Anhaenge, Archiv; Dokumente, Bilder, ZIPs aus
            inbox/ ebenso (Unlesbares bleibt liegen)           deterministisch
  protokolle Protokolle, Transkripte, Teams-Zusammenfassungen im Eingang in ihre Termin-
            Notiz (vorgemerkt zum Nachbereiten); unklar -> Rueckfrage   deterministisch
  einarbeiten  Eingang ins Vault einsortieren (einarbeiten.py)  LLM, erst nach Freigabe
            (`"einarbeiten": {"automatisch": true}`; wartet ohne Modell)
  wissen    Begriffs-Index, Kontext-Verzeichnis, Glossar - nur wenn sich ihre Quellen
            geaendert haben (wissen.py)                       LLM nur fuers Glossar, in Portionen
  vorbereiten heute + morgen vorbereiten (stuendlich)        deterministisch
  nachbereiten Notizen nachbereiten: auf Ansage (--note) und was am LLM
            Handy vorgemerkt ist (`nachbereiten: angefordert`)
  themenlog je Notiz: Entscheidungen/Risiken ins Themen-Log   deterministisch
  rueckfragen angehakte Rueckfragen einarbeiten, Erledigtes archivieren  deterministisch
  altbestand nachbereitete Termine: Altbestand gilt als geprueft deterministisch
  archivieren erledigte Termin-Notizen (nachbereitet und eingearbeitet, entfallen,
            uebersprungen) abschliessen und nach archive/meetings/ deterministisch
  verdichten Erledigtes + altes Log ins Themen-Archiv (monatl.) LLM je Quartal
            (erster Lauf nur Vorschau, verdichtet 30 Tage danach)
  stand     Stand-Bloecke + Radar (Prosa nur bei Aenderung)  LLM, sonst nur Fakten
  systemuebersicht  LikeC4-Modell + Bericht aus den System-Seiten (taeglich,
            ohne likec4-Pruefung; geschrieben nur bei Aenderung)  deterministisch
  personen  Personen-Ueberblick (taeglich)                   deterministisch

Zwei Regeln:
  - `themenlog` schreibt JE NOTIZ mit ihr als Quelle: Datum = Termin, Link = Notiz.
    (Ein Sammelpaket ohne Quelle truege im Log das heutige Datum und keinen Quellen-Link.)
  - Ohne Modell laeuft `nachbereiten` NICHT mit der Notloesung: die setzt den
    Fingerabdruck, und die Nachbereitung durch das Modell kaeme nie mehr. Der Schritt wartet.

Sperre: .2ndbrain/daten/.auto.lock verhindert parallele Laeufe (Plugin + Aufgabenplanung). Das Plugin
schreibt waehrenddessen weiter - nur nicht den Termin, den die Nachbereitung gerade haelt
(.2ndbrain/daten/.in-arbeit.json, inarbeit.py).

    2ndbrain auto [--dry-run] [--json] [--only nachbereiten,stand] [--force]
    2ndbrain auto --only nachbereiten,themenlog,stand --note "active-meetings/.../x.md"
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

LOCK_FILE = vp.DATA_DIR / ".auto.lock"
STATE_FILE = vp.DATA_DIR / ".auto_state.json"
LOCK_MAX_AGE_S = 30 * 60
# Mindestabstand je Schritt in Minuten (0 = jeder Lauf)
INTERVAL_MIN = {"kalender": 360, "mails": 0, "protokolle": 0, "einarbeiten": 0, "wissen": 0, "vorbereiten": 60,
                "nachbereiten": 0, "themenlog": 0,
                "rueckfragen": 0, "schreibweisen": 0, "altbestand": 0, "archivieren": 0, "verdichten": 43200, "stand": 0,
                "systemuebersicht": 1440, "personen": 1440}
ORDER = ("kalender", "mails", "protokolle", "einarbeiten", "wissen", "vorbereiten", "nachbereiten", "themenlog", "rueckfragen",
         "schreibweisen", "altbestand", "archivieren",
         "verdichten",
         "stand", "systemuebersicht", "personen")


# --------------------------------------------------------------- Sperre, Zustand

def acquire_lock() -> bool:
    try:
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < LOCK_MAX_AGE_S:
            return False
    except OSError:
        pass
    LOCK_FILE.write_text(f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}\n",
                         encoding="utf-8", newline="\n")
    return True


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except OSError:
        pass


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8", newline="\n")


def due(step: str, state: dict, now: float, force: bool) -> bool:
    if force or not INTERVAL_MIN.get(step):
        return True
    return now - float(state.get(step, 0)) >= INTERVAL_MIN[step] * 60


# ------------------------------------------------------------------- Schritte

def step_kalender(ctx: dict) -> dict:
    import einlesen
    ok, msg = einlesen.ingest_calendar(ctx["dry_run"])
    return {"ok": ok, "detail": msg}


def step_mails(ctx: dict) -> dict:
    """Eingang: Mails (Root oder inbox/) werden Notizen samt ihren Anhaengen, die Mail kommt ins
    Archiv - dieselben Stufen wie `2ndbrain einlesen`. Was du selbst in inbox/ ablegst (Dokumente,
    Bilder, ZIPs), wird ebenso Notiz; das Original wandert nach .attachments/. Was sich nicht lesen
    laesst, bleibt mit Grund liegen. Dateien im Vault-Ordner selbst (ausser Mails) bleiben unberuehrt."""
    import auspacken as co
    import dokumente as de
    import mails as ie
    import einlesen
    inbox = vp.INBOX_DIR

    def lesbar(f: Path) -> bool:
        sfx = f.suffix.lower()
        return f.is_file() and (sfx in co.ARCHIVE_SUFFIXES or (sfx in de.SUPPORTED_EXTENSIONS and sfx != ".md"))

    mails = einlesen._inbox_files("*.eml")
    eigene = [f for f in sorted(inbox.iterdir()) if lesbar(f)] if inbox.is_dir() else []
    if not mails and not eigene:
        return {"ok": True, "detail": "nichts im Eingang"}
    if ctx["dry_run"]:
        return {"ok": True, "detail": f"[DRY] {len(mails)} Mail(s), {len(eigene)} Datei(en) würden eingelesen"}
    inbox.mkdir(parents=True, exist_ok=True)
    vorher = set(inbox.iterdir()) - set(eigene)     # die eigenen Dateien kommen mit den Anhaengen dran
    fehler, archiviert, doppelt, liegen = [], 0, 0, []
    for m in mails:
        try:
            if ie.process_eml(str(m), str(inbox), keep_source=True) is None:   # schon eingelesen
                doppelt += 1
                continue
            st = co.unpack_eml(m)                   # .eml blieb fuer die Anhaenge liegen
            if st.get("parent"):
                co.archive_mail(m, st["parent"], False)
                archiviert += 1
        except Exception as e:                  # eine kaputte Mail haelt die anderen nicht auf
            fehler.append(f"{m.name}: {type(e).__name__}")
    # Anhaenge und eigene Dateien: ZIPs auspacken, Dokumente zu Notizen (weitere Runden fuer ZIP-Inhalte)
    erledigt, dokumente = set(), 0
    for _ in range(3):
        neu = [f for f in sorted(inbox.iterdir()) if f.is_file() and f not in vorher and f not in erledigt]
        if not neu:
            break
        for f in neu:
            erledigt.add(f)
            sfx = f.suffix.lower()
            try:
                if sfx in co.ARCHIVE_SUFFIXES:
                    if co.unpack_zip(f).get("members"):
                        co.archive_container(f, False)
                elif sfx in de.SUPPORTED_EXTENSIONS and sfx != ".md":
                    de.process_inbox_document(f, str(vp.VAULT))
                    dokumente += 1
            except Exception as e:
                if f in eigene:                 # wie `einlesen`: bleibt liegen, mit Grund
                    alt = de.ALTE_OFFICE.get(sfx)
                    grund = f"altes Format, bitte als {alt} speichern" if alt else type(e).__name__
                    liegen.append(f"{f.name} ({grund})")
                else:
                    fehler.append(f"{f.name}: {type(e).__name__}")
    neu = len(mails) - doppelt
    teile = [f"{neu} Mail(s) importiert"] if mails else []
    teile.append(f"{dokumente} Notiz(en) aus Anhängen und Dateien")
    detail = ", ".join(teile)
    if doppelt:
        detail += f", {doppelt} schon eingelesen (Papierkorb)"
    if archiviert < neu:
        detail += f", {neu - archiviert} Mail(s) bleiben im Eingang"
    if liegen:
        detail += " – nicht lesbar, bleibt liegen: " + "; ".join(liegen[:3])
    if fehler:
        detail += " – Fehler: " + "; ".join(fehler[:3])
    return {"ok": not fehler, "detail": detail, "changed": len(mails) + dokumente}


def step_einarbeiten(ctx: dict) -> dict:
    """Eingang (Mails, Dokumente, Anhaenge) mit dem Modell einsortieren - erst nach Freigabe des
    Probelaufs (`"einarbeiten": {"automatisch": true}`), je Lauf nur ein paar Pakete."""
    cfg = vp.local_config().get("einarbeiten") or {}
    if not cfg.get("automatisch"):
        return {"ok": True, "skipped": True,
                "detail": "wartet auf Freigabe (Probelauf: 2ndbrain einarbeiten --probelauf)"}
    if not ctx["llm_ok"]:
        return {"ok": True, "skipped": True, "detail": f"wartet auf das Modell ({ctx['llm_reason']})"}
    if ctx["dry_run"]:
        return {"ok": True, "detail": "[DRY] Eingang würde eingearbeitet"}
    import einarbeiten
    r = einarbeiten.run(max_packets=int(cfg.get("je_lauf") or 3))
    n = len(r["eingearbeitet"])
    detail = f"{n} eingearbeitet" + (f", {r['ohne_modell']} ohne Modell" if r["ohne_modell"] else "")
    if r["wartet"]:
        detail += f" – wartet auf das Modell ({r['wartet']})"
    if r["fehler"]:
        detail += " – zurückgelegt: " + "; ".join(r["fehler"][:3])
    return {"ok": not r["fehler"], "detail": detail, "changed": n + r["ohne_modell"]}


def step_wissen(ctx: dict) -> dict:
    """Begriffs-Index, Kontext-Verzeichnis, Glossar - nur wenn sich ihre Quellen geaendert haben."""
    import wissen
    r = wissen.aktualisieren(llm_ok=ctx["llm_ok"], dry_run=ctx["dry_run"])
    return {"ok": True, "detail": "; ".join(r["detail"]), "changed": r["changed"]}


def step_vorbereiten(ctx: dict) -> dict:
    import vorbereiten
    days = vorbereiten.window_days(date.today())
    vorbereiten.run(days=days, dry_run=ctx["dry_run"])
    return {"ok": True, "detail": "heute + morgen" if days == 2 else f"heute + {days - 1} Tage (bis Werktag)"}


def wrapup_automatic() -> bool:
    """Nachbereitet wird nur auf Ansage (Knopf / "Speichern und nachbereiten",
    also mit --note). Automatisch nur, wenn in .2ndbrain/local.config.json
    `"auto": {"wrapup_automatisch": true}` steht: Nach dem Termin werden oft erst
    Notizen nacherfasst - eine automatische Nachbereitung kaeme ihnen mit halbem
    Material zuvor."""
    return bool((vp.local_config().get("auto") or {}).get("wrapup_automatisch"))


WRAPUP_FLAG, WRAPUP_REQUESTED = "nachbereiten", "angefordert"


def requested_notes() -> list[Path]:
    """Termin-Notizen, die am Handy zum Nachbereiten vorgemerkt wurden (`nachbereiten: angefordert`,
    Plugin: "Speichern und vormerken") - am Handy laeuft keine Engine, der Desktop arbeitet sie ab."""
    root = vp.VAULT / "active-meetings"
    return [f for f in sorted(root.rglob("*.md")) if root.is_dir()
            and str(vp.read_frontmatter_head(f).get(WRAPUP_FLAG) or "") == WRAPUP_REQUESTED]


def step_nachbereiten(ctx: dict) -> dict:
    requested = [] if ctx.get("note") else requested_notes()
    if not ctx.get("note") and not requested and not wrapup_automatic():
        return {"ok": True, "skipped": True,
                "detail": "nur auf Ansage (Nachbereiten-Knopf, Vormerkung am Handy)"}
    if not ctx["llm_ok"]:
        return {"ok": True, "skipped": True,
                "detail": f"wartet auf das Modell ({ctx['llm_reason']})"
                          + (f" – {len(requested)} vorgemerkt" if requested else "")}
    import nachbereiten
    done = []
    if ctx.get("note"):
        notes = [ctx["note"]]
    elif wrapup_automatic():
        notes = list(dict.fromkeys([*requested, *nachbereiten.iter_notes()]))
    else:
        notes = requested
    last = ""
    for path in notes:
        # Auf Ansage (Nacherfassen, Vormerkung) reichen wenige Stichpunkte
        on_request = bool(ctx.get("note")) or path in requested
        # vorgemerkt ist sie auch, wenn sie einzeln (Knopf) nachbereitet wird - sonst bliebe die
        # Vormerkung stehen und die Notiz kaeme nie ins Archiv
        vorgemerkt = (path in requested
                      or str(vp.read_frontmatter_head(path).get(WRAPUP_FLAG) or "") == WRAPUP_REQUESTED)
        r = nachbereiten.process_note(path, dry_run=ctx["dry_run"],
                                min_chars=30 if on_request else nachbereiten.MIN_PROSE_CHARS)
        last = str(r.get("status", ""))
        if nachbereiten.by_model(r):
            done.append(r)
        if vorgemerkt and not ctx["dry_run"] and last != nachbereiten.GEAENDERT:
            # Vormerkung erledigt; ohne Material bleibt ein Hinweis statt einer Dauer-Vormerkung.
            # Waehrenddessen geaendert: sie bleibt - der naechste Lauf nimmt das Neue mit.
            vp.update_frontmatter(path, {WRAPUP_FLAG: "zu wenig Text" if last == "kein Material" else None})
    ctx["wrapped"] = done
    detail = f"{len(done)} Notiz(en) nachbereitet"
    if ctx.get("note") and not done:
        # Eine Notiz auf Ansage: sagen, warum nichts passiert ist
        detail = {"kein Material": "zu wenig Text zum Nachbereiten",
                  "unveraendert": "unverändert seit der letzten Nachbereitung",
                  nachbereiten.GEAENDERT: "die Notiz wurde während der Nachbereitung geändert – "
                                          "nichts überschrieben, bitte noch einmal nachbereiten"}.get(last, last)
    return {"ok": True, "detail": detail, "changed": len(done)}


def step_themenlog(ctx: dict) -> dict:
    """Je nachbereiteter Notiz ein Sync ins Themen-Log mit ihr als Quelle (Datum + Link)."""
    import nachbereiten
    applied, clarifications = nachbereiten.sync_to_logs(ctx.get("wrapped", []), dry_run=ctx["dry_run"])
    return {"ok": True, "detail": f"{applied} Notiz(en) ins Log, {clarifications} mit Rueckfragen",
            "changed": applied}


def step_rueckfragen(ctx: dict) -> dict:
    """Angehakte Rueckfragen (04_Clarifications.md) einarbeiten, Erledigtes ins Archiv."""
    import rueckfragen as ce
    if ctx["dry_run"]:
        return {"ok": True, "detail": "Probelauf"}
    done = ce.apply_checked()
    moved = ce.archive_resolved()
    ok = sum(1 for r in done if r["ok"])
    return {"ok": True, "changed": ok + moved,
            "detail": f"{ok} eingearbeitet, {moved} archiviert"
                      + (f", {len(done) - ok} brauchen Handarbeit" if len(done) > ok else "")}


def step_schreibweisen(ctx: dict) -> dict:
    """Namen sauber: angekreuzte Eintraege der Schreibweisen-Liste einarbeiten; nach Freigabe
    (`"schreibweisen": {"bereinigen": true}`) den Bestand bereinigen, sobald Schreibweisen dazukommen."""
    import schreibweisen
    r = schreibweisen.automatik(dry_run=ctx["dry_run"])
    return {"ok": True, "changed": r["changed"], "detail": r["detail"]}


def step_altbestand(ctx: dict) -> dict:
    """Nach der Nachbereitung eines Termins gilt der vorgelegte Altbestand als geprueft."""
    import altbestand
    done = altbestand.settle(dry_run=ctx["dry_run"])
    return {"ok": True, "changed": len(done),
            "detail": f"{len(done)} Thema/Themen nach dem Termin übernommen"}


def step_protokolle(ctx: dict) -> dict:
    """Protokolle aus dem Eingang in ihre Termin-Notiz - vor dem Einarbeiten, das sie sonst als
    Dokument behandeln wuerde; unklare Zuordnung wird eine Rueckfrage."""
    import protokolle
    r = protokolle.run(dry_run=ctx["dry_run"])
    detail = f"{len(r['zugeordnet'])} Protokoll(e) zugeordnet"
    if r["rueckfragen"]:
        detail += f", {len(r['rueckfragen'])} Rückfrage(n)"
    return {"ok": True, "detail": detail, "changed": len(r["zugeordnet"])}


def step_archivieren(ctx: dict) -> dict:
    """Erledigte Termin-Notizen abschliessen und nach archive/meetings/ (nachbereitet und
    eingearbeitet, entfallen, uebersprungen) - nach dem Altbestand, der sie noch auswertet."""
    import archivieren
    r = archivieren.run(dry_run=ctx["dry_run"])
    detail = f"{len(r['archiviert'])} Termin-Notiz(en) ins Archiv"
    if r["fehler"]:
        detail += f", {len(r['fehler'])} nicht (Name im Archiv belegt)"
    return {"ok": True, "detail": detail, "changed": len(r["archiviert"])}


def step_verdichten(ctx: dict) -> dict:
    """Monatlich: erledigte Punkte und altes Log ins Themen-Archiv (verdichten.py)."""
    import verdichten
    llm_call = None
    if ctx["llm_ok"]:
        import modell
        llm_call = modell.complete_json
    return verdichten.auto_step(date.today(), llm_call=llm_call, dry_run=ctx["dry_run"])


def step_stand(ctx: dict) -> dict:
    import stand
    llm_call = None
    if ctx["llm_ok"]:
        import modell
        llm_call = modell.complete_json
    reports = stand.run(dry_run=ctx["dry_run"], llm_call=llm_call)
    return {"ok": True, "changed": sum(1 for r in reports if r["changed"]),
            "detail": f"{sum(1 for r in reports if r['llm'])} Stand-Text(e) neu"
                      + ("" if llm_call else " (ohne Modell: nur Fakten)")}


def step_systemuebersicht(ctx: dict) -> dict:
    """Taeglich: LikeC4-Modell + reports/systemuebersicht.md aus den System-Seiten neu - ohne
    likec4-Pruefung (braucht Node, dauert); der Explorer im Plugin laedt Aenderungen selbst nach."""
    import systemuebersicht as su
    if ctx["dry_run"]:
        return {"ok": True, "detail": "Probelauf – nichts geschrieben"}
    r = su.run(su.target_dir(None), check=False)
    if r["pruefung"].startswith("FEHLER"):
        return {"ok": False, "detail": r["pruefung"]}
    return {"ok": True, "changed": int(r["geaendert"]),
            "detail": f"{r['systeme']} Systeme, {r['verbindungen']} Verbindungen"
                      + (" – Modell neu" if r["geaendert"] else " – unverändert")}


def step_personen(ctx: dict) -> dict:
    import personen
    r = personen.run(dry_run=ctx["dry_run"])
    return {"ok": True, "detail": f"{r.get('written', 0)} Person(en) aktualisiert"}


STEPS = {"kalender": step_kalender, "mails": step_mails, "protokolle": step_protokolle,
         "einarbeiten": step_einarbeiten, "wissen": step_wissen, "vorbereiten": step_vorbereiten,
         "nachbereiten": step_nachbereiten, "themenlog": step_themenlog, "rueckfragen": step_rueckfragen, "schreibweisen": step_schreibweisen,
         "altbestand": step_altbestand, "archivieren": step_archivieren, "verdichten": step_verdichten,
         "stand": step_stand, "systemuebersicht": step_systemuebersicht,
         "personen": step_personen}


# ----------------------------------------------------------------------- Lauf

def run(*, only: set[str] | None = None, dry_run: bool = False, force: bool = False,
        llm_status: tuple[bool, str] | None = None, note: Path | None = None) -> dict:
    if not acquire_lock():
        return {"ok": True, "skipped": "laeuft bereits (Sperre aktiv)", "steps": []}
    started = time.time()
    try:
        if llm_status is None:
            import modell
            llm_status = modell.available()
        ctx = {"dry_run": dry_run, "llm_ok": llm_status[0], "llm_reason": llm_status[1],
               "wrapped": [], "note": note}
        state = load_state()
        steps = []
        for name in ORDER:
            if only and name not in only:
                continue
            if not due(name, state, started, force):
                steps.append({"step": name, "ok": True, "skipped": True, "detail": "Intervall"})
                continue
            t0 = time.time()
            try:
                # Schritte melden sich auf stdout - das gehoert nach stderr,
                # stdout traegt bei --json nur das Ergebnis.
                with contextlib.redirect_stdout(sys.stderr):
                    res = STEPS[name](ctx)
            except Exception as e:           # ein Schritt darf die Kette nicht kippen
                res = {"ok": False, "detail": f"{type(e).__name__}: {e}"}
            res.update(step=name, seconds=round(time.time() - t0, 1))
            steps.append(res)
            if res.get("ok") and not res.get("skipped") and not dry_run:
                state[name] = started
        if not dry_run:
            save_state(state)
        return {"ok": all(s.get("ok") for s in steps), "llm": llm_status[0],
                "seconds": round(time.time() - started, 1), "steps": steps}
    finally:
        release_lock()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Automatik: Engine-Schritte in Reihenfolge")
    ap.add_argument("--only", help="nur diese Schritte, komma-getrennt: " + ",".join(ORDER))
    ap.add_argument("--force", action="store_true", help="Intervalle ignorieren")
    ap.add_argument("--note", help="nur diese Meeting-Notiz nachbereiten (Pfad relativ zum Vault)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    note = (vp.VAULT / args.note) if args.note else None
    if note is not None and not note.is_file():
        print(f"Notiz nicht gefunden: {args.note}", file=sys.stderr)
        return 1
    only = {s.strip() for s in args.only.split(",")} if args.only else None
    if only and only - set(ORDER):
        print(f"Unbekannte Schritte: {', '.join(sorted(only - set(ORDER)))}", file=sys.stderr)
        return 1
    result = run(only=only, dry_run=args.dry_run, force=args.force, note=note)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result.get("ok") else 2
    if result.get("skipped"):
        print(f"Automatik: {result['skipped']}")
        return 0
    print(f"Automatik ({result['seconds']} s, Modell {'bereit' if result['llm'] else 'aus'}):")
    for s in result["steps"]:
        mark = "–" if s.get("skipped") else ("ok" if s.get("ok") else "FEHLER")
        print(f"  {s['step']:9} {mark:6} {s.get('detail', '')}")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
