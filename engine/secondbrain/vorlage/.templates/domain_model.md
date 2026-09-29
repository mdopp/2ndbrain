---
type: domain_model
name: {{title}}
bounded_context: "[[]]"
status: active            # draft | active | deprecated
last_updated: {{date:YYYY-MM-DD}}
tags: [architecture, ddd, domain-model]
---
# Domain Model: {{title}}

> Bounded Context: `{{bounded_context}}`

---

## 🏛️ Aggregates & Aggregate Roots

### Aggregate: `[Haupt-Aggregat]`
- **Aggregate Root:** `[Root-Entity]`
- **Invarianten (Konsistenzregeln):**
  - Regel 1: 
  - Regel 2:
- **Enthaltene Entities (mit eigener ID innerhalb des Aggregats):**
  - `EntityName`: Zweck und Lebenszyklus
- **Enthaltene Value Objects:**
  - `ValueObjectName`: Beschreibung

---

## 💎 Value Objects (Unveraenderliche Wertobjekte)
<!-- Haben keine Identitaet, werden nur durch ihre Attribute definiert -->
- `ValueObject`: Attribute, Validierung, Formatregeln

---

## ⚡ Domain Events (Fakten der Vergangenheit)
<!-- Unumkehrbare Geschaeftsereignisse, die von diesem Aggregat emittiert werden -->
- `EventName`: Ausloeser, Nutzlast (Payload)

---

## ⚙️ Domain Services & Business Rules
<!-- Fachliche Operationen, die nicht natuerlich zu einer einzelnen Entity gehoeren -->
- `ServiceName`: Fachliche Aufgabe und Regeln
