// Der letzte Lauf der Automatik (core/automatik.ts): Ergebnis oder Ausgabe der Engine, Hinweise fuer bekannte
// Faelle, der Bericht zum Weitergeben - ohne Kalender-Adresse. Adressen und Pfade erfunden (example.org).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  AutoErgebnis, LetzterLauf, auswerten, bericht, datumZeit, gescheitert, hinweis, letzterLauf, neueFehler,
  ohneGeheimnis, schrittName, zeitText,
} from "../src/core/automatik";

const KALENDER_FEHLT = "ERROR: keine Kalender-Adresse (calendar.config.json fehlt, VAULT_CALENDAR_URL leer).\n"
  + "Eintragen im 2ndBrain-Plugin (Einstellungen -> Kalender, Obsidian-Schluesselbund) oder mit";

const LAUF: AutoErgebnis = {
  ok: false, llm: true, seconds: 42.5,
  steps: [
    { step: "kalender", ok: false, detail: KALENDER_FEHLT, seconds: 0.4 },
    { step: "mails", ok: true, detail: "2 Mails eingelesen", changed: 2, seconds: 1.2 },
    { step: "wissen", ok: true, skipped: true, detail: "Intervall" },
    { step: "personen", ok: false, detail: "ZeroDivisionError: division by zero", seconds: 0.1,
      traceback: "Traceback (most recent call last):\n  File \"auto.py\", line 448, in run\nZeroDivisionError: division by zero" },
  ],
};

test("Auswerten: JSON der Engine ist das Ergebnis, sonst ihre letzten Zeilen mit Code und Dauer", () => {
  const gut = auswerten({ code: 2, stdout: JSON.stringify(LAUF), stderr: "Fortschritt …", seconds: 42.5 });
  assert.equal(gut.result?.steps.length, 4, "Code 2 (mit Fehlern) liefert trotzdem das Ergebnis");
  assert.equal(gut.ausgabe, "");

  const stderr = ["Traceback (most recent call last):", "  File \"x.py\", line 3, in <module>", "",
                  "ModuleNotFoundError: No module named 'secondbrain'"].join("\n");
  const kaputt = auswerten({ code: 1, stdout: "", stderr, seconds: 0.8 });
  assert.equal(kaputt.result, null);
  assert.match(kaputt.ausgabe, /^Engine beendet mit Code 1 nach 1 s\./);
  assert.match(kaputt.ausgabe, /ModuleNotFoundError: No module named 'secondbrain'$/);
  assert.ok(!kaputt.ausgabe.includes("\n\n"), "leere Zeilen fallen weg");

  const lang = auswerten({ code: -1, stdout: "{halb", stderr: Array.from({ length: 100 }, (_, i) => `Zeile ${i}`).join("\n"), seconds: 900 });
  assert.equal(lang.result, null, "halbes JSON ist kein Ergebnis");
  assert.ok(lang.ausgabe.includes("Zeile 99") && !lang.ausgabe.includes("Zeile 59\n"), "nur die letzten 40 Zeilen");
  assert.equal(auswerten({ code: 0, stdout: "{\"ok\": true}", stderr: "", seconds: 1 }).result, null, "ohne Schritte kein Ergebnis");
});

test("Datei der Engine: gültig, kaputt, fehlt", () => {
  const r = letzterLauf(JSON.stringify({ am: "2026-10-05T10:30:00", ...LAUF }));
  assert.equal(r?.am, "2026-10-05T10:30:00");
  assert.deepEqual(gescheitert(r).map((s) => s.step), ["kalender", "personen"]);
  assert.equal(letzterLauf("{kaputt"), null);
  assert.equal(letzterLauf(JSON.stringify({ ok: true })), null);
  assert.equal(letzterLauf(null), null);
});

test("Hinweise: bekannte Fälle mit Ausweg, der erste Treffer gilt, Unbekanntes ohne", () => {
  const h = (step: string, detail: string, traceback?: string) => hinweis({ step, ok: false, detail, traceback });
  assert.match(h("kalender", KALENDER_FEHLT) ?? "", /Einstellungen → 2ndBrain → Kalender.*je Gerät/s);
  assert.match(h("kalender", "ERROR fetching calendar: HTTPError: HTTP Error 404: Not Found") ?? "", /lehnt die Adresse ab/);
  assert.match(h("kalender", "ERROR fetching calendar: URLError: <urlopen error [Errno 8] nodename nor servname provided>") ?? "",
               /nicht erreichbar/);
  assert.match(h("kalender", "ERROR fetching calendar: FileNotFoundError: [Errno 2] No such file or directory: '/x/k.ics'") ?? "",
               /Kalender-Datei/, "beim Kalender ist es die .ics-Datei, nicht local.config.json");
  assert.match(h("systemuebersicht", "FEHLER: /x/likec4-model gehört zum Vault „anderer“ – nicht überschrieben") ?? "",
               /Modell-Ordner/);
  assert.match(h("wissen", "FileNotFoundError: [Errno 2] No such file or directory: 'C:/Users/nutzer/atlas'") ?? "",
               /local\.config\.json unter „paths“/);
  assert.match(h("einarbeiten", "LLMUnavailableError: URLError: timed out") ?? "", /Modell-Server/);
  assert.match(h("stand", "KeyError: 'x'", "Traceback …\nModuleNotFoundError: No module named 'yaml'") ?? "",
               /Engine → Installieren bzw\. Aktualisieren/, "auch aus der Stelle im Code");
  assert.equal(h("personen", "ZeroDivisionError: division by zero"), null);
  assert.equal(h("systemuebersicht", "gehört zum Vault"), hinweis({ step: "systemuebersicht", ok: false, detail: "gehört zum Vault" }));
  assert.match(hinweis(null, "Kein Python ≥ 3.10 gefunden (PATH, Homebrew, python.org, pyenv)") ?? "", /Python \(mindestens 3\.10\)/,
               "ohne Ergebnis: aus der Ausgabe");
});

test("Neue Fehler: Hintergrund meldet sich nur, wenn etwas neu scheitert oder das Ergebnis neu fehlt", () => {
  const am = new Date(2026, 9, 5, 10, 0);
  const mit = (...steps: string[]): AutoErgebnis => ({ ok: !steps.length, steps: steps.map((step) => ({ step, ok: false })) });
  const lauf = (result: AutoErgebnis | null): LetzterLauf => ({ at: am, result });
  assert.equal(neueFehler(null, mit("kalender")), true, "erster Lauf mit Fehler");
  assert.equal(neueFehler(lauf(mit("kalender")), mit("kalender")), false, "derselbe Fehler wie vorher");
  assert.equal(neueFehler(lauf(mit("kalender")), mit("kalender", "stand")), true, "dazu ein neuer");
  assert.equal(neueFehler(lauf(mit("kalender")), mit()), false, "alles gut");
  assert.equal(neueFehler(lauf(mit()), null), true, "Engine liefert neu kein Ergebnis");
  assert.equal(neueFehler(lauf(null), null), false, "weiter kein Ergebnis");
  assert.equal(neueFehler(lauf(null), mit("kalender")), true, "wieder ein Ergebnis, mit Fehler");
});

test("Kalender-Adresse: in keinem Bericht – auch nicht die https-Fassung von webcal", () => {
  const geheim = "webcal://kalender.example.org/geheim/abc123.ics";
  const text = `ERROR fetching calendar: ${geheim} und https://kalender.example.org/geheim/abc123.ics`;
  const sauber = ohneGeheimnis(text, geheim);
  assert.ok(!sauber.includes("abc123"), sauber);
  assert.equal(sauber, "ERROR fetching calendar: <Kalender-Adresse> und <Kalender-Adresse>");
  assert.equal(ohneGeheimnis(text, ""), text, "keine Adresse eingetragen");
  assert.equal(ohneGeheimnis("a b", " "), "a b");
});

test("Bericht: gescheiterte Schritte mit ganzer Meldung, Ausweg und Stelle im Code zuerst, dann die übrigen", () => {
  const am = new Date(2026, 9, 5, 9, 5);
  const text = bericht({ at: am, result: LAUF }, "Plugin 0.12.1 · macOS");
  const zeilen = text.split("\n");
  assert.equal(zeilen[0], "2ndBrain – Automatik, letzter Lauf 05.10. 09:05 (42.5 s, Modell bereit)");
  assert.equal(zeilen[1], "Plugin 0.12.1 · macOS");
  assert.ok(text.indexOf("FEHLER Kalender") < text.indexOf("FEHLER Personen"), "Reihenfolge des Laufs");
  assert.ok(text.indexOf("FEHLER Personen") < text.indexOf("ok Eingang"), "Fehler vor den übrigen");
  assert.ok(text.includes("  Eintragen im 2ndBrain-Plugin"), "die ganze Meldung, nicht nur die letzte Zeile");
  assert.ok(text.includes("  Ausweg: Auf diesem Gerät ist keine Kalender-Adresse eingetragen"));
  assert.ok(text.includes("  Stelle im Code:\n    Traceback (most recent call last):"));
  assert.ok(text.includes("ok Eingang (Mails, Dateien): 2 Mails eingelesen (1.2 s)"));
  assert.ok(text.includes("– Wissen (Begriffe, Glossar): Intervall"));

  const ohne = bericht({ at: am, result: null, ausgabe: "Engine beendet mit Code 1 nach 1 s.\nModuleNotFoundError: No module named 'pypdf'" });
  assert.match(ohne, /kein Ergebnis geliefert/);
  assert.match(ohne, /No module named 'pypdf'/);
  assert.match(ohne, /Ausweg: Der Engine fehlt ein Paket/);
});

test("Zeit: heute nur die Uhrzeit, sonst mit Datum; Schrittnamen", () => {
  const jetzt = new Date(2026, 9, 5, 18, 0);
  assert.equal(zeitText(new Date(2026, 9, 5, 7, 3), jetzt), "07:03");
  assert.equal(zeitText(new Date(2026, 9, 4, 23, 59), jetzt), "04.10. 23:59");
  assert.equal(datumZeit(new Date(2026, 0, 2, 3, 4)), "02.01. 03:04");
  assert.equal(schrittName("systemuebersicht"), "Systemübersicht");
  assert.equal(schrittName("neu"), "neu", "unbekannter Schritt: sein Name");
});

test("Modell fehlt: Ursache, was es betrifft und Ausweg stehen in Meldung und Bericht", async () => {
  const { modellMeldung, diagnoseZeilen } = await import("../src/core/automatik");
  const ohne: AutoErgebnis = {
    ok: true, llm: false, seconds: 12,
    llm_fehler: { art: "gesperrt", ursache: "Der Server laesst das Modell gerade nicht zu. Erlaubt ist gerade: klein-b.",
                  ausweg: "Am Server das Modell wieder freigeben oder warten.", erlaubt: ["klein-b"],
                  meldung: "OSError: HTTP 409: Modell gross-a ist im Modus x nicht erlaubt." },
    steps: [
      { step: "nachbereiten", ok: true, detail: "1 Termin (Notbehelf)" },
      { step: "stand", ok: true, detail: "0 Stand-Text(e) neu (ohne Modell: nur Fakten)" },
      { step: "wissen", ok: true, skipped: true, detail: "Intervall" },
      { step: "kalender", ok: true, detail: "3 Termine" },
    ],
  };
  const m = modellMeldung(ohne);
  assert.equal(m?.titel, "Das Modell ist gerade gesperrt");
  assert.match(m?.betrifft ?? "", /^Nachbereiten, Stand der Themen liefen ohne Modell/, "nur gelaufene Schritte, die das Modell brauchen");
  const text = bericht({ at: new Date(2026, 10, 17, 9, 0), result: ohne });
  assert.match(text, /MODELL Das Modell ist gerade gesperrt:\n {2}Ursache: .*klein-b/);
  assert.match(text, /Ausweg: Am Server/);

  assert.equal(modellMeldung(LAUF), null, "mit Modell keine Meldung");
  const ersatz = modellMeldung({ ...LAUF, llm_ersatz: { model: "mittel-b", ersatz_fuer: "gross-a" } });
  assert.equal(ersatz?.titel, "Ersatzmodell mittel-b");

  const z = diagnoseZeilen([
    { schritt: "adresse", titel: "Adresse eingetragen", ok: true, detail: "http://modell.example.org", ausweg: "" },
    { schritt: "server", titel: "Server antwortet", ok: false, detail: "Der Modell-Server antwortet nicht.", ausweg: "Netz pruefen." },
    { schritt: "modell", titel: "Modell vorhanden", ok: null, detail: "", ausweg: "" },
  ]);
  assert.deepEqual(z.map((x) => x.marke), ["✓", "✗", "–"]);
  assert.equal(z[1].ausweg, "Netz pruefen.");
});
