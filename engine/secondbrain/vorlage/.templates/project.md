---
type: project
title: {{title}}
status: active               # proposed | active | on_hold | completed | cancelled
kind: project                # project (befristet) | product (produkt-<system>) | account (firma-<firma>) | area (Bereich)
health: green                # green | yellow | red | gray
lead: "[[]]"
team: "[[]]"
company: "[[internal]]"
systems: []                  # ["[[system-slug]]"]
target_date: ""
created: {{date:YYYY-MM-DD}}
last_updated: {{date:YYYY-MM-DD}}
source: ""                   # meeting-extractor | manual | sync
tags: [project]
---
# {{title}}

## Beschreibung
<!-- Zweck, Zielzustand, Erfolgskriterien -->

## Event Log
- [{{date:YYYY-MM-DD}}] [STATUS] Projekt angelegt
