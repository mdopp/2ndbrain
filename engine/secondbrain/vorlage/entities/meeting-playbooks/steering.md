---
type: meeting-playbook
meeting_type: steering
label: Steering / Lenkungskreis
leitfrage: Machen wir weiter, und womit?
dauer: 45–60 Min (Quartal, Halbjahr, Jahr deutlich länger)
kadenz: monatlich bis quartalsweise
pflicht_output: Beschlüsse im Protokoll, jeder mit Entscheider und Datum
vorbereitung_vorlauf: 3 Tage
entscheidung_erforderlich: ja
kernteil:
- Ampel
- Meilensteine Plan vs. Ist
- Entscheidungsvorlagen
- Top-Risiken
blocks:
- block: "Ampel"
  anteil: 10
  inhalt: "Zeit / Budget / Scope / Qualität — je eine Farbe und ein Satz Begründung"
- block: "Meilensteine"
  anteil: 20
  inhalt: "Plan gegen Ist, Forecast bis Go-Live"
- block: "Entscheidungsvorlagen"
  anteil: 40
  inhalt: "Vorbereitete Vorlagen mit Optionen und Empfehlung"
- block: "Top-Risiken"
  anteil: 20
  inhalt: "Drei bis fünf, jedes mit Maßnahme und Owner"
- block: "Ausblick"
  anteil: 10
  inhalt: "Was bis zum nächsten Termin passiert"
match:
  priority: 20
  keywords: [steering, lenkungskreis, steuerkreis, board, monthly, monatlich, quarterly, quartalsplanung,
             roadmap review, portfolio review, halbjahresplanung, jahresplanung, allokation]
  regex: '\bQ[1-4]\s*(?:Planung|Review|Steering)\b'
varianten:
  monatlich:
    label: Monthly
    frage: Sind wir auf Kurs?
    horizont: 1–3 Monate
    waehrung: Meilensteine
    typischer_fehler: Überraschungen, die im Check-in längst bekannt waren
    keywords: [monthly, monatlich]
  quartal:
    label: Quarterly Steering / Roadmap Review
    frage: Machen wir die richtigen Dinge?
    horizont: 3–6 Monate
    waehrung: Kapazität und Priorität
    typischer_fehler: Wunschliste statt Kapazitätsplan
    keywords: [quarterly, quartal, roadmap review, portfolio review]
    vorbereitung_vorlauf: 14 Tage
    kernteil: [Rückblick Zusage vs. Lieferung, Lagebild, Priorisierung, Ressourcen, Commitment, Streichliste]
    blocks:
    - block: "Rückblick"
      anteil: 15
      inhalt: "Was war zugesagt, was ist geliefert — ehrlich, inklusive Abweichungen"
    - block: "Lagebild"
      anteil: 15
      inhalt: "Marktanforderungen, Regulatorik, Technische Schulden, Kapazität"
    - block: "Priorisierung"
      anteil: 35
      inhalt: "Kandidatenliste bewerten, ranken, Schnittlinie ziehen"
    - block: "Ressourcen"
      anteil: 20
      inhalt: "Wer arbeitet woran, wo fehlt Kapazität oder Budget"
    - block: "Commitment"
      anteil: 15
      inhalt: "Was ist verbindlich, was ist nice to have"
  jahr:
    label: Halbjahres- / Jahresplanung
    frage: Sind wir für das nächste Jahr richtig aufgestellt?
    horizont: 12–24 Monate
    waehrung: Budget und Fähigkeiten
    typischer_fehler: Fortschreibung des Vorjahres
    keywords: [halbjahresplanung, jahresplanung, jahresziele]
    vorbereitung_vorlauf: 21 Tage
    kernteil: [Strategie-Abgleich, Portfolio-Bereinigung, Budget, Fähigkeiten, Architektur-Ausblick, Streichliste]
    blocks:
    - block: "Strategie-Abgleich"
      anteil: 20
      inhalt: "Zahlen die Vorhaben auf die Unternehmensziele ein — welche nicht mehr"
    - block: "Portfolio-Bereinigung"
      anteil: 20
      inhalt: "Was wird abgeschaltet, eingestellt, abgelöst"
    - block: "Budget"
      anteil: 20
      inhalt: "Investitionsbedarf, externe Leistungen, Lizenzen"
    - block: "Fähigkeiten"
      anteil: 20
      inhalt: "Skills, Personalbedarf, Partner"
    - block: "Architektur-Ausblick"
      anteil: 20
      inhalt: "Technologiepfade, Plattformentscheidungen mit mehrjähriger Bindung"
extract: [entscheidungen, actions, risiken, ampel, meilensteine]
---

# Steering / Lenkungskreis

## Ziel
Über Projekte hinweg entscheiden, was Ressourcen bekommt und was nicht. Kein
Status-Theater — Entscheidungsvorlagen.

## Abgrenzung
Monthly, Quarterly und Jahresplanung sind **Varianten desselben Typs**, keine
eigenen Playbooks. Das Gerüst ist identisch; was sich ändert, ist der Horizont
und die Währung:

| | monatlich | quartal | jahr |
|---|---|---|---|
| Frage | Sind wir auf Kurs? | Machen wir die richtigen Dinge? | Sind wir richtig aufgestellt? |
| Horizont | 1–3 Monate | 3–6 Monate | 12–24 Monate |
| Währung | Meilensteine | Kapazität und Priorität | Budget und Fähigkeiten |
| Ergebnis | Entscheidungen | verbindliche Roadmap | Portfolio und Budgetrahmen |
| Typischer Fehler | Überraschungen | Wunschliste statt Kapazitätsplan | Fortschreibung des Vorjahres |

Quartals- und Jahrestermine sind **keine größeren Monthlys**. Dort geht es nicht
um Fortschritt, sondern um Allokation: was machen wir überhaupt, womit, und was
lassen wir bewusst weg.

## Leitfragen
- Welche Entscheidung liegt oberhalb der Projektleitung, und wer trifft sie heute?
- Wo konkurrieren zwei Vorhaben um dieselbe Person oder dasselbe System?
- Welche Zusage nach außen ist gefährdet, und was kostet die Absicherung?
- Was streichen wir, wenn wir das Neue aufnehmen?
- Variante `quartal`/`jahr`: Ist die Netto-Kapazität gegengerechnet, oder steht hier eine Wunschliste?

## Risiko-Fokus
- Ampel steht auf grün, obwohl Fristen überschritten sind
- Risikokonzentration auf einer Person oder einem Zulieferer
- Kumulierte Puffer-Verschiebungen mehrerer Projekte auf denselben Endtermin
- Roadmap enthält mehr als 100 % der verfügbaren Personentage
- Es wurde nur addiert, nie gestrichen

## Gesprächsführung
- ❌ „Wie ist der Status?" — erzeugt Statustheater
- ✅ „Welche Entscheidung liegt oberhalb der Projektleitung?"
- ✅ „Was streichen wir, wenn wir das Neue aufnehmen?"
- ✅ „Wo konkurrieren zwei Projekte um dieselbe Person?"
- ✅ „Mit welcher Netto-Kapazität ist gerechnet — und was ist abgezogen?"

## Vorbereitung
- [ ] Unterlagen **vorab** verschicken, nicht im Termin verteilen
- [ ] Kritische Punkte vorher **bilateral** mit den Entscheidern abstimmen — das Gremium bestätigt, es diskutiert nicht zum ersten Mal
- [ ] Jede rote Ampel braucht einen Maßnahmenvorschlag, sonst wird es eine Anklage
- [ ] Zahlen prüfen — eine falsche Zahl kostet Glaubwürdigkeit für Monate
- [ ] Variante `quartal`/`jahr`: Kandidatenliste mit Schätzung, Nutzen, Abhängigkeit und Status mitbringen; Netto-Kapazität gegenrechnen (Urlaub, Support, Betrieb, Puffer ab — erfahrungsgemäß bleiben 50–60 % für Projektarbeit)
- [ ] Variante `quartal`/`jahr`: **explizite Streichliste** mitbringen. Ohne sie ist die Priorisierung Theater

## Abbruchkriterium
Eine Überraschung im Termin heißt: die Vorbereitung ist versäumt worden. Was hier
auf Rot geht, darf für niemanden neu sein. Fehlt der Entscheider, wird der
Beschlusspunkt vertagt statt „vorbesprochen".

## Typischer Fehler
Der Termin wird zum Vorlesetermin. Unterlagen werden im Raum zum ersten Mal
gezeigt, und danach ist nichts entschieden.

## Nachbereitung
Aus Protokoll, Teams-Zusammenfassung oder Transkript ziehen:
- **Beschlüsse** wörtlich, mit Entscheider und Datum — ein Beschluss ohne Entscheider ist eine Meinung
- **Ampelwerte** je Dimension mit der genannten Begründung
- **Meilensteinverschiebungen** Plan gegen Ist, mit neuem Datum
- **Top-Risiken** mit Maßnahme und Owner
- **Vertagte Vorlagen** in den Parkplatz, mit dem Grund der Vertagung
- Variante `quartal`/`jahr` zusätzlich: **Streichliste** — was bewusst nicht aufgenommen wurde
