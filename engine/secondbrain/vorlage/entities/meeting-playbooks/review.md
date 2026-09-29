---
type: meeting-playbook
meeting_type: review
label: Review / Retrospektive / Abnahme
leitfrage: Was hat funktioniert, was nicht, und woran lag es?
dauer: 60–90 Min
kadenz: nach Phase, Sprint oder Lieferung
pflicht_output: Maßnahmen mit Owner — maximal drei
vorbereitung_vorlauf: 3 Tage
entscheidung_erforderlich: nein
kernteil:
- Ergebnis vs. Zusage
- Was lief gut
- Was lief nicht
- Ursachen
- Maßnahmen
blocks:
- block: "Ergebnis vs. Zusage"
  anteil: 25
  inhalt: "Was war zugesagt, was ist geliefert und abgenommen"
- block: "Beobachtungen"
  anteil: 25
  inhalt: "Was lief gut, was lief nicht — an Fakten, nicht an Eindrücken"
- block: "Ursachen"
  anteil: 30
  inhalt: "Warum es so kam — Ursache, nicht Symptom"
- block: "Maßnahmen"
  anteil: 20
  inhalt: "Maximal drei, jede mit Owner und Datum"
match:
  priority: 30
  keywords: [review, retro, retrospektive, abnahme, lessons learned, nachbetrachtung, postmortem, post mortem, uat]
varianten:
  abnahme:
    label: Abnahme
    frage: Entspricht das Gelieferte der Zusage?
    keywords: [abnahme, freigabe, acceptance, uat]
    entscheidung_erforderlich: ja
    kernteil: [Ergebnis vs. Zusage, Abweichungen, Abnahmeentscheidung, Restpunkte]
    blocks:
    - block: "Ergebnis vs. Zusage"
      anteil: 40
      inhalt: "Abnahmekriterium für Abnahmekriterium durchgehen"
    - block: "Abweichungen"
      anteil: 25
      inhalt: "Was fehlt, was ist anders als vereinbart"
    - block: "Abnahmeentscheidung"
      anteil: 25
      inhalt: "Abgenommen, abgenommen unter Auflagen, oder abgelehnt"
    - block: "Restpunkte"
      anteil: 10
      inhalt: "Was mit Frist nachgereicht wird"
  retro:
    label: Retrospektive
    frage: Wie arbeiten wir besser zusammen?
    keywords: [retro, retrospektive, lessons learned]
    entscheidung_erforderlich: nein
extract: [maßnahmen, actions, ursachen, entscheidungen]
---

# Review / Retrospektive / Abnahme

## Ziel
Gelieferte Arbeit abnehmen oder die Arbeitsweise verbessern — an Fakten, nicht
an Eindrücken. Ohne Maßnahme mit Owner war es eine Klagerunde.

## Abgrenzung
Abnahme und Retrospektive teilen dasselbe Gerüst — beide fragen „was war
zugesagt, was ist passiert, woran lag es". Sie unterscheiden sich im Gegenstand:
die Abnahme prüft das **Ergebnis**, die Retro die **Arbeitsweise**. Deshalb
Varianten, kein zweites Playbook. Die Abnahme braucht eine Entscheidung
(`entscheidung_erforderlich: ja`), die Retro nicht.

## Leitfragen
- Entspricht das Gelieferte der Zusage, oder hat sich der Umfang leise verändert?
- Was ist fertig **und** abgenommen, was nur fertig?
- Welche Ursache steckt hinter dem, was nicht lief — nicht welches Symptom?
- Welche Maßnahme aus dem letzten Review wurde umgesetzt?
- Was würden wir beim nächsten Mal von Anfang an anders aufsetzen?

## Risiko-Fokus
- „Fast fertig" über mehrere Reviews hinweg
- Abnahmekriterien wurden nie festgelegt — dann gibt es nichts zu prüfen
- Maßnahmen ohne Verantwortlichen
- Mehr als drei Maßnahmen: dann passiert keine

## Gesprächsführung
- ❌ „Hat's geklappt?" — bekommt ein Gefühl statt eines Befunds
- ❌ „Was hat euch gestört?" — ohne Ursachenfrage wird es eine Klagerunde
- ✅ „Entspricht das Gelieferte der Zusage, oder hat sich der Umfang verändert?"
- ✅ „Was ist fertig und abgenommen — nicht nur fertig?"
- ✅ „Woran lag das — und was hätte es früher sichtbar gemacht?"
- ✅ „Welche Maßnahme aus dem letzten Review wurde umgesetzt?"

## Vorbereitung
- [ ] Daten und Feedback **vorab** einsammeln — im Termin wird ausgewertet, nicht erhoben
- [ ] Die ursprüngliche Zusage heraussuchen: Umfang, Termin, Abnahmekriterien
- [ ] Maßnahmen des letzten Reviews auf Umsetzung prüfen und das Ergebnis mitbringen
- [ ] Variante `abnahme`: Abnahmekriterien als Liste vorbereiten, Punkt für Punkt abhakbar
- [ ] Prüfen, ob die Runde offen sprechen kann — sonst erst diesen Rahmen klären

## Abbruchkriterium
Ohne psychologische Sicherheit ist eine Retro sinnlos — sie produziert dann
Höflichkeit statt Befunde. Sitzt jemand im Raum, vor dem nicht offen gesprochen
wird, ist der Teilnehmerkreis falsch. Bei der Abnahme: fehlen die
Abnahmekriterien, wird nicht abgenommen, sondern erst festgelegt.

## Typischer Fehler
Klagerunde ohne Maßnahme. Oder: acht Maßnahmen beschlossen, keine umgesetzt.

## Nachbereitung
Aus Mitschrift oder Transkript ziehen:
- **Ergebnis gegen Zusage** — was geliefert wurde, was fehlt, mit Zahl
- **Ursachen**, nicht Symptome. „Testumgebung stand drei Wochen nicht" ist eine Ursache, „es war eng" nicht
- **Maßnahmen** als Action mit Owner und Datum — **maximal drei**. Sind mehr genannt, die drei mit dem größten Hebel nehmen, den Rest in den Parkplatz
- Variante `abnahme`: die **Abnahmeentscheidung** als Beschluss, mit Auflagen und Frist
- Beobachtungen ohne Ursache und ohne Maßnahme gehören nicht ins Protokoll
