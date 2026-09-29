import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MeetingInfo, TaskInfo, addDays, daysBetween, followUps, hasMaterial, localIsoDate,
  materialText, meetingPhase, meetingsOn, missingNotes, myTasks, pendingWrapups, sectionLines, standBlock,
  TopicInfo, dayLabel, exampleTopics, isPersonMeeting, nextMeetingDay, radarAttention, radarCounts, shortReason, taskBuckets, weekdayDate,
  cockpitTasks, riskSummary, sortAltbestand,
} from "../src/core/ansicht";

const meeting = (over: Partial<MeetingInfo>): MeetingInfo => ({
  path: "active-meetings/x.md", title: "X", date: "2026-09-28", time: "", type: "checkin",
  topic: null, status: "vorbereitet", persons: [], hasMaterial: false, ...over,
});

const task = (over: Partial<TaskInfo>): TaskInfo => ({
  status: " ", text: "T", kind: "aufgabe", owner: null, owner_raw: null, topics: [],
  due: null, created: null, path: null, line: null, fmt: "neu", ...over,
});

test("lokales Datum statt UTC (alter Plugin-Fehler um Mitternacht)", () => {
  assert.equal(localIsoDate(new Date(2026, 8, 28, 23, 59)), "2026-09-28");
  assert.equal(localIsoDate(new Date(2026, 8, 29, 0, 1)), "2026-09-29");
  assert.equal(addDays("2026-09-30", 1), "2026-10-01");
  assert.equal(daysBetween("2026-09-14", "2026-09-28"), 14);
});

test("Phase eines Termins", () => {
  const today = "2026-09-28";
  assert.equal(meetingPhase(meeting({ date: "2026-09-29" }), today), "vorbereitet");
  assert.equal(meetingPhase(meeting({ date: "2026-09-29", status: "" }), today), "vorbereiten");
  assert.equal(meetingPhase(meeting({ date: today, hasMaterial: true }), today), "nachbereiten");
  assert.equal(meetingPhase(meeting({ date: "2026-09-21" }), today), "notizen-fehlen");
  assert.equal(meetingPhase(meeting({ date: "2026-09-21", status: "nachbereitet", hasMaterial: true }), today),
               "nachbereitet");
});

test("Termine eines Tages nach Uhrzeit, offene Nachbereitungen der letzten 14 Tage", () => {
  const ms = [meeting({ title: "B", time: "13:00" }), meeting({ title: "A", time: "09:00" }),
              meeting({ title: "C", date: "2026-09-21", hasMaterial: true }),
              meeting({ title: "alt", date: "2026-09-01", hasMaterial: true })];
  assert.deepEqual(meetingsOn(ms, "2026-09-28").map((m) => m.title), ["A", "B"]);
  assert.deepEqual(pendingWrapups(ms, "2026-09-28").map((m) => m.title), ["C"]);
});

test("Nachfassen: nur Anwesende, nie ich selbst, Ueberfaelliges zuerst", () => {
  const tasks = [
    task({ text: "neu", owner: "anna", created: "2026-09-27" }),
    task({ text: "alt", owner: "anna", created: "2026-08-01" }),
    task({ text: "ueberfaellig", owner: "tom", created: "2026-09-20", due: "2026-09-25" }),
    task({ text: "meins", owner: "daniel-mohr", created: "2026-08-01" }),
    task({ text: "fremd", owner: "zoe", created: "2026-08-01" }),
    task({ text: "Frage?", owner: "anna", kind: "frage", created: "2026-09-10" }),
  ];
  const fus = followUps(tasks, ["anna", "tom", "daniel-mohr"], "daniel-mohr", "2026-09-28", 10);
  assert.deepEqual(fus.map((f) => f.task.text), ["ueberfaellig", "alt", "Frage?", "neu"]);
  assert.equal(fus.find((f) => f.task.text === "Frage?")?.kind, "frage");
});

test("Material: Kommentare und Platzhalter zaehlen nicht", () => {
  const empty = "## Meine Notizen\n<!-- Mitschrift hier -->\n_(wird vom Prep-Lauf gefüllt)_\n## Actions\n";
  assert.equal(hasMaterial(empty), false);
  const real = "## Meine Notizen\n" + "Echte Notiz. ".repeat(20) + "\n## Actions\n";
  assert.equal(hasMaterial(real), true);
  assert.equal(hasMaterial("## Teams-Zusammenfassung\n" + "x".repeat(250)), true);
});

test("Stand-Block ohne Dataview-Abfrage", () => {
  const text = "# T\n<!-- stand-auto:start -->\n> [!abstract] Stand\n> Prosa.\n\n"
    + "**Offene Punkte aus Meetings und anderen Themen**\n\n```dataview\nTASK\n```\n"
    + "<!-- stand-auto:end -->\n## Event Log\n";
  assert.equal(standBlock(text), "> [!abstract] Stand\n> Prosa.");
  assert.equal(standBlock("# ohne Block"), null);
});

test("Nacherfassen: fehlende Notizen der letzten 14 Tage, entfallene zaehlen nicht", () => {
  const today = "2026-09-28";
  const ms = [meeting({ title: "leer", date: "2026-09-23", time: "10:00" }),
              meeting({ title: "leer spaet", date: "2026-09-23", time: "15:00" }),
              meeting({ title: "mit Notizen", date: "2026-09-24", hasMaterial: true }),
              meeting({ title: "entfallen", date: "2026-09-25", status: "entfallen" }),
              meeting({ title: "heute", date: today }),
              meeting({ title: "zu alt", date: "2026-09-01" })];
  assert.deepEqual(missingNotes(ms, today).map((m) => m.title), ["leer spaet", "leer"]);
  assert.equal(meetingPhase(ms[3], today), "entfallen");
});

test("Material und Abschnitte fuer Fenster und Ergebnis", () => {
  const text = ["## Meine Notizen", "<!-- Mitschrift -->", "Ines liefert die Liste.",
                "## Entscheidungen", "", "- [E] Englisch — ?", "<!-- - [E] Was -->", "## Actions", ""].join("\n");
  assert.equal(materialText(text), "Ines liefert die Liste.");
  assert.equal(hasMaterial(text), false);        // < 30 Zeichen
  assert.equal(hasMaterial(text, 10), true);
  assert.deepEqual(sectionLines(text, "## Entscheidungen"), ["- [E] Englisch — ?"]);
});

test("Meine Aufgaben: ueberfaellig zuerst, dann Frist, dann die aeltesten; keine Fragen, nur meine", () => {
  const me = "daniel-mohr";
  const ts = [
    task({ text: "ohne Frist neu", owner: me, created: "2026-09-20" }),
    task({ text: "spaeter", owner: me, due: "2026-10-20" }),
    task({ text: "ohne Frist alt", owner: me, created: "2026-08-01" }),
    task({ text: "ueberfaellig", owner: me, due: "2026-09-01" }),
    task({ text: "bald", owner: me, due: "2026-09-30" }),
    task({ text: "Frage", owner: me, kind: "frage" }),
    task({ text: "von Anna", owner: "anna", due: "2026-09-01" }),
  ];
  const r = myTasks(ts, me, "2026-09-28");
  assert.deepEqual(r.list.map((t) => t.text), ["ueberfaellig", "bald", "spaeter", "ohne Frist alt", "ohne Frist neu"]);
  assert.equal(r.overdue, 1);
});

const topic = (over: Partial<TopicInfo>): TopicInfo => ({
  slug: "t", path: "entities/projects/t.md", title: "T", health: "green", reason: "", overdue: 0,
  risks: 0, altbestand: 0, nextMeeting: "", ...over,
});

test("Radar in Heute: rot vor gelb, dann Ueberfaelliges und Risiken; gruen nie", () => {
  const ts = [topic({ title: "gelb viel", health: "yellow", overdue: 3 }),
              topic({ title: "gruen", health: "green", overdue: 9 }),
              topic({ title: "rot", health: "red" }),
              topic({ title: "gelb risiko", health: "yellow", risks: 5 }),
              topic({ title: "gelb wenig", health: "yellow", overdue: 1 })];
  assert.deepEqual(radarAttention(ts, 3).map((t) => t.title), ["rot", "gelb viel", "gelb wenig"]);
  assert.deepEqual(radarCounts(ts), { red: 1, yellow: 3, green: 1 });
  // Oberthema mit geerbter Ampel: weder in der Liste noch in den Zahlen doppelt
  const withRoof = [...ts, topic({ title: "Dach", health: "red", inherited: true })];
  assert.deepEqual(radarAttention(withRoof, 1).map((t) => t.title), ["rot"]);
  assert.deepEqual(radarCounts(withRoof), { red: 1, yellow: 3, green: 1 });
});

test("Meine Aufgaben gruppiert, hoechstens n insgesamt", () => {
  const today = "2026-09-28";
  const ts = [task({ text: "a", due: "2026-09-20" }), task({ text: "b", due: "2026-09-30" }),
              task({ text: "c", due: "2026-10-20" }), task({ text: "d" }), task({ text: "e" })];
  const g = taskBuckets(ts, today, 4);
  assert.deepEqual(g.map((x) => [x.label, x.tasks.map((t) => t.text)]),
    [["Überfällig", ["a"]], ["Diese Woche", ["b"]], ["Später", ["c"]], ["Ohne Frist", ["d"]]]);
});

test("Naechster Termintag (Wochenende -> Montag), Tagesnamen, Ueberspringen", () => {
  const ms = [meeting({ date: "2026-09-28" }), meeting({ date: "2026-09-29" }),
              meeting({ date: "2026-09-27", skip: true })];
  assert.equal(nextMeetingDay(ms, "2026-09-26"), "2026-09-28");
  assert.equal(nextMeetingDay(ms, "2026-10-10"), null);
  assert.equal(dayLabel("2026-09-27", "2026-09-27"), "heute");
  assert.equal(dayLabel("2026-09-28", "2026-09-27"), "morgen");
  assert.equal(weekdayDate("2026-09-28"), "Mo 28.09.");
  assert.equal(meetingPhase(meeting({ date: "2026-09-24", skip: true }), "2026-09-28"), "uebersprungen");
  assert.deepEqual(missingNotes([meeting({ date: "2026-09-24", skip: true })], "2026-09-28"), []);
});

test("Ampel-Grund kurz", () => {
  assert.equal(shortReason(topic({ reason: "2 Risiko/Risiken in den letzten 30 Tagen; 1 überfällige Aufgabe",
                                   overdue: 1, risks: 2 })), "1 überfällig · 2 Risiken");
  assert.equal(shortReason(topic({ reason: "Zieltermin 2026-09-01 überschritten" })), "Ziel überschritten");
  assert.equal(shortReason(topic({ reason: "pausiert" })), "pausiert");
});

test("Personen-Termin erkennen", () => {
  assert.equal(isPersonMeeting("Jourfix: Kuno/Daniel", "other"), true);
  assert.equal(isPersonMeeting("NoLa Product BPM Jour Fixe", "other"), true);
  assert.equal(isPersonMeeting("1:1 Anna", ""), true);
  assert.equal(isPersonMeeting("Blue Cargo Checkin", "checkin"), false);
  assert.equal(isPersonMeeting("Irgendwas", "oneonone"), true);
});

test("Beispiel-Themen kommen aus dem Vault: naechster Termin zuerst, ohne Klammer-Zusatz, ohne Oberthemen", () => {
  const t = (title: string, nextMeeting: string, inherited = false): TopicInfo => ({
    slug: title.toLowerCase(), path: "", title, health: "", reason: "", overdue: 0, risks: 0, altbestand: 0,
    nextMeeting, inherited });
  const topics = [t("Portal (Produkt)", "2026-10-02"), t("Lager", "2026-09-30"), t("Nord", "2026-09-29", true),
                  t("Ohne Termin", ""), t("Versand", "2026-10-05")];
  assert.deepEqual(exampleTopics(topics), ["Lager", "Portal"]);
  assert.deepEqual(exampleTopics(topics, 1), ["Lager"]);
  assert.deepEqual(exampleTopics([t("Ohne Termin", "")]), []);
});

test("Aufgaben-Seite: Abschnitte wie die frühere dataviewjs-Fassung, Punkte aus der Engine", () => {
  const today = "2026-09-28";
  const tasks = [
    task({ text: "meins spät", owner: "ich", due: "2026-09-20" }),
    task({ text: "meins bald", owner: "ich", due: "2026-10-01" }),
    task({ text: "meins später", owner: "ich", due: "2026-11-01" }),
    task({ text: "meins ohne", owner: "ich", created: "2026-09-01" }),
    task({ text: "anna 1", owner: "anna", created: "2026-09-10" }),
    task({ text: "anna 2", owner: "anna", due: "2026-09-25" }),
    task({ text: "gernot", owner: "gernot" }),
    task({ text: "gernot 2", owner: "gernot" }),
    task({ text: "❓ an anna", owner: "anna", kind: "frage" }),
    task({ text: "❓ an niemand", kind: "frage", path: "b.md" }),
    task({ text: "wer?", path: "a.md" }),
  ];
  const c = cockpitTasks(tasks, "ich", today);
  assert.deepEqual(c.mine.map((b) => [b.label, b.tasks.map((t) => t.text)]), [
    ["Überfällig", ["meins spät"]], ["Fällig in 7 Tagen", ["meins bald"]],
    ["Später fällig", ["meins später"]], ["Ohne Frist – älteste zuerst", ["meins ohne"]]]);
  assert.equal(c.mineCount, 4);
  // Nachfassen: wer Ueberfaelliges hat, zuerst - innerhalb nach Dringlichkeit
  assert.deepEqual(c.others.map((g) => [g.owner, g.overdue, g.tasks.map((t) => t.text)]),
    [["anna", 1, ["anna 2", "anna 1"]], ["gernot", 0, ["gernot", "gernot 2"]]]);
  assert.equal(c.othersCount, 4);
  assert.deepEqual(c.questions.map((g) => g.owner), ["anna", ""]);
  // Person unklar: auch Fragen ohne Adressat, nach Fundstelle
  assert.deepEqual(c.unclear.map((t) => t.text), ["wer?", "❓ an niemand"]);
});

test("Altbestand: mit Termin zuerst, dann die meisten; Risiken zählen", () => {
  const rows = sortAltbestand([
    { path: "a", title: "A", altbestand: 2, nextMeeting: "" },
    { path: "b", title: "B", altbestand: 5, nextMeeting: "2026-10-02" },
    { path: "c", title: "C", altbestand: 9, nextMeeting: "2026-10-02" },
    { path: "d", title: "D", altbestand: 0, nextMeeting: "2026-09-29" },
  ]);
  assert.deepEqual(rows.map((r) => r.title), ["C", "B", "A"]);
  const risk = (pfad: string, aktiv: boolean) => ({ datum: "", alter: 0, aktiv, art: "", pfad, titel: "", text: "", quelle: "" });
  assert.deepEqual(riskSummary([risk("p", true), risk("p", false), risk("q", true)]), { total: 3, orte: 2, aktiv: 2 });
});
