---
type: meeting-playbook
meeting_type: projekt
label: Projektarbeit / Sprint
leitfrage: Wie bauen wir es?
dauer: 60–120 Min
kadenz: fest getaktet
pflicht_output: committete Tasks mit Owner und Schätzung
vorbereitung_vorlauf: 1 Tag
entscheidung_erforderlich: nein
kernteil:
- Ziel des Inkrements
- Aufgaben
- Risiken
- Definition of Done
blocks:
- block: "Ziel des Inkrements"
  anteil: 15
  inhalt: "Was am Ende lauffähig ist — ein Satz"
- block: "Aufgaben"
  anteil: 45
  inhalt: "Je Aufgabe: Schätzung, Owner, Abhängigkeit"
- block: "Risiken"
  anteil: 20
  inhalt: "Was das Inkrement kippen kann"
- block: "Definition of Done"
  anteil: 20
  inhalt: "Woran man erkennt, dass es fertig ist"
match:
  priority: 50
  keywords: [projektarbeit, sprint, sprint planning, planning, refinement, grooming, meilenstein, milestone, arbeitssitzung, backlog]
extract: [actions, risiken, schaetzungen, abhaengigkeiten]
---

# Projektarbeit / Sprint

## Ziel
Ein Inkrement planen und verteilen: was gebaut wird, von wem, bis wann, und
woran man erkennt, dass es fertig ist.

## Abgrenzung
Der Unterschied zum Check-in in einem Satz: **im Check-in wird berichtet, im
Projekt-Termin wird gearbeitet.** Wird im Check-in geplant, ist der Termin falsch
geschnitten — dann fehlt entweder ein Projekt-Termin, oder der Check-in ist zu
lang. Umgekehrt: wird im Projekt-Termin nur berichtet, ist er überflüssig.

Der Unterschied zur Abstimmung: hier wird nicht entschieden, **was** wir tun,
sondern **wie** wir es bauen. Kommt die Was-Frage auf, gehört sie in eine
Abstimmung und hier in den Parkplatz.

## Leitfragen
- Was ist am Ende dieses Inkrements lauffähig — nicht „bearbeitet", sondern lauffähig?
- Welche Aufgabe hat noch keinen Owner?
- Welche Abhängigkeit zu einem anderen Team oder System ist ungeklärt?
- Passt die Summe der Schätzungen in die verfügbare Netto-Kapazität?
- Was ist der nächste überprüfbare Meilenstein, und wann?

## Risiko-Fokus
- Aufgabe ohne Owner — die wird nicht gemacht
- Schätzung fehlt oder ist eine Zahl ohne Grundlage
- Abhängigkeit zu einem Team, das nicht im Raum sitzt
- Schnittstelle zu einem System, das parallel abgelöst wird
- Summe der Schätzungen über 100 % der Netto-Kapazität
- Definition of Done fehlt — dann ist am Ende nichts nachweisbar fertig

## Gesprächsführung
- ❌ „Wer macht das?" in die Runde — bekommt Schweigen
- ❌ „Schaffen wir das?" — bekommt ein Ja ohne Substanz
- ✅ „X, übernimmst du das bis zum <Datum>?"
- ✅ „Woran erkennen wir, dass das fertig ist?"
- ✅ „Welche Abhängigkeit ist ungeklärt — und wer klärt sie bis wann?"
- ✅ „Das ist eine Was-Frage. Die nehmen wir in die Abstimmung mit, hier planen wir das Wie."

## Vorbereitung
- [ ] Backlog gepflegt und refined — im Termin wird nicht zum ersten Mal gelesen
- [ ] Offene Aufgaben des letzten Inkrements: erledigt, überfällig oder gestorben
- [ ] Netto-Kapazität für das Inkrement ausrechnen (Urlaub, Support, Betrieb abziehen)
- [ ] Abhängigkeiten zu anderen Teams vorher bilateral ansprechen
- [ ] Definition of Done aus dem Projekt heraussuchen oder neu festlegen

## Abbruchkriterium
Aufgaben ohne Owner → verschieben statt zuweisen „klären wir später". Ein
Inkrement mit unbesetzten Aufgaben ist keine Planung, sondern eine Wunschliste.
Fehlt der Backlog-Stand, wird der Termin zum Refinement umgewidmet und die
Planung vertagt.

## Typischer Fehler
Der Termin wird zur Diskussionsrunde. Zwei Stunden über Architektur geredet,
keine Aufgabe verteilt.

## Nachbereitung
Aus Mitschrift oder Transkript ziehen:
- **Jede committete Aufgabe** als Action mit Owner, Schätzung und Datum. Ohne Owner: nicht committet, gehört in den Parkplatz
- **Abhängigkeiten** mit dem Team oder System, auf das gewartet wird
- **Risiken**, die das Inkrement kippen können, mit Gegenmaßnahme
- **Definition of Done**, falls sie im Termin festgelegt oder geändert wurde — als Beschluss
- Was-Fragen, die aufkamen, in den Parkplatz mit dem Hinweis „gehört in eine Abstimmung"
