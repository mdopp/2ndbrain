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
        if len(text) > 4000:
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


# ───────────────────────────────────────── main

TESTS = [
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
