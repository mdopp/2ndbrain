# 2ndBrain

Ein Arbeits-Vault in Obsidian, der mitdenkt: Termine vor- und nachbereiten, Aufgaben und Risiken aus
allen Notizen, der Stand jedes Themas, ein Glossar der eigenen Fachsprache und ein Chat, der nur aus
dem Vault antwortet – mit einem **lokalen** Sprachmodell (llama.cpp oder ein anderer OpenAI-kompatibler
Server im eigenen Netz).

**Die Idee in drei Sätzen.** Wissen gehört zum *Thema*, nicht zum Termin: Jedes Thema hat ein Log
(was war), einen Stand (was gilt jetzt) und offene Punkte (was fehlt, wen frage ich was). Termine sind
der Ort, an dem dieses Wissen entsteht (Nachbereiten zieht Entscheidungen, Aufgaben und Risiken aus der
Mitschrift) und gebraucht wird (Vorbereiten legt Stand, offene Punkte und Fragen vor). Das lokale Modell
formuliert nur – was geschrieben wird, entscheidet der Code, und Personen werden nie geraten.

Die Begriffe und wie sie im Code heißen: [KONZEPT §19](docs/KONZEPT.md#19-begriffe).

| Teil | Ordner | Läuft auf | Was es tut |
|---|---|---|---|
| Obsidian-Plugin | `plugin/` | Desktop und Handy | Heute, Aufgaben- und Risiken-Seiten, Sofortsuche, Nacherfassen, Chat |
| Engine (Python) | `engine/secondbrain/` | Desktop | Automatik: Kalender, Mails, Einarbeiten, Vor- und Nachbereiten, Stand, Glossar; MCP-Server für Claude |
| Entwickler-Werkzeuge | `engine/tools/` | – | Referenzlauf, Entdrahtung, Plugin- und Prompt-Vergleich (nur im Code-Repo) |
| Vorlagen | `engine/secondbrain/vorlage/` | – | was ein neuer Vault braucht: Cockpit-Seiten, Templates, Playbooks, Chat-Rezepte, Protokoll-Vorlage, die Anleitung für Benutzer |
| Konzept | `docs/KONZEPT.md` | – | Aufbau, Regeln, Entscheidungen |

Am Handy liest und erfasst man; gerechnet wird am Desktop. Beide Seiten verbinden sich über die Notizen
selbst – was die Engine schreibt, sieht jedes Gerät.

## Voraussetzungen

- Obsidian ab 1.11.4 und das Community-Plugin **Dataview**
- am Desktop **Python ab 3.10**
- optional: ein lokaler Modell-Server (ohne ihn gibt es Fakten, aber keine Texte), Node.js mit
  `likec4` (Systemübersicht), `tesseract`/`poppler` (Text aus Bildern und gescannten PDFs)

## Installieren

1. In Obsidian das Community-Plugin **BRAT** installieren → „Add beta plugin“ → `mdopp/2ndbrain`.
   (Sobald 2ndBrain in der Liste der Community-Plugins steht, geht es auch direkt dort.)
2. **2ndBrain** einschalten – am Desktop und am Handy.
3. Am Desktop: *Einstellungen → 2ndBrain → Engine* → **Installieren** (holt die zur Plugin-Version
   passende Engine über `python -m pip`), dann **Einrichten**: legt fehlende Ordner, Vorlagen,
   Chat-Rezepte und die Anleitung an (Vorhandenes bleibt), sucht Pfade und zeigt den Befehl für Claude.
4. In den Einstellungen eintragen: Modell-Server und Modell (dazu, wenn gewünscht, ein Prüfmodell für die
   Nachbereitung), dich selbst („Ich“, dein Personen-Slug), den Kalender (iCal-Adresse – sie liegt im
   Obsidian-Schlüsselbund, nicht im Vault).

Wie man damit arbeitet, erklärt die **Anleitung im Vault** (`README.md`, Vorlage:
[engine/secondbrain/vorlage/README.md](engine/secondbrain/vorlage/README.md)) – in Obsidian über das
„?“ in *Heute*, oben in den Einstellungen oder den Befehl „Anleitung: so funktioniert 2ndBrain“.

Nur die Engine, ohne Plugin: `python -m pip install <Wheel aus dem Release>`, dann im Vault-Ordner
`2ndbrain einrichten` (oder `python -m secondbrain einrichten`).

## Aktualisieren

- **Plugin:** wie jedes Obsidian-Plugin – BRAT aktualisiert es selbst.
- **Engine:** Passt ihre Version nicht zum Plugin, sagt es das Plugin; *Engine → Aktualisieren* holt die
  passende. Von Hand: `python -m pip install --upgrade <Wheel der neuen Version>`.
- Deine Notizen, `.2ndbrain/` (Konfiguration, Chat-Rezepte) und Vorlagen, die du geändert hast, bleiben
  unberührt – „Einrichten“ ergänzt nur, was fehlt.

## Claude (MCP)

`2ndbrain einrichten` zeigt den Befehl, etwa
`claude mcp add --scope user 2ndbrain-vault -e VAULT_DIR="<Vault>" -- "<python>" -m secondbrain mcp`.
Der Server liest nur: Termin-Notizen, Themen, Reihen, Glossar, Kontexte, Systeme. Personen-Seiten, die
Seite zu Personalrisiken, der Kalender und `.2ndbrain/` bleiben zu.

Werkzeuge: `search_notes`, `read_note`, `topic_status`, `term_in_vault`, `atlas_evidence`. Protokolle
schreibt das 2ndBrain selbst beim Nachbereiten (nach `.2ndbrain/protokoll-vorlage.md`, in der Sprache
des Termins) – nicht Claude.

## Daten und Netz

- **Modell-Server:** Chat und Engine schicken Ausschnitte aus deinen Notizen an den eingetragenen Server.
  Sonst geht nichts nach außen, es gibt keine Telemetrie.
- **Kalender:** Die iCal-Adresse wirkt wie ein Zugangsschlüssel; sie liegt im Obsidian-Schlüsselbund.
- **MCP:** Was ein Werkzeug liefert, geht an das Modell, das den Server nutzt – bei Claude in die Cloud.

## Entwickeln

```bash
git clone https://github.com/mdopp/2ndbrain
cd 2ndbrain
python -m pip install -e engine     # Engine aus dem Quelltext: jede Änderung gilt sofort
cd plugin
npm install
npm test
npm run build                       # Ziel: <Vault>/.obsidian/plugins/2ndbrain, wenn plugin/.vault den
                                    # Pfad zum Vault enthält (nur lokal), sonst plugin/dist/
```

- Im Plugin unter *Engine-Quelle* `-e <Pfad>/engine` eintragen – dann installiert „Aktualisieren“ aus
  dem Quelltext.
- `2ndbrain test` – Engine-Tests; jeder Test baut sich einen eigenen Vault und fasst keinen echten an.
- `2ndbrain plugin-vergleich` – rechnen Plugin und Engine auf dem eigenen Vault dasselbe? (nur lesend)
- `2ndbrain entdrahtung` – stehen Namen aus dem eigenen Vault im Code?

## Neue Version

`python scripts/version.py 0.10.1` setzt die Version überall (Plugin und Engine erscheinen immer
zusammen). Ein Tag `0.10.1` startet den Release-Ablauf: Tests, Build, Release mit `main.js`,
`manifest.json`, `styles.css` und dem Wheel der Engine.

## Lizenz

MIT – siehe [LICENSE](LICENSE).
