---
type: bounded_context
name: {{title}}
domain_type: core          # core (Kerngeschaeft) | supporting (Unterstuetzend) | generic (Generisch)
owner_team: "[[]]"
strategic_importance: high # high | medium | low
upstream_contexts: []      # Liefert Daten/Services an diesen Kontext [U]
downstream_contexts: []    # Empfaengt Daten/Services von diesem Kontext [D]
implements_systems: []     # Assoziierte Software-Systeme ["[[engine-api]]"]
last_updated: {{date:YYYY-MM-DD}}
tags: [architecture, ddd, bounded-context]
---
# Bounded Context: {{title}}

## 🎯 Fachlicher Zuschnitt & Verantwortung (Scope)
<!-- Welche Geschaeftsfaehigkeit bildet dieser Kontext isoliert ab? Wo liegen die Grenzen? -->

## 🔄 Schnittstellenmuster (Integration Patterns)
- **Upstream-Beziehungen (Lieferanten):**
  - Wie binden wir Upstream-Systeme an? (z.B. Open Host Service, Anti-Corruption Layer)
- **Downstream-Beziehungen (Konsumenten):**
  - Welche Schnittstellen stellen wir bereit? (z.B. Published Language, REST, gRPC)

## 🧩 Implementierende Softwaresysteme
```dataview
TABLE owner_team as "Team", runtime as "Laufzeit", status as "Status"
FROM "entities/systems"
WHERE contains(implements_concepts, this.file.link) OR file.link = any(this.implements_systems)
```

## 📖 Assoziierte Fachbegriffe (Ubiquitous Language)
```dataview
TABLE term as "Fachbegriff", status as "Status"
FROM "glossary"
WHERE bounded_context = this.name
```
