// Fokus-Themen (core/fokus.ts): Rang, Nordstern (Dach mit Unterthemen), naechster eigener Schritt, Termine
// mit Dauer aus dem Kalender, Zeit nach Fokus / anderen Themen / ohne Thema, Warnungen - dazu der neue Punkt
// aus „Fokus planen“ (core/aufgaben.ts) und das Chat-Werkzeug `fokus`. Namen und Daten erfunden; heute ist
// Di 06.10.2026 - dieselben Faelle wie der Engine-Test (fokus.py).
import assert from "node:assert/strict";
import { test } from "node:test";
import { TOPIC_SECTION, appendToSection, parseLine, renderTask } from "../src/core/aufgaben";
import {
  RANG_OHNE_NUMMER, anteile, dauerFuer, dauerIndex, fokusFuer, fokusRang, fokusText, fokusThemen, fokusVon, fokusZeilen,
  naechsterSchritt, stunden, zeitVerteilung, zeitZeile,
} from "../src/core/fokus";
import { isOpen, scanTasks } from "../src/core/aufgaben";
import { VaultIndex } from "../src/core/vaultIndex";
import { fuehreAus } from "../src/core/werkzeuge";
import { baueGraph } from "../src/core/graph";
import { MemorySource } from "./quellen";

const HEUTE = "2026-10-06";
const ICH = "[[ich-selbst|Ich Selbst]]";

function vault(): MemorySource {
  return new MemorySource({
    "entities/people/ich-selbst.md": "---\ntype: person\nname: Ich Selbst\n---\n",
    "entities/projects/portal.md": "---\ntype: project\ntitle: Portal\nkind: area\nfokus: 1\nziel: Neues Portal live\n"
      + "target_date: '2026-11-30'\nhealth: yellow\nzuletzt_bewegt: '2026-10-02'\nnaechster_termin: '2026-10-08'\n---\n# Portal\n",
    "entities/projects/portal-suche.md": "---\ntype: project\ntitle: Portal Suche\nparent: '[[portal]]'\n---\n# Suche\n\n"
      + "## Offene Punkte\n"
      + `- [ ] Suchindex freigeben — ${ICH} · [[portal-suche|Portal Suche]] 📅 2026-10-09 ➕ 2026-10-01\n`
      + `- [ ] Altes aufräumen — ${ICH} · [[portal-suche|Portal Suche]] ➕ 2026-09-01\n`
      + `- [ ] ❓ Kommt das Budget? — an ${ICH} · [[portal-suche|Portal Suche]] 📅 2026-10-07\n`
      + `- [x] Konzept abgestimmt — ${ICH} ➕ 2026-09-20 ✅ 2026-10-01\n\n`
      + "### Altbestand – im nächsten Termin prüfen\n- [ ] Alter Punkt ➕ 2026-01-01\n\n## Event Log\n"
      + "- [2026-10-03] [MILESTONE] Suche im Test\n",
    "entities/projects/daten.md": "---\ntype: project\ntitle: Datenplattform\nfokus: 2\nzuletzt_bewegt: '2026-09-01'\n---\n# Daten\n",
    "entities/projects/betrieb.md": "---\ntype: project\ntitle: Betrieb\n---\n# Betrieb\n",
    "archive/meetings/2026-09/a.md": "---\ntype: meeting\ntitle: Review Suche\ndate: '2026-09-30'\nmeeting_time: '10:00'\n"
      + "themen: [portal-suche]\noutlook_uid: u-1\n---\n",
    "active-meetings/2026/10/b.md": "---\ntype: meeting\ntitle: Portal Weekly\ndate: '2026-10-05'\nmeeting_time: '09:00'\n"
      + "themen: [portal]\n---\n",
    "active-meetings/2026/10/c.md": "---\ntype: meeting\ntitle: Betrieb Runde\ndate: '2026-10-02'\nmeeting_time: '14:00'\n"
      + "themen: [betrieb]\n---\n",
    "active-meetings/2026/10/e.md": "---\ntype: meeting\ntitle: Kaffee\ndate: '2026-10-01'\nmeeting_time: '08:00'\n---\n",
    "active-meetings/2026/10/x.md": "---\ntype: meeting\ntitle: Entfallen\ndate: '2026-10-01'\nstatus: entfallen\nthemen: [portal]\n---\n",
    "active-meetings/2026/10/f.md": "---\ntype: meeting\ntitle: Portal Planung\ndate: '2026-10-07'\nmeeting_time: '10:00'\n"
      + "themen: [portal]\n---\n",
    "archive/calendar/events.json": JSON.stringify([
      { date_iso: "2026-09-30", time: "10:00", summary: "Review Suche", outlook_uid: "u-1", dauer_min: 90 },
      { date_iso: "2026-10-05", time: "09:00", summary: "Portal Weekly", dauer_min: 30 },
      { date_iso: "2026-10-02", time: "14:00", summary: "Betrieb Runde", dauer_min: 60 },
      { date_iso: "2026-10-01", time: "08:00", summary: "Kaffee", dauer_min: 30 },
      { date_iso: "2026-10-01", time: "16:00", summary: "Doppelt", dauer_min: 30 },
      { date_iso: "2026-10-01", time: "17:00", summary: "Doppelt", dauer_min: 45 }]),
  });
}

test("Rang: Zahl ab 1, true hinter allen Nummern, sonst kein Fokus", () => {
  assert.deepEqual([1, "2", true, false, 0, "ja", "x", null, 1.5].map(fokusRang),
                   [1, 2, RANG_OHNE_NUMMER, null, null, RANG_OHNE_NUMMER, null, null, null]);
});

test("Fokus-Themen: nach Rang, ein Dach zählt seine Unterthemen mit (Nordstern)", () => {
  const index = new VaultIndex(vault());
  const fokus = fokusThemen(index.topics(), HEUTE);
  assert.deepEqual(fokus.map((f) => [f.slug, f.rang, [...f.menge].sort()]),
                   [["portal", 1, ["portal", "portal-suche"]], ["daten", 2, ["daten"]]]);
  const [p] = fokus;
  assert.deepEqual([p.ziel, p.zieltermin, p.zuletztBewegt, p.naechsterTermin], ["Neues Portal live", "2026-11-30", "2026-10-02", "2026-10-08"]);
  const zu = fokusVon(fokus);
  assert.equal(fokusFuer(["betrieb", "portal-suche"], zu)?.slug, "portal", "ein Unterthema reicht");
  assert.equal(fokusFuer(["betrieb"], zu), null);
});

test("Nächster Schritt: eigene Punkte der Menge, Frist zuerst, Fragen zählen nicht", async () => {
  const src = vault();
  const tasks = (await scanTasks(src)).filter(isOpen);
  const index = new VaultIndex(src);
  const [p, d] = fokusThemen(index.topics(), HEUTE);
  const s = naechsterSchritt(tasks, p.menge, "ich-selbst", HEUTE);
  assert.equal(s.schritt?.text, "Suchindex freigeben");
  assert.deepEqual([s.offen, s.ueberfaellig], [2, 0], "Altbestand ohne Person und die Frage zählen nicht");
  assert.equal(naechsterSchritt(tasks, d.menge, "ich-selbst", HEUTE).schritt, null);
  assert.equal(naechsterSchritt(tasks, p.menge, "", HEUTE).schritt, null, "ohne „ich“ kein Schritt");
});

test("Zeit: Termine mit Dauer aus dem Kalender – Fokus, andere Themen, ohne Thema; entfallene zählen nicht", async () => {
  const src = vault();
  const index = new VaultIndex(src);
  const idx = dauerIndex(await src.readFile("archive/calendar/events.json"));
  const termine = index.termine("2026-09-29", "2026-10-05").map((t) => ({ ...t, minuten: dauerFuer(t, idx) }));
  assert.deepEqual(termine.map((t) => [t.title, t.minuten]).sort(),
                   [["Betrieb Runde", 60], ["Kaffee", 30], ["Portal Weekly", 30], ["Review Suche", 90]]);
  assert.equal(dauerFuer({ date: "2026-10-01", time: "", title: "Doppelt", uid: "" }, idx), null, "zweideutig ohne Zeit");
  assert.equal(dauerFuer({ date: "2026-10-01", time: "17:00", title: "Doppelt", uid: "" }, idx), 45);
  const fokus = fokusThemen(index.topics(), HEUTE);
  const z = zeitVerteilung(termine, fokusVon(fokus));
  assert.deepEqual([z.fokus, z.andere, z.ohne], [{ anzahl: 2, minuten: 120 }, { anzahl: 1, minuten: 60 }, { anzahl: 1, minuten: 30 }]);
  assert.deepEqual(anteile(z), { fokus: 57, andere: 29, ohne: 14 });
  assert.equal(zeitZeile(z), "57 % Fokus · 29 % andere Themen · 14 % ohne Thema (3,5 h in 4 Terminen)");
  const ohneDauer = zeitVerteilung(termine.map((t) => ({ ...t, minuten: null })), fokusVon(fokus));
  assert.equal(zeitZeile(ohneDauer), "50 % Fokus · 25 % andere Themen · 25 % ohne Thema (4 Termine, nach Anzahl)");
  assert.deepEqual([stunden(45), stunden(60), stunden(270)], ["45 min", "1 h", "4,5 h"]);
  assert.equal(dauerIndex("{kaputt").size, 0);
});

test("Heute-Zeilen und Warnungen – dieselben Regeln wie die Engine", async () => {
  const src = vault();
  const index = new VaultIndex(src);
  const tasks = (await scanTasks(src)).filter(isOpen);
  const idx = dauerIndex(await src.readFile("archive/calendar/events.json"));
  const termine = index.termine("2026-09-22", "2026-10-05").map((t) => ({ ...t, minuten: dauerFuer(t, idx) }));
  const [p, d] = fokusZeilen(fokusThemen(index.topics(), HEUTE), tasks, termine, "ich-selbst", HEUTE);
  assert.deepEqual([p.warnungen, p.termine, p.tageBisZiel], [[], { anzahl: 2, minuten: 120 }, 55]);
  assert.deepEqual(d.warnungen, ["kein nächster Schritt", "seit 35 Tagen keine Bewegung",
                                 "kein Termin in den nächsten 14 Tagen", "kein Ziel formuliert"]);
});

test("Fokus planen: der Schritt wird ein normaler Punkt – vor dem Altbestand, ohne Dublette, Abschnitt notfalls neu", () => {
  const zeile = renderTask({ text: "Freigabe  im Board holen", owner: { slug: "ich-selbst", name: "Ich Selbst" },
                             topics: [{ slug: "portal", name: "Portal" }], due: "2026-10-09", created: HEUTE });
  assert.equal(zeile, `- [ ] Freigabe im Board holen — ${ICH} · [[portal|Portal]] 📅 2026-10-09 ➕ 2026-10-06`);
  const t = parseLine(zeile)!;
  assert.deepEqual([t.text, t.owner, t.topics, t.due, t.created], ["Freigabe im Board holen", "ich-selbst", ["portal"], "2026-10-09", HEUTE]);

  const mitAlt = "# P\n\n## Offene Punkte\n- [ ] A — [[x]]\n\n### Altbestand – im nächsten Termin prüfen\n- [ ] Alt\n\n## Event Log\n";
  const r = appendToSection(mitAlt, TOPIC_SECTION, [zeile]);
  assert.equal(r.text, `# P\n\n## Offene Punkte\n- [ ] A — [[x]]\n${zeile}\n\n### Altbestand – im nächsten Termin prüfen\n- [ ] Alt\n\n## Event Log\n`);
  assert.equal(appendToSection(r.text, TOPIC_SECTION, [zeile]).added, 0, "Dublette");

  const ohne = "# P\n\nText\n\n## Event Log\n- [2026-10-01] [STATUS] x\n";
  assert.equal(appendToSection(ohne, TOPIC_SECTION, [zeile]).text,
               `# P\n\nText\n\n## Offene Punkte\n${zeile}\n\n## Event Log\n- [2026-10-01] [STATUS] x\n`);
  assert.equal(appendToSection("# P\n", TOPIC_SECTION, [zeile]).text, `# P\n\n## Offene Punkte\n${zeile}\n`);
});

test("Chat: Werkzeug `fokus` mit den Zahlen vom Code; ohne Fokus ein Hinweis zum Festlegen", async () => {
  const src = vault();
  const g = await baueGraph(src, "ich-selbst");
  const r = await fuehreAus("fokus", {}, g, src, { today: HEUTE, me: "ich-selbst" });
  assert.equal(r.schritt, "liest deinen Fokus");
  assert.ok(r.text.startsWith("Fokus-Themen (2, nach Rang; Stand 06.10.2026). Deine Zeit in den letzten 14 Tagen: "
    + "57 % Fokus · 29 % andere Themen · 14 % ohne Thema (3,5 h in 4 Terminen)."), r.text);
  assert.ok(r.text.includes("1. [[portal|Portal]] · Ampel gelb · Ziel: Neues Portal live · Zieltermin 30.11.2026 (noch 55 Tage) · mit 1 Unterthema"), r.text);
  assert.ok(r.text.includes("nächster eigener Schritt: Suchindex freigeben (fällig 09.10.2026) · 2 offen"), r.text);
  assert.ok(r.text.includes("Warnungen: kein nächster Schritt; seit 35 Tagen keine Bewegung"), r.text);
  const leer = new MemorySource({ "entities/projects/x.md": "---\ntype: project\ntitle: X\n---\n" });
  const l = await fuehreAus("fokus", {}, await baueGraph(leer, ""), leer, { today: HEUTE, me: "" });
  assert.ok(l.text.startsWith("Es sind keine Fokus-Themen festgelegt."), l.text);
  assert.equal(fokusText([], zeitVerteilung([], new Map()), 14, HEUTE).startsWith("Es sind keine"), true);
});
