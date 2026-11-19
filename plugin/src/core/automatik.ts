// Der letzte Lauf der Automatik (`2ndbrain auto --json`, gespeichert in .2ndbrain/daten/auto_letzter_lauf.json):
// welche Schritte gescheitert sind, mit ganzer Meldung, der Stelle im Code und - fuer bekannte Faelle - dem
// Ausweg. Reine Textfunktionen; das Fenster dazu ist views/automatik.ts.

/** Die Datei der Engine (engine/secondbrain/auto.py: letzten_lauf_merken) - nur volle Laeufe. */
export const LETZTER_LAUF = ".2ndbrain/daten/auto_letzter_lauf.json";

export interface AutoSchritt {
  step: string;
  ok: boolean;
  skipped?: boolean;
  detail?: string;
  changed?: number;
  seconds?: number;
  /** nur bei einem unerwarteten Fehler: die Stelle im Code (Ende des Tracebacks) */
  traceback?: string;
}

/** Warum das Modell fehlt - von der Engine eingeordnet (modell.py: fehler_einordnen). */
export interface ModellFehler { art: string; ursache: string; ausweg: string; erlaubt?: string[]; meldung?: string }

/** `am` steht nur in der Datei (Ortszeit ohne Zone, "2026-10-05T10:30:00"). `llm_fehler`: das Modell fehlte in
 *  diesem Lauf; `llm_ersatz`: ein anderes Modell der Liste ist eingesprungen. */
export interface AutoErgebnis {
  ok: boolean; llm?: boolean; seconds?: number; skipped?: string; steps: AutoSchritt[]; am?: string;
  llm_fehler?: ModellFehler; llm_ersatz?: { model: string; ersatz_fuer: string };
}

/** Ein Schritt von `2ndbrain modell --diagnose --json`; `ok: null` = nicht geprueft (ein Schritt davor scheiterte). */
export interface DiagnoseSchritt { schritt: string; titel: string; ok: boolean | null; detail: string; ausweg: string }

/** Die Diagnose als Zeilen: „✓ Server antwortet: 65 ms“, „✗ …“ mit Ausweg, „– …“ fuer Ungeprueftes. */
export function diagnoseZeilen(schritte: DiagnoseSchritt[]): { marke: string; text: string; ausweg: string; ok: boolean | null }[] {
  return schritte.map((s) => ({
    marke: s.ok ? "✓" : s.ok === null ? "–" : "✗",
    text: s.titel + (s.detail ? `: ${s.detail}` : ""),
    ausweg: s.ausweg || "",
    ok: s.ok,
  }));
}

const MODELL_TITEL: Record<string, string> = {
  kein_server: "Kein Modell-Server eingetragen", offline: "Das Modell ist abgeschaltet",
  nicht_erreichbar: "Modell-Server nicht erreichbar", gesperrt: "Das Modell ist gerade gesperrt",
  unbekannt_modell: "Der Server kennt das Modell nicht", abbruch: "Verbindung zum Modell abgebrochen",
  zeitlimit: "Das Modell hat nicht rechtzeitig geantwortet", http: "Der Modell-Server hat abgelehnt",
};

/** Schritte, die ohne Modell nur einen Teil leisten - sie laufen trotzdem und holen nach, sobald es wieder da ist. */
const BRAUCHT_MODELL = ["nachbereiten", "einarbeiten", "stand", "wissen", "fokus", "verdichten"];

export interface ModellMeldung { titel: string; ursache: string; betrifft: string; ausweg: string; meldung: string }

/** Die Stoerung des Modells als Meldung, mit der man etwas anfangen kann: was los ist, was es betrifft, was zu
 *  tun ist - null, wenn das Modell da war. Ein eingesprungenes Ersatzmodell ist keine Stoerung, aber ein Hinweis. */
export function modellMeldung(r: AutoErgebnis | null): ModellMeldung | null {
  if (!r) return null;
  if (r.llm_fehler) {
    const f = r.llm_fehler;
    const betroffen = r.steps.filter((s) => BRAUCHT_MODELL.includes(s.step) && !s.skipped).map((s) => schrittName(s.step));
    return {
      titel: MODELL_TITEL[f.art] ?? "Das Modell war nicht verfügbar",
      ursache: f.ursache,
      betrifft: betroffen.length
        ? `${betroffen.join(", ")} liefen ohne Modell (nur Fakten, Notbehelf). Der nächste Lauf mit Modell holt es nach.`
        : "In diesem Lauf brauchte kein Schritt das Modell.",
      ausweg: f.ausweg,
      meldung: f.meldung ?? "",
    };
  }
  if (r.llm_ersatz) {
    return {
      titel: `Ersatzmodell ${r.llm_ersatz.model}`,
      ursache: `Der Server hat ${r.llm_ersatz.ersatz_fuer} abgelehnt; das nächste Modell der Liste ist eingesprungen.`,
      betrifft: "Was dieser Lauf mit dem Modell geschrieben hat, stammt vom Ersatzmodell.",
      ausweg: "Der nächste Lauf versucht es zuerst wieder mit dem besten Modell der Liste.",
      meldung: "",
    };
  }
  return null;
}

/** Was das Plugin vom letzten Lauf weiss: das Ergebnis - oder, ohne Ergebnis, die letzten Zeilen der Engine. */
export interface LetzterLauf { at: Date; result: AutoErgebnis | null; ausgabe?: string }

/** So heissen die Schritte in der Oberflaeche. */
export const SCHRITT_NAMEN: Record<string, string> = {
  kalender: "Kalender", mails: "Eingang (Mails, Dateien)", nachziehen: "Nachziehen", protokolle: "Protokolle",
  einarbeiten: "Einarbeiten", wissen: "Wissen (Begriffe, Glossar)", vorbereiten: "Vorbereiten",
  nachbereiten: "Nachbereiten", themenlog: "Themen-Log", rueckfragen: "Rückfragen", schreibweisen: "Schreibweisen",
  altbestand: "Altbestand", archivieren: "Archivieren",
  pruefen: "Offene Punkte prüfen", verdichten: "Verdichten", stand: "Stand der Themen",
  fokus: "Fokus-Spiegel", systemuebersicht: "Systemübersicht", personen: "Personen",
};

export const schrittName = (step: string): string => SCHRITT_NAMEN[step] ?? step;

export function gescheitert(r: AutoErgebnis | null): AutoSchritt[] {
  return (r?.steps ?? []).filter((s) => !s.ok);
}

/** Scheitert seit dem vorigen Lauf etwas Neues (oder fehlt jetzt das Ergebnis)? Nur dann meldet sich ein Lauf im
 *  Hintergrund - sonst stuende alle 20 Minuten dieselbe Meldung da; „mit Fehlern“ in Heute bleibt ohnehin. */
export function neueFehler(vorher: LetzterLauf | null, jetzt: AutoErgebnis | null): boolean {
  if (!jetzt) return !vorher || vorher.result !== null;
  const alt = new Set(gescheitert(vorher?.result ?? null).map((s) => s.step));
  return gescheitert(jetzt).some((s) => !alt.has(s.step));
}

function istErgebnis(j: unknown): j is AutoErgebnis {
  return !!j && typeof j === "object" && Array.isArray((j as AutoErgebnis).steps);
}

function letzteZeilen(text: string, n: number): string[] {
  return text.split(/\r?\n/).map((z) => z.trimEnd()).filter((z) => z.trim()).slice(-n);
}

/** Ein Lauf von `2ndbrain auto --json`: das Ergebnis - oder, wenn die Engine keins liefert (Absturz beim Start,
 *  fehlendes Paket, Zeitlimit), was sie zuletzt gesagt hat. */
export function auswerten(r: { code: number; stdout: string; stderr: string; seconds: number }):
    { result: AutoErgebnis | null; ausgabe: string } {
  try {
    const j: unknown = JSON.parse(r.stdout);
    if (istErgebnis(j)) return { result: j, ausgabe: "" };
  } catch {
    // kein JSON - unten die Ausgabe
  }
  const kopf = `Engine beendet mit Code ${r.code} nach ${Math.round(r.seconds)} s.`;
  return { result: null, ausgabe: [kopf, ...letzteZeilen(r.stderr, 40), ...letzteZeilen(r.stdout, 10)].join("\n") };
}

/** Die Datei der Engine lesen; null, wenn sie fehlt oder kaputt ist. */
export function letzterLauf(text: string | null): AutoErgebnis | null {
  if (!text) return null;
  try {
    const j: unknown = JSON.parse(text);
    return istErgebnis(j) ? j : null;
  } catch {
    return null;
  }
}

/** Die Kalender-Adresse ist ein Zugangsschluessel: in keinem Bericht, auch nicht als https-Fassung von webcal. */
export function ohneGeheimnis(text: string, geheim: string): string {
  const g = geheim.trim();
  if (!g) return text;
  const fassungen = [g, g.replace(/^webcal:\/\//i, "https://")].filter((x) => x.length > 8);
  return fassungen.reduce((t, x) => t.split(x).join("<Kalender-Adresse>"), text);
}

interface Regel { schritt?: string; muster: RegExp; text: string }

// Bekannte Faelle, der erste Treffer gilt. `schritt`: nur fuer diesen Schritt.
const REGELN: Regel[] = [
  { muster: /keine Kalender-Adresse/i,
    text: "Auf diesem Gerät ist keine Kalender-Adresse eingetragen: Einstellungen → 2ndBrain → Kalender. Sie liegt im "
      + "Obsidian-Schlüsselbund und gilt je Gerät – auf jedem Rechner einmal eintragen." },
  { schritt: "kalender", muster: /HTTP Error (401|403|404|410)/,
    text: "Der Kalender lehnt die Adresse ab (zurückgezogen oder neu veröffentlicht?): die aktuelle iCal-Adresse unter "
      + "Einstellungen → 2ndBrain → Kalender eintragen." },
  { schritt: "kalender", muster: /FileNotFoundError|No such file or directory/,
    text: "Die Kalender-Datei (.ics) gibt es auf diesem Rechner nicht: Einstellungen → 2ndBrain → Kalender prüfen "
      + "(gilt je Gerät)." },
  { schritt: "kalender", muster: /URLError|getaddrinfo|timed out|nodename nor servname|Name or service not known|unreachable|SSL/i,
    text: "Der Kalender ist gerade nicht erreichbar (Netz, unterwegs VPN?). Der nächste Lauf versucht es wieder." },
  { schritt: "systemuebersicht", muster: /gehört zum Vault/,
    text: "Der Ordner fürs Modell der Systemübersicht ist für einen anderen Vault angelegt (Name in der Meldung) und "
      + "bleibt deshalb unberührt: Einstellungen → 2ndBrain → Systemübersicht (LikeC4) → Modell-Ordner – einen eigenen "
      + "Ordner für diesen Vault eintragen." },
  { muster: /ModuleNotFoundError|No module named|ImportError/,
    text: "Der Engine fehlt ein Paket, oder sie passt nicht zum Plugin: Einstellungen → 2ndBrain → Engine → "
      + "Installieren bzw. Aktualisieren." },
  { muster: /Kein Python/,
    text: "Kein passendes Python gefunden: Einstellungen → 2ndBrain → Python (mindestens 3.10)." },
  { muster: /LLMUnavailableError|ConnectionRefusedError|Connection refused|RemoteDisconnected/,
    text: "Der Modell-Server hat mitten im Lauf nicht geantwortet: Einstellungen → 2ndBrain → Vault-Konfiguration → "
      + "Modell-Server prüfen (unterwegs über VPN). Der nächste Lauf versucht es wieder." },
  { muster: /FileNotFoundError|No such file or directory|cannot find the path|Pfad nicht finden/i,
    text: "Eine Datei oder ein Ordner fehlt. Stammt der Pfad von einem anderen Rechner, steht er meist in "
      + ".2ndbrain/local.config.json unter „paths“ – dort prüfen oder leeren (leer = 2ndBrain sucht selbst)." },
];

/** Der Ausweg fuer bekannte Faelle - null, wenn keiner bekannt ist. Ohne Schritt: die Ausgabe einer Engine ohne
 *  Ergebnis. */
export function hinweis(s: AutoSchritt | null, ausgabe = ""): string | null {
  const t = `${s?.detail ?? ""}\n${s?.traceback ?? ""}\n${ausgabe}`;
  const r = REGELN.find((x) => (!x.schritt || x.schritt === s?.step) && x.muster.test(t));
  return r ? r.text : null;
}

const zwei = (n: number) => String(n).padStart(2, "0");

/** „05.10. 10:30“ */
export function datumZeit(am: Date): string {
  return `${zwei(am.getDate())}.${zwei(am.getMonth() + 1)}. ${zwei(am.getHours())}:${zwei(am.getMinutes())}`;
}

/** Heute nur die Uhrzeit, sonst mit Datum. */
export function zeitText(am: Date, jetzt = new Date()): string {
  return am.toDateString() === jetzt.toDateString() ? datumZeit(am).slice(-5) : datumZeit(am);
}

/** Der Lauf als Text zum Kopieren und Schicken: gescheiterte Schritte mit Meldung, Ausweg und Stelle im Code
 *  zuerst, dann die uebrigen. `umgebung`: Plugin-Version, System, Python - wo der Lauf war. */
export function bericht(last: LetzterLauf, umgebung = ""): string {
  const r = last.result;
  const kopf = `2ndBrain – Automatik, letzter Lauf ${datumZeit(last.at)}`
    + (r ? ` (${r.seconds ?? "?"} s, Modell ${r.llm ? "bereit" : "aus"})` : "") + (umgebung ? `\n${umgebung}` : "");
  if (!r) {
    const h = hinweis(null, last.ausgabe ?? "");
    return [kopf, "", "Die Engine hat kein Ergebnis geliefert. Ihre letzten Zeilen:", (last.ausgabe ?? "").trim() || "(keine)",
            ...(h ? ["", `Ausweg: ${h}`] : [])].join("\n");
  }
  const zeilen = [kopf, ""];
  const m = modellMeldung(r);
  if (m) {
    zeilen.push(`MODELL ${m.titel}:`, `  Ursache: ${m.ursache}`, `  Betrifft: ${m.betrifft}`, `  Ausweg: ${m.ausweg}`,
                ...(m.meldung ? [`  Meldung: ${m.meldung}`] : []), "");
  }
  for (const s of gescheitert(r)) {
    zeilen.push(`FEHLER ${schrittName(s.step)} (${s.step}):`, ...(s.detail ?? "(keine Meldung)").split("\n").map((z) => `  ${z}`));
    const h = hinweis(s);
    if (h) zeilen.push(`  Ausweg: ${h}`);
    if (s.traceback) zeilen.push("  Stelle im Code:", ...s.traceback.trim().split("\n").map((z) => `    ${z}`));
    zeilen.push("");
  }
  for (const s of r.steps.filter((x) => x.ok)) {
    zeilen.push(`${s.skipped ? "–" : "ok"} ${schrittName(s.step)}: ${s.detail ?? ""}${s.seconds ? ` (${s.seconds} s)` : ""}`);
  }
  return zeilen.join("\n").trim();
}
