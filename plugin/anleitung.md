# 2ndBrain – so funktioniert dein Vault

2ndBrain nimmt dir die Nacharbeit von Terminen ab. Es liest deinen Kalender, bereitet Termine vor,
macht aus Notizen, Transkripten und Mails Entscheidungen und Aufgaben und hält für jedes Thema fest,
wo es steht. Alles bleibt in diesem Vault; gerechnet wird mit einem Modell auf einem Server, den du
selbst einträgst.

> **Kurz gesagt:** Termine haben Notizen, Notizen werden nachbereitet, Themen wissen, wo sie stehen.
> Deine wichtigste Aufgabe: Jeder vergangene Termin hat Notizen – oder ist übersprungen.

Diese Anleitung öffnest du jederzeit über das **?** in „Heute“, in den Plugin-Einstellungen oder mit
dem Befehl „Anleitung: so funktioniert 2ndBrain“.

## Der Tag mit 2ndBrain

1. **„Heute“ öffnen** – Kalender-Symbol in der linken Leiste oder Befehl „Heute öffnen“.
2. **„Ohne Notizen“ leeren** – für vergangene Termine Notizen nachtragen (✏️) oder den Termin
   überspringen (⏭), wenn es nichts festzuhalten gibt.
3. **Im Termin mitschreiben** – Stichpunkte in der Termin-Notiz oder über ✏️ „Nacherfassen“.
4. **„Speichern und nachbereiten“** – 2ndBrain zieht Entscheidungen, Aufgaben und offene Fragen
   heraus. Das Ergebnis siehst du sofort und kannst es zurücknehmen.
5. **Rückfragen beantworten**, wenn 2ndBrain etwas nicht sicher zuordnen kann (ein Haken genügt).

Den Rest erledigt die **Automatik** am Desktop im Hintergrund (Standard: alle 20 Minuten):
Kalender, Mails, Eingang einsortieren, Termine vorbereiten, Stand der Themen, Glossar, Archiv.

## Die Ansicht „Heute“

Von oben nach unten – in der Reihenfolge, in der man es braucht:

| Abschnitt | Was du siehst | Was du tust |
|---|---|---|
| Kopfzeile | Datum, „Modell bereit“, letzter Lauf der Automatik | ⟳ Automatik jetzt · 🔍 Sofortsuche (Thema oder Person) · **?** diese Anleitung |
| Nachbereitungen | was gerade im Hintergrund nachbereitet wird oder fertig ist | „Ergebnis“ ansehen, bei Bedarf zurücknehmen |
| **Ohne Notizen** | vergangene Termine ohne jede Notiz | ✏️ nachtragen oder ⏭ überspringen. Diese Liste soll leer sein: Ohne Notizen gibt es keine Nachbereitung und keine Fragen. |
| Themen-Radar | Themen mit 🔴 oder 🟡 und dem Grund | Thema öffnen; „Radar“ zeigt alle |
| Meine Aufgaben | deine offenen Punkte, Überfälliges zuerst | direkt hier abhaken; „Alle“ öffnet [[01_Aufgaben]] |
| Termine heute / am nächsten Tag | Uhrzeit, Titel, Phase, Themen mit Ampel, offene Punkte zum Nachfassen | ✏️ Notizen, „Thema wählen“, „Mit wem?“ bei 1:1 |
| Nacharbeit (zugeklappt) | Termine ohne Thema (nächste 14 Tage); Termine mit Notizen, die noch nicht nachbereitet sind | Vorschlag übernehmen (→ Thema), 🏷 Thema wählen, ⊘ kein Thema nötig; ✏️ nachbereiten |

Die **Phase** eines Termins steht als kleines Etikett daneben: *Notizen fehlen*, *nachbereiten*,
*nachbereitet*, *entfallen*, *übersprungen* – oder *vorgemerkt*, wenn am Handy zum Nachbereiten
vorgemerkt wurde.

## Der Weg eines Termins

```
Kalender → Termin-Notiz → vorbereitet → Notizen / Transkript → nachbereitet → eingearbeitet → Archiv
```

| Schritt | Was passiert | Wer |
|---|---|---|
| Kalender | Die Automatik liest deinen Kalender – 30 Tage voraus. Für Reihen ohne Thema fragt „Nacharbeit“ schon jetzt nach. | Automatik |
| Vorbereiten | Kurz vor dem Termin (spätestens am Arbeitstag davor) entsteht die Notiz in `active-meetings/`: Agenda, offene Punkte der Teilnehmer und Themen, letzte Entscheidungen – je nach Termin-Typ (1:1, Abstimmung, Review, Steering …). | Automatik |
| Notizen | Stichpunkte reichen, z. B. „Entscheidung: …“, „Name: Liste liefern bis 2.10.“, „Offen: …“. Transkripte und Teams-Zusammenfassungen zählen auch. | du |
| Nachbereiten | Entscheidungen, Aufgaben (mit Verantwortlichen und Fristen), offene Fragen und Kernpunkte; mit Transkript zusätzlich ein Protokoll nach deiner Vorlage. | du: „Speichern und nachbereiten“ |
| Einarbeiten | Entscheidungen, Aufgaben und Risiken gehen ins Log der betroffenen Themen und zu den Personen. | Automatik |
| Archivieren | Erledigte Termine ziehen nach `archive/meetings/JJJJ-MM/`. Ihre Aufgaben bleiben überall sichtbar. | Automatik |

- **Fand nicht statt?** Im Nacherfassen „Fand nicht statt“ – der Termin heißt dann *entfallen*.
- **Nichts festzuhalten?** ⏭ überspringen (der Hinweis danach bietet „rückgängig“).
- **Unterwegs?** Am Handy „Speichern und vormerken“ – der Desktop bereitet beim nächsten Lauf nach.
- **Stimmt etwas nicht?** Im Ergebnis „Rückgängig machen“ oder Befehl „Nachbereitung dieses Termins
  zurücknehmen“ – das holt auch einen schon archivierten Termin zurück.

### Nachbereiten in zwei Stufen

Das eingestellte **Modell** schreibt einen Entwurf – lange Termine abschnittweise. Ist ein
**Prüfmodell** eingestellt, geht es den Entwurf danach mit dem ganzen Material Abschnitt für Abschnitt
durch: ergänzt, was fehlt, korrigiert Namen, Werte und Fristen, führt Doppeltes zusammen und streicht
Erfundenes. Das dauert einige Minuten je Termin, dafür ist das Ergebnis deutlich vollständiger. Im
Ergebnis steht dann „Geprüft von …“. Klappt die Prüfung nicht, gilt der Entwurf.

## Protokolle und Transkripte

Transkripte, Teams-Zusammenfassungen und fertige Protokolle einfach in `inbox/` legen – als Datei
oder als Notiz. 2ndBrain erkennt Datum und Titel und hängt sie an den passenden Termin:

- **eindeutig** → in die Termin-Notiz (`## Transkript`, `## Teams-Zusammenfassung` oder
  `## Mitschrift`); der Termin wird zum Nachbereiten vorgemerkt, die Datei wandert nach
  `archive/protokolle/`;
- **unklar** → eine Rückfrage mit den passenden Terminen zur Auswahl.

Steht ein Transkript im Termin, schreibt das Modell daraus ein **Protokoll** (`## Protokoll`) nach der
**Protokoll-Vorlage** – in der Sprache des Materials. Die Vorlage bearbeitest du in den Einstellungen
unter „Protokoll-Vorlage → Bearbeiten“. Sie liegt in `.2ndbrain/protokoll-vorlage.md` oder an einem
Ort im Vault, den du dort einträgst (zum Beispiel eine sichtbare Notiz).

## Eingang: Mails und Dokumente

In `inbox/` gehört alles, was noch einsortiert werden muss: Mails (`.eml`), PDF, Word, PowerPoint,
Excel, Bilder, ZIP-Archive. Die Automatik packt aus, macht Notizen daraus (Text oder Texterkennung) und
sortiert sie zu Themen, Personen und Terminen.

Mit dem Modell einsortiert wird erst nach deiner Freigabe: einmal den Probelauf ansehen
(`2ndbrain einarbeiten --probelauf`), dann in `.2ndbrain/local.config.json`
`"einarbeiten": {"automatisch": true}` setzen.

## Rückfragen

Wo 2ndBrain etwas nicht sicher weiß – welche von zwei Personen gemeint ist, zu welchem Termin ein
Protokoll gehört, ob ein Begriff nur ein anderes Wort für einen bekannten ist –, rät es nicht, sondern
fragt: als Karte in `04_Clarifications.md`. **Beantworten:** das Kästchen bei der passenden Antwort
anhaken. Der nächste Lauf der Automatik arbeitet die Antwort ein; erledigte Karten wandern ins Archiv.

## Namen sauber

Transkripte und Teams-Zusammenfassungen schreiben Namen, wie die Spracherkennung sie hört – dieselbe
Person oder dasselbe Produkt in mehreren Schreibweisen. 2ndBrain schreibt in Entscheidungen, Aufgaben,
Protokoll, Themen-Logs, Stand und Glossar den Namen, der auf der Seite der Person oder des Themas steht.
Transkript, Teams-Text, deine eigenen Notizen und Mails bleiben wörtlich.

- **Bekannte Verschreiber** stehen auf der Seite unter der Eigenschaft `schreibweisen` – dort kannst du
  auch selbst welche eintragen.
- **Neue Verschreiber** fragt 2ndBrain nach dem Nachbereiten nach: „Ist ‚X‘ = Y?“ – **A** Verschreiber,
  **B** der neue Name ist richtig (die Seite heißt künftig so), **C** jemand oder etwas anderes (wird
  nicht wieder gefragt).
- **Einmal für den ganzen Vault:** `reports/schreibweisen-review.md` stellt je Seite eine Frage mit allen
  ihren fraglichen Schreibweisen (A alle Verschreiber, B die häufigste ist richtig, C alle lassen – oder
  einzeln ankreuzen) und nennt mögliche doppelte Personenseiten. Ankreuzen genügt, die Automatik arbeitet es
  ein; doppelte Seiten werden zusammengeführt, die zweite landet in `.trash/`. Was du einmal entschieden hast,
  gilt auch für ähnliche Verschreiber derselben Seite.
- **Umlaute und Akzente** entscheidet 2ndBrain ohne Nachfrage: Die Schreibung mit Umlaut oder Akzent gilt
  als richtig („Möller“ statt „Moeller“ oder „Moller“, „Renée“ statt „Renee“). Steht sie nur im Text, heißt
  die Seite künftig so. Bei Personen gleicht 2ndBrain auch Groß-/Kleinschreibung und Bindestriche an; wie
  ein Thema geschrieben wird, entscheidest du in der Liste.
- **Wörter, die immer gleich geschrieben werden** (etwa ein Produktname auch in „…-Team“), stehen in
  `.2ndbrain/local.config.json` unter `"schreibweisen": {"woerter": {"Richtig": ["Falsch", …]}}`.
- **E-Mail-Adressen** (vorname.nachname@ aus Personenseiten, Mails und Kalender) sind die zweitbeste Quelle:
  Schreibt eine Adresse den Namen wie die Variante, heißt die Seite künftig so; schreibt sie ihn wie die
  Seite, ist die Variante ein Verschreiber – ebenfalls ohne Nachfrage.
- Alte Einträge bereinigt die Automatik erst nach deiner Freigabe (`"schreibweisen": {"bereinigen": true}`
  in `.2ndbrain/local.config.json`). Was sich ändern würde, zeigt vorher
  `2ndbrain schreibweisen --bereinigen --vorschau`. Jede geänderte Datei wird vorher in `.trash/` gesichert.

## Themen und Reihen

Themen (`entities/projects/`) sind das Gedächtnis des Vaults. Jedes hat eine Beschreibung, einen
**Stand** (die Lage in wenigen Sätzen, von der Automatik aktuell gehalten), eine **Ampel** und ein
**Log** mit allen Entscheidungen, Aufgaben und Risiken aus den Terminen. Themen können Unterthemen
haben.

- **Termin ohne Thema?** Unter „Nacharbeit“ schlägt 2ndBrain eines vor – auch „neu aus dem Kanon“,
  wenn ein passender Bereich des fachlichen Modells noch kein Thema hat. Bei Reihen gilt die Wahl für
  alle Termine der Reihe.
- **Reihen** (`entities/forums/`) sind wiederkehrende Termine mit einem Hauptthema. Einzelne Punkte
  landen trotzdem beim Thema, zu dem sie gehören.
- **[[00_Themen-Radar.base|Themen-Radar]]** zeigt alle Themen mit Ampel auf einen Blick.
- **Stand von Hand auffrischen:** Befehl „Stand dieses Themas aktualisieren“ in der Themen-Notiz.

## Glossar und Kanon

Das [[07_Glossar]] sammelt die Fachbegriffe, die in deinen Notizen vorkommen – mit Langform,
Erklärung und Fundstellen. Ist ein **Kanon** eingestellt (ein fachliches Modell, zum Beispiel ein
Domain Atlas oder eine einfache YAML-Datei), dient er als Wortschatz: Seine Begriffe, Bereiche und Teams
stehen im Glossar, Termine und Themen werden danach zugeordnet. Taucht in den Notizen ein wichtiger
Begriff auf, der im Kanon fehlt, schlägt 2ndBrain eine Erweiterung vor – als Rückfrage.

## Aufgaben und Risiken

- [[01_Aufgaben]] – alle offenen Punkte: deine unter „Meine Aufgaben“, die anderer unter
  „Nachfassen“. Bei einem Termin mit der Person stehen sie direkt am Termin.
- Abhaken geht in „Heute“, in der Aufgabenliste oder in der Notiz selbst.
- [[05_Risiken]] – Risiken aus den Logs der Themen; aktiv ist, was in den letzten 30 Tagen erwähnt wurde.

## Chat: Fragen an den Vault

Sprechblase in der linken Leiste oder Befehl „Fragen an den Vault (Chat)“. Die Antworten kommen nur
aus deinem Vault, mit Links zu den Quellen.

- **Bezug:** Die offene Notiz ist automatisch der Bezug, ihr Inhalt geht mit; ✕ fragt ohne sie.
- **Gespräch:** Nachfragen („und wer kümmert sich darum?“) verstehen die vorigen Antworten – etwa die
  letzten 3–4k Token des Gesprächs gehen mit. „Neues Gespräch“ fängt von vorn an.
- **Nachschlagen:** Reicht das Vorbereitete nicht, schlägt der Chat selbst nach – in allem, was der
  Vault weiß, auch im Domain Atlas und in der Systemübersicht: suchen, lesen, **Wege** zwischen zwei
  Punkten („Wie hängen das Kundenportal und das Lagersystem zusammen?“ – die Stationen dazwischen sind
  die Antwort) und der **Umkreis** eines Punkts („Wer ist alles betroffen, wenn das Altsystem abgelöst
  wird?“). Dazu filtert er wie die Übersichten: **Aufgaben** („Was ist bei Anna überfällig?“), **Log**
  („Welche Beschlüsse gab es seit dem 15.09. zum Portal?“), **Termine** mit dem Kalender („Welche Termine
  habe ich nächste Woche zum Portal?“) und **Felder** der Notizen („Welche Systeme haben keinen Owner?“) –
  die Zahlen rechnet der Code. Den **Domain Atlas** fragt er wie dessen eigener Agent: Nachrichten nach
  Event, Command oder Query samt Sender, Empfänger und Owner, Prozesse mit ihren Schritten, Teams mit ihren
  Kontexten und das Domänenmodell eines Kontexts (Fachobjekte mit Stereotyp und Relationen). Die Wartezeile zeigt Runde für Runde, welches Werkzeug er gerade
  aufruft; unter der Antwort steht, was er nachgeschlagen hat (anklickbar) und wie viele Runden es
  waren. Das dauert meist 5–20 Sekunden, Bilder weiterhin etwa eine.
- **Vorlagen ▾:** fertige Rezepte – Briefing für einen Termin, 1:1-Vorbereitung, Nachfassen, Stand
  eines Themas, Was hat sich bewegt, Risiken & Entscheidungen – und Bilder (Themenbaum, Verlauf,
  Beteiligte, Reihen), die ohne Modell in etwa einer Sekunde gezeichnet werden.
- **Größer / kleiner:** Der Chat sitzt klein in der Seitenleiste oder groß neben der Notiz; das
  Gespräch bleibt dabei erhalten.
- Die Rezepte liegen in `.2ndbrain/chat-skills/` und lassen sich anpassen.

## Am Handy

Lesen, abhaken, nacherfassen und den Vault fragen geht überall. Nachbereiten, Einsortieren und die
Automatik laufen am Desktop: Am Handy heißt der Knopf „Speichern und vormerken“, der Desktop erledigt
es beim nächsten Lauf. Unterwegs erreicht das Handy den Modell-Server zum Beispiel über VPN.

## Einstellungen

| Einstellung | Wofür |
|---|---|
| Anleitung | öffnet diese Seite |
| Python, Engine | Die Engine rechnet am Desktop. „Installieren / Aktualisieren“ nimmt das Engine-Paket, das dem Plugin beiliegt (Abhängigkeiten kommen aus dem Internet); lehnt das Python des Systems ab (am Mac mit Homebrew), bekommt die Engine eine eigene Umgebung in `~/.2ndbrain/venv`. Python sucht das Plugin auch in Homebrew, python.org und pyenv – sonst den Pfad eintragen, etwa `/opt/homebrew/bin/python3`. „Einrichten“ prüft den Vault und legt Fehlendes an – auch diese Anleitung. |
| Automatik alle … Minuten | Lauf im Hintergrund; 0 = aus |
| Ich | deine Personenseite – trennt „Meine Aufgaben“ von „Nachfassen“ |
| Worum es in diesem Vault geht | ein Satz, der den Modellen den Rahmen gibt |
| Modell-Server, Modell | ein OpenAI-kompatibler Server (z. B. llama.cpp); das Modell wählst du aus der Liste des Servers. Chat und Entwurf nutzen es. |
| Prüfmodell (Nachbereitung) | die zweite Stufe (siehe oben); leer = keine Prüfung |
| Protokoll-Vorlage | wo die Vorlage liegt – und „Bearbeiten“ |
| Kanon | das fachliche Modell (Domain Atlas oder YAML-Datei) |
| Kalender | die iCal-Adresse; sie liegt im Obsidian-Schlüsselbund, nicht im Vault |
| Systemübersicht (LikeC4) | Ordner des Systemmodells, Start mit Obsidian |

## Sicherheit und Vertrauen

- Notizinhalte gehen nur an den Modell-Server, den du einträgst – trag nur einen ein, dem du deine
  Notizen anvertraust.
- Die Kalender-Adresse wirkt wie ein Schlüssel. Sie liegt im Schlüsselbund dieses Geräts.
- 2ndBrain löscht nichts endgültig: Aussortiertes landet in `.trash/`, Nachbereitungen lassen sich
  zurücknehmen.
- Wo es unsicher ist, fragt es, statt zu raten.
- Die Anbindung an Claude (optional, über MCP) sieht nur Termine, Themen, Reihen, Glossar, Kontexte
  und Systeme – keine Personenseiten und keine Konfiguration.

## Wo was liegt

| Ordner / Seite | Inhalt |
|---|---|
| `inbox/` | Eingang: Mails, Dokumente, Transkripte, Protokolle |
| `active-meetings/` | Termin-Notizen, die anstehen oder noch offen sind |
| `archive/` | erledigte Termine (`meetings/JJJJ-MM/`), eingearbeitete Quellen, verdichtete Themen-Historie |
| `entities/projects/` | Themen |
| `entities/forums/` | Termin-Reihen |
| `entities/people/`, `teams/`, `companies/` | Personen, Teams, Firmen |
| `entities/glossary/`, `contexts/`, `systems/` | Begriffe, fachliche Kontexte, Systeme |
| `entities/meeting-playbooks/` | Termin-Typen: was Vor- und Nachbereitung je Typ tun |
| `reports/` | Berichte und Vorschlagslisten |
| `00_…` bis `07_…` | Cockpit: Themen-Radar, Aufgaben, Rückfragen, Risiken, Glossar |
| `.2ndbrain/` | Konfiguration (Modell, Kanon, Protokoll-Vorlage, Chat-Rezepte) und Daten dieses Vaults; in Obsidian unsichtbar, die Einstellungen schreiben hinein |

## Befehle

In der Befehlspalette (Strg/Cmd + P), alle mit „2ndBrain:“ davor:

- Heute öffnen · Fragen an den Vault (Chat) · Sofortsuche: Thema oder Person · Anleitung: so
  funktioniert 2ndBrain
- Diesen Termin nacherfassen / nachbereiten · Thema für diesen Termin festlegen · Nachbereitung dieses
  Termins zurücknehmen
- Stand dieses Themas aktualisieren · Automatik jetzt ausführen · Systemübersicht öffnen (LikeC4)
