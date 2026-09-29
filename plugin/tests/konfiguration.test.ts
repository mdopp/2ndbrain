import assert from "node:assert/strict";
import { test } from "node:test";
import { applyPatch, calendarSourceKind, getPath } from "../src/konfiguration";

test("Konfiguration: einzelne Schlüssel setzen, Rest bleibt, leer entfernt", () => {
  const cur = { ich: "anna", kanon: { format: "domain-atlas", regeln: { x: 1 } }, glossar: { beispiele: "auto" } };
  const next = applyPatch(cur, { ich: "gernot", "kanon.pfad": "kanon.yaml", "glossar.beispiele": "" });
  assert.deepEqual(next, { ich: "gernot", kanon: { format: "domain-atlas", regeln: { x: 1 }, pfad: "kanon.yaml" }, glossar: {} });
  assert.deepEqual(cur.kanon, { format: "domain-atlas", regeln: { x: 1 } }, "Eingabe verändert");
  assert.equal(getPath(next, "kanon.format"), "domain-atlas");
  assert.equal(getPath(null, "ich"), undefined);
  assert.deepEqual(applyPatch({ kanon: "kaputt" }, { "kanon.format": "einfach" }), { kanon: { format: "einfach" } });
});

test("Kalender-Adresse: wie kalender.source_kind", () => {
  assert.equal(calendarSourceKind("https://outlook.example.com/owa/calendar/x/reachcalendar.ics"), "web");
  assert.equal(calendarSourceKind("webcal://p01-caldav.icloud.com/published/2/abc"), "web");
  assert.equal(calendarSourceKind("http://kein-kalender"), "");
  assert.equal(calendarSourceKind("C:\\Kalender\\privat.ics"), "datei");
  assert.equal(calendarSourceKind("file:///home/a/k.ics"), "datei");
  assert.equal(calendarSourceKind("mein kalender"), "");
});
