# 2ndBrain – Obsidian-Plugin

Oberfläche und Lese-/Erfassungsseite von 2ndBrain (Konzept: `docs/KONZEPT.md` §8, §18, Begriffe §19; Installation: `README.md` im Repo).

**Aufteilung:** Das Plugin liest, erfasst und fragt – am Desktop **und am Handy**. Die Python-Engine
(`engine/`, installiert als Paket `2ndbrain`) rechnet und sortiert ein: Kalender, Mails, Einarbeiten, Nachbereiten, Stand, Vorbereitung,
Glossar. Sie läuft nur am Desktop und schreibt ihre Ergebnisse in die Notizen – dort sieht sie jedes Gerät.

| Teil | Wo es läuft | Was es tut |
|---|---|---|
| `src/core/` | überall (Desktop, Handy, Node-Tests) – kein Obsidian, kein Node | Aufgaben, Themen-Log, Risiken, Termine/Themen/Personen, Nacherfassen, Chat (Ausschnitt, Bilder, Modellaufruf) |
| `src/views/`, `main.ts`, `einstellungen.ts`, `konfiguration.ts` | Obsidian (Desktop und Handy) | Heute, Cockpit-Seiten, Sofortsuche, Nacherfassen, Chat, Einstellungen |
| `src/desktop/` | nur Desktop, dynamisch geladen | Python finden, Engine starten (`python -m secondbrain`), LikeC4-Explorer |

Aufgaben, Log, Risiken und Nacherfassen gibt es auch in der Engine (sie braucht sie für ihre eigenen
Schritte); `2ndbrain plugin-vergleich` prüft auf dem Vault, dass beide dasselbe liefern (nur lesend).
Das Lesen und den Chat rechnet immer das Plugin selbst – am Desktop wie am Handy.

## Was es kann (0.11.2)

| Funktion | Handy | Desktop | Modell nötig? |
|---|---|---|---|
| **Heute**: Radar, Termine mit Phase, Thema + Ampel, *Nachfassen*, meine Aufgaben zum Abhaken | ja | ja | nein |
| **Cockpit-Seiten** (`01_Aufgaben.md`, `05_Risiken.md`): Codeblock `2ndbrain aufgaben` / `risiken`, ohne JavaScript in der Notiz | ja | ja | nein |
| **Sofortsuche**: Thema oder Person → Stand-Block, offene Punkte, Fragen | ja | ja | nein |
| **Nacherfassen**: Notizen anhängen, *Fand nicht statt*, überspringen | ja | ja | nein |
| **Nachbereiten**: am Desktop sofort (im Hintergrund, mit Ergebnis und *Rückgängig*); am Handy *Speichern und vormerken* – der Desktop bereitet beim nächsten Lauf der Automatik nach | vormerken | ja | ja |
| **Fragen an den Vault** (Chat): Antworten nur aus dem Vault, mit Quellen; Skills als Knöpfe; **Bilder** (Themenbaum, Verlauf, Beteiligte, Reihen, Kontexte aus dem Domain Atlas mit den Systemen dahinter) zeichnet der Code als Mermaid – ein Klick auf einen Kasten öffnet seine Notiz | ja | ja | ja (Bilder nein) |
| **Fragen über mehrere Schritte**: das Modell schlägt nach – `search`, `read`, `path` (Wege zwischen zwei Punkten über ihre Zwischenstationen), `neighbors` (Umkreis, etwa alle Personen mit Bezug zu einem Thema) über einen Graphen aus Notizen, Domain Atlas und Systemübersicht; dazu `tasks`, `log`, `meetings` (mit Kalender), `query` (Frontmatter) und `atlas` (Nachrichten nach Event/Command/Query, Prozesse, Teams, Domänenmodell) – gefiltert und gezählt vom Code; offene Notiz und Gespräch gehen mit, die Wartezeile zeigt Runde und Werkzeug; passt ein Name auf mehrere (etwa ein Vorname), nennt der Code alle und der Chat fragt zurück, statt zu raten | ja | ja | ja |
| **Anleitung**: eingebaut (`anleitung.md`, steckt in main.js), eigene Ansicht | ja | ja | nein |
| **Offene Fragen** (Kanon, Systemübersicht) im Chat – der einzige Chat-Teil, der die Engine braucht | – | ja | nein |
| **Thema zuordnen**, **Mit wem?**, Liste *Ohne Thema* | – | ja | nein |
| **Automatik**: `2ndbrain auto` alle N Minuten | – | ja | teils |
| **Systemübersicht (LikeC4)** | – | ja | nein |

Termin-Notizen legt die Automatik **heute bis zum nächsten Werktag** an; Privates wird keine Notiz.
Befehle haben bewusst keine vorbelegten Tastenkürzel (*Einstellungen → Tastenkürzel*).

## Netzwerk und Daten

- **Modell-Server**: Chat (Desktop und Handy) und Engine schicken Ausschnitte aus deinen Notizen an den
  eingetragenen OpenAI-kompatiblen Server (z. B. llama.cpp im eigenen Netz). Kein anderer Dienst, keine
  Telemetrie. Unterwegs erreicht das Handy einen Server im Heimnetz über VPN; die Adresse bleibt dieselbe.
- **Kalender**: die iCal-Adresse liegt im Obsidian-Schlüsselbund (je Gerät) und geht nur an die Engine.
- **Handy**: Mit Sync liegt der ganze Vault auf dem Gerät. Was in Ordnern mit Punkt steht (`.2ndbrain/`),
  bringen manche Sync-Dienste nicht mit – deshalb legt das Plugin am Desktop eine Kopie von
  „ich“, Modell-Adresse und Chat-Rezepten in seinen eigenen Daten ab.

## Aktivieren

1. Obsidian → *Einstellungen → Community-Plugins* → „2ndBrain“ einschalten (Desktop und Handy).
2. Am Desktop *Einstellungen → 2ndBrain → Engine*: **Installieren** (passende Engine über `python -m pip`),
   dann **Einrichten** (fehlende Ordner, Vorlagen, Chat-Rezepte; Pfade; Befehl für Claude). Passt die Version
   der Engine nicht mehr zum Plugin (nach einem Update des Plugins), meldet es sich einmal mit „Engine
   aktualisieren“ – ein Klick, oder **Aktualisieren** in den Einstellungen.
3. Automatik-Intervall (Standard 20 min, 0 = aus); **Vault-Konfiguration**
   (Ich, Beschreibung, Modell-Server, Modell, Kanon) – schreibt direkt in `.2ndbrain/*.json`, dieselben
   Dateien, die die Engine liest; **Kalender** im Schlüsselbund; **Systemübersicht**: Modell-Ordner (leer =
   automatisch gefunden), mitstarten, Port.
4. **Python** muss man nicht eintragen: leer = das Plugin sucht selbst (`py`, `python`, `python3`, ab 3.10).

## Entwickeln

```bash
cd plugin
npm install
npm test          # Logik-Tests (node:test)
npm run build     # Typprüfung (strict) + Build nach <Vault>/.obsidian/plugins/2ndbrain/ (Pfad in plugin/.vault),
                  # ohne .vault nach plugin/dist/; npm run build:dist baut immer nach dist/
npm run dev       # Watch-Modus
```

Vergleich mit der Engine auf dem echten Vault (nur lesend): `2ndbrain plugin-vergleich`
(entspricht `SB_VERGLEICH=1 npm test`; die Engine-Seite liefert `engine/tools/plugin_vergleich.py`).
