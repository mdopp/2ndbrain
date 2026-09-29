# Meeting-Playbooks — die eine Quelle

Ein Playbook pro Meeting-Typ. **Hier und nirgends sonst** steht, wie ein Termin
vor- und nachbereitet wird.

Gelesen von `playbook.py`; genutzt von `vorbereiten.py` (Vorbereitung),
`nachbereiten.py` (Nachbereitung) und `nachbereiten_modell.py` (Prompt-Bausteine für das
lokale Modell).

## Sechs Typen, keine sieben

| Datei | Leitfrage | Ersetzt |
|---|---|---|
| `oneonone.md` | Sind wir beide ausgerichtet? | jourfix, jourfix-up/-down, programm-jourfix |
| `checkin.md` | Kommen wir voran? | checkin, weekly |
| `abstimmung.md` | Worauf einigen wir uns? | abstimmung, workshop (Variante `erarbeitend`) |
| `review.md` | Was hat funktioniert? | review, retro, abnahme |
| `projekt.md` | Wie bauen wir es? | projekt, sprint |
| `steering.md` | Machen wir weiter, und womit? | steering, monthly, quarterly, halbjahr |
| `other.md` | — | Rückfall, wenn nichts greift |

Varianten statt eigener Typen: `monthly` ist `steering/monatlich`, `workshop`
ist `abstimmung/erarbeitend`, der Jour Fixe nach oben ist `oneonone/up`. Der
Grund steht in jedem Playbook unter `## Abgrenzung`.

## Frontmatter — was der Code liest

```yaml
type: meeting-playbook          # Pflicht, immer dieser Wert
meeting_type: steering          # Pflicht, = Dateiname
label: Steering / Lenkungskreis # Anzeigename
leitfrage: ...                  # ein Satz
dauer: 45–60 Min
kadenz: monatlich bis quartalsweise
pflicht_output: ...             # woran man erkennt, dass der Termin etwas wert war
vorbereitung_vorlauf: 2–3 Tage  # steuert, wie früh vorbereiten.py den Termin aufmacht
entscheidung_erforderlich: ja   # ja | nein | offen — zwingt zur Klärung vorab
kernteil:                       # typspezifische H2-Abschnitte der Notiz, in Reihenfolge
  - Ampel
  - Meilensteine Plan vs. Ist
blocks:                         # Zeitanteile, Summe 100
  - block: "Ampel"
    anteil: 10
    inhalt: "Zeit/Budget/Scope/Qualität — je Farbe und ein Satz"
match:                          # Typ-Erkennung aus dem Titel
  priority: 30                  # kleiner = früher geprüft, erster Treffer gewinnt
  keywords: [steering, lenkungskreis]
  regex: ''                     # optional, hat Vorrang vor keywords
varianten:                      # optional; wählt Blöcke/Zusatzfragen feiner
  monatlich:
    label: Monthly
    frage: Sind wir auf Kurs?
    horizont: 1–3 Monate
    keywords: [monthly, monatlich]
    blocks: [...]               # überschreibt blocks, wenn gesetzt
extract:                        # was die Nachbereitung aus dem Material ziehen MUSS
  - entscheidungen
  - actions
```

Regeln:

- **`match.priority`** entscheidet die Reihenfolge, nicht die Dateisortierung.
  `oneonone` steht vor `checkin`, sonst wird jeder Jour Fixe ein Check-in.
- **Keywords sind kleingeschrieben** und werden gegen den normalisierten Titel
  geprüft (Umlaute aufgelöst, Datumsangaben entfernt — `agenda.normalize_title`).
- **`kernteil`** erzeugt die H2-Abschnitte zwischen `## Agenda` und
  `## Entscheidungen`. Ändert man sie, ändert sich das Skelett neuer Notizen —
  bestehende Notizen bleiben unberührt.
- **Summe der `anteil`** muss 100 sein. `2ndbrain test` prüft das.
- **Blöcke immer im Blockstil, `inhalt` immer in Anführungszeichen.** Die
  Flow-Schreibweise `- {block: X, anteil: 10, inhalt: Text mit, Komma}` ist
  verboten: in einer YAML-Flow-Map beendet das Komma den Wert. Der Text wird
  stillschweigend abgeschnitten und der Rest landet als Geisterschlüssel im
  Dict. Das ist einmal passiert und kostete 56 Einträge. `2ndbrain test` prüft
  seitdem, dass jeder Block genau die Schlüssel `block`, `anteil`, `inhalt` hat.

## Body — was Mensch und Modell lesen

Feste H2-Abschnitte, in dieser Reihenfolge. Fehlt einer, ist er leer — kein Fehler.

| Abschnitt | Inhalt | Wer nutzt es |
|---|---|---|
| `## Ziel` | ein Satz, sonst ist der Termin nicht nötig | Notiz-Kopf, Prompt |
| `## Abgrenzung` | wogegen dieser Typ sich abgrenzt, und warum keine eigene Datei | Mensch |
| `## Leitfragen` | 3–5 Fragen, die vorbereitet werden | `## Vorbereitung` |
| `## Risiko-Fokus` | worauf man im Termin achtet | `## Vorbereitung` |
| `## Gesprächsführung` | ❌ schlechte / ✅ gute Formulierung | `## Vorbereitung` |
| `## Vorbereitung` | Checkliste mit `- [ ]`, in Reihenfolge | `## Vorbereitung` |
| `## Abbruchkriterium` | wann der Termin abgesagt oder verschoben gehört | Prompt, Warnung |
| `## Typischer Fehler` | der eine Fehler, an dem dieser Typ scheitert | Prompt |
| `## Nachbereitung` | was aus Mitschrift/Transkript zu ziehen ist | `nachbereiten.py`-Prompt |

## Bullets, die nur für eine Variante gelten

Ein Playbook beschreibt **alle** Varianten in einem Body. Damit bei Variante
`down` nicht die „Nach oben"-Zeilen in der Notiz landen, gibt es zwei Marken am
Zeilenanfang — `playbook.view()` filtert danach und streift die Marke ab:

```markdown
- Variante `quartal`/`jahr`: Ist die Netto-Kapazität gegengerechnet?
- Nach oben zusätzlich: ✅ „Ich empfehle A. Trägst du das mit?"
```

| Schreibweise | Wann | Voraussetzung |
|---|---|---|
| ``Variante `x`/`y`: …`` | Variantennamen stehen direkt im Text | keine |
| `Nach oben: …` / `Nach unten: …` | Richtung statt Name lesbarer | `marker:` im Frontmatter der Variante |

Gefiltert werden `## Leitfragen`, `## Risiko-Fokus`, `## Gesprächsführung`,
`## Vorbereitung` und `## Nachbereitung`. Bullets ohne Marke gelten immer.
Die Basis-Sicht ohne Variante (`playbook.py --show oneonone`) zeigt alles.

Die Marke muss **am Zeilenanfang** stehen. „Ab Variante `quartal`: …" greift
nicht — das ist einmal durchgerutscht und stand dann auch im Monthly.

## Einheitliches Skelett der Meeting-Notiz

Gilt für **alle** Typen. Nur der Kernteil variiert. Entscheidungen und Actions
haben über alle Typen exakt dieselbe Syntax — das ist der Teil, der später
Auswertung, Dashboard und Wiedervorlage trägt.

```markdown
## Ziel
## Vorbereitung      <- generiert von vorbereiten.py, bei jedem Lauf ersetzt
## Agenda            <- generiert, aber von Hand Geändertes bleibt
<Kernteil aus dem Playbook>
## Meine Notizen     <- Mitschrift, Teams-Zusammenfassung, Transkript
## Entscheidungen
## Actions
## Parkplatz
## Verweise
```

Syntax, die nicht verhandelbar ist (Aufgaben: `.mcp-server/KONZEPT.md` §4.1,
einziger Parser/Renderer `aufgaben.py`):

```markdown
## Entscheidungen
- [E] Was entschieden wurde — Wer entschieden hat — 2026-09-23

## Actions
- [ ] Was zu tun ist — [[person-slug|Name]] · [[thema-slug|Thema]] 📅 2026-10-01 ➕ 2026-09-23
- [ ] ❓ Offene Frage? — an [[person-slug|Name]] · [[thema-slug|Thema]] ➕ 2026-09-23
- [ ] Was zu tun ist — Max (?) · [[thema-slug|Thema]] ➕ 2026-09-23
```

Eine Person, eine Tätigkeit je Zeile. `📅` nur, wenn eine Frist genannt wurde;
`➕` = Datum des Termins; `Name (?)` = Person noch unklar (Rückfrage, nie geraten).
Die Altform `- [ ] Was — @wer — Datum` wird weiterhin gelesen.

## Neues Playbook anlegen

1. Datei `<meeting_type>.md` mit vollständigem Frontmatter anlegen.
2. `match.priority` so wählen, dass der spezifischere Typ vorn steht.
3. `2ndbrain test` — prüft Schema, Anteilsummen und
   Eindeutigkeit der Keywords über alle Playbooks.
