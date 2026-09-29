#!/usr/bin/env python3
"""auspacken.py - Behaelter auspacken: Mail-Anhaenge und ZIP-Archive.

Mail-Anhang und ZIP sind dasselbe Problem: ein Behaelter, dessen Wert im Inhalt
steckt. Beide werden hier nach `inbox/` ausgepackt und laufen danach durch
den **normalen** Dokumenten-Weg (`dokumente.py`) - als waeren sie einzeln
abgelegt worden. Den Mailtext liest mails.py; dieses Modul schreibt nur die
Anhaenge und archiviert danach Mail bzw. ZIP.

Drei Dinge machen den Unterschied zwischen Mehrwert und Muell:

1. **Herkunft.** Jede ausgepackte Datei wird in `.2ndbrain/daten/.provenance.json`
   vermerkt. `dokumente.py` schreibt daraus `parent:` und `source_container:`
   ins Frontmatter der erzeugten Notiz. Ohne das bekommst du "Folie 7" ohne
   Kontext.
2. **Rauschfilter.** Signatur-Logos (`image001.png`, wenige KB, mehrfach
   identisch) wuerden sonst lauter wertlose Notizen erzeugen.
3. **Dedup ueber Inhalts-Hash.** Dasselbe Angebot in fuenf Mails ergibt eine
   Datei, nicht fuenf.

Laeuft als Schritt von `2ndbrain einlesen` (Quelle `containers`) und in der Automatik
(Schritt `mails`) fuer die Anhaenge neuer Mails:
    2ndbrain einlesen --source containers [--dry-run]
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fremdtext
import vault_paths as vp

PROVENANCE = vp.DATA_DIR / ".provenance.json"
SEEN_HASHES = vp.DATA_DIR / ".container_hashes"

# Im Eingang weiterverarbeitbar (dokumente.py, dazu .md und .eml) - alles andere waere ein Waisenkind
USEFUL_SUFFIXES = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls",
                   ".txt", ".csv", ".png", ".jpg", ".jpeg", ".webp", ".bmp",
                   ".svg", ".vtt", ".wtt", ".md", ".eml"}
ARCHIVE_SUFFIXES = {".zip"}

# Signatur-Grafiken: image001.png & Co. unterhalb dieser Groesse
SIGNATURE_NAME = re.compile(r"^(image|oledata|logo|signatur\w*)[-_ ]?\d*\.(png|gif|jpe?g|bmp)$",
                            re.IGNORECASE)
SIGNATURE_MAX_BYTES = 20_000

# ZIP-Sicherheit
ZIP_MAX_MEMBERS = 200
ZIP_MAX_TOTAL_BYTES = 200 * 1024 * 1024
ZIP_MAX_RATIO = 200


def _slug(text: str, limit: int = 48) -> str:
    t = str(text).strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:limit].strip("-") or "datei"


def _load_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_provenance() -> dict:
    return _load_json(PROVENANCE, {})


def record_provenance(entries: dict) -> None:
    data = load_provenance()
    data.update(entries)
    PROVENANCE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def pop_provenance(filename: str) -> dict | None:
    """Herkunft abrufen und entfernen - `dokumente.py` ruft das genau einmal je Datei."""
    data = load_provenance()
    info = data.pop(filename, None)
    if info is not None:
        PROVENANCE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return info


def _seen_hashes() -> set[str]:
    if not SEEN_HASHES.is_file():
        return set()
    return set(SEEN_HASHES.read_text(encoding="utf-8").split())


def _mark_hash(h: str) -> None:
    seen = _seen_hashes()
    if h in seen:
        return
    with SEEN_HASHES.open("a", encoding="utf-8") as fh:
        fh.write(h + "\n")


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def _is_noise(name: str, size: int, inline: bool) -> bool:
    """Signaturbilder und Tracking-Pixel aussortieren.

    Die Groessenschwelle gilt **nur fuer Bilder**: eine winzige `Agenda.txt` aus
    einem Workshop-ZIP ist bedeutungstragend und darf nicht als Rauschen herausfallen.
    """
    suffix = Path(name).suffix.lower()
    if SIGNATURE_NAME.match(Path(name).name) and size <= SIGNATURE_MAX_BYTES:
        return True
    if suffix in IMAGE_SUFFIXES and size < 4096:
        return True                     # Tracking-Pixel, Aufzaehlungszeichen
    if size == 0:
        return True
    return False


def _mail_note_stem(msg) -> str:
    """Genau der Dateiname, den mails.py fuer diese Mail erzeugt - auch wenn mehrere Mails
    mit gleichem Betreff am selben Tag kamen (dann mit Uhrzeit, siehe mails.note_stem)."""
    import mails as ie
    return ie.note_stem(ie.extract_headers(msg), [vp.INBOX_DIR, vp.VAULT])


def _parent_note_for(container: Path, msg=None) -> str:
    """Die Notiz, zu der der Behaelter gehoert (Mail-Notiz bzw. ZIP-Notiz)."""
    if container.suffix.lower() == ".eml":
        # mails.py erzeugt <datum>-<betreff-slug>.md - denselben Namen bilden.
        # Die Aehnlichkeitssuche unten allein griffe bei gleichem Betreff an
        # verschiedenen Tagen ("AW: Portal-Relaunch") die falsche Mail.
        try:
            stem = _mail_note_stem(msg or email.message_from_bytes(container.read_bytes()))
            for d in (vp.INBOX_DIR, vp.VAULT):
                if (d / f"{stem}.md").is_file():
                    return stem
        except Exception:
            pass
        cand = _slug(re.sub(r"^(AW|RE|WG|FWD?)[- ]*", "", container.stem))
        notes = sorted(vp.VAULT.glob("*.md"))
        if vp.INBOX_DIR.is_dir():
            notes += sorted(vp.INBOX_DIR.glob("*.md"))
        for md in notes:
            if cand[:20] and cand[:20] in _slug(md.stem):
                return md.stem
    return ""


def _write_member(data: bytes, base_name: str, date_str: str, dry_run: bool) -> Path | None:
    """Mitglied in den Eingang (`inbox/`) schreiben - dort holt es `dokumente.py` ab."""
    suffix = Path(base_name).suffix.lower()
    stem = _slug(Path(base_name).stem)
    vp.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    dest = vp.INBOX_DIR / f"{date_str}-{stem}{suffix}"
    n = 1
    while dest.exists():
        dest = vp.INBOX_DIR / f"{date_str}-{stem}-{n}{suffix}"
        n += 1
    if dry_run:
        return dest
    if suffix == ".md":
        # Markdown aus einem Anhang ist Fremdtext und landet unveraendert im Vault - keine
        # ausfuehrbaren Codebloecke (dataviewjs). Ohne Fund bleiben die Bytes, wie sie sind.
        text = data.decode("utf-8", errors="replace")
        sicher = fremdtext.entschaerfen(text)
        if sicher != text:
            data = sicher.encode("utf-8")
    dest.write_bytes(data)
    return dest


def unpack_eml(path: Path, *, dry_run: bool = False) -> dict:
    """Anhaenge einer .eml in den Eingang (inbox/) auspacken."""
    stats = {"members": 0, "skipped_noise": 0, "skipped_dup": 0,
             "skipped_unsupported": 0, "bytes": 0}
    prov = {}
    try:
        msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    except Exception as e:
        print(f"  [FEHL] {path.name}: {type(e).__name__}: {e}", file=sys.stderr)
        return stats

    date_str = (re.match(r"^(\d{4}-\d{2}-\d{2})", path.stem) or [None, ""])[1]
    if not date_str:
        try:
            dt = email.utils.parsedate_to_datetime(msg.get("Date"))
            date_str = dt.strftime("%Y-%m-%d")
        except Exception:
            date_str = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")

    parent = _parent_note_for(path, msg)
    stats["parent"] = parent
    seen = _seen_hashes()

    for part in msg.walk():
        cd = part.get_content_disposition()
        if cd not in ("attachment", "inline"):
            continue
        name = part.get_filename()
        if not name:
            continue
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            continue
        if not data:
            continue
        if _is_noise(name, len(data), cd == "inline"):
            stats["skipped_noise"] += 1
            continue
        suffix = Path(name).suffix.lower()
        if suffix not in USEFUL_SUFFIXES and suffix not in ARCHIVE_SUFFIXES:
            stats["skipped_unsupported"] += 1
            continue
        h = hashlib.sha256(data).hexdigest()[:16]
        if h in seen:
            stats["skipped_dup"] += 1
            continue

        dest = _write_member(data, name, date_str, dry_run)
        if dest is None:
            continue
        stats["members"] += 1
        stats["bytes"] += len(data)
        if not dry_run:
            _mark_hash(h)
            seen.add(h)
            prov[dest.name] = {"container": path.name, "container_type": "email",
                               "member": name, "parent": parent,
                               "sha256_16": h, "unpacked_at": datetime.now().isoformat(
                                   timespec="seconds")}
    if prov:
        record_provenance(prov)
    return stats


def unpack_zip(path: Path, *, dry_run: bool = False) -> dict:
    """ZIP in den Eingang (inbox/) auspacken - mit Schutz gegen Zip-Bomben und Traversal."""
    stats = {"members": 0, "skipped_noise": 0, "skipped_dup": 0,
             "skipped_unsupported": 0, "skipped_unsafe": 0, "bytes": 0}
    prov = {}
    date_str = (re.match(r"^(\d{4}-\d{2}-\d{2})", path.stem) or [None, ""])[1] or \
        datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    # Datum aus dem Container-Namen entfernen - `_write_member` setzt es
    # selbst davor, sonst steht es doppelt im Dateinamen.
    container_slug = _slug(re.sub(r"^\d{4}[-_]\d{2}[-_]\d{2}[-_]?", "", path.stem), 32)
    seen = _seen_hashes()

    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        print(f"  [FEHL] {path.name}: {e}", file=sys.stderr)
        return stats

    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > ZIP_MAX_MEMBERS:
            print(f"  [ABBRUCH] {path.name}: {len(infos)} Mitglieder "
                  f"(Grenze {ZIP_MAX_MEMBERS})", file=sys.stderr)
            return stats
        total = sum(i.file_size for i in infos)
        if total > ZIP_MAX_TOTAL_BYTES:
            print(f"  [ABBRUCH] {path.name}: {total/1024/1024:.0f} MB entpackt "
                  f"(Grenze {ZIP_MAX_TOTAL_BYTES//1024//1024} MB)", file=sys.stderr)
            return stats

        for info in infos:
            member = info.filename
            # Path-Traversal und absolute Pfade ablehnen
            pure = Path(member)
            if pure.is_absolute() or ".." in pure.parts or member.startswith(("/", "\\")):
                stats["skipped_unsafe"] += 1
                continue
            if info.compress_size and info.file_size / max(1, info.compress_size) > ZIP_MAX_RATIO:
                stats["skipped_unsafe"] += 1
                continue
            suffix = pure.suffix.lower()
            if suffix in ARCHIVE_SUFFIXES:
                # Verschachtelte Archive nicht weiter aufloesen
                stats["skipped_unsupported"] += 1
                continue
            if suffix not in USEFUL_SUFFIXES:
                stats["skipped_unsupported"] += 1
                continue
            try:
                data = zf.read(info)
            except Exception:
                stats["skipped_unsafe"] += 1
                continue
            if _is_noise(member, len(data), False):
                stats["skipped_noise"] += 1
                continue
            h = hashlib.sha256(data).hexdigest()[:16]
            if h in seen:
                stats["skipped_dup"] += 1
                continue

            # Interne Ordnerstruktur in den Namen uebernehmen: bei einem
            # Workshop-ZIP ist "Gruppe 3/Ergebnis.pptx" bedeutungstragend.
            inner = "-".join(_slug(p, 20) for p in pure.parts[:-1] if p)
            base = f"{container_slug}--{inner + '-' if inner else ''}{pure.stem}{suffix}"
            dest = _write_member(data, base, date_str, dry_run)
            if dest is None:
                continue
            stats["members"] += 1
            stats["bytes"] += len(data)
            if not dry_run:
                _mark_hash(h)
                seen.add(h)
                prov[dest.name] = {"container": path.name, "container_type": "zip",
                                   "member": member, "parent": "",
                                   "sha256_16": h, "unpacked_at": datetime.now().isoformat(
                                       timespec="seconds")}
    if prov:
        record_provenance(prov)
    return stats


def archive_mail(path: Path, note_stem: str, dry_run: bool) -> None:
    """.eml wie mails.py nach archive/emails/YYYY-MM/ verschieben."""
    if dry_run:
        print("      -> wuerde nach archive/emails/YYYY-MM/ verschieben")
        return
    import mails as ie
    ie._archive_source_eml(path, f"{note_stem}.md")


def archive_container(path: Path, dry_run: bool) -> None:
    """Behaelter nach dem Auspacken nach archive/ wegraeumen, damit Root und Eingang
    aufgeraeumt bleiben. Das Original verschwindet erst, wenn die Kopie byte-gleich ist."""
    kind = "emails" if path.suffix.lower() == ".eml" else "archives"
    dest_dir = vp.SOURCES_DIR / kind
    if dry_run:
        print(f"      -> wuerde nach archive/{kind}/ verschieben")
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    n = 1
    while dest.exists():
        dest = dest_dir / f"{path.stem}-{n}{path.suffix}"
        n += 1
    data = path.read_bytes()
    dest.write_bytes(data)
    if dest.read_bytes() == data:
        path.unlink()
    else:
        dest.unlink(missing_ok=True)
        print(f"      [FEHL] Kopie von {path.name} weicht ab - Original bleibt",
              file=sys.stderr)


def run(dry_run: bool = False, keep: bool = False) -> int:
    scan = list(sorted(vp.VAULT.iterdir()))
    if vp.INBOX_DIR.is_dir():
        scan += sorted(vp.INBOX_DIR.iterdir())
    containers = [f for f in scan
                  if f.is_file() and f.suffix.lower() in ({".eml"} | ARCHIVE_SUFFIXES)]
    print(f"Behaelter auspacken — {len(containers)} gefunden"
          + ("   [DRY-RUN]" if dry_run else ""))
    if not containers:
        print("  keine .eml oder .zip im Root")
        return 0

    total = {"members": 0, "skipped_noise": 0, "skipped_dup": 0,
             "skipped_unsupported": 0, "skipped_unsafe": 0, "bytes": 0}
    for c in containers:
        is_mail = c.suffix.lower() == ".eml"
        st = unpack_eml(c, dry_run=dry_run) if is_mail else unpack_zip(c, dry_run=dry_run)
        parent = st.pop("parent", "")
        for k, v in st.items():
            total[k] = total.get(k, 0) + v
        detail = ", ".join(f"{k.replace('skipped_', '−')}={v}"
                           for k, v in st.items() if v and k != "bytes")
        print(f"  {c.name[:56]:58} {detail or 'nichts verwertbares'}")
        if keep:
            continue
        if is_mail:
            # Mails archiviert erst dieser Schritt (mails.py laeuft mit
            # --keep-source) - aber nur, wenn die Mail-Notiz existiert. Sonst
            # waere die Mail weg, ohne je importiert worden zu sein.
            if parent:
                archive_mail(c, parent, dry_run)
            else:
                print("      [WARN] keine Mail-Notiz gefunden - .eml bleibt im Eingang",
                      file=sys.stderr)
        elif st["members"]:
            archive_container(c, dry_run)

    print(f"\n  ausgepackt: {total['members']} Datei(en), "
          f"{total['bytes']/1024/1024:.1f} MB")
    print(f"  uebersprungen: {total['skipped_noise']} Signaturbilder, "
          f"{total['skipped_dup']} Duplikate, "
          f"{total['skipped_unsupported']} nicht verarbeitbar, "
          f"{total.get('skipped_unsafe', 0)} unsicher")
    if total["members"] and not dry_run:
        print("\n  Naechster Schritt: die ausgepackten Dateien werden beim "
              "Dokumenten-Schritt zu Notizen (mit Herkunft im Frontmatter).")
    return 0


def main() -> int:
    args = sys.argv[1:]
    return run(dry_run="--dry-run" in args, keep="--keep" in args)


if __name__ == "__main__":
    sys.exit(main())
