---
type: meeting-playbook
meeting_type: abstimmung
label: Abstimmung / Alignment
leitfrage: Worauf einigen wir uns?
dauer: 20–45 Min
kadenz: ad hoc
pflicht_output: eine Festlegung oder ein klarer Eskalationspfad
vorbereitung_vorlauf: 1 Tag
entscheidung_erforderlich: ja
kernteil:
- Sachlage
- Optionen
- Empfehlung
- Beschluss
blocks:
- block: "Sachlage"
  anteil: 20
  inhalt: "Drei Sätze — was ist der Stand, warum jetzt"
- block: "Optionen"
  anteil: 35
  inhalt: "Je Option: Aufwand, Risiko, Konsequenz"
- block: "Empfehlung"
  anteil: 20
  inhalt: "Deine Präferenz mit Begründung"
- block: "Beschluss"
  anteil: 25
  inhalt: "Was gilt, ab wann, wer setzt um"
match:
  priority: 40
  keywords: [abstimmung, alignment, sync, absprache, klaerung, entscheidung, workshop, werkstatt, design session,
             discuss, onboarding]
varianten:
  entscheidend:
    label: Abstimmung (Festlegung)
    frage: Welche Frage schließen wir heute, und wer entscheidet sie?
    entscheidung_erforderlich: ja
    keywords: [abstimmung, entscheidung, klaerung, alignment]
  erarbeitend:
    label: Workshop (ergebnisoffen)
    frage: Was soll am Ende auf dem Papier stehen?
    entscheidung_erforderlich: nein
    keywords: [workshop, werkstatt, design session, onboarding]
    dauer: 2–4 Stunden
    kernteil: [Rahmen und Nicht-Ziele, Erarbeitung, Ergebnis, Offene Punkte]
    blocks:
    - block: "Rahmen und Nicht-Ziele"
      anteil: 15
      inhalt: "Kontext, Ziel, was ausdrücklich nicht Gegenstand ist"
    - block: "Erarbeitung"
      anteil: 55
      inhalt: "Gemeinsame Arbeit mit Moderation"
    - block: "Ergebnis"
      anteil: 20
      inhalt: "Was auf dem Papier steht, wer zustimmt"
    - block: "Offene Punkte"
      anteil: 10
      inhalt: "Was nicht geklärt wurde, und wer es klärt"
extract: [entscheidungen, optionen, actions]
---

# Abstimmung / Alignment

## Ziel
Eine offene Frage zwischen mehreren Beteiligten schließen. Ergebnis ist eine
Festlegung, kein Meinungsbild.

## Abgrenzung
**Dieser Typ ist der gefährlichste.** Wenn er der häufigste in deinem Kalender
ist, ist das ein Warnsignal: „Abstimmung" wird zum Sammelbecken für alles, was
keinen anderen Namen hat.

Eine Abstimmung ohne benennbare Entscheidung ist in Wahrheit eines von zwei
anderen Dingen:

- ein **Workshop** — ergebnisoffen, erarbeitend. Das ist die Variante
  `erarbeitend`, die es deshalb hier gibt und nicht als eigenes Playbook: das
  Gerüst ist dasselbe, nur ohne Beschlusspunkt.
- ein **Info-Termin** — der eine Mail sein sollte. Dafür gibt es hier bewusst
  keine Variante.

Deshalb ist `entscheidung_erforderlich` im Frontmatter der Notiz Pflicht. Das
Feld zwingt zur Klärung **vorab**, nicht im Termin.

## Leitfragen
- Welche Frage wird heute geschlossen, und wer entscheidet sie?
- Welche Varianten liegen auf dem Tisch, und was kostet jede?
- Wer ist von der Festlegung betroffen und heute nicht dabei?
- Was gilt, wenn wir uns nicht einigen?
- Widerspricht die Festlegung einer früheren aus einem anderen Termin?

## Risiko-Fokus
- Runde ohne Entscheidungsbefugnis
- Festlegung ohne die Beteiligten, die sie umsetzen müssen
- Ergebnis widerspricht einer früheren Festlegung in einem anderen Termin
- Der Termin sammelt drei unzusammenhängende Themen ein

## Gesprächsführung
- ❌ „Was meint ihr?" — ergibt ein Meinungsbild, keine Festlegung
- ❌ „Lass uns mal sammeln" — endet ohne Ergebnis
- ✅ „Welche Frage schließen wir heute, und wer entscheidet sie?"
- ✅ „Was kostet jede Variante — Aufwand, Risiko, Konsequenz?"
- ✅ „Was gilt, wenn wir uns nicht einigen?"
- ✅ Variante `erarbeitend`: „Was genau soll am Ende auf dem Papier stehen? Was ist ausdrücklich nicht Gegenstand?"

## Vorbereitung
- [ ] Die Frage in einem Satz aufschreiben. Geht das nicht, ist der Termin noch nicht reif
- [ ] Optionen **vorab** verschicken, je mit Aufwand, Risiko, Konsequenz
- [ ] Deine Empfehlung dazuschreiben — nie Optionen ohne Präferenz vorlegen
- [ ] Prüfen, ob der Entscheider im Termin sitzt
- [ ] Prüfen, ob es zu dieser Frage schon eine Festlegung gibt (`2ndbrain aufloesen`)
- [ ] Variante `erarbeitend`: Vorarbeit so weit treiben, dass im Termin nicht recherchiert wird

## Abbruchkriterium
Der Entscheider fehlt → absagen. Eine Abstimmung ohne Entscheidungsbefugnis
erzeugt nur einen zweiten Termin. Stehen mehr als zwei unabhängige Fragen auf
der Agenda, wird geteilt statt durchgehetzt.

## Typischer Fehler
Sammelbecken für alles. Drei Themen angerissen, keines geschlossen.

## Nachbereitung
Aus Mitschrift oder Transkript ziehen:
- **Den Beschluss** in einem Satz: was gilt, ab wann, wer setzt um. Wurde nichts entschieden, das ausdrücklich festhalten — inklusive des Grundes und des Eskalationspfads
- **Die verworfenen Optionen** mit dem Grund. Das verhindert, dass dieselbe Frage in drei Monaten wieder aufgemacht wird
- **Betroffene, die nicht im Raum waren** — als Action „informieren" mit Owner
- Offene Teilfragen in den Parkplatz
