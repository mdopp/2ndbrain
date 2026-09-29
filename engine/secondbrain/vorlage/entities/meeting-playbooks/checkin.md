---
type: meeting-playbook
meeting_type: checkin
label: Check-in
leitfrage: Kommen wir voran?
dauer: 15–30 Min
kadenz: wöchentlich
pflicht_output: Actions mit Owner und Datum
vorbereitung_vorlauf: 1 Tag
entscheidung_erforderlich: offen
kernteil:
- Seit letztem Mal
- Blocker
- Bis nächstes Mal
blocks:
- block: "Seit letztem Mal"
  anteil: 25
  inhalt: "Nur Ergebnisse, kein Tätigkeitsbericht"
- block: "Blocker"
  anteil: 40
  inhalt: "Was steht, wer räumt es weg, bis wann"
- block: "Bis nächstes Mal"
  anteil: 25
  inhalt: "Konkrete Zusagen mit Namen und Datum"
- block: "Änderungen"
  anteil: 10
  inhalt: "Neues aus dem Fachbereich, Scope-Anfragen, Abhängigkeiten"
match:
  priority: 60
  keywords: [checkin, check in, weekly, woechentlich, standup, stand up, daily, statusrunde, regeltermin,
             biweekly, zweiwoechentlich, management update, status update]
varianten:
  weekly:
    label: Weekly (Team)
    frage: Kommen wir diese Woche voran?
    keywords: [weekly, woechentlich]
    dauer: 30–45 Min
    blocks:
    - block: "Fortschritt"
      anteil: 15
      inhalt: "Was ist seit letzter Woche fertig — nur Deliverables"
    - block: "Blocker"
      anteil: 35
      inhalt: "Was steht, wer räumt es weg, bis wann"
    - block: "Nächste Woche"
      anteil: 25
      inhalt: "Konkrete Zusagen mit Namen und Datum"
    - block: "Risiken und Änderungen"
      anteil: 25
      inhalt: "Neues aus dem Fachbereich, Scope-Anfragen, Abhängigkeiten"
extract: [actions, blocker, risiken]
---

# Check-in

## Ziel
Einen Arbeitsstrang entblockieren. Ein Check-in ohne aufgelösten Blocker oder
neue Zusage war überflüssig.

## Abgrenzung
Weekly ist die Team-Variante desselben Typs — größerer Kreis, etwas länger,
gleiche Frage. Kein eigenes Playbook.

Gegen das **1:1**: dort geht es um zwei Personen, hier um einen Arbeitsstrang.
Ein 1:1 als Check-in geführt wird zum Statusreport.

Gegen den **Projekt-Termin**: hier wird berichtet, dort wird gearbeitet. Wird im
Check-in geplant, ist der Termin falsch geschnitten.

## Leitfragen
- Was blockiert genau jetzt, und wer kann es auflösen?
- Welche Zusage aus der letzten Runde ist **nicht** erledigt, und warum?
- Welcher Punkt steht jetzt zum zweiten Mal auf der Liste? Das ist das eigentliche Thema
- Ist die Annahme von letztem Mal noch gültig?
- Wo wartet gerade jemand auf eine Entscheidung von mir?

## Risiko-Fokus
- Blocker, der seit dem letzten Check-in unverändert ist — als Blocker benennen, nicht wiederholen
- Abhängigkeit zu einem Team, das nicht im Raum sitzt
- Entscheidung wird vertagt, obwohl alle Informationen vorliegen
- Stille Umfangserweiterung („machen wir gleich mit")
- Es wurde etwas zugesagt, ohne dass jemand Zeit dafür hat

## Gesprächsführung
- ❌ „Wie läuft's?" — bekommt eine Zusammenfassung, keine Entscheidung
- ❌ „Was ist mit X?" — lädt zum Statusbericht ein
- ✅ „Was blockiert heute, und wer löst es auf?"
- ✅ „X läuft jetzt seit <n> Tagen ohne Abschluss. Was hat Priorität?"
- ✅ „Welche Entscheidung brauchst du von mir, jetzt in diesem Termin?"
- ✅ „Gilt die Annahme von letztem Mal noch?"

## Vorbereitung
- [ ] Board oder Plan **vor** dem Termin aktualisieren — im Termin wird nicht gepflegt
- [ ] Offene Actions der Vorrunde durchgehen: erledigt, überfällig oder gestorben
- [ ] Die zwei bis drei Punkte markieren, die wirklich Diskussion brauchen; der Rest ist Vorlesen und kann schriftlich
- [ ] Teilnehmerkreis prüfen: nur wer beiträgt oder entscheidet

## Abbruchkriterium
Nichts Neues seit dem letzten Mal → schriftlich erledigen, Termin absagen. Ein
Check-in, den man absagen kann, ist ein gut getakteter Check-in.

## Typischer Fehler
Wird zum Statusreport. Alle berichten reihum, niemand wird entblockiert.

## Nachbereitung
Aus Mitschrift oder Transkript ziehen:
- **Blocker** mit dem, der ihn auflöst, und dem Datum. Ein Blocker ohne beides ist nur eine Klage
- **Zusagen** als Action mit Owner und Datum
- **Erledigtes** nur, wenn es eine offene Action von früher schließt — sonst ist es Tätigkeitsbericht und gehört nicht in die Notiz
- **Blocker, die schon beim letzten Mal standen**, ausdrücklich als wiederholt markieren. Diese Wiederholung ist der wichtigste Befund des Formats
- Themen ohne Abschluss in den Parkplatz
