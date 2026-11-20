// Rueckfragen lesen und beantworten (core/rueckfragen.ts), Punkt mit Hinweis und Log-Zeile (core/aufgaben.ts).
// Namen erfunden.
import assert from "node:assert/strict";
import { test } from "node:test";
import { completeInText, logEintragInText } from "../src/core/aufgaben";
import { beantworten, beantwortet, rueckfragen } from "../src/core/rueckfragen";

const NOTIZ = [
  "# Rückfragen", "", "Einleitung", "", "---", "",
  "### ❓ [CLARIFY-0920-101500] Mehrdeutige Person 'Anna'",
  "*Erstellt: 2026-09-20* *(Quelle: [[2026-09-19 - checkin - Hallenrunde.md]])* ", "",
  "**Situation / Kontext:**", "Im Termin wurde nur „Anna“ genannt.", "",
  "**Optionen zur Auswahl:**", "- [ ] A) Anna Bauer (anna-bauer)", "- [ ] B) Anna Berg (anna-berg)", "- [ ] C) Unklar – bleibt", "", "---", "",
  "### ❓ [CLARIFY-0921-090000] Wer ist 'Tom'?", "*Erstellt: 2026-09-21* ", "", "- [x] A) Unklar – Datei bleibt", "> Hinweis: schon geklärt", "", "---", "",
  "### ✅ [CLARIFY-0901-080000] ~~Erledigt~~", "*Geloest am 2026-09-02: x*", "",
].join("\n");

test("Rückfragen: offene Karten mit Kontext, Quelle, Optionen und Hinweis", () => {
  const k = rueckfragen(NOTIZ);
  assert.deepEqual(k.map((x) => x.id), ["CLARIFY-0920-101500", "CLARIFY-0921-090000"]);
  assert.equal(k[0].titel, "Mehrdeutige Person 'Anna'");
  assert.equal(k[0].kontext, "Im Termin wurde nur „Anna“ genannt.");
  assert.equal(k[0].quelle, "2026-09-19 - checkin - Hallenrunde.md");
  assert.equal(k[0].erstellt, "2026-09-20");
  assert.deepEqual(k[0].optionen.map((o) => o.text), ["A) Anna Bauer (anna-bauer)", "B) Anna Berg (anna-berg)", "C) Unklar – bleibt"]);
  assert.equal(beantwortet(k[0]), false);
  assert.equal(k[1].hinweis, "schon geklärt");
  assert.equal(beantwortet(k[1]), true);
});

test("Rückfragen: Antwort setzt genau einen Haken und den Hinweis; die anderen Karten bleiben", () => {
  const neu = beantworten(NOTIZ, "CLARIFY-0920-101500", { option: 1, hinweis: "  die aus dem\nEinkauf " })!;
  const k = rueckfragen(neu);
  assert.deepEqual(k[0].optionen.map((o) => o.gewaehlt), [false, true, false]);
  assert.equal(k[0].hinweis, "die aus dem Einkauf");
  assert.ok(neu.includes("- [x] B) Anna Berg (anna-berg)\n- [ ] C) Unklar – bleibt\n> Hinweis: die aus dem Einkauf\n\n---"));
  assert.equal(k[1].hinweis, "schon geklärt");
  assert.ok(neu.includes("### ✅ [CLARIFY-0901-080000]"));
  // noch einmal anders beantwortet: der alte Haken und der alte Hinweis gehen
  const um = beantworten(neu, "CLARIFY-0920-101500", { option: 0, hinweis: "" })!;
  assert.deepEqual(rueckfragen(um)[0].optionen.map((o) => o.gewaehlt), [true, false, false]);
  assert.equal(rueckfragen(um)[0].hinweis, "");
});

test("Rückfragen: Hinweis allein genügt; ohne Aktion schließen ist eine eigene, angehakte Zeile", () => {
  const nur = beantworten(NOTIZ, "CLARIFY-0920-101500", { option: null, hinweis: "das ist Anna Bauer" })!;
  assert.deepEqual(rueckfragen(nur)[0].optionen.map((o) => o.gewaehlt), [false, false, false]);
  assert.equal(rueckfragen(nur)[0].hinweis, "das ist Anna Bauer");
  const zu = beantworten(NOTIZ, "CLARIFY-0920-101500", { option: 1, ohneAktion: true, hinweis: "hat sich erledigt" })!;
  assert.ok(zu.includes("- [ ] B) Anna Berg (anna-berg)\n- [ ] C) Unklar – bleibt\n- [x] Ohne Aktion schließen\n> Hinweis: hat sich erledigt"));
  assert.equal(beantworten(NOTIZ, "CLARIFY-0920-101500", { option: null, hinweis: "  " }), null);
  assert.equal(beantworten(NOTIZ, "CLARIFY-gibt-es-nicht", { option: 0, hinweis: "" }), null);
  assert.equal(beantworten(NOTIZ, "CLARIFY-0920-101500", { option: 7, hinweis: "" }), null);
});

const SEITE = [
  "# Thema", "", "## Offene Punkte",
  "- [ ] Angebot pruefen — [[rita]] ➕ 2026-09-14 (→ [[quelle]])",
  "  - [ ] Muster bestellen — [[rita]]", "", "## Event Log", "- [2026-09-01] [STATUS] Auftakt", "",
].join("\n");

test("Punkt mit Hinweis: erledigt, verworfen, nur Hinweis - der Satz steht als Unterpunkt darunter", () => {
  const e = completeInText(SEITE, 3, "Angebot pruefen", "2026-11-20", { hinweis: " liegt  vor " });
  assert.equal(e.aktion, "erledigt");
  assert.ok(e.text!.includes("- [x] Angebot pruefen — [[rita]] ➕ 2026-09-14 ✅ 2026-11-20 (→ [[quelle]])\n    - Erledigt am 20.11.2026: liegt vor\n"));
  const v = completeInText(SEITE, 4, "Muster bestellen", "2026-11-20", { als: "verworfen" });
  assert.ok(v.text!.includes("  - [-] Muster bestellen — [[rita]]\n      - Verworfen am 20.11.2026\n"));
  const h = completeInText(SEITE, 3, "Angebot pruefen", "2026-11-20", { als: "hinweis", hinweis: "wartet auf den Einkauf" });
  assert.ok(h.text!.includes("- [ ] Angebot pruefen — [[rita]] ➕ 2026-09-14 (→ [[quelle]])\n    - Hinweis am 20.11.2026: wartet auf den Einkauf\n"));
  assert.equal(completeInText(SEITE, 3, "Angebot pruefen", "2026-11-20", { als: "hinweis" }).ok, false);
  // ohne Angaben wie bisher: nur der Haken, kein Unterpunkt
  assert.equal(completeInText(SEITE, 3, "Angebot pruefen", "2026-11-20").text!.split("\n").length, SEITE.split("\n").length);
});

test("Log-Zeile: oben im Event Log, keine Dublette, fehlender Abschnitt entsteht", () => {
  const neu = logEintragInText(SEITE, "STATUS", "Erledigt:  Angebot pruefen – liegt vor", "2026-11-20");
  assert.ok(neu.includes("## Event Log\n- [2026-11-20] [STATUS] Erledigt: Angebot pruefen – liegt vor\n- [2026-09-01] [STATUS] Auftakt"));
  assert.equal(logEintragInText(neu, "STATUS", "Erledigt: Angebot pruefen – liegt vor", "2026-11-20"), neu);
  assert.ok(logEintragInText("# Leer\n", "DECISION", "Start im Januar", "2026-11-20").endsWith("\n## Event Log\n- [2026-11-20] [DECISION] Start im Januar\n"));
  assert.ok(logEintragInText("# T\n\n## Event Log\n\n## Notizen\n", "RISK", "x y", "2026-11-20").includes("## Event Log\n- [2026-11-20] [RISK] x y\n\n## Notizen"));
});
