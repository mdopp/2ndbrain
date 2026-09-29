---
type: company
name: {{title}}
company_types: [provider]  # Liste: beliebig kombinierbar aus [provider, partner, customer, internal]
contact_person: "[[]]"
contract_status: active     # active | negotiation | expired | paused
sla: 
contract_end: 
last_updated: {{date:YYYY-MM-DD}}
tags: [company]             # Dynamisch ergaenzt um z.B. provider, partner, customer
---
# {{title}}

## Profil & Verantwortung
<!-- Taetigkeitsbereich, Kernkompetenzen, Ansprechpartner & Eskalationswege -->

## Vereinbarungen, SLAs & Vertraege
- 

## Bereitgestellte Systeme / Software
```dataview
TABLE owner_team as "Internes Team", runtime as "Laufzeit", status as "Status"
FROM "entities/systems"
WHERE provider = this.file.link OR vendor = this.file.link
```

## Beteiligte Projekte
```dataview
TABLE lead as "Projekt-Lead", health as "Ampel", target_date as "Deadline"
FROM "projects"
WHERE company = this.file.link OR customer = this.file.link OR partner = this.file.link
```
