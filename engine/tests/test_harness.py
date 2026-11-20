#!/usr/bin/env python3
"""test_harness.py - Regressionstests fuer den LLM-Harness (modell.py, nachbereiten_modell.py,
nachbereiten.py).

    python engine/tests/test_harness.py
    2ndbrain test      # ruft dieses Skript zusaetzlich zu test_tools.py auf

Kein Netzzugriff: entweder `VAULT_LLM_OFFLINE=1` oder der HTTP-Layer
(`modell._http_get`/`modell._http_post`) wird per Monkeypatch ersetzt. Gleicher Stil
wie `test_tools.py` (`check/eq/ok`), eigenes `main()` mit Exit-Code.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "secondbrain"))
# Eigener leerer Vault: Protokoll und Rueckgaengig-Daten landen dort, nie im aktuellen Ordner
_VAULT = Path(tempfile.mkdtemp(prefix="harness-vault-"))
(_VAULT / ".obsidian").mkdir()
(_VAULT / ".2ndbrain" / "daten").mkdir(parents=True)
os.environ["VAULT_DIR"] = str(_VAULT)

import modell
import nachbereiten_modell
import nachbereiten
from modell_ausgabe import LLMOutputError

_passed, _failed = 0, []


def check(name, fn):
    global _passed
    try:
        fn()
        print(f"  OK   {name}")
        _passed += 1
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


# ───────────────────────────────────────── Hilfsmittel: Monkeypatch-Guards

class _EnvGuard:
    """Setzt/entfernt Env-Variablen, stellt den Ausgangszustand wieder her."""

    def __init__(self, **kv):
        self.kv = kv
        self.saved = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class _AttrGuard:
    """Modulattribute temporaer umbiegen (modell.CONFIG_PATH, modell._http_get, ...)."""

    def __init__(self, obj, **kv):
        self.obj, self.kv, self.saved = obj, kv, {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.saved[k] = getattr(self.obj, k)
            setattr(self.obj, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(self.obj, k, v)


# ───────────────────────────────────────── 1. modell.config() Rangfolge

def t_config_precedence():
    d = Path(tempfile.mkdtemp(prefix="llmtest-"))
    cfg_path = d / "llm.config.json"

    env = _EnvGuard(VAULT_LLM_URL=None, VAULT_LLM_MODEL=None, VAULT_LLM_TIMEOUT=None,
                     VAULT_LLM_OFFLINE=None)
    attrs = _AttrGuard(modell, CONFIG_PATH=cfg_path)
    with env, attrs:
        # 3. Vorgabe: keine llm.config.json
        cfg = modell.config()
        eq(cfg["url"], modell.DEFAULTS["url"], "Vorgabe-URL ohne jede Quelle")

        # 2. llm.config.json schlaegt die Vorgabe
        cfg_path.write_text('{"url": "http://cfg-json:2", "model": "modell-aus-config"}',
                             encoding="utf-8", newline="\n")
        cfg = modell.config()
        eq(cfg["url"], "http://cfg-json:2", "llm.config.json muss die Vorgabe schlagen")
        eq(cfg["model"], "modell-aus-config")

        # 1. Umgebung schlaegt alles
        os.environ["VAULT_LLM_URL"] = "http://env:3"
        os.environ["VAULT_LLM_MODEL"] = "modell-aus-env"
        os.environ["VAULT_LLM_TIMEOUT"] = "17"
        cfg = modell.config()
        eq(cfg["url"], "http://env:3", "Env muss alles andere schlagen")
        eq(cfg["model"], "modell-aus-env")
        eq(cfg["timeout_s"], 17)

        # VAULT_LLM_OFFLINE=1 erzwingt "nicht verfuegbar"
        os.environ["VAULT_LLM_OFFLINE"] = "1"
        ok(modell.config()["offline"] is True, "offline-Flag muss aus Env kommen")


# ───────────────────────────────────────── 2. modell.available() ohne Netz

def t_available_unreachable_no_throw():
    def boom(url, timeout):
        raise OSError("Connection refused (simuliert, kein echtes Netz)")

    with _AttrGuard(modell, _http_get=boom):
        ok_flag, reason = modell.available(timeout=1)
        eq(ok_flag, False, "unerreichbarer Host muss False liefern")
        ok(isinstance(reason, str) and reason, "Grund fehlt")


def t_available_offline_env():
    with _EnvGuard(VAULT_LLM_OFFLINE="1"):
        ok_flag, reason = modell.available()
        eq(ok_flag, False)
        ok("OFFLINE" in reason, "Offline-Grund muss die Env-Variable nennen")


# ───────────────────────────────────────── 3. modell.complete_json mit gefaktem Transport

def t_complete_json_repairs_fence_and_think():
    fake_content = '<think>lange Ueberlegung</think>```json\n{"ok": true}\n```'

    def fake_post(url, payload, timeout):
        return {"choices": [{"message": {"content": fake_content}}]}

    schema = {"type": "object", "additionalProperties": False, "required": ["ok"],
              "properties": {"ok": {"type": "boolean"}}}
    with _EnvGuard(VAULT_LLM_OFFLINE=None, VAULT_LLM_URL="http://modell.test"), _AttrGuard(modell, _http_post=fake_post):
        payload, repairs = modell.complete_json(
            [{"role": "user", "content": "test"}], schema, task="test")
        eq(payload, {"ok": True})
        ok(isinstance(repairs, list), "repairs muss eine Liste sein")


def t_complete_json_reraises_after_retry():
    calls = []

    def fake_post(url, payload, timeout):
        calls.append(1)
        return {"choices": [{"message": {"content": "das ist kein JSON"}}]}

    schema = {"type": "object", "properties": {}}
    with _EnvGuard(VAULT_LLM_OFFLINE=None, VAULT_LLM_URL="http://modell.test"), _AttrGuard(modell, _http_post=fake_post):
        try:
            modell.complete_json([{"role": "user", "content": "x"}], schema, retries=1, task="t")
            ok(False, "haette LLMOutputError werfen muessen")
        except LLMOutputError:
            pass
        eq(len(calls), 2, "1 Versuch + 1 Wiederholung = 2 Aufrufe")




# ───────────────────────────────────────── 4. nachbereiten_modell.extract Nachvalidierung

def t_extract_filters_unknown_section_blank_date_dedupes():
    fake_payload = {
        "ziel": "Testziel",
        "entscheidungen": [
            {"was": "Budget freigeben", "wer": "Daniel", "datum": "naechste Woche"},
            {"was": "budget   freigeben", "wer": "Daniel", "datum": "2026-09-23"},  # Dublette
        ],
        "actions": [],
        "kernteil": [
            {"abschnitt": "Ampel", "punkte": ["Zeit gruen"]},
            {"abschnitt": "Erfundener Abschnitt", "punkte": ["sollte raus"]},
        ],
        "parkplatz": [],
    }

    def fake_complete_json(messages, schema, **kw):
        return fake_payload, []

    playbook_view = {"meeting_type": "steering", "kernteil": ["Ampel", "Top-Risiken"],
                     "label": "Steering", "nachbereitung": ["Entscheidungen", "Risiken"]}
    with _AttrGuard(modell, complete_json=fake_complete_json):
        result = nachbereiten_modell.extract("irrelevantes Material fuer den Fake-Transport",
                                     playbook_view, {"title": "Steering X"})

    eq(len(result["entscheidungen"]), 1, "Dubletten muessen dedupliziert werden")
    eq(result["entscheidungen"][0]["datum"], "",
       "'naechste Woche' ist kein ISO-Datum und muss leer bleiben")
    eq(len(result["kernteil"]), 1, "unbekannter Abschnitt muss verworfen werden")
    eq(result["kernteil"][0]["abschnitt"], "Ampel")


def t_extract_review_caps_at_three_actions():
    fake_payload = {
        "ziel": "", "entscheidungen": [],
        "actions": [{"was": f"Massnahme {i}", "wer": "X", "bis": ""} for i in range(5)],
        "kernteil": [], "parkplatz": [],
    }

    def fake_complete_json(messages, schema, **kw):
        return fake_payload, []

    playbook_view = {"meeting_type": "review", "kernteil": [], "label": "Review",
                     "nachbereitung": ["Massnahmen - maximal drei"]}
    with _AttrGuard(modell, complete_json=fake_complete_json):
        result = nachbereiten_modell.extract("Material" * 50, playbook_view, {"title": "Review X"})

    eq(len(result["actions"]), 3, "Review: hoechstens drei Massnahmen behalten")
    eq(len(result["parkplatz"]), 2, "der Rest muss in den Parkplatz wandern")


def t_extract_splits_piece_when_answer_breaks():
    """Bleibt die Antwort fuer ein Stueck unbrauchbar (abgeschnittenes JSON bei vielen Punkten),
    wird das Stueck halbiert und jede Haelfte einzeln ausgewertet - statt in den Notbehelf zu
    fallen, der nichts ins Themen-Log bringt."""
    material = "\n\n".join(f"Absatz {i}: " + "Inhalt " * 60 for i in range(12))
    aufrufe = []

    def fake_complete_json(messages, schema, **kw):
        text = messages[-1]["content"]
        aufrufe.append(len(text))
        if len(text) > 4500:               # das Ganze (rund 6600 Zeichen) bricht, eine Haelfte (rund 4000) nicht
            raise LLMOutputError("abgeschnitten")
        return {"ziel": "", "entscheidungen": [{"was": f"Beschluss {len(aufrufe)}", "wer": "X", "datum": ""}],
                "actions": [], "kernteil": [], "parkplatz": []}, []

    playbook_view = {"meeting_type": "checkin", "kernteil": [], "label": "Checkin", "nachbereitung": []}
    with _AttrGuard(modell, complete_json=fake_complete_json):
        result = nachbereiten_modell.extract(material, playbook_view, {"title": "Checkin X"})
    ok(len(aufrufe) == 3, f"nicht halbiert: {aufrufe}")
    eq(len(result["entscheidungen"]), 2, "Ergebnisse beider Haelften fehlen")


# ───────────────────────────────────────── 5. nachbereiten: Rendering

def t_wrapup_renders_exact_lines():
    eq(nachbereiten._render_decision({"was": "X", "wer": "Y", "datum": "2026-09-23"}),
       "- [E] X — Y — 2026-09-23")
    # Kanonisches Punkt-Format (KONZEPT §4.1): unaufgeloeste Person = "Name (?)"
    import aufgaben
    eq(aufgaben.render(nachbereiten._action_task({"was": "X", "wer": "Yzx", "bis": "2026-10-01"})),
       "- [ ] X — Yzx (?) 📅 2026-10-01")


# ───────────────────────────────────────── 6. nachbereiten.process_note

_NOTE_TEMPLATE = """---
type: meeting
title: Testtermin
date: '2026-09-20'
meeting_type: checkin
status: prepared
---

# Testtermin

## Ziel

## Vorbereitung

## Agenda

## Meine Notizen

{material}

## Entscheidungen

## Actions

## Parkplatz

## Verweise
"""


def _write_temp_note(material: str) -> Path:
    d = Path(tempfile.mkdtemp(prefix="wraptest-"))
    p = d / "2026-09-20 - checkin - Testtermin.md"
    p.write_text(_NOTE_TEMPLATE.format(material=material), encoding="utf-8", newline="\n")
    return p


def t_wrapup_idempotent_second_run_is_byte_identical():
    material = ("Wir haben besprochen, dass das Budget freigegeben wird und die Testphase "
                "beginnt. " * 4)
    path = _write_temp_note(material)
    with _EnvGuard(VAULT_LLM_OFFLINE="1"):
        r1 = nachbereiten.process_note(path, dry_run=False)
        ok(r1["status"] != "unveraendert", "erster Lauf darf nicht 'unveraendert' sein")
        after_first = path.read_bytes()

        r2 = nachbereiten.process_note(path, dry_run=False)
        eq(r2["status"], "unveraendert", "zweiter Lauf mit gleichem Material muss ueberspringen")
        eq(path.read_bytes(), after_first, "Datei muss byte-gleich bleiben")


def t_wrapup_without_model_is_deterministic_and_exits_clean():
    material = "Ein laengerer Freitext ohne erkennbare Modell-Verfuegbarkeit. " * 6
    path = _write_temp_note(material)
    with _EnvGuard(VAULT_LLM_OFFLINE="1"):
        r = nachbereiten.process_note(path, dry_run=False)
    ok("deterministisch" in r["status"], f"Status muss 'deterministisch' nennen, war: {r['status']}")
    eq(r["changed"], True)


def t_wrapup_skips_notes_without_prose():
    path = _write_temp_note("_(wird vom Prep-Lauf gefüllt)_")
    r = nachbereiten.process_note(path, dry_run=True)
    eq(r["status"], "kein Material")


# ───────────────────────────────────────── 7. Fehlerbild und Modellwahl

def t_fehler_einordnen_echte_meldungen():
    """Die drei Meldungen aus dem Modell-Protokoll des eigenen Vaults (28./29.09.2026)."""
    a = modell.fehler_einordnen("OSError: HTTP 409: Modell gross-a ist im Modus haushalt nicht erlaubt. "
                                "Erlaubt ist: klein-b. Für die anderen Modelle in der Modell-Kachel umschalten.")
    eq(a["art"], "gesperrt")
    eq(a["erlaubt"], ["klein-b"], "das erlaubte Modell muss aus der Meldung kommen:")
    ok("klein-b" in a["ursache"] and a["ausweg"], "Ursache nennt das erlaubte Modell, Ausweg fehlt nicht")
    eq(modell.fehler_einordnen("HTTPError: HTTP Error 409: Conflict")["art"], "gesperrt")
    eq(modell.fehler_einordnen("ConnectionResetError: [WinError 10054] Eine vorhandene Verbindung wurde vom "
                               "Remotehost geschlossen")["art"], "abbruch")
    eq(modell.fehler_einordnen("URLError: <urlopen error timed out>")["art"], "nicht_erreichbar")
    eq(modell.fehler_einordnen("TimeoutError: timed out")["art"], "zeitlimit")
    eq(modell.fehler_einordnen(modell.NO_SERVER)["art"], "kein_server")
    b = modell.fehler_einordnen("Modell 'x' nicht in /v1/models (a, b)")
    eq((b["art"], b["erlaubt"]), ("unbekannt_modell", ["a", "b"]))
    e = modell.LLMUnavailableError("HTTPError: HTTP Error 409: Conflict")
    eq(e.art, "gesperrt", "die Ausnahme traegt die Art:")


def _modell_umgebung(cfg: dict):
    d = Path(tempfile.mkdtemp(prefix="llmtest-"))
    p = d / "llm.config.json"
    import json as _json
    p.write_text(_json.dumps(cfg), encoding="utf-8", newline="\n")
    modell._ABGELEHNT.clear()
    modell._ZULETZT.update(model="", ersatz_fuer="")
    modell._LEASE["model"] = ""

    def keine_lease_schnittstelle(method, url, payload, key, timeout):
        raise OSError("HTTP 404 Not Found")

    return (_EnvGuard(VAULT_LLM_OFFLINE=None, VAULT_LLM_URL=None, VAULT_LLM_MODEL=None, VAULT_LLM_KEY=None,
                      VAULT_LLM_LOG=str(d / "log.jsonl")),
            _AttrGuard(modell, CONFIG_PATH=p, _http_lease=keine_lease_schnittstelle))


def t_lease_holt_das_gesperrte_modell():
    """Mit Modell-Schluessel fordert die Engine das gesperrte Modell an und fragt es noch einmal -
    auch fuer ein fest gewaehltes Modell (Pruefstufe). Der Schluessel steht nur im Kopf der Anfrage,
    nie im Protokoll; die Lease geht am Ende zurueck."""
    frei = set()
    lease_rufe = []

    def fake_post(url, payload, timeout):
        if payload["model"] not in frei:
            raise OSError(f"HTTP 409: Modell {payload['model']} ist im Modus haushalt nicht erlaubt. "
                          "Im Haushalt antwortet nur das Haushaltsmodell klein. Ein anderes Modell braucht eine Lease.")
        return {"choices": [{"message": {"content": "ok"}}]}

    def fake_lease(method, url, payload, key, timeout):
        if method == "GET":                     # der Stand braucht keinen Schluessel
            return {"state": "none", "holder": "", "allowed": ["klein"], "mode": "haushalt", "last_human_at": None}
        lease_rufe.append((method, payload, key))
        if key != "geheim-123":
            raise modell.LeaseAbgelehnt(401, {"ok": False, "reason": "unauthorized"})
        if method == "POST":
            frei.add(payload["model"])
            return {"ok": True, "state": "ready", "renew_after": 0}
        return {"ok": True, "state": "released"}

    env, attrs = _modell_umgebung({"url": "http://modell.test", "model": "klein", "model_pruefung": "pruefer"})
    with env, attrs, _AttrGuard(modell, _http_post=fake_post, _http_lease=fake_lease):
        try:
            modell.complete([{"role": "user", "content": "x"}], model="pruefer")
            ok(False, "ohne Schluessel haette es scheitern muessen")
        except modell.LLMUnavailableError as e:
            ok(e.art == "gesperrt" and "kein Modell-Schlüssel" in str(e), f"der Grund muss den fehlenden Schluessel nennen: {e}")
        eq(lease_rufe, [], "ohne Schluessel gibt es keinen Aufruf der Lease-Schnittstelle:")

        os.environ["VAULT_LLM_KEY"] = "falsch"
        try:
            modell.complete([{"role": "user", "content": "x"}], model="pruefer")
            ok(False, "mit falschem Schluessel haette es scheitern muessen")
        except modell.LLMUnavailableError as e:
            ok("lehnt den Modell-Schlüssel ab" in str(e) and "falsch" not in str(e), f"Grund ohne Schluessel im Text: {e}")

        os.environ["VAULT_LLM_KEY"] = "geheim-123"
        eq(modell.complete([{"role": "user", "content": "x"}], model="pruefer"), "ok", "nach der Lease antwortet das Modell:")
        eq(lease_rufe[-1], ("POST", {"model": "pruefer", "ttl_s": modell.LEASE_TTL_S, "holder": "2ndbrain"}, "geheim-123"),
           "der Rumpf ist genau {model, ttl_s, holder}:")
        log = Path(modell.config()["log"]).read_text(encoding="utf-8")
        ok("geheim-123" not in log and '"task": "lease"' in log, "die Lease steht im Protokoll, der Schluessel nie")
        ok(modell.lease_freigeben(), "die Lease muss zurueckgehen")
        eq(lease_rufe[-1][0], "DELETE")
        eq(modell._LEASE["model"], "")
    modell._ABGELEHNT.clear()


def t_complete_nimmt_naechstes_modell_der_liste():
    """Gesperrtes Modell: das naechste der Liste antwortet, das gesperrte wird in diesem Prozess
    nicht noch einmal gefragt, ein Modell ausserhalb der Liste nie."""
    gefragt = []

    def fake_post(url, payload, timeout):
        gefragt.append(payload["model"])
        if payload["model"] == "gross-a":
            raise OSError("HTTP 409: Modell gross-a ist im Modus haushalt nicht erlaubt. Erlaubt ist: klein-z.")
        return {"choices": [{"message": {"content": "ok"}}]}

    env, attrs = _modell_umgebung({"url": "http://modell.test", "model": "mittel-b", "modelle": ["gross-a", "mittel-b"]})
    with env, attrs, _AttrGuard(modell, _http_post=fake_post):
        eq(modell.kandidaten(), ["gross-a", "mittel-b"], "Reihe aus der Konfiguration:")
        eq(modell.complete([{"role": "user", "content": "x"}]), "ok")
        eq(gefragt, ["gross-a", "mittel-b"], "erst das beste, dann das naechste:")
        eq(modell.zuletzt(), {"model": "mittel-b", "ersatz_fuer": "gross-a"})
        modell.complete([{"role": "user", "content": "x"}])
        eq(gefragt[2:], ["mittel-b"], "das gesperrte Modell wird nicht noch einmal gefragt:")
        ok("klein-z" not in gefragt, "ein Modell ausserhalb der Liste darf nie einspringen")
    modell._ABGELEHNT.clear()


def t_complete_ohne_ersatz_meldet_die_sperre():
    def fake_post(url, payload, timeout):
        raise OSError("HTTP 409: Modell einzig ist im Modus haushalt nicht erlaubt. Erlaubt ist: klein-z.")

    env, attrs = _modell_umgebung({"url": "http://modell.test", "model": "einzig"})
    with env, attrs, _AttrGuard(modell, _http_post=fake_post):
        try:
            modell.complete([{"role": "user", "content": "x"}])
            ok(False, "haette LLMUnavailableError werfen muessen")
        except modell.LLMUnavailableError as e:
            eq((e.art, e.erlaubt), ("gesperrt", ["klein-z"]))
    modell._ABGELEHNT.clear()


def t_complete_wiederholt_einen_abbruch_einmal():
    aufrufe = []

    def fake_post(url, payload, timeout):
        aufrufe.append(1)
        if len(aufrufe) == 1:
            raise ConnectionResetError("[WinError 10054] vom Remotehost geschlossen")
        return {"choices": [{"message": {"content": "ok"}}]}

    env, attrs = _modell_umgebung({"url": "http://modell.test", "model": "m"})
    with env, attrs, _AttrGuard(modell, _http_post=fake_post):
        eq(modell.complete([{"role": "user", "content": "x"}]), "ok")
        eq(len(aufrufe), 2, "ein Abbruch wird genau einmal wiederholt:")

    def immer(url, payload, timeout):
        aufrufe.append(1)
        raise ConnectionResetError("[WinError 10054] vom Remotehost geschlossen")

    del aufrufe[:]
    env, attrs = _modell_umgebung({"url": "http://modell.test", "model": "m"})
    with env, attrs, _AttrGuard(modell, _http_post=immer):
        try:
            modell.complete([{"role": "user", "content": "x"}])
            ok(False, "haette werfen muessen")
        except modell.LLMUnavailableError as e:
            eq(e.art, "abbruch")
        eq(len(aufrufe), 2, "nach der einen Wiederholung ist Schluss:")


def t_diagnose_haelt_beim_ersten_fehler():
    def kein_netz(url, timeout):
        raise OSError("Connection refused")

    env, attrs = _modell_umgebung({"url": "http://modell.test", "model": "m"})
    with env, attrs, _AttrGuard(modell, _http_get=kein_netz):
        s = {x["schritt"]: x for x in modell.diagnose()}
    eq([s[k]["ok"] for k in ("adresse", "server", "modell", "format", "werkzeuge")],
       [True, False, None, None, None], "Schritte hinter dem Fehler bleiben ungeprueft:")
    ok(s["server"]["ausweg"] and "antwortet nicht" in s["server"]["detail"], "Ursache und Ausweg fehlen")

    def liste(url, timeout):
        return {"data": [{"id": "m"}]}

    def post(url, payload, timeout):
        if "tools" in payload:
            raise OSError("HTTP 400: tools not supported")
        return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    env, attrs = _modell_umgebung({"url": "http://modell.test", "model": "m"})
    with env, attrs, _AttrGuard(modell, _http_get=liste, _http_post=post):
        s = {x["schritt"]: x for x in modell.diagnose()}
    eq([s[k]["ok"] for k in ("adresse", "server", "modell", "format", "werkzeuge")],
       [True, True, True, True, False])
    ok("--jinja" in s["werkzeuge"]["ausweg"], "der Ausweg fuer fehlende Werkzeuge fehlt")


# ───────────────────────────────────────── 8. Aufgaben: Art, Beleg, Zusammenfuehren

def t_extract_ordnet_ein_und_fuehrt_zusammen():
    material = ("Anna sagt zu, den Process Owner fuer den Software-Check zu bestaetigen und das Formular "
                "einzureichen. Man muesste irgendwann das Dashboard zum Migrationsfortschritt bauen. "
                "Die Angebotsvergleich liegt in Ordner 12, Bodo prueft die Unterlagen dort.")
    fake_payload = {
        "ziel": "", "entscheidungen": [], "kernteil": [], "parkplatz": [],
        "actions": [
            {"was": "Process Owner fuer den Software-Check bestaetigen und Formular einreichen", "wer": "Anna",
             "bis": "", "art": "zusage",
             "beleg": "Anna sagt zu, den Process Owner fuer den Software-Check zu bestaetigen"},
            {"was": "Formular einreichen", "wer": "Anna", "bis": "", "art": "zusage", "beleg": ""},
            {"was": "Dashboard zum Migrationsfortschritt bauen", "wer": "", "bis": "", "art": "absicht",
             "beleg": "Man muesste irgendwann das Dashboard zum Migrationsfortschritt bauen"},
            {"was": "Angebotsvergleich pruefen (liegt in Ordner 12)", "wer": "Bodo", "bis": "",
             "art": "zusage", "beleg": "Bodo hat versprochen, alles bis Freitag zu liefern"},
            {"was": "Pruefe die im Ordner 12 abgelegten Unterlagen zur Angebotsvergleich", "wer": "Bodo",
             "bis": "", "art": "zusage", "beleg": ""},
            {"was": "Raum fuer den Workshop buchen", "wer": "Raum Elbe III Erdgeschoss", "bis": "",
             "art": "zusage", "beleg": ""},
        ],
    }
    playbook_view = {"meeting_type": "checkin", "kernteil": [], "label": "Checkin", "nachbereitung": []}
    with _AttrGuard(modell, complete_json=lambda messages, schema, **kw: (fake_payload, [])):
        r = nachbereiten_modell.extract(material, playbook_view, {"title": "Checkin X"})
    texte = [a["was"] for a in r["actions"]]
    eq(len(texte), 3, f"Satzteil und Umschreibung muessen in ihrer Aufgabe aufgehen: {texte}")
    ok("Formular einreichen" not in texte, "der Satzteil steht noch einzeln da")
    anna = next(a for a in r["actions"] if a["wer"] == "Anna")
    ok(anna["beleg"].startswith("Anna sagt zu"), "ein woertlicher Beleg bleibt")
    bodo = next(a for a in r["actions"] if a["wer"] == "Bodo")
    eq(bodo["beleg"], "", "ein Beleg, der nicht im Material steht, entfaellt:")
    ok(bodo["was"].startswith("Pruefe die im Ordner"), "der laengere Text bleibt")
    raum = next(a for a in r["actions"] if "Raum" in a["was"])
    eq(raum["wer"], "", "ein Raum ist keine Person:")
    ok(any(p.startswith("Noch ohne Zusage: Dashboard") for p in r["parkplatz"]),
       f"eine Absicht gehoert in den Parkplatz: {r['parkplatz']}")
    eq(r["eingeordnet"]["absicht"], 1)
    ok(not nachbereiten_modell.aehnlich("Mit Theo das Budget fuer eine Testperson klaeren",
                                        "Mit Theo verbindlich klaeren, wie die Testkapazitaeten eingesetzt werden"),
       "zwei verschiedene Aufgaben mit derselben Person duerfen nicht zusammenfallen")


def t_lease_haelt_sich_an_den_vertrag():
    """Laib-Vertrag (docs/adr/0011): Ruhe nach einem Menschen, 202 -> GET abfragen statt neu senden,
    409 held -> Halter und Ende nennen, eigene liegengebliebene Lease zuerst zurueckgeben."""
    import time as _time
    rufe = []
    stand = {"state": "none", "holder": "", "allowed": ["klein"], "mode": "haushalt", "last_human_at": None}
    antwort = {"POST": {"ok": True, "state": "ready", "renew_after": 0}}

    def fake_lease(method, url, payload, key, timeout):
        rufe.append(method)
        if method == "GET":
            return dict(stand)
        if method == "POST":
            if isinstance(antwort["POST"], Exception):
                raise antwort["POST"]
            if antwort["POST"].get("state") == "preparing":
                stand.update(state="ready", holder="2ndbrain")      # beim naechsten GET ist es geladen
            return antwort["POST"]
        stand.update(state="none", holder="")
        return {"ok": True, "state": "released"}

    env, attrs = _modell_umgebung({"url": "http://modell.test", "model": "klein"})
    with env, attrs, _AttrGuard(modell, _http_lease=fake_lease, _schlafen=lambda s: None):
        os.environ["VAULT_LLM_KEY"] = "k"

        stand["last_human_at"] = _time.time() - 60
        ok_, grund = modell.lease_anfordern("gross")
        ok(not ok_ and "jemand gefragt" in grund and "POST" not in rufe, f"nach einem Menschen wird nicht angefordert: {grund}")

        stand["last_human_at"] = _time.time() - 3600
        antwort["POST"] = {"ok": True, "state": "preparing", "retry_after": 30}
        del rufe[:]
        ok_, grund = modell.lease_anfordern("gross")
        ok(ok_, f"nach dem Laden muss die Lease stehen: {grund}")
        eq(rufe.count("POST"), 1, "waehrend des Ladens wird GET abgefragt, nicht noch einmal gesendet:")
        ok(modell.lease_freigeben() and stand["holder"] == "", "Rueckgabe mit DELETE")

        antwort["POST"] = modell.LeaseAbgelehnt(409, {"ok": False, "reason": "held", "holder": "foundry",
                                                       "expires_at": 1794950000, "mode": "full", "allowed": ["klein", "mittel"]})
        ok_, grund = modell.lease_anfordern("gross")
        ok(not ok_ and "foundry hält den Modell-Server bis" in grund, f"Halter und Ende fehlen: {grund}")
        ok_, grund = modell.lease_anfordern("mittel")
        ok(ok_ and modell._LEASE["model"] == "", "im fremden Fenster schon erlaubt: weiter ohne eigene Lease")

        stand.update(state="ready", holder="2ndbrain")              # von einem abgebrochenen Lauf
        antwort["POST"] = {"ok": True, "state": "ready", "renew_after": 0}
        del rufe[:]
        ok(modell.lease_anfordern("gross")[0], "nach dem Aufraeumen neu anfordern")
        eq(rufe[:3], ["GET", "DELETE", "GET"], "die liegengebliebene eigene Lease geht zuerst zurueck:")
        modell.lease_freigeben()


def t_gruppen_zusammenfuehren_prueft_die_wahl_des_modells():
    actions = [
        {"was": "Enablement-Sessions organisieren (Raum, Einladungen, Wellen)", "wer": "Otto", "bis": "", "art": "zusage", "beleg": ""},
        {"was": "Git-Lizenzen zuweisen", "wer": "Rita", "bis": "", "art": "zusage", "beleg": "Rita kuemmert sich"},
        {"was": "Koordination und Terminierung der Waves uebernehmen", "wer": "Otto Muster", "bis": "2026-10-01", "art": "zusage", "beleg": ""},
        {"was": "Sandbox auf die Endgeraete bringen", "wer": "Rita", "bis": "", "art": "zusage", "beleg": ""},
        {"was": "Sessions inhaltlich vorbereiten", "wer": "Anna", "bis": "", "art": "zusage", "beleg": ""},
        {"was": "Liste der Teilnehmenden bereinigen", "wer": "", "bis": "", "art": "absicht", "beleg": ""},
    ]
    # 0+2 dieselbe Person (Vorname/voller Name) -> eine; 1+4 verschiedene Personen -> bleiben zwei;
    # 99 gibt es nicht; 3 steht schon in keiner gueltigen Gruppe; Nummern nur einmal
    antwort = {"gruppen": [[0, 2], [1, 4], [3, 99], [2, 5]]}
    with _AttrGuard(modell, complete_json=lambda messages, schema, **kw: (antwort, [])):
        out = nachbereiten_modell.gruppen_zusammenfuehren(actions)
    eq(len(out), 5, f"nur die eine gueltige Gruppe faellt zusammen: {[a['was'] for a in out]}")
    eq((out[0]["wer"], out[0]["bis"]), ("Otto Muster", "2026-10-01"), "der vollere Name und die Frist bleiben:")
    ok(any(a["wer"] == "Anna" for a in out) and sum(a["wer"] == "Rita" for a in out) == 2,
       "Aufgaben verschiedener Personen duerfen nie zusammenfallen")

    def kaputt(messages, schema, **kw):
        raise modell.LLMUnavailableError("HTTPError: HTTP Error 409: Conflict")

    with _AttrGuard(modell, complete_json=kaputt):
        eq(len(nachbereiten_modell.gruppen_zusammenfuehren(actions)), 6, "ohne Modell bleibt die Liste:")
    eq(modell.fehler_einordnen("OSError: HTTP 409: Modell gross-a ist im Modus haushalt nicht erlaubt. Im Haushalt "
                               "antwortet nur das Haushaltsmodell mittel-b. Ein anderes Modell braucht eine Lease.")["erlaubt"],
       ["mittel-b"], "auch diese Fassung der Sperre nennt das erlaubte Modell:")


def t_ausgefallene_pruefung_steht_im_ergebnis():
    d = Path(tempfile.mkdtemp(prefix="llmtest-"))
    cfg = d / "llm.config.json"
    cfg.write_text('{"url": "http://modell.test", "model": "entwurf", "model_pruefung": "pruefer"}', encoding="utf-8")
    payload = {"ziel": "", "entscheidungen": [{"was": "Budget freigeben", "wer": "A", "datum": ""}],
               "actions": [], "kernteil": [], "parkplatz": []}

    def fake(messages, schema, **kw):
        if kw.get("model") == "pruefer":
            raise modell.LLMUnavailableError("OSError: HTTP 409: Modell pruefer ist im Modus haushalt nicht erlaubt.")
        return payload, []

    view = {"meeting_type": "checkin", "kernteil": [], "label": "Checkin", "nachbereitung": []}
    with _EnvGuard(VAULT_LLM_URL=None, VAULT_LLM_MODEL=None), _AttrGuard(modell, CONFIG_PATH=cfg, complete_json=fake):
        r = nachbereiten_modell.extract("Material fuer den Test. " * 5, view, {"title": "X"})
    ok("pruefer" in r.get("pruefung_ausgefallen", "") and "nicht zu" in r["pruefung_ausgefallen"],
       f"der Ausfall der Pruefstufe muss mit Ursache im Ergebnis stehen: {r.get('pruefung_ausgefallen')!r}")
    eq(len(r["entscheidungen"]), 1, "der Entwurf gilt:")


def t_beleg_steht_als_unterpunkt():
    text = _NOTE_TEMPLATE.format(material="egal")
    result = {"entscheidungen": [], "kernteil": [], "parkplatz": [], "offene_fragen": [],
              "actions": [{"was": "Formular einreichen", "wer": "Yzx", "bis": "", "beleg": "Yzx reicht das Formular ein"},
                          {"was": "Termin aufsetzen", "wer": "Yzx", "bis": ""}]}
    neu, counts = nachbereiten.write_extract(text, result, {"kernteil": []}, None, {})
    eq(counts["actions_neu"], 2, "gezaehlt werden Punkte, nicht Zeilen:")
    ok("- [ ] Formular einreichen — Yzx (?)\n    - Beleg: „Yzx reicht das Formular ein“\n- [ ] Termin aufsetzen" in neu,
       "der Beleg muss eingerueckt unter seinem Punkt stehen")
    import aufgaben
    eq(len(aufgaben.tasks_in_text(neu, "meeting")), 2, "der Unterpunkt ist kein eigener Punkt:")
    eq(nachbereiten.write_extract(neu, result, {"kernteil": []}, None, {})[0], neu, "zweites Schreiben aendert nichts:")


# ───────────────────────────────────────── 9. Alles neu aufbauen

def t_neuaufbau_schuetzt_den_vault():
    """Schreibende Schritte laufen nur in einer Kopie; die Kopie liegt nie im Vault; aus Themen geht
    nur heraus, was aus einem zurueckgesetzten Termin stammt - samt Unterpunkten."""
    import neuaufbau
    for schritt in (neuaufbau.zuruecksetzen, neuaufbau.bauen, neuaufbau.vergleichen, neuaufbau.erledigt_uebernehmen):
        try:
            schritt()
            ok(False, f"{schritt.__name__} haette im Vault abbrechen muessen")
        except SystemExit as e:
            ok("keine Neuaufbau-Kopie" in str(e), f"Grund fehlt: {e}")
    r = neuaufbau.anlegen(_VAULT / "drinnen")
    ok(not r["ok"] and "nicht im Vault" in r["grund"], f"eine Kopie im Vault muss abgelehnt werden: {r}")

    thema = "\n".join([
        "## Offene Punkte",
        "- [ ] Bleibt — [[a-b|A B]] ➕ 2026-09-01 (→ [[2026-09-01 - alt]])",
        "- [ ] Geht — [[a-b|A B]] ➕ 2026-09-22 (→ [[2026-09-22 - neu]])",
        "    - Beleg: „gehört zum entfernten Punkt“",
        "- [x] Geht auch ➕ 2026-09-22 ✅ 2026-09-25 (→ [[2026-09-22 - neu]])",
        "## Event Log",
        "- [2026-09-22] [DECISION] Geht (→ [[2026-09-22 - neu]])",
        "- [2026-09-01] [RISK] Bleibt (→ [[2026-09-01 - alt]])",
        "Fließtext mit (→ [[2026-09-22 - neu]]) bleibt, er ist keine Listenzeile"])
    neu, n = neuaufbau._zeilen_mit_quelle_entfernen(thema, {"2026-09-22 - neu"})
    eq(n, 3, "zwei Punkte und eine Log-Zeile:")
    ok("Beleg" not in neu and "Geht —" not in neu and "Bleibt —" in neu and "[RISK] Bleibt" in neu
       and "Fließtext" in neu, f"falsch entfernt:\n{neu}")
    eq(neuaufbau._abschnitt_leeren("## Actions\n- [ ] x\n\n## Parkplatz\n- y\n", "## Actions"),
       "## Actions\n\n## Parkplatz\n- y\n", "nur der eine Abschnitt wird geleert:")

    # Auf der Befehlszeile kommt immer ein Ergebnis mit Grund - nie nur ein Abbruch ohne JSON
    import contextlib
    import io as _io
    import json as _json
    for args, erwartet in ((["zuruecksetzen", "--json"], "keine Neuaufbau-Kopie"),):
        aus = _io.StringIO()
        with contextlib.redirect_stdout(aus):
            code = neuaufbau.main(args)
        r = _json.loads(aus.getvalue().strip().splitlines()[-1])
        ok(code == 1 and r["ok"] is False and erwartet in r["grund"], f"Grund im JSON: {r}")
    with _AttrGuard(neuaufbau, anlegen=lambda ziel=None: (_ for _ in ()).throw(PermissionError("gesperrt"))):
        aus, err = _io.StringIO(), _io.StringIO()
        with contextlib.redirect_stdout(aus), contextlib.redirect_stderr(err):
            code = neuaufbau.main(["anlegen", "--json"])
        r = _json.loads(aus.getvalue().strip().splitlines()[-1])
        ok(code == 1 and r["grund"] == "PermissionError: gesperrt" and "Traceback" in err.getvalue(),
           f"ein unerwarteter Fehler steht mit Art und Text im Ergebnis: {r}")

    # Alte Termin-Notiz: ihr Text wird Material - eigene Ueberschriften ruecken unter die Mitschrift
    alt = "# Runde vom Juni\n\nWir haben viel besprochen.\n\n## Entscheidungen\n- Budget frei\n\n```\n## kein Kopf\n```\n### Tief\nText\n"
    m = neuaufbau.als_material(alt)
    ok(m.startswith("## Mitschrift\n\n### Runde vom Juni") and "### Entscheidungen\n- Budget frei" in m and "#### Tief" in m
       and "```\n## kein Kopf\n```" in m, f"Ueberschriften ruecken ein, Code bleibt:\n{m}")
    voll = "---\ntype: meeting\n---\n\n" + m
    ok("Budget frei" in nachbereiten.find_material(voll) and "Wir haben viel besprochen" in nachbereiten.find_material(voll),
       "der ganze alte Text zaehlt als Material")
    eq(nachbereiten.ms.section_text(voll, "## Actions").strip(), "", "die neuen Abschnitte stehen leer bereit:")
    archiv = nachbereiten.vp.MEETINGS_DIR / "2026-06" / "2026-06-29 - runde.md"
    basis = {"processed": True, "date": "2026-06-29"}
    eq([neuaufbau._ist_alte_notiz(archiv, fm) for fm in (
        {**basis, "type": "meeting"}, basis, {**basis, "type": "email-thread"}, {**basis, "type": "migration-report"},
        {"type": "meeting", "date": "2026-06-29"}, {"type": "meeting", "processed": True})],
       [True, True, False, False, False, False], "eingearbeitet, datiert, kein Bericht und keine Mail:")
    ok(not neuaufbau._ist_alte_notiz(nachbereiten.ACTIVE_DIR / "x.md", {**basis, "type": "meeting"}), "nur im Archiv")

    # Reihenfolge: wie die Termine stattfanden - nach Datum, nicht nach Dateiname
    import auto
    daten = {"2026-09-01 - neu.md": "2026-09-01", "Alte Runde ohne Datum im Namen.md": "2025-04-08",
             "2026-03-16-mitte.md": "2026-03-16", "zzz ohne datum.md": ""}
    with _AttrGuard(auto, requested_notes=lambda: [Path("active-meetings") / n for n in daten]), \
            _AttrGuard(neuaufbau.vp, read_frontmatter_head=lambda p, max_bytes=8192: {"date": daten[Path(p).name]}):
        eq([p.name for p in neuaufbau._vorgemerkt()],
           ["Alte Runde ohne Datum im Namen.md", "2026-03-16-mitte.md", "2026-09-01 - neu.md", "zzz ohne datum.md"],
           "die aeltesten zuerst, Undatiertes zuletzt:")

    # Laeuft schon einer? Ein zweiter Start wird abgelehnt; fortgesetzt wird nur eine Kopie mit dem
    # heutigen Umfang (mit den alten Termin-Notizen), die juengste zuerst.
    ok(neuaufbau.prozess_lebt(os.getpid()) and not neuaufbau.prozess_lebt(0) and not neuaufbau.prozess_lebt(None)
       and not neuaufbau.prozess_lebt("x"), "prozess_lebt")
    alt_kopie = {"stufe": "baut", "am": "2026-11-18T08:00:00", "zurueckgesetzt": {"termine": 41}, "ziel": "/alt"}
    neue_kopie = {"stufe": "unterbrochen", "am": "2026-11-18T09:00:00", "zurueckgesetzt": {"termine": 23, "alte_termine": 209},
                  "ziel": "/neu"}
    fertig = {"stufe": "verglichen", "am": "2026-11-18T10:00:00", "zurueckgesetzt": {"alte_termine": 1}, "ziel": "/fertig"}
    with _AttrGuard(neuaufbau, kopien=lambda: [(Path("/alt"), alt_kopie), (Path("/neu"), neue_kopie), (Path("/fertig"), fertig)]):
        eq(neuaufbau._fortsetzbare().get("ziel"), "/neu", "nicht die alte Kopie ohne alte Notizen, nicht die fertige:")
    with _AttrGuard(neuaufbau, kopien=lambda: [(Path("/alt"), alt_kopie)]):
        eq(neuaufbau._fortsetzbare(), {}, "eine Kopie aus einer aelteren Version wird nicht fortgesetzt:")
    rechnet = {"stufe": "baut", "am": "2026-11-18T09:00:00", "pid": os.getpid(), "rechner": neuaufbau._rechner()}
    with _AttrGuard(neuaufbau, kopien=lambda: [(Path("/k"), rechnet), (Path("/tot"), {**rechnet, "pid": 0}),
                                               (Path("/woanders"), {**rechnet, "rechner": "anderer-rechner"})]):
        eq([p.name for p, _ in neuaufbau.laufende()], ["k"], "nur lebende Prozesse auf diesem Rechner:")
        r = neuaufbau.alles()
        ok(r["ok"] is False and "rechnet schon ein Neuaufbau" in r["grund"] and "beenden" in r["grund"],
           f"ein zweiter Start wird abgelehnt, mit Ausweg: {r}")
    with _AttrGuard(neuaufbau, kopien=lambda: [], fremde_prozesse=lambda: [4711]):
        r = neuaufbau.alles()
        ok(r["ok"] is False and "4711" in r["grund"] and "älteren Version" in r["grund"],
           f"auch ein Lauf, der sich nur an der Befehlszeile zeigt: {r}")

    # Der eigene Start laeuft ueber mehrere Python-Prozesse (Starter -> Befehlszeile -> Schritt): weder
    # Vorfahren noch Nachkommen sind ein fremder Lauf - sonst blockierte sich der Neuaufbau selbst.
    prozesse = [["100", "1", "obsidian.exe"],
                ["200", "100", "python.exe -m secondbrain neuaufbau alles --json"],        # Starter
                ["300", "200", "C:\\py\\python.exe -m secondbrain neuaufbau alles --json"],  # ich
                ["400", "300", "python neuaufbau.py bauen --json"],                         # mein Schritt
                ["500", "100", "python.exe -m secondbrain neuaufbau alles --json"],        # ein anderer Lauf
                ["600", "500", "python neuaufbau.py bauen --json"],                         # dessen Schritt
                ["700", "100", "python -m secondbrain neuaufbau stand --json"],            # fragt nur
                ["800", "100", "node neuaufbau alles"]]                                     # kein Python
    eq(neuaufbau._fremde(prozesse, 300), [500, 600], "nur der andere Lauf und sein Schritt:")
    eq(neuaufbau._fremde(prozesse, 700), [200, 300, 400, 500, 600], "wer nur fragt, sieht alle laufenden:")
    eq(neuaufbau._fremde([["1", "1", "python neuaufbau bauen"]], 1), [], "ein Kreis in den Eltern haengt nichts auf:")

    kopie = Path(tempfile.mkdtemp(prefix="neuaufbau-")) / "kopie"
    r = neuaufbau.anlegen(kopie)
    ok(r["ok"] and (kopie / ".2ndbrain" / "daten" / neuaufbau.MARKE).is_file(), f"Kopie mit Marke: {r}")
    ok(not (_VAULT / ".2ndbrain" / "daten" / neuaufbau.MARKE).exists(), "der Vault selbst bekommt keine Marke")
    ok(not neuaufbau.anlegen(kopie)["ok"], "ein vorhandener Ordner wird nicht ueberschrieben")


# ───────────────────────────────────────── 10. Organisation

def t_organisation_liest_die_linie():
    """Von Hand vor Verzeichnis vor Organigramm; "Direct Reports" zaehlt als Verzeichnis; ein Kreis in
    den Daten haengt nichts auf; das Verhaeltnis zu mir stimmt in jede Richtung."""
    import organisation
    people = _VAULT / "entities" / "people"
    people.mkdir(parents=True, exist_ok=True)

    def seite(slug, name, block="", fm=""):
        people.joinpath(f"{slug}.md").write_text(
            f"---\ntype: person\nname: {name}\n{fm}---\n# {name}\n\n<!-- orgchart-auto:start -->\n{block}\n<!-- orgchart-auto:end -->\n",
            encoding="utf-8", newline="\n")

    seite("org-chefin", "Chefin Oben", "- **Direct Reports (M365):** [[org-ich|Ich Selbst]] · [[org-peer|Peer Kollege]]")
    seite("org-ich", "Ich Selbst", "- **Berichtet fachlich an (Organigramm):** [[org-fremd|Fremd Anders]]\n"
          "- **M365 (2026-09-16):** Titel · Abteilung · Vorgesetzt: [[org-chefin|Chefin Oben]]")
    seite("org-peer", "Peer Kollege", "- **Berichtet fachlich an (Organigramm):** [[org-fremd|Fremd Anders]]")
    seite("org-direkt", "Direkt Bericht", "- **Berichtet fachlich an (Organigramm):** [[org-ich|Ich Selbst]]")
    seite("org-enkel", "Enkel Bericht", "- **Berichtet fachlich an (Organigramm):** [[org-fremd|Fremd Anders]]",
          fm="berichtet_an: '[[org-direkt]]'\n")
    seite("org-fremd", "Fremd Anders", "- **Berichtet fachlich an (Organigramm):** [[org-kreis|Kreis Lauf]]")
    seite("org-kreis", "Kreis Lauf", "- **Berichtet fachlich an (Organigramm):** [[org-fremd|Fremd Anders]]")
    seite("org-allein", "Allein Ohne")

    org = organisation.lade()
    eq((org.vorgesetzt("org-ich"), org.personen["org-ich"]["quelle"]), ("org-chefin", "Verzeichnis"),
       "Verzeichnis schlaegt Organigramm:")
    eq((org.vorgesetzt("org-peer"), org.personen["org-peer"]["quelle"]), ("org-chefin", "Verzeichnis"),
       "wer unter Direct Reports steht, berichtet dorthin:")
    eq((org.vorgesetzt("org-enkel"), org.personen["org-enkel"]["quelle"]), ("org-direkt", "von Hand"),
       "von Hand schlaegt alles:")
    eq(org.linie("org-enkel"), ["org-direkt", "org-ich", "org-chefin"])
    ok(len(org.linie("org-fremd")) <= 2, "ein Kreis in den Daten darf nicht endlos laufen")
    eq(org.alle_berichte("org-ich"), ["org-direkt", "org-enkel"])
    eq([org.verhaeltnis("org-ich", s) for s in ("org-direkt", "org-enkel", "org-chefin", "org-peer", "org-fremd", "org-allein", "gibt-es-nicht")],
       [organisation.DIREKT, organisation.LINIE, organisation.VORGESETZT, organisation.KOLLEGE, organisation.ANDERE,
        organisation.UNBEKANNT, organisation.UNBEKANNT])
    b = organisation.bild(org, "org-ich", {"org-direkt": 3})
    ok('p_org_chefin --> p_org_ich' in b and 'p_org_ich --> p_org_direkt' in b and 'p_org_direkt --> p_org_enkel' in b,
       f"Linie ueber mir, direkte Berichte und die Ebene darunter:\n{b}")
    ok('Direkt Bericht<br/>3 offen' in b, "offene Zusagen stehen am Namen")
    eq(organisation.luecken(org, "org-ich", {"org-allein": 2, "org-direkt": 1, "org-ich": 5}), ["org-allein"],
       "zu pflegen ist, wer Zusagen hat und keinen Platz:")


# ───────────────────────────────────────── 11. Triage

def t_triage_ordnet_ein():
    """Die Regeln an echten Formen von Punkten (Namen erfunden) - in der Reihenfolge des Moduls."""
    import organisation
    import triage
    from datetime import date as _date
    import aufgaben
    eq([triage.art_aus_woertern(s) for s in (
        "Freigabe für die Löschung der zwei Buchungen geben", "Mit Theo klären, wie die Testkapazitäten eingesetzt werden",
        "Dashboard zum Migrationsfortschritt erstellen", "Mit Till abstimmen und entscheiden, ob daraus Routing wird",
        "Wissenstransfer zur Transformationslogik")],
       ["entscheiden", "abstimmen", "ausarbeiten", "entscheiden", "unklar"])
    ok(triage.ist_atlas("Füge das fehlende Ereignis „Packstück ausgelagert“ in die Landkarte und Ereignisliste ein."))
    ok(triage.ist_atlas("Ordne „Schadensfotos archiviert“ dem Kontext Warehouse Processing zu"))
    ok(not triage.ist_atlas("Emil und Rita in die Domain-Atlas-Gruppe aufnehmen"), "eine Gruppe ist keine Kanon-Aenderung")
    ok(not triage.ist_atlas("Domain Atlas Workshop-Tool an das Team teilen"))
    eq(triage.anderer_handelnder("Prüfung durch Nordfracht, ob die gelbe Kennzeichnung noch begründet ist"), "Nordfracht")
    eq(triage.anderer_handelnder("Produktbereiche Nord und Sued müssen eine gemeinsame Entscheidung treffen"),
       "Produktbereiche Nord und Sued")
    eq(triage.anderer_handelnder("Mit Theo klären, wer das Budget trägt"), "")

    org = organisation.Organisation({
        "ich": {"name": "Ich Selbst", "rolle": "", "team": "", "aktiv": True, "vorgesetzt": "", "quelle": ""},
        "bert": {"name": "Bert Direkt", "rolle": "", "team": "", "aktiv": True, "vorgesetzt": "ich", "quelle": "Verzeichnis"},
        "carla": {"name": "Annaa Enkel", "rolle": "", "team": "", "aktiv": True, "vorgesetzt": "bert", "quelle": "Organigramm"},
        "dora": {"name": "Dora Fremd", "rolle": "", "team": "", "aktiv": True, "vorgesetzt": "", "quelle": ""}})
    linie = triage._in_meiner_linie(org, "ich")
    eq(linie, {"bert": organisation.DIREKT, "carla": organisation.LINIE})
    themen = {"betrieb": {"titel": "Betrieb", "fokus": False, "parent": "", "beteiligte": ["carla", "dora"], "naechster_termin": ""},
              "kern": {"titel": "Kern", "fokus": True, "parent": "", "beteiligte": ["bert"], "naechster_termin": ""},
              "unter": {"titel": "Unter", "fokus": False, "parent": "kern", "beteiligte": [], "naechster_termin": ""}}
    heute = _date(2026, 11, 18)

    def e(text, thema="betrieb", created="2026-11-10", due=None, art=None):
        t = aufgaben.Task(status=" ", text=text, owner="ich", topics=[thema], created=created, due=due)
        return triage.einordnen(t, art=art or triage.art_aus_woertern(text), ich="ich", org=org, linie=linie,
                                themen=themen, heute=heute)

    eq(e("Dashboard zum Fortschritt erstellen")["vorschlag"], "uebergeben")
    eq(e("Dashboard zum Fortschritt erstellen")["an"], "carla", "wer am Thema beteiligt und in meiner Linie ist:")
    r = e("Mit Bert das Dashboard zum Fortschritt erstellen")
    eq((r["vorschlag"], r["an"]), ("uebergeben", "bert"), "im Punkt genannt und direkter Bericht geht vor:")
    eq(e("Bert in die Gruppe aufnehmen und Zugang einrichten")["an"], "carla", "wer nur Gegenstand ist, ist nicht genannt:")
    eq(e("Dashboard erstellen", thema="unter")["vorschlag"], "selbst", "Fokus (auch ueber das Dach-Thema) bleibt bei mir:")
    eq(e("Freigabe geben")["vorschlag"], "selbst")
    eq(e("Dashboard erstellen", created="2026-07-01")["vorschlag"], "parken")
    eq(e("Dashboard erstellen", created="2026-07-01", due="2026-12-01")["vorschlag"], "uebergeben", "mit Frist wird nicht geparkt:")
    eq(e("Freigabe geben", created="2026-07-01")["vorschlag"], "selbst", "eine Entscheidung wird nicht geparkt:")
    eq(e("Prüfung durch Nordfracht, ob die Kennzeichnung begründet ist")["vorschlag"], "nachfassen")
    eq(e("Mit Theo klären, wer das Budget trägt")["vorschlag"], "selbst")


def t_triage_matrix_und_gruppen():
    """Matrix: uebergeben geht auch an den Fachkreis (nach Rolle oder benannt) und an Gruppen - ein Team,
    das der Punkt nennt, oder die Runde, die das Thema behandelt. Die eigene Linie geht vor."""
    import organisation
    import triage
    import aufgaben
    from datetime import date as _date
    P = lambda name, chef="", rolle="", team="": {"name": name, "rolle": rolle, "team": team, "aktiv": True,   # noqa: E731
                                                   "vorgesetzt": chef, "quelle": ""}
    org = organisation.Organisation({
        "ich": P("Ich Selbst"), "bert": P("Bert Direkt", "ich"),
        "arno": P("Arno Architekt", "wer-anders", "Lead Architect"), "eva": P("Eva Einzeln", "wer-anders", "Product Owner"),
        "fritz": P("Fritz Fremd", "wer-anders", "Entwickler"), "wer-anders": P("Wer Anders")})
    k = organisation.kreis(org, "ich", {"rollen": ["architekt", "architect"], "personen": ["eva"], "gruppen": []})
    eq(k, {"bert": organisation.DIREKT, "arno": organisation.MATRIX, "eva": organisation.MATRIX},
       "Linie, Rolle und einzeln benannt - sonst niemand:")
    gruppen = {"lager-team": {"art": "team", "name": "Lager-Team", "namen": ["Lager-Team", "LGT"], "lead": "fritz", "thema": "", "personen": []},
               "architektur": {"art": "reihe", "name": "Architektur-Runde", "namen": ["Architektur-Runde"], "lead": "", "thema": "plattform", "personen": ["arno"]}}
    themen = {"plattform": {"titel": "Plattform", "fokus": False, "parent": "", "beteiligte": [], "naechster_termin": ""},
              "edi": {"titel": "EDI", "fokus": False, "parent": "", "beteiligte": ["arno", "fritz"], "naechster_termin": ""}}

    def e(text, thema):
        t = aufgaben.Task(status=" ", text=text, owner="ich", topics=[thema], created="2026-11-10")
        return triage.einordnen(t, art=triage.art_aus_woertern(text), ich="ich", org=org, linie=k, themen=themen,
                                heute=_date(2026, 11, 18), gruppen=gruppen)

    r = e("Schnittstellenbeschreibung erstellen", "edi")
    eq((r["vorschlag"], r["an"]), ("uebergeben", "arno"), "am Thema beteiligt und im Fachkreis:")
    ok("Fachkreis (Matrix)" in r["grund"], f"der Grund nennt die Matrix: {r['grund']}")
    r = e("Mit Arno Architekt und Bert Direkt das Zielbild ausarbeiten", "edi")
    eq(r["an"], "bert", "die eigene Linie geht vor dem Fachkreis:")
    r = e("Gefahrgutdaten mit dem Lager-Team dokumentieren", "edi")
    eq((r["an"], r.get("an_art")), ("gruppe:lager-team", "team"), "ein genanntes Team geht vor 'am Thema beteiligt':")
    r = e("Zielbild für die Plattform dokumentieren", "plattform")
    eq((r["an"], r.get("an_art")), ("gruppe:architektur", "reihe"), "sonst die Runde, die das Thema behandelt:")
    eq(triage._genannte_gruppe("Mit LGT klären", gruppen), "", "ein kurzer Name (unter fuenf Zeichen) zaehlt nicht:")


def t_triage_wendet_an_der_quelle_an():
    import triage
    from datetime import date as _date
    d = _VAULT / "active-meetings"
    d.mkdir(parents=True, exist_ok=True)
    people = _VAULT / "entities" / "people"
    people.mkdir(parents=True, exist_ok=True)
    people.joinpath("tri-bert.md").write_text("---\ntype: person\nname: Bert Direkt\n---\n# Bert Direkt\n", encoding="utf-8", newline="\n")
    note = d / "2026-11-10 - checkin - Triage.md"
    note.write_text("---\ntype: meeting\ndate: '2026-11-10'\n---\n\n## Actions\n"
                    "- [ ] Dashboard erstellen — [[tri-ich|Ich Selbst]] ➕ 2026-11-10\n"
                    "    - Beleg: „ich baue das Dashboard“\n"
                    "- [ ] Alte Liste aufräumen — [[tri-ich|Ich Selbst]] ➕ 2026-07-01\n"
                    "- [ ] Freigabe geben — [[tri-ich|Ich Selbst]] ➕ 2026-11-10\n", encoding="utf-8", newline="\n")
    rel = note.relative_to(_VAULT).as_posix()
    heute = _date(2026, 11, 18)
    eq(triage.anwenden(rel, 6, "Etwas ganz anderes", "parken", heute=heute)["ok"], False, "falscher Text an der Zeile:")
    ok(triage.anwenden(rel, 6, "Dashboard erstellen", "uebergeben", "tri-bert", heute=heute)["ok"])
    text = note.read_text(encoding="utf-8")
    ok("- [ ] Dashboard erstellen — [[tri-bert|Bert Direkt]] ➕ 2026-11-10\n    - Übergeben von" in text
       and "Triage 18.11.2026\n    - Beleg:" in text, f"Person wechselt, Vermerk steht darunter, der Beleg bleibt:\n{text}")
    zeile = text.split("\n").index("- [ ] Alte Liste aufräumen — [[tri-ich|Ich Selbst]] ➕ 2026-07-01")
    ok(triage.anwenden(rel, zeile, "Alte Liste aufräumen", "parken", heute=heute)["ok"])
    text = note.read_text(encoding="utf-8")
    ok("- [-] Alte Liste aufräumen" in text and "Geparkt am 18.11.2026" in text, "geparkt heisst [-] mit Vermerk")
    zeile = text.split("\n").index("- [ ] Freigabe geben — [[tri-ich|Ich Selbst]] ➕ 2026-11-10")
    vorher = text
    ok(triage.anwenden(rel, zeile, "Freigabe geben", "selbst", heute=heute)["ok"])
    eq(note.read_text(encoding="utf-8"), vorher, "selbst aendert die Notiz nicht:")
    ok(any(v["als"] == "selbst" for v in triage.lade_zustand()["entschieden"].values()), "die Entscheidung ist gemerkt")
    import aufgaben
    offen = [t for t in aufgaben.tasks_in_text(note.read_text(encoding="utf-8"), "meeting") if t.is_open]
    eq(len(offen), 2, "Vermerke sind keine eigenen Punkte, der geparkte ist nicht mehr offen:")


# ───────────────────────────────────────── 12. Stand als Delta, Briefing, Lagebild, Altbestand

def t_stand_delta_und_risiko_gruppen():
    import stand
    import aufgaben
    from datetime import date as _date
    heute = _date(2026, 9, 30)
    events = [("2026-09-28", "STATUS", "Datenlieferung geht an das Data-Warehouse-Team"),
              ("2026-09-02", "RISK", "Lager Nord: fehlende Reife der Prozessdefinition"),
              ("2026-09-02", "RISK", "Lager Nord: mangelnde Kapazitaet am Teststandort"),
              ("2026-09-02", "RISK", "Lager Nord: Testkit fehlt"),
              ("2026-09-11", "RISK", "Zahlungsziele (Mail X, 11.09.2026): Zahlungsbedingungen nicht pflegbar"),
              ("2026-09-22", "RISK", "Ausstehende Stammdaten fuer Artikel und Gefahrgut"),
              ("2026-09-22", "RISK", "Ausstehende Stammdaten fuer Gefahrgut und Artikel fehlen weiter"),
              ("2026-07-01", "RISK", "Altes Risiko ausserhalb des Fensters"),
              ("2026-08-01", "DECISION", "Zu alt fuer Neu")]
    g = stand.risiko_gruppen(events, heute)
    eq(g[0], ("Lager Nord", 3), "Stichwort vor dem Doppelpunkt gruppiert:")
    eq(sorted(n for _, n in g), [1, 2, 3], f"aehnlicher Wortlaut faellt zusammen, das alte Risiko zaehlt nicht: {g}")
    ok(any(name == "Zahlungsziele" for name, _ in g), "die Klammer am Stichwort faellt weg")
    eq(stand.neu_seit(events, heute), ["Datenlieferung geht an das Data-Warehouse-Team"], "neu sind die letzten 14 Tage, ohne Risiken:")

    f = {"health": "red", "health_reasons": ["1 überfällige Aufgabe"], "open": 4, "overdue": 1, "questions": 0, "risks": 6,
         "last_movement": "2026-09-28", "next_meeting": None, "altbestand": 0, "verantwortlich": "",
         "neu": stand.neu_seit(events, heute), "risiko_gruppen": g,
         "braucht_dich": {"anzahl": 2, "ueberfaellig": 1, "punkte": ["Vorhaben konsolidieren (bis 05.10.)", "Kontakte prüfen"]},
         "rollen": ["[[a|A]] (Leitung)"], "beteiligte": ["[[b|B]]", "[[c|C]]"]}
    block = stand.render_block(f, "Prosa bleibt.", heute)
    ok("> **Neu (14 Tage):** Datenlieferung" in block and "> **Braucht dich:** 2 Punkt(e), 1 überfällig – Vorhaben" in block,
       f"die Delta-Zeilen fehlen:\n{block}")
    ok("**Risiken (30 Tage):** 6 in 3 Gruppen – Lager Nord (3)" in block, "Risiken stehen in Gruppen")
    ok("> > [!info]- Beteiligte (3)\n> > **Rollen:**" in block, "wer beteiligt ist, steht eingeklappt")
    eq(stand.existing_prose(stand.apply_block("# T\n\nText\n", block)), "Prosa bleibt.", "die Prosa laesst sich wieder lesen:")


def t_briefing_ohne_schablone():
    import briefing
    basis = {"label": "Credit Check", "owners": ["@Anna"], "kind": "risk", "times_seen": 1, "overdue": False,
             "age_days": 3, "first_seen": "2026-09-11", "deadline": "", "context": "Feld entfällt"}
    eq(briefing.default_question(basis), "", "ein Risiko ohne Besonderheit bekommt keine Schablonenfrage:")
    eq(briefing.default_question({**basis, "kind": "action"}), "", "auch kein 'Wie steht es um ...?':")
    ok(briefing.default_question({**basis, "overdue": True}).startswith("Über die Frist"))
    ok("Zum 3. Mal" in briefing.default_question({**basis, "times_seen": 3}))
    eq(briefing.default_question({**basis, "kind": "question", "context": "Steht der Termin"}), "Steht der Termin?")
    prio, why = briefing.classify({**basis, "age_days": 30, "stale": False}, {"health": "red"})
    ok("Projekt auf rot" not in why and "als Risiko erfasst" not in why and "30 Tagen" in why,
       f"die Begruendung nennt nur, was dieses Thema auszeichnet: {why}")
    eq(briefing.classify({**basis, "stale": False}, {"health": "red"})[1], "als Risiko erfasst",
       "ohne anderen Grund bleibt der eine:")
    ok(briefing.MAX_TOPICS <= 6 and briefing.hoechstens() == briefing.MAX_TOPICS, "ein Briefing hat hoechstens sechs Themen")


def t_lagebild_rechnet_die_bilder():
    import lagebild
    import organisation
    import aufgaben
    from datetime import date as _date
    heute = _date(2026, 9, 30)
    T = lambda owner, created, due=None, pruefen=False: aufgaben.Task(status=" ", text="x", owner=owner, created=created,   # noqa: E731
                                                                      due=due, pruefen=pruefen)
    z = lagebild.zusagen([T("a", "2026-09-25"), T("a", "2026-09-20"), T("a", "2026-09-10"), T("b", "2026-07-01"),
                          T("b", "2026-07-11", due="2026-09-01"), T("ich", "2026-09-01"), T("c", "2026-06-01", pruefen=True)],
                         "ich", heute)
    eq([(r["person"], r["offen"], r["typisch"], r["ueberfaellig"]) for r in z], [("a", 3, 10, 0), ("b", 2, 86, 1)],
       "je Person, ohne mich und ohne ungeprueften Altbestand:")
    org = organisation.Organisation({s: {"name": s.upper(), "rolle": "", "team": "", "aktiv": True, "vorgesetzt": "", "quelle": ""}
                                     for s in ("a", "b", "ich")})
    tab = lagebild.zusagen_tabelle(z, org, "ich")
    ok("**86 Tage**" in tab[3] and "**" not in tab[2].split("|")[4], f"fett ist nur, was typisch alt ist:\n{tab}")

    themen = [{"slug": "a-b", "titel": "Ä-B (Bereich)", "ampel": "red", "offen": 20, "still": 30, "atlas": []},
              {"slug": "klein", "titel": "Klein", "ampel": "green", "offen": 2, "still": 1, "atlas": []},
              {"slug": "ohne", "titel": "Ohne Datum", "ampel": "", "offen": 9, "still": None, "atlas": []}]
    r = lagebild.radar(themen)
    ok(r[1] == "quadrantChart" and any(l.strip().startswith("Ae B Bereich 20: [0.67, 0.98] color: #E24B4A") for l in r),
       f"Punkt mit sauberem Namen, Lage und Ampelfarbe:\n{r}")
    ok(not any("Klein" in l or "Ohne Datum" in l for l in r), "zu wenig offen oder ohne Datum steht nicht im Radar")

    kanon = {"kontexte": [{"id": "ctx-eingang", "name": "Eingang", "subdomain": "sd-edi"},
                          {"id": "ctx-verteiler", "name": "Verteiler", "subdomain": "sd-order"},
                          {"id": "ctx-ziel", "name": "Ziel", "subdomain": "sd-fremd"}],
             "externe": [{"id": "ext-partner", "name": "Partnersystem (TMS)"}]}
    th = {"edi": {"titel": "EDI", "ampel": "yellow", "offen": 1, "atlas": []},
          "auftrag": {"titel": "Auftrag", "ampel": "red", "offen": 23, "atlas": ["sd-order"]},
          "partnersystem-anbindung": {"titel": "Anbindung", "ampel": "green", "offen": 4, "atlas": []}}
    eq([lagebild._thema_zu(k, kanon, th) for k in ("ctx-eingang", "ctx-verteiler", "ctx-ziel", "ext-partner")],
       ["edi", "auftrag", "", "partnersystem-anbindung"], "Thema ueber Subdomaene, atlas_id oder den Namen des Externen:")
    b = lagebild.ablauf_bild({"schritte": [{"kontext": "ext-partner"}, {"kontext": "ctx-eingang"}, {"kontext": "ctx-verteiler"},
                                           {"kontext": "ctx-ziel"}]}, kanon, th)
    bild = "\n".join(b)
    ok('k0(["Partnersystem  TMS<br/>4 offen"])' in bild and "k0 --> k1" in bild and "k1 --> k2" in bild and "k2 --> k3" in bild
       and "style k2 stroke:#E24B4A" in bild, f"Externe rund, Kanten in Reihenfolge, Ampel am Rahmen:\n{bild}")


def t_altbestand_parkt_nur_alt_und_ohne_frist():
    import altbestand
    import aufgaben
    from datetime import date as _date
    d = _VAULT / "entities" / "projects"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "park-thema.md"
    f.write_text("---\ntype: project\ntitle: Park-Thema\n---\n# Park-Thema\n\n## Offene Punkte\n"
                 "- [ ] Bleibt, kein Altbestand ➕ 2026-06-01\n\n"
                 f"{aufgaben.ALTBESTAND_HEADING}\n\n"
                 "- [ ] Alt und ohne Frist ➕ 2026-07-01\n"
                 "    - Beleg: „bleibt darunter stehen“\n"
                 "- [ ] Alt, aber mit Frist 📅 2026-12-01 ➕ 2026-07-01\n"
                 "- [ ] Frisch ➕ 2026-11-01\n\n## Event Log\n", encoding="utf-8", newline="\n")
    heute = _date(2026, 11, 18)
    v = altbestand.parken(today=heute)
    eq((v["je_thema"].get("park-thema"), v["angewendet"]), (1, False), "Vorschau zaehlt nur alt und ohne Frist:")
    ok("- [ ] Alt und ohne Frist" in f.read_text(encoding="utf-8"), "die Vorschau schreibt nichts")
    altbestand.parken(anwenden=True, today=heute)
    text = f.read_text(encoding="utf-8")
    ok("- [-] Alt und ohne Frist ➕ 2026-07-01\n    - Geparkt am 18.11.2026 (Altbestand, ungeprüft, 140 Tage alt)" in text
       and "    - Beleg: „bleibt darunter stehen“" in text, f"geparkt mit Vermerk, der Beleg bleibt:\n{text}")
    ok("- [ ] Alt, aber mit Frist" in text and "- [ ] Frisch" in text and "- [ ] Bleibt, kein Altbestand" in text,
       "mit Frist, frisch oder kein Altbestand bleibt offen")
    eq(altbestand.parken(today=heute)["je_thema"].get("park-thema"), None, "ein zweiter Lauf findet nichts mehr:")


# ───────────────────────────────────────── 14. Rolle je Thema, offene Punkte pruefen

def t_rollen_vererben_und_blenden_aus():
    import aufgaben
    import rollen
    import vault_paths
    d = _VAULT / "entities" / "projects"
    d.mkdir(parents=True, exist_ok=True)
    seite = lambda slug, kopf: (d / f"{slug}.md").write_text(   # noqa: E731
        f"---\ntype: project\ntitle: {slug}\n{kopf}---\n# {slug}\n\n## Offene Punkte\n\n## Event Log\n", encoding="utf-8", newline="\n")
    seite("rolle-dach", "meine_rolle: beobachte\n")
    seite("rolle-kind", "parent: \"[[rolle-dach]]\"\n")
    seite("rolle-enkel", "parent: \"[[rolle-kind]]\"\nmeine_rolle: beteiligt\n")
    seite("rolle-frei", "")
    seite("rolle-meins", "verantwortlich: \"[[ich]]\"\n")
    r = rollen.lade()
    eq((r["rolle-dach"], r["rolle-kind"], r["rolle-enkel"], r["rolle-frei"]),
       ("beobachte", "beobachte", "beteiligt", "fuehre"), "eigene Angabe, sonst das Dach, sonst fuehre:")
    T = lambda owner, thema, status=" ": aufgaben.Task(status=status, text="x", owner=owner, topics=[thema] if thema else [])   # noqa: E731
    eq([rollen.sichtbar(T(*a), "ich", r) for a in (("ich", "rolle-kind"), ("rita", "rolle-kind"), ("rita", "rolle-frei"),
                                                    ("rita", "ohne-seite"), ("rita", ""))],
       [True, False, True, True, True], "meine immer; die anderer nur, wo ich fuehre:")
    ok(rollen.sichtbar(T("rita", "rolle-kind"), "ich", r, {"rita"}), "wer an mich berichtet, bleibt sichtbar")
    punkte = ([T("ich", "rolle-frei")] * 3 + [T("rita", "rolle-frei")] * 3 + [T("rita", "rolle-kind", "x")] * 4
              + [T("ich", "rolle-enkel")] + [T("rita", "rolle-enkel")] * 9)
    with _AttrGuard(aufgaben, scan=lambda: punkte), _AttrGuard(vault_paths, ich=lambda: "ich"):
        v = {x["slug"]: x for x in rollen.vorschlaege()}
        eq((v["rolle-frei"]["vorschlag"], v["rolle-frei"]["grund"]), ("fuehre", "3 von 6 Punkten sind deine"), "hoher Anteil:")
        eq((v["rolle-kind"]["vorschlag"], v["rolle-enkel"]["vorschlag"], v["rolle-meins"]["vorschlag"]),
           ("beobachte", "beteiligt", "fuehre"), "nie ein eigener Punkt / wenige / verantwortlich:")
        eq(rollen.setzen({"rolle-frei": "beteiligt", "rolle-dach": "", "gibt-es-nicht": "fuehre", "rolle-kind": "chef"}),
           {"ok": False, "geaendert": ["rolle-frei", "rolle-dach"], "unbekannt": ["gibt-es-nicht", "rolle-kind"]}, "setzen:")
    r = rollen.lade()
    eq((r["rolle-frei"], r["rolle-dach"], r["rolle-kind"]), ("beteiligt", "fuehre", "fuehre"), "geschrieben und herausgenommen:")
    ok("title: rolle-frei" in (d / "rolle-frei.md").read_text(encoding="utf-8"), "das uebrige Frontmatter bleibt")


def t_pruefung_parkt_verstummtes():
    """Ein Punkt eines anderen, der in den naechsten zwei nachbereiteten Terminen der Reihe nicht mehr
    vorkommt, wird geparkt - nicht der eigene, nicht mit Frist, nicht der spaeter wieder genannte."""
    import aufgaben
    import pruefung
    import vault_paths
    from datetime import date as _date
    m = _VAULT / "active-meetings"
    m.mkdir(parents=True, exist_ok=True)
    P = lambda text, owner, due=None: aufgaben.render(aufgaben.Task(status=" ", text=text, owner=owner, due=due))   # noqa: E731

    def notiz(tag, status, punkte, mitschrift):
        (m / f"{tag} - Hallenrunde Pruef.md").write_text(
            f"---\ntype: meeting\ntitle: Hallenrunde Pruef\ndate: {tag}\nstatus: {status}\nseries: hallenrunde-pruef\n---\n"
            f"# Hallenrunde Pruef\n\n## Mitschrift\n{mitschrift}\n\n## Actions\n" + "\n".join(punkte) + "\n", encoding="utf-8", newline="\n")

    notiz("2026-09-01", "nachbereitet",
          [P("Regalplan fuer die Nordhalle zeichnen", "rita-pruef"), P("Wartung der Gabelstapler beauftragen", "rita-pruef"),
           P("Schichtplan mit dem Betriebsrat abstimmen", "ich"), P("Brandschutz begehen lassen", "rita-pruef", due="2026-12-01")],
          "Rita zeichnet den Regalplan.")
    notiz("2026-09-08", "nachbereitet", [P("Etiketten nachbestellen", "rita-pruef")], "Es ging um die Inventur und sonst nichts.")
    notiz("2026-09-15", "done", [], "Die Wartung der Gabelstapler ist beauftragt, der Dienstleister kommt naechste Woche.")
    notiz("2026-09-22", "vorbereitet", [], "")
    heute = _date(2026, 9, 20)
    with _AttrGuard(vault_paths, ich=lambda: "ich"):
        v = pruefung.verstummte(heute)
        eq([a["text"] for a in v], ["Regalplan fuer die Nordhalle zeichnen"], "nur der verstummte Punkt eines anderen:")
        ok("in den folgenden 2 Terminen der Reihe nicht mehr genannt ([[2026-09-08 - Hallenrunde Pruef]], "
           "[[2026-09-15 - Hallenrunde Pruef]])" in v[0]["vermerk"], f"der Vermerk nennt die Termine: {v[0]['vermerk']}")
        r = pruefung.run(heute=heute)
    text = (m / "2026-09-01 - Hallenrunde Pruef.md").read_text(encoding="utf-8")
    ok("- [-] Regalplan fuer die Nordhalle zeichnen" in text and "\n    - Geparkt am 20.09.2026" in text, f"geparkt mit Vermerk:\n{text}")
    ok(text.count("- [ ] ") == 3 and r["verstummt"] == 1 and not r["mit_modell"], f"die anderen drei bleiben offen: {r}")
    bericht = (_VAULT / pruefung.BERICHT).read_text(encoding="utf-8")
    ok("## 20.09.2026 – " in bericht and "**geparkt (verstummt):** Regalplan" in bericht, f"im Bericht:\n{bericht}")
    with _AttrGuard(vault_paths, ich=lambda: "ich"):
        eq(pruefung.verstummte(heute), [], "ein zweiter Lauf findet nichts mehr:")


def t_einstieg_karte_und_verzeichnis():
    """Karte und Themen-Verzeichnis fuer Agenten: Unterthemen unter ihrem Dach, Altbestand zaehlt nicht,
    ein zweiter Lauf (auch an einem anderen Tag) schreibt nichts, eigene Hinweise in der Karte bleiben."""
    import aufgaben
    import einstieg
    import vault_paths
    from datetime import date as _date
    d = _VAULT / "entities" / "projects"
    d.mkdir(parents=True, exist_ok=True)
    seite = lambda slug, kopf: (d / f"{slug}.md").write_text(   # noqa: E731
        f"---\ntype: project\ntitle: {slug}\n{kopf}---\n# {slug}\n\n## Offene Punkte\n\n## Event Log\n", encoding="utf-8", newline="\n")
    seite("karte-dach", "health: red\nampel_grund: zwei Risiken\nmeine_rolle: beteiligt\nfokus: 2\n")
    seite("karte-kind", "parent: \"[[karte-dach]]\"\nzuletzt_bewegt: '2026-09-28'\nstatus: proposed\n")
    T = lambda owner, thema, **kw: aufgaben.Task(status=" ", text="x", owner=owner, topics=[thema], **kw)   # noqa: E731
    punkte = [T("ich", "karte-kind"), T("rita", "karte-kind", due="2026-09-01"), T("rita", "karte-kind", pruefen=True),
              T("ich", "karte-kind", kind=aufgaben.KIND_QUESTION), aufgaben.Task(status=" ", text="frei")]
    with _AttrGuard(aufgaben, scan=lambda: punkte), _AttrGuard(vault_paths, ich=lambda: "ich"):
        zeilen = {r["slug"]: r for r in einstieg.themen_zeilen(_date(2026, 9, 30))}
        k = zeilen["karte-kind"]
        eq((k["tiefe"], k["offen"], k["meine"], k["ueberfaellig"], k["fragen"], k["altbestand"], k["rolle"]),
           (1, 2, 1, 1, 1, 1, "beteiligt"), "Unterthema: Stufe, Zahlen ohne Altbestand, Rolle vom Dach:")
        text = einstieg.verzeichnis_text(_date(2026, 9, 30))
        reihe = [z for z in text.splitlines() if "karte-" in z]
        ok(reihe[0].startswith("| [[karte-dach\\|karte-dach]] ★2 |") and "rot – zwei Risiken" in reihe[0], f"Dach mit Fokus und Ampel:\n{reihe[0]}")
        ok(reihe[1].startswith("| · [[karte-kind\\|karte-kind]] (proposed) |") and "| 2 | 1 | 1 | 1 | 28.09.2026 |" in reihe[1],
           f"Unterthema eingerueckt:\n{reihe[1]}")
        ok("_1 offene Punkte gehören zu keinem Thema" in text, "Punkte ohne Thema werden genannt")
        ok(einstieg.run(heute=_date(2026, 9, 30))["geaendert"], "erster Lauf schreibt")
        f = _VAULT / einstieg.KARTE
        f.write_text(f.read_text(encoding="utf-8") + "\nMein Hinweis an den Agenten.\n", encoding="utf-8", newline="\n")
        r = einstieg.run(heute=_date(2026, 10, 7))
        eq((r["karte_geaendert"], r["verzeichnis_geaendert"]), (False, False), "ein anderer Tag allein schreibt nichts:")
        punkte.append(T("ich", "karte-dach"))
        (_VAULT / "reports" / "lagebild.md").write_text("# Lagebild\n", encoding="utf-8")
        r = einstieg.run(heute=_date(2026, 10, 7))
        eq((r["karte_geaendert"], r["verzeichnis_geaendert"]), (True, True), "neuer Punkt, neuer Bericht -> beide neu:")
    karte = f.read_text(encoding="utf-8")
    ok("Mein Hinweis an den Agenten." in karte and karte.count(einstieg.START) == 1, "eigene Hinweise bleiben, ein Block")
    ok("`reports/lagebild.md`" in karte and "`reports/orgchart.md`" not in karte, "die Karte nennt nur, was es gibt")
    ok("_Stand 07.10.2026" in (_VAULT / einstieg.VERZEICHNIS).read_text(encoding="utf-8"), "Datum des Schreibens")


def _hand_vault():
    """Zwei Personen, ein Dach mit Unterthema, Punkte auf der Seite und in einer Termin-Notiz."""
    import vault_paths
    d = _VAULT / "entities" / "projects"
    p = _VAULT / "entities" / "people"
    m = _VAULT / "active-meetings"
    for x in (d, p, m):
        x.mkdir(parents=True, exist_ok=True)
    for slug, name in (("hand-ich", "Ich Hand"), ("rita-hand", "Rita Hand")):
        (p / f"{slug}.md").write_text(f"---\ntype: person\nname: {name}\n---\n# {name}\n", encoding="utf-8", newline="\n")
    (d / "hand-dach.md").write_text("---\ntype: project\ntitle: Hand Dach\nstatus: active\n---\n# Hand Dach\n\n## Offene Punkte\n\n## Event Log\n",
                                    encoding="utf-8", newline="\n")
    (d / "hand-kind.md").write_text(
        "---\ntype: project\ntitle: Hand Kind\nstatus: active\nparent: \"[[hand-dach]]\"\nfokus: 1\n---\n# Hand Kind\n\n## Offene Punkte\n"
        "- [ ] Lastenheft schreiben — [[hand-ich|Ich Hand]] · [[hand-kind|Hand Kind]] ➕ 2026-09-01\n"
        "    - Beleg aus dem Termin\n"
        "- [ ] Lieferanten anfragen — [[rita-hand|Rita Hand]] · [[hand-kind|Hand Kind]] 📅 2026-10-01 ➕ 2026-09-02\n"
        "- [ ] ❓ Wer zahlt die Lizenz? — an [[rita-hand|Rita Hand]] · [[hand-kind|Hand Kind]] ➕ 2026-09-03\n\n"
        "## Event Log\n- [2026-09-01] [STATUS] Auftakt (→ [[x]])\n", encoding="utf-8", newline="\n")
    (m / "2026-09-05 - Handrunde.md").write_text(
        "---\ntype: meeting\ntitle: Handrunde\ndate: 2026-09-05\nstatus: nachbereitet\n---\n# Handrunde\n\n## Actions\n"
        "- [ ] Testdaten besorgen — [[rita-hand|Rita Hand]] · [[hand-kind|Hand Kind]] ➕ 2026-09-05\n"
        "- [ ] Abnahme planen — [[hand-ich|Ich Hand]] · [[hand-kind|Hand Kind]] ➕ 2026-09-05\n", encoding="utf-8", newline="\n")
    vault_paths.invalidate_entity_caches()
    return d, m


def t_aendern_mit_hinweis_und_log():
    """Aendern von Hand: der Hinweis steht als Unterpunkt, die Zeile bleibt bei Status-Wechsel wie notiert,
    Person und Frist schreiben sie neu, eine verschobene Zeile wird nicht angefasst, das Log bekommt eine Zeile."""
    import aendern
    from datetime import date as _date
    d, m = _hand_vault()
    heute = _date(2026, 11, 20)
    rel = "entities/projects/hand-kind.md"
    getan = aendern.punkte_aendern([
        {"path": rel, "line": 10, "text": "Lastenheft schreiben", "aktion": "erledigt", "hinweis": "liegt  im Wiki"},
        {"path": rel, "line": 12, "text": "Lieferanten anfragen", "aktion": "uebergeben", "an": "hand-ich"},
        {"path": rel, "line": 13, "text": "ein ganz anderer Punkt", "aktion": "verworfen"},
        {"path": "entities/people/rita-hand.md", "line": 0, "text": "x", "aktion": "erledigt"},
    ], heute=heute, woher="Test")
    eq([a["aktion"] for a in getan], ["uebergeben", "erledigt"], "nur was an der Zeile noch stimmt, in erlaubten Dateien:")
    text = (d / "hand-kind.md").read_text(encoding="utf-8")
    ok("- [x] Lastenheft schreiben — [[hand-ich|Ich Hand]] · [[hand-kind|Hand Kind]] ➕ 2026-09-01 ✅ 2026-11-20\n"
       "    - Erledigt am 20.11.2026 (Test): liegt im Wiki\n    - Beleg aus dem Termin" in text, f"erledigt mit Hinweis:\n{text}")
    ok("- [ ] Lieferanten anfragen — [[hand-ich|Ich Hand]] · [[hand-kind|Hand Kind]] 📅 2026-10-01 ➕ 2026-09-02\n"
       "    - Übergeben an Ich Hand, vorher Rita Hand am 20.11.2026 (Test)" in text, f"uebergeben:\n{text}")
    ok("- [ ] ❓ Wer zahlt die Lizenz?" in text, "die Frage blieb unberuehrt")
    ok(aendern.log_eintrag("hand-kind", "DECISION", "Wir nehmen  den zweiten Anbieter", heute=heute, quelle="Test"), "Log-Zeile")
    ok(not aendern.log_eintrag("hand-kind", "DECISION", "Wir nehmen den zweiten Anbieter", heute=heute, quelle="Test"), "keine Dublette")
    ok(not aendern.log_eintrag("hand-kind", "ACTION", "x", heute=heute) and not aendern.log_eintrag("gibts-nicht", "STATUS", "x"), "Art und Thema geprueft")
    text = (d / "hand-kind.md").read_text(encoding="utf-8")
    ok("## Event Log\n- [2026-11-20] [DECISION] Wir nehmen den zweiten Anbieter (Test)\n- [2026-09-01] [STATUS] Auftakt" in text, f"oben im Log:\n{text}")
    ok(aendern.punkt_neu("hand-dach", "Vertrag pruefen", person="rita-hand", frist="2026-12-01", heute=heute), "neuer Punkt")
    ok("- [ ] Vertrag pruefen — [[rita-hand|Rita Hand]] · [[hand-dach|Hand Dach]] 📅 2026-12-01 ➕ 2026-11-20"
       in (d / "hand-dach.md").read_text(encoding="utf-8"), "kanonisch auf der Themen-Seite")


def t_thema_schliessen_mit_punkten():
    """Thema abschliessen: je Punkt die Wahl (sonst der Standard), umhaengen zieht mit Unterpunkten ans Dach,
    auch Punkte in Termin-Notizen; Status, Grund und Log stehen am Thema; es faellt aus Verzeichnis und Rollen."""
    import aufgaben
    import einstieg
    import rollen
    import thema_schliessen
    import vault_paths
    from datetime import date as _date
    d, m = _hand_vault()
    heute = _date(2026, 11, 20)
    with _AttrGuard(vault_paths, ich=lambda: "hand-ich"):
        v = thema_schliessen.vorschau("hand-kind")
        eq((len(v["punkte"]), v["dach"], [p["vorschlag"] for p in v["punkte"] if p["frage"]]), (5, "hand-dach", ["verworfen"]),
           "Vorschau: alle offenen Punkte des Themas, das Dach, Fragen fallen weg:")
        ok(not thema_schliessen.schliessen("hand-kind", " ")["ok"], "ohne Grund kein Abschluss")
        ident = {p["text"]: p["id"] for p in v["punkte"]}
        r = thema_schliessen.schliessen("hand-kind", "Projekt ist live", {ident["Lastenheft schreiben"]: "dach",
                                                                          ident["Testdaten besorgen"]: "dach",
                                                                          ident["Abnahme planen"]: "erledigt"}, heute=heute)
        eq((r["ok"], r["punkte"], r["nicht_geaendert"]), (True, {"erledigt": 1, "verworfen": 2, "umhaengen": 2}, 0), "Ergebnis:")
        kind = (d / "hand-kind.md").read_text(encoding="utf-8")
        dach = (d / "hand-dach.md").read_text(encoding="utf-8")
        ok("Lastenheft schreiben" not in kind and "- [ ] Lastenheft schreiben — [[hand-ich|Ich Hand]] · [[hand-dach|Hand Dach]] ➕ 2026-09-01\n"
           "    - Beleg aus dem Termin\n    - Umgehängt von Hand Kind nach Hand Dach am 20.11.2026 (Thema „Hand Kind“ abgeschlossen): Projekt ist live"
           in dach, f"mit Unterpunkten ans Dach gezogen:\n{dach}")
        ok("- [-] Lieferanten anfragen" in kind and "- [-] ❓ Wer zahlt die Lizenz?" in kind, f"der Rest verworfen:\n{kind}")
        ok("status: done" in kind and "abgeschlossen: '2026-11-20'" in kind and "abschluss_grund: Projekt ist live" in kind
           and "fokus:" not in kind, f"Frontmatter:\n{kind[:300]}")
        ok("- [2026-11-20] [MILESTONE] Thema abgeschlossen: Projekt ist live" in kind, "Log-Eintrag")
        notiz = (m / "2026-09-05 - Handrunde.md").read_text(encoding="utf-8")
        ok("- [ ] Testdaten besorgen — [[rita-hand|Rita Hand]] · [[hand-dach|Hand Dach]] ➕ 2026-09-05" in notiz
           and "- [x] Abnahme planen" in notiz and "✅ 2026-11-20" in notiz, f"Termin-Notiz:\n{notiz}")
        eq(len([t for t in aufgaben.scan() if t.is_open and "hand-kind" in t.topics]), 0, "kein offener Punkt mehr am Thema:")
        ok(not thema_schliessen.schliessen("hand-kind", "noch einmal")["ok"], "zweimal geht nicht")
        ok("hand-kind" not in {z["slug"] for z in einstieg.themen_zeilen(heute)} and "hand-kind" not in {x["slug"] for x in rollen.vorschlaege()}
           and "_Abgeschlossen (Seite bleibt, `status: done`): " in einstieg.verzeichnis_text(heute), "aus Verzeichnis und Rollen heraus")
        bericht = (_VAULT / "reports" / "geprueft.md").read_text(encoding="utf-8")
        ok("## 20.11.2026 – Thema abgeschlossen: Hand Kind" in bericht and "- Grund: Projekt ist live" in bericht, f"Bericht:\n{bericht[:600]}")
        ok(thema_schliessen.oeffnen("hand-kind", heute=heute)["ok"], "wieder oeffnen")
        kind = (d / "hand-kind.md").read_text(encoding="utf-8")
        ok("status: active" in kind and "abschluss_grund" not in kind and "[STATUS] Thema wieder geöffnet" in kind, "wieder aktiv")
        # mit Unterthemen: nur wenn genannt
        ok(thema_schliessen.schliessen("hand-dach", "Programm beendet", unterthemen=["hand-kind"], heute=heute)["unterthemen"] == ["hand-kind"],
           "das genannte Unterthema geht mit")
        ok("status: done" in (d / "hand-kind.md").read_text(encoding="utf-8"), "Unterthema abgeschlossen")


def t_durchsprechen_nur_mit_beleg():
    """Durchsprechen: das Modell ordnet zu, der Code prueft - Nummer aus der Liste, Beleg woertlich im eigenen
    Text, Person bekannt, Frist aus dem Beleg gerechnet; geschrieben wird erst beim Anwenden."""
    import durchsprechen
    import vault_paths
    from datetime import date as _date
    d, m = _hand_vault()
    heute = _date(2026, 11, 20)                    # ein Freitag
    text = ("Das Lastenheft ist fertig und abgenommen. Die Lieferanten fragt jetzt Ich Hand an, bis zum 3.12. "
            "Die Lizenzfrage vergessen wir. Entschieden wurde: wir starten im Januar.")
    antwort = {"aenderungen": [
        {"punkt": 1, "aktion": "erledigt", "beleg": "Das Lastenheft ist fertig und abgenommen"},
        {"punkt": 2, "aktion": "uebergeben", "an": "Ich Hand", "beleg": "Die Lieferanten fragt jetzt Ich Hand an, bis zum 3.12."},
        {"punkt": 2, "aktion": "frist", "beleg": "Die Lieferanten fragt jetzt Ich Hand an, bis zum 3.12."},
        {"punkt": 3, "aktion": "verworfen", "beleg": "Die Lizenzfrage vergessen wir"},
        {"punkt": 4, "aktion": "erledigt", "beleg": "Die Testdaten sind da"},              # steht nicht im Text
        {"punkt": 99, "aktion": "erledigt", "beleg": "Das Lastenheft ist fertig"},         # Nummer gibt es nicht
        {"punkt": 5, "aktion": "uebergeben", "an": "Otto Niemand", "beleg": "Die Lizenzfrage vergessen wir"},   # Name nicht im Text
    ], "log": [{"thema": "hand-kind", "art": "DECISION", "text": "Start im Januar.", "beleg": "wir starten im Januar"},
               {"thema": "gibts-nicht", "art": "ACTION", "text": "x", "beleg": "wir starten im Januar"}],
        "neu": [{"text": "Lastenheft schreiben", "beleg": "Das Lastenheft ist fertig"}]}                       # steht schon in der Liste
    gesehen = []

    def modell(messages, schema, **kw):
        gesehen.append(messages[1]["content"])
        return antwort, []

    with _AttrGuard(vault_paths, ich=lambda: "hand-ich"):
        p = durchsprechen.punkte({"thema": "hand-kind"})
        eq([x["text"] for x in p["punkte"]], ["Lastenheft schreiben", "Lieferanten anfragen", "Wer zahlt die Lizenz?",
                                              "Abnahme planen", "Testdaten besorgen"][:3] + sorted(["Abnahme planen", "Testdaten besorgen"],
                                                                                                    key=lambda s: s != "Testdaten besorgen"),
           "die Punkte des Themas, aelteste zuerst:")
        eq(len(durchsprechen.punkte({"meine": True})["punkte"]), 2, "meine:")
        v = durchsprechen.vorschlag({"thema": "hand-kind"}, text, modell, heute=heute)
        ok("Heute ist Freitag, der 20.11.2026" in gesehen[0] and "1. Lastenheft schreiben — Ich Hand" in gesehen[0], "das Modell bekommt Datum und Liste")
        eq([(a["nr"], a["aktion"], a.get("an", ""), a.get("datum", "")) for a in v["aenderungen"]],
           [(1, "erledigt", "", ""), (2, "uebergeben", "hand-ich", ""), (2, "frist", "", "2026-12-03"), (3, "verworfen", "", "")],
           "nur was Nummer, Beleg und Person besteht; die Frist rechnet der Code:")
        eq(([e["text"] for e in v["log"]], v["neu"], v["verworfen"]), (["Start im Januar."], [], 5), "Log nur fuer bekannte Themen, keine Dublette:")
        vorher = (d / "hand-kind.md").read_text(encoding="utf-8")
        r = durchsprechen.anwenden({"titel": v["titel"], "aenderungen": v["aenderungen"], "log": v["log"], "neu": []}, heute=heute)
        eq((r["geaendert"], r["nicht_geaendert"], r["log"]), (4, 0, 1), "angewendet:")
    kind = (d / "hand-kind.md").read_text(encoding="utf-8")
    ok(vorher != kind and "- [x] Lastenheft schreiben" in kind
       and "    - Erledigt am 20.11.2026 (durchgesprochen): Das Lastenheft ist fertig und abgenommen" in kind, f"erledigt mit dem eigenen Satz:\n{kind}")
    ok("- [ ] Lieferanten anfragen — [[hand-ich|Ich Hand]] · [[hand-kind|Hand Kind]] 📅 2026-12-03 ➕ 2026-09-02" in kind
       and "Frist geändert auf 03.12.2026, vorher 2026-10-01 am 20.11.2026 (durchgesprochen)" in kind
       and "Übergeben an Ich Hand, vorher Rita Hand" in kind, f"uebergeben und neue Frist am selben Punkt:\n{kind}")
    ok("- [-] ❓ Wer zahlt die Lizenz?" in kind and "- [2026-11-20] [DECISION] Start im Januar. (durchgesprochen)" in kind, "verworfen, Log-Eintrag")
    ok("## 20.11.2026 – Durchgesprochen: Hand Kind" in (_VAULT / "reports" / "geprueft.md").read_text(encoding="utf-8"), "im Bericht")


def t_pruefung_schliesst_nur_mit_beleg():
    """Das Modell nennt, was laut Log erledigt oder ueberholt ist - geschlossen wird nur, wenn der Eintrag
    nicht aelter ist als der Punkt und der Beleg woertlich darin steht."""
    import aufgaben
    import pruefung
    import vault_paths
    from datetime import date as _date
    d = _VAULT / "entities" / "projects"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "pruef-thema.md"
    f.write_text("---\ntype: project\ntitle: Pruef-Thema\n---\n# Pruef-Thema\n\n## Offene Punkte\n"
                 "- [ ] Angebot fuer die Rampe einholen ➕ 2026-09-01\n"
                 "    - Beleg: „bleibt darunter stehen“\n"
                 "- [ ] Pilot in der Suedhalle starten ➕ 2026-09-02\n"
                 "- [ ] Schulung planen ➕ 2026-09-03\n"
                 "- [ ] Erfundenes pruefen ➕ 2026-09-04\n"
                 "- [ ] Zu frueh belegt ➕ 2026-09-20\n\n## Event Log\n"
                 "- [2026-09-10] [STATUS] Das Angebot fuer die Rampe liegt vor, zwei Anbieter haben geantwortet.\n"
                 "- [2026-09-12] [DECISION] Der Pilot in der Suedhalle entfaellt, die Halle wird umgebaut.\n"
                 "- [2026-09-14] [STATUS] Ueber die Schulung wurde gesprochen.\n", encoding="utf-8", newline="\n")
    gefragt = []

    def modell_antwort(messages, schema, **kw):
        gefragt.append(messages[1]["content"])
        zeilen = messages[1]["content"].split("Log-Einträge:")
        nr = lambda teil, wort: next((int(l.split(".")[0]) for l in teil.splitlines() if wort in l), 98)   # noqa: E731
        p, e = zeilen
        return {"urteile": [
            {"punkt": nr(p, "Angebot"), "urteil": "erledigt", "eintrag": nr(e, "Angebot"), "beleg": "Das Angebot fuer die Rampe liegt vor"},
            {"punkt": nr(p, "Pilot"), "urteil": "ueberholt", "eintrag": nr(e, "Pilot"), "beleg": "Der Pilot in der Suedhalle entfaellt"},
            {"punkt": nr(p, "Schulung"), "urteil": "offen", "eintrag": nr(e, "Schulung"), "beleg": "Ueber die Schulung wurde gesprochen"},
            {"punkt": nr(p, "Erfundenes"), "urteil": "erledigt", "eintrag": nr(e, "Schulung"), "beleg": "Das wurde komplett abgeschlossen"},
            {"punkt": nr(p, "Zu frueh"), "urteil": "erledigt", "eintrag": nr(e, "Angebot"), "beleg": "Das Angebot fuer die Rampe liegt vor"},
            {"punkt": 99, "urteil": "erledigt", "eintrag": 0, "beleg": "Das Angebot fuer die Rampe liegt vor"},
        ]}, {}

    heute = _date(2026, 9, 25)
    with _AttrGuard(vault_paths, ich=lambda: "ich"), _AttrGuard(pruefung, THEMEN_JE_LAUF=50):
        r = pruefung.run(llm_call=modell_antwort, heute=heute)
    text = f.read_text(encoding="utf-8")
    ok("- [x] Angebot fuer die Rampe einholen ➕ 2026-09-01 ✅ 2026-09-10\n"
       "    - Erledigt laut Log vom 10.09.2026: „Das Angebot fuer die Rampe liegt vor“" in text
       and "    - Beleg: „bleibt darunter stehen“" in text, f"erledigt mit dem Datum des Eintrags und dem Beleg:\n{text}")
    ok("- [-] Pilot in der Suedhalle starten" in text and "    - Überholt laut Log vom 12.09.2026" in text, f"ueberholt = verworfen:\n{text}")
    ok("- [ ] Schulung planen" in text and "- [ ] Erfundenes pruefen" in text and "- [ ] Zu frueh belegt" in text,
       f"offen, erfundener Beleg, Eintrag aelter als der Punkt: bleibt\n{text}")
    eq((r["erledigt"], r["ueberholt"], r["mit_modell"]), (1, 1, True), "gezaehlt:")
    n = len(gefragt)
    with _AttrGuard(vault_paths, ich=lambda: "ich"), _AttrGuard(pruefung, THEMEN_JE_LAUF=50):
        pruefung.run(llm_call=modell_antwort, heute=heute)
    ok(len(gefragt) == n, f"ein Thema, an dem sich nichts geaendert hat, wird nicht noch einmal gefragt ({n} -> {len(gefragt)})")


# ───────────────────────────────────────── 13. Jourfix nach Richtung

def t_jourfix_nach_richtung():
    """Drei Richtungen, je hoechstens drei Punkte: bei der Person am laengsten offen, ich schulde,
    zum Uebergeben. Ein Vorname allein ordnet nie zu - nur in einem Thema der Person."""
    import vorbereiten
    import triage
    import themen
    import aufgaben
    from datetime import date as _date
    T = lambda text, owner, created, path="active-meetings/x.md", topics=("betrieb",), due=None: aufgaben.Task(   # noqa: E731
        status=" ", text=text, owner=owner, created=created, path=path, topics=list(topics), due=due)
    punkte = [T("Doku zusammenfuehren", "bert", "2026-08-03"), T("Zeitplan setzen", "bert", "2026-08-24"),
              T("Update planen", "bert", "2026-09-07"), T("Viertes von Bert", "bert", "2026-09-14"),
              T("Formular einreichen", "ich", "2026-09-07", path="active-meetings/2026-09-07 - jourfix - Bert.md"),
              T("Mit Bert Direkt das Budget ansehen", "ich", "2026-09-10", topics=("fremd",)),
              T("Bert nach dem Stand fragen", "ich", "2026-09-11", topics=("betrieb",)),
              T("Bert nach dem Wetter fragen", "ich", "2026-09-12", topics=("fremd",)),
              T("Etwas ganz anderes", "ich", "2026-09-01", topics=("fremd",)),
              T("Erledigtes zaehlt nicht", "bert", "2026-07-01")]
    punkte[-1].status = "x"
    geben = {"offen": [{"vorschlag": "uebergeben", "an": "bert", "text": "Dashboard erstellen", "thema": "betrieb"},
                       {"vorschlag": "uebergeben", "an": "wer-anders", "text": "Nicht fuer Bert", "thema": "betrieb"},
                       {"vorschlag": "selbst", "an": "", "text": "Bleibt", "thema": "betrieb"}]}
    reihe = [(Path("active-meetings/2026-09-07 - jourfix - Bert.md"), {})]
    with _AttrGuard(aufgaben, scan=lambda: punkte), _AttrGuard(triage, vorschlaege=lambda **kw: geben), \
            _AttrGuard(themen, _series_notes=lambda key, exclude=None: iter(reihe)):
        z = vorbereiten._richtung("bert", "Bert Direkt", "jourfix-bert", {"betrieb"}, _date(2026, 9, 28), "ich")
    text = "\n".join(z)
    ok("**Bei Bert am längsten offen** (4 insgesamt)\n- Doku zusammenfuehren — seit 56 Tagen · [[betrieb]]" in text
       and "Viertes von Bert" not in text and "Erledigtes" not in text, f"die drei aeltesten, mit Alter:\n{text}")
    ok("**Du schuldest Bert** (3)" in text and "Formular einreichen" in text and "Mit Bert Direkt das Budget" in text
       and "Bert nach dem Stand fragen" in text, f"aus der Reihe, voller Name, oder Vorname im Thema der Person:\n{text}")
    ok("Wetter" not in text and "ganz anderes" not in text, "ein Vorname in einem fremden Thema ordnet nicht zu")
    ok("**Zum Übergeben an Bert** (1)" in text and "- Dashboard erstellen · [[betrieb]]" in text and "Nicht fuer Bert" not in text,
       f"nur Uebergabe-Vorschlaege an diese Person:\n{text}")
    with _AttrGuard(aufgaben, scan=lambda: []), _AttrGuard(triage, vorschlaege=lambda **kw: {"offen": []}), \
            _AttrGuard(themen, _series_notes=lambda key, exclude=None: iter([])):
        eq(vorbereiten._richtung("bert", "Bert Direkt", "jourfix-bert", set(), _date(2026, 9, 28), "ich"), [],
           "ohne Punkte steht nichts da:")


# ───────────────────────────────────────── main

TESTS = [
    ("rollen: vererben, ausblenden, Vorschlag aus den Punkten, eintragen", t_rollen_vererben_und_blenden_aus),
    ("pruefung: verstummt in den naechsten Terminen der Reihe -> geparkt", t_pruefung_parkt_verstummtes),
    ("pruefung: erledigt/ueberholt nur mit woertlichem Beleg aus einem juengeren Eintrag", t_pruefung_schliesst_nur_mit_beleg),
    ("einstieg: Karte (CLAUDE.md) und Themen-Verzeichnis, schreibt nur bei Aenderung", t_einstieg_karte_und_verzeichnis),
    ("aendern: Hinweis als Unterpunkt, Person, Log-Zeile, neuer Punkt", t_aendern_mit_hinweis_und_log),
    ("thema-schliessen: Punkte je Wahl, umhaengen ans Dach, Status, wieder oeffnen", t_thema_schliessen_mit_punkten),
    ("durchsprechen: nur mit Nummer und woertlichem Beleg, Frist vom Code, zwei Aenderungen am Punkt", t_durchsprechen_nur_mit_beleg),
    ("vorbereiten: Jourfix nach Richtung - laengst offen, ich schulde, zum Uebergeben", t_jourfix_nach_richtung),
    ("stand: Delta-Zeilen, Risiken in Gruppen, Beteiligte eingeklappt", t_stand_delta_und_risiko_gruppen),
    ("briefing: keine Schablonenfrage, Begruendung ohne Wiederholung, hoechstens sechs", t_briefing_ohne_schablone),
    ("lagebild: Zusagen je Person, Radar, Ablauf mit Ampel", t_lagebild_rechnet_die_bilder),
    ("altbestand: parken nur alt und ohne Frist, mit Vermerk", t_altbestand_parkt_nur_alt_und_ohne_frist),
    ("triage: Art, Atlas, anderer Handelnder, Linie, Fokus, Parken", t_triage_ordnet_ein),
    ("triage: Matrix - Fachkreis nach Rolle, Teams und Runden", t_triage_matrix_und_gruppen),
    ("triage: Bestaetigen schreibt an der Quelle (Person, Vermerk, [-]) oder merkt sich die Entscheidung",
     t_triage_wendet_an_der_quelle_an),
    ("organisation: Linie aus den Personenseiten, Vorrang, Verhaeltnis, Bild", t_organisation_liest_die_linie),
    ("neuaufbau: nur in der Kopie, nie im Vault; aus Themen geht nur Abgeleitetes", t_neuaufbau_schuetzt_den_vault),
    ("modell.fehler_einordnen: echte Meldungen bekommen Art, Ursache, Ausweg", t_fehler_einordnen_echte_meldungen),
    ("modell.complete: gesperrtes Modell -> naechstes der Liste, nie eines ausserhalb",
     t_complete_nimmt_naechstes_modell_der_liste),
    ("modell.complete: ohne Ersatz traegt der Fehler Art und erlaubte Modelle", t_complete_ohne_ersatz_meldet_die_sperre),
    ("modell.complete: ein Abbruch wird genau einmal wiederholt", t_complete_wiederholt_einen_abbruch_einmal),
    ("modell.diagnose: haelt beim ersten Fehler, nennt Ursache und Ausweg", t_diagnose_haelt_beim_ersten_fehler),
    ("modell.complete: Lease holt das gesperrte Modell, der Schluessel bleibt geheim", t_lease_holt_das_gesperrte_modell),
    ("modell.lease: Ruhe nach Menschen, Laden abwarten, fremder Halter, Aufraeumen", t_lease_haelt_sich_an_den_vertrag),
    ("nachbereiten_modell.extract: Art, Beleg, Zusammenfuehren, Raum ist keine Person",
     t_extract_ordnet_ein_und_fuehrt_zusammen),
    ("nachbereiten: Beleg steht als Unterpunkt, zaehlt nicht als Punkt", t_beleg_steht_als_unterpunkt),
    ("nachbereiten_modell: Umschreibungen - das Modell waehlt Nummern, der Code prueft",
     t_gruppen_zusammenfuehren_prueft_die_wahl_des_modells),
    ("nachbereiten_modell.extract: ausgefallene Pruefstufe steht mit Ursache im Ergebnis",
     t_ausgefallene_pruefung_steht_im_ergebnis),
    ("modell.config(): Env > llm.config.json > Vorgabe", t_config_precedence),
    ("modell.available(): unerreichbar wirft nie", t_available_unreachable_no_throw),
    ("modell.available(): VAULT_LLM_OFFLINE=1 erzwingt False", t_available_offline_env),
    ("modell.complete_json: Fence + <think> werden repariert", t_complete_json_repairs_fence_and_think),
    ("modell.complete_json: nach 1 Wiederholung wird der Fehler weitergereicht",
     t_complete_json_reraises_after_retry),
    ("nachbereiten_modell.extract: unbekannter Abschnitt raus, Datum blank, Dublette weg",
     t_extract_filters_unknown_section_blank_date_dedupes),
    ("nachbereiten_modell.extract: Review deckelt bei drei Massnahmen", t_extract_review_caps_at_three_actions),
    ("nachbereiten_modell.extract: unbrauchbare Antwort -> Stueck halbieren statt Notbehelf",
     t_extract_splits_piece_when_answer_breaks),
    ("nachbereiten: Rendering von Entscheidung/Action exakt", t_wrapup_renders_exact_lines),
    ("nachbereiten: zweiter Lauf ist 'unveraendert' und byte-gleich",
     t_wrapup_idempotent_second_run_is_byte_identical),
    ("nachbereiten: ohne Modell deterministisch, Exit sauber",
     t_wrapup_without_model_is_deterministic_and_exits_clean),
    ("nachbereiten: Notiz ohne Prosa wird uebersprungen", t_wrapup_skips_notes_without_prose),
]


def main() -> int:
    # Testaufrufe gehoeren nicht ins echte Protokoll (.2ndbrain/daten/.llm_log.jsonl) -
    # sonst stehen dort Eintraege mit task "t"/"test" neben echten Laeufen.
    os.environ["VAULT_LLM_LOG"] = str(Path(tempfile.gettempdir()) / "vault-test-llm-log.jsonl")
    print(f"LLM-Harness — {len(TESTS)} Regressionstests\n")
    for name, fn in TESTS:
        check(name, fn)
    print(f"\n{_passed} bestanden, {len(_failed)} fehlgeschlagen")
    if _failed:
        print("  " + ", ".join(_failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
