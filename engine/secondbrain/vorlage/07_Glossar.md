

# 📖 Glossar-Cockpit

Ein Begriff, eine Datei: `entities/glossary/<slug>.md`.

Das Glossar pflegt die Automatik selbst, sobald neue Notizen eingearbeitet sind (von Hand:
`2ndbrain glossar` zeigt, `--apply` schreibt):

```
1. zählen       was Menschen geschrieben haben (Termine, Mails, Dokumente, Transkripte;
                ohne Vorlagen, Code, Log-Markierungen) → Häufigkeitsindex (.2ndbrain/daten/glossary.json)
2. Kanon        Fachobjekte mit Definition → status: atlas
3. Bestand      Messwerte in den Seiten, Schreibweise („erp“ → „ERP“)
4. einordnen    neue Begriffe, Abkürzungen, leere Definitionen → lokales Modell
5. kuratieren   hier im Cockpit          status: candidate → approved
```

Die Zahlen im Frontmatter (`occurrences`, `first_seen`, `last_seen`, `sources`)
pflegt Schritt 3 automatisch und **überschreibt nie den Rumpf**. Alles, was du
schreibst, bleibt. Eine **neue** Seite entsteht nur, wenn der Begriff in mindestens drei
Notizen steht und das Modell ihn als Fachbegriff, System, Organisation oder Abkürzung
einordnet – allgemeine IT-Wörter und Rauschen nicht; Kürzel aus zwei Buchstaben nur, wenn
die Langform in einer Notiz ausgeschrieben ist („Change Request (CR)“). Was es schon
eingeordnet hat, fragt es erst wieder, wenn sich die Fundstellen ändern.

Schritt 4 füllt nur **leere** Definitionen: Fachobjekte aus dem Domain Atlas
(`status: atlas`) und sonst einen Vorschlag des lokalen Modells — nur aus den
Fundstellen, als Callout „Vorschlag lokales Modell – bitte prüfen" mit Links auf
die Quellen. Eine Langform steht nur da, wenn sie in den Quellen steht. `art`
(fachbegriff · system · organisation · abkuerzung · allgemein · rauschen · unklar)
ist die Einordnung des Modells — ein Hinweis für die Triage, keine Entscheidung:
den Status setzt nur du.

## Status-Modell

| `status` | Bedeutung | Was der Wächter prüft |
|---|---|---|
| `atlas` | aus dem Domain Atlas — dort gepflegt, hier nur gespiegelt | nichts |
| `candidate` | aus dem Index übernommen, unbearbeitet | nur Synonym-Kollisionen |
| `review` | in Arbeit | alles |
| `approved` | verbindlich | alles (Definition, Abgrenzung, Bounded Context) |
| `rejected` | kein Fachbegriff (Personenname, Dateiformat, Füllwort) | nichts |
| `deprecated` | abgelöst — `related_terms` auf den Nachfolger setzen | nichts |



## 1. Triage: häufigste unbearbeitete Kandidaten

Hier fängst du an. Von oben nach unten: entweder `approved` (Vorschlag prüfen,
Callout-Titel ersetzen oder eigene Definition schreiben) oder `rejected` (dann
fertig). Fachbegriffe, Systeme und Organisation stehen oben; allgemeine IT-Wörter, Rauschen und
Unklares unten — die sind meist schnell `rejected`.

```dataview
TABLE art AS "Art", langform AS "Langform", occurrences AS "Vorkommen", last_seen AS "zuletzt"
FROM "entities/glossary"
WHERE status = "candidate"
SORT choice(art = "allgemein" OR art = "rauschen" OR art = "unklar", 1, 0) ASC, occurrences DESC
LIMIT 60
```

> Personennamen und Dateiformate rutschen gelegentlich durch (z. B. ein Name,
> der noch keine Personen-Notiz hat). Auf `rejected` setzen — oder besser: eine
> Notiz unter `entities/people/` anlegen, dann filtert der nächste Sync ihn raus.

## 2. Kuratierte Begriffe nach Bounded Context

Offiziell aus dem Domain Atlas (Definition dort ändern, nicht hier):

```dataview
TABLE WITHOUT ID bounded_context AS "Bounded Context", file.link AS "Begriff", synonyms AS "Synonyme"
FROM "entities/glossary"
WHERE status = "atlas"
SORT bounded_context ASC, file.name ASC
```

Von dir kuratiert:

```dataview
TABLE WITHOUT ID bounded_context AS "Bounded Context", file.link AS "Begriff", occurrences AS "Vorkommen", status
FROM "entities/glossary"
WHERE status = "approved" OR status = "review"
SORT bounded_context ASC, occurrences DESC
```

## 3. Lücken: verbindlich, aber unvollständig

Das sind die Befunde, die der Wächter meldet — hier vor dem Lauf sichtbar.

```dataview
TABLE occurrences AS "Vorkommen", synonyms AS "Synonyme", related_terms AS "verwandt"
FROM "entities/glossary"
WHERE (status = "approved" OR status = "review") AND (!bounded_context OR bounded_context = "")
SORT occurrences DESC
```

## 4. Karteileichen: seit über 90 Tagen nicht erwähnt

```dataview
TABLE occurrences AS "Vorkommen", last_seen AS "zuletzt gesehen", status
FROM "entities/glossary"
WHERE last_seen AND date(last_seen) < date(today) - dur(90 days)
SORT last_seen ASC
LIMIT 30
```

## 5. Synonym-Kollisionen vorbereiten

Zwei Begriffe dürfen nicht dasselbe Synonym beanspruchen — genau das ist die
stärkste Prüfung des Wächters.

```dataview
TABLE synonyms AS "Synonyme", bounded_context AS "Kontext"
FROM "entities/glossary"
WHERE synonyms AND length(synonyms) > 0
SORT file.name ASC
```

## 6. Wo kommt ein Begriff vor?

Jede Kandidaten-Datei listet ihre Fundstellen im Frontmatter (`sources`, bis zu
12). Für die vollständige Suche:

```bash
grep -ril "<begriff>" --include='*.md' .                        # alle Fundstellen
2ndbrain aufloesen "<begriff>"                      # Atlas / C4 / Vault
```

`resolve` ist der schnellste Weg zu der Frage, die beim Kuratieren zuerst kommt:
**ist der Begriff schon offiziell definiert?** Wenn `resolved: atlas`, dann muss
die Definition hier zum Domain Atlas passen — nicht daneben entstehen.



## Kuratieren: was in die Datei gehört

```markdown
## Definition (Ubiquitous Language)
Ein Satz, der ohne Kontext funktioniert. Keine Beispiele, keine Abgrenzung.

## Abgrenzung & Nicht-Ziele
Was der Begriff ausdrücklich NICHT ist. Hier verhindert man God-Concepts.

## Begruendung der Verwandschaften
Warum die `related_terms` verwandt sind — und worin sie sich unterscheiden.
```

Im Frontmatter zusätzlich setzen:

```yaml
status: approved
bounded_context: "Auftragsverwaltung"   # welcher Kontext besitzt den Begriff
synonyms: ["Direktverladung"]           # umgangssprachlich/veraltet
related_terms: []         # mit Begründung im Rumpf
```

## Schwelle anpassen

Standard ist `occurrences >= 10`. Seltenere Begriffe holen:

```bash
2ndbrain glossar --min-count 5            # erst zeigen
2ndbrain glossar --min-count 5 --apply    # dann einordnen und anlegen
```
