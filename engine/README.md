# 2ndBrain-Engine (Python)

Der Teil von 2ndBrain, der am Desktop rechnet: Automatik, Einarbeiten des Eingangs, Vor- und
Nachbereiten von Terminen, Stand je Thema, Glossar, Systemübersicht und der MCP-Server für Claude.
Das Obsidian-Plugin startet sie; man kann sie auch im Terminal nutzen.

```bash
2ndbrain help                      # alle Befehle (oder: python -m secondbrain help)
2ndbrain einrichten                # im Vault-Ordner: fehlende Vorlagen, Pfade, Prüfungen, MCP-Befehl
2ndbrain auto --dry-run            # was die Automatik jetzt täte
```

Die Engine findet den Vault über `VAULT_DIR` (so startet sie das Plugin, so steht es im MCP-Befehl)
oder sucht ab dem aktuellen Ordner aufwärts nach `.2ndbrain/` bzw. `.obsidian/`. Ohne Vault bricht
sie ab, statt irgendwo zu schreiben. Konfiguration und Daten des Vaults liegen in dessen `.2ndbrain/`
(`llm.config.json`, `local.config.json`, `chat-skills/`, `protokoll-vorlage.md`, `daten/`); der Code
enthält keine Namen eines Vaults (`2ndbrain entdrahtung` prüft das).

| Ordner | Inhalt |
|---|---|
| `secondbrain/` | die Module (flach, sie importieren einander über den Namen), Einstieg `befehle.py`; Namen und Begriffe: KONZEPT §19 |
| `secondbrain/vorlage/` | was `einrichten` in einem neuen Vault anlegt, wenn es fehlt |
| `tests/` | Regressionstests – jeder Test baut sich einen eigenen Vault |
| `tools/` | Entwickler-Werkzeuge (Referenzlauf, Entdrahtung, Plugin- und Prompt-Vergleich) – nicht im Paket |

## Installieren

Normalerweise über den Knopf im Plugin. Von Hand, mit dem Python, das die Engine nutzen soll:

```bash
python -m pip install <Wheel aus dem GitHub-Release>     # Nutzung
python -m pip install -e engine                          # Entwicklung, im Code-Repo
```

System-Werkzeuge installiert die Engine nie selbst. Fehlt eins, meldet sie es:

| Werkzeug | Wofür | Installieren |
|---|---|---|
| `tesseract` (+ `deu`, `eng`) | Text aus Bildern (Linux/macOS; Windows nutzt die eingebaute Texterkennung) | `winget` / `brew` / `apt` |
| `pdftoppm` (poppler) | gescannte PDFs ohne Text-Ebene: Seite → Bild → Texterkennung (`nachfuellen.py`) | `winget` / `brew` / `apt` |
| Node.js + `likec4` | LikeC4-Explorer, den das Plugin startet | nodejs.org, dann `npm install likec4` im Modell-Ordner |

## Anhänge und Dokumente → Text (`dokumente.extract_content`)

Ein einziger Einstieg, gibt `(doc_type, text)` zurück; kein Modell für die reine Textgewinnung.
Läuft in `2ndbrain einlesen` (Mails samt Anhängen, Dokumente, Bilder im Eingang) und in
`2ndbrain nachfuellen` (leere Notizen nachfüllen).

| Typ | Funktion | Nutzt |
|---|---|---|
| `.pdf` | `extract_pdf` | `pypdf` (Text-Ebene); ohne Text: `nachfuellen` mit `pdftoppm` + Texterkennung |
| `.pptx` / `.docx` / `.xlsx` | `extract_pptx` / `extract_docx` / `extract_xlsx` | `python-pptx` / `python-docx` / `openpyxl` |
| `.png` / `.jpg` / … | `extract_image_ocr` | Windows: Windows.Media.Ocr (Ausgabe als UTF-8, Umlaute bleiben erhalten); sonst `tesseract -l deu+eng` |
| `.svg`, `.vtt` | `extract_svg`, `extract_vtt` | – |
| `.txt` / `.csv` | `extract_text` | – |

Texterkennung liefert den sichtbaren Text, keine Deutung; die Deutung macht danach das Einarbeiten mit
dem lokalen Modell.

## Prüfen

```bash
2ndbrain selbsttest                          # Verdrahtung, Konventionen, Daten
2ndbrain test                               # Regressionstests (Code-Repo)
2ndbrain plugin-vergleich                   # Plugin und Engine auf dem Vault vergleichen (nur lesend)
2ndbrain referenz --vergleichen <name>      # Verhalten vor/nach einem Umbau
```
