// Abfragen fuer den Chat (core/abfragen.ts): Aufgaben, Themen-Log, Termine (mit Kalender), Frontmatter -
// gefiltert, gezaehlt und sortiert vom Code. Namen und Daten erfunden; heute ist Mo 29.09.2026.
import assert from "node:assert/strict";
import { test } from "node:test";
import { baueGraph } from "../src/core/graph";
import { fuehreAus } from "../src/core/werkzeuge";
import { MemorySource } from "./quellen";

const HEUTE = "2026-09-29";

function vault(): MemorySource {
  return new MemorySource({
    "entities/people/ich-selbst.md": "---\ntype: person\nname: Ich Selbst\n---\n",
    "entities/people/rita-rot.md": "---\ntype: person\nname: Rita Rot\n---\n",
    "entities/people/max-muster.md": "---\ntype: person\nname: Max Muster\n---\n",
    "entities/projects/dach.md": "---\ntype: project\ntitle: Dach\nkind: area\nhealth: yellow\n---\n# Dach\n\n## Offene Punkte\n"
      + "- [ ] Dachpunkt klären — [[ich-selbst|Ich Selbst]] · [[dach|Dach]] 📅 2026-10-10 ➕ 2026-09-01\n",
    "entities/projects/portal.md": "---\ntype: project\ntitle: Portal\nparent: '[[dach]]'\nhealth: red\n---\n# Portal\n\n"
      + "## Offene Punkte\n"
      + "- [ ] Schnittstelle klären — [[rita-rot|Rita Rot]] · [[portal|Portal]] 📅 2026-09-20 ➕ 2026-09-01\n"
      + "- [ ] ❓ Wer zahlt? — an [[max-muster|Max Muster]] · [[portal|Portal]] ➕ 2026-09-05\n"
      + "- [x] Alte Sache — [[rita-rot|Rita Rot]] · [[portal|Portal]] ➕ 2026-08-01 ✅ 2026-08-10\n\n"
      + "## Event Log\n"
      + "- [2026-09-20] [RISK] Termin wackelt (→ [[2026-09-10 - checkin - Portal]])\n"
      + "- [2026-09-12] [DECISION] Portal geht im Oktober live\n"
      + "- [2026-08-01] [RISK] Alter Risikopunkt\n",
    "active-meetings/2026-09-10 - checkin - Portal.md": "---\ntype: meeting\ntitle: Checkin Portal\ndate: '2026-09-10'\n"
      + "meeting_time: '10:00'\nstatus: nachbereitet\nthemen: [portal]\nteilnehmer: [rita-rot]\n---\n",
    "active-meetings/2026-10-02 - review - Portal Review.md": "---\ntype: meeting\ntitle: Portal Review\ndate: '2026-10-02'\n"
      + "meeting_time: '14:00'\nstatus: vorbereitet\nthemen: [portal]\nteilnehmer: [max-muster]\n---\n",
    "archive/meetings/2026-08/2026-08-01 - checkin - Portal.md": "---\ntype: meeting\ntitle: Checkin Portal\ndate: '2026-08-01'\n"
      + "themen: [portal]\n---\n",
    "archive/calendar/events.json": JSON.stringify([
      { date_iso: "2026-10-03", time: "09:00", summary: "Portal Abstimmung" },
      { date_iso: "2026-10-02", time: "14:00", summary: "Portal Review" },
      { date_iso: "2026-10-04", time: "11:00", summary: "Mittagspause" }]),
    "entities/systems/altsys.md": "---\ntype: system\nname: AltSys\nbereich: '[[dach]]'\n---\n",
    "entities/systems/neusys.md": "---\ntype: system\nname: NeuSys\nbereich: '[[dach]]'\nowner: '[[rita-rot]]'\n---\n",
    "entities/systems/fremdsys.md": "---\ntype: system\nname: FremdSys\n---\n",
  });
}

async function werkzeug(name: string, args: Record<string, unknown>): Promise<string> {
  const src = vault();
  const g = await baueGraph(src, "ich-selbst");
  return (await fuehreAus(name, args, g, src, { today: HEUTE, me: "ich-selbst" })).text;
}

test("tasks: Person, ich, Thema mit Unterthemen, überfällig, erledigt – Zahlen vom Code", async () => {
  const rita = await werkzeug("tasks", { person: "Rita Rot" });
  assert.ok(rita.startsWith("Aufgaben (offen, von Rita Rot): 1, davon 1 überfällig\n"), rita);
  assert.ok(rita.includes("- Schnittstelle klären (Rita Rot; fällig 20.09.2026 – ÜBERFÄLLIG; seit 01.09.2026; [[portal|Portal]]; in [[portal]])"), rita);
  const dach = await werkzeug("tasks", { thema: "Dach" });
  assert.ok(dach.startsWith("Aufgaben (offen, zu Dach): 3, davon 1 überfällig, 1 Fragen – mit 1 Unterthemen"), dach);
  // Reihenfolge: ueberfaellig, dann Frist, dann die juengsten
  assert.ok(dach.indexOf("Schnittstelle") < dach.indexOf("Dachpunkt") && dach.indexOf("Dachpunkt") < dach.indexOf("❓ Wer zahlt?"), dach);
  const ich = await werkzeug("tasks", { person: "ich" });
  assert.ok(ich.includes("Dachpunkt klären (Ich Selbst") && !ich.includes("Schnittstelle"), ich);
  const erledigt = await werkzeug("tasks", { person: "Rita Rot", status: "erledigt" });
  assert.ok(erledigt.includes("Alte Sache (Rita Rot; erledigt 10.08.2026") && !erledigt.includes("Schnittstelle"), erledigt);
  const spaet = await werkzeug("tasks", { ueberfaellig: true });
  assert.ok(spaet.startsWith("Aufgaben (offen, nur überfällige): 1, davon 1 überfällig"), spaet);
  assert.ok((await werkzeug("tasks", { person: "Niemand Da" })).startsWith("Keine Person „Niemand Da“ gefunden."));
});

test("log: Art, Thema mit Unterthemen, Zeitraum, aktive Risiken – neueste zuerst", async () => {
  const risiken = await werkzeug("log", { thema: "Dach", art: "Risiko" });
  assert.ok(risiken.startsWith("Log-Einträge (Risiko, zu Dach mit Unterthemen): 2, neueste zuerst"), risiken);
  assert.ok(risiken.indexOf("20.09.2026 [Risiko] Termin wackelt") < risiken.indexOf("01.08.2026 [Risiko] Alter Risikopunkt"), risiken);
  const aktiv = await werkzeug("log", { art: "Risiko", nur_aktiv: true });
  assert.ok(aktiv.includes(": 1, neueste zuerst") && aktiv.includes("Termin wackelt") && !aktiv.includes("Alter Risikopunkt"), aktiv);
  const beschluss = await werkzeug("log", { art: "Beschluss", seit: "2026-09-01" });
  assert.ok(beschluss.includes("- 12.09.2026 [Beschluss] Portal geht im Oktober live · [[portal|Portal]]"), beschluss);
});

test("meetings: Zeitraum, Thema, Person, Kalender ohne Notiz, sortiert", async () => {
  const kommend = await werkzeug("meetings", { von: "2026-09-01", bis: "2026-10-05", thema: "Portal" });
  assert.ok(kommend.startsWith("Termine 01.09.2026–05.10.2026 zu Portal: 3 (2 mit Notiz, 1 nur im Kalender), früheste zuerst"), kommend);
  const zeilen = kommend.split("\n").slice(1);
  assert.ok(zeilen[0].startsWith("- Do 10.09.2026 10:00 · [[2026-09-10 - checkin - Portal|Checkin Portal (10.09.2026)]] · Status nachbereitet"), zeilen[0]);
  assert.ok(zeilen[1].includes("Portal Review") && zeilen[2] === "- Sa 03.10.2026 09:00 · Portal Abstimmung (Kalender, noch keine Notiz)", kommend);
  const max = await werkzeug("meetings", { von: "2026-09-01", bis: "2026-10-05", person: "Max Muster" });
  assert.ok(max.includes(": 1, früheste zuerst") && max.includes("Portal Review") && max.includes("mit Max Muster"), max);
  // „ich“ filtert nicht - meine Termine sind alle, auch die aus dem Kalender
  const ich = await werkzeug("meetings", { von: "2026-09-01", bis: "2026-10-05", thema: "Portal", person: "ich" });
  assert.ok(ich.includes(": 3 (2 mit Notiz, 1 nur im Kalender)"), ich);
  const frueher = await werkzeug("meetings", { von: "2026-07-01", bis: "2026-09-15" });
  assert.ok(frueher.includes(": 2, neueste zuerst") && frueher.indexOf("10.09.2026") < frueher.indexOf("01.08.2026"), frueher);
});

const ATLAS = [
  "## Subdomänen", "", "| Subdomäne | Name | Kontexte | Art | Reife | Beschreibung |", "|---|---|---|---|---|---|",
  "| `sd-lagerhof` | Lagerhof | 2 | core | agreed | Hof und Halle. |", "| `sd-auftrag` | Auftragswesen | 1 | supporting |  |  |", "",
  "## Kontexte", "", "| Kontext | Subdomain | Owner | Reife | Beschreibung |", "|---|---|---|---|---|",
  "| `ctx-verladung` Verladung | sd-lagerhof | team-halle | proposed | Lädt Paletten. |",
  "| `ctx-wareneingang` Wareneingang | sd-lagerhof | team-halle |  |  |",
  "| `ctx-annahme` Annahme | sd-auftrag | team-auftrag | agreed |  |", "",
  "## Nachrichten", "", "| Nachricht | Typ | Reife | von | an | Beschreibung |", "|---|---|---|---|---|---|",
  "| `msg-palette-gebildet` Palette gebildet | event | agreed | `ctx-verladung` | `ctx-annahme` | Palette fertig. |",
  "| `msg-lade-tour` Belade Tour | command | review | `ctx-annahme` | `ctx-verladung` |  |",
  "| `msg-finde-sendung` finde Sendung | query | review | `ctx-wareneingang` | `ctx-annahme` |  |",
  "| `msg-tor-frei` Tor frei | event | live | `ctx-wareneingang` | `ctx-verladung` |  |", "",
  "## Fachobjekte", "", "| Objekt | Kontext | Stereotyp | Synonyme | Relationen | Definition |", "|---|---|---|---|---|---|",
  "| `obj-palette` Palette | `ctx-verladung` | entity | Pallet | liegt-auf `obj-ladeeinheit` (0..n) · gehoert-zu `obj-sendung` (1..1) | Ladungsträger. |",
  "| `obj-sendung` Sendung | `ctx-annahme` | aggregate-root |  |  | Auftrag des Kunden. |", "",
  "## Teams", "", "| Team | Beschreibung |", "|---|---|", "| `team-halle` Team Halle | Betreibt die Halle. |", "",
  "## Abläufe", "", "| Ablauf | Reife | betrifft | Schritte | Beschreibung |", "|---|---|---|---|---|",
  "| `proc-verladen` Verladen | proposed | `ctx-verladung` | `ctx-annahme`: `msg-lade-tour` → `ctx-verladung`: `msg-palette-gebildet` "
    + "| Erst Tour, dann Palette. |", "",
].join("\n");

async function atlasWerkzeug(args: Record<string, unknown>): Promise<string> {
  const src = new MemorySource({ "entities/contexts/_index.md": ATLAS });
  const g = await baueGraph(src);
  return (await fuehreAus("atlas", args, g, src, { today: HEUTE })).text;
}

test("atlas: Nachrichten nach Typ mit Gegenseite und Owner, Prozesse, Teams, Domänenmodell, Kontexte", async () => {
  const events = await atlasWerkzeug({ art: "nachricht", typ: "event", subdomaene: "Lagerhof" });
  assert.ok(events.startsWith("Nachrichten (Event) – Subdomäne Lagerhof: 2 – 1 agreed, 1 live"), events);
  assert.ok(events.includes("- Event „Palette gebildet“ (`msg-palette-gebildet`, agreed) · raus: Verladung [Team Halle] → "
                            + "Annahme [team-auftrag] – Palette fertig.") && events.includes("„Tor frei“ (`msg-tor-frei`, live) · innerhalb"), events);
  assert.ok((await atlasWerkzeug({ art: "commands" })).startsWith("Nachrichten (Command): 1"));
  const proc = await atlasWerkzeug({ art: "prozess", kontext: "Verladung" });
  assert.ok(proc.includes("- Prozess „Verladen“ (`proc-verladen`, proposed) · betrifft Verladung\n"
                          + "  Schritte: Annahme: Belade Tour → Verladung: Palette gebildet\n  Erst Tour, dann Palette."), proc);
  const teams = await atlasWerkzeug({ art: "team" });
  assert.ok(teams.startsWith("Teams: 2\n- Team „Team Halle“ (`team-halle`): 2 Kontexte – Lagerhof: Verladung, Wareneingang – "
                             + "Betreibt die Halle.\n- Team „team-auftrag“ (`team-auftrag`): 1 Kontexte – Auftragswesen: Annahme"), teams);
  const modell = await atlasWerkzeug({ art: "domaenenmodell", kontext: "ctx-verladung" });
  assert.ok(modell.startsWith("Domänenmodell – Kontext Verladung: 1 Fachobjekte – 1 entity\n"
                              + "- „Palette“ (`obj-palette`, entity) in Verladung · auch: Pallet – Ladungsträger.\n"
                              + "  - liegt-auf obj-ladeeinheit (0..n)\n  - gehoert-zu Sendung (1..1)"), modell);
  const halle = await atlasWerkzeug({ art: "kontext", team: "Team Halle" });
  assert.ok(halle.startsWith("Kontexte – Team Team Halle: 2") && halle.includes("(`ctx-verladung`, proposed) · Subdomäne Lagerhof · "
                                                                              + "Owner Team Halle · Nachrichten 1 raus, 2 rein"), halle);
  assert.ok((await atlasWerkzeug({ art: "kontext", kontext: "Zollamt" })).startsWith("Kein Eintrag „Zollamt“ (Kontext) im Atlas."));
  // das Domaenenmodell im Graphen: Relationen mit ihrem Verb
  const g = await baueGraph(new MemorySource({ "entities/contexts/_index.md": ATLAS }));
  assert.deepEqual(g.kante("obj-palette", "obj-sendung"), { von: "obj-palette", wie: "Gehoert-zu" });
});

test("Mehrdeutig: passt ein Name auf mehrere, nennen tasks, log, meetings und atlas alle – nie still den ersten", async () => {
  const src = new MemorySource({
    "entities/people/rita-rot.md": "---\ntype: person\nname: Rita Rot\n---\n",
    "entities/people/rita-rauch.md": "---\ntype: person\nname: Rita Rauch\n---\n",
    "entities/people/rita.md": "---\ntype: person\nname: Rita\nrole: Unbekannt\n---\n",       // Platzhalter aus einer Mitschrift
    "entities/projects/hof-ost.md": "---\ntype: project\ntitle: Hofplanung Ost\n---\n# Hofplanung Ost\n\n## Offene Punkte\n"
      + "- [ ] Rampe prüfen — [[rita-rot|Rita Rot]] · [[hof-ost|Hofplanung Ost]]\n\n## Event Log\n- [2026-09-20] [RISK] Rampe zu schmal\n",
    "entities/projects/hof-west.md": "---\ntype: project\ntitle: Hofplanung West\n---\n# Hofplanung West\n\n## Offene Punkte\n"
      + "- [ ] Tor prüfen — [[rita-rauch|Rita Rauch]] · [[hof-west|Hofplanung West]]\n",
    "entities/forums/runde-hof.md": "---\ntype: forum\nname: Runde Hof\n---\n",
    "entities/forums/runde-halle.md": "---\ntype: forum\nname: Runde Halle\n---\n",
    "entities/contexts/_index.md": ["## Subdomänen", "", "| Subdomäne | Name | Kontexte | Art | Reife | Beschreibung |",
      "|---|---|---|---|---|---|", "| `sd-hof` | Hof | 2 | core |  |  |", "", "## Kontexte", "",
      "| Kontext | Subdomain | Owner | Reife | Beschreibung |", "|---|---|---|---|---|",
      "| `ctx-tor-nord` Tor Nord | sd-hof |  |  |  |", "| `ctx-tor-sued` Tor Süd | sd-hof |  |  |  |", ""].join("\n"),
  });
  const g = await baueGraph(src);
  const w = async (name: string, args: Record<string, unknown>) => (await fuehreAus(name, args, g, src, { today: HEUTE })).text;
  const rita = await w("tasks", { person: "Rita" });
  assert.ok(rita.startsWith("„Rita“ ist nicht eindeutig – gemeint ist eines davon:\n") && rita.includes("- [[rita-rot|Rita Rot]] · Person")
            && rita.includes("- [[rita-rauch|Rita Rauch]] · Person") && rita.endsWith("frag zurück.") && !rita.includes("Rampe"), rita);
  // eine Seite, die nur „Rita“ heisst, trifft genau - und ist doch nur eine von dreien
  assert.ok(rita.includes("- [[rita|Rita]] · Person"), rita);
  assert.ok((await w("read", { ziel: "Rita" })).startsWith("„Rita“ ist nicht eindeutig"));
  assert.ok((await w("tasks", { person: "Rita Rot" })).includes("Rampe prüfen"), "der volle Name ist eindeutig");
  const hof = await w("log", { thema: "Hofplanung" });
  assert.ok(hof.includes("- [[hof-ost|Hofplanung Ost]] · Thema") && hof.includes("- [[hof-west|Hofplanung West]] · Thema")
            && !hof.includes("Rampe zu schmal"), hof);
  assert.ok((await w("meetings", { reihe: "Runde" })).startsWith("„Runde“ ist nicht eindeutig"));
  const tor = await w("atlas", { art: "kontext", kontext: "Tor" });
  assert.ok(tor.startsWith("„Tor“ ist nicht eindeutig") && tor.includes("- Tor Nord (`ctx-tor-nord`) · Kontext")
            && tor.includes("- Tor Süd (`ctx-tor-sued`) · Kontext"), tor);
  // nicht gefunden: weiter mit dem Rat zu suchen; beides zusammen: Liste und Rat
  assert.ok((await w("tasks", { person: "Niemand" })).endsWith("Mit search den Namen finden."));
  const beides = await w("tasks", { person: "Rita", thema: "Quatsch" });
  assert.ok(beides.includes("[[rita-rauch|Rita Rauch]]") && beides.includes("Kein Thema „Quatsch“ gefunden.") && beides.endsWith("Mit search den Namen finden."), beides);
});

test("query: Frontmatter filtern – gleich (auch über Links und Namen), fehlt, sortieren", async () => {
  const ohneOwner = await werkzeug("query", { art: "System", bedingungen: [{ feld: "bereich", op: "=", wert: "Dach" },
                                                                         { feld: "owner", op: "fehlt" }] });
  assert.ok(ohneOwner.startsWith("Abfrage (System, bereich = Dach, owner fehlt): 1 Treffer\n- [[altsys|AltSys]] · System · bereich: [[dach]] · owner: –"),
            ohneOwner);
  const ohneBereich = await werkzeug("query", { art: "Systeme", bedingungen: [{ feld: "bereich", op: "fehlt" }] });
  assert.ok(ohneBereich.includes("1 Treffer") && ohneBereich.includes("FremdSys"), ohneBereich);
  const rot = await werkzeug("query", { art: "Thema", bedingungen: [{ feld: "health", op: "=", wert: "red" }], felder: ["parent"] });
  assert.ok(rot.includes("- [[portal|Portal]] · Thema · health: red · parent: [[dach]]") && !rot.includes("Dach · Thema"), rot);
  const sortiert = await werkzeug("query", { art: "System", felder: ["owner"], sortiere: "-name" });
  assert.ok(sortiert.indexOf("NeuSys") < sortiert.indexOf("FremdSys") && sortiert.indexOf("FremdSys") < sortiert.indexOf("AltSys"), sortiert);
  assert.ok((await werkzeug("query", { art: "Quatsch" })).startsWith("Art „Quatsch“ unbekannt"));
});
