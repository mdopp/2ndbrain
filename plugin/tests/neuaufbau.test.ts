// „Alles neu aufbauen“ (core/neuaufbau.ts): Stand und Ergebnis der Engine als Zeilen. Pfade erfunden.
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdirSync, mkdtempSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  ABLEITUNG_STAND, NeuaufbauStand, ableitungBeimStart, angebotFaellig, fortsetzbar, gueltigesSeit, neuaufbauAuswerten,
  neuaufbauMeldung, neuaufbauZeilen, ohneAlteTermine, startArgs, startKnopf,
} from "../src/core/neuaufbau";
import { neuaufbauKopien, neuaufbauStand, prozessLebt } from "../src/desktop/neuaufbau";

const ZAHLEN = { offen: 654, meine: 127, andere: 256, person_unklar: 181, ohne_person: 90, mit_frist: 28, fragen: 43, altbestand: 349 };

test("Stand: Stufe, Fortschritt mit Restzeit, Zahlen vorher/nachher", () => {
  assert.deepEqual(neuaufbauZeilen({ ok: true, kopie: false, stufe: "" }).map((z) => z.text), ["Noch kein Neuaufbau."]);
  assert.equal(neuaufbauZeilen(null)[0].fehler, true);

  const baut: NeuaufbauStand = { ok: true, stufe: "baut", am: "2026-11-17T22:40:00", ziel: "/vaults/mein-neuaufbau",
                                 nachbereitet: 5, gesamt: 23, sekunden_je_termin: 240 };
  const z = neuaufbauZeilen(baut).map((x) => x.text);
  assert.equal(z[0], "Letzter Neuaufbau vom 17.11.: rechnet – /vaults/mein-neuaufbau");
  assert.ok(z.includes("5 von 23 Terminen nachbereitet, noch etwa 72 Minuten"));
  assert.ok(z.includes("Rechnet gerade nicht – „Fortsetzen“ macht weiter."), "baut, aber kein Prozess: das sagen");
  const lebt = neuaufbauZeilen({ ...baut, lebt: true, pid: 4711, kopien: 3, zuletzt: "active-meetings/2026-03-16 - runde.md" }).map((x) => x.text);
  assert.ok(lebt.includes("Rechnet gerade (Prozess 4711)."));
  assert.ok(lebt.includes("Daneben liegen 2 ältere Kopie(n) – sie bleiben, bis du sie löschst."));
  assert.ok(lebt.includes("Zuletzt gerechnet: 2026-03-16 - runde"), "woran er gerade ist, steht da");
  assert.equal(startKnopf(baut, true), "Läuft …");

  const fertig = neuaufbauZeilen({ ok: true, stufe: "verglichen", fehler: ["a: zu wenig Text"],
    vergleich: { ok: true, vorher: ZAHLEN, nachher: { ...ZAHLEN, offen: 410, meine: 61, person_unklar: 40 }, faellt_weg: 300, kommt_dazu: 56 } });
  assert.ok(fertig.some((x) => x.text === "Offene Punkte: 654 → 410 · meine: 127 → 61 · Person unklar: 181 → 40"));
  assert.ok(fertig.some((x) => x.text === "300 fallen weg, 56 kommen dazu"));
  assert.ok(fertig.some((x) => x.fehler && x.text.startsWith("1 nicht neu gerechnet")));

  const unterbrochen = neuaufbauZeilen({ ok: true, stufe: "unterbrochen", grund: "Der Modell-Server antwortet nicht.", ausweg: "Netz prüfen." });
  assert.equal(unterbrochen[1].fehler, true);
  assert.equal(unterbrochen[2].text, "Netz prüfen.");
});

test("Angebot nach einem Update: nur bei bestehendem Vault mit älterer Ableitung; der Knopf setzt fort", () => {
  assert.equal(ableitungBeimStart(undefined, false), ABLEITUNG_STAND, "frisch eingerichtet: kein alter Bestand");
  assert.equal(ableitungBeimStart(undefined, true), 1, "bestehender Vault ohne Merker: der Stand von vorher");
  assert.equal(ableitungBeimStart(2, true), 2);
  assert.equal(angebotFaellig(1), ABLEITUNG_STAND > 1);
  assert.equal(angebotFaellig(ABLEITUNG_STAND), false, "gesehen heißt: nicht noch einmal anbieten");
  assert.equal(angebotFaellig(undefined), true);

  assert.equal(startKnopf({ ok: true, stufe: "" }, false), "Neuaufbau starten");
  assert.equal(startKnopf({ ok: true, stufe: "unterbrochen" }, false), "Fortsetzen");
  assert.equal(startKnopf({ ok: true, stufe: "baut" }, false), "Fortsetzen", "nach einem Neustart von Obsidian");
  assert.equal(startKnopf({ ok: true, stufe: "verglichen" }, false), "Neuaufbau starten", "ein fertiger wird nicht fortgesetzt");
  assert.equal(startKnopf({ ok: true, stufe: "baut" }, true), "Läuft …");
});

test("Stand von der Platte: die jüngste Kopie neben dem Vault, ohne die Engine zu fragen", () => {
  const eltern = mkdtempSync(join(tmpdir(), "sb-neuaufbau-"));
  const vault = join(eltern, "mein-vault");
  mkdirSync(vault);
  assert.deepEqual(neuaufbauStand(vault), { ok: true, kopie: false, stufe: "" }, "ohne Kopie: noch kein Neuaufbau");

  const kopie = (name: string, marke: string | null) => {
    const d = join(eltern, name, ".2ndbrain", "daten");
    mkdirSync(d, { recursive: true });
    if (marke !== null) writeFileSync(join(d, "neuaufbau.json"), marke, "utf8");
    return join(eltern, name);
  };
  kopie("mein-vault-neuaufbau-ohne-marke", null);
  kopie("anderer-vault-neuaufbau-2026-11-17", JSON.stringify({ stufe: "gebaut" }));
  const alt = kopie("mein-vault-neuaufbau-2026-11-17", JSON.stringify({ stufe: "verglichen", ziel: "/alt" }));
  utimesSync(join(alt, ".2ndbrain", "daten", "neuaufbau.json"), new Date(2026, 10, 17), new Date(2026, 10, 17));
  const neu = kopie("mein-vault-neuaufbau-2026-11-18", JSON.stringify({ stufe: "baut", nachbereitet: 5, gesamt: 23 }));
  assert.deepEqual(neuaufbauKopien(vault).map((p) => p.slice(eltern.length + 1)),
                   ["mein-vault-neuaufbau-2026-11-17", "mein-vault-neuaufbau-2026-11-18"],
                   "nur Kopien dieses Vaults mit Marke, die jüngste zuletzt");
  const s = neuaufbauStand(vault);
  assert.equal(s.stufe, "baut");
  assert.equal(s.nachbereitet, 5);
  assert.equal(s.ziel, neu, "ohne Ziel in der Marke gilt der Ordner");

  assert.equal(s.lebt, false);
  assert.equal(s.kopien, 2);

  // Rechnet in einer aelteren Kopie ein Prozess, zeigt das Fenster die - nicht die zuletzt angelegte
  writeFileSync(join(alt, ".2ndbrain", "daten", "neuaufbau.json"),
                JSON.stringify({ stufe: "baut", am: "2026-11-17T10:00:00", pid: process.pid }), "utf8");
  writeFileSync(join(neu, ".2ndbrain", "daten", "neuaufbau.json"),
                JSON.stringify({ stufe: "baut", am: "2026-11-18T10:00:00", pid: 0 }), "utf8");
  const laeuft = neuaufbauStand(vault);
  assert.equal(laeuft.ziel, alt, "die Kopie mit dem lebenden Prozess");
  assert.equal(laeuft.lebt, true);
  assert.equal(prozessLebt(process.pid), true);
  assert.equal(prozessLebt(0), false);
  assert.equal(prozessLebt(undefined), false);
  writeFileSync(join(alt, ".2ndbrain", "daten", "neuaufbau.json"), JSON.stringify({ stufe: "verglichen", am: "2026-11-17T10:00:00" }), "utf8");
  assert.equal(neuaufbauStand(vault).ziel, neu, "ohne lebenden Prozess: die zuletzt angelegte");

  writeFileSync(join(neu, ".2ndbrain", "daten", "neuaufbau.json"), "{kaputt", "utf8");
  writeFileSync(join(alt, ".2ndbrain", "daten", "neuaufbau.json"), "{kaputt", "utf8");
  assert.equal(neuaufbauStand(vault).ok, false, "unlesbare Marken sind ein Fehler, kein leerer Stand");
});

test("Umfang und Neu beginnen: eine Kopie ohne die alten Termin-Notizen wird erkannt", () => {
  const alt: NeuaufbauStand = { ok: true, stufe: "baut", nachbereitet: 1, gesamt: 41,
                                zurueckgesetzt: { termine: 41, mails_zurueck: 20 } };
  assert.equal(ohneAlteTermine(alt), true, "bis 0.13.2 angelegt: kein Zähler für alte Notizen");
  assert.equal(fortsetzbar(alt), true);
  const z = neuaufbauZeilen(alt);
  assert.ok(z.some((x) => x.text === "Umfang: 41 Termine mit Material, 20 Mails und Dokumente – die ältesten zuerst"));
  assert.ok(z.some((x) => x.fehler && x.text.includes("Neu beginnen")), "der Hinweis auf den Neustart");

  const neu: NeuaufbauStand = { ok: true, stufe: "baut", zurueckgesetzt: { termine: 23, alte_termine: 209, mails_zurueck: 20 } };
  assert.equal(ohneAlteTermine(neu), false);
  assert.ok(neuaufbauZeilen(neu).some((x) => x.text.startsWith("Umfang: 23 Termine mit Material, 209 alte Termin-Notizen, 20 Mails")));
  assert.equal(fortsetzbar({ ok: true, stufe: "verglichen" }), false, "ein fertiger Neuaufbau braucht keinen zweiten Knopf");
  assert.equal(ohneAlteTermine({ ok: true, stufe: "verglichen", zurueckgesetzt: { termine: 5 } }), false);
});

test("Start: Neu beginnen und das Datum, ab dem alte Notizen neu gerechnet werden", () => {
  assert.deepEqual(startArgs(false, ""), ["neuaufbau", "alles", "--json"]);
  assert.deepEqual(startArgs(true, "2026-06-01"), ["neuaufbau", "alles", "--json", "--neu", "--seit", "2026-06-01"]);
  assert.deepEqual(startArgs(false, " 2026-06-01 "), ["neuaufbau", "alles", "--json", "--seit", "2026-06-01"]);
  assert.deepEqual(startArgs(false, "01.06.2026"), ["neuaufbau", "alles", "--json"], "kein Datum: nichts begrenzen");
  assert.equal(gueltigesSeit("2026-02-30"), "", "ein Tag, den es nicht gibt");
  assert.equal(gueltigesSeit("2026-13-01"), "");
});

test("Kein Ergebnis von der Engine: die Meldung nennt den Grund und den Ausweg", () => {
  const gut = neuaufbauAuswerten({ code: 0, stderr: "[1/23] active-meetings/x.md", stdout: "Die Engine redet davor.\n{\"ok\": true, \"ziel\": \"/k\"}\n" });
  assert.equal(gut.ergebnis?.ziel, "/k", "das Ergebnis ist die letzte JSON-Zeile, auch wenn davor Text steht");

  const alt = neuaufbauAuswerten({ code: 1, stdout: "\n2ndBrain-Engine - Befehlszeile\n", stderr: "[FEHLER] Unbekannter Befehl: 'neuaufbau'" });
  assert.equal(alt.ergebnis, null);
  assert.match(alt.grund, /älter als das Plugin.*Engine → Aktualisieren/, "eine alte Engine kennt den Befehl nicht");

  assert.match(neuaufbauAuswerten({ code: 1, stdout: "", stderr: "No module named secondbrain" }).grund, /nicht installiert/);
  assert.match(neuaufbauAuswerten({ code: -1, stdout: "", stderr: "Kein Python ≥ 3.10 gefunden (PATH, Homebrew)" }).grund, /Python \(mindestens 3\.10\)/);
  assert.match(neuaufbauAuswerten({ code: 1, stdout: "", stderr: "PermissionError: [WinError 5] Zugriff verweigert: 'C:\\\\x'" }).grund,
               /kein Schreibrecht/);

  const fremd = neuaufbauAuswerten({ code: 3, stdout: "", stderr: "Zeile 1\nZeile 2\nValueError: etwas Unerwartetes" });
  assert.match(fremd.grund, /^Die Engine hat ohne Ergebnis aufgehört \(Code 3\)\.\nZeile 1\nZeile 2\nValueError: etwas Unerwartetes$/,
               "ohne bekannten Grund: ihre letzten Zeilen");
  assert.equal(neuaufbauAuswerten({ code: 0, stdout: "{\"version\": \"1\"}", stderr: "" }).ergebnis, null, "JSON ohne ok ist kein Ergebnis");

  assert.equal(neuaufbauMeldung({ ok: false, ziel: "/k", grund: "PermissionError: gesperrt" }),
               "Neuaufbau abgebrochen: PermissionError: gesperrt – Kopie: /k");
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
