#!/usr/bin/env python3
"""mails.py - Mails (.eml, z. B. aus Outlook) als Markdown-Notizen in den Eingang holen.

Ausgabe: eine Notiz je Mail in inbox/ (Frontmatter, Verlauf, voller Text); die .eml
kommt nach archive/emails/YYYY-MM/. Die Anhaenge packt auspacken.py aus, nicht dieses Modul.
Liegt die Notiz einer Mail schon im Archiv (gleiche Message-ID), wandert die Mail in den
Papierkorb (.trash/doppelte-mails/), statt doppelt eingearbeitet zu werden.
Normalerweise ueber `2ndbrain einlesen` (Quelle `emails`) oder die Automatik (Schritt `mails`).

Usage:
  python -m secondbrain.mails                                    # alle .eml im Vault-Root und in inbox/
  python -m secondbrain.mails --file "AW- Beispielthema.eml"     # process single file
  python -m secondbrain.mails --dir "./my-emls/"                  # process directory
  python -m secondbrain.mails --output-dir "./andere-notizen/"    # custom output dir
  python -m secondbrain.mails --keep-source                      # .eml liegen lassen (danach Anhaenge auspacken)
"""

import sys
import os
import re
import email
import hashlib
import shutil
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
import adressen  # noqa: E402 - Pfad erst gesetzt
import fremdtext  # noqa: E402


# --- Configuration ---
# Mails sind **Quellmaterial**, keine Entities: Root/inbox -> Notiz im Eingang -> Archiv.
import vault_paths as _vp  # noqa: E402

_VAULT = _vp.VAULT
DEFAULT_INPUT_DIR = str(_VAULT)
DEFAULT_OUTPUT_DIR = str(_VAULT / "inbox")


def parse_args():
    """Parse command-line arguments."""
    input_file = None
    input_dir = DEFAULT_INPUT_DIR
    output_dir = DEFAULT_OUTPUT_DIR

    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == '--file' and i + 1 < len(args):
            input_file = args[i + 1]
        elif arg == '--dir' and i + 1 < len(args):
            input_dir = args[i + 1]
        elif arg == '--output-dir' and i + 1 < len(args):
            output_dir = args[i + 1]
        elif arg == '--help':
            print(__doc__)
            sys.exit(0)

    return input_file, input_dir, output_dir


def find_eml_files(input_file, input_dir):
    """Find .eml files to process."""
    files = []

    if input_file:
        files.append(Path(input_file))
    else:
        input_path = Path(input_dir)
        if not input_path.exists():
            print(f"WARNING: Input directory not found: {input_path}", file=sys.stderr)
            return []
        files = sorted(input_path.glob('*.eml'))
        # Eingang: inbox/ ist der kanonische Ablageort; Root bleibt lesbar.
        inbox = input_path / "inbox"
        if inbox.is_dir():
            files = sorted(set(files) | set(inbox.glob('*.eml')))
        if not files:
            print(f"No .eml files found in {input_path} (+ inbox/)", file=sys.stderr)

    return files


def extract_headers(msg):
    """Extract and clean email headers."""
    headers = {
        'from': msg['From'],
        'to': msg['To'],
        'cc': msg.get('CC', ''),
        'subject': msg['Subject'],
        'date': msg['Date'],
        'message_id': msg.get('Message-ID', ''),
        'has_attachment': 'yes' if msg.get('X-MS-Has-Attach') else 'no',
    }
    return headers


def decode_body(msg):
    """Recursively extract text content from email parts."""
    if not msg.is_multipart():
        return extract_single_part(msg)

    plain, html = [], []
    for part in msg.walk():
        cd = part.get_content_disposition()
        if cd and cd in ('attachment', 'inline'):
            continue  # Skip attachments

        content_type = part.get_content_type()
        if content_type == 'text/plain':
            text = extract_single_part(part)
            if text and text.strip():
                plain.append(text)
        elif content_type == 'text/html':
            text = re.sub(r'<[^>]+>', ' ', extract_single_part(part))
            text = re.sub(r'\s+', ' ', text.replace('&nbsp;', ' ')).strip()
            if len(text) > 50:
                html.append(text)

    # HTML ist meist nur die zweite Darstellung desselben Texts.
    return '\n\n'.join(plain or html)


def extract_single_part(part):
    """Text eines Parts - Content-Transfer-Encoding (base64, quoted-printable)
    und Zeichensatz werden dekodiert."""
    try:
        raw = part.get_payload(decode=True)
    except Exception:
        raw = None
    if raw is None:
        payload = part.get_payload()
        return payload if isinstance(payload, str) else str(payload)
    charset = part.get_content_charset() or 'utf-8'
    try:
        return raw.decode(charset, errors='replace')
    except LookupError:
        return raw.decode('utf-8', errors='replace')


def extract_attachments(msg):
    """Extract attachment information from email."""
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            cd = part.get_content_disposition()
            if cd and cd in ('attachment', 'inline'):
                # get_filename() dekodiert RFC 2231, aber keine Encoded-Words
                # ("=?Windows-1252?Q?=DCbersicht.xlsx?=").
                filename = decode_mime_header(part.get_filename())
                if filename:
                    try:
                        decoded = part.get_payload(decode=True)
                        if decoded:
                            attachments.append({
                                'filename': filename,
                                'size': len(decoded),
                                'content_type': part.get_content_type(),
                                'data': decoded,
                            })
                    except Exception:
                        attachments.append({
                            'filename': filename,
                            'size': 0,
                            'content_type': part.get_content_type(),
                            'data': None,
                        })
    return attachments


def extract_participants(headers):
    """Extract person names from email headers.

    `email.utils.getaddresses()` ist der Standardparser fuer RFC-2822-Adresslisten
    und kennt beide Schreibweisen. Ein Komma-Split zerrisse "Nachname, Vorname <email>"
    mitten in der Adresse, und ein einfacher Namens-Regex (`[A-Z][a-z]+`) verloere
    Adressen ohne Klammern oder Namen mit Umlaut/Bindestrich (z.B. "Sönke" oder
    "Muster-Beispiel").
    """
    from email.utils import getaddresses
    participants = set()
    raw_fields = [headers.get(field, '') or '' for field in ('from', 'to', 'cc')]
    for name, addr in getaddresses(raw_fields):
        # Erst nach dem Adress-Split dekodieren: ein Komma im Encoded-Word
        # wuerde den Split sonst zerreissen.
        name = decode_mime_header(name).strip()
        if name:
            participants.add(name)
        elif addr:
            # Kein Anzeigename im Header - aus der Adresse ableiten
            # (z.B. Anna.Berg@firma.example -> Anna Berg).
            local = addr.split('@')[0]
            participants.add(re.sub(r'[.\-_]+', ' ', local).title())
    return sorted(participants)


def company_from_email(addr, internal_domains=None):
    """Firmen-Slug aus der Absender-Domain, oder None fuer interne Adressen
    (Standard: die eigene Organisation, `vault_paths.interne_domains()`).

    `lieferant.example` -> `lieferant`. Erzeugt **keine** Datei - nur einen Vorschlag;
    eine Firma legt man mit `2ndbrain firma-neu` an.
    """
    addr = str(addr or '').strip().lower()
    if '@' not in addr:
        return None
    domain = addr.split('@', 1)[1]
    if internal_domains is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import vault_paths as vp
        internal_domains = vp.interne_domains()
    if domain in internal_domains:
        return None
    return re.sub(r'[^a-z0-9]+', '-', domain.split('.')[0]).strip('-') or None


def extract_thread_summary(body):
    """Extract a thread summary from email body."""
    if not body:
        return ''

    # Split by email separators (e.g., "Von:", "De:", "Date:")
    # This handles reply chains in German/English
    lines = body.split('\n')

    # Find the most recent (top) message
    # In threaded emails, the newest message is at the top
    thread = []
    for line in lines[:20]:  # First 20 lines should contain the newest message
        if line.strip() and not line.startswith(('Von:', 'De:', 'Date:', 'Gesendet:')):
            thread.append(line)
        elif line.strip().startswith(('Von:', 'De:', 'Gesendet:')):
            break

    return '\n'.join(thread).strip()[:500]


def format_date(date_str):
    """Format email date for filename."""
    try:
        dt = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %z')
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d')


def decode_mime_header(value):
    """MIME-kodierte Header dekodieren.

    `msg['Subject']` liefert bei Outlook oft `=?windows-1252?Q?...?=`. Ohne
    Dekodierung landete das roh im Dateinamen, und gefaltete Header braechten
    sogar einen Zeilenumbruch in den Namen.
    """
    if not value:
        return ''
    try:
        from email.header import decode_header, make_header
        text = str(make_header(decode_header(str(value))))
    except Exception:
        text = str(value)
    return re.sub(r'[\r\n\t\x00-\x1f]+', ' ', text).strip()


def slugify_subject(subject):
    """Create a safe slug from subject line."""
    subject = decode_mime_header(subject)
    if not subject:
        return 'no-subject'
    subject = re.sub(r'^\s*(?:re|aw|wg|fwd?|antwort)\s*:\s*', '', subject, flags=re.I)
    slug = re.sub(r'[^a-zA-Z0-9äöüÄÖÜß\s-]', '', subject)
    slug = re.sub(r'\s+', '-', slug.lower())
    slug = re.sub(r'-{2,}', '-', slug).strip('-')[:60].strip('-')
    return slug or 'no-subject'


def _fm_safe(value, limit=400):
    """Header fuer YAML-Frontmatter aufbereiten.

    Gefaltete Header enthalten Tabs und Zeilenumbrueche. Landen die roh im
    Frontmatter, ist das YAML kaputt und die Datei fuer die ganze Pipeline
    unlesbar (`read_frontmatter` liefert {}). Zusaetzlich MIME-dekodieren.
    """
    text = decode_mime_header(value)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text.replace('"', "'")
    return text[:limit]


def _mail_zeit(date_value):
    """HHMM aus dem Date-Header - macht Notiznamen eindeutig."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(str(date_value)).strftime('%H%M')
    except Exception:
        return ''


def _fm_wert(head, key):
    """Wert von `key:` im Frontmatter - mit oder ohne Anfuehrungszeichen. Eingearbeitete Notizen
    schreibt YAML neu; `message_id: <...>` steht dann ohne Anfuehrungszeichen da."""
    m = re.search(rf'^{key}:[ \t]*(.*?)[ \t]*$', head, re.M)
    v = m.group(1) if m else ''
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        v = v[1:-1]
    return v


def _note_kopf(path):
    """Frontmatter-Text einer vorhandenen Notiz ('' wenn nicht lesbar)."""
    try:
        head = Path(path).read_text(encoding='utf-8', errors='replace')[:4000]
    except OSError:
        return ''
    if head.startswith('---'):
        ende = head.find('\n---', 3)
        head = head[:ende] if ende > 0 else head
    return head


def _note_owner(path):
    """(message_id, timestamp) aus dem Frontmatter einer vorhandenen Mail-Notiz."""
    head = _note_kopf(path)
    return _fm_wert(head, 'message_id'), _fm_wert(head, 'timestamp')


_EINGELESEN: dict[str, Path] | None = None


def schon_eingelesen(message_id: str, timestamp: str = '') -> Path | None:
    """Archivierte Notiz, die diese Mail schon einmal eingelesen hat - None, wenn neu. Erkannt an
    der message_id; aeltere Mail-Notizen ohne message_id am Zeitstempel (Date-Header). Notizen im
    Eingang zaehlen nicht: dort ersetzt ein erneuter Import die Notiz (`note_stem`)."""
    global _EINGELESEN
    if _EINGELESEN is None:
        import vault_paths as vp
        _EINGELESEN = {}
        root = vp.MEETINGS_DIR
        for f in sorted(root.rglob("*.md")) if root.is_dir() else []:
            head = _note_kopf(f)
            mid, ts = _fm_wert(head, 'message_id'), _fm_wert(head, 'timestamp')
            if mid:
                _EINGELESEN.setdefault(mid, f)
            elif ts and _fm_wert(head, 'type') == 'email-thread':
                _EINGELESEN.setdefault('date:' + ts, f)
    if message_id and message_id in _EINGELESEN:
        return _EINGELESEN[message_id]
    return _EINGELESEN.get('date:' + timestamp) if timestamp else None


def _beiseite_legen(eml: Path) -> Path:
    """Doppelte Mail nach `.trash/doppelte-mails/` - nichts wird geloescht."""
    import vault_paths as vp
    ziel_dir = vp.VAULT / ".trash" / "doppelte-mails"
    ziel_dir.mkdir(parents=True, exist_ok=True)
    ziel = ziel_dir / eml.name
    n = 2
    while ziel.exists():
        ziel = ziel_dir / f"{eml.stem}-{n}{eml.suffix}"
        n += 1
    shutil.move(str(eml), str(ziel))
    return ziel


def note_stem(headers, dirs):
    """Dateiname (ohne .md) der Notiz zu dieser Mail: <datum>-<betreff>.

    Antworten mit gleichem Betreff am selben Tag bekaemen sonst denselben Namen - die Notizen
    ueberschrieben sich, nur die letzte bliebe, und alle Anhaenge hingen an ihr. Gehoert der
    Name schon einer *anderen* Mail, kommt die Uhrzeit dazu. Dieselbe Mail behaelt ihren Namen
    (erneuter Import ersetzt ihre Notiz) - erkannt an message_id, bei Notizen ohne message_id
    am Zeitstempel. `dirs`: wo Mail-Notizen liegen (Eingang, Root)."""
    base = (f"{format_date(str(headers.get('date') or ''))}-"
            f"{slugify_subject(headers.get('subject') or 'no-subject')}")
    mid = _fm_safe(headers.get('message_id'))
    ts = _fm_safe(headers.get('date'))
    zeit = _mail_zeit(headers.get('date')) or hashlib.sha1((mid or ts).encode()).hexdigest()[:6]
    kandidaten = [base, f"{base}-{zeit}"] + [f"{base}-{zeit}-{n}" for n in range(2, 50)]
    for stem in kandidaten:
        vorhanden = next((Path(d) / f"{stem}.md" for d in dirs if (Path(d) / f"{stem}.md").is_file()), None)
        if vorhanden is None:
            return stem
        n_mid, n_ts = _note_owner(vorhanden)
        dieselbe = (n_mid == mid) if (mid and n_mid) else (bool(ts) and n_ts == ts)
        if dieselbe:
            return stem
    return kandidaten[-1]


def _kopf_zeilen(kopf: dict) -> list[str]:
    """Frontmatter-Zeilen fuer Absender und Empfaenger (adressen.felder) - Listen vollstaendig, je Eintrag
    YAML-sicher."""
    def liste(key, werte):
        return f'{key}: [' + ', '.join(f'"{_fm_safe(w, limit=300)}"' for w in werte) + ']'
    zeilen = [f'von: "{_fm_safe(kopf["von"], limit=300)}"', liste("an", kopf["an"])]
    for key in ("cc", "verteiler"):
        if kopf[key]:
            zeilen.append(liste(key, kopf[key]))
    zeilen.append(liste("teilnehmer", kopf["teilnehmer"]))
    if kopf["rundmail"]:
        zeilen.append("rundmail: true")
    zeilen.append(f"mail_fassung: {adressen.MAIL_FASSUNG}")
    return zeilen


def generate_vault_note(headers, body, participants, attachments, stem=None):
    """Generate vault-friendly Markdown from email data (`stem`: Dateiname aus note_stem)."""
    date_str = format_date(headers.get('date', ''))
    slug = slugify_subject(headers.get('subject', 'no-subject'))
    year_month = date_str[:7]  # YYYY-MM

    # Determine file name
    filename = f"{date_str}-{slug}.md"
    if filename == "--.md":
        filename = f"{date_str}-no-subject.md"
    if stem:
        filename = f"{stem}.md"

    # Extract thread summary
    summary = extract_thread_summary(body)

    # Build markdown
    lines = []
    lines.append('---')
    lines.append(f'slug: "{_fm_safe(slug)}"')
    lines.append(f'type: email-thread')
    lines.append(f'title: "{_fm_safe(headers.get("subject")) or "No Subject"}"')
    lines.append(f'description: "{_fm_safe(headers.get("subject")) or "No Subject"}"')
    lines.append(f'timestamp: "{_fm_safe(headers.get("date"))}"')
    if headers.get('message_id'):
        lines.append(f'message_id: "{_fm_safe(headers.get("message_id"))}"')
    lines.append(f'last_updated: {datetime.now().strftime("%Y-%m-%d")}')
    # Absender und Empfaenger vollstaendig, als Verweise auf die Personenseiten (adressen.py)
    kopf = adressen.felder(headers.get("from") or "", headers.get("to") or "", headers.get("cc") or "")
    lines.extend(_kopf_zeilen(kopf))
    lines.append(f'has_attachment: {headers.get("has_attachment", "no")}')
    lines.append(f'---')
    lines.append('')
    lines.append(f'# {decode_mime_header(headers.get("subject")) or "No Subject"}')
    lines.append('')
    lines.append(f'**Datum:** {date_str}')
    lines.append(f'**Von:** {decode_mime_header(headers.get("from"))}')
    lines.append(f'**An:** {decode_mime_header(headers.get("to"))}')
    if headers.get('cc'):
        lines.append(f'**CC:** {decode_mime_header(headers.get("cc"))}')
    lines.append('')

    if summary:
        # Jede Zeile zitieren und entschaerfen: das ist Mailtext. Eine ungequotete Folgezeile
        # koennte einen Codeblock oeffnen - bis hin zu einem ausfuehrbaren dataviewjs-Block.
        for zeile in fremdtext.entschaerfen(summary[:300]).splitlines():
            lines.append(f'> {zeile}')
        lines.append('')

    if attachments:
        lines.append(f'## 📎 Anhänge ({len(attachments)})')
        lines.append('')
        for att in attachments:
            size_kb = att['size'] / 1024
            lines.append(f'- `{att["filename"]}` ({size_kb:.1f} KB, {att["content_type"]})')
        lines.append('')

    # Full thread
    lines.append('## 💬 Vollständiger Thread')
    lines.append('')
    # Zaun laenger als jede Backtick-Folge im Mailtext: ein ``` in der Mail beendet
    # den Codeblock nicht (sonst liefe dahinter z. B. dataviewjs als Code).
    lines.append(fremdtext.zaun(body))
    lines.append('')

    return filename, '\n'.join(lines)


def process_eml(input_file, output_dir, keep_source=False):
    """Process a single .eml file and generate vault output.

    `keep_source`: die .eml liegen lassen - `2ndbrain einlesen` packt danach die
    Anhaenge aus (auspacken.py) und archiviert die Mail erst dann."""
    print(f"Processing: {input_file}")

    # Bytes lesen: 8bit-Mails in Latin-1/Windows-1252 sind kein gueltiges UTF-8.
    with open(input_file, 'rb') as f:
        raw = f.read()

    # Parse
    msg = email.message_from_bytes(raw)
    headers = extract_headers(msg)
    body = decode_body(msg)
    participants = extract_participants(headers)
    attachments = extract_attachments(msg)

    import vault_paths as vp
    # Schon einmal eingelesen und eingearbeitet (Notiz im Archiv)? Dann nicht noch einmal:
    # sonst stuenden Ereignisse und Aufgaben doppelt im Vault. Die Mail wandert in den Papierkorb.
    frueher = schon_eingelesen(_fm_safe(headers.get('message_id')), _fm_safe(headers.get('date')))
    if frueher is not None:
        ziel = _beiseite_legen(Path(input_file))
        print(f"  = schon eingelesen ({frueher.relative_to(vp.VAULT).as_posix()}) - "
              f"Mail liegt jetzt in {ziel.relative_to(vp.VAULT).as_posix()}")
        return None

    # Generate - eigener Name je Mail (sonst ueberschriebe sich gleicher Betreff am selben Tag)
    dirs = list(dict.fromkeys(Path(p) for p in (output_dir, vp.INBOX_DIR, vp.VAULT)))
    filename, md_content = generate_vault_note(headers, body, participants, attachments,
                                               stem=note_stem(headers, dirs))

    # Write output
    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8', newline="\n") as f:
        f.write(md_content)

    print(f"  → {output_path}")
    print(f"  Participants: {participants}")
    print(f"  Attachments: {len(attachments)}")

    # Quelle archivieren: die .eml darf nicht im Eingang liegen bleiben, sonst
    # meldet das Einarbeiten bei jedem Lauf erneut "erst einlesen" (Endlosschleife).
    if not keep_source:
        _archive_source_eml(Path(input_file), filename)

    return output_path


def _archive_source_eml(eml_path, note_filename):
    """Verarbeitete .eml nach archive/emails/YYYY-MM/ verschieben
    (auch von auspacken.py nach dem Auspacken genutzt)."""
    import re as _re
    import vault_paths as vp
    try:
        if not eml_path.is_file():
            return
        m = _re.match(r"^(\d{4}-\d{2})", note_filename)
        month = m.group(1) if m else "unknown"
        dest_dir = vp.SOURCES_DIR / "emails" / month
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / eml_path.name
        os.replace(eml_path, dest)
        print(f"  → Quelle archiviert: {dest.relative_to(vp.VAULT)}")
    except OSError as e:
        print(f"  WARN: .eml nicht archiviert ({e})", file=sys.stderr)


def main():
    input_file, input_dir, output_dir = parse_args()
    keep_source = '--keep-source' in sys.argv[1:]

    eml_files = find_eml_files(input_file, input_dir)
    if not eml_files:
        print("No .eml files found. Nothing to process.")
        sys.exit(0)

    print(f"Found {len(eml_files)} .eml file(s)")
    print(f"Input: {input_dir}")
    print(f"Output: {output_dir}")
    print(f"{'='*60}")

    results, doppelt = [], 0
    for eml_file in eml_files:
        try:
            result = process_eml(eml_file, output_dir, keep_source=keep_source)
            if result is None:
                doppelt += 1
            else:
                results.append(result)
        except Exception as e:
            print(f"  ERROR processing {eml_file}: {e}", file=sys.stderr)

    print(f"{'='*60}")
    print(f"Processed {len(results)}/{len(eml_files)} files"
          + (f", {doppelt} schon eingelesen (Papierkorb)" if doppelt else ""))
    print(f"Output directory: {output_dir}")


if __name__ == '__main__':
    main()
