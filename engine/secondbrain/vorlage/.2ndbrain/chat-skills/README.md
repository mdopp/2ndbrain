# Chat-Skills

Rezepte für den Chat im Plugin. Das Plugin rechnet den Chat selbst (auch auf dem Handy); nur der
Frage-Modus „Offene Fragen“ läuft über die Engine (`2ndbrain frage`).
Ein Skill besteht aus:

- `quelle` – welcher Baustein den Ausschnitt liefert. Die Bausteine (im Plugin `src/core/chat.ts`)
  **lesen nur**, was die vorhandenen Skripte schon berechnet haben – hier entsteht
  keine neue Auswertung.
- `ziel` – welcher Bezug nötig ist (`thema`, `person`, `termin` oder `keins`).
  Der Bezug kommt aus der Frage oder aus der aktiven Notiz.
- Rumpf – die Antwortform. Den darfst du frei ändern.

| Skill | quelle | liest (vorhandenes Skript) |
|---|---|---|
| Briefing | termin | Vorbereitung in der Termin-Notiz (`vorbereiten.py`) + Stand der Themen |
| 1:1-Vorbereitung | person | offene Punkte der Person (`aufgaben.py`), Altbestand (`altbestand.py`), Beteiligte (`beteiligte.py`) |
| Nachfassen | nachfassen | überfällige/wartende Punkte (`aufgaben.py`, wie `01_Aufgaben.md`), Altbestand (`altbestand.py`) |
| Stand für … | thema | Stand-Block und Ampel (`stand.py`, `ampel.py`), offene Punkte, Log |
| Was hat sich bewegt | bewegung | Event Log der Themen im Zeitraum |
| Risiken & Entscheidungen | risiken | [RISK]/[DECISION]/[DEADLINE] im Event Log (30 Tage) |
| Bild: Themenbaum | bild-baum | Landkarte (`parent`) + Ampel (`stand.py`) – **Code zeichnet**, kein Modell |
| Bild: Verlauf | bild-verlauf | Event Log des Themas (+ Beschlüsse/Risiken der Unterthemen) als Zeitstrahl |
| Bild: Beteiligte | bild-beteiligte | `beteiligte` (`beteiligte.py`) + offene Punkte (`aufgaben.py`) |
| Bild: Reihen | bild-reihen | Kalender + Zuordnungsregeln (`themen.py`) der nächsten 30 Tage |
| Offene Fragen | fragen | Fragen an Domain Atlas und Systemübersicht (`atlas_vorschlaege.py`) – nur am Desktop, kein Modell |

Bild-Skills antworten ohne Modell in etwa einer Sekunde mit einem ` ```mermaid `-Block,
den Obsidian im Chat zeichnet. Eine freie Bitte („Zeichne das Kundenportal mit Unterthemen“)
landet beim passenden Bild-Skill; alles andere zeichnet das Modell.

Abgrenzung: Diese Skills beantworten nur Fragen und schreiben nichts. Einsortieren
und Nachbereiten macht die Engine (Nachbereiten im Plugin, Automatik). Die Priorisierung der Vorbereitung und die Ampel stammen aus den
Skripten – das Modell formuliert, es bewertet nicht neu.
