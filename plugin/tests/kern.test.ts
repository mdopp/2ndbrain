// Tests fuer src/core ohne Obsidian (Dateien im Speicher); die Faelle zu Punkten, Themen-Log und
// Nacherfassen entsprechen denen in engine/tests/test_tools.py.
import assert from "node:assert/strict";
import { test } from "node:test";
import { appendNotes, fmGet, fmUpdate, setWrapupRequest, yamlScalar } from "../src/core/nacherfassen";
import { logEntries, newestFirst, riskLines } from "../src/core/themenlog";
import { checkLinks, timeWindow } from "../src/core/chat";
import { label, pictureWish } from "../src/core/chatBilder";
import { HttpPost, complete, stripThink } from "../src/core/modell";
import { casefold, splitlines, squash, strip } from "../src/core/pytext";
import { riskRows } from "../src/core/risiken";
import { completable, completeInText, isOpen, key, parseLine, scanTasks } from "../src/core/aufgaben";
import { VaultIndex } from "../src/core/vaultIndex";
import { withoutAssigned } from "../src/core/themen";
import { MemorySource } from "./quellen";

test("Python-Text: splitlines, strip, casefold", () => {
  assert.deepEqual(splitlines("a\nb\r\nc\rd\u2028e\n"), ["a", "b", "c", "d", "e"]);
  assert.deepEqual(splitlines("a\n\n"), ["a", ""]);
  assert.deepEqual(splitlines(""), []);
  assert.equal(strip("\u00a0 x \x85"), "x");
  assert.equal(strip("\uFEFFx"), "\uFEFFx", "BOM ist in Python kein Leerraum");
  assert.equal(squash("  a \t b\n c "), "a b c");
  assert.equal(casefold("Straße"), "strasse");
});

test("Punkte: kanonisches Format, Frage, unaufgelöste Person", () => {
  const t = parseLine("- [ ] Freigaberunde-Entscheidung einfordern — [[kasimir-kempf|Kasimir Kempf]]"
    + " · [[blue-cargo|Blue Cargo]] 📅 2026-10-03 ➕ 2026-09-14 (→ [[2026-09-14 - Checkin - BlueCargo]])")!;
  assert.deepEqual([t.text, t.owner, t.topics, t.due, t.created, t.source, t.fmt, isOpen(t)],
    ["Freigaberunde-Entscheidung einfordern", "kasimir-kempf", ["blue-cargo"], "2026-10-03", "2026-09-14",
     "2026-09-14 - Checkin - BlueCargo", "neu", true]);
  const q = parseLine("- [ ] ❓ Steht der Frankreich-Termin? — an [[robert-senger|Robert Senger]] ➕ 2026-08-03")!;
  assert.deepEqual([q.kind, q.text, q.owner], ["frage", "Steht der Frankreich-Termin?", "robert-senger"]);
  const u = parseLine("- [x] Lizenzfrage klaeren — Robert (?) · [[blue-cargo]] ✅ 2026-09-30")!;
  assert.deepEqual([u.owner, u.owner_raw, isOpen(u), u.done], [null, "Robert", false, "2026-09-30"]);
});

test("Punkte: Kurzform lesbar, [ACTION]-Zeilen sind keine Punkte, Gedankenstrich im Text ist keine Person", () => {
  const a = parseLine("- [ ] Plan abstimmen — @Felix — 2026-10-01")!;
  assert.deepEqual([a.text, a.owner_raw, a.due, a.fmt], ["Plan abstimmen", "Felix", "2026-10-01", "kurz"]);
  const b = parseLine("- [ ] Plan abstimmen — @Felix — —")!;
  assert.deepEqual([b.owner_raw, b.due], ["Felix", null]);
  assert.equal(parseLine("- [2026-08-31] [ACTION] @unassigned: Felix - LOI klaeren -> Deadline: TBD"), null);
  const d = parseLine("- [ ] Daten **vorab** einsammeln — im Termin wird ausgewertet, nicht erhoben")!;
  assert.deepEqual([d.text.endsWith("nicht erhoben"), d.owner, d.owner_raw], [true, null, null]);
  assert.equal(parseLine("- [2026-09-14] [DECISION] Kein Punkt"), null);
  assert.equal(key("- Lizenzen klären!"), key("lizenzen  KLÄREN"));
  assert.equal(key("❓ Straße_prüfen"), "strasse prüfen");
});

test("Punkte: nur Actions/Offene Punkte, @slug nur exakt, Vorgaben aus der Datei", async () => {
  const src = new MemorySource({
    "entities/people/daniel-mohr.md": "---\ntype: person\nname: Daniel Mohr\n---\n",
    "entities/projects/blue-cargo.md": "---\ntype: project\ntitle: Blue Cargo\n---\n# Blue Cargo\n\n"
      + "## Offene Punkte\n- [ ] Migrierter Punkt — [[daniel-mohr]] ➕ 2026-09-01\n\n"
      + "### Altbestand – im nächsten Termin prüfen\n- [ ] Alter Punkt — [[daniel-mohr]]\n\n"
      + "## Event Log\n- [2026-09-14] [ACTION] @daniel-mohr: Kein Punkt mehr -> Deadline: 2026-09-20\n"
      + "- [2026-09-14] [DECISION] Keine Aufgabe\n",
    "active-meetings/2026-09-21 - review - Review Blue Cargo.md":
      "---\ntype: meeting\ndate: '2026-09-21'\nthemen: [blue-cargo]\n---\n"
      + "## Vorbereitung\n- [ ] Daten vorab einsammeln — im Termin wird ausgewertet\n\n"
      + "## Actions\n- [ ] Magnus informieren — [[daniel-mohr]]\n"
      + "- [ ] Terrorcheck — @daniel-mohr — 2026-09-20\n- [ ] Irgendwas — @kuno — TBD\n",
  });
  const found = await scanTasks(src);
  assert.deepEqual(found.map((t) => t.text).sort(),
    ["Alter Punkt", "Irgendwas", "Magnus informieren", "Migrierter Punkt", "Terrorcheck"]);
  const by = Object.fromEntries(found.map((t) => [t.text, t]));
  assert.equal(by["Terrorcheck"].owner, "daniel-mohr");
  assert.deepEqual([by["Irgendwas"].owner, by["Irgendwas"].owner_raw], [null, "kuno"]);
  assert.deepEqual(by["Magnus informieren"].topics, ["blue-cargo"]);
  assert.equal(by["Magnus informieren"].created, "2026-09-21");
  assert.equal(by["Magnus informieren"].path, "active-meetings/2026-09-21 - review - Review Blue Cargo.md");
  assert.deepEqual([by["Migrierter Punkt"].topics, by["Migrierter Punkt"].pruefen], [["blue-cargo"], false]);
  assert.equal(by["Alter Punkt"].pruefen, true);
  assert.equal(found[0].path?.startsWith("active-meetings/"), true, "Termine zuerst (wie die Engine)");
});

test("Abhaken: nur die erwartete Zeile, ✅ vor der Quelle, Erledigtes bleibt", () => {
  const text = "## Offene Punkte\n"
    + "- [ ] Angebot pruefen — [[anna|Anna]] 📅 2026-10-01 ➕ 2026-09-14 (→ [[q1]])\n"
    + "- [x] Schon da ➕ 2026-09-01 ✅ 2026-09-10\n";
  assert.equal(completeInText(text, 1, "Anderer Text", "2026-09-28").ok, false);
  assert.equal(completeInText(text, 9, "Angebot pruefen", "2026-09-28").ok, false);
  const r = completeInText(text, 1, "angebot pruefen!", "2026-09-28");
  assert.equal(r.ok, true);
  assert.equal(r.text!.split("\n")[1],
    "- [x] Angebot pruefen — [[anna|Anna]] 📅 2026-10-01 ➕ 2026-09-14 ✅ 2026-09-28 (→ [[q1]])");
  assert.equal(completeInText(text, 2, "Schon da", "2026-09-28").aktion, "schon erledigt");
  assert.equal(completeInText(text, 0, null, "2026-09-28").ok, false);
  const crlf = completeInText("## Actions\r\n- [ ] Tun  \r\n", 1, "Tun", "2026-09-28");
  assert.equal(crlf.text, "## Actions\n- [x] Tun ✅ 2026-09-28\n", "wie Python: \\r\\n wird \\n");
  assert.equal(completable("entities/projects/x.md"), true);
  assert.equal(completable("entities/people/x.md"), false);
  assert.equal(completable("active-meetings/../x.md"), false);
  assert.equal(completable("archive/meetings/2026-09/x.md"), true, "archivierte Termine");
});

test("Aufgaben: archivierte Termin-Notizen zählen mit (wie aufgaben.scan)", async () => {
  const src = new MemorySource({
    "active-meetings/2026-09-29 - checkin - Heute.md": "---\ntype: meeting\n---\n## Actions\n- [ ] Neu — @max\n",
    "archive/meetings/2026-09/2026-09-22 - checkin - Alt.md": "---\ntype: meeting\n---\n## Actions\n- [ ] Offen — @max\n",
    "archive/meetings/2026-09/2026-09-22-mail.md": "---\ntype: email-thread\n---\n# Mail\n- [ ] kein Punkt\n",
  });
  const found = await scanTasks(src);
  assert.deepEqual(found.map((t) => [t.path, t.text]),
    [["active-meetings/2026-09-29 - checkin - Heute.md", "Neu"],
     ["archive/meetings/2026-09/2026-09-22 - checkin - Alt.md", "Offen"]]);
});

test("Themen-Log: Einträge, Risiken im ganzen Text", () => {
  const text = "# T\n- [2026-01-01] [RISK] ausserhalb des Logs (→ [[q0]])\n\n## Event Log\n"
    + "- [2026-09-14] [DECISION] Beschluss A (→ [[q1]])\n"
    + "- [2026-09-02] [STATUS]   Freight   live\n"
    + "- [2026-09-14] [RISK] Blockiert\n## Danach\n- [2026-09-20] [STATUS] nicht im Log\n";
  const log = logEntries(text);
  assert.deepEqual(log.map((e) => [e.date, e.kind, e.text, e.line]), [
    ["2026-09-14", "DECISION", "Beschluss A (→ [[q1]])", 4],
    ["2026-09-02", "STATUS", "Freight   live", 5],
    ["2026-09-14", "RISK", "Blockiert", 6]]);
  assert.deepEqual(newestFirst(log).map((e) => e.text), ["Beschluss A (→ [[q1]])", "Blockiert", "Freight   live"]);
  assert.deepEqual(riskLines(text).map((r) => [r.date, r.rest]),
    [["2026-01-01", "ausserhalb des Logs (→ [[q0]])"], ["2026-09-14", "Blockiert"]]);
});

test("Risiken: Art, aktiv, Quelle, Reihenfolge", async () => {
  const src = new MemorySource({
    "entities/projects/p.md": "---\ntype: project\nkind: product\ntitle: Portal\n---\n## Event Log\n"
      + "- [2026-09-20] [RISK] Lizenz läuft aus (→ [[2026-09-20 - Termin|Termin]])\n"
      + "- [2026-06-01] [RISK] alt\n- [2026-02-30] [RISK] kein Datum\n",
    "entities/forums/f.md": "---\ntype: forum\nname: Runde\n---\n## Event Log\n- [2026-09-27] [RISK] Personal knapp\n",
  });
  const rows = await riskRows(src, "2026-09-28");
  assert.deepEqual(rows.map((r) => [r.datum, r.alter, r.aktiv, r.art, r.titel, r.text, r.quelle]), [
    ["2026-09-27", 1, true, "Gremium", "f", "Personal knapp", ""],
    ["2026-09-20", 8, true, "Produkt", "Portal", "Lizenz läuft aus", "2026-09-20 - Termin"],
    ["2026-06-01", 119, false, "Produkt", "Portal", "alt", ""]]);
});

test("Nacherfassen: Abschnitt an fester Stelle, Nachgetragen-Zeile, entfallen zurück", () => {
  const note = "---\ntitle: T\nstatus: entfallen\nentfallen_grund: krank\n---\n# T\n\n## Agenda\n- a\n\n## Actions\n- [ ] x\n";
  const r = appendNotes(note, "  Stichpunkt eins  \n\n", "2026-09-28");
  assert.equal(r.ok, true);
  assert.equal(r.text, "---\ntitle: T\nstatus: vorbereitet\n---\n# T\n\n## Agenda\n- a\n\n## Meine Notizen\n\n"
    + "Stichpunkt eins\n\n## Actions\n- [ ] x\n");
  const again = appendNotes(r.text!, "Zweiter", "2026-09-29");
  assert.match(again.text!, /Stichpunkt eins\n\n\*\*Nachgetragen am 29\.09\.2026:\*\*\n\nZweiter\n\n## Actions/);
  assert.equal(appendNotes(note, "   ", "2026-09-28").ok, false);
});

test("Frontmatter zeilengenau: setzen, entfernen samt Liste, anlegen; Werte eindeutig", () => {
  const t = "---\ntitle: T\nthemen:\n- a\n- b\nskip_meeting: true\n---\nText\n";
  assert.equal(fmUpdate(t, { themen: null, status: "entfallen" }),
               "---\ntitle: T\nskip_meeting: true\nstatus: entfallen\n---\nText\n");
  assert.equal(fmUpdate(t, { skip_meeting: null }), "---\ntitle: T\nthemen:\n- a\n- b\n---\nText\n");
  assert.equal(fmUpdate("Nur Text\n", { nachbereiten: "angefordert" }), "---\nnachbereiten: angefordert\n---\nNur Text\n");
  assert.equal(fmGet("---\nstatus: 'nachbereitet'\n---\n", "status"), "nachbereitet");
  assert.equal(yamlScalar("Krank"), "Krank");
  assert.equal(yamlScalar("true"), "'true'");
  assert.equal(yamlScalar("2026-10-02"), "'2026-10-02'");
  assert.equal(yamlScalar("Urlaub: lang"), "'Urlaub: lang'");
  assert.equal(yamlScalar("it's"), "'it''s'");
});

test("Vormerken: nicht, wenn schon nachbereitet oder entfallen", () => {
  const base = (status: string) => `---\ntitle: T\nstatus: ${status}\n---\n`;
  assert.equal(setWrapupRequest(base("nachbereitet"), true).ok, false);
  assert.equal(setWrapupRequest(base("entfallen"), true).ok, false);
  const r = setWrapupRequest(base("vorbereitet"), true);
  assert.equal(r.text, "---\ntitle: T\nstatus: vorbereitet\nnachbereiten: angefordert\n---\n");
  assert.equal(setWrapupRequest(r.text!, false).text, base("vorbereitet"));
});

test("Index ohne Obsidian: Termine mit Personen, Themen, Vormerkung", async () => {
  const src = new MemorySource({
    "entities/people/anna-berg.md": "---\nname: Anna Berg\n---\n",
    "entities/projects/p.md": "---\ntitle: Portal\nhealth: yellow\nnaechster_termin: '2026-10-01'\n---\n",
    "active-meetings/2026-09-28 - checkin - P.md": "---\ntitle: P Checkin\ndate: '2026-09-28'\nmeeting_time: '10:00'\n"
      + "themen: [p]\nkey_persons: [Anna Berg]\nnachbereiten: angefordert\n---\n## Meine Notizen\n\n"
      + "Genug Text zum Nachbereiten, mehr als dreißig Zeichen.\n",
  });
  const idx = new VaultIndex(src);
  const [m] = await idx.meetings("2026-09-28");
  assert.deepEqual([m.title, m.time, m.topic, m.persons, m.nachbereiten, m.hasMaterial],
                   ["P Checkin", "10:00", "p", ["anna-berg"], "angefordert", true]);
  assert.equal(idx.topic("p")?.title, "Portal");
  assert.equal(idx.personName("anna-berg"), "Anna Berg");
  assert.deepEqual(idx.topics().map((t) => [t.slug, t.health, t.nextMeeting]), [["p", "yellow", "2026-10-01"]]);
});

test("Chat: Zeitfenster aus der Frage", () => {
  const today = "2026-09-30";                               // Mittwoch
  assert.deepEqual(timeWindow("Was ist heute los?", today), ["2026-09-30", "heute"]);
  assert.deepEqual(timeWindow("Was ist seit letzter Woche passiert?", today), ["2026-09-21", "seit letzter Woche"]);
  assert.deepEqual(timeWindow("diese Woche", today), ["2026-09-28", "diese Woche"]);
  assert.deepEqual(timeWindow("die letzten 10 Tage", today), ["2026-09-20", "letzte 10 Tage"]);
  assert.deepEqual(timeWindow("seit dem 3.9.", today), ["2026-09-03", "seit 3.9."]);
  assert.equal(timeWindow("seit dem 31.2.", today), null);
  assert.equal(timeWindow("Wo steht das Portal?", today), null);
});

test("Chat: erfundene Links werden Text, Codeblöcke bleiben", () => {
  const ctx = "## Thema [[portal|Portal]]";
  const files = () => new Set(["anna-berg"]);
  assert.equal(checkLinks("Siehe [[portal]], [[anna-berg|Anna]] und [[erfunden|Quelle]].\n```mermaid\nA[[x]]\n```", ctx, files),
               "Siehe [[portal]], [[anna-berg|Anna]] und Quelle.\n```mermaid\nA[[x]]\n```");
});

test("Chat: Bildwunsch, Mermaid-Beschriftung", () => {
  assert.equal(pictureWish("Zeig mir den Verlauf als Bild", { themen: ["p"] }), "bild-verlauf");
  assert.equal(pictureWish("Zeig mir den Verlauf als Bild", {}), null);
  assert.equal(pictureWish("Mal die Reihen auf", {}), "bild-reihen");
  assert.equal(pictureWish("Wo steht das Portal?", { themen: ["p"] }), null);
  assert.equal(label('Portal "Nord" [neu] | alt'), "Portal Nord neu alt");
  assert.equal(label("x".repeat(50), 10), "xxxxxxxxx…");
});

test("Modell-Aufruf: Nutzlast wie modell.py, Antwort entschärft, <think> weg", async () => {
  let sent: { url: string; body: Record<string, unknown> } | null = null;
  const post: HttpPost = async (url, body) => {
    sent = { url, body: body as Record<string, unknown> };
    return { status: 200, json: { choices: [{ message: { content: "<think>hm</think>Antwort\n```dataviewjs\nx\n```" } }] }, text: "" };
  };
  const out = stripThink(await complete(post, { url: "http://m:1/", model: "q", timeoutS: 5 },
                                         [{ role: "user", content: "hi" }], { maxTokens: 900, temperature: 0.2 }));
  assert.equal(out, "Antwort\n```text dataviewjs\nx\n```");
  assert.equal(sent!.url, "http://m:1/v1/chat/completions");
  assert.deepEqual(sent!.body, { model: "q", messages: [{ role: "user", content: "hi" }], max_tokens: 900, stream: false,
                                 temperature: 0.2, top_p: 0.9, enable_thinking: false, chat_template_kwargs: { enable_thinking: false } });
  const fail: HttpPost = async () => ({ status: 409, json: { error: { message: "Modus haushalt" } }, text: "" });
  await assert.rejects(complete(fail, { url: "http://m:1", model: "q", timeoutS: 5 }, [], { maxTokens: 1, temperature: 0 }),
                       /HTTP 409: Modus haushalt/);
});

test("Ohne Thema: nach dem Setzen faellt der Termin sofort weg, fuer die Reihe alle ihre Termine", () => {
  const open = [
    { reihe: "team-runde", note: "active-meetings/a1.md" },
    { reihe: "team-runde", note: null },
    { reihe: "wochenplan", note: "active-meetings/w.md" },
  ];
  const keys = (xs: typeof open) => xs.map((s) => `${s.reihe}:${s.note ?? "-"}`);
  assert.deepEqual(keys(withoutAssigned(open, { kind: "note", path: "active-meetings/w.md" }, false)),
                   ["team-runde:active-meetings/a1.md", "team-runde:-"]);
  assert.deepEqual(keys(withoutAssigned(open, { kind: "note", path: "active-meetings/a1.md" }, false)),
                   ["team-runde:-", "wochenplan:active-meetings/w.md"]);
  assert.deepEqual(keys(withoutAssigned(open, { kind: "note", path: "active-meetings/a1.md" }, true)),
                   ["wochenplan:active-meetings/w.md"]);
  assert.deepEqual(keys(withoutAssigned(open, { kind: "serie", key: "team-runde" }, true)),
                   ["wochenplan:active-meetings/w.md"]);
});

test("Index: auch aeltere offene Termine mit Material, Datum notfalls aus timestamp", async () => {
  const src = new MemorySource({
    "active-meetings/2026-08-01 - review - Alt.md": "---\ntitle: Alt\ndate: '2026-08-01'\n---\n## Meine Notizen\n\n"
      + "Genug Text zum Nachbereiten, mehr als dreißig Zeichen.\n",
    "active-meetings/2026-08-02---sonstiges---runde.md": "---\ntitle: Runde\ntimestamp: 2026-08-02 00:00:00+02:00\n---\n",
  });
  const ms = await new VaultIndex(src).meetings("2026-09-28");
  assert.deepEqual(ms.map((m) => [m.title, m.date, m.hasMaterial]).sort(),
                   [["Alt", "2026-08-01", true], ["Runde", "2026-08-02", false]]);
});
