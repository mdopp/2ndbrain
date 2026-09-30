"""nachziehen.py - Alte Notizen auf den Stand der Engine bringen, wenn eine Aufbereitung besser geworden ist.

Jede Aufbereitung, die aus Quellen Felder ableitet, hat eine Fassung (eine Zahl); eine Notiz traegt die
Fassung, mit der sie aufbereitet wurde. Ist die Engine neuer, zieht die Automatik (Schritt `nachziehen`) die
alten Notizen nach - je Lauf ein Stueck (MAX_JE_LAUF, MAX_SEKUNDEN), damit sie nicht lange blockiert. Den
Stand liest das Plugin aus .2ndbrain/daten/nachziehen.json (Heute).

Nachgezogen werden nur aufbereitete Felder - nie, was der Nutzer geschrieben oder abgehakt hat.

    mail   Absender und Empfaenger (adressen.py, `mail_fassung`): von, an, cc, verteiler, teilnehmer
           vollstaendig und als Verweise; themen aus dem Einarbeiten (entities_updated). Auch spaeter noch:
           bekommt eine Person eine Seite, zeigen ihre Mails darauf.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from email.parser import BytesHeaderParser
from pathlib import Path

import adressen
import vault_paths as vp

MAX_JE_LAUF = 200
MAX_SEKUNDEN = 60
# Felder der ersten Fassung, die von/an/teilnehmer ersetzen (cc bleibt - als Liste)
ALTE_FELDER = ("from", "to", "participants")


def datei() -> Path:
    return vp.DATA_DIR / "nachziehen.json"


# ------------------------------------------------------------------ Mails

_EML: dict[str, Path] = {}
_EML_GELESEN = [False]


def _eml_nach_id() -> dict[str, Path]:
    """Die archivierten Original-Mails nach Message-ID (einmal je Lauf)."""
    if not _EML_GELESEN[0]:
        root = vp.SOURCES_DIR / "emails"
        for f in sorted(root.rglob("*.eml")) if root.is_dir() else []:
            try:
                with f.open("rb") as h:
                    mid = str(BytesHeaderParser().parse(h).get("Message-ID") or "").strip()
            except (OSError, ValueError):
                continue
            if mid:
                _EML.setdefault(mid, f)
        _EML_GELESEN[0] = True
    return _EML


def mail_notizen() -> list[Path]:
    """Alle Mail-Notizen: eingearbeitete im Archiv, noch offene im Eingang."""
    out = []
    for root in (vp.MEETINGS_DIR, vp.INBOX_DIR):
        for f in sorted(root.rglob("*.md")) if root.is_dir() else []:
            if str(vp.read_frontmatter_head(f).get("type") or "") == "email-thread":
                out.append(f)
    return out


def _koepfe(fm: dict, text: str) -> tuple[str, str, str]:
    """From, To, CC einer Mail-Notiz: aus der Original-Mail (Message-ID), sonst aus den Kopfzeilen im Text
    (vollstaendig), zuletzt aus dem Frontmatter der ersten Fassung (dort bei 400 Zeichen abgeschnitten)."""
    eml = _eml_nach_id().get(str(fm.get("message_id") or "").strip())
    if eml:
        with eml.open("rb") as h:
            kopf = BytesHeaderParser().parse(h)
        return str(kopf.get("From") or ""), str(kopf.get("To") or ""), str(kopf.get("Cc") or "")
    kopf = text.split("## ", 1)[0]                    # nur der Kopf der Notiz, nicht der zitierte Verlauf

    def zeile(label: str) -> str | None:
        return next((z.split(":**", 1)[1] for z in kopf.splitlines() if z.startswith(f"**{label}:**")), None)
    if zeile("Von") is not None:
        return tuple(adressen.aus_kopfzeile(zeile(x) or "") for x in ("Von", "An", "CC"))
    return tuple(adressen.aus_kopfzeile(str(fm.get(k) or "")) for k in ("from", "to", "cc"))


def _soll(note: Path, fm: dict, personen: adressen.Personen) -> dict:
    """Die Felder, die die Mail-Notiz nach dieser Fassung tragen soll."""
    k = adressen.felder(*_koepfe(fm, note.read_text(encoding="utf-8")), personen=personen)
    soll = {"von": k["von"], "an": k["an"], "cc": k["cc"], "verteiler": k["verteiler"],
            "teilnehmer": k["teilnehmer"], "rundmail": True if k["rundmail"] else None,
            "mail_fassung": adressen.MAIL_FASSUNG}
    if not fm.get("themen"):                          # eingearbeitet: die Themen, in die es ging
        themen = [s for s in fm.get("entities_updated") or []
                  if (vp.PROJECTS_DIR / f"{s}.md").is_file() or (vp.FORUMS_DIR / f"{s}.md").is_file()]
        if themen:
            soll["themen"] = themen
    return soll


def _leer(v) -> bool:
    return v is None or v == "" or v == [] or v is False


def mail_offen(note: Path, personen: adressen.Personen) -> bool:
    """Braucht die Mail-Notiz eine neue Fassung - oder hat eine Person inzwischen eine Seite?"""
    fm = vp.read_frontmatter(note)
    if int(fm.get("mail_fassung") or 1) < adressen.MAIL_FASSUNG or any(k in fm for k in ALTE_FELDER):
        return True
    soll = _soll(note, fm, personen)
    return any((fm.get(k) if not _leer(fm.get(k)) else None) != (v if not _leer(v) else None) for k, v in soll.items())


def mail(note: Path, personen: adressen.Personen | None = None) -> bool:
    """Eine Mail-Notiz auf den Stand bringen. True = geaendert."""
    fm = vp.read_frontmatter(note)
    return vp.update_frontmatter(note, _soll(note, fm, personen or adressen.Personen()), remove=ALTE_FELDER)


# ------------------------------------------------------------------ Lauf

def run(*, dry_run: bool = False, max_je_lauf: int = MAX_JE_LAUF, max_sekunden: float = MAX_SEKUNDEN) -> dict:
    """Ein Stueck nachziehen; der Stand steht danach in nachziehen.json."""
    t0 = time.time()
    personen = adressen.Personen()
    notizen = mail_notizen()
    offen = [n for n in notizen if mail_offen(n, personen)]
    erledigt, fehler = 0, []
    for n in offen[:max_je_lauf]:
        if time.time() - t0 > max_sekunden:
            break
        try:
            if not dry_run:
                mail(n, personen)
            erledigt += 1
        except Exception as e:  # noqa: BLE001 - eine kaputte Notiz haelt die anderen nicht auf
            fehler.append(f"{n.name}: {type(e).__name__}")
    rest = len(offen) - erledigt
    if not dry_run:
        f = datei()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"mail": {"fassung": adressen.MAIL_FASSUNG, "gesamt": len(notizen), "offen": rest,
                                          "am": datetime.now().isoformat(timespec="seconds")}},
                                ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return {"nachgezogen": erledigt, "offen": rest, "gesamt": len(notizen), "fehler": fehler}
