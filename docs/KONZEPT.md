# 2ndBrain — Konzept

> Zielbild, Aufbau und verbindliche Formate. Die Formate in §4 sind Spezifikation: Code und Tests
> richten sich danach. Beispiele in diesem Text sind erfunden. Welcher Begriff im Code wie heißt,
> steht in §19.

---

## 1. Worum es geht

Wer beruflich in viele Themen eingebunden ist – als Führungskraft, Architektin, Projektleiter –, muss

1. **wissen, wo die eigenen Themen stehen** (Überblick, Bewegung, Ampel),
2. **in Terminen auskunftsfähig sein** (in Sekunden sagen können, was gilt),
3. **die richtigen Fragen stellen und Zusagen nachhalten** (wer schuldet wem was, was ist offen),
4. **das Wichtigste priorisiert voranbringen** (Fokus-Themen mit Ziel und nächstem Schritt, und immer
   wieder die Frage: Geht meine Zeit dorthin? → §20).

Termine sind dabei **Eingang** (dort entsteht Wissen) und **Moment der Nutzung** (dort wird es
gebraucht). Das Wissen selbst gehört zum **Thema**, nicht zum Termin.

## 2. Ausgangslage

Ein gewachsener Notiz-Vault hat typischerweise viel Wissen, aber in einer Form, die vor einem Termin
nicht hilft:

| Befund | Folge |
|---|---|
| Ereignisse stehen als Protokoll im Thema, nicht als Stand | vor einem Termin nicht lesbar |
| Termin-Notizen haben kein Thema, Sammelrunden werden nicht aufgeteilt | der Stand eines Themas wird „vergiftet“ |
| Aufgaben als Freitext, oft ohne Termin, ohne Verantwortliche, ohne Erledigt-Status | „Was ist offen?“ ist nicht beantwortbar |
| Quellen-Links zeigen in versteckte Ordner | keine Nachvollziehbarkeit |
| Kalender ohne Teilnehmer, Personen nur als Vornamen | Zuordnung zu Personen rät |

## 3. Kernmodell

### 3.1 Themen mit drei Schichten

| Schicht | Frage | Wer erzeugt | Wo |
|---|---|---|---|
| **Log** | Was war? | Extraktion (LLM) → Validierung (Code) | `## Event Log` der Themen-Datei (append-only) |
| **Stand** | Was gilt jetzt? | Fakten: Code · Prosa: LLM im Hintergrund | Auto-Block oben in der Themen-Datei |
| **Offene Punkte** | Was fehlt? Wen frage ich was? | Extraktion + Mensch | Checkboxen dort, wo sie entstehen; Sicht per Abfrage |

**Frage** ist ein eigener Punkt-Typ: Was man jemanden fragen muss, sammelt sich an und erscheint
automatisch, wenn man die Person oder die Reihe trifft.

### 3.2 Themen-Landkarte

Themen liegen in `entities/projects/`. Frontmatter `kind` unterscheidet `group` (Themengruppe) ·
`area` (Bereich, Langläufer) · `project` · `product` · `account` (Firma). `parent: '[[slug]]'` bildet
die Hierarchie; die Ampel eines Dachs ist die schlechteste seiner Unterthemen. Zu kleinteilige
Projekte werden Unterthemen statt eigener Radar-Zeilen.

### 3.3 Begriffs-Index

Verbindet Sprache mit Themen, Systemen und Kontexten. Quellen: der Kanon (z. B. ein Domain Atlas:
Kontexte, Fachobjekte mit Aliassen und Definitionen, Subdomänen, Teams), das LikeC4-Modell
(Systeme), der Vault (Namen, Aliasse, Keywords aller Seiten) und das Glossar. Nutzen: Kandidaten für
die Themen-Zuordnung pro Punkt, Alias-Auflösung (ein Kürzel = ein Systemname), die „richtigen
Begriffe“ fürs Glossar.

Kontexte und Fachobjekte des Kanons gehören über ihre Subdomäne zu einem Thema: zu dem, das genauso
heißt wie die Subdomäne oder das Team (ohne Präfix: `sd-lager` → Thema `lager`), sonst zu dem, das die
Kennung in `atlas_id:` nennt (`atlas_id: [sd-rechnung, team-rechnung]` für ein Thema „Rechnung und
Zahlung“). Hat eine Subdomäne noch kein Thema und steht sie (oder einer ihrer Kontexte, eines ihrer
Fachobjekte) im Termintitel, schlägt die Zuordnung „neues Thema aus dem Atlas“ vor; ein Klick legt es
an – Name aus dem Kanon, Bereich, verknüpft über `atlas_id`, eingeordnet wie die übrigen
Subdomänen-Themen. Themen entstehen so, wenn es Arbeit gibt, nicht vorab für jede Subdomäne.

**Der Kanon als Wortschatz.** Wie Glossar und Themen liefert der Kanon die richtigen Begriffe: Jede
Subdomäne, jedes Team, jeder Kontext und jedes Fachobjekt ohne eigene Seite hat eine Glossar-Seite
(`status: atlas`, Abschnitt „Im Domain Atlas“ mit Art, Reife, Kontexten, Teams und Thema; eine
Beschreibung aus dem Kanon wird die Definition). Vorhandene Glossar-Seiten bekommen den Abschnitt dazu,
ihr Text bleibt. Was dem Kanon fehlt, wird ein Vorschlag an ihn (§12, Art „Begriff“) – der Kanon wächst
mit dem Wortschatz der Termine.

### 3.4 Quellen der Wahrheit

| Quelle | Zuständig für | Zugriff |
|---|---|---|
| Kanon (z. B. Domain Atlas, oder eine einfache YAML-Datei) | Domäne: Kontexte, Objekte, Teams, Abläufe | lesen; Änderungen nur als Vorschlag (§12) |
| LikeC4-Modell | Systemlandschaft | wird aus den System-Seiten erzeugt; lesen |
| Vault | Themen, Personen, Termine, Log/Stand/Offene Punkte | lesen + schreiben (über die Engine) |
| Mitschriften, Transkripte, Mails | was in Terminen und Nachrichten gesagt wurde | liefern an (§5) |

Pfade externer Quellen: Auto-Erkennung (neben dem Vault, `~/code/<repo>`, `~/<repo>`),
überschreibbar in `.2ndbrain/local.config.json` oder per Umgebungsvariable.

## 4. Formate (Spezifikation)

### 4.1 Offene Punkte

```markdown
- [ ] Freigabe im Architekturboard einholen — [[erika-muster|Erika Muster]] · [[portal-relaunch|Portal-Relaunch]] 📅 2026-10-03 ➕ 2026-09-14
- [ ] ❓ Steht der Go-live-Termin? — an [[max-beispiel|Max Beispiel]] · [[portal-relaunch|Portal-Relaunch]] ➕ 2026-08-03
- [ ] Lizenzfrage klären — Max (?) · [[portal-relaunch|Portal-Relaunch]] ➕ 2026-09-21
- [x] Sicherheitsprüfung einplanen — [[jana-probe|Jana Probe]] ➕ 2026-09-14 ✅ 2026-09-30
```

- Ein Punkt = **eine** verantwortliche Person, **eine** Tätigkeit.
- Nach ` — `: Verantwortliche(r) als Personen-Link (bei Fragen: `an [[…]]`), danach ` · ` Themen-Link(s).
  Unaufgelöste Person: Klartext mit `(?)` → Rückfrage, nie geraten.
- `📅` Frist nur wenn genannt (nie geraten) · `➕` Entstehungsdatum (Datum der Quelle) · `✅` erledigt am.
- `❓` am Textanfang = Frage. `[x]` erledigt, `[-]` verworfen.
- Optional `(→ [[quelle]])` am Ende.
- **Nur Zusagen sind Punkte.** Das Modell gibt jeder Aufgabe eine Art: *Zusage* (eine genannte Person hat es
  zugesagt oder den Auftrag bekommen), *Absicht* (soll geschehen, niemand hat es übernommen) oder *Info*.
  Absichten und Infos stehen im Parkplatz der Termin-Notiz („Noch ohne Zusage: …“, „Festgestellt: …“), nicht
  in den Aufgabenlisten. Dieselbe Zusage in anderen Worten oder als Satzteil wird eine Aufgabe (der längere
  Text bleibt). Ein Raum oder Ort ist nie verantwortlich.
- **Beleg.** Unter einem Punkt aus einem Termin steht eingerückt der Satz aus dem Material, aus dem Aufgabe
  und Person hervorgehen (`    - Beleg: „…“`) – nur, wenn er wörtlich im Material steht.
- **Wo:** Termin-Notiz `## Actions` (entstanden im Termin) · Themen-Datei `## Offene Punkte`
  (entstanden außerhalb von Terminen). **Nie kopieren** — Themen- und Personenseiten zeigen fremde
  Punkte per Abfrage (abhaken wirkt an der Quelle).
- **Kurzform zum Eintippen:** `- [ ] Was — @wer — 2026-10-01` (Datum = Frist). `@wer` wird nur bei
  einem exakten Personen-Slug zur Person.
- Einziger Parser/Renderer: `aufgaben.py` (im Plugin übertragen: `src/core/aufgaben.ts`).

### 4.2 Log

`- [YYYY-MM-DD] [DECISION|RISK|STATUS|MILESTONE|DEADLINE] Text (→ [[quelle]])`, neueste oben,
Datum = Datum der Quelle. **Aufgaben stehen nicht im Log** (→ 4.1).

### 4.3 Stand-Block

```markdown
<!-- stand-auto:start -->
> [!abstract] Stand 27.09.2026 · 🟡 gelb
> Drei bis fünf Sätze Prosa: was jetzt gilt (LLM, nur aus dem Log).
>
> **Offen:** 5 Aufgaben (1 überfällig) · 2 Fragen · **Risiken (30 Tage):** 2 · **Zuletzt bewegt:** 18.09.
<!-- stand-auto:end -->
```

Steht direkt unter der H1. Alles außer der Prosa rechnet Code (Ampel aus `ampel.py`). Neu
erzeugt nur, wenn sich der Fingerabdruck (Log + offene Punkte) ändert (`stand_updated`,
`stand_fingerprint` im Frontmatter).

### 4.4 Frontmatter-Ergänzungen

- Themen: `kind`, `parent`, `atlas_id` (→ 3.3); `stand_updated`, `stand_fingerprint`. Optional als Fokus
  (→ §20): `fokus` (Rang, 1 = am wichtigsten; `true` zählt hinter allen Nummern), `ziel` (ein Satz: woran
  merke ich, dass es geschafft ist), `target_date` (Zieltermin, auch für die Ampel).
- Termine: `themen` (Slugs; das erste ist das Hauptthema), `themen_von_hand` (von Hand zugeordnet,
  wird nicht neu berechnet), `meeting_type` (das Playbook), `teilnehmer` (Personen-Slugs),
  `teilnehmer_unaufgeloest`, `outlook_uid`, `nachbereiten: angefordert` (Vormerkung vom Handy);
  `nachbereitet_von: modell|notbehelf`, `eingearbeitet` (Datum), `archiviert` (Zeitpunkt) → 4.6.
- Reihen (`entities/forums/`): `project` (Hauptthema der Reihe), `reports_on`, `mit`, `kein_thema`.
- Personen, Themen, Systeme, Teams, Firmen: `schreibweisen` – bestätigte Verschreiber des Namens (→ 5).
- Systeme: `atlas_kontexte` – die Kontexte des Domain Atlas, die das System umsetzt; zugeordnet wird nur
  über die Liste `reports/kontext-systeme.md` (Vorschläge mit Beleg: Name, Daten laut Migrationstabellen,
  Team), nie geraten (→ 17).

### 4.5 Archiv

Verarbeitete Quellen liegen in `archive/<typ>/YYYY-MM/` (sichtbarer Ordner – Obsidian indiziert
Punkt-Ordner nicht, Quellen-Links wären tot). Verdichtete Themen-Historie (erledigte Punkte, Log älter
als 6 Monate): `archive/themen/<slug>-archiv-<jahr>.md` – nichts wird gelöscht.

### 4.6 Lebenslauf einer Termin-Notiz

**Vorbereiten → Termin → Material → Nachbereiten → Einarbeiten → Archivieren.**

1. **Vorbereiten** (`vorbereiten`, für heute und morgen): Notiz in `active-meetings/` mit Thema,
   Playbook, Agenda und Briefing.
2. **Material**: Mitschrift, Transkript, Teams-Zusammenfassung oder Protokoll kommt in die Notiz (→ 5) –
   von Hand oder aus dem Eingang (Automatik-Schritt `protokolle`, → 5).
3. **Nachbereiten** (`nachbereiten`): Das Modell zieht Entscheidungen, Aufgaben und Risiken heraus;
   steht nur ein Transkript da, schreibt es auch das Protokoll (→ 5). Vermerk `nachbereitet_von: modell`.
   Zwei Stufen (→ 7): Das Modell entwirft, langes Material in Stücken; ist ein Prüfmodell eingestellt,
   gleicht es den Entwurf mit dem ganzen Material ab – Abschnitt für Abschnitt, ergänzen, korrigieren,
   zusammenführen, Erfundenes streichen – und sein Ergebnis gilt (`geprueft_von: <modell>`). Scheitert
   die Prüfung oder liefert sie nichts, gilt der Entwurf. Beide Stufen kennen Termin und Datum (sonst
   rät das Modell bei „bis Freitag“ das Jahr). Eine Frist bekommt nur die Aufgabe, für die das Material
   sie nennt – mit dem Datum rechnete die Prüfung „nächste Woche“ sonst aus und gab es allen Aufgaben.
   Wochen zählen wie im Code bis Freitag („diese Woche“, „noch in dieser Woche“ = Freitag dieser Woche,
   „nächste“/„kommende Woche“ = Freitag der nächsten). Der Code prüft jede Frist gegen die Stelle des
   Materials, von der die Aufgabe handelt (`nachbereiten.fundstelle`: die Sätze mit den meisten ihrer
   Wörter; ohne klare Stelle das ganze Material) – „in dieser Woche“ bei einer Aufgabe belegt keine Frist
   einer anderen.
   Ohne Modell hilft ein Notbehelf (nur, was schon als Text dasteht; `nachbereitet_von: notbehelf`) –
   er wartet auf eine echte Nachbereitung.
4. **Einarbeiten** (Automatik-Schritt `themenlog`): Entscheidungen und Risiken gehen ins Log der Themen,
   mit der Notiz als Quelle; danach `eingearbeitet: <Datum>`. Aufgaben bleiben in der Notiz (→ 4.1).
5. **Archivieren** (`archivieren`, Automatik-Schritt nach dem Einarbeiten): nach
   `archive/meetings/JJJJ-MM/` kommt, was durch das Modell nachbereitet und eingearbeitet ist
   (`status: done`), und was entfallen oder übersprungen ist, sobald der Termin vorbei ist.
   `processed: true` und `archiviert:` wie im Eingang.

In `active-meetings/` bleibt, was noch etwas braucht: künftige Termine, Termine ohne Material,
Notbehelf, Vormerkungen vom Handy. Aufgabenliste, Plugin und die Abfragen der Themen- und
Personenseiten lesen das Archiv mit – abhaken wirkt dort wie vorher. Zurücknehmen
(`nacherfassen --note <pfad> --undo`) holt eine Notiz aus dem Archiv zurück.

## 5. Mitschriften, Mails und Protokolle

**Mitschriften.** Was im Termin gesagt wurde – eigene Notizen, ein Transkript, eine Zusammenfassung
aus Teams oder einem anderen Werkzeug, ein Protokoll –, gehört in die Termin-Notiz: `## Meine Notizen`,
`## Mitschrift`, `## Transkript` oder `## Teams-Zusammenfassung`. „Nachbereiten“ liest alle vier.
Gegliederte Protokolle (Entscheidungen, Aufgaben, Risiken als eigene Abschnitte) liest das Modell am
zuverlässigsten.

**Protokolle im Eingang.** Liegt ein Protokoll, ein Transkript oder eine Teams-Zusammenfassung im
Eingang, ordnet der Automatik-Schritt `protokolle` es seinem Termin zu – vor dem Einarbeiten, ohne
Modell: Datum aus Dateiname oder Kopf, dann der Titel gegen die Termin-Notizen dieses Tages (aktiv und
Archiv) und den Kalender. Eindeutig: Inhalt in `## Transkript`, `## Teams-Zusammenfassung` oder
`## Mitschrift` der Notiz, vorgemerkt zum Nachbereiten; eine archivierte Notiz kommt zurück, zu einem
Kalendertermin ohne Notiz entsteht sie; die Datei geht nach `archive/protokolle/JJJJ-MM/`. Unklar: eine
Rückfrage mit den Kandidaten, „neue Termin-Notiz“ und „kein Termin“ – bis zur Antwort wartet die Datei.
Ein Protokoll ohne passenden Termin bleibt fürs Einarbeiten (es kann auch ein anderes Dokument sein).

**Mails und Dokumente.** Was im Eingang (`inbox/` oder Vault-Wurzel) landet, liest `2ndbrain einlesen`
bzw. die Automatik ein: Mail → Notiz, Anhänge und ZIPs → eigene Notizen, Bilder → Texterkennung. Die
Automatik nimmt aus der Vault-Wurzel nur Mails; Dokumente, Bilder und ZIPs nur aus `inbox/` (was im
Vault-Ordner selbst liegt, gehört dem Nutzer). Einsortiert wird danach je Lauf nur `je_lauf` Vorgänge.

**Absender und Empfänger** sind Quellen für Namen, Beteiligte und das Wiederfinden (`adressen.py`): Die
Mail-Notiz trägt `von`, `an`, `cc` vollständig, jede Person als Verweis auf ihre Seite – erkannt über die
Mail-Adresse der Seite (`email:`), den vollen Namen, einen Alias, „Nachname, Vorname“, die umgekehrte
Reihenfolge, Initialen am Vornamen oder vorname.nachname@; ein Name, der auf mehrere Seiten passt, bleibt
Klartext. Gruppen-Adressen stehen unter `verteiler`. `teilnehmer` sind die erkannten Personen aus Von und An –
bei einer Rundmail (ein Verteiler in An oder mehr als 15 Empfänger) nur der Absender. So zählen Mails für die
**Beteiligten** eines Themas wie Termine, und nach dem Einarbeiten trägt die Mail ihre `themen`. Log-Einträge
und Aufgaben aus einer Mail nennen ihren Absender vor der Quellenangabe („… (laut X) (→ [[mail]])“, „…
(von X)“) – außer der Text nennt ihn schon, es ist seine eigene Zusage oder die eigene Mail. Die Kopfzeilen
im Text der Notiz bleiben wörtlich.

**Nachziehen nach einem Update** (`nachziehen.py`, Schritt `nachziehen` der Automatik): Jede Aufbereitung,
die aus Quellen Felder ableitet, hat eine Fassung, und jede Notiz trägt ihre (`mail_fassung`). Ist die Engine
neuer, bringt die Automatik alte Notizen im Hintergrund auf den Stand – je Lauf ein Stück (200 Notizen oder
60 Sekunden); „Heute“ zeigt, was noch offen ist (`.2ndbrain/daten/nachziehen.json`). Nachgezogen werden nur
aufbereitete Felder, nie was der Nutzer geschrieben oder abgehakt hat; bei Mails aus der Original-Mail im
Archiv (Message-ID), sonst aus den Kopfzeilen im Text. Auch später noch: bekommt eine Person eine Seite,
zeigen ihre Mails darauf. Ein neues Einarbeiten mit dem Modell gehört nicht dazu – es legte Einträge doppelt
an und verlöre, was inzwischen geändert wurde.
Eine Mail, die schon einmal eingelesen und eingearbeitet wurde, wird kein zweites Mal eingelesen; sie
wandert nach `.trash/doppelte-mails/`. Erkannt wird sie an der Message-ID ihrer Notiz im Archiv, bei
älteren Mail-Notizen ohne Message-ID am Zeitstempel (Date-Header). Eine Datei, die sich nicht lesen
lässt (altes `.doc`/`.ppt`/`.xls`, beschädigte Datei), bleibt im Eingang liegen und wird mit Grund
gemeldet; die übrigen Dateien werden trotzdem eingelesen.

**Protokoll im 2ndBrain.** Steht in der Termin-Notiz ein Transkript oder eine Teams-Zusammenfassung,
aber noch kein Protokoll (`## Protokoll` oder `## Mitschrift`), schreibt das lokale Modell beim
Nachbereiten eines – nach der Vorlage des Vaults (`.2ndbrain/protokoll-vorlage.md` oder der Pfad in
`protokoll.vorlage` in local.config.json; fehlt sie: die mitgelieferte) und in der Sprache des Materials
(Termin auf Englisch → Protokoll auf Englisch). Die Vorlage ist in den Plugin-Einstellungen zu finden und
zu bearbeiten („Protokoll-Vorlage“), weil Obsidian `.2ndbrain/` nicht zeigt. Das Protokoll steht als
`## Protokoll` vor dem Transkript; Fristen nur, wenn das Material sie nennt, kein Soll-Ablauf, der nicht
besprochen wurde; die Antwortgrenze wächst mit dem Material (→ 7, mindestens 6000 Tokens). Entscheidungen
und Aufgaben zieht die Nachbereitung weiter aus dem Material selbst (`protokoll.py`). Alles geschieht im
2ndBrain – der MCP-Server liest nur, er schreibt keine Protokolle.

**Namen sauber (Schreibweisen).** Transkripte und Teams-Zusammenfassungen schreiben Namen, wie die
Spracherkennung sie hört – eine Person, ein Produkt in fünf Schreibweisen. Bestätigte Verschreiber stehen an
der Seite im Feld `schreibweisen:` (nicht in `aliases:` – dort stehen auch Kurzformen und verwandte
Begriffe, die im Text bleiben sollen). Umlaute und Akzente entscheidet eine Regel des Benutzers ohne
Nachfrage: Unterscheiden sich zwei Schreibweisen nur darin (ae/oe/ue, fehlende Umlaut-Punkte, Akzente), ist
die mit mehr solcher Zeichen richtig – hat die Seite sie, wird der Text angeglichen; hat nur der Text sie
(„Mühlenkamp“ zur Seite „Muehlenkamp“), heißt die Seite künftig so (in der Liste, beim Nachbereiten statt einer
Rückfrage). Zweitbeste Quelle bei Personen: eine E-Mail-Adresse mit dem vollen Namen (vorname.nachname@ – aus
Personenseiten, Mails und Kalender; Umlaute kennt sie nicht, darum kommt sie nach der Umlaut-Regel). Passt sie
zur Variante, heißt die Seite künftig so – nur, wenn die Variante wie ein Name aussieht, nicht bei Initialen
aus der Adresse –, passt sie zum Namen der Seite, ist die Variante ein Verschreiber. Die Adressen selbst stehen
in keiner Liste und keinem Bericht. Bei Personen gelten auch Groß-/Kleinschreibung und Bindestriche ohne
Nachfrage als gleich.
Wie ein Thema, System, Team oder eine Firma geschrieben wird (groß/klein, Bindestrich, Bindewort), bestätigt der
Benutzer: Im Probelauf hätte die Schreibung der Seite hunderte Stellen geändert – teils falsch, weil der Name
der Seite selbst uneinheitlich war, ein Name zugleich ein Allerweltswort ist oder ein Bindestrich-Kompositum
zerrissen worden wäre (dort bleibt die Trennung immer). Nachbereiten, Protokoll, Einarbeiten und Stand
ersetzen die Schreibweisen im Material *vor* dem Modell (eine Kopie) und in seiner Antwort *danach*;
Transkript, Teams-Text, Mitschrift, eigene Notizen und Mails bleiben in der Notiz wörtlich, Link-Ziele,
Code und Adressen auch. Einen neuen Verschreiber einer Person oder eines Themas des Termins fragt die
Nachbereitung nach (Rückfrage: A Verschreiber, B der neue Name ist richtig – die Seite heißt künftig so,
C etwas anderes – wird nie wieder gefragt). Automatisch ähnliche Wörter zu ersetzen ginge daneben (im
Vergleich: „Portugal“ ≈ „Portal“, zwei Teams mit ähnlichem Kürzel) – deshalb gilt ein Ding nur als
verschrieben, wenn genau ein Wort abweicht und dieses verhört klingt. Den Anfang macht eine Liste über den
ganzen Vault (`2ndbrain schreibweisen --liste` → `reports/schreibweisen-review.md`: je Seite eine Frage mit
allen ihren fraglichen Schreibweisen – A alle Verschreiber, B die häufigste ist richtig, C alle lassen, oder
einzeln ankreuzen –, dazu mögliche doppelte Personenseiten zum Zusammenführen, die zweite Seite geht nach
`.trash/`; Erledigtes steht unten). Frühere Antworten zählen mit: ein Verschreiber, der einem schon bestätigten
derselben Seite ähnelt oder sich nur in der Schreibung von ihm unterscheidet, ist auch einer; eine Variante wie
eine mit „anderes“ beantwortete wird nicht mehr gefragt. Die Schreibung eines Dings (groß/klein, Bindestrich)
leitet 2ndBrain nie ab – eine Antwort zu „X-Y“ sagt nichts über „x Y“. Füllwörter am Rand („… Und“) machen
keinen Namen und werden nie Schreibweise. Wortregeln (`"schreibweisen": {"woerter": {"Richtig": ["Falsch"]}}`)
gelten für ein einzelnes Wort überall, auch mitten in einem Namen („Lagerblick-Team“ → „LagerBlick-Team“), nicht aber in
Link-Zielen (Dateinamen), Code oder klein geschriebenen Slugs. Angekreuzt arbeitet die Liste der
Automatik-Schritt `schreibweisen` ein. Den Bestand bereinigt er erst nach Freigabe
(`"schreibweisen": {"bereinigen": true}`, vorher `--bereinigen --vorschau`), dann bei jeder neuen
Schreibweise: abgeleiteter Text (Entscheidungen, Aufgaben, Vorbereitung, Protokoll, Glossarseiten, Log-Zeilen,
automatische Blöcke), jede Datei vorher nach `.trash/schreibweisen-<Zeit>/`, dazu ein Bericht in `reports/`.

## 6. Arbeitsteilung Code ↔ LLM

| Aufgabe | Wer | Warum |
|---|---|---|
| Punkte aus Notizen und Mitschriften extrahieren | LLM | gute Formulierung, schnell genug |
| Thema pro Punkt | Code-Vorauswahl + LLM | freie Wahl aus allen Themen lag daneben → Vorgabe = Thema des Termins, das LLM wählt nur aus ≤ 8 Kandidaten (Begriffs-Index, Hierarchie) |
| Sammel-Aufgaben zerlegen | LLM | Personen löst der Code auf |
| Stand-Prosa | LLM | gut bei sauberem Log |
| Ampel, offene Punkte, Fristen, Alter | Code | das LLM lag bei der Ampel daneben |
| Personen | Code | Teilnehmer + E-Mail, Themen-Team, gelernte Regeln; sonst Rückfrage |
| Modellierungsurteile (Kanon, Beziehungen) | Mensch | siehe §12 |

Regeln: eine Aufgabe pro Aufruf, JSON-Schema, `enable_thinking: false`, Kontext ≤ ~8k Tokens (Ausnahme:
die Prüfstufe der Nachbereitung sieht das ganze Material, bis 150 000 Zeichen), jede Ausgabe wird im
Code validiert, nichts wird ungeprüft geschrieben.

## 7. LLM-Betrieb

Ein OpenAI-kompatibler Server (z. B. llama.cpp) im eigenen Netz; Adresse und Modell stehen in
`.2ndbrain/llm.config.json`. Eine Warteschlange (Server `--parallel 1`), offline-tolerant (Aufgaben
warten, bis der Server erreichbar ist), Ergebnisse als Markdown im Vault → überall lesbar, auch am
Handy. **Nie live im Termin rechnen** — was im Termin gebraucht wird, ist vorberechnet.

**Zwei Modelle.** `model` rechnet alles – Chat, Einarbeiten, Stand, den Entwurf der Nachbereitung.
`model_pruefung` (leer = keine Prüfung) prüft nur den Entwurf der Nachbereitung (→ 4.6). Im Vergleich
war ein schnelles Modell für den Entwurf plus ein gründlicheres für die Prüfung besser als jedes allein:
vollständigere Entscheidungen und Aufgaben, keine Doppelten; ein guter Entwurf bleibt, wie er ist. Die
Prüfung kostet einige Minuten je Termin (lädt der Server nur ein Modell zur Zeit, kommt der Wechsel
dazu) – vertretbar bei ein, zwei Nachbereitungen pro Stunde. Beide Modelle wählt man in den
Plugin-Einstellungen aus der Liste des Servers (`/v1/models`).

**Das beste Modell zuerst.** `modelle` in `llm.config.json` ist die Reihe der Modelle, das beste zuerst
(ohne Liste: `model`, dann `model_pruefung`). Jeder Lauf beginnt beim besten. Lehnt der Server ein Modell
ab (gesperrt, unbekannt), kommt das nächste der Liste und wird in diesem Lauf nicht noch einmal gefragt;
ein Modell außerhalb der Liste springt nie ein, auch wenn der Server es anbietet. Welches Modell eingesprungen
ist, steht im Ergebnis des Laufs (`llm_ersatz`) und an der Termin-Notiz (`modell_ersatz`).

**Gesperrtes Modell anfordern (Lease).** Gibt der Server gerade nur ein Modell frei und lehnt ein anderes mit
409 ab, fordert die Engine es an und fragt es noch einmal – auch für die Prüfstufe (`modell.lease_anfordern`).
Sie hält sich an den Lease-Vertrag des Servers (Laib, ADR 0011): Rumpf genau `{model, ttl_s, holder}` mit dem
Halter `2ndbrain`; lädt das Modell noch (202), fragt sie den Stand ab, statt noch einmal zu senden; solange sie
die Lease hält, verlängert sie alle `renew_after` Sekunden; eine liegengebliebene eigene Lease gibt sie zuerst
zurück. Eine Lease kostet den Haushalt etwas (Spracherkennung und Einbettungen ruhen). Deshalb fordert die
Engine nur an, wenn seit zehn Minuten niemand das Modell gefragt hat (`last_human_at`), gibt nach dem Schritt
zurück, der sie brauchte (`lease_freigeben` in `auto.py`, sonst am Prozessende), und kennzeichnet ihre eigenen
Aufrufe als unbeaufsichtigt (`X-Laib-Background`). Hält ein anderer Dienst den Server, steht sein Name und
das Ende in der Meldung. Dafür
braucht sie den Modell-Schlüssel des Servers: Er liegt im Obsidian-Schlüsselbund (Einstellungen →
Modell-Schlüssel), das Plugin reicht ihn je Lauf als `VAULT_LLM_KEY` herein; er steht in keiner Datei und in
keinem Protokoll. Ohne Schlüssel oder wenn der Server ablehnt, gilt die Reihe der Modelle wie oben; fällt die
Prüfstufe aus, steht das mit Ursache an der Termin-Notiz (`pruefung_ausgefallen`).

**Störungen mit Ursache und Ausweg.** Jede Störung der Verbindung bekommt eine Art (`modell.fehler_einordnen`:
kein Server, nicht erreichbar, gesperrt, unbekanntes Modell, Abbruch, Zeitlimit, abgelehnt), eine Ursache in
einem Satz und einen Ausweg – nie nur „HTTP 409“. Ein Abbruch mitten im Aufruf wird einmal wiederholt. Fehlt
das Modell, laufen die Schritte ohne es weiter; das Ergebnis des Laufs sagt, warum es fehlte (`llm_fehler`),
und das Plugin zeigt Ursache, betroffene Schritte und Ausweg im Fenster „Automatik – letzter Lauf“.
`2ndbrain modell --diagnose` prüft Schritt für Schritt (Adresse, Server, Modell, Antwortformat, Werkzeuge)
und hält beim ersten Fehler; im Plugin ist das der Knopf „Diagnose starten“.

**Antwortgrenze nach Eingabe.** Prüfstufe und Protokoll bekommen eine Antwortgrenze, die mit dem Material
wächst: etwa ein Viertel der Eingabezeichen in Tokens, 4096 bis 12288 (`modell.antwort_tokens`) – eine
feste Grenze schnitt lange Termine ab. Langes Material wird für den Entwurf an Absatz-, Satz- oder
Wortgrenzen geteilt, nie mitten im Wort.

## 8. Oberflächen (Obsidian-Plugin)

Heute (ganz oben der Fokus (§20) und „Ohne Notizen“, dann Radar, eigene Aufgaben, Termine mit Phase, Nachfassen) ·
Anleitung für Benutzer (ins Plugin eingebaut, `plugin/anleitung.md`, eigene Ansicht; „?“ in Heute und
oben in den Einstellungen) · Cockpit-Seiten über Codeblöcke
(```` ```2ndbrain aufgaben ```` / `risiken`, ohne JavaScript in der Notiz) · Sofortsuche (Stand und
offene Punkte ohne LLM-Wartezeit) · Nacherfassen und Nachbereiten · Chat mit Rezepten und Bildern
(rechnet ganz im Plugin; nur der Frage-Modus „Offene Fragen“ läuft über die Engine). Welche Teile wo
laufen: §18.

**Bilder im Chat** zeichnet der Code aus den Daten, nicht das Modell: Themenbaum, Verlauf, Beteiligte,
Reihen und **Kontexte** – wie Subdomänen und Kontexte des Domain Atlas zusammenspielen (die Nachrichten
aus dem Kontext-Verzeichnis, durchgezogen = abgestimmt, gestrichelt = offen), darunter die Systeme, die
sie umsetzen (`atlas_kontexte`), mit den Nachrichten auf die Systeme übertragen.

**Was gemeint ist, versteht das Modell – was gezeichnet wird, entscheidet der Code** (`core/absicht.ts`):
Das lokale Modell bekommt die Frage, den Bezug (offene Notiz, gewählter oder voriger Bezug, mit IDs) und
eine feste Liste – Bild-Arten, Themen, Subdomänen, Kontexte – und wählt daraus (JSON, kurzer Aufruf mit
eigenem Zeitlimit). Tippfehler, „und“ statt „&“, Teilnamen, Englisch und „den Kontext“ löst es auf. Der
Code prüft die Wahl: nur IDs aus der Liste; Atlas-Einträge zeichnet nur das Kontext-Bild, ein Verlauf
braucht ein Thema, „zeichne/Bild/Diagramm“ ist immer ein Bildwunsch; wählt das Modell viele Kontexte
einer Subdomäne, gilt die Subdomäne. Personen bestimmen weiter die Regeln (nie geraten). Ohne Modell
oder bei unbrauchbarer Antwort gelten die Regeln: Bildwunsch nur mit „zeichne“, „Bild“, „Diagramm“ …
(„zeig“ nur mit einer Bild-Art, „Sag mal …“ nie), Atlas-Namen wortgleich oder mit kleinem Tippfehler,
ein nur ungefähr passender Name führt zur Rückfrage – nie still der alte Bezug. Eine Frage nach
Kontexten bekommt nie den Themenbaum. Den Bezug kann man im Chat einzeln entfernen oder neu wählen
(Thema, Person, Subdomäne, Kontext). Treffsicherheit an echten Fragen: `plugin/tests/absicht.test.ts`
mit `SB_ABSICHT=1 SB_VAULT=<Vault>` und `.2ndbrain/chat-fragen.json` im Vault (Regeln gegen Modell). Jeder Kasten trägt den Pfad seiner Notiz im Hinweistext – ein Klick öffnet sie, im Chat wie
in jeder Notiz (Obsidians Mermaid entfernt obsidian://-Adressen, das Plugin öffnet selbst).

**Fragen über mehrere Schritte** (seit 0.11): Mit der Frage gehen der Ausschnitt, die offene Notiz (bis
8.000 Zeichen, gekürzt mit Gliederung) und das Gespräch (jüngstes zuerst, bis 12.000 Zeichen ≈ 3–4k Token;
Bilder als Vermerk) an das Modell. Reicht das nicht, schlägt es nach – vier Werkzeuge im OpenAI-Format
(llama.cpp mit `--jinja`), nur lesend (`core/werkzeuge.ts`): `search` (Namen, Aliasse, Atlas-IDs,
Volltext), `read` (Notiz, auch einen Abschnitt; Atlas-Eintrag mit Beschreibung und Bezügen; System mit
seinen Verbindungen), `path` (bis zu drei Wege zwischen zwei Punkten über verschiedene
Zwischenstationen) und `neighbors` (Umkreis bis drei Schritte, nach Art filterbar; Termine: direkt
verbundene zuerst, darin die neuesten); dazu die Abfragen aus `core/abfragen.ts` auf denselben Daten wie
Heute und die Cockpit-Seiten – `tasks` (Person, „ich“, Thema mit Unterthemen, Status, Art, überfällig,
Frist, Altbestand), `log` (Risiken, Beschlüsse, Status, Meilensteine, Fristen nach Thema und Zeitraum),
`meetings` (Termin-Notizen und Kalender ohne Notiz, Thema über Reihe oder Titel wie beim Anlegen) und
`query` (Frontmatter: gleich – auch über Links und Namen –, enthält, fehlt, größer/kleiner, sortiert) und
`atlas` (wie `query_canon`/`join_canon` des Atlas-Agenten, aber auf dem Kontext-Verzeichnis im Vault:
Nachrichten nach Typ mit Gegenseite und Owner, Prozesse mit Schritten, Teams mit ihren Kontexten, das
Domänenmodell – Fachobjekte mit Stereotyp und Relationen, im Graphen Kanten mit dem Verb –, Kontexte,
Subdomänen, Beziehungen, Externe; gefiltert nach Kontext, Subdomäne, Team, Typ, Reife);
Filtern und Zählen macht der Code, die Zahlen stehen im Ergebnis. Gleichnamiges (ein Name als Thema,
Begriff, Subdomäne, Team) ist ein Punkt; gelesen wird das Thema zuerst. Passt ein Name dagegen auf mehrere
derselben Art (zwei Personen mit dem Vornamen, nur ungefähr passende Themen, Reihen, Kontexte), nimmt kein
Werkzeug still den ersten: es nennt alle, und das Modell schlägt mit dem vollen Namen nach oder fragt zurück,
wenn Frage, Gespräch und offene Notiz es nicht entscheiden (Regel im Systemprompt, auch ohne Werkzeuge; die
Antwort auf die Rückfrage versteht es aus dem Gespräch). Fragt die Frage nach einer Liste, die der Ausschnitt
nur gekürzt zeigt (Aufgaben, Log), oder nach Terminen – der Ausschnitt kennt nur die mit Notiz, nicht den
Kalender –, schlägt der Code vorab selbst nach, den Zeitraum („nächste Woche“, „morgen“) rechnet er aus;
eine Bitte ans Modell reichte nicht. Die Wartezeile zeigt Runde,
Werkzeug und Schritt. Grundlage ist ein
**Wissensgraph** (`core/graph.ts`, am Desktop wie am Handy, vom Plugin vorgehalten und nach Änderungen
neu gebaut): Knoten sind alle sichtbaren Notizen und die Einträge des Kontext-Verzeichnisses, Kanten
[[Links]], Felder im Frontmatter (auch Slugs ohne Klammern wie `themen:` eines Termins), Atlas-IDs im
Text, die Bezüge im Atlas und die Verbindungstabelle der Systemübersicht. Ein Knoten kostet als
Zwischenstation umso mehr, je mehr Verbindungen er hat (1 + ln(1 + Grad)); die eigene Person und
Berichte, Übersichten, Verzeichnis und Vorlagen sind nie Zwischenstation – sonst liefe jeder Weg
darüber. Punkt-Ordner gehören nicht zum Graphen (Konfiguration, Schlüssel, Papierkorb). Grenzen der
Schleife: vier Runden mit Werkzeugen, dann antwortet das Modell (die Werkzeuge bleiben im Prompt,
`tool_choice: none` – der Server rechnet den Anfang aus dem Zwischenspeicher); drei Aufrufe je Runde,
acht je Frage, 6.000 Zeichen je Ergebnis, 40.000 zusammen; gleiche Aufrufe laufen einmal. Kennt der
Server keine Werkzeuge, antwortet das Modell wie früher in einem Schritt. Was Notizen, Mails und
Dokumente sagen, ist Material, keine Anweisung; Bilder von außen und HTML in Antworten werden Text (ein
Bild mit Daten in der Adresse könnte sonst beim Anzeigen etwas nach außen tragen). Probelauf an echten
Fragen: `plugin/tests/mehrschritt.test.ts` mit `SB_MEHRSCHRITT=1 SB_VAULT=<Vault>` und
`.2ndbrain/chat-fragen-mehrschritt.json` im Vault (`SB_FRAGEN=<Datei>` nimmt eine andere Fragen-Datei).

## 9. Aufbau

| Teil | Ordner im Repo | Läuft |
|---|---|---|
| Obsidian-Plugin (TypeScript) | `plugin/` | Desktop und Handy; über Obsidian installiert und aktualisiert |
| Engine (Python, Paket `2ndbrain`, Modul `secondbrain`) | `engine/secondbrain/` | Desktop; `python -m pip install`, Befehl `2ndbrain` |
| Vorlagen für einen neuen Vault | `engine/secondbrain/vorlage/` | `2ndbrain einrichten` legt an, was fehlt (die Anleitung steckt im Plugin) |
| Entwickler-Werkzeuge | `engine/tools/` | nur im Code-Repo: Referenzlauf, Entdrahtung, Plugin- und Prompt-Vergleich |

Im Vault liegt kein Code. Konfiguration, Chat-Rezepte, Protokoll-Vorlage und Daten des Vaults stehen
in `.2ndbrain/` (`llm.config.json`, `local.config.json`, `chat-skills/`, `protokoll-vorlage.md`,
`daten/`). Die Engine findet den Vault über `VAULT_DIR` (so startet sie das Plugin, so steht es im
MCP-Befehl) oder ab dem aktuellen Ordner; ohne Vault bricht sie ab. Plugin und Engine tragen dieselbe
Version; das Plugin prüft die Version der Engine und bietet Installieren und Aktualisieren an
(„Obsidian-nah in der Bedienung, nicht in der Verpackung“ – die Engine läuft auch ohne Obsidian:
MCP, Automatik, Befehlszeile). Fest eingetragen ist keine Version: „Installieren“ holt die Engine zur
Version des Plugins (aus seinem Manifest). Ein Update kommt also über das Plugin (BRAT); passt die Engine
danach nicht mehr, meldet sich das Plugin einmal mit „Engine aktualisieren“ – ein Klick, denn selbst
installieren soll ein Plugin nichts. „Immer die neueste Engine“ wäre schlechter: Plugin und Engine teilen
Formate (etwa das Kontext-Verzeichnis) und Befehle. Ein Release: `python scripts/version.py <v>`, Commit,
Tag `<v>` (ohne „v“) – der Workflow testet, baut und legt es an. Das Engine-Paket liegt dem Plugin bei: der Build legt
`2ndbrain-<version>-py3-none-any.whl` neben `main.js`, „Installieren“ nimmt es von dort (sonst eine eigene
Quelle aus den Einstellungen, zuletzt ein GitHub-Release). Lehnt das Python des Systems pip ab (Homebrew,
PEP 668), bekommt die Engine eine eigene Umgebung `~/.2ndbrain/venv`, deren Python eingetragen wird. Python
sucht das Plugin am Mac nicht nur über den PATH – Programme aus Finder oder Dock bekommen nur
`/usr/bin:/bin:/usr/sbin:/sbin` –, sondern auch in Homebrew, python.org, pyenv und MacPorts (der
Xcode-Platzhalter `/usr/bin/python3` zuletzt); Engine und LikeC4-Explorer bekommen diese Ordner in den PATH.

## 10. Leitlinien

- Jede Verhaltensänderung bekommt einen Regressionstest; die Suite bleibt grün. Tests bauen sich
  eigene Vaults und fassen nie einen echten an.
- Erst die lesende Seite kompatibel machen, dann die schreibende umstellen, dann Daten migrieren.
- Migrationen: Probelauf ist Standard, Prüfbericht vor Übernahme, nichts wird gelöscht (Papierkorb).
- Ein Format = ein Modul (`aufgaben.py`, `vault_paths.py`); das Plugin überträgt es und wird mit
  `2ndbrain plugin-vergleich` gegen die Engine geprüft.
- LLM formuliert, Code entscheidet und schreibt. Modell-Einordnungen sind Hinweise (`art`, „bitte
  prüfen“); zurückweisen, löschen, Status ändern entscheidet der Mensch.
- Belege vor Prompt: erst prüfen, was das Modell zu sehen bekommt (Stichprobe), dann laufen lassen.
- Kommentare beschreiben, was gilt und warum – nicht, wie es früher war.
- Läuft auf Windows, macOS und Linux; keine Zugangsdaten im Code. Die Kalender-Adresse wirkt wie ein
  Zugangsschlüssel und liegt im Obsidian-Schlüsselbund.
- Plugin: TypeScript strict, esbuild, Obsidian-API statt globaler Objekte (`registerEvent`,
  `processFrontMatter`, `requestUrl`), Aufräumen in `onunload`; lädt am Handy ohne Node-Modul.

## 11. Grenzen

- Die Engine braucht einen Desktop mit Python; am Handy wird gelesen, erfasst und gefragt, nicht
  eingearbeitet.
- Ohne Modell-Server gibt es Fakten (Ampel, offene Punkte, Fristen), aber keine Texte (Stand-Prosa,
  Nachbereitung, Glossar-Vorschläge, Chat-Antworten).
- Personen werden nie geraten: Was nicht eindeutig ist, wird eine Rückfrage in `04_Clarifications.md`.

## 12. Vorschläge an den Kanon und die Systemübersicht

**Ziel.** Was in Terminen über Kontexte, Objekte, Nachrichten, Partner und Abläufe gesagt oder
entschieden wird, kommt als prüfbarer Vorschlag im Kanon an – statt im Protokoll liegen zu bleiben.

**Leitplanken.**
- Der Kanon bleibt die einzige Quelle der Wahrheit. Der Vault schreibt **nie** in den Kanon; er liefert
  Fragen mit Belegen. Übernommen wird über den Weg, den der Kanon selbst vorsieht (etwa Review mit
  zweiter Person); die Hausregeln einer Organisation stehen in `kanon.regeln` der Konfiguration, nicht im
  Code.
- Modellierungsurteile (welches Element, welche Richtung, gehört ein Kunde in den Kanon) trifft der
  Mensch – das lokale Modell formuliert nur.

**Vorschlagsarten.**

| Befund im Vault | Beispiel | Vorschlag an den Kanon |
|---|---|---|
| Beschluss zu Zuständigkeit | „alle Kontexte der Auftragsannahme an Team X“ | Owner-Änderung |
| oft benutztes Fachwort, nicht im Kanon | Glossar-Begriff, oft in Terminen des Bereichs (`atlas.bereich`) | Alias (die Langform kennt der Kanon), neuer Fachbegriff oder – bei „…-Team“ – neues Team |
| Partner/System in vielen Terminen | ein Dienstleister, ein Fremdsystem | Externer + Beziehung |
| „X übergibt an Y“, Schnittstelle | zwei Kontexte, mehrfach genannt | Beziehung (Typ = Urteil → Frage) |
| Ablauf in Schritten beschrieben | ein Prozess aus einem Workshop | Prozess-Entwurf, fehlende Nachrichten |
| Termin widerspricht dem Kanon | Owner/Status weicht ab | Review-Frage |

**Ablauf (`2ndbrain kanon-vorschlaege`).**
1. *Abrufen*: Der Code sucht in den Themen-Logs Kandidaten mit Beleg – ohne Modell: Zuständigkeit,
   Externe, Beziehungen, Abläufe; im Glossar Begriffe, die dem Kanon fehlen (Firmen und Systeme fragt
   „Extern“ ab, Protokoll-Floskeln fallen weg); dazu Fragen zur Systemübersicht (Bereich, Verbindung). Höchstens
   einige Fragen je Abruf, die wichtigsten zuerst.
2. *Entscheiden*: in den Begriffen des Kanons („Ja – Partner mit Schnittstelle“, „Nein – keine
   Schnittstelle“, „Typ im Kanon klären“ – nie geraten). Im Bericht ankreuzen oder im Chat klicken
   (Frage-Modus „Offene Fragen“).
3. *Übernehmen*: „Ja …“ kommt ins Review-Paket (`reports/atlas-review-<datum>.md`) mit Vorschlag und
   Belegen; „Nein …“ wird als Einordnung festgehalten und nicht wieder gefragt; Systemfelder werden
   direkt eingetragen, die Systemübersicht neu erzeugt.
4. *Einarbeiten*: im Repository des Kanons, auf dessen Weg.

**Systemübersicht (`2ndbrain systemuebersicht`).** Ein LikeC4-Modell, erzeugt aus den System-Seiten und
der Themen-Landkarte, wegwerfbar: Bereich = Feld `bereich` > Produkt-Thema > meistnennendes Thema;
`ersetzt` → „löst ab“; `verbindungen` von Hand; belegt = zwei Systeme im selben Log-Eintrag mit
Schnittstellen-Wort, ab zwei Einträgen. Owner: Feld `owner` (Person) vor `owner_team`; Beschreibungen als
Klartext (ohne Obsidian-Links). Sichten je Bereich, `likec4 validate` + Layout-Prüfung. Das
Plugin startet den LikeC4-Explorer lokal (`127.0.0.1`, abschaltbar). Ein Modell-Ordner gehört genau
einem Vault (Kopfzeile); ein fremder Ordner wird nicht überschrieben.

## 13. Entdrahtung: der Code kennt keine Namen

Engine und Plugin enthalten nur Mechanik und erfundene Beispiele – keine Firma, keine Menschen, keine
Systeme eines echten Vaults. Wissen gehört in den Vault (Seiten, `.2ndbrain/local.config.json`: eigene
Person, Organisation, interne Mail-Domains, Rauschwörter fürs Glossar, Regeln für den Kanon).

Prüfen: `2ndbrain entdrahtung` gleicht Code, Tests, Vorlagen, Chat-Rezepte, Plugin und Doku mit den
Namen des eigenen Vaults ab: Personen (auch Vornamen allein), Firmen, Systeme, Teams, Themen, Reihen,
Aliasse, Titel aller Termine und Mails (auch früherer), Kalender-Einträge, Organisation, Mail-Domains,
private IP-Adressen, Benutzerpfad. Namen des Vaults, die zugleich allgemeine Wörter sind (ein Team
„Reporting“), stehen als Ausnahme in `local.config.json` unter `entdrahtung.allgemein` – nicht im Code. Vor einem Umbau `2ndbrain referenz --speichern NAME`, danach
`--vergleichen NAME`: zehn Proben rufen dieselben Funktionen wie die Engine auf, nur lesend, ohne
Modell; jede Abweichung muss begründet sein.

## 14. Kalender und Kanon

**Kalender: jedes iCal.** `ical.py` liest RFC 5545 ohne Zusatzpakete: Parameter, Zeitzonen aus
VTIMEZONE (Sommerzeit), UTC, Serien (DAILY/WEEKLY/MONTHLY/YEARLY mit INTERVAL, COUNT, UNTIL, BYDAY,
BYMONTHDAY, BYMONTH, WKST), RDATE, EXDATE, verschobene und abgesagte Einzeltermine, eigene Absagen.
Quelle: https, webcal oder eine .ics-Datei (Outlook, Google, iCloud, Nextcloud …). `kalender.py`
schreibt `archive/calendar/events.json` (Vorbereitung, Plugin) und `kalender.md` (zum Lesen).

**Kanon.** `kanon.py` ist eine Leseschicht mit allgemeinem Modell (Kontexte mit Owner und Subdomäne,
Fachbegriffe, Teams, Externe, Nachrichten, Beziehungen, Abläufe) und Adaptern: `domain-atlas` und
`einfach` (eine YAML-Datei, Vorlage `kanon.example.yaml`). Das Regelwerk (Präfixe, Texte,
Vorschlags-Vorlagen) hängt am Format.

## 15. Fremdtext wird nie Code

Dataview führt `dataviewjs`-Blöcke beim Anzeigen als JavaScript aus, am Desktop mit Zugriff auf Dateien
und Prozesse. Fremder Text – Mails, Dokumente, Anhänge, Mitschriften, jede Antwort des Modells – darf
deshalb nie ausführbarer Code werden: `fremdtext.entschaerfen()` macht ausführbare Blöcke zu
gewöhnlichen, `zaun()` legt Text in einen Codeblock, aus dem er nicht ausbrechen kann. Die
Cockpit-Seiten brauchen kein JavaScript (Codeblock `2ndbrain`); „Enable JavaScript Queries“ in
Dataview kann aus bleiben.

## 16. Einarbeiten mit dem lokalen Modell

Alles im Eingang (`inbox/`: Mails, Dokumente, Anhänge, Transkripte) wird eingearbeitet
(`2ndbrain einarbeiten`): Das Arbeitspaket (`arbeitspaket.py`) fasst Mail und Anhänge zu einem Vorgang
zusammen, bringt bekannte Themen und Personen, aufgelöste Begriffe und Daten mit; strukturierte Notizen
gehen ohne Modell durch. Das Modell liefert nach festem JSON-Schema Ereignisse je Thema, Zusagen, neue
Personen/Firmen/Systeme – Themen nur aus der Liste; Unklares wird eine Rückfrage. `uebernehmen.py`
schreibt, `eingang_abschluss.py` schließt ab und legt ins Archiv.

Sicherheit: `--probelauf` schreibt nichts außer einem Bericht. Jedes Paket sichert vorher alle Dateien,
die es ändern kann; `--rueckgaengig <notiz>` stellt sie wieder her. In der Automatik erst nach Freigabe
(`"einarbeiten": {"automatisch": true, "je_lauf": 3}` in `local.config.json`).

## 17. Wissen hält sich selbst aktuell

Begriffs-Index, Kontext-Verzeichnis und Glossar laufen als Schritt `wissen` der Automatik, sobald sich
ihre Quellen ändern (sonst kostet der Schritt nur ein paar `stat`-Aufrufe).

**Kontext-Verzeichnis** (`kontexte.py`, `entities/contexts/_index.md`): Subdomänen, Kontexte und die
Nachrichten zwischen ihnen (Typ, Reife, von, an; eine Kante mit eigener Reife in Klammern) – als
Tabellen, lesbar für Menschen und fürs Plugin, das daraus am Handy wie am Desktop das Bild „Kontexte“
zeichnet. **Kontexte und Systeme** (`kontext_systeme.py`): Vorschläge mit Beleg, welches System welchen
Kontext umsetzt, als Liste zum Abhaken (`reports/kontext-systeme.md`); die Haken landen als
`atlas_kontexte` auf der System-Seite, ein entfernter Haken nimmt die Zuordnung zurück.

**Glossar** (`glossar.py`): zählen → Kanon → Bestand → Modell.
- Gezählt wird nur, was Menschen geschrieben haben: keine Kalender-Exporte, Vorlagen, Code- und
  Diagrammblöcke, automatischen Blöcke, Log-Markierungen, Link-Ziele, fette Beschriftungen; Wörter, die
  die Engine selbst schreibt, werden aus ihrem Code gelesen.
- Eine **neue** Seite entsteht nur für einen Begriff aus mindestens drei Notizen, der auf keiner
  Stoppliste steht (Stoppwörter und allgemeine Abkürzungen gelten für Begriffe und Abkürzungen,
  dazu eigene Rauschwörter aus der Konfiguration), keine Person und kein Termintitel ist – und nur,
  wenn das Modell ihn als Fachbegriff, System, Organisation oder Abkürzung einordnet. Kürzel aus zwei
  Buchstaben nur, wenn die Langform in einer Notiz ausgeschrieben ist („Change Request (CR)“) –
  sonst rät das Modell.
- Je Lauf höchstens 8 Begriffe fürs Modell; Eingeordnetes wird erst bei geänderten Fundstellen wieder
  gefragt. Bestehende Texte werden nie überschrieben; Definitionen des Kanons gelten ohne Modell.

## 18. Handy liest und erfasst, Desktop rechnet

| Teil | läuft | Inhalt |
|---|---|---|
| `src/core/` (TypeScript) | überall: Desktop, Handy, Node-Tests – ohne Obsidian, ohne Node | Aufgaben (lesen, abhaken), Themen-Log, Risiken, Termine/Themen/Personen, Nacherfassen, Chat |
| Obsidian-Anbindung (`main.ts`, `views/`) | Desktop und Handy | Heute, Cockpit-Seiten, Sofortsuche, Nacherfassen, Chat, Einstellungen |
| `src/desktop/` | nur Desktop, dynamisch geladen | Engine starten, Python finden, LikeC4 |
| Engine | nur Desktop | Automatik: Kalender, Mails, Einarbeiten, Nachbereiten, Stand, Vorbereitung, Wissen; Frage-Modus „Offene Fragen“; MCP-Server |

Schnittstelle zwischen Handy und Desktop sind die Notizen selbst: Die Engine schreibt Stand-Kasten,
Radar-Felder, Vorbereitung und Glossar in den Vault, jedes Gerät liest sie. Nachbereiten vom Handy ist
eine Vormerkung in der Termin-Notiz (`nachbereiten: angefordert`); die Automatik am Desktop arbeitet sie
ab. Der Stand bleibt in der Engine: ein einziger Schreiber, und der MCP-Server braucht ihn auch bei
geschlossenem Obsidian.

Aufgaben, Themen-Log, Risiken und Nacherfassen gibt es in beiden Teilen: Die Engine braucht sie für
ihre eigenen Schritte, das Plugin rechnet damit am Handy. `2ndbrain plugin-vergleich` prüft auf dem
eigenen Vault, dass beide dasselbe liefern. Den Chat rechnet nur das Plugin.

**Schreiben, während die Engine läuft.** Die Sperre der Automatik (`.2ndbrain/daten/.auto.lock`) sorgt
dafür, dass nur ein Engine-Lauf zur Zeit rechnet. Das Plugin wartet auf sie nicht mehr für jede Notiz:
Gefährlich ist nur eine Notiz, die die Engine liest, lange rechnen lässt und dann aus dem alten Stand
zurückschreibt. Das tut allein die Nachbereitung mit ihrem Termin; sie trägt ihn, solange das Modell
rechnet, in `.2ndbrain/daten/.in-arbeit.json` ein (`inarbeit.py`) und überschreibt ihn nicht, wenn er sich
in der Zeit geändert hat (Editor) – dann bleibt die Vormerkung stehen. Der Stand eines Themas setzt seinen
Block in den aktuellen Text ein. Das Plugin (`core/inarbeit.ts`) schreibt jede andere Notiz sofort
(Nacherfassen, Abhaken); läuft keine Engine, nimmt es dafür kurz die Sperre. Nur bei dem Termin in Arbeit
wartet es: die Änderung steht in den Plugin-Daten (übersteht einen Neustart) und kommt dazu, sobald er frei
ist – bei „Speichern und nachbereiten“ mit neuer Nachbereitung; gibt es den Termin nicht mehr, landen die
Notizen als „Nachtrag“ in `inbox/`. Die übrigen Schritte der Automatik lesen und schreiben eine Notiz in
Millisekunden – wie das Tippen im Editor.

**Fehler der Automatik sichtbar machen.** Jeder volle Lauf (nicht `--only`, `--note`, `--dry-run`) landet mit
allen Schritten in `.2ndbrain/daten/auto_letzter_lauf.json`, auch Läufe aus der Aufgabenplanung. Gemeldet
wird die ganze Meldung eines Unterprogramms ab der Zeile mit `ERROR`/`FEHLER`, mit Hilfetext, nicht nur die
letzte Zeile (`einlesen._meldung`). Scheitert ein Schritt unerwartet, kommt das Ende des Tracebacks dazu.
Das Plugin (`core/automatik.ts`, `views/automatik.ts`) zeigt den Lauf hinter „mit Fehlern“ in Heute, über
den Befehl „Automatik: letzter Lauf“ und über „Details“ in der Meldung. Gescheiterte Schritte stehen
zuerst, für bekannte Fälle mit dem Ausweg: Kalender-Adresse je Gerät, fremder Modell-Ordner,
fehlendes Paket, Modell-Server, fehlender Pfad. „Bericht kopieren“ liefert denselben Inhalt als Text,
mit Plugin- und Engine-Version, System und Python; die Kalender-Adresse ersetzt das Plugin dabei durch
`<Kalender-Adresse>`. Liefert die Engine kein JSON, behält das Plugin Code, Dauer und die letzten 40 Zeilen
ihrer Fehlerausgabe. Ein Lauf im Hintergrund meldet sich nur, wenn ein Schritt neu scheitert. Sonst
stünde alle 20 Minuten dieselbe Meldung da.

Für das Handy: Das Plugin lädt dort ohne Node-Modul; die Sperre der Automatik schreibt es nur am
Desktop; Frontmatter ändert es zeilengenau (kleine Änderungen, die der Sync zusammenführen kann);
„ich“, Modell-Adresse und Chat-Rezepte kopiert es am Desktop in seine eigenen Daten, weil Ordner mit
Punkt nicht jeder Sync mitnimmt.

## 19. Begriffe

Ein Begriff, ein Name – in der Oberfläche, in den Befehlen und im Code. Die Engine benennt Module und
Befehle deutsch; das Plugin folgt bei den Dateinamen, im Code selbst stehen englische Bezeichner.

| Begriff | im Vault | Befehl | Engine-Modul | Plugin-Datei |
|---|---|---|---|---|
| Thema | `entities/projects/`, Feld `themen:` | `thema`, `thema-neu` | `themen.py`, `thema_anlegen.py` | `core/themen.ts`, `views/themen.ts` |
| Reihe (Gremium, wiederkehrender Termin) | `entities/forums/` | `reihen`, `reihe-neu` | `reihen.py` | – |
| Termin-Notiz | `active-meetings/`, `archive/meetings/` | – | `vorbereiten.py`, `nachbereiten.py` | `core/ansicht.ts` |
| Archivieren (Termin-Notiz) | `active-meetings/` → `archive/meetings/JJJJ-MM/` | `archivieren` | `archivieren.py` | – |
| Vorbereiten | `## Vorbereitung`, `## Agenda` | `vorbereiten` | `vorbereiten.py`, `agenda.py`, `briefing.py` | – |
| Nachbereiten | `## Entscheidungen`, `## Actions` | `nachbereiten` | `nachbereiten.py`, `nachbereiten_modell.py` | `views/nacherfassen.ts` |
| Nacherfassen | `## Meine Notizen` | `nacherfassen` | `nacherfassen.py` | `core/nacherfassen.ts` |
| Offener Punkt / Aufgabe / Frage | `## Actions`, `## Offene Punkte` | `aufgaben` | `aufgaben.py` | `core/aufgaben.ts` |
| Themen-Log | `## Event Log` | – | `uebernehmen.py`, Automatik-Schritt `themenlog` | `core/themenlog.ts` |
| Stand, Ampel | Stand-Block, Feld `health` | `stand`, `risiken` | `stand.py`, `ampel.py` | `core/risiken.ts` |
| Rückfrage | `04_Clarifications.md` | `rueckfragen` | `rueckfragen.py` | – |
| Eingang, Einlesen | `inbox/` | `einlesen` | `einlesen.py`, `mails.py`, `auspacken.py`, `dokumente.py`, `nachfuellen.py` | – |
| Einarbeiten | `inbox/` → `archive/` | `einarbeiten` | `einarbeiten.py`, `arbeitspaket.py`, `eingang.py`, `eingang_abschluss.py`, `zerlegen.py`, `ausgabe_pruefen.py` | – |
| Kanon | externes Repo (z. B. Domain Atlas) | `kanon-vorschlaege`, `kontexte` | `kanon.py`, `kanon_vorschlaege.py`, `kontexte.py` | `core/atlas.ts` |
| Kontexte und Systeme | Feld `atlas_kontexte:`, `reports/kontext-systeme.md` | `kontext-systeme` | `kontext_systeme.py` | `core/chatBilder.ts` |
| Anleitung | – (im Plugin) | – | – | `anleitung.md`, `views/anleitung.ts` |
| Begriffs-Index, Glossar | `.2ndbrain/daten/`, `entities/glossary/` | `begriffe`, `glossar`, `wissen` | `begriffsindex.py`, `glossar.py`, `wissen.py` | – |
| Personen | `entities/people/` | `personen`, `person-neu`, `umbenennen` | `personen.py`, `personen_namen.py`, `beteiligte.py`, `anlegen.py`, `umbenennen.py`, `zusammenfuehren.py`, `aufloesen.py` | `views/personen.ts` |
| Modell (lokales LLM) | `.2ndbrain/llm.config.json` | `modell` | `modell.py`, `modell_ausgabe.py` | `core/modell.ts` |
| Chat, Rezepte | `.2ndbrain/chat-skills/` | `frage` (nur „Offene Fragen“) | `frage.py` | `core/chat.ts`, `core/rezepte.ts`, `views/chat.ts` |
| Protokoll | `.2ndbrain/protokoll-vorlage.md`, `## Protokoll` | `nachbereiten` | `protokoll.py` | – |
| Protokoll zuordnen (Eingang → Termin) | `inbox/` → Termin-Notiz, `archive/protokolle/` | `protokolle` | `protokolle.py` | – |
| Schreibweise (Verschreiber eines Namens) | Feld `schreibweisen:`, `reports/schreibweisen-review.md` | `schreibweisen` | `schreibweisen.py` | – |
| Automatik | `.2ndbrain/daten/.auto_state.json`, `auto_letzter_lauf.json` | `auto` | `auto.py` | `main.ts`, `core/automatik.ts`, `views/automatik.ts` |
| Fokus, Nordstern, Fokus-Spiegel | Felder `fokus`, `ziel`, `target_date`; `reports/fokus-spiegel.md` | `fokus` | `fokus.py` | `core/fokus.ts`, `views/fokus.ts` |
| Rolle je Thema | Feld `meine_rolle` | `rollen` | `rollen.py` | `core/rollen.ts`, `views/rollen.ts` |
| Offene Punkte prüfen (verstummt, erledigt laut Log) | `reports/geprueft.md`, `.2ndbrain/daten/pruefung_state.json` | `pruefen` | `pruefung.py` | – |
| Punkt ändern mit Hinweis, Log-Zeile | Unterpunkt an der Quelle, `reports/geprueft.md` | `punkt` | `aendern.py` | `core/aufgaben.ts`, `views/punkt.ts` |
| Thema abschließen, wieder öffnen | Felder `status: done`, `abgeschlossen`, `abschluss_grund` | `thema-schliessen` | `thema_schliessen.py` | `views/themaSchliessen.ts` |
| Rückfragen mit Hinweis | `04_Clarifications.md` (`> Hinweis:`) | `rueckfragen abhaken` | `rueckfragen.py` | `core/rueckfragen.ts`, `views/rueckfragen.ts` |
| Durchsprechen | – | `durchsprechen` | `durchsprechen.py` | `views/durchsprechen.ts` |
| Einstieg für Agenten (Karte, Themen-Verzeichnis) | `CLAUDE.md`, `reports/themen.md` | `einstieg` (in der Automatik mit `stand`) | `einstieg.py` | – |
| Befehlszeile | – | `help` | `befehle.py` | `desktop/engine.ts` |

## 24. Wenig vorlegen: Stand als Delta, Briefing ohne Schablone, Lagebild

Die Engine erfasst mehr, als man lesen kann. Was sie vorlegt, ist deshalb begrenzt und sagt zuerst, was sich
geändert hat (Befund 17.11.2026 am eigenen Vault: 13 Briefing-Zeilen mit derselben Frage, „20 Risiken“ je Thema).

- **Stand-Block (§4.3).** Vor den Zahlen stehen zwei Zeilen: *Neu (14 Tage)* – die jüngsten Log-Einträge ohne
  Risiken, höchstens drei – und *Braucht dich* – die eigenen offenen Punkte am Thema, die zwei dringendsten
  beim Namen. Risiken stehen in Gruppen („20 in 8 Gruppen – Lager Nord (3), …“): gleiche Stichworte vor
  dem Doppelpunkt oder ähnlicher Wortlaut sind ein Risiko mit mehreren Seiten. Rollen und Beteiligte stehen
  eingeklappt unter dem Block.
- **Briefing.** Höchstens sechs Themen (`briefing.hoechstens`), zwei kritisch, drei wichtig. Eine Frage steht
  nur da, wenn es eine bestimmte gibt (echte offene Frage, verstrichene Frist, mehrfach vertagt, verstummt) –
  keine „Wie steht es um …?“. Die Begründung nennt, was dieses Thema auszeichnet; „als Risiko erfasst“ und
  „Projekt auf rot“ nur, wenn sonst nichts begründet. Ein Vorgänger, der nur über einen ähnlichen Titel unter
  der Schwelle der Historie (0,80) gefunden wurde, gilt nicht als Vorgänger; die Vorbereitung nennt ihn als
  „am ähnlichsten“ und bittet um Zuordnung der Reihe.
- **Jourfix nach Richtung.** Die Vorbereitung eines Jourfix oder 1:1 beginnt je Person mit drei kurzen Listen
  (je höchstens drei Punkte): *Bei X am längsten offen* (mit Alter), *Du schuldest X* und *Zum Übergeben an X*
  (die Übergabe-Vorschläge der Triage an diese Person, §23). „Ich schulde“ heißt: mein offener Punkt stammt aus
  einem Termin dieser Reihe, nennt die Person mit vollem Namen, oder nennt ihren Vornamen in einem Thema, an
  dem sie beteiligt ist – ein Vorname allein ordnet nie zu. Die vollständigen Listen stehen darunter (live).
- **Lagebild** (`reports/lagebild.md`, `2ndbrain lagebild`, in der Automatik mit `stand`): Zusagen je Person als
  Balken mit typischem Alter (fett ab 30 Tagen – „hängt“), das Themen-Radar (offene Punkte gegen Tage seit der
  letzten Bewegung, gemessen am jüngsten Eintrag im Vault, Farbe = Ampel) und die Abläufe des Kanons, jeder
  Kontext in der Ampelfarbe des Themas dahinter (über die Subdomäne oder `atlas_id`).
- **Altbestand auslaufen lassen.** `2ndbrain altbestand --parken` zeigt, welche ungeprüften Alt-Punkte älter als
  60 Tage, ohne Frist und ohne Fokus sind; mit `--anwenden` werden sie `[-]` mit dem Vermerk „Geparkt am …“ –
  aus allen Sichten, nicht gelöscht. Seit 0.13.5 auch in der Automatik (Schritt `pruefen`, §25) – bis dahin
  bewusst nur von Hand; die Entscheidung vom 19.11.2026 lautet: die Automatik darf selbst räumen.

## 25. Offene Punkte prüfen: Rolle je Thema, verstummt, erledigt laut Log

Ein Punkt bleibt offen, bis ihn jemand abhakt – und das tut selten jemand (Befund 19.11.2026 am eigenen Vault:
611 offene Punkte, davon 127 eigene; wortgleiche Dubletten und „schon erledigt“ fand der Code so gut wie
keine – was zu viel ist, steht anders formuliert im Log oder gehört jemand anderem).

- **Meine Rolle je Thema** (`rollen.py`, im Plugin `core/rollen.ts` und „Meine Rolle je Thema“). Feld
  `meine_rolle:` im Frontmatter des Themas: `fuehre` (alle offenen Punkte, auch die der anderen), `beteiligt`
  (nur die eigenen), `beobachte` (keine Punkte anderer). Ein Unterthema ohne Angabe erbt die des Dachs, ohne
  jede Angabe gilt `fuehre`. Die Rolle blendet aus, sie löscht nichts: in „Nachfassen“ (Heute, Cockpit), im
  Lagebild und in „Bei X am längsten offen“ des Jourfix. Die eigenen Punkte bleiben immer; in den Berichten
  der Engine auch die der Personen, die laut Organisation an mich berichten. Den Vorschlag rechnet der Code
  ohne Modell: Fokus-Thema, als `verantwortlich` eingetragen oder mindestens 40 % eigene Punkte (ab fünf
  Punkten) = `fuehre`; nie ein eigener Punkt = `beobachte`; sonst `beteiligt`. Das Fenster im Plugin zeigt vor
  dem Speichern, wie viele Punkte anderer die Auswahl ausblendet. Themen-Seite, Sofortsuche und Chat zeigen
  weiter alles.
- **Verstummt** (`pruefung.py`, ohne Modell). Ein Punkt eines anderen aus einer Reihe, der in den nächsten
  zwei abgeschlossenen Terminen dieser Reihe weder in der Mitschrift noch in Actions oder Entscheidungen
  vorkommt (`nachbereiten.fundstelle`), wird geparkt. Ohne Reihe zählen die nächsten drei Termine desselben
  Themas. Nie: eigene Punkte (die legt die Triage vor), Punkte mit Frist, Fokus-Themen, ungeprüfter Altbestand.
- **Erledigt oder überholt laut Log** (`pruefung.py`, mit Modell). Je Thema bekommt das Modell die offenen
  Punkte und die Log-Einträge (STATUS, DECISION, MILESTONE), die danach kamen, und nennt Punkt, Eintrag und
  einen Belegsatz. Der Code schließt nur, wenn der Eintrag nicht älter ist als der Punkt und der Beleg
  wörtlich (mindestens drei Wörter) darin steht: erledigt = `[x]` mit dem Datum des Eintrags, überholt = `[-]`.
  Je Lauf höchstens vier Themen, die mit den meisten Punkten zuerst; ein Thema, an dem sich nichts geändert
  hat, wird nicht noch einmal gefragt (`.2ndbrain/daten/pruefung_state.json`).
- **Selbst räumen, nachvollziehbar.** Schritt `pruefen` der Automatik (alle sechs Stunden, `2ndbrain pruefen`).
  Jede Änderung steht an der Quelle als Unterpunkt („Erledigt laut Log vom … – automatisch geprüft“, „Geparkt
  am …“) und in `reports/geprueft.md` (jüngster Lauf oben). Zurücknehmen: das Kästchen wieder leeren.
- **Gröber schneiden.** Die Nachbereitung nennt das Ergebnis, das am Ende vorliegen soll, nicht jeden Handgriff
  dorthin; mehrere Aufgaben derselben Person zum selben Gegenstand sind eine (`AUFGABEN_REGEL`).
- **Bewusst nicht gebaut:** andere Quellen als führend (Ticket-System, Planner) – zurückgestellt am 19.11.2026.

### Einstieg für Agenten: Karte und Themen-Verzeichnis

Wer den Vault-Ordner einem Agenten gibt (Claude Code, Cowork), bezahlt nach gelesenem Text. Gemessen am
19.11.2026: rund die Hälfte des Vaults sind archivierte Termine, die Themen-Seiten – die eigentliche
Antwortschicht – etwa ein Zehntel. Ohne Wegweiser liest ein Agent das Teure. `einstieg.py` schreibt deshalb
zwei Dateien, beide ohne Modell und in der Automatik mit dem Schritt `stand`:

- **`CLAUDE.md` im Vault-Stamm, die Karte.** Sie steht in jedem Gespräch im Kontext und ist deshalb knapp
  (unter tausend Tokens): Vorgehen (Verzeichnis → Themen-Seite → suchen → Quelle), Suchmuster für Punkte, Log
  und Themen-Frontmatter – sie treffen die Zeilen selbst, sind also immer aktuell, und zeigen das Format gleich
  mit –, die Fallen der Suche (Checklisten, Altbestand, geerbte Rolle) und die Regeln (nur aus dem Vault mit
  Quelle, Erzeugtes nicht ändern, nichts löschen, der Kalender-Schlüssel bleibt zu). Keine Ordner-Tabelle,
  keine Formatbeschreibung: was sich aus Namen, Muster oder einem Blick in die Seite ergibt, fehlt. Der Text ist fest: er hängt nur an „ich“ und daran, welche Ordner und Berichte
  es gibt – kein Datum, keine Zahlen. Er steht zwischen zwei Marken; eigene Hinweise außerhalb bleiben.
- **`reports/themen.md`, das Verzeichnis.** Eine Zeile je Thema, Unterthemen eingerückt unter ihrem Dach: Art,
  Rolle, Ampel mit Grund, offen (ohne ungeprüften Altbestand), meine, überfällig, Fragen, zuletzt bewegt,
  nächster Termin, Fokus-Rang. Geschrieben wird nur, wenn sich mehr als das Datum geändert hat.

Grundsatz dahinter (Entscheidung 19.11.2026): die Engine führt Buch – Punkte mit Person, Datum und Quelle, Log,
Rollen, Organisation – und rechnet, was ohne Modell geht. Urteil und Synthese auf Nachfrage kann ein großes
Modell aus dieser Buchhaltung selbst leisten; eine neue Ableitung mit dem lokalen Modell muss sich daran messen.

## 26. Von Hand abschließen: Hinweis, Thema, Rückfragen, Durchsprechen

Bis 0.13.6 konnte man nur auswählen: ein Haken an einer Aufgabe, ein Haken an einer Option. Warum etwas
erledigt ist, was beim Einarbeiten zu beachten wäre, dass ein ganzes Vorhaben vorbei ist – dafür gab es keinen
Ort. Seit 0.14.0 (Entscheidung 20.11.2026) gilt: jede Entscheidung von Hand darf einen eigenen Satz tragen, und
der steht an der Quelle.

- **Ein Schreib-Baustein** (`aendern.py`): erledigt, verworfen, übergeben, Frist, Hinweis, umhängen – jede
  Änderung mit Unterpunkt an der Quelle („Erledigt am … (durchgesprochen): …“), nur wenn an der Zeile noch der
  erwartete offene Punkt steht, je Datei von unten nach oben. Status und Hinweis lassen die Zeile, wie sie
  notiert wurde; Person, Frist und Thema schreiben sie kanonisch neu. Dazu `log_eintrag` (eine Zeile oben ins
  Event Log) und `punkt_neu`. Was von Hand geräumt wurde, steht mit im Bericht `reports/geprueft.md`.
- **Hinweis am Punkt** (Plugin, auch am Handy): das ✎ an einer Aufgabe in „Heute“ und in der Aufgabenliste –
  erledigt, verworfen oder nur ein Hinweis, auf Wunsch zusätzlich als `[STATUS]` im Log des Themas
  (`completeInText`, `logEintragInText`; dieselbe Form wie `aendern.py`). Die Triage nimmt je Entscheidung
  einen Hinweis mit (`--hinweis`).
- **Thema abschließen** (`thema_schliessen.py`): Grund (Pflicht), je offenem Punkt des Themas – auf seiner Seite
  und in Termin-Notizen – erledigt, verworfen oder ans Dach-Thema umhängen (ein Punkt auf der Themen-Seite
  zieht mit seinen Unterpunkten um). Vorbelegt: Fragen und ungeprüfter Altbestand fallen weg, das Übrige ist
  erledigt. Das Thema bekommt `status: done`, `abgeschlossen`, `abschluss_grund`; Fokus-Rang und nächster
  Schritt entfallen; im Log steht `[MILESTONE] Thema abgeschlossen: …`. Unterthemen werden angeboten und nur
  mit abgeschlossen, wenn man sie nennt (ihre Punkte werden verworfen). Die Seite bleibt (nichts wird gelöscht);
  das Thema fällt aus Heute, Radar-Ansicht des Plugins, Fokus, Rollen, Lagebild und Themen-Verzeichnis (dort in
  der Fußzeile). Wieder öffnen setzt den Status zurück, die Punkte bleiben geschlossen.
- **Rückfragen mit Hinweis** (`rueckfragen.py`, Plugin-Fenster „Rückfragen“): je Karte die Optionen zum
  Anklicken und ein Feld für einen Hinweis (`> Hinweis: …` in der Karte). Der Hinweis bleibt an der erledigten
  Karte und, wo die Antwort Aufgaben zuordnet, als Unterpunkt an ihnen. Ohne Haken ist er selbst die Antwort:
  ein Name gilt wie eine frei eingetragene Option, sonst nennt das Modell die Nummer der gemeinten Option –
  nennt es keine (oder fehlt es), bleibt die Karte offen und der Hinweis stehen. „Ohne Aktion schließen“
  schließt jede Karte. Am Desktop arbeitet das Plugin die Antwort sofort ein (`rueckfragen abhaken --json`).
- **Durchsprechen** (`durchsprechen.py`, Plugin-Fenster): ein Ausschnitt (Thema, Person, meine Punkte),
  höchstens 60 Punkte nummeriert, dazu Fließtext („A ist durch, B macht jetzt Rita bis Freitag, C vergessen
  wir, entschieden wurde X“). Das Modell ordnet zu, der Code prüft: Nummer aus der Liste; Beleg wörtlich im
  eigenen Text (mindestens zwei Wörter); eine neue Person muss im Text stehen und wird nur bei eindeutigem
  Namen oder Alias zum Verweis; die Frist rechnet der Code aus dem Beleg (`zeitangaben.py`, „3.12.“); Log-
  Einträge und neue Punkte nur für Themen, die es gibt. Die Vorschläge stehen mit Beleg zur Auswahl, geschrieben
  wird erst mit „Übernehmen“, danach steht die Liste neu da. Der Chat selbst bleibt lesend – das Durchsprechen
  ist ein eigenes Fenster mit eigener Prüfung, nicht ein Werkzeug des Chats.

Nicht gebaut: Durchsprechen am Handy (die Engine rechnet am Desktop) und ein Filter in der Radar-Notiz
(`00_Themen-Radar.base`) für abgeschlossene Themen.

## 23. Triage: was mache ich mit meinen offenen Punkten?

„Meine Aufgaben“ ist eine Liste gleich aussehender Zeilen. Die Triage (`triage.py`, im Plugin „Meine Woche“)
macht daraus Vorschläge, die man mit einem Klick bestätigt. Die Regeln rechnet der Code, die erste zutreffende
gilt; das Modell bestimmt nur die Art der Tätigkeit, wo die Wörter sie nicht hergeben (sein Urteil wird gemerkt):

| Vorschlag | Regel |
|---|---|
| Atlas | der Punkt ändert den Kanon (Kontext, Ereignis, Fachobjekt, Landkarte – und ein Wort, das ändert) |
| Nachfassen | der Text nennt jemand anderen als Handelnden („Prüfung durch X“, „X muss …“) |
| Selbst | Fokus-Thema (auch über das Dach-Thema), oder die Tätigkeit ist entscheiden, freigeben, antworten |
| Parken | älter als 60 Tage, ohne Frist, kein Termin zum Thema in den nächsten 14 Tagen |
| Übergeben | die Tätigkeit ist Ausarbeitung, und im Punkt („mit X …“) oder am Thema steht jemand aus der eigenen Linie (§22); wer direkt berichtet, zuerst |
| Selbst | alles andere (Abstimmungen führt man selbst) |

**Matrix.** Übergeben geht nicht nur in der eigenen Linie. `delegation` in `.2ndbrain/local.config.json` nennt
den Fachkreis: `rollen` (Personen, deren Rolle eines der Wörter enthält, z. B. „architekt“), `personen`
(einzelne dazu), `gruppen` (leer = alle). Gruppen sind die Teams (mit Leitung) und die Reihen (die Runden aus
dem Kalender mit den Personen, die dort regelmäßig dabei sind). Rang der Vorschläge: im Punkt genannte Person
(eigene Linie vor Fachkreis) › im Punkt genanntes Team oder genannte Runde › am Thema beteiligte Person › die
Runde, die das Thema behandelt. An ein Team übergeben heißt: die Leitung trägt den Punkt; in eine Runde geben
heißt: der Punkt bleibt bei mir, hängt aber an der Reihe und kommt in ihre nächste Vorbereitung.

Vorgelegt werden höchstens zehn Punkte je Woche: höchstens zur Hälfte Fälliges, dann reihum aus jeder Gruppe. Bestätigen
schreibt an der Quelle des Punkts: bei *übergeben* und *nachfassen* wechselt die verantwortliche Person, darunter
steht eingerückt, von wem und wann – der Punkt erscheint danach unter „Nachfassen“; *parken* macht ihn `[-]` mit
dem Vermerk „Geparkt am …“ (aus den Sichten, nicht gelöscht); *selbst* und *Atlas* lassen den Punkt stehen und
merken die Entscheidung in `.2ndbrain/daten/triage.json`, er wird nicht noch einmal vorgelegt.

## 22. Organisation: wer berichtet an wen

Die Berichtslinie steht auf den Personenseiten; `organisation.py` liest sie und kennt drei Quellen, die
stärkste gewinnt: `berichtet_an: '[[slug]]'` im Frontmatter (von Hand, gilt immer), die disziplinarische Linie
aus dem Verzeichnis („Vorgesetzt: …“ im Abschnitt „Organisation (automatisch)“, oder die Person steht bei
jemandem unter „Direct Reports“), sonst die fachliche Linie des Organigramms („Berichtet fachlich an“). Den
Abschnitt schreibt ein Organigramm-Import; die Engine liest ihn nur. Ändert sich etwas, trägt man
`berichtet_an` ein.

Daraus: das **Verhältnis einer Person zu mir** (berichtet an mich · in meiner Linie · über mir · gleiche
Führungskraft · andere Linie · ohne Platz) als Grundlage für die Einordnung von Aufgaben (übergeben kann man
nur in der eigenen Linie, bei allen anderen fasst man nach) und `reports/orgchart.md` (`2ndbrain orgchart`,
in der Automatik mit dem Schritt `personen`): das Bild der eigenen Linie mit den offenen Zusagen je Person,
die Tabelle der direkten Berichte und die Pflegeliste – Personen mit offenen Zusagen, deren Platz unbekannt ist.

## 21. Alles neu aufbauen

Ändert sich, wie Aufgaben, Entscheidungen oder der Stand abgeleitet werden, bliebe der Bestand im alten
Zustand. `2ndbrain neuaufbau` (im Plugin: „Alles neu aufbauen“) rechnet ihn aus den Ursprungsdaten neu –
**in einer Kopie neben dem Vault** (`<Vault>-neuaufbau-<Datum>`), nie im Vault selbst. Jeder schreibende
Schritt prüft die Marke `.2ndbrain/daten/neuaufbau.json`, die nur in einer Kopie steht.

| Schritt | Was passiert |
|---|---|
| `anlegen` | Vault kopieren (unter der Sperre der Automatik), Kopie kennzeichnen |
| `zuruecksetzen` | Stand vorher festhalten; Termine mit Material: Nachbereitung zurücknehmen (Sicherung, sonst Entscheidungen/Actions/Parkplatz/Kernteil leeren), aus dem Archiv zurück, vormerken; Mails und Dokumente zurück in den Eingang; aus den Themen heraus, was aus diesen Quellen stammt (Log-Zeilen, übernommene Punkte) |
| `bauen` | jeden Termin einzeln nachbereiten und ins Themen-Log (Fortschritt nach jedem Termin, fortsetzbar), Eingang einarbeiten, Altbestand, Archiv, Stand, Personen; was vorher erledigt oder verworfen war, ist es wieder |
| `vergleichen` | `reports/neuaufbau-vergleich.md`: Zahlen vorher/nachher, je Thema, was wegfällt, was dazukommt |

**Im Plugin.** Der Neuaufbau hat einen eigenen Abschnitt in den Einstellungen (Stand des letzten, Knopf) und
das Fenster „Alles neu aufbauen“: Es liest den Fortschritt alle 15 Sekunden direkt aus der Marke der Kopie
(`desktop/neuaufbau.ts` – die Engine kann man nicht fragen, solange sie rechnet), setzt einen angefangenen
Neuaufbau fort und öffnet Vergleich und Ordner. **Angeboten wird er von selbst:** `ABLEITUNG_STAND`
(`core/neuaufbau.ts`) zählt, wie oft sich die Ableitung geändert hat; das Plugin merkt sich in seinen Daten,
welchen Stand der Nutzer gesehen hat (`ableitungGesehen`), und meldet sich nach einem Update einmal beim Start –
ein frisch eingerichteter Vault ohne alten Bestand nicht. Wer eine Version baut, die Aufgaben, Entscheidungen
oder den Stand anders ableitet, erhöht die Zahl.

**Alle Termine, die ältesten zuerst.** Auch die alten Termin-Notizen im Archiv (eingearbeitet, ohne getrenntes
Material) werden neu gerechnet: Ihr Text wird als `## Mitschrift` verpackt (eigene Überschriften rücken
darunter), und sie laufen durch dieselbe Nachbereitung. Gerechnet wird in der Reihenfolge des Datums, damit
jedes Thema wächst wie damals. `--seit JJJJ-MM-TT` begrenzt, wie weit zurück; `--neu` (im Plugin „Neu beginnen“)
lässt eine angefangene Kopie liegen und beginnt eine frische – nötig für eine Kopie, die eine ältere Version
ohne die alten Notizen angelegt hat.

**Nur einer rechnet.** Ein Neuaufbau überlebt das Plugin, das ihn gestartet hat; zwei nebeneinander teilen
sich den Modell-Server, und man sieht nur einen (Befund 18.11.2026). Deshalb trägt die Marke der Kopie den
Prozess, der gerade baut (`pid`, `rechner`). Ein Start wird abgelehnt, solange einer rechnet – auch einer aus
einer älteren Version, der sich nur an seiner Befehlszeile zeigt (`fremde_prozesse`; die eigenen Vorfahren und
Nachkommen zählen nicht). `2ndbrain neuaufbau stoppen` (im Fenster „Laufenden Neuaufbau beenden“) beendet alle
Läufe auf dem Rechner samt Unterprozessen. Das Plugin hält den laufenden Auftrag der Engine an, wenn es
entladen wird oder Obsidian schließt. Fortgesetzt wird nur eine Kopie mit dem heutigen Umfang, die zuletzt
angelegte.

Ursprungsdaten sind das Material der Termin-Notizen (Transkript, Mitschrift, eigene Notizen) und die Mails
und Dokumente, die das Einarbeiten ins Archiv gelegt hat. Termin-Notizen ohne Material (alte Notizen) bleiben,
wie sie sind – aus ihnen lässt sich nichts neu rechnen. Umgeschaltet wird von Hand (Ordner umbenennen, der alte
bleibt als Sicherung); die Engine schaltet nicht um und löscht nichts.

## 20. Fokus: das Wichtigste priorisiert voranbringen

Der Vault weiß, wo jedes Thema steht. Er weiß aber nicht, welche Themen dir am wichtigsten sind und ob deine
Zeit dorthin geht. Fokus ist dafür **kein neues Ding neben den Themen, sondern ein Rang an einem Thema**:
`fokus: 1` ist das wichtigste, dazu `ziel` (ein Satz) und der Zieltermin (`target_date`). Ein Dach-Thema
mit Unterthemen ist ein **Nordstern**. Was in den Unterthemen passiert, zählt für ihn mit: Schritte,
Bewegung, Termine. Mehr als fünf Fokus-Themen meldet das Plugin, denn dann ist es kein Fokus mehr.

**Planen** („Fokus planen“, `views/fokus.ts`; am Handy genauso): Themen wählen und ordnen, je Thema Ziel,
Zieltermin und der nächste Schritt mit Frist. Geschrieben wird beim Speichern, zeilengenau ins Frontmatter
(`fmUpdate`). Der Schritt wird ein normaler Punkt in `## Offene Punkte` des Themas, mit dir als
verantwortlich (`renderTask`, `appendToSection` im Plugin wie `aufgaben.render` und
`append_to_section` in der Engine). Damit gilt er überall, wo Aufgaben gelten.

**Was der Code zählt** (`core/fokus.ts` und `fokus.py`, dieselben Regeln):
- **Nächster Schritt:** dein offener Punkt in der Menge, Frist zuerst, ohne Frist der älteste. Fragen an
  andere sind kein Schritt.
- **Bewegung:** Einträge im Log der Menge. Der Anlage-Eintrag der Vorlage zählt nicht.
- **Termine:** Termin-Notizen (aktiv und archiviert) mit einem Thema der Menge, ohne übersprungene und
  entfallene. Ihre Dauer kommt aus dem Kalender: `dauer_min` in `events.json`, aus DTEND oder DURATION,
  bei Serien die der Serie, beim verschobenen Einzeltermin seine eigene. Zugeordnet wird über UID und Tag,
  sonst über Tag, Zeit und Titel, sonst über einen eindeutigen Titel am Tag.
- **Zeit:** alle Termin-Notizen des Zeitraums, eingeteilt in *Fokus · andere Themen · ohne Thema*. Gezählt
  wird nach Minuten, solange welche bekannt sind, sonst nach Anzahl. Ohne Thema zählt nicht als Fokus.
  Die Zahl ist so gut wie die Zuordnung der Termine.
- **Warnungen:** kein nächster Schritt, 14 Tage ohne Bewegung, kein Termin in den nächsten 14 Tagen,
  Zieltermin überschritten, kein Ziel formuliert.

**Wo es erscheint:**
- *Heute* zeigt den Fokus ganz oben, mit der Zeit der letzten 14 Tage. Termine und Aufgaben zu einem
  Fokus tragen einen ★.
- Die **Vorbereitung** eines Termins zum Fokus nennt Ziel und nächsten Schritt und fragt, was der Termin
  dafür bringen soll. Die Blocktabelle rechnet dabei mit der echten Dauer des Termins.
- Der **Chat** hat das Werkzeug `fokus` (auch vorab, wenn die Frage nach Fokus, Prioritäten oder dem
  „Richtigen“ fragt).
- `2ndbrain fokus` zeigt dieselben Zahlen im Terminal.

**Fokus-Spiegel** (Schritt `fokus` der Automatik nach `stand`, `reports/fokus-spiegel.md`): Einmal je Woche,
beim ersten Lauf ab Montag, rechnet der Code für die letzten sieben Tage je Fokus:
- Bewegung, erledigte und offene Schritte
- Termine und Stunden
- die Termine der Woche voraus, dazu die Liste der Termine ohne Fokus-Bezug

Das Modell ordnet nur ein: 2–4 Sätze Überblick, eine Frage zur Woche, je Fokus 1–3 Sätze und genau eine
Frage. Verworfen wird seine Antwort, wenn sie zu kurz oder zu lang ist, ein Datum nennt, das in keinem Fakt
steht, oder einen Fokus erfindet. Dann steht der Spiegel mit den Zahlen allein da. Ohne Modell ebenso.
Kommt das Modell später in der Woche, wird er mit Einordnung neu geschrieben (`mit_modell` im
Frontmatter). „Fokus-Spiegel jetzt erstellen“ (`2ndbrain fokus --spiegel --neu`) schreibt ihn sofort.
