// Schreiben, waehrend die Engine laeuft (core/inarbeit.ts) und die Warteliste fuer den Termin, den sie
// gerade nachbereitet (core/nacherfassen.ts: Wartend, anwenden, vormerken). Namen erfunden.
import assert from "node:assert/strict";
import { test } from "node:test";
import { IN_ARBEIT_MAX_MS, inArbeit, nachziehenOffen, nachziehenText, schreibweg } from "../src/core/inarbeit";
import { NOTES_HEADING, Wartend, anwenden, vormerken } from "../src/core/nacherfassen";

const A = "active-meetings/2026-09-30 - checkin - Portal.md";
const B = "active-meetings/2026-09-30 - review - Hof.md";

test("in Arbeit: die Datei der Engine – gültig, verwaist, kaputt, fehlt", () => {
  const datei = JSON.stringify({ pfade: [A], pid: 4711, seit: "2026-09-30T12:00:00" });
  assert.deepEqual(inArbeit(datei, 5_000), [A]);
  assert.deepEqual(inArbeit(datei, IN_ARBEIT_MAX_MS), [], "nach 30 Minuten verwaist");
  assert.deepEqual(inArbeit("{kaputt", 0), []);
  assert.deepEqual(inArbeit(JSON.stringify({ pfade: [A, 7, null] }), 0), [A], "nur Pfade");
  assert.deepEqual(inArbeit(null, 0), []);
});

test("Schreibweg: Sperre frei → kurz sperren; Engine läuft → andere Notiz sofort, dieselbe wartet", () => {
  assert.equal(schreibweg(A, true, [A]), "sperren", "keine Engine läuft: die Sperre nehmen");
  assert.equal(schreibweg(B, false, [A]), "sofort", "Engine bereitet A nach – B wird trotzdem geschrieben");
  assert.equal(schreibweg(B, false, []), "sofort", "Automatik läuft, arbeitet an keinem Termin");
  assert.equal(schreibweg(A, false, [A]), "warten", "genau der Termin, den die Engine gerade schreibt");
});

test("Nachziehen: Stand der Engine lesen – nur was offen ist, kaputt oder fehlend heißt nichts offen", () => {
  const datei = JSON.stringify({ mail: { fassung: 2, gesamt: 40, offen: 12 }, fertig: { fassung: 1, gesamt: 5, offen: 0 } });
  assert.deepEqual(nachziehenOffen(datei), [{ name: "mail", offen: 12, gesamt: 40 }]);
  assert.equal(nachziehenText(nachziehenOffen(datei)), "Mails 12 von 40");
  assert.deepEqual([nachziehenOffen("{kaputt"), nachziehenOffen(null)], [[], []]);
});

test("Warteliste: Notizen sammeln sich, ein Schalter ersetzt den vorigen, anwenden wie sofort", () => {
  const w = (art: Wartend["art"], x: Partial<Wartend> = {}): Wartend =>
    ({ pfad: A, titel: "Checkin Portal", art, seit: "2026-09-30T12:00:00Z", ...x });
  let liste = vormerken([], w("notizen", { text: "Erstens" }));
  liste = vormerken(liste, w("notizen", { text: "Zweitens", nachbereiten: true }));
  liste = vormerken(liste, w("ueberspringen", { an: true }));
  liste = vormerken(liste, w("ueberspringen", { an: false }));
  liste = vormerken(liste, w("ueberspringen", { pfad: B, an: true }));
  assert.deepEqual(liste.map((x) => [x.pfad === A ? "A" : "B", x.art, x.text ?? x.an]),
                   [["A", "notizen", "Erstens"], ["A", "notizen", "Zweitens"], ["A", "ueberspringen", false],
                    ["B", "ueberspringen", true]]);
  const note = "---\ntype: meeting\ntitle: Checkin Portal\nstatus: vorbereitet\n---\n# Checkin Portal\n";
  const r = anwenden(liste[0], note, "2026-09-30");
  assert.ok(r.ok && r.text?.includes(`${NOTES_HEADING}\n\nErstens`), r.text);
  const zwei = anwenden(liste[1], r.text ?? "", "2026-09-30");
  assert.ok(zwei.text?.includes("**Nachgetragen am 30.09.2026:**\n\nZweitens"), zwei.text);
  assert.ok(anwenden(w("entfallen", { an: true }), note, "2026-09-30").text?.includes("status: entfallen"));
  assert.ok(anwenden(w("vormerken", { an: true }), note, "2026-09-30").text?.includes("nachbereiten: angefordert"));
});
