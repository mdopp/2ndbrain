#!/usr/bin/env python3
"""modell.py - Client fuer den lokalen llama-server (Modell und Adresse aus der Konfiguration).

Der Server bedient eine Anfrage gleichzeitig (`--parallel 1`); mehrschrittige Ablaeufe
stehen in Python (`nachbereiten_modell.py`, `nachbereiten.py`, `einarbeiten.py`), das Modell bekommt
je Aufruf genau eine Aufgabe.

Konfiguration, in dieser Rangfolge (hoechste zuerst):
  1. Umgebung: VAULT_LLM_URL, VAULT_LLM_MODEL, VAULT_LLM_TIMEOUT, VAULT_LLM_LOG,
     VAULT_LLM_OFFLINE=1 (erzwingt "nicht verfuegbar" - fuer Tests/Offline-Laeufe)
  2. `.2ndbrain/llm.config.json`
  3. Eingebaute Vorgaben

Nur Standardbibliothek (`urllib` statt `requests`). Ohne Netz importierbar -
es gibt keinen Aufruf auf Modulebene. Jede Antwort wird entschaerft (fremdtext.py);
jeder Aufruf landet mit Laenge, Dauer und Fehler (ohne Text) im Protokoll `.llm_log.jsonl`.

    2ndbrain modell --selftest     # Endpoint, Modell, ein Mini-JSON-Roundtrip
    2ndbrain modell --diagnose     # Schritt fuer Schritt mit Ursache und Ausweg (--json fuers Plugin)
    2ndbrain modell --config       # aufgeloeste Konfiguration

Modellwahl: `modelle` in llm.config.json ist die Reihe der Modelle, das beste zuerst (ohne Liste:
`model`, dann `model_pruefung`). Jeder Lauf beginnt beim besten; lehnt der Server es ab, kommt das
naechste der Liste (`kandidaten`, `zuletzt`).
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fremdtext  # noqa: E402
from modell_ausgabe import LLMOutputError, llama_params, parse_json  # noqa: E402 - Pfad erst gesetzt

# Modulattribute statt fest verdrahteter Pfade in config(): Tests koennen sie
# direkt umbiegen (`modell.CONFIG_PATH = tmp / "llm.config.json"`).
import vault_paths as _vp  # noqa: E402

CONFIG_PATH = _vp.DATA_ROOT / "llm.config.json"

DEFAULTS = {
    "url": "",                  # kein Server fest im Code - `.2ndbrain/llm.config.json` (oder VAULT_LLM_URL)
    "model": "qwen3.6-35b-a3b",
    "model_pruefung": "",       # zweite Stufe der Nachbereitung (nachbereiten_modell.pruefen); leer = keine
    "timeout_s": 240,
    "max_input_chars": 20000,
    "temperature": 0.1,
    "retries": 2,
    "log": ".2ndbrain/daten/.llm_log.jsonl",
}

NO_SERVER = "kein Modell-Server eingetragen (.2ndbrain/llm.config.json: \"url\")"

# Der Server bedient genau eine Anfrage gleichzeitig (`--parallel 1`) - eine
# zweite waehrend der ersten wuerde blockieren oder abgewiesen werden. Ein
# modulweites Lock serialisiert alle Aufrufe, egal aus wie vielen Threads.
_LOCK = threading.Lock()


def _load_json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def config() -> dict:
    """Aufgeloeste Konfiguration nach der Rangfolge im Modul-Docstring."""
    cfg = dict(DEFAULTS)

    file_cfg = _load_json_file(CONFIG_PATH)
    for k, v in file_cfg.items():
        if v is not None:
            cfg[k] = v

    if os.environ.get("VAULT_LLM_URL"):
        cfg["url"] = os.environ["VAULT_LLM_URL"]
    if os.environ.get("VAULT_LLM_MODEL"):
        cfg["model"] = os.environ["VAULT_LLM_MODEL"]
    if os.environ.get("VAULT_LLM_TIMEOUT"):
        try:
            cfg["timeout_s"] = int(os.environ["VAULT_LLM_TIMEOUT"])
        except ValueError:
            pass
    if os.environ.get("VAULT_LLM_LOG"):
        cfg["log"] = os.environ["VAULT_LLM_LOG"]
    cfg["offline"] = os.environ.get("VAULT_LLM_OFFLINE") == "1"

    log = Path(str(cfg["log"]))
    cfg["log"] = str(log if log.is_absolute() else _vp.VAULT / log)
    return cfg


# ------------------------------------------------------------- Fehlerbild
#
# Jede Stoerung der Verbindung zum Modell bekommt eine Art, eine Ursache in einem Satz und einen
# Ausweg - statt "HTTPError: HTTP Error 409: Conflict". Die Art entscheidet auch, was die Engine
# selbst tut: ein Abbruch wird einmal wiederholt, bei einer Sperre kommt das naechste Modell der
# Liste (`kandidaten`), alles andere geht an den Aufrufer.

FEHLER_ARTEN: dict[str, tuple[str, str]] = {
    "kein_server": (
        "Es ist kein Modell-Server eingetragen.",
        "Einstellungen → 2ndBrain → Vault-Konfiguration → Modell-Server: Adresse eintragen."),
    "offline": (
        "Das Modell ist für diesen Lauf abgeschaltet (VAULT_LLM_OFFLINE=1).",
        "Die Umgebungsvariable VAULT_LLM_OFFLINE entfernen."),
    "nicht_erreichbar": (
        "Der Modell-Server antwortet nicht.",
        "Netz prüfen (unterwegs: VPN) oder die Adresse unter Einstellungen → 2ndBrain → Vault-Konfiguration "
        "→ Modell-Server ändern. Was ohne Modell liegen bleibt, holt der nächste Lauf nach."),
    "gesperrt": (
        "Der Server lässt das Modell gerade nicht zu.",
        "Mit eingetragenem Modell-Schlüssel (Einstellungen → 2ndBrain → Modell-Server) fordert die Engine das "
        "Modell selbst an. Sonst am Server freigeben oder warten – der nächste Lauf versucht es zuerst wieder "
        "mit dem besten Modell der Liste."),
    "unbekannt_modell": (
        "Der Server kennt das eingetragene Modell nicht.",
        "Einstellungen → 2ndBrain → Vault-Konfiguration → Modell: eines der vorhandenen Modelle eintragen."),
    "abbruch": (
        "Der Server hat die Verbindung mitten im Aufruf geschlossen (Neustart oder Modellwechsel?).",
        "Die Engine hat es einmal wiederholt. Bleibt es dabei: am Server nachsehen, ob das Modell geladen "
        "bleibt (Speicher)."),
    "zeitlimit": (
        "Das Modell hat nicht rechtzeitig geantwortet.",
        "Das Material ist für einen Aufruf zu lang oder der Server ausgelastet: später noch einmal, oder "
        "`timeout_s` in .2ndbrain/llm.config.json anheben."),
    "http": (
        "Der Server hat den Aufruf abgelehnt.",
        "Die Meldung des Servers steht dabei – meist eine Einstellung am Server."),
    "unbekannt": (
        "Der Aufruf ans Modell ist gescheitert.",
        "Diagnose starten: `2ndbrain modell --diagnose`."),
}

_ERLAUBT_RE = re.compile(r"Erlaubt (?:ist|sind):\s*([^.\n]+)|antwortet nur das \w*[Mm]odell\s+([\w.:\-]+\w)")
_VORHANDEN_RE = re.compile(r"nicht in /v1/models \(([^)]*)\)")
_ART_MUSTER: list[tuple[str, re.Pattern]] = [
    ("kein_server", re.compile(r"kein Modell-Server eingetragen")),
    ("offline", re.compile(r"VAULT_LLM_OFFLINE")),
    ("gesperrt", re.compile(r"HTTP (?:Error )?409|nicht erlaubt", re.I)),
    ("unbekannt_modell", re.compile(r"nicht in /v1/models|HTTP (?:Error )?404|model.{0,40}not found", re.I)),
    ("abbruch", re.compile(r"ConnectionResetError|ConnectionAbortedError|RemoteDisconnected|IncompleteRead|"
                           r"WinError 1005[34]|Connection reset|Broken pipe", re.I)),
    ("nicht_erreichbar", re.compile(r"urlopen error|ConnectionRefusedError|Connection refused|getaddrinfo|"
                                    r"WinError 1006[01]|unreachable|No route to host|Name or service not known|"
                                    r"nodename nor servname", re.I)),
    ("zeitlimit", re.compile(r"TimeoutError|timed out", re.I)),
    ("http", re.compile(r"HTTP (?:Error )?\d{3}")),
]


def fehler_einordnen(error: str) -> dict:
    """Eine Fehlermeldung des Modell-Aufrufs einordnen: {art, ursache, ausweg, erlaubt, meldung}.
    `erlaubt`: Modelle, die der Server stattdessen nennt (Sperre) oder kennt (unbekanntes Modell)."""
    text = str(error or "")
    art = next((a for a, muster in _ART_MUSTER if muster.search(text)), "unbekannt")
    erlaubt: list[str] = []
    m = _ERLAUBT_RE.search(text) if art == "gesperrt" else _VORHANDEN_RE.search(text) if art == "unbekannt_modell" else None
    if m:
        erlaubt = [x.strip(" '\"`") for x in re.split(r",|\bund\b", next(g for g in m.groups() if g))]
        erlaubt = [x for x in erlaubt if x and x != "keine Eintraege"]
    ursache, ausweg = FEHLER_ARTEN[art]
    if art == "gesperrt" and erlaubt:
        ursache += f" Erlaubt ist gerade: {', '.join(erlaubt)}."
    if art == "unbekannt_modell" and erlaubt:
        ursache += f" Vorhanden: {', '.join(erlaubt)}."
    return {"art": art, "ursache": ursache, "ausweg": ausweg, "erlaubt": erlaubt, "meldung": text}


class LLMUnavailableError(RuntimeError):
    """Der Aufruf ans Modell kam nicht zustande. `art`, `ursache`, `ausweg` und `erlaubt` wie
    `fehler_einordnen` - fuer eine Meldung, mit der man etwas anfangen kann."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        info = fehler_einordnen(message)
        self.art: str = info["art"]
        self.ursache: str = info["ursache"]
        self.ausweg: str = info["ausweg"]
        self.erlaubt: list[str] = info["erlaubt"]


# Modelle, die der Server in diesem Prozess abgelehnt hat (Sperre, unbekannt) - sie werden nicht
# noch einmal gefragt. Am 28.09.2026 gingen zehn Aufrufe im Abstand von zehn Sekunden an ein
# gesperrtes Modell. Der naechste Lauf (neuer Prozess) beginnt wieder beim besten Modell.
_ABGELEHNT: dict[str, str] = {}
_ZULETZT = {"model": "", "ersatz_fuer": ""}


def kandidaten(cfg: dict | None = None) -> list[str]:
    """Die Modelle in der Reihenfolge, in der sie versucht werden - das beste zuerst: `modelle` aus
    llm.config.json; ohne Liste das eingestellte Modell, dann das der Pruefstufe."""
    cfg = cfg or config()
    liste = cfg.get("modelle")
    reihe = [str(m).strip() for m in liste] if isinstance(liste, list) else []
    reihe += [str(cfg.get("model") or "").strip()]
    if not isinstance(liste, list):
        reihe.append(str(cfg.get("model_pruefung") or "").strip())
    return [m for m in dict.fromkeys(reihe) if m]


def zuletzt() -> dict:
    """Welches Modell den letzten gelungenen Aufruf beantwortet hat: {model, ersatz_fuer} -
    `ersatz_fuer` nennt das gewuenschte Modell, wenn ein anderes einspringen musste."""
    return dict(_ZULETZT)


def _http_get(url: str, timeout: float) -> dict:
    """Isoliert fuer Tests: hier und nur hier passiert der echte GET."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post(url: str, payload: dict, timeout: float) -> dict:
    """Isoliert fuer Tests: hier und nur hier passiert der echte POST."""
    data = json.dumps(payload).encode("utf-8")
    # Die Engine arbeitet unbeaufsichtigt: ein Laib-Server zaehlt ihre Aufrufe dann nicht als
    # "ein Mensch hat gerade gefragt" (laib ADR 0011, #550). Andere Server uebergehen den Kopf.
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                          "X-Laib-Background": LEASE_HALTER})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Die Begruendung des Servers mitgeben statt nur "409 Conflict" - z. B. wenn
        # der Server das angefragte Modell gerade nicht zulaesst.
        try:
            msg = json.loads(e.read().decode("utf-8", "replace")).get("error", {}).get("message")
        except (ValueError, AttributeError, OSError):
            msg = None
        raise OSError(f"HTTP {e.code}: {msg}" if msg else f"HTTP {e.code} {e.reason}") from e


# ------------------------------------------------------------------ Lease
#
# Ein Laib-Server gibt im Haushalt nur das Haushaltsmodell frei und lehnt jedes andere mit 409 ab -
# ausser, ein benannter Halter holt sich eine Lease. Der Vertrag (laib, docs/adr/0011, Fassung
# 2026-10-14):
#   POST   {model, ttl_s, holder} + Authorization: Bearer <Modell-Schluessel>
#          200 ready | 202 preparing (GET abfragen, nicht noch einmal senden) | 409 held | 401
#          derselbe POST verlaengert - alle `renew_after` Sekunden, sonst geht die Karte verloren
#   GET    ohne Schluessel: {state, holder, allowed, mode, expires_at, last_human_at, ...}
#   DELETE {holder} + Schluessel: gibt zurueck
# Eine Lease fuer ein grosses Modell kostet den Haushalt etwas (Spracherkennung und Einbettungen
# ruhen, die Sprachausgabe rechnet auf der CPU). Deshalb: nur anfordern, wenn seit LEASE_RUHE_S
# niemand das Modell gefragt hat, so kurz wie moeglich halten (auto.py gibt nach jedem Schritt
# zurueck, sonst das Prozessende) und nie die eigene Arbeit daran scheitern lassen.
# Der Schluessel kommt nur aus der Umgebung (VAULT_LLM_KEY - das Plugin reicht ihn aus dem
# Obsidian-Schluesselbund herein), steht in keiner Datei und in keinem Protokoll.

LEASE_PFAD = "/api/model-lease"
LEASE_HALTER = "2ndbrain"                 # der Dienst, nie eine Person oder ein Lauf: [a-z0-9-]{1,64}
LEASE_TTL_S = 3600                        # laengstens so lange; zurueckgegeben wird frueher
LEASE_RUHE_S = 600                        # so lange muss der letzte Mensch am Modell her sein
LEASE_WARTEN_S = 600                      # so lange darf das Modell laden (202 preparing)
OHNE_SCHLUESSEL = ("kein Modell-Schlüssel eingetragen (Einstellungen → 2ndBrain → Modell-Server → "
                   "Modell-Schlüssel) – ohne ihn kann die Engine das Modell nicht anfordern")
_LEASE: dict = {"model": "", "puls": None}     # die Lease, die dieser Prozess haelt, und ihr Verlaengerer


class LeaseAbgelehnt(OSError):
    """Der Server hat die Lease-Anfrage abgelehnt: `code` und der Rumpf seiner Antwort."""

    def __init__(self, code: int, body: dict) -> None:
        self.code, self.body = code, body if isinstance(body, dict) else {}
        super().__init__(f"HTTP {code}: {self.body.get('message') or self.body.get('reason') or ''}".rstrip(": "))


def lease_schluessel() -> str:
    return os.environ.get("VAULT_LLM_KEY", "").strip()


def _uhrzeit(epoch) -> str:
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "?"


def _http_lease(method: str, url: str, payload: dict | None, key: str, timeout: float) -> dict:
    """Isoliert fuer Tests: der einzige Aufruf der Lease-Schnittstelle. Der Schluessel steht nur im Kopf."""
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            return json.loads(text) if text.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
        except (ValueError, OSError):
            body = {}
        raise LeaseAbgelehnt(e.code, body) from e


def lease_stand(timeout: float = 5) -> dict:
    """Was der Server zur Freigabe sagt: {mode, allowed, state, holder, model, expires_at, ...} -
    {} ohne Server, ohne diese Schnittstelle oder bei einem Fehler. Wirft nie."""
    cfg = config()
    if cfg["offline"] or not cfg["url"]:
        return {}
    try:
        data = _http_lease("GET", cfg["url"].rstrip("/") + LEASE_PFAD, None, "", timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return {}
    return data if isinstance(data, dict) else {}


def lease_anfordern(model: str, timeout: float = 30) -> tuple[bool, str]:
    """Das Modell fuer diesen Prozess anfordern. (ok, grund) - wirft nie. Ohne Schluessel gar kein
    Aufruf; lehnt der Server ab (gerade nutzt jemand das Haushaltsmodell, falscher Schluessel),
    steht seine Begruendung im Grund."""
    cfg = config()
    key = lease_schluessel()
    if not key:
        return False, OHNE_SCHLUESSEL
    url = cfg["url"].rstrip("/") + LEASE_PFAD
    netz = (urllib.error.URLError, OSError, ValueError, TimeoutError)

    stand = lease_stand()
    if stand.get("holder") == LEASE_HALTER and not _LEASE["model"]:
        # ein frueherer Lauf ist mit der Lease abgebrochen: erst zurueckgeben (Regel des Vertrags)
        try:
            _http_lease("DELETE", url, {"holder": LEASE_HALTER}, key, 10)
        except netz:
            pass
        stand = lease_stand()
    # niemandem das Modell unter den Haenden wegnehmen: war gerade ein Mensch dran, wartet die Engine
    zuletzt_mensch = stand.get("last_human_at")
    if isinstance(zuletzt_mensch, (int, float)) and time.time() - zuletzt_mensch < LEASE_RUHE_S:
        return False, (f"am Modell-Server hat um {_uhrzeit(zuletzt_mensch)} jemand gefragt – die Engine fordert "
                       f"{model} erst an, wenn {LEASE_RUHE_S // 60} Minuten Ruhe ist")

    try:
        data = _http_lease("POST", url, {"model": model, "ttl_s": LEASE_TTL_S, "holder": LEASE_HALTER}, key, timeout)
    except LeaseAbgelehnt as e:
        if e.code in (401, 403):
            return False, "der Server lehnt den Modell-Schlüssel ab (Einstellungen → 2ndBrain → Modell-Server)"
        if e.code == 409:
            if model in (e.body.get("allowed") or []):
                return True, f"{model} ist im Fenster von {e.body.get('holder') or '?'} schon freigegeben"
            return False, (f"{e.body.get('holder') or 'ein anderer Dienst'} hält den Modell-Server bis "
                           f"{_uhrzeit(e.body.get('expires_at'))}")
        return False, f"der Server gibt {model} nicht frei ({e})"
    except netz as e:
        return False, f"der Server gibt {model} nicht frei ({type(e).__name__}: {e})"

    if not _LEASE["model"]:
        import atexit
        atexit.register(lease_freigeben)
    _LEASE["model"] = model
    if isinstance(data, dict) and data.get("state") == "preparing":
        # die Gewichte laden: GET abfragen, nicht noch einmal senden
        pause = max(1, min(60, int(data.get("retry_after") or 30)))
        ende = time.monotonic() + LEASE_WARTEN_S
        while time.monotonic() < ende:
            _schlafen(pause)
            stand = lease_stand()
            if stand.get("state") == "ready" and stand.get("holder") == LEASE_HALTER:
                data = stand
                break
            if stand.get("holder") not in (LEASE_HALTER, None) or stand.get("state") == "none":
                lease_freigeben()
                return False, f"der Server hat die Lease für {model} wieder zurückgenommen"
        else:
            lease_freigeben()
            return False, f"{model} war nach {LEASE_WARTEN_S // 60} Minuten noch nicht geladen"
    _puls_starten(model, int((data or {}).get("renew_after") or 0))
    return True, f"Lease für {model}"


def _schlafen(sekunden: float) -> None:
    """Isoliert fuer Tests."""
    time.sleep(sekunden)


def _puls_starten(model: str, renew_after: int) -> None:
    """Die Lease verlaengern, solange dieser Prozess sie haelt - derselbe POST alle `renew_after`
    Sekunden (ein Aufruf ans Modell kann laenger dauern als die Frist). Ein Hintergrund-Faden, der
    mit dem Prozess endet."""
    if renew_after <= 0:
        return
    stopp = threading.Event()

    def lauf() -> None:
        cfg = config()
        while not stopp.wait(renew_after):
            if _LEASE["model"] != model:
                return
            try:
                _http_lease("POST", cfg["url"].rstrip("/") + LEASE_PFAD,
                            {"model": model, "ttl_s": LEASE_TTL_S, "holder": LEASE_HALTER}, lease_schluessel(), 30)
            except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                pass                    # die naechste Verlaengerung versucht es wieder

    _puls_stoppen()
    _LEASE["puls"] = stopp
    threading.Thread(target=lauf, name="lease-puls", daemon=True).start()


def _puls_stoppen() -> None:
    if _LEASE.get("puls") is not None:
        _LEASE["puls"].set()
        _LEASE["puls"] = None


def lease_freigeben(timeout: float = 10) -> bool:
    """Die Lease dieses Prozesses zurueckgeben - nach dem Schritt, der sie brauchte (auto.py), sonst
    am Prozessende. Der Server faellt dann auf sein Modell zurueck, der Haushalt hat seine
    Dienste wieder. Wirft nie."""
    _puls_stoppen()
    if not _LEASE["model"]:
        return False
    cfg = config()
    try:
        _http_lease("DELETE", cfg["url"].rstrip("/") + LEASE_PFAD, {"holder": LEASE_HALTER},
                    lease_schluessel(), timeout)
        ok = True
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        ok = False                      # ohne Verlaengerung laeuft sie von selbst ab
    _LEASE["model"] = ""
    return ok


def available(timeout: int = 5) -> tuple[bool, str]:
    """`GET /v1/models` pruefen. Wirft nie - Netzfehler kommen als (False, grund)."""
    cfg = config()
    if cfg["offline"]:
        return False, "VAULT_LLM_OFFLINE=1 gesetzt"
    if not cfg["url"]:
        return False, NO_SERVER

    url = cfg["url"].rstrip("/") + "/v1/models"
    try:
        data = _http_get(url, timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        return False, f"{type(e).__name__}: {e}"

    entries = [m for m in (data.get("data") or []) if isinstance(m, dict)]
    ids = set()
    for m in entries:
        if m.get("id"):
            ids.add(str(m["id"]))
        ids.update(str(a) for a in (m.get("aliases") or []))

    # Das beste Modell der Liste, das der Server kennt und in diesem Prozess nicht abgelehnt hat
    reihe = kandidaten(cfg) or [cfg["model"]]
    bekannt = [m for m in reihe if m in ids and m not in _ABGELEHNT]
    if not bekannt:
        abgelehnt = [m for m in reihe if m in _ABGELEHNT]
        if abgelehnt:
            return False, _ABGELEHNT[abgelehnt[0]]
        return False, f"Modell '{reihe[0]}' nicht in /v1/models ({', '.join(sorted(ids)) or 'keine Eintraege'})"
    model = bekannt[0]

    # llama-server laedt Modelle bei Bedarf nach - status != 'loaded' ist ein
    # Hinweis, kein Fehler (der naechste Aufruf wartet einfach laenger).
    hint = ""
    for m in entries:
        if m.get("id") != model and model not in (m.get("aliases") or []):
            continue
        status = m.get("status")
        value = status.get("value") if isinstance(status, dict) else status
        if value and value != "loaded":
            hint = f", Status: {value} (laedt bei Bedarf)"
        break
    if model != reihe[0]:
        hint += f" - Ersatz fuer '{reihe[0]}'"
    return True, f"erreichbar, Modell '{model}' bekannt{hint}"


def _log(*, log_path: str, **fields) -> None:
    """Ein Protokoll-Fehler darf den eigentlichen Aufruf nie kippen."""
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), **fields}
    try:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def complete(messages: list[dict], *, schema: dict | None = None, max_tokens: int = 1024,
             temperature: float | None = None, timeout: float | None = None,
             task: str = "", model: str | None = None) -> str:
    """Einen Chat-Completion-Aufruf absetzen. Gibt den rohen Content-String zurueck.
    `model`: genau dieses Modell (z. B. die Pruefstufe der Nachbereitung). Ohne Angabe gilt die
    Reihe aus `kandidaten()`, das beste zuerst: lehnt der Server ein Modell ab (gesperrt, unbekannt),
    kommt das naechste der Liste - nie eines, das nicht in der Liste steht. Ein Abbruch mitten im
    Aufruf wird einmal wiederholt."""
    cfg = config()
    if cfg["offline"]:
        raise LLMUnavailableError("VAULT_LLM_OFFLINE=1 gesetzt")
    if not cfg["url"]:
        raise LLMUnavailableError(NO_SERVER)

    fest = bool(model)
    alle = kandidaten(cfg) or [cfg["model"]]
    wunsch = alle[0]
    reihe = [model] if fest else ([m for m in alle if m not in _ABGELEHNT] or alle[:1])
    temp = cfg["temperature"] if temperature is None else temperature
    params = llama_params(schema, temperature=temp)
    url = cfg["url"].rstrip("/") + "/v1/chat/completions"
    to = timeout or cfg["timeout_s"]
    chars_in = sum(len(str(m.get("content", ""))) for m in messages)

    i, wiederholt = 0, False
    angefordert: set[str] = set()          # je Aufruf hoechstens eine Lease-Anfrage je Modell
    while True:
        aktuell = reihe[i]
        payload = {"model": aktuell, "messages": messages, "max_tokens": max_tokens,
                   "stream": False, **params}
        t0 = time.monotonic()
        content, error = "", ""
        try:
            with _LOCK:
                result = _http_post(url, payload, to)
            content = (result.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        except (urllib.error.URLError, OSError, ValueError, TimeoutError, IndexError, KeyError) as e:
            error = f"{type(e).__name__}: {e}"
        duration = time.monotonic() - t0
        ersatz_fuer = wunsch if (not fest and aktuell != wunsch) else ""

        _log(log_path=cfg["log"], task=task, model=aktuell, chars_in=chars_in,
             chars_out=len(content), duration_s=round(duration, 3), repairs=[],
             ok=not error, error=error, **({"ersatz_fuer": ersatz_fuer} if ersatz_fuer else {}))
        if not error:
            _ZULETZT.update(model=aktuell, ersatz_fuer=ersatz_fuer)
            # Die Antwort landet in Notizen und das Modell liest fremde Mails mit: ausfuehrbare
            # Codebloecke (dataviewjs ...) nie durchreichen.
            return fremdtext.entschaerfen(content)

        art = fehler_einordnen(error)["art"]
        if art == "abbruch" and not wiederholt:
            wiederholt = True
            continue
        if art == "gesperrt" and aktuell not in angefordert:
            # das bessere Modell anfordern, statt gleich auszuweichen (Lease; auch fuer die Pruefstufe)
            angefordert.add(aktuell)
            ok_lease, grund = lease_anfordern(aktuell)
            _log(log_path=cfg["log"], task="lease", model=aktuell, chars_in=0, chars_out=0,
                 duration_s=0, repairs=[], ok=ok_lease, error="" if ok_lease else grund)
            if ok_lease:
                continue
            error = f"{error} – Lease: {grund}"
        if not fest and art in ("gesperrt", "unbekannt_modell"):
            _ABGELEHNT[aktuell] = error
            if i + 1 < len(reihe):
                i, wiederholt = i + 1, False
                continue
        raise LLMUnavailableError(error)


def complete_json(messages: list[dict], schema: dict, *, max_tokens: int = 1024,
                   retries: int | None = None, task: str = "", model: str | None = None,
                   timeout: float | None = None) -> tuple[dict, list[str]]:
    """`complete()` + `modell_ausgabe.parse_json`. Bei kaputtem JSON wird die Ausgabe-
    Rettung selbst zum Prompt: ein Wiederholungsversuch mit expliziter
    Fehlermeldung, danach wird `LLMOutputError` weitergereicht statt geschluckt."""
    cfg = config()
    attempts = 1 + (cfg["retries"] if retries is None else retries)
    msgs = list(messages)
    last_err: LLMOutputError | None = None
    all_repairs: list[str] = []

    for _ in range(max(1, attempts)):
        raw = complete(msgs, schema=schema, max_tokens=max_tokens, task=task, model=model, timeout=timeout)
        try:
            payload, repairs = parse_json(raw, expect=dict)
            return fremdtext.entschaerfen_daten(payload), all_repairs + repairs
        except LLMOutputError as e:
            last_err = e
            all_repairs.append(f"Neuversuch nach Parse-Fehler: {e}")
            msgs = msgs + [{"role": "user", "content":
                f"Deine Antwort war kein gültiges JSON ({e}). Antworte ausschließlich "
                "mit dem JSON-Objekt, ohne Fließtext und ohne Code-Fence."}]
    raise last_err


def chunks(text: str, max_chars: int) -> list[str]:
    """Text in Stuecke <= max_chars teilen - an Absatzgrenzen, wenn moeglich.

    Fuer lange Transkripte: `nachbereiten_modell.extract()` extrahiert je Stueck einmal
    und mischt/dedupliziert danach, statt den ganzen Text in einen Prompt zu
    zwingen (stark quantisierte Modelle verlieren bei sehr langen Prompts an Genauigkeit)."""
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return [text] if text else []

    parts: list[str] = []
    cur = ""
    for para in re.split(r"\n{2,}", text):
        candidate = f"{cur}\n\n{para}" if cur else para
        if len(candidate) <= max_chars:
            cur = candidate
            continue
        if cur:
            parts.append(cur)
            cur = ""
        if len(para) <= max_chars:
            cur = para
        else:
            parts.extend(_zerlegen(para, max_chars))
    if cur:
        parts.append(cur)
    return parts


_TRENNER = ("\n", ". ", " ")


def _zerlegen(text: str, max_chars: int, stufe: int = 0) -> list[str]:
    """Zu langen Absatz teilen: an Zeilen, sonst an Saetzen, sonst an Leerzeichen - nie mitten im
    Wort (eine Teams-Zusammenfassung ist oft ein einziger Block ohne Leerzeile; hart nach Zeichen
    geschnitten wurde aus "Use-Case-Schnueffeln" im naechsten Stueck "ase-Schnueffeln")."""
    if len(text) <= max_chars:
        return [text]
    for i in range(stufe, len(_TRENNER)):
        sep = _TRENNER[i]
        teile = text.split(sep)
        if len(teile) < 2:
            continue
        out, cur = [], ""
        for t in teile:
            kand = f"{cur}{sep}{t}" if cur else t
            if len(kand) <= max_chars:
                cur = kand
                continue
            if cur:
                out.append(cur + sep.rstrip())
            if len(t) <= max_chars:
                cur = t
            else:
                out.extend(_zerlegen(t, max_chars, i + 1))
                cur = ""
        if cur:
            out.append(cur)
        return out
    return [text[j:j + max_chars] for j in range(0, len(text), max_chars)]     # ein einziges Riesenwort


def antwort_tokens(eingabe_zeichen: int, *, mindestens: int = 4096, hoechstens: int = 12288,
                   faktor: float = 0.26) -> int:
    """Obergrenze fuer eine Antwort, die das ganze Material liest (Pruefstufe, Protokoll): gemessen
    sind Antworten 13-44 % so lang wie die Eingabe (in Zeichen), bei rund 3,5 Zeichen je Token und
    doppeltem Spielraum ~0,26 Token je Eingabezeichen - begrenzt auf mindestens/hoechstens. Nur
    eine Grenze: das Modell hoert auf, wenn es fertig ist."""
    return max(mindestens, min(hoechstens, round(eingabe_zeichen * faktor)))


# -------------------------------------------------------------- Diagnose

DIAGNOSE_SCHRITTE = (("adresse", "Adresse eingetragen"), ("server", "Server antwortet"),
                     ("modell", "Modell vorhanden"), ("format", "Antwort im verlangten Format"),
                     ("werkzeuge", "Werkzeuge für den Chat"), ("freigabe", "Alle Modelle freigegeben"))


def diagnose() -> list[dict]:
    """Die Verbindung zum Modell Schritt fuer Schritt pruefen. Je Schritt
    {schritt, titel, ok, detail, ausweg}; `ok` ist None fuer Schritte hinter dem ersten
    gescheiterten (nicht geprueft). Wirft nie."""
    cfg = config()
    out: list[dict] = []
    offen = True

    def schritt(name: str, ok: bool | None, detail: str = "", ausweg: str = "") -> None:
        nonlocal offen
        out.append({"schritt": name, "titel": dict(DIAGNOSE_SCHRITTE)[name], "ok": ok if offen else None,
                    "detail": detail if offen else "", "ausweg": ausweg if (offen and ok is False) else ""})
        if ok is False:
            offen = False

    def fehler(name: str, error: str) -> None:
        info = fehler_einordnen(error)
        schritt(name, False, f"{info['ursache']} ({error})", info["ausweg"])

    if cfg["offline"]:
        fehler("adresse", "VAULT_LLM_OFFLINE=1 gesetzt")
    elif not cfg["url"]:
        fehler("adresse", NO_SERVER)
    else:
        schritt("adresse", True, cfg["url"])

    ids: set[str] = set()
    if offen:
        t0 = time.monotonic()
        try:
            data = _http_get(cfg["url"].rstrip("/") + "/v1/models", 5)
            for m in (data.get("data") or []):
                if isinstance(m, dict):
                    ids.update(str(x) for x in [m.get("id"), *(m.get("aliases") or [])] if x)
            schritt("server", True, f"{int((time.monotonic() - t0) * 1000)} ms, {len(ids)} Modell(e)")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
            fehler("server", f"{type(e).__name__}: {e}")
    else:
        schritt("server", None)

    reihe = kandidaten(cfg) or [cfg["model"]]
    if offen:
        bekannt = [m for m in reihe if m in ids]
        if not bekannt:
            fehler("modell", f"Modell '{reihe[0]}' nicht in /v1/models ({', '.join(sorted(ids)) or 'keine Eintraege'})")
        else:
            fehlt = [m for m in reihe if m not in ids]
            schritt("modell", True, bekannt[0] + (f" – nicht vorhanden: {', '.join(fehlt)}" if fehlt else ""))
    else:
        schritt("modell", None)

    if offen:
        schema = {"type": "object", "additionalProperties": False, "required": ["ok"],
                  "properties": {"ok": {"type": "boolean"}}}
        t0 = time.monotonic()
        try:
            complete_json([{"role": "system", "content": "Antworte ausschliesslich mit einem JSON-Objekt."},
                           {"role": "user", "content": 'Antworte exakt mit {"ok": true}'}],
                          schema, max_tokens=32, task="diagnose")
            z = zuletzt()
            schritt("format", True, f"{z['model']}, {int((time.monotonic() - t0) * 1000)} ms"
                    + (f" – Ersatz für {z['ersatz_fuer']}" if z["ersatz_fuer"] else ""))
        except LLMUnavailableError as e:
            fehler("format", str(e))
        except LLMOutputError as e:
            schritt("format", False, f"Das Modell hält das Format nicht ein ({e}).",
                    "Ein anderes Modell eintragen oder am Server die Grammatik-Unterstützung prüfen.")
    else:
        schritt("format", None)

    if offen:
        payload = {"model": zuletzt()["model"] or reihe[0], "max_tokens": 16, "stream": False,
                   "messages": [{"role": "user", "content": "Sag ok."}], "tool_choice": "auto",
                   "tools": [{"type": "function", "function": {
                       "name": "probe", "description": "Probe", "parameters": {"type": "object", "properties": {}}}}]}
        try:
            with _LOCK:
                _http_post(cfg["url"].rstrip("/") + "/v1/chat/completions", payload, 60)
            schritt("werkzeuge", True, "unterstützt")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
            schritt("werkzeuge", False, f"Der Server nimmt keine Werkzeuge an ({type(e).__name__}: {e}).",
                    "Der Chat antwortet dann in einem Schritt, ohne nachzuschlagen. llama.cpp: mit `--jinja` starten.")
    else:
        schritt("werkzeuge", None)

    # Gibt der Server gerade alle Modelle frei, die gebraucht werden (Entwurf, Pruefstufe)? Ein
    # fehlender Chat-Werkzeug-Schritt haelt diese Pruefung nicht auf.
    if out and all(s["ok"] is not None for s in out[:4]) and all(s["ok"] for s in out[:4]):
        offen = True
        stand = lease_stand()
        erlaubt = stand.get("allowed") if isinstance(stand.get("allowed"), list) else None
        gebraucht = list(dict.fromkeys([*reihe, str(cfg.get("model_pruefung") or "").strip()]))
        gesperrt = [m for m in gebraucht if m and erlaubt is not None and m not in erlaubt
                    and m != stand.get("model")]
        if not gesperrt:
            schritt("freigabe", True, f"Modus {stand['mode']}" if stand.get("mode") else "")
        elif lease_schluessel():
            schritt("freigabe", True, f"Modus {stand.get('mode') or '?'}: {', '.join(gesperrt)} gesperrt – "
                    "die Engine fordert es bei Bedarf an (Modell-Schlüssel eingetragen)")
        else:
            schritt("freigabe", False, f"Modus {stand.get('mode') or '?'}: {', '.join(gesperrt)} gesperrt – "
                    "die Prüfstufe der Nachbereitung fällt aus",
                    "Modell-Schlüssel eintragen (Einstellungen → 2ndBrain → Modell-Server → Modell-Schlüssel): "
                    "dann fordert die Engine das Modell selbst an und gibt es danach zurück.")
    else:
        schritt("freigabe", None)
    return out


def _cli_diagnose(as_json: bool) -> int:
    schritte = diagnose()
    if as_json:
        print(json.dumps({"ok": all(s["ok"] for s in schritte), "schritte": schritte}, ensure_ascii=False, indent=2))
    else:
        for s in schritte:
            marke = "OK  " if s["ok"] else "–   " if s["ok"] is None else "NEIN"
            print(f"{marke} {s['titel']}" + (f": {s['detail']}" if s["detail"] else ""))
            if s["ausweg"]:
                print(f"     Ausweg: {s['ausweg']}")
    return 0 if all(s["ok"] for s in schritte) else 1


# ------------------------------------------------------------------- CLI

def _cli_selftest() -> int:
    cfg = config()
    print(f"URL: {cfg['url']}  Modell: {cfg['model']}  Timeout: {cfg['timeout_s']}s")

    t0 = time.monotonic()
    ok, reason = available(timeout=min(10, cfg["timeout_s"]))
    ms = int((time.monotonic() - t0) * 1000)
    print(f"/v1/models  {'OK' if ok else 'FEHLER'}  ({ms} ms)  {reason}")
    if not ok:
        return 1

    schema = {"type": "object", "additionalProperties": False, "required": ["ok"],
              "properties": {"ok": {"type": "boolean"}}}
    messages = [
        {"role": "system", "content": "Antworte ausschliesslich mit einem JSON-Objekt."},
        {"role": "user", "content": 'Antworte exakt mit {"ok": true}'},
    ]
    t0 = time.monotonic()
    try:
        payload, repairs = complete_json(messages, schema, max_tokens=32, task="selftest")
        ms2 = int((time.monotonic() - t0) * 1000)
        print(f"JSON-Roundtrip  OK  ({ms2} ms)  {payload}"
              + (f"  Reparaturen: {repairs}" if repairs else ""))
        return 0
    except Exception as e:
        ms2 = int((time.monotonic() - t0) * 1000)
        print(f"JSON-Roundtrip  FEHLER  ({ms2} ms)  {type(e).__name__}: {e}")
        return 1


def main() -> int:
    args = sys.argv[1:]
    if "--config" in args:
        print(json.dumps(config(), indent=2, ensure_ascii=False))
        return 0
    if "--diagnose" in args:
        return _cli_diagnose("--json" in args)
    if "--selftest" in args or not args:
        return _cli_selftest()
    print("Usage: python -m secondbrain.modell --selftest | --diagnose [--json] | --config")
    return 0


if __name__ == "__main__":
    sys.exit(main())
