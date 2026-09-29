#!/usr/bin/env python3
"""dokumente.py - Dokumente und Bilder aus Root und Eingang zu Markdown-Notizen machen (ohne Modell).

Unterstuetzte Formate:
  - PPTX (Folien, Titel, Sprechernotizen)
  - DOCX (Absaetze, Tabellen, Ueberschriften)
  - XLSX (Arbeitsblaetter, Markdown-Tabellen)
  - PDF  (Seitenweiser Text)
  - TXT / CSV (Klartext)
  - SVG  (Textelemente, ohne OCR)
  - VTT / WTT (Teams-Transkripte, deterministisch verdichtet)
  - Bilder (PNG, JPG, JPEG, WEBP, BMP: Windows OCR, sonst tesseract)

Datums-Erkennung:
  1. Regex im Dateinamen (YYYY-MM-DD, YYYYMMDD, DD.MM.YYYY, YYYY_MM_DD)
  2. Fallback: Dateisystem-Aenderungsdatum (st_mtime)

Output:
  Eine standardisierte .md-Notiz in inbox/ (einsortiert wird sie danach von einarbeiten.py);
  die Originaldatei kommt nach `.attachments/<Jahr>/`. Stammt sie aus einer Mail oder einem
  ZIP, steht die Herkunft im Frontmatter (aus auspacken.py). Bleibt der Inhalt leer
  ([OCR]/[WARN]), fuellt nachfuellen.py ihn spaeter nach.

Laeuft in `2ndbrain einlesen` (Quelle `documents`) und in der Automatik fuer Mail-Anhaenge.
"""
import re, sys, subprocess
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fremdtext  # noqa: E402 - Pfad erst gesetzt

# Dokumenten-Parser
try:
    import docx
except ImportError:
    docx = None

try:
    import pptx
except ImportError:
    pptx = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    import pypdf
except ImportError:
    pypdf = None


SUPPORTED_EXTENSIONS = {
    ".pptx", ".ppt",
    ".svg",                      # Text aus Architekturskizzen, ohne OCR
    ".vtt", ".wtt",              # Teams-Transkripte mit Sprecherzuordnung
    ".docx", ".doc",
    ".xlsx", ".xls",
    ".pdf",
    ".txt", ".csv",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp",
}


def detect_file_date(filepath: Path) -> str:
    """Ermittelt das Datum aus Dateiname oder Dateisystem-Metadaten."""
    name = filepath.stem

    # 1. YYYY-MM-DD oder YYYY_MM_DD
    m = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # 2. DD.MM.YYYY
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", name)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    # 3. YYYYMMDD (z.B. 20260913)
    m = re.search(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # 4. Fallback: Dateisystem mtime
    mtime = filepath.stat().st_mtime
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


def extract_pptx(filepath: Path) -> str:
    """Extrahiert Folientitel, Text und Sprechernotizen aus PPTX."""
    if not pptx:
        return "[WARN] python-pptx nicht installiert."
    prs = pptx.Presentation(str(filepath))
    sections = []
    for idx, slide in enumerate(prs.slides, 1):
        slide_lines = [f"### Folie {idx}"]
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    text = paragraph.text.strip()
                    if text:
                        slide_lines.append(f"- {text}")
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                slide_lines.append(f"\n*Sprechernotizen:* {notes}")
        sections.append("\n".join(slide_lines))
    return "\n\n".join(sections)


def extract_docx(filepath: Path) -> str:
    """Extrahiert Absaetze und Tabellen aus DOCX."""
    if not docx:
        return "[WARN] python-docx nicht installiert."
    doc = docx.Document(str(filepath))
    lines = []
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue
        if p.style.name.startswith("Heading 1"):
            lines.append(f"## {txt}")
        elif p.style.name.startswith("Heading 2"):
            lines.append(f"### {txt}")
        elif p.style.name.startswith("Heading"):
            lines.append(f"#### {txt}")
        else:
            lines.append(txt)

    # Tabellen
    for t_idx, table in enumerate(doc.tables, 1):
        lines.append(f"\n#### Tabelle {t_idx}")
        rows_data = []
        for row in table.rows:
            rows_data.append([cell.text.strip().replace("\n", " ") for cell in row.cells])
        if rows_data:
            # Header
            lines.append("| " + " | ".join(rows_data[0]) + " |")
            lines.append("| " + " | ".join(["---"] * len(rows_data[0])) + " |")
            for r in rows_data[1:]:
                lines.append("| " + " | ".join(r) + " |")

    return "\n\n".join(lines)


def extract_xlsx(filepath: Path) -> str:
    """Extrahiert Tabellenblaetter als Markdown-Tabellen aus XLSX."""
    if not openpyxl:
        return "[WARN] openpyxl nicht installiert."
    wb = openpyxl.load_workbook(str(filepath), data_only=True)
    sheets_output = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        # Leere Zeilen filtern
        non_empty_rows = [
            [str(c).strip() if c is not None else "" for c in row]
            for row in rows if any(c is not None and str(c).strip() for c in row)
        ]
        if not non_empty_rows:
            continue

        sheet_lines = [f"### Arbeitsblatt: {sheet_name}"]
        # Maximal 50 Zeilen extrahieren um Token-Budget zu schonen
        sample = non_empty_rows[:50]
        col_count = max(len(r) for r in sample)
        padded = [r + [""] * (col_count - len(r)) for r in sample]

        sheet_lines.append("| " + " | ".join(padded[0]) + " |")
        sheet_lines.append("| " + " | ".join(["---"] * col_count) + " |")
        for r in padded[1:]:
            sheet_lines.append("| " + " | ".join(r) + " |")

        if len(non_empty_rows) > 50:
            sheet_lines.append(f"\n*(... {len(non_empty_rows) - 50} weitere Zeilen gekuerzt)*")

        sheets_output.append("\n".join(sheet_lines))

    return "\n\n".join(sheets_output)


def extract_pdf(filepath: Path) -> str:
    """Extrahiert Text aus PDF-Dateien."""
    if not pypdf:
        return "[WARN] pypdf nicht installiert."
    reader = pypdf.PdfReader(str(filepath))
    pages_text = []
    for idx, page in enumerate(reader.pages, 1):
        txt = page.extract_text() or ""
        txt = txt.strip()
        if txt:
            pages_text.append(f"### Seite {idx}\n{txt}")
    return "\n\n".join(pages_text)


def extract_text(filepath: Path) -> str:
    """Liest einfache Textdateien (.txt, .csv)."""
    return filepath.read_text(encoding="utf-8", errors="replace").strip()


def extract_image_ocr(filepath: Path) -> str:
    """Extrahiert Text aus Bildern (Windows Media OCR auf Windows, tesseract auf Linux/macOS)."""
    import shutil
    if sys.platform == "win32":
        # PowerShell-Script zur Nutzung von Windows.Media.Ocr
        # Ausgabe als UTF-8: sonst schreibt PowerShell in der OEM-Codepage, und jedes Bild mit
        # Umlauten verliert seinen erkannten Text (Lesefehler im Unterprozess).
        ps_script = f'''
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime] | Out-Null
        [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
        [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
        [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null

        $path = [System.IO.Path]::GetFullPath('{filepath.as_posix()}')
        $fileTask = [Windows.Storage.StorageFile]::GetFileFromPathAsync($path)
        $asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }} | Select-Object -First 1
        $file = $asTaskGeneric.MakeGenericMethod([Windows.Storage.StorageFile]).Invoke($null, @($fileTask)).Result

        $streamTask = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
        $stream = $asTaskGeneric.MakeGenericMethod([Windows.Storage.Streams.IRandomAccessStream]).Invoke($null, @($streamTask)).Result

        $decoderTask = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
        $decoder = $asTaskGeneric.MakeGenericMethod([Windows.Graphics.Imaging.BitmapDecoder]).Invoke($null, @($decoderTask)).Result

        $bitmapTask = $decoder.GetSoftwareBitmapAsync()
        $bitmap = $asTaskGeneric.MakeGenericMethod([Windows.Graphics.Imaging.SoftwareBitmap]).Invoke($null, @($bitmapTask)).Result

        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new("de-DE"))
        if (-not $engine) {{
            $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
        }}
        $ocrTask = $engine.RecognizeAsync($bitmap)
        $result = $asTaskGeneric.MakeGenericMethod([Windows.Media.Ocr.OcrResult]).Invoke($null, @($ocrTask)).Result
        Write-Output $result.Text
        '''
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20, check=False
            )
            out = res.stdout.strip()
            if out:
                return out
            return "[OCR] Kein lesbarer Text im Bild erkannt oder Bild ist rein grafisch."
        except Exception as e:
            return f"[OCR-FEHLER] {e}"

    # Linux (ARM/x86) und macOS: Tesseract CLI nutzen falls verfuegbar
    tesseract_cmd = shutil.which("tesseract")
    if tesseract_cmd:
        try:
            res = subprocess.run(
                [tesseract_cmd, str(filepath), "stdout", "-l", "deu+eng"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20, check=False
            )
            out = res.stdout.strip()
            if out:
                return out
            return "[OCR] Kein lesbarer Text im Bild erkannt oder Bild ist rein grafisch."
        except Exception as e:
            return f"[OCR-FEHLER] {e}"

    return "[OCR] Bild archiviert. Auf Linux/macOS: 'sudo apt install tesseract-ocr tesseract-ocr-deu' fuer automatische Bild-Textextraktion."


def extract_svg(filepath: Path) -> str:
    """Text aus SVG - ohne OCR.

    Architekturskizzen tragen ihre Labels als `<text>`-Elemente im XML. Die
    x/y-Koordinaten ergeben Lesereihenfolge und Gruppierung, sodass aus einem
    Diagramm Systemnamen und Nachbarschaften werden. Deutlich genauer als OCR
    auf einem gerasterten Bild.
    """
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(filepath).getroot()
    except Exception as e:
        return f"[WARN] SVG nicht lesbar: {e}"

    items = []
    for el in root.iter():
        if not el.tag.endswith("text") and not el.tag.endswith("tspan"):
            continue
        parts = [(el.text or "")] + [(c.text or "") + (c.tail or "") for c in el]
        txt = re.sub(r"\s+", " ", "".join(parts)).strip()
        if not txt:
            continue
        try:
            x = float(el.attrib.get("x", "0") or 0)
            y = float(el.attrib.get("y", "0") or 0)
        except ValueError:
            x = y = 0.0
        items.append((y, x, txt))

    if not items:
        return "[WARN] SVG ohne Textelemente - vermutlich reine Grafik (Vision-LLM noetig)."

    # Kein Rekonstruieren des Layouts: in dichten Diagrammen liegen Labels
    # 5-10px auseinander, jede Gruppierung verschmilzt alles zu einer
    # unlesbaren Zeile. Ein Label pro Zeile in Dokumentreihenfolge verliert
    # nichts und ist fuer Mensch und Modell brauchbar.
    uniq = []
    for txt in (t for _, _, t in items):
        t = (txt.replace("&lt;", "<").replace("&gt;", ">")
                .replace("&amp;", "&").replace("\u200b", "").strip())
        if t and t not in uniq:
            uniq.append(t)
    return (f"_{len(items)} Textelemente aus der Grafik, "
            f"{len(uniq)} eindeutig (Dokumentreihenfolge)._\n\n"
            + "\n".join(f"- {l}" for l in uniq))


_VTT_SPEAKER = re.compile(r"<v\s+([^>]+)>(.*?)</v>", re.DOTALL)
_VTT_TS = re.compile(r"^(\d{2}:\d{2}:\d{2})[.,]\d{3}\s*-->")
# Teams schreibt vor jeden Block eine Cue-ID wie
# "1dbc525b-9cb6-4167-b160-bad91a17edb0/6-0" - das ist keine Sprechzeile.
_VTT_CUE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:/\S*)?$",
                         re.IGNORECASE)
_VTT_FILLER = re.compile(
    r"^(?:mm+|hm+|ah+|oh+|ja|nein|ok(?:ay)?|genau|gut|so|also|ne|nö|yeah|yep|"
    r"right|okay|uh+|um+|the guns?)[.!?]?$", re.IGNORECASE)


def extract_vtt(filepath: Path) -> str:
    """Teams-/WebVTT-Transkript zu lesbarem Text mit Sprecherzuordnung.

    `<v Anna Muster>Text</v>` liefert, wer etwas gesagt hat - genau das, was
    aus "jemand hat zugesagt" ein "@person hat zugesagt" macht.

    Ein Rohtranskript hat leicht Tausende Sprechzeilen und sprengt jedes
    Kontextfenster. Deshalb wird hier **deterministisch verdichtet**:
    aufeinanderfolgende Zeilen desselben Sprechers werden zusammengefasst,
    Fuellzeilen entfernt, und alle 5 Minuten ein Zeitanker gesetzt.
    """
    try:
        raw = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"[WARN] Transkript nicht lesbar: {e}"

    blocks, ts = [], ""
    for line in raw.splitlines():
        s = line.strip()
        if not s or s == "WEBVTT" or s.isdigit():
            continue
        if _VTT_CUE_ID.match(s):
            continue
        m = _VTT_TS.match(s)
        if m:
            ts = m.group(1)
            continue
        if "-->" in s:
            continue
        for who, txt in _VTT_SPEAKER.findall(s):
            t = re.sub(r"<[^>]+>", "", txt)
            t = re.sub(r"\s+", " ", t).strip()
            if t and not _VTT_FILLER.match(t):
                blocks.append((ts, who.strip(), t))
        if "<v" not in s:
            t = re.sub(r"<[^>]+>", "", s).strip()
            if t and not _VTT_FILLER.match(t):
                blocks.append((ts, "", t))

    if not blocks:
        return "[WARN] Transkript ohne verwertbare Sprechzeilen."

    # Zusammenfassen: gleicher Sprecher hintereinander -> ein Absatz
    merged = []
    for ts_, who, txt in blocks:
        if merged and merged[-1][1] == who:
            merged[-1][2] += " " + txt
        else:
            merged.append([ts_, who, txt])

    speakers = {}
    for _, who, txt in merged:
        if who:
            speakers[who] = speakers.get(who, 0) + len(txt)

    out = []
    if speakers:
        top = sorted(speakers.items(), key=lambda x: -x[1])
        out.append("**Sprecher (nach Redeanteil):** "
                   + ", ".join(f"{w} ({c // 1000}k)" if c >= 1000 else f"{w}"
                               for w, c in top[:12]))
        out.append("")
    out.append(f"_{len(blocks)} Sprechzeilen zu {len(merged)} Abschnitten verdichtet._")
    out.append("")

    last_anchor = ""
    for ts_, who, txt in merged:
        anchor = ts_[:5] if ts_ else ""          # HH:MM
        if anchor and anchor[:4] != last_anchor[:4]:
            out.append(f"\n### {anchor}")
            last_anchor = anchor
        prefix = f"**{who}:** " if who else ""
        out.append(f"- {prefix}{txt}")
    return "\n".join(out)


def extract_content(filepath: Path) -> tuple[str, str]:
    """Extrahiert Inhalt je nach Dateiendung. Gibt (Dateityp, Inhalt) zurueck."""
    ext = filepath.suffix.lower()
    if ext in ALTE_OFFICE:
        raise ValueError(f"altes Office-Format, bitte als {ALTE_OFFICE[ext]} speichern")
    if ext in (".pptx", ".ppt"):
        return "Präsentation", extract_pptx(filepath)
    elif ext in (".docx", ".doc"):
        return "Dokument", extract_docx(filepath)
    elif ext in (".xlsx", ".xls"):
        return "Kalkulationstabelle", extract_xlsx(filepath)
    elif ext == ".pdf":
        return "PDF", extract_pdf(filepath)
    elif ext in (".txt", ".csv"):
        return "Textdatei", extract_text(filepath)
    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        return "Bild / Screenshot", extract_image_ocr(filepath)
    elif ext == ".svg":
        return "Grafik / Diagramm", extract_svg(filepath)
    elif ext in (".vtt", ".wtt"):
        return "Transkript", extract_vtt(filepath)
    return "Unbekannt", ""


def process_inbox_document(filepath: Path, vault_dir: str = ".") -> Path:
    """Verarbeitet ein einzelnes Dokument (Root oder Eingang): Notiz in inbox/, Original
    nach `.attachments/<Jahr>/`."""
    vault = Path(vault_dir)
    file_date = detect_file_date(filepath)
    doc_type, content = extract_content(filepath)
    content = fremdtext.entschaerfen(content)   # Dokumenttext ist Fremdtext

    # Binaerdatei nach `.attachments/<jahr>/` - das ist der in Obsidian
    # konfigurierte Anhang-Ordner.
    year = file_date[:4] if re.match(r"^\d{4}", file_date) else "unsortiert"
    attach_dir = vault / ".attachments" / year
    attach_dir.mkdir(parents=True, exist_ok=True)

    archive_dest = attach_dir / filepath.name
    if archive_dest.exists():
        stem = filepath.stem
        archive_dest = attach_dir / f"{stem}-{datetime.now().strftime('%H%M%S')}{filepath.suffix}"

    # Markdown-Notiz im Eingang (inbox/) anlegen
    stem = filepath.stem
    clean_stem = re.sub(r"^20\d{6}[-_]?", "", stem)
    if clean_stem and stem.startswith(file_date):
        md_filename = f"{stem}.md"
    elif clean_stem:
        md_filename = f"{file_date}-{clean_stem}.md"
    else:
        md_filename = f"{file_date}-{stem}.md"

    safe_title = clean_stem.replace("_", " ").replace("-", " ").title() if clean_stem else filepath.stem
    inbox = vault / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    md_path = inbox / md_filename
    rel_attach = f".attachments/{year}/{archive_dest.name}"

    # Herkunft: stammt die Datei aus einem Behaelter (Mail-Anhang, ZIP)?
    # Ohne diese Zeilen ist eine Anhang-Notiz ein Waisenkind - "Folie 7" ohne
    # die Information, aus welchem Workshop sie kommt.
    prov_lines = []
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from auspacken import pop_provenance
        info = pop_provenance(filepath.name)
    except Exception:
        info = None
    if info:
        prov_lines.append(f'source_container: "{info.get("container", "")}"')
        prov_lines.append(f'container_type: {info.get("container_type", "")}')
        prov_lines.append(f'source_member: "{info.get("member", "")}"')
        if info.get("parent"):
            prov_lines.append(f'parent: "[[{info["parent"]}]]"')
    prov_block = ("\n" + "\n".join(prov_lines)) if prov_lines else ""

    md_content = f"""---
type: meeting
date: {file_date}
source_file: "{archive_dest.name}"
source_type: "{doc_type}"
source_path: "{rel_attach}"{prov_block}
tags: [inbox, document-import]
---
# {safe_title}

![[{rel_attach}|{filepath.name}]]

## Dokumenten-Inhalt
{content}
"""
    md_path.write_text(md_content, encoding="utf-8", newline="\n")

    # Originaldatei verschieben
    filepath.rename(archive_dest)
    print(f"[IMPORT] {filepath.name} ({doc_type}) -> Erzeugt: {md_filename}, Archiviert: {rel_attach}", file=sys.stderr)

    return md_path


# Die Bibliotheken lesen nur die neuen Office-Formate
ALTE_OFFICE = {".ppt": ".pptx", ".doc": ".docx", ".xls": ".xlsx"}
NICHT_LESBAR: list[str] = []   # Dateien des letzten Durchlaufs, die liegen geblieben sind (mit Grund)


def scan_and_convert_inbox(vault_dir: str = ".") -> list[Path]:
    """Scannt `inbox/` und das Vault-Root nach unterstuetzten Dokumenten und konvertiert sie.
    Eine Datei, die sich nicht lesen laesst, bleibt liegen (Warnung, `NICHT_LESBAR`) - sie haelt
    die anderen nicht auf."""
    vault = Path(vault_dir)
    created_notes = []
    NICHT_LESBAR.clear()
    candidates = list(vault.iterdir())
    if (vault / "inbox").is_dir():
        candidates += list((vault / "inbox").iterdir())
    for f in candidates:
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
            # Markdown nicht als Dokument behandeln
            if f.suffix.lower() == ".md":
                continue
            try:
                created_md = process_inbox_document(f, vault_dir)
            except Exception as e:
                neu = ALTE_OFFICE.get(f.suffix.lower())
                grund = f"altes Office-Format, bitte als {neu} speichern" if neu else f"{type(e).__name__}: {e}"
                NICHT_LESBAR.append(f"{f.name} ({grund})")
                print(f"[WARN] {f.name} nicht lesbar ({grund}) - bleibt liegen", file=sys.stderr)
                continue
            created_notes.append(created_md)
    return created_notes


if __name__ == "__main__":
    vault_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    converted = scan_and_convert_inbox(vault_dir)
    if converted:
        print(f"[OK] {len(converted)} Dokument(e) in Markdown-Notizen konvertiert.")
    else:
        print("[INFO] Keine neuen Dokumente (PPTX, DOCX, XLSX, PDF, Bilder) im Root gefunden.")
