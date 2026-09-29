#!/usr/bin/env python3
"""kalender.py - Kalender im iCal-Format holen und nach archive/calendar/ schreiben.

Ergebnis: `events.json` (Vorbereitung, Plugin) und `kalender.md` (Uebersicht zum Lesen,
Rueckfall); jeder Lauf ersetzt beide Dateien.

Quelle: die Kalender-Adresse aus dem Obsidian-Schluesselbund (das Plugin reicht sie als
VAULT_CALENDAR_URL herein), sonst `ical_url` in .2ndbrain/calendar.config.json - https://,
webcal:// oder eine lokale .ics-Datei. Jeder Kalender, der iCal ausgibt (Outlook/Exchange,
Google, iCloud, Nextcloud …). Die Adresse wirkt wie ein Schluessel und steht in keiner Meldung.
Serien werden aufgeloest, Zeitzonen in Ortszeit umgerechnet (ical.py); abgesagte Termine und
eigene Absagen kommen mit `status` ("abgesagt"/"abgelehnt").

Laeuft in der Automatik (Schritt `kalender`, alle 6 h) und mit `2ndbrain einlesen --source calendar`.

Usage:
  python -m secondbrain.kalender                    # exports to archive/calendar/
  python -m secondbrain.kalender --days 90           # limit lookback (voraus immer 30 Tage)
  python -m secondbrain.kalender --range "2026-09-01,2026-10-31"  # specific range
"""

import os
import sys
import json
import re
from pathlib import Path
from datetime import date, datetime, timedelta
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ical  # noqa: E402

import vault_paths as vp  # noqa: E402

# Kalender-Zugang aus .2ndbrain/calendar.config.json.
# Die Freigabe-URL ist zugangsdaten-aequivalent (Lesezugriff ohne Anmeldung) und
# gehoert deshalb nicht in den Quellcode.
CONFIG_PATH = vp.DATA_ROOT / "calendar.config.json"
# Das Plugin reicht die Adresse aus dem Obsidian-Schluesselbund als Umgebungsvariable herein -
# dann liegt sie in keiner Datei im Vault-Ordner (und geht mit keiner Kopie des Vaults mit).
ENV_URL = "VAULT_CALENDAR_URL"
_SKIP_PREFIX_STATUS = (("declined:", "abgelehnt"), ("abgelehnt:", "abgelehnt"), ("canceled:", "abgesagt"),
                       ("cancelled:", "abgesagt"), ("abgesagt:", "abgesagt"), ("storniert:", "abgesagt"))


def load_calendar_config():
    """Erst beim Abrufen lesen (nicht beim Import - Tests und Werkzeuge brauchen keine Adresse).
    Zuerst der Schluesselbund (VAULT_CALENDAR_URL vom Plugin), sonst .2ndbrain/calendar.config.json."""
    env = os.environ.get(ENV_URL, "").strip()
    if env:
        return {"ical_url": env}
    if not CONFIG_PATH.is_file():
        print(f"ERROR: keine Kalender-Adresse ({CONFIG_PATH.name} fehlt, {ENV_URL} leer).", file=sys.stderr)
        print("Eintragen im 2ndBrain-Plugin (Einstellungen -> Kalender, Obsidian-Schluesselbund) oder mit",
              file=sys.stderr)
        print("`2ndbrain einrichten --kalender-url <Adresse>` (die iCal-Adresse deines Kalenders:",
              file=sys.stderr)
        print("  Outlook: Kalender veroeffentlichen -> ICS-Link; Google: Geheime Adresse im iCal-Format;",
              file=sys.stderr)
        print("  iCloud: Oeffentlicher Kalender (webcal://…); oder eine lokale .ics-Datei)", file=sys.stderr)
        sys.exit(2)
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: {CONFIG_PATH} nicht lesbar: {type(e).__name__}", file=sys.stderr)
        sys.exit(2)
    if not cfg.get("ical_url"):
        print(f"ERROR: 'ical_url' fehlt in {CONFIG_PATH}", file=sys.stderr)
        sys.exit(2)
    return cfg


# Vorbereitet werden die naechsten ein, zwei Tage; die Uebersicht zeigt die naechsten Wochen.
VORAUS_TAGE = 30


def parse_args():
    """Parse command-line arguments for date range."""
    days = 90
    start_date = None
    end_date = None

    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == '--days' and i + 1 < len(args):
            days = int(args[i + 1])
        elif arg == '--range' and i + 1 < len(args):
            parts = args[i + 1].split(',')
            start_date = parts[0].strip()
            end_date = parts[1].strip()
        elif arg == '--help':
            print(__doc__)
            sys.exit(0)

    if start_date and end_date:
        return start_date, end_date
    else:
        today = datetime.now()
        return (today - timedelta(days=days)).strftime('%Y-%m-%d'), (today + timedelta(days=VORAUS_TAGE)).strftime('%Y-%m-%d')


def source_kind(url: str) -> str:
    """"web" (https/http/webcal), "datei" (file:// oder Pfad) oder "" (unbrauchbar) - ohne Abruf."""
    u = (url or "").strip()
    if re.match(r"^(https?|webcal)://([^/\s:]+\.[^/\s:]+|localhost)(:\d+)?(/\S*)?$", u, re.I):
        return "web"                                 # Rechnername mit Punkt (oder localhost)
    if u.lower().startswith("file://") or u.lower().endswith(".ics") or re.match(r"^([A-Za-z]:[\\/]|[/~.])", u):
        return "datei"
    return ""


def fetch_ics(url=None):
    """Kalender holen: https/http, webcal (= https), file:// oder Pfad zu einer .ics-Datei.
    Die Adresse wirkt wie ein Schluessel - sie erscheint in keiner Meldung."""
    url = (url or load_calendar_config()["ical_url"]).strip()
    try:
        if url.lower().startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        if re.match(r"^https?://", url, re.I):
            with urlopen(url, timeout=20) as response:
                return response.read().decode('utf-8', errors='replace')
        path = Path(url[7:] if url.lower().startswith("file://") else url).expanduser()
        if not path.is_absolute():
            path = vp.VAULT / path                             # relativ zum Vault
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        # die Adresse ist ein Zugangsschluessel - nie in eine Meldung
        ohne_adresse = re.sub(r"(https?|webcal)://[^\s]+", "<Adresse>", str(e))
        print(f"ERROR fetching calendar: {type(e).__name__}: {ohne_adresse}", file=sys.stderr)
        sys.exit(1)


def _unescape_ical(s):
    """iCal-Escapes in der richtigen Reihenfolge aufloesen - siehe ical.unescape."""
    return ical.unescape(s)


def _attendee(params: dict, value: str, role: str) -> dict | None:
    name = (params.get("CN") or "").strip().strip('"')
    addr = value.split(':')[-1].strip() if 'mailto:' in value.lower() else value.strip()
    if not (name or addr):
        return None
    out = {'name': name or addr, 'email': addr, 'role': role}
    if params.get("PARTSTAT"):
        out['partstat'] = params["PARTSTAT"].upper()
    return out


def _parse_attendees(ev):
    """ATTENDEE/ORGANIZER-Zeilen -> Teilnehmerliste. `ev`: Text eines VEVENT oder dessen Komponente.
    Format: `ATTENDEE;CN=Name;...:mailto:a@b.de` - Name im `CN=`-Parameter, Adresse nach `mailto:`."""
    lines = ev["props"] if isinstance(ev, dict) else [
        x for x in (ical.parse_line(line) for line in ical.unfold(ev).splitlines()) if x]
    people = []
    for name, params, value in lines:
        if name in ("ATTENDEE", "ORGANIZER"):
            a = _attendee(params, value, 'organizer' if name == 'ORGANIZER' else 'attendee')
            if a:
                people.append(a)
    return people


def _own_emails() -> set:
    """Eigene Adresse(n) fuer "abgelehnt": `email:` der eigenen Personen-Seite."""
    try:
        import vault_paths as vp
        mail = str(vp.ich_seite().get("email") or "").strip().lower()
        return {mail} if mail else set()
    except Exception:
        return set()


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v).strip()[:10])


def parse_events(ics_data, start_date, end_date, own_emails=None, local=None):
    """Termine mit Beginn im Zeitraum (Tage einschliesslich, Ortszeit), Serien aufgeloest.
    `local`: Umrechnung UTC -> Ortszeit (Standard: dieser Rechner; Tests geben eine feste Zone)."""
    occurrences, warnings = ical.events(ics_data, _as_date(start_date), _as_date(end_date),
                                        local=local or ical.system_local)
    for w in warnings:
        print(f"[WARN] {w}", file=sys.stderr)
    own = {x.lower() for x in (_own_emails() if own_emails is None else own_emails)}
    events = []
    for o in occurrences:
        ev, when = o["comp"], o["start"]
        summary = ical.prop(ev, "SUMMARY")
        if summary is None:
            continue
        dt_str = when.strftime('%Y%m%d') if o["all_day"] else when.strftime('%Y%m%dT%H%M%S')
        s = _unescape_ical(summary[1])
        location = ical.prop(ev, "LOCATION")
        description = ical.prop(ev, "DESCRIPTION")
        loc = _unescape_ical(location[1]) if location else ''
        desc = _unescape_ical(description[1]) if description else ''
        attendees = _parse_attendees(ev)
        time_str = '' if o["all_day"] or (when.hour == 0 and when.minute == 0) else f"{when.hour:02d}:{when.minute:02d}"

        # Status: abgesagt (STATUS:CANCELLED), eigene Absage (PARTSTAT=DECLINED) oder - wie
        # Outlook es schreibt - als Vorsilbe im Titel ("Declined: …", "Abgesagt: …")
        status = o["status"]
        if not status and any(a.get('partstat') == 'DECLINED' and a.get('email', '').lower() in own
                              for a in attendees):
            status = 'abgelehnt'
        if not status:
            status = next((st for pre, st in _SKIP_PREFIX_STATUS if s.lower().startswith(pre)), '')

        events.append({
            'date': dt_str,
            'date_short': f"{dt_str[4:6]}-{dt_str[6:8]}",
            'time': time_str,
            'summary': s,
            'location': loc,
            'description': desc,
            'attendees': attendees,
            'all_day': o["all_day"],
            'status': status,
            # UID des Kalender-Eintrags (bei Serien fuer alle Termine gleich);
            # `outlook_uid` bleibt der Name in den Notizen.
            'uid': o["uid"],
            'outlook_uid': o["uid"],
        })

    # Sort by date descending (newest first)
    events.sort(key=lambda e: e['date'], reverse=True)
    return events


def classify_meeting(summary):
    """Classify a meeting by type for grouping."""
    s = summary.lower()
    if 'weekly' in s or 'wöchentlich' in s:
        return 'Weekly'
    elif 'checkin' in s or 'check-in' in s:
        return 'Checkin'
    elif 'jour' in s or 'j-fix' in s:
        return 'Jour Fixe'
    elif 'update' in s or 'status' in s:
        return 'Update/Status'
    elif 'steering' in s or 'board' in s:
        return 'Steering'
    elif 'private' in s or 'urlaub' in s or 'krank' in s:
        return 'Privat'
    elif 'declined' in s:
        return 'Abgesagt'
    else:
        return 'Sonstige'


def export_md(events, start_date, end_date):
    """Export events as a vault-friendly Markdown file."""
    lines = []
    lines.append(f'---')
    lines.append(f'slug: calendar-export')
    lines.append(f'type: calendar-export')
    lines.append(f'title: Kalender-Export {start_date} bis {end_date}')
    lines.append(f'description: Export aus dem Kalender (iCal)')
    lines.append(f'timestamp: {datetime.now().strftime("%Y-%m-%d %H:%M:%S+02:00")}')
    lines.append(f'---')
    lines.append(f'')
    lines.append(f'# Kalender-Export {start_date} bis {end_date}')
    lines.append(f'')
    lines.append(f'> Exportiert via iCal — {len(events)} Events')
    lines.append(f'')
    lines.append(f'**Datum:** {datetime.now().strftime("%Y-%m-%d %H:%M")} UTC+2')
    lines.append(f'')

    # Group by week for readability
    weeks = {}
    for ev in events:
        # Extract year-week
        year = ev['date'][:4]
        month = ev['date'][4:6]
        day = ev['date'][6:8]
        date_obj = datetime(int(year), int(month), int(day))
        week_key = date_obj.strftime('%Y-W%W')
        if week_key not in weeks:
            weeks[week_key] = []
        weeks[week_key].append(ev)

    # Group by category
    categories = {}
    for ev in events:
        cat = classify_meeting(ev['summary'])
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(ev)

    # --- Section 1: Upcoming (hoechstens 30 Termine) ---
    today = datetime.now().strftime('%Y%m%d')
    # Die Liste oben ist absteigend sortiert - hier die naechsten zuerst (sonst stuenden die
    # fernsten 30 da und heute fehlte)
    upcoming = sorted((e for e in events if e['date'] >= today), key=lambda e: (e['date'], e['time']))
    if upcoming:
        lines.append(f'## 🔮 Nächste Termine')
        lines.append(f'')
        for ev in upcoming[:30]:
            lines.append(f'- **{ev["date_short"]} {ev["time"]}** {ev["summary"]}')
            if ev['location']:
                lines.append(f'  📍 {ev["location"]}')
            if ev.get('outlook_uid'):
                lines.append(f'  🔑 UID: {ev["outlook_uid"][:40]}...')
        lines.append(f'')

    # --- Section 2: all events grouped by category ---
    lines.append(f'## 📊 Nach Kategorie ({len(events)} Events gesamt)')
    lines.append(f'')
    for cat in sorted(categories.keys(), key=lambda c: -len(categories[c])):
        cat_events = categories[cat]
        lines.append(f'### {cat} ({len(cat_events)})')
        lines.append(f'')
        for ev in cat_events[:15]:  # Cap per category
            lines.append(f'- **{ev["date_short"]} {ev["time"]}** {ev["summary"]}')
            if ev['location']:
                lines.append(f'  📍 {ev["location"]}')
            if ev.get('outlook_uid'):
                lines.append(f'  🔑 UID: {ev["outlook_uid"][:40]}...')
        lines.append(f'')

    # --- Section 3: Weekly breakdown ---
    lines.append(f'## 📆 Wochen-Übersicht')
    lines.append(f'')
    for week_key in sorted(weeks.keys(), reverse=True)[:10]:
        week_events = weeks[week_key]
        lines.append(f'### {week_key}')
        lines.append(f'')
        for ev in week_events:
            lines.append(f'- **{ev["time"]}** {ev["summary"]}')
        lines.append(f'')

    return '\n'.join(lines)


if __name__ == '__main__':
    start_date, end_date = parse_args()

    print(f"Fetching calendar...")
    ics_data = fetch_ics()
    print(f"Got {len(ics_data)} bytes")

    events = parse_events(ics_data, start_date, end_date)
    print(f"Parsed {len(events)} events for {start_date} to {end_date}")

    output = export_md(events, start_date, end_date)

    # Ausgabeverzeichnis relativ zum Vault, nicht zum CWD
    import vault_paths as vp
    out_dir = vp.SOURCES_DIR / "calendar"
    out_dir.mkdir(parents=True, exist_ok=True)

    # fester Name: jeder Lauf ersetzt die Datei, statt einen weiteren Export liegen zu lassen
    output_path = out_dir / "kalender.md"
    output_path.write_text(output, encoding='utf-8', newline="\n")
    print(f"\nExported to {output_path}")

    # JSON-Sidecar fuer die Vorbereitung. Der Markdown-Export ist menschenlesbar
    # gruppiert ("- **MM-DD HH:MM** Titel", ohne Jahr) und damit nicht
    # verlaesslich maschinenlesbar. vorbereiten.py und das Plugin lesen bevorzugt diese Datei.
    sidecar = out_dir / "events.json"
    payload = []
    for ev in events:
        d = str(ev.get('date', ''))
        iso = f"{d[0:4]}-{d[4:6]}-{d[6:8]}" if len(d) >= 8 else ''
        payload.append({
            'date_iso': iso,
            'time': ev.get('time', ''),
            'summary': ev.get('summary', ''),
            'location': ev.get('location', ''),
            'all_day': ev.get('all_day', False),
            'description': (ev.get('description') or '')[:2000],
            # Teilnehmer (ATTENDEE/ORGANIZER). Liefert der Freigabe-Feed keine,
            # bleibt die Liste leer und `vorbereiten.py` nimmt Namen aus dem Titel.
            'attendees': ev.get('attendees', []),
            'status': ev.get('status', ''),
            'uid': ev.get('uid', ''),
            'outlook_uid': ev.get('outlook_uid', ''),
        })
    payload.sort(key=lambda e: (e['date_iso'], e['time']))
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8', newline="\n")
    print(f"Sidecar:     {sidecar}  ({len(payload)} Events, ISO-Datum)")
    print(f"Total events: {len(events)}")
