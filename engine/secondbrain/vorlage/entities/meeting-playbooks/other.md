---
type: meeting-playbook
meeting_type: other
label: Sonstiges
leitfrage: Warum findet dieser Termin statt?
dauer: unbekannt
kadenz: ad hoc
pflicht_output: ein festgehaltenes Ergebnis
vorbereitung_vorlauf: 1 Tag
entscheidung_erforderlich: offen
kernteil:
- Sachstand
blocks:
- block: "Sachstand"
  anteil: 100
  inhalt: "Frei — der Typ ist noch nicht bestimmt"
match:
  priority: 999
  keywords: []
extract: [entscheidungen, actions]
---

# Sonstiges

## Ziel
Vor dem Termin festhalten, warum er stattfindet und was danach anders sein soll.

## Abgrenzung
Rückfall, wenn kein anderer Typ greift. Landet ein wiederkehrender Termin hier,
ist das ein Befund und keine Lösung: entweder fehlt ein Keyword im passenden
Playbook, oder der Termin hat wirklich keinen Zweck. Beides gehört geklärt.

Typ von Hand festlegen: `meeting_type: <typ>` **und** `meeting_type_locked: true`
im Frontmatter der Notiz. Sonst bestimmt jeder Prep-Lauf den Typ neu.

## Leitfragen
- Warum findet dieser Termin statt, und was wäre ohne ihn offen?
- Was ist das erwartete Ergebnis?
- Wer braucht das Ergebnis danach?
- Welcher der sechs Typen passt eigentlich?

## Risiko-Fokus
- Termin ohne erkennbares Ziel — dann absagen oder zusammenlegen
- Ergebnis wird nirgends festgehalten

## Gesprächsführung
- ❌ „Wollen wir kurz sprechen?" — ohne Ziel wird es ein Plausch
- ✅ „Was wäre ohne diesen Termin offen?"
- ✅ „Wer braucht das Ergebnis danach?"

## Vorbereitung
- [ ] Ziel in einem Satz aufschreiben
- [ ] Prüfen, ob ein Playbook passt — dann Typ setzen und sperren

## Abbruchkriterium
Kein Ziel formulierbar → absagen.

## Typischer Fehler
Der Termin bleibt dauerhaft auf `other` stehen und wird nie vorbereitet.

## Nachbereitung
Entscheidungen und Actions im Standardformat ziehen. Zusätzlich vermerken,
welcher Typ eigentlich gepasst hätte.
