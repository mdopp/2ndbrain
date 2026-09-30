// Absicht einer Chat-Frage: das lokale Modell waehlt aus einer festen Liste, was gemeint ist - die
// Bild-Art und die Eintraege (Themen, Subdomaenen und Kontexte des Domain Atlas). Der Code prueft die
// Wahl (nur IDs aus der Liste, nur bekannte Bild-Arten) und zeichnet selbst. Personen bestimmen weiter
// die Regeln (chat.scopeFromText) - sie werden nie geraten. Ohne Modell, bei Zeitueberschreitung oder
// unbrauchbarer Antwort gibt es keine Absicht; dann gelten die Regeln (chatBilder.pictureWish,
// atlas.matchAtlas).

import type { Atlas } from "./atlas";
import { asList } from "./entities";
import type { ChatMessage } from "./modell";
import { str, strip } from "./pytext";

/** Die Bilder, die der Code zeichnen kann - Name und was sie zeigen (so steht es im Prompt). */
export const BILDER: Record<string, string> = {
  "bild-kontexte": "Subdomänen und Kontexte des Domain Atlas: wie sie zusammenhängen, zusammenspielen, interagieren "
    + "(Nachrichten), darunter die Systeme - das einzige Bild für Einträge sd- und ctx-",
  "bild-baum": "Themenbaum mit Ampel: ein Thema mit Oberthema und Unterthemen",
  "bild-verlauf": "Zeitstrahl eines Themas (thema:): was ist wann passiert",
  "bild-beteiligte": "Personen um ein Thema oder die Themen einer Person",
  "bild-reihen": "wiederkehrende Termine (Reihen) und ihre Themen",
};

export interface Kandidat { id: string; text: string }

/** Was die Frage meint: Bild-Art (oder keine), Themen (Slugs), Atlas-IDs, oder eine Rueckfrage. */
export interface Absicht { bild: string | null; themen: string[]; atlas: string[]; rueckfrage: string | null }

export const ABSICHT_SYSTEM = [
  "Du ordnest eine Frage an einen Arbeits-Vault zu. Antworte NUR mit JSON:",
  '{"bild": <Bild-Art oder null>, "eintraege": [<IDs aus der Liste>], "rueckfrage": <Text oder null>}',
  "- bild: nur wenn ein Bild gewünscht ist ('zeichne', 'mal', 'Bild', 'Diagramm', 'Skizze', 'visualisiere', 'als",
  "  Bild'), die passende Bild-Art – für Einträge sd- oder ctx- dann immer bild-kontexte. Ohne Bildwunsch null,",
  "  auch bei Fragen nach Zusammenhängen ('Wie hängen A und B zusammen?' ist kein Bildwunsch).",
  "- eintraege: die IDs aus der Liste, die die Frage meint. Tippfehler, 'und' statt '&', Abkürzungen,",
  "  Teile eines Namens und andere Sprachen sind egal. Nennt die Frage nichts, meint aber etwas ('das',",
  "  'den Kontext', 'dazu'), nimm den Bezug - genau mit den IDs, die dort in eckigen Klammern stehen.",
  "  Nennt sie etwas anderes als den Bezug, gilt das Genannte.",
  "  Meint die Frage eine ganze Subdomäne, nimm die Subdomäne, nicht alle ihre Kontexte einzeln.",
  "- Personen stehen nicht in der Liste - lass sie weg. Fragen, die kein Thema brauchen ('Was habe ich",
  "  offen?', 'Was ist diese Woche passiert?'), sind klar: eintraege leer, rueckfrage null. Ebenso Listen- und",
  "  Filterfragen ('Welche Prozesse gibt es?', 'Welche Commands stehen auf review?', 'Welche Kontexte gehören",
  "  Team X?'): eintraege nur, was genannt ist, rueckfrage null.",
  "- Passen mehrere Einträge gleich gut und die Frage entscheidet es nicht: eintraege leer und eine kurze",
  "  rueckfrage, die die Möglichkeiten nennt.",
  "- Erfinde keine IDs.",
].join("\n");

/** Die Liste fuer das Modell: alle Themen (mit Aliasen), Subdomaenen und Kontexte des Atlas. */
export function kandidaten(themen: { slug: string; name: string; fm: Record<string, unknown> }[],
                           atlas: Atlas | null): Kandidat[] {
  const out: Kandidat[] = [];
  for (const t of themen) {
    const al = asList(t.fm.aliases).map((x) => strip(str(x))).filter(Boolean).slice(0, 3);
    out.push({ id: `thema:${t.slug}`, text: `Thema: ${t.name}${al.length ? ` (auch: ${al.join(", ")})` : ""}` });
  }
  for (const s of atlas?.subdomaenen.values() ?? []) out.push({ id: s.id, text: `Subdomäne: ${s.name}` });
  for (const k of atlas?.kontexte.values() ?? []) {
    out.push({ id: k.id, text: `Kontext: ${k.name} (in ${atlas?.subdomaenen.get(k.sd)?.name ?? k.sd})` });
  }
  return out;
}

export function absichtNachrichten(frage: string, kand: Kandidat[], bezug: string, vorher: string): ChatMessage[] {
  const bilder = Object.entries(BILDER).map(([k, v]) => `${k}: ${v}`).join("\n");
  const liste = kand.map((k) => `${k.id} = ${k.text}`).join("\n");
  return [{ role: "system", content: ABSICHT_SYSTEM },
          { role: "user", content: `Bild-Arten:\n${bilder}\n\nEinträge:\n${liste}\n\nBezug des Gesprächs: ${bezug || "keiner"}`
            + (vorher ? `\n\nVorige Frage: ${vorher}` : "") + `\n\nFrage: ${frage}` }];
}

/** Antwort des Modells pruefen: JSON, nur bekannte Bild-Arten und IDs. null = unbrauchbar. */
export function absichtLesen(text: string, kand: Kandidat[]): Absicht | null {
  const m = /\{[\s\S]*\}/.exec(text.replace(/<think>[\s\S]*?<\/think>/g, ""));
  if (!m) return null;
  let j: Record<string, unknown>;
  try {
    j = JSON.parse(m[0]) as Record<string, unknown>;
  } catch {
    return null;
  }
  const bekannt = new Set(kand.map((k) => k.id));
  const ids = (Array.isArray(j.eintraege) ? j.eintraege : []).map((x) => strip(str(x))).filter((x) => bekannt.has(x));
  const bild = typeof j.bild === "string" && j.bild in BILDER ? j.bild : null;
  const rueckfrage = !ids.length && typeof j.rueckfrage === "string" && strip(j.rueckfrage) ? strip(j.rueckfrage) : null;
  return { bild, themen: [...new Set(ids.filter((x) => x.startsWith("thema:")).map((x) => x.slice(6)))],
           atlas: [...new Set(ids.filter((x) => /^(sd|ctx)-/.test(x)))], rueckfrage };
}
