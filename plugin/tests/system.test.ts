import assert from "node:assert/strict";
import { test } from "node:test";
import { Likec4Server, busyPort, findUrl, isBatch, lastLines, parseLsof, parseNetstat, quoteWin, startArgs }
  from "../src/desktop/likec4";
import { Probe, findPython, parseProbe, pythonCandidates, versionOk } from "../src/desktop/python";

test("Python-Kandidaten: eingetragen zuerst, dann py/python/python3 (Windows), ohne Doppelte", () => {
  assert.deepEqual(pythonCandidates("", "win32"), ["py", "python", "python3"]);
  assert.deepEqual(pythonCandidates("  C:\\Py\\python.exe ", "win32"), ["C:\\Py\\python.exe", "py", "python", "python3"]);
  assert.deepEqual(pythonCandidates("python3", "linux"), ["python3", "python"]);
});

test("Python-Antwort: Version und Pfad; der Store-Platzhalter nennt keine Version", () => {
  assert.deepEqual(parseProbe("3 14 C:\\Py\\python.exe\r\n"), { major: 3, minor: 14, executable: "C:\\Py\\python.exe" });
  assert.equal(parseProbe("Python was not found; run without arguments to install from the Microsoft Store"), null);
  assert.equal(versionOk(3, 9), false);
  assert.equal(versionOk(3, 10), true);
  assert.equal(versionOk(4, 0), true);
});

test("Python-Suche: kaputter Eintrag, Store-Platzhalter, zu alt - das erste brauchbare gewinnt", async () => {
  const answers: Record<string, { code: number; stdout: string }> = {
    "C:\\alt\\python.exe": { code: -1, stdout: "" },       // gibt es nicht mehr
    py: { code: 0, stdout: "3 8 C:\\Py38\\python.exe" },   // zu alt
    python: { code: -1, stdout: "" },                       // Microsoft-Store-Platzhalter (9009)
    python3: { code: 0, stdout: "3 12 C:\\Py312\\python.exe" },
  };
  const asked: string[] = [];
  const probe: Probe = async (c) => {
    asked.push(c);
    return answers[c];
  };
  const info = await findPython("C:\\alt\\python.exe", "win32", probe);
  assert.deepEqual(info, { command: "python3", executable: "C:\\Py312\\python.exe", version: "3.12" });
  assert.deepEqual(asked, ["C:\\alt\\python.exe", "py", "python", "python3"]);
  const none = await findPython("", "win32", async () => { throw new Error("ENOENT"); });
  assert.equal(none, null);
});

test("LikeC4: Batch-Starter nur unter Windows über die Shell, Pfade mit Leerzeichen gequotet", () => {
  assert.equal(isBatch("C:\\Program Files\\nodejs\\npx.CMD", "win32"), true);
  assert.equal(isBatch("C:\\x\\likec4.cmd", "linux"), false);
  assert.equal(isBatch("/usr/local/bin/likec4", "darwin"), false);
  assert.equal(quoteWin("C:\\Program Files\\nodejs\\npx.cmd"), "\"C:\\Program Files\\nodejs\\npx.cmd\"");
  assert.equal(quoteWin("--port"), "--port");
  assert.deepEqual(startArgs("C:\\m", 5188), ["start", "C:\\m", "--port", "5188", "--listen", "127.0.0.1"]);
});

test("LikeC4: Adresse aus der Startausgabe (mit Rahmen und Farben), nicht die HMR-Zeile", () => {
  const out = "Enabling HMR: localhost:24678 (auto-discovered)\n   │   LikeC4 served at:   │\n"
    + "   │   Local:   \u001b[36mhttp://127.0.0.1:5190/\u001b[39m   │\n";
  assert.equal(findUrl(out), "http://127.0.0.1:5190/");
  assert.equal(findUrl("Enabling HMR: localhost:24678 (auto-discovered)"), null);
  assert.equal(lastLines("a\n   ┌──┐\n  b  \n│ c │\n"), "a · b · c");
});

test("LikeC4: Prozess am Port aus netstat (deutsch/englisch) und lsof; nur LikeC4 wird beendet", () => {
  const de = "\n  Proto  Lokale Adresse         Remoteadresse          Status           PID\n"
    + "  TCP    127.0.0.1:5188         0.0.0.0:0              ABHÖREN          19160\n"
    + "  TCP    127.0.0.1:5188         127.0.0.1:56152        HERGESTELLT      19160\n"
    + "  TCP    127.0.0.1:51880        0.0.0.0:0              ABHÖREN          7\n";
  assert.equal(parseNetstat(de, 5188), 19160);
  assert.equal(parseNetstat(de.replace("ABHÖREN ", "LISTENING"), 5188), 19160);
  assert.equal(parseNetstat(de, 5190), null);
  assert.equal(parseNetstat("  TCP    [::]:5188    [::]:0    LISTENING    42\n", 5188), 42);
  assert.equal(parseLsof("19160\n"), 19160);
  assert.equal(parseLsof(""), null);
  assert.equal(busyPort(null), "frei");
  assert.equal(busyPort({ pid: 1, command: "node likec4.mjs start C:\\m --port 5188" }), "beenden");
  assert.equal(busyPort({ pid: 1, command: "C:\\Programme\\andere.exe" }), "fremd");
});

test("LikeC4: haengender Explorer am Port wird beendet; ein fremdes Programm nie", async () => {
  const killed: number[] = [];
  let owner: { pid: number; command: string } | null = { pid: 19160, command: "node likec4.mjs start C:\\m" };
  const tools = {
    owner: async () => owner,
    kill: async (pid: number) => { killed.push(pid); owner = null; },
  };
  // Befehl ohne Programm -> nach dem Beenden scheitert der Start sofort; es geht nur um das Beenden
  const server = new Likec4Server("linux", async () => false, tools);
  await server.start({ likec4_model: "/m", likec4_befehl: ["/gibt/es/nicht/likec4"] }, 5188);
  assert.deepEqual(killed, [19160]);
  owner = { pid: 7, command: "/usr/bin/anderer-dienst" };
  const fremd = new Likec4Server("linux", async () => false, tools);
  assert.equal(await fremd.start({ likec4_model: "/m", likec4_befehl: ["/x/likec4"] }, 5188), null);
  assert.deepEqual(killed, [19160], "fremdes Programm beendet");
  assert.match(fremd.detail, /anderen Programm belegt/);
});

