// Triage (core/triage.ts): Gruppen, Beschriftungen und die Argumente fuer die Engine. Namen erfunden.
import assert from "node:assert/strict";
import { test } from "node:test";
import { TriageErgebnis, TriagePunkt, anwendenArgs, gruppen, hinweise, knopfText, kopfZeile, metaZeile } from "../src/core/triage";

const punkt = (x: Partial<TriagePunkt>): TriagePunkt => ({
  vorschlag: "selbst", an: "", an_name: "", grund: "", art: "unklar", fokus: false, alter_tage: 5, text: "Etwas tun",
  path: "active-meetings/2026-11-10 - checkin - X.md", line: 12, due: null, created: "2026-11-10", thema: "betrieb",
  thema_titel: "Betrieb", ueberfaellig: false, altbestand: false, ...x,
});

test("Gruppen in fester Reihenfolge, leere fallen weg; der Knopf sagt, was passiert", () => {
  const woche = [
    punkt({ vorschlag: "parken", text: "Alt" }),
    punkt({ vorschlag: "uebergeben", an: "bert-direkt", an_name: "Bert Direkt", text: "Dashboard" }),
    punkt({ vorschlag: "selbst", text: "Freigabe" }),
  ];
  assert.deepEqual(gruppen(woche).map((g) => g.vorschlag), ["selbst", "uebergeben", "parken"]);
  assert.equal(gruppen(woche)[1].titel, "Vorschlag: übergeben");
  assert.equal(knopfText(woche[1]), "An Bert Direkt übergeben");
  assert.equal(knopfText(punkt({ vorschlag: "nachfassen", an_name: "Nordfracht" })), "Liegt bei Nordfracht");
  assert.equal(knopfText(woche[2]), "Passt, bleibt bei mir");
});

test("Meta-Zeile: Thema, Frist (überfällig hervorgehoben), Alter, Fokus", () => {
  assert.deepEqual(metaZeile(punkt({ due: "2026-11-01", ueberfaellig: true, alter_tage: 40, fokus: true })),
                   { text: "Betrieb · überfällig seit 01.11. · 40 Tage alt · Fokus", dringend: true });
  assert.deepEqual(metaZeile(punkt({ due: "2026-12-05", alter_tage: 0, thema_titel: "" })), { text: "betrieb · bis 05.12.", dringend: false });
});

test("Kopfzeile und Hinweise; Argumente für die Engine", () => {
  const r: TriageErgebnis = { ok: true, ich: "ich", stand: "2026-11-18", gesamt: 127, in_meiner_linie: 15, fokus_gesetzt: false,
    zahl: { selbst: 57, uebergeben: 6, nachfassen: 2, atlas: 11, parken: 51 }, woche: [punkt({})], offen_gesamt: 127 };
  assert.match(kopfZeile(r), /^127 offene Punkte bei dir – 70 davon müssen nicht bei dir bleiben \(6 übergeben, 2 nachfassen, 11 Atlas, 51 parken\)/);
  assert.equal(hinweise(r).length, 1);
  assert.equal(hinweise({ ...r, fokus_gesetzt: true, in_meiner_linie: 0 }).length, 1);
  assert.equal(hinweise({ ...r, fokus_gesetzt: true }).length, 0);

  const p = punkt({ vorschlag: "uebergeben", an: "bert-direkt", an_name: "Bert Direkt", text: "Dashboard — bauen" });
  assert.deepEqual(anwendenArgs(p, "uebergeben"),
                   ["triage", "--anwenden", p.path, "--line", "12", "--text", "Dashboard — bauen", "--als", "uebergeben", "--an", "bert-direkt"]);
  assert.deepEqual(anwendenArgs(p, "selbst").slice(-2), ["--als", "selbst"], "wer es behält, braucht kein „an“");
  assert.deepEqual(anwendenArgs(punkt({ vorschlag: "nachfassen", an: "", an_name: "Nordfracht" }), "nachfassen").slice(-2), ["--an", "Nordfracht"]);
});
