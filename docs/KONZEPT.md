# 2ndBrain — Konzept

> Zielbild, Aufbau und verbindliche Formate. Die Formate in §4 sind Spezifikation: Code und Tests
> richten sich danach. Beispiele in diesem Text sind erfunden. Welcher Begriff im Code wie heißt,
> steht in §19.

---

## 1. Worum es geht

Wer beruflich in viele Themen eingebunden ist – als Führungskraft, Architektin, Projektleiter –, muss

1. **wissen, wo die eigenen Themen stehen** (Überblick, Bewegung, Ampel),
2. **in Terminen auskunftsfähig sein** (in Sekunden sagen können, was gilt),
3. **die richtigen Fragen stellen und Zusagen nachhalten** (wer schuldet wem was, was ist offen).

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

- Themen: `kind`, `parent`, optional `fokus: true`, `atlas_id` (→ 3.3); `stand_updated`, `stand_fingerprint`.
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
bzw. die Automatik ein: Mail → Notiz, Anhänge und ZIPs → eigene Notizen, Bilder → Texterkennung.
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

**Antwortgrenze nach Eingabe.** Prüfstufe und Protokoll bekommen eine Antwortgrenze, die mit dem Material
wächst: etwa ein Viertel der Eingabezeichen in Tokens, 4096 bis 12288 (`modell.antwort_tokens`) – eine
feste Grenze schnitt lange Termine ab. Langes Material wird für den Entwurf an Absatz-, Satz- oder
Wortgrenzen geteilt, nie mitten im Wort.

## 8. Oberflächen (Obsidian-Plugin)

Heute (ganz oben „Ohne Notizen“, dann Radar, eigene Aufgaben, Termine mit Phase, Nachfassen) ·
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
Begriff, Subdomäne, Team) ist ein Punkt; gelesen wird das Thema zuerst. Die Wartezeile zeigt Runde,
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
`.2ndbrain/chat-fragen-mehrschritt.json` im Vault.

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
MCP, Automatik, Befehlszeile). Das Engine-Paket liegt dem Plugin bei: der Build legt
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
| Automatik | `.2ndbrain/daten/.auto_state.json` | `auto` | `auto.py` | `main.ts` |
| Befehlszeile | – | `help` | `befehle.py` | `desktop/engine.ts` |
