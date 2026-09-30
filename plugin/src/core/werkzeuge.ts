// Werkzeuge des Chats - search, read, path, neighbors -, nur lesend, ueber den Wissensgraphen
// (core/graph.ts): Notizen, Domain Atlas, Systemuebersicht. Das Modell ruft sie in einer Schleife auf
// (core/chat.ts); jedes liefert Text fuers Modell - Notizen als [[Links]], damit die Antwort sie so
// zitiert und der Link-Check sie kennt - und was gelesen wurde.

import { ABFRAGE_WERKZEUGE, AbfrageKontext, abfrage, atlasAbfrage, aufgaben, log, termine } from "./abfragen";
import { norm } from "./atlas";
import { localIsoDate } from "./datum";
import { Graph, Knoten, artFilter } from "./graph";
import { str, strip, universalNewlines } from "./pytext";
import type { WerkzeugSpec } from "./modell";
import { VaultSource } from "./quelle";

/** So viel Text liefert ein Werkzeug hoechstens (Zeichen). */
export const ERGEBNIS_ZEICHEN = 6000;

export interface WerkzeugErgebnis {
  text: string;
  /** Notizen und Atlas-Eintraege, die gelesen wurden (fuer „Gelesen:“ unter der Antwort) */
  gelesen: Knoten[];
  /** Was geschah, fuer die Wartezeile und unter der Antwort: „liest Kundenportal“ */
  schritt: string;
}

const ARTEN = ["Person", "Thema", "Termin", "Mail", "System", "Team", "Firma", "Begriff", "Reihe", "Quelle", "Eingang",
               "Subdomäne", "Kontext", "Nachricht", "Fachobjekt", "Ablauf", "Externer", "Beziehung", "Atlas-Team"];

export const WERKZEUGE: WerkzeugSpec[] = [
  { name: "search",
    beschreibung: "Sucht im ganzen Wissen: Notizen (Themen, Personen, Termine, Systeme, Teams, Begriffe, Mails und "
      + "Dokumente), Domain Atlas (Subdomänen, Kontexte, Nachrichten, Fachobjekte, Abläufe) und Systemübersicht – "
      + "nach Namen, Aliassen, Atlas-IDs und im Volltext. Liefert Treffer mit Art und Fundstelle.",
    parameter: { type: "object", properties: {
      query: { type: "string", description: "Begriffe, ein Name oder eine Atlas-ID" },
      art: { type: "string", enum: ARTEN, description: "optional: nur Treffer dieser Art" } }, required: ["query"] } },
  { name: "read",
    beschreibung: "Liest eine Notiz, einen Atlas-Eintrag (mit Beschreibung und Bezügen) oder ein System (mit seinen "
      + "Verbindungen). Lange Notizen kommen gekürzt mit ihrer Gliederung – dann einen Abschnitt gezielt lesen.",
    parameter: { type: "object", properties: {
      ziel: { type: "string", description: "Name, Pfad, [[Link]] oder Atlas-ID" },
      abschnitt: { type: "string", description: "optional: Überschrift eines Abschnitts der Notiz" } }, required: ["ziel"] } },
  { name: "path",
    beschreibung: "Findet Wege zwischen zwei Punkten im Wissensgraphen – bis zu drei, über verschiedene "
      + "Zwischenstationen. Die Knoten dazwischen sind das, was A und B verbindet.",
    parameter: { type: "object", properties: {
      von: { type: "string", description: "Name, [[Link]] oder Atlas-ID" },
      nach: { type: "string", description: "Name, [[Link]] oder Atlas-ID" } }, required: ["von", "nach"] } },
  { name: "neighbors",
    beschreibung: "Umkreis eines Punkts (Blast Radius): was bis zu drei Schritte entfernt damit verbunden ist, nach "
      + "Nähe sortiert, mit den Knoten, über die es verbunden ist – etwa alle Personen mit Bezug zu einem Thema "
      + "oder alle Systeme an einem Kontext.",
    parameter: { type: "object", properties: {
      von: { type: "string", description: "Name, [[Link]] oder Atlas-ID" },
      art: { type: "string", enum: ARTEN, description: "optional: nur diese Art" },
      tiefe: { type: "integer", minimum: 1, maximum: 3, description: "Schritte, Standard 2" } }, required: ["von"] } },
  // Aufgaben, Log, Termine, Frontmatter (core/abfragen.ts)
  ...ABFRAGE_WERKZEUGE,
];

// ------------------------------------------------------------------ Anzeige

function kurzName(g: Graph, id: string): string {
  return g.knoten.get(id)?.name ?? id;
}

/** Ueberschriften einer Notiz (fuer die Gliederung gekuerzter Notizen). */
function gliederung(text: string): string[] {
  return [...text.matchAll(/^(#{1,4})[ \t]+(.+?)[ \t]*$/gm)].map((m) => `${m[1]} ${m[2]}`);
}

/** Text auf etwa `max` Zeichen kuerzen - an einer Zeilengrenze, mit einem Hinweis samt Gliederung
 *  dessen, was fehlt (dann kann das Modell einen Abschnitt gezielt lesen). */
export function kappe(text: string, max: number): string {
  if (text.length <= max) return text;
  const schneide = (n: number) => {
    const cut = text.lastIndexOf("\n", n);
    return text.slice(0, cut > n / 2 ? cut : Math.max(0, n));
  };
  const hinweis = (vorne: string) => {
    const fehlt = gliederung(text.slice(vorne.length)).slice(0, 12).join(" · ").slice(0, 400);
    return `\n[… gekürzt, ${text.length - vorne.length} Zeichen fehlen`
      + (fehlt ? ` – weitere Abschnitte: ${fehlt}; gezielt lesen mit read(ziel, abschnitt)` : "") + "]";
  };
  let vorne = schneide(max - 120);
  const h = hinweis(vorne);
  if (vorne.length + h.length > max) vorne = schneide(Math.max(0, max - h.length));
  return vorne + hinweis(vorne);
}

/** Abschnitt unter einer Ueberschrift bis zur naechsten gleicher oder hoeherer Ebene; null = nicht da. */
function abschnittText(text: string, abschnitt: string): string | null {
  const gesucht = norm(abschnitt.replace(/^#+\s*/, ""));
  const zeilen = text.split("\n");
  const start = zeilen.findIndex((z) => /^#{1,6}\s/.test(z) && norm(z.replace(/^#+/, "")).includes(gesucht));
  if (start < 0 || !gesucht) return null;
  const ebene = /^(#+)/.exec(zeilen[start])![1].length;
  let ende = zeilen.length;
  for (let i = start + 1; i < zeilen.length; i++) {
    const m = /^(#{1,6})\s/.exec(zeilen[i]);
    if (m && m[1].length <= ebene) { ende = i; break; }
  }
  return zeilen.slice(start, ende).join("\n");
}

/** Kanten eines Knotens nach Beschriftung - „sendet: A, B · ← setzt um: X“. */
function bezuege(g: Graph, k: Knoten, nurArten?: Set<string>, max = 12): string[] {
  const gruppen = new Map<string, string[]>();
  for (const [v, kante] of g.nachbarn(k.id)) {
    const n = g.knoten.get(v);
    if (!n || g.gesperrt(v) || (nurArten && !nurArten.has(n.art))) continue;
    const label = kante.von === k.id ? kante.wie : `← ${kante.wie}`;
    gruppen.set(label, [...(gruppen.get(label) ?? []), g.nennung(n)]);
  }
  return [...gruppen.entries()].sort((a, b) => b[1].length - a[1].length)
    .map(([label, ns]) => `${label}: ${ns.slice(0, max).join(", ")}${ns.length > max ? ` (+${ns.length - max})` : ""}`);
}

function atlasText(g: Graph, k: Knoten): string {
  const a = g.atlas;
  const zeilen = [`${k.art} **${k.name}** (\`${k.id}\`) – Domain Atlas`];
  const kontext = a?.kontexte.get(k.id);
  const sd = a?.subdomaenen.get(k.id);
  const msg = a?.nachrichten.find((m) => m.id === k.id);
  const eintrag = a?.weitere.get(k.id);
  if (kontext) {
    zeilen.push(`Subdomäne: ${kurzName(g, kontext.sd)} · Owner: ${kontext.owner.join(", ") || "–"}`
      + (kontext.reife ? ` · Reife: ${kontext.reife}` : ""));
    if (kontext.beschreibung) zeilen.push(`Beschreibung: ${kontext.beschreibung}`);
  } else if (sd) {
    zeilen.push([sd.art && `Art: ${sd.art}`, sd.reife && `Reife: ${sd.reife}`].filter(Boolean).join(" · "));
    if (sd.beschreibung) zeilen.push(`Beschreibung: ${sd.beschreibung}`);
  } else if (msg) {
    zeilen.push(`Typ: ${msg.typ || "–"} · Reife: ${msg.reife || "–"} · von ${msg.von.map((c) => kurzName(g, c)).join(", ")}`
      + ` an ${msg.an.map((c) => kurzName(g, c)).join(", ")}`);
    if (msg.beschreibung) zeilen.push(`Beschreibung: ${msg.beschreibung}`);
  } else if (eintrag) {
    for (const [feld, wert] of eintrag.felder) zeilen.push(`${feld.charAt(0).toUpperCase()}${feld.slice(1)}: ${wert}`);
    if (eintrag.beschreibung) zeilen.push(`Beschreibung: ${eintrag.beschreibung}`);
  }
  const b = bezuege(g, k);
  if (b.length) zeilen.push("Verbunden:", ...b.map((x) => `- ${x}`));
  return zeilen.filter(Boolean).join("\n");
}

// ------------------------------------------------------------------ Werkzeuge

const STOPP = new Set(["und", "oder", "der", "die", "das", "den", "dem", "des", "ein", "eine", "mit", "von", "vom", "zu",
                       "zum", "zur", "im", "in", "an", "am", "auf", "fuer", "für", "the", "and", "of", "ist", "sind"]);

function fundstelle(text: string, klein: string, wort: string): string {
  const i = klein.indexOf(wort);
  if (i < 0) return "";
  const a = text.lastIndexOf("\n", i) + 1;
  const e = text.indexOf("\n", i);
  let zeile = strip(text.slice(a, e < 0 ? undefined : e)).replace(/^[-*>#\s]+/, "");
  if (zeile.length > 160) {
    const p = Math.max(0, i - a - 60);
    zeile = `${p ? "…" : ""}${zeile.slice(p, p + 150)}…`;
  }
  return zeile;
}

const kompakt = (s: string) => s.split(" ").join("");

function suche(g: Graph, query: string, art: string | null, max = 10): WerkzeugErgebnis {
  const q = norm(query);
  const qw = q.split(" ").filter((w) => w.length >= 2 && !STOPP.has(w));
  const roh = query.toLowerCase().split(/[^\p{L}\p{N}_-]+/u).filter((w) => w.length >= 2 && !STOPP.has(w));
  const schritt = `sucht „${strip(query)}“`;
  if (!qw.length && !roh.length) return { text: "Leere Suche – Begriffe angeben.", gelesen: [], schritt };
  const treffer: { k: Knoten; p: number; stelle: string }[] = [];
  // ein Wort passt zu einem Namen: gleich, zusammengeschrieben gleich („KundenPortal“) oder Wortanfang
  const wortPasst = (w: string, n: string) => n === w || kompakt(n) === w
    || (w.length >= 3 && n.split(" ").some((x) => x.startsWith(w)));
  for (const k of g.knoten.values()) {
    if ((art && k.art !== art) || g.gesperrt(k.id)) continue;
    let p = k.id.toLowerCase() === strip(query).toLowerCase() ? 100 : 0;
    for (const n of k.namen) {
      if (n === q || kompakt(n) === kompakt(q)) p = Math.max(p, 100);
      else if (qw.length && qw.every((w) => n.split(" ").some((x) => x.startsWith(w)))) {
        p = Math.max(p, 60 - Math.min(20, Math.abs(n.length - q.length) / 3));
      } else if (q.length >= 4 && n.includes(q)) p = Math.max(p, 45);
    }
    // mehrere Dinge in einer Suche („Portal Lagersystem“): jedes einzeln als Name
    if (!p && qw.length > 1) {
      const n = qw.filter((w) => k.namen.some((name) => wortPasst(w, name))).length;
      if (n) p = 25 + 15 * n / qw.length;
    }
    // Volltext: je mehr Woerter der Suche, desto besser
    let stelle = "";
    const klein = roh.length ? g.textKlein(k.id) : "";
    const drin = klein ? roh.filter((w) => klein.includes(w)) : [];
    if (drin.length) {
      if (!p) p = 5 + 15 * drin.length / roh.length + Math.min(5, (klein.split(drin[0]).length - 1) / 4);
      stelle = fundstelle(g.texte.get(k.id) ?? "", klein, drin[0]);
    }
    if (p) treffer.push({ k, p: p + Math.min(5, g.grad(k.id) / 20), stelle });
  }
  treffer.sort((a, b) => b.p - a.p || a.k.name.localeCompare(b.k.name));
  if (!treffer.length) {
    return { text: `Keine Treffer für „${query}“${art ? ` (Art ${art})` : ""}.`, gelesen: [], schritt };
  }
  const zeilen = treffer.slice(0, max).map(({ k, stelle }) => `- ${g.nennung(k)} · ${k.art}${stelle ? ` – „${stelle}“` : ""}`);
  return { text: `Treffer für „${query}“${art ? ` (nur ${art})` : ""}: ${treffer.length}`
    + `${treffer.length > max ? `, die ${max} besten` : ""}\n${zeilen.join("\n")}`, gelesen: [], schritt };
}

function nichtEindeutig(g: Graph, ref: string, kandidaten: Knoten[]): string {
  return kandidaten.length ? g.mehrdeutig(ref, kandidaten) : `„${ref}“ nicht gefunden – erst mit search suchen.`;
}

/** Gleichnamiges anderer Art („auch: Begriff …, Subdomäne …“) - damit das Modell es gezielt lesen kann. */
function auch(g: Graph, k: Knoten, gleichnamig: Knoten[]): string {
  const andere = gleichnamig.filter((x) => x.id !== k.id);
  return andere.length ? `\nGleichnamig (mit read gezielt lesbar): ${andere.map((x) => `${g.nennung(x)} · ${x.art}`).join("; ")}` : "";
}

async function lies(g: Graph, src: VaultSource, ziel: string, abschnitt: string, max: number): Promise<WerkzeugErgebnis> {
  const r = g.aufloesen(ziel);
  if (!r.knoten) return { text: nichtEindeutig(g, ziel, r.kandidaten), gelesen: [], schritt: `liest ${ziel}` };
  const k = r.knoten;
  const schritt = `liest ${k.name}${abschnitt ? ` (${abschnitt})` : ""}`;
  const weitere = auch(g, k, r.gleichnamig);
  if (!k.pfad) return { text: kappe(atlasText(g, k), max - weitere.length) + weitere, gelesen: [k], schritt };
  const roh = universalNewlines((await src.read(k.pfad)) ?? "");
  let text = roh;
  if (abschnitt) {
    const a = abschnittText(roh, abschnitt);
    if (a === null) {
      return { text: `${g.nennung(k)} hat keinen Abschnitt „${abschnitt}“. Abschnitte: ${gliederung(roh).join(" · ") || "keine"}`,
               gelesen: [], schritt };
    }
    text = a;
  }
  // System: die Verbindungen der Systemuebersicht (C4) und die Kontexte dazu
  const zusatz = k.art === "System"
    ? bezuege(g, k, new Set(["System", "Kontext", "Subdomäne", "Thema", "Firma"])) : [];
  const kopf = `${k.art} ${g.nennung(k)} (${k.pfad})`;
  const rest = (zusatz.length ? `\nVerbindungen im Graphen:\n${zusatz.map((x) => `- ${x}`).join("\n")}` : "") + weitere;
  return { text: `${kopf}\n<<<\n${kappe(text, Math.max(500, max - kopf.length - rest.length - 20))}\n>>>${rest}`,
           gelesen: [k], schritt };
}

function kante(g: Graph, u: string, v: string): string {
  const k = g.kante(u, v);
  if (!k) return " — ";
  return k.von === u ? ` —${k.wie}→ ` : ` ←${k.wie}— `;
}

function wege(g: Graph, von: string, nach: string): WerkzeugErgebnis {
  const a = g.aufloesen(von);
  const b = g.aufloesen(nach);
  const schritt = `sucht Wege ${a.knoten?.name ?? von} ↔ ${b.knoten?.name ?? nach}`;
  if (!a.knoten || !b.knoten) {
    return { text: [!a.knoten ? nichtEindeutig(g, von, a.kandidaten) : "", !b.knoten ? nichtEindeutig(g, nach, b.kandidaten) : ""]
      .filter(Boolean).join("\n\n"), gelesen: [], schritt };
  }
  // Gleichnamiges (Thema, Begriff, Subdomaene …) ist ein Punkt: der Weg beginnt und endet am guenstigsten
  const ws = g.wege(a.gleichnamig.map((k) => k.id), b.gleichnamig.map((k) => k.id));
  if (!ws.length) {
    return { text: `Kein Weg zwischen ${g.nennung(a.knoten)} und ${g.nennung(b.knoten)} (bis 8 Schritte).`, gelesen: [], schritt };
  }
  const zeige = (id: string) => `${g.nennung(g.knoten.get(id)!)} [${g.knoten.get(id)!.art}]`;
  const zeilen = ws.map((w, i) => `${i + 1}. ${w.map((id, j) => (j ? kante(g, w[j - 1], id) : "") + zeige(id)).join("")}`);
  const zwischen = new Map<string, number>();
  for (const w of ws) for (const id of w.slice(1, -1)) zwischen.set(id, (zwischen.get(id) ?? 0) + 1);
  const hubs = [...zwischen.entries()].sort((x, y) => y[1] - x[1])
    .map(([id, n]) => `${kurzName(g, id)} (${g.knoten.get(id)!.art}${n > 1 ? `, ${n} Wege` : ""})`);
  return { text: `Wege zwischen ${g.nennung(a.knoten)} und ${g.nennung(b.knoten)} – Allerwelts-Knoten zählen weniger:\n`
    + zeilen.join("\n") + (hubs.length ? `\nZwischenstationen: ${hubs.join(", ")}` : "\nDirekt verbunden."), gelesen: [], schritt };
}

function umkreis(g: Graph, von: string, art: string, tiefe: number | undefined): WerkzeugErgebnis {
  const a = g.aufloesen(von);
  const artF = art ? artFilter(art) : null;
  const schritt = `schaut im Umkreis von ${a.knoten?.name ?? von}${artF ? ` (${artF})` : ""}`;
  if (!a.knoten) return { text: nichtEindeutig(g, von, a.kandidaten), gelesen: [], schritt };
  const t = Math.max(1, Math.min(3, Math.round(Number(tiefe) || 2)));
  const treffer = g.umkreis(a.gleichnamig.map((k) => k.id), { art: artF, tiefe: t, max: 15 });
  const hinweis = art && !artF ? ` (Art „${art}“ unbekannt – ohne Filter)` : "";
  if (!treffer.length) {
    return { text: `Im Umkreis von ${g.nennung(a.knoten)} (${t} Schritte${artF ? `, nur ${artF}` : ""}) nichts gefunden.${hinweis}`,
             gelesen: [], schritt };
  }
  const zeilen = treffer.map((x) => {
    const via = x.ueber.map((u) => (u.startsWith("direkt") ? u : kurzName(g, u)));
    return `- ${g.nennung(x.knoten)} · ${x.knoten.art} – über ${via.slice(0, 3).join(", ")}${via.length > 3 ? ` (+${via.length - 3})` : ""}`;
  });
  return { text: `Umkreis von ${g.nennung(a.knoten)} (${t} Schritte${artF ? `, nur ${artF}` : ""}), nach Nähe:${hinweis}\n`
    + zeilen.join("\n"), gelesen: [], schritt };
}

/** Ein Werkzeug ausfuehren. Unbekannt oder kaputt: ein Satz fuers Modell statt eines Fehlers. `today` und
 *  `me` brauchen die Abfragen (ueberfaellig, „ich“). */
export async function fuehreAus(name: string, args: Record<string, unknown>, g: Graph, src: VaultSource,
                                opts: { max?: number; fortschritt?: (s: string) => void; today?: string; me?: string } = {}): Promise<WerkzeugErgebnis> {
  const max = opts.max ?? ERGEBNIS_ZEICHEN;
  const s = (k: string) => strip(str(args[k] ?? ""));
  const vorab: Record<string, string> = {
    read: `liest ${s("ziel")}`, search: `sucht „${s("query")}“`, path: `sucht Wege ${s("von")} ↔ ${s("nach")}`,
    neighbors: `schaut im Umkreis von ${s("von")}`, tasks: "sucht Aufgaben", log: "sucht im Log", meetings: "sucht Termine",
    query: "fragt Felder ab", atlas: `fragt den Atlas (${s("art")}${s("typ") ? `, ${s("typ")}` : ""})`,
  };
  opts.fortschritt?.(vorab[name] ?? name);
  const ctx: AbfrageKontext = { g, src, today: opts.today ?? localIsoDate(), me: opts.me ?? "" };
  let r: WerkzeugErgebnis;
  if (name === "search") r = suche(g, s("query"), s("art") ? artFilter(s("art")) : null);
  else if (name === "read") r = await lies(g, src, s("ziel"), s("abschnitt"), max);
  else if (name === "path") r = wege(g, s("von"), s("nach"));
  else if (name === "neighbors") r = umkreis(g, s("von"), s("art"), args.tiefe as number | undefined);
  else if (name === "tasks") r = { ...(await aufgaben(ctx, args)), gelesen: [] };
  else if (name === "log") r = { ...(await log(ctx, args)), gelesen: [] };
  else if (name === "meetings") r = { ...(await termine(ctx, args)), gelesen: [] };
  else if (name === "query") r = { ...abfrage(ctx, args), gelesen: [] };
  else if (name === "atlas") r = { ...atlasAbfrage(ctx, args), gelesen: [] };
  else {
    return { text: `Unbekanntes Werkzeug „${name}“ – es gibt ${WERKZEUGE.map((w) => w.name).join(", ")}.`, gelesen: [], schritt: name };
  }
  return { ...r, text: kappe(r.text, max) };
}
