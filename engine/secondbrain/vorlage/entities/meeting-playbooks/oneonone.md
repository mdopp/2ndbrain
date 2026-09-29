---
type: meeting-playbook
meeting_type: oneonone
label: 1:1 / Jour Fixe
leitfrage: Sind wir beide ausgerichtet — und was braucht die andere Seite von mir?
dauer: 30–60 Min
kadenz: wöchentlich bis zweiwöchentlich
pflicht_output: gegenseitige Zusagen mit Namen und Datum
vorbereitung_vorlauf: 1 Tag
entscheidung_erforderlich: offen
varianten_quelle: orgchart
kernteil:
- Seit letztem Mal
- Erwartungen beidseitig
- Blocker
blocks:
- block: Seit letztem Mal
  anteil: 25
  inhalt: Zusagen aus dem Vortermin auf Erledigung prüfen
- block: Erwartungen beidseitig
  anteil: 35
  inhalt: Was erwartet die andere Seite von mir, das ich nicht geliefert habe — und umgekehrt
- block: Blocker
  anteil: 25
  inhalt: Was hält auf, wer räumt es weg, bis wann
- block: Ausblick
  anteil: 15
  inhalt: Was kommt, wo fehlt Kontext
match:
  priority: 10
  keywords: [jourfix, jour fixe, 1zu1, one on one, oneonone, bilateral, zweiergespraech]
  regex: '\b(?:1\s*[:/-]\s*1|jf|jour[- ]?fixe?)\b'
varianten:
  up:
    marker: Nach oben
    label: Jour Fixe nach oben (Vorgesetzter)
    frage: Welche Entscheidung brauche ich von oben, und was empfehle ich?
    modus: liefern und entscheiden lassen
    agenda_setzt: du
    kernteil: [Status, Entscheidungsbedarf, Risiken und Eskalationen, Ausblick]
    blocks:
    - block: "Status"
      anteil: 20
      inhalt: "3–5 Themen, je ein Satz: on track / Risiko / blockiert"
    - block: "Entscheidungsbedarf"
      anteil: 40
      inhalt: "Konkrete Frage plus deine Empfehlung — nie offene Fragen ohne Vorschlag"
    - block: "Risiken und Eskalationen"
      anteil: 20
      inhalt: "Früh melden, immer mit Lösungsvorschlag"
    - block: "Ausblick"
      anteil: 20
      inhalt: "Was kommt, wo brauchst du Kontext von oben"
  down:
    marker: Nach unten
    label: Jour Fixe nach unten (Direct Report)
    frage: Was hält dich auf, und was kann ich wegräumen?
    modus: zuhören und Hindernisse entfernen
    agenda_setzt: er/sie zuerst, du ergänzt
    kernteil: [Ihre Themen, Blocker, Meine Themen, Entwicklung]
    blocks:
    - block: "Ihre Themen"
      anteil: 40
      inhalt: "Er/sie eröffnet, du hörst zu"
    - block: "Blocker"
      anteil: 25
      inhalt: "Was hält auf, was kannst du wegräumen"
    - block: "Meine Themen"
      anteil: 25
      inhalt: "Priorisierung, Feedback, Kontext von oben weitergeben"
    - block: "Entwicklung"
      anteil: 10
      inhalt: "Nicht jedes Mal — aber regelmäßig"
  peer:
    label: Jour Fixe auf Augenhöhe (Programm-/Bereichs-Lead)
    frage: Wo reiben sich unsere Vorhaben, und wer zieht?
    modus: gegenseitig zuliefern
    agenda_setzt: beide
    kernteil: [Stand beidseitig, Reibungspunkte, Gegenseitige Zusagen]
    blocks:
    - block: "Stand beidseitig"
      anteil: 25
      inhalt: "Was hat sich seit dem letzten Mal auf beiden Seiten bewegt"
    - block: "Reibungspunkte"
      anteil: 35
      inhalt: "Wo konkurrieren Vorhaben um dieselbe Person, dasselbe System, denselben Termin"
    - block: "Gegenseitige Zusagen"
      anteil: 25
      inhalt: "Wer liefert wem was bis wann"
    - block: "Ausblick"
      anteil: 15
      inhalt: "Was kommt auf beide zu"
extract: [entscheidungen, actions, erwartungen, blocker]
---

# 1:1 / Jour Fixe

## Ziel
Zwei Personen richten sich aus: gegenseitige Erwartungen, Prioritäten und
Reibungspunkte klären, bevor sie zu Eskalationen werden.

## Abgrenzung
Ein 1:1 ist **kein Check-in**. Im Check-in wird über einen Arbeitsstrang
berichtet, im 1:1 über die Zusammenarbeit zweier Personen. Wer das 1:1 als
Check-in führt, bekommt einen Statusreport — und Status gehört ins Ticket-Tool.
Deshalb ein eigener Typ, keine Check-in-Variante.

Die drei Richtungen sind Varianten, keine eigenen Typen: das Gerüst ist
identisch, nur Zeitanteile und Modus drehen sich. Die Richtung kommt aus dem
Organigramm (die eigene Personen-Seite, `ich` in `local.config.json`: „Berichtet fachlich an" ⇒ `up`,
„Direct Reports" ⇒ `down`, sonst `peer`) — nicht aus einer Namensliste im Code.

## Leitfragen
- Was erwartet die andere Seite von mir, das ich noch nicht geliefert habe — und umgekehrt?
- Welche Priorität hat sich auf einer Seite verschoben, ohne dass die andere es weiß?
- Gibt es ein Thema, das wir beide vermeiden?
- Was sollte ich wissen, bevor es eskaliert?

## Risiko-Fokus
- Unterschiedliche Annahmen über Zuständigkeit
- Zusagen ohne Termin
- Themen, die nur hier besprochen werden und nirgends dokumentiert sind
- Ein Punkt, der zum dritten Mal auf der Liste steht — das ist das eigentliche Thema

## Gesprächsführung
- ❌ „Gibt es was?" — die andere Seite sortiert dann für dich vor
- ✅ „Was erwartest du von mir, das ich noch nicht geliefert habe?"
- ✅ „Was hat sich bei dir in der Priorität verschoben?"
- ✅ „Gibt es ein Thema, das wir beide umgehen?"
- Nach oben zusätzlich: ✅ „Ich empfehle A. Trägst du das mit?" statt ❌ „Was sollen wir tun?"
- Nach unten zusätzlich: ✅ „Was kann ich wegräumen?" statt ❌ „Wie ist der Stand?"

## Vorbereitung
- [ ] Laufendes Dokument dieser Person durchgehen — die Punkte, die zwischen den Terminen dort hineingeworfen wurden
- [ ] Zusagen aus dem Vortermin auf Erledigung prüfen
- [ ] Nach oben: zu jedem Entscheidungspunkt Optionen **und** deine Präferenz notieren
- [ ] Nach unten: ein konkretes Feedback vorbereiten, positiv oder korrigierend
- [ ] Ein Thema bewusst weglassen, wenn die Zeit knapp ist — lieber drei Punkte geklärt als acht angerissen

## Abbruchkriterium
Nichts auf der Liste außer Status → schriftlich erledigen, Termin zurückgeben.
Das ist kein Ausfall, das ist der Beweis, dass die Taktung stimmt.

## Typischer Fehler
Nach oben: Probleme ohne Lösungsvorschlag. Nach unten: der Termin wird zum
Statusreport.

## Nachbereitung
Aus Mitschrift oder Transkript ziehen:
- **Erwartungen** beider Seiten, wörtlich zugeordnet — wer erwartet was von wem
- **Zusagen** als Action mit Owner und Datum; eine Zusage ohne Datum ist keine
- **Blocker**, die der andere nicht selbst auflösen kann — mit dem, der es kann
- **Themen ohne Abschluss** in den Parkplatz, damit sie beim nächsten Mal oben stehen
Kein Wortprotokoll. Was nur Kontext war, gehört nicht in die Notiz.
