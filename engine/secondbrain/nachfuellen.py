#!/usr/bin/env python3
"""nachfuellen.py - Leere Dokumenten-Notizen aus ihren Anhaengen nachfuellen (ohne Modell).

Eine Notiz aus dokumente.py bleibt leer ([OCR]/[WARN] statt Text), wenn beim Einlesen die
Texterkennung fehlte oder ein PDF keinen Text-Layer hat. Dieses Modul liest den Anhang
erneut (Texterkennung wie in dokumente.py, pypdf) und baut den Body neu: Titel, Zitatzeilen,
'## Dokumenten-Inhalt'.

- `archive/meetings/**/*.md` mit '## Dokumenten-Inhalt' noch [OCR]/[WARN]
- Anhang: Bild (Texterkennung) ODER PDF (pypdf; bei 0 Text: pdftoppm -> Bild -> Texterkennung)

Anhaenge liegen unter `.attachments/<Jahr>/` (siehe `dokumente.py`), Pfade aus `vault_paths`.

    2ndbrain nachfuellen          (laeuft auch in `2ndbrain einlesen`, Quelle `refill`)
"""
import sys, re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dokumente import extract_content, extract_image_ocr  # noqa
from pypdf import PdfReader  # noqa
import vault_paths as vp  # noqa

ATTACH_DIR = vp.VAULT / ".attachments"
MEETINGS = vp.MEETINGS_DIR
STUB_MARKERS = ("[OCR]", "[WARN]", "nicht installiert")

def parse_fm(text):
    fm = {}
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return fm
    for line in m.group(1).splitlines():
        mm = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if mm:
            fm[mm.group(1).strip()] = mm.group(2).strip().strip('"').strip("'")
    return fm


def resolve_attachment(src):
    """Findet die reale Anhangs-Datei zu 'source_file'.

    Bei Namenskollisionen tragen Anhaenge ein Suffix wie '-033311', das in 'source_file'
    fehlen kann. Wir probieren:
      1. exakt 'source_file' (direkt unter .attachments/)
      2. 'source_file' mit Suffix (gleiche Basis + '-XXXXXX' + Extension)
      3. case-insensiv
    """
    p = ATTACH_DIR / src
    if p.exists():
        return p
    ext = Path(src).suffix
    stem = Path(src).stem
    # Anhaenge liegen in Jahresordnern '.attachments/<Jahr>/' (siehe dokumente.py) -
    # deshalb rglob statt iterdir.
    candidates = [c for c in ATTACH_DIR.rglob("*") if c.is_file()]
    # Gleiche Basis + '-XXXXXX' Suffix (6 Ziffern) + Extension
    for cand in candidates:
        if cand.suffix != ext:
            continue
        # base endet mit '-XXXXXX' (6 Ziffern) und beginnt mit 'stem'
        m = re.match(rf"^{re.escape(stem)}-(\d+)" + re.escape(ext) + r"$", cand.name)
        if m:
            return cand
    # Case-insensiv Fallback
    for cand in candidates:
        if cand.name.lower() == src.lower():
            return cand
    return None

def ocr_pdf_pages(pdf_path):
    """PDF ohne Text-Layer: Seiten als PNG, dann tesseract."""
    import subprocess, tempfile, os
    tmp = tempfile.mkdtemp()
    try:
        r = subprocess.run(["pdftoppm", "-png", "-r", "200", str(pdf_path), os.path.join(tmp, "p")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return ""
        imgs = sorted(Path(tmp).glob("p-*.png"))
        texts = []
        for im in imgs:
            t = extract_image_ocr(im).strip()
            if t:
                texts.append(t)
        return "\n\n".join(texts)
    finally:
        import shutil; shutil.rmtree(tmp, ignore_errors=True)

def refill_one(md_path):
    text = md_path.read_text(encoding="utf-8")
    if not any(mk in text for mk in STUB_MARKERS):
        return None, "kein_stub"
    fm = parse_fm(text)
    src = fm.get("source_file", "").strip()
    if not src:
        return None, "kein_source_file"
    attach = resolve_attachment(src)
    if attach is None:
        return None, f"anhang_fehlt:{src}"
    ext = attach.suffix.lower()
    content = ""
    if ext == ".pdf":
        # 1) pypdf Text-Layer; 2) falls leer: OCR ueber pdftoppm
        try:
            reader = PdfReader(str(attach))
            pages = [(p.extract_text() or "").strip() for p in reader.pages]
            pages = [p for p in pages if p]
            content = "\n\n".join(pages)
        except Exception:
            content = ""
        if not content:
            content = ocr_pdf_pages(attach)
    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        content = extract_image_ocr(attach).strip()
    else:
        doc_type, content = extract_content(attach)
        if content.startswith("[OCR]") or content.startswith("[WARN]"):
            content = extract_image_ocr(attach).strip() if ext in (".png", ".jpg", ".jpeg") else content
    if not content or content.strip() in ("",) or content.startswith("[OCR]"):
        return None, "ocr_leer"
    # Neu-Body
    title_m = re.search(r"^# (.+)$", text, re.M)
    title = title_m.group(1).strip() if title_m else md_path.stem
    quote_lines = re.findall(r"^> .*$", text, re.M)
    quote_block = "\n".join(quote_lines)
    fm_m = re.match(r"^---\n.*?\n---\n", text, re.S)
    fm_block = fm_m.group(0) if fm_m else ""
    parts = [f"# {title}"]
    if quote_block:
        parts.append(quote_block)
    parts.append("## Dokumenten-Inhalt")
    parts.append("")
    parts.append(content.strip())
    new_text = fm_block + "\n" + "\n\n".join(parts) + "\n"
    md_path.write_text(new_text, encoding="utf-8", newline="\n")
    return len(content), ext

def main():
    results = []
    for md in sorted(MEETINGS.rglob("*.md")):
        status, detail = refill_one(md)
        results.append({"file": md.name, "status": status, "detail": detail})
    ok = [r for r in results if isinstance(r["status"], int) and r["status"] > 0]
    print(f"refilled={len(ok)} total={len(results)}")
    for r in results:
        if not (isinstance(r["status"], int) and r["status"] > 0):
            print(f"  {r['file']}: {r['detail']}")

if __name__ == "__main__":
    main()
