// „Alles neu aufbauen“ (core/neuaufbau.ts): Stand und Ergebnis der Engine als Zeilen. Pfade erfunden.
import assert from "node:assert/strict";
import { test } from "node:test";
import { NeuaufbauStand, neuaufbauMeldung, neuaufbauZeilen } from "../src/core/neuaufbau";

const ZAHLEN = { offen: 654, meine: 127, andere: 256, person_unklar: 181, ohne_person: 90, mit_frist: 28, fragen: 43, altbestand: 349 };

test("Stand: Stufe, Fortschritt mit Restzeit, Zahlen vorher/nachher", () => {
  assert.deepEqual(neuaufbauZeilen({ ok: true, kopie: false, stufe: "" }).map((z) => z.text), ["Noch kein Neuaufbau."]);
  assert.equal(neuaufbauZeilen(null)[0].fehler, true);

  const baut: NeuaufbauStand = { ok: true, stufe: "baut", am: "2026-11-17T22:40:00", ziel: "/vaults/mein-neuaufbau",
                                 nachbereitet: 5, gesamt: 23, sekunden_je_termin: 240 };
  const z = neuaufbauZeilen(baut).map((x) => x.text);
  assert.equal(z[0], "Letzter Neuaufbau vom 17.11.: rechnet – /vaults/mein-neuaufbau");
  assert.equal(z[1], "5 von 23 Terminen nachbereitet, noch etwa 72 Minuten");

  const fertig = neuaufbauZeilen({ ok: true, stufe: "verglichen", fehler: ["a: zu wenig Text"],
    vergleich: { ok: true, vorher: ZAHLEN, nachher: { ...ZAHLEN, offen: 410, meine: 61, person_unklar: 40 }, faellt_weg: 300, kommt_dazu: 56 } });
  assert.ok(fertig.some((x) => x.text === "Offene Punkte: 654 → 410 · meine: 127 → 61 · Person unklar: 181 → 40"));
  assert.ok(fertig.some((x) => x.text === "300 fallen weg, 56 kommen dazu"));
  assert.ok(fertig.some((x) => x.fehler && x.text.startsWith("1 nicht neu gerechnet")));

  const unterbrochen = neuaufbauZeilen({ ok: true, stufe: "unterbrochen", grund: "Der Modell-Server antwortet nicht.", ausweg: "Netz prüfen." });
  assert.equal(unterbrochen[1].fehler, true);
  assert.equal(unterbrochen[2].text, "Netz prüfen.");
});

test("Meldung nach dem Lauf: nicht gestartet, unterbrochen, noch offen, fertig", () => {
  assert.match(neuaufbauMeldung(null), /kein Ergebnis/);
  assert.equal(neuaufbauMeldung({ ok: false, grund: "Die Automatik läuft gerade – gleich noch einmal." }),
               "Neuaufbau nicht gestartet: Die Automatik läuft gerade – gleich noch einmal.");
  assert.match(neuaufbauMeldung({ ok: false, ziel: "/k", gebaut: { ok: false, grund: "Modell gesperrt.", ausweg: "Schlüssel eintragen." } }),
               /^Neuaufbau unterbrochen: Modell gesperrt\. – Schlüssel eintragen\.$/);
  assert.match(neuaufbauMeldung({ ok: true, ziel: "/k", gebaut: { ok: true, nachbereitet: 2, offen: 21 } }), /2 Termine gerechnet, 21 noch offen/);
  assert.match(neuaufbauMeldung({ ok: true, ziel: "/k", gebaut: { ok: true, nachbereitet: 23, offen: 0 },
    vergleich: { ok: true, bericht: "/k/reports/neuaufbau-vergleich.md", vorher: ZAHLEN, nachher: { ...ZAHLEN, offen: 410, meine: 61 } } }),
               /offene Punkte 654 → 410, meine 127 → 61\. Vergleich: \/k\/reports\/neuaufbau-vergleich\.md$/);
});
