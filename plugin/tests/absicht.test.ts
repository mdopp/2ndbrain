// Absicht einer Chat-Frage (core/absicht.ts): die Antwort des Modells wird geprueft, der Chat folgt ihr -
// und ohne Modell den Regeln. Namen und Modellantworten sind erfunden; kein Modell noetig.
// Mit SB_ABSICHT=1 und SB_VAULT=<Vault> vergleicht der letzte Test Regeln und Modell an echten Fragen
// aus <Vault>/.2ndbrain/chat-fragen.json (bleiben im Vault) - nur lesend, braucht den Modell-Server.
import assert from "node:assert/strict";
import { test } from "node:test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { ask } from "../src/core/chat";
import { absichtLesen, absichtNachrichten, kandidaten } from "../src/core/absicht";
import { parseAtlas } from "../src/core/atlas";
import { FsSource, MemorySource, simpleFrontmatter } from "./quellen";

const INDEX = [
  "## Subdomänen", "", "| Subdomäne | Name | Kontexte |", "|---|---|---|",
  "| `sd-lagerhof` | Lagerhof | 2 |", "| `sd-zoll-einfuhr` | Zoll & Einfuhr | 3 |", "",
  "## Kontexte", "", "| Kontext | Subdomain | Owner |", "|---|---|---|",
  "| `ctx-verladung` Verladung | sd-lagerhof |  |", "| `ctx-wareneingang` Wareneingang | sd-lagerhof |  |",
  "| `ctx-zollanmeldung` Zollanmeldung | sd-zoll-einfuhr |  |", "| `ctx-einfuhrkontrolle` Einfuhrkontrolle | sd-zoll-einfuhr |  |",
  "| `ctx-zolllager` Zolllager | sd-zoll-einfuhr |  |", "",
  "## Nachrichten", "", "| Nachricht | Typ | Reife | von | an |", "|---|---|---|---|---|",
  "| `msg-ware-verladen` Ware verladen | event | agreed | `ctx-verladung` | `ctx-zollanmeldung` |",
  "| `msg-kontrolle-frei` Kontrolle frei | event | agreed | `ctx-einfuhrkontrolle` | `ctx-zollanmeldung` |", "",
].join("\n");

const vault = () => new MemorySource({
  "entities/contexts/_index.md": INDEX,
  "entities/projects/lagerhof.md": "---\ntype: project\ntitle: Lagerhof (Bereich)\n---\n",
  "entities/projects/portal.md": "---\ntype: project\ntitle: Portal\naliases: [Kundenportal]\n---\n",
});

/** Modell-Attrappe: gibt fuer eine Frage eine vorbereitete Antwort und merkt sich, was es bekam. */
function attrappe(antworten: Record<string, string>) {
  const gesehen: string[] = [];
  const fn = async (messages: { content: string }[]) => {
    const u = messages[messages.length - 1].content;
    gesehen.push(u);
    const frage = /Frage: ([^\n]*)$/.exec(u)?.[1] ?? "";
    if (!(frage in antworten)) throw new Error("keine Antwort vorbereitet");
    return antworten[frage];
  };
  return { fn, gesehen };
}

const opts = (src: MemorySource, absicht?: (m: { content: string }[]) => Promise<string>) =>
  ({ src, today: "2026-09-29", me: "", beschreibung: "", skills: [], llm: null, files: () => new Set<string>(),
     vault: "V", absicht });

test("Absicht: Antwort des Modells prüfen – nur IDs aus der Liste, nur bekannte Bild-Arten", () => {
  const atlas = parseAtlas(INDEX)!;
  const kand = kandidaten([{ slug: "portal", name: "Portal", fm: { aliases: ["Kundenportal"] } }], atlas);
  assert.deepEqual(kand.map((k) => k.id).slice(0, 3), ["thema:portal", "sd-lagerhof", "sd-zoll-einfuhr"]);
  assert.equal(kand[0].text, "Thema: Portal (auch: Kundenportal)");
  assert.equal(kand.find((k) => k.id === "ctx-verladung")?.text, "Kontext: Verladung (in Lagerhof)");
  assert.deepEqual(absichtLesen('<think>hm</think>{"bild":"bild-kontexte","eintraege":["sd-zoll-einfuhr","sd-erfunden","thema:portal"],'
                                + '"rueckfrage":"x"}', kand),
                   { bild: "bild-kontexte", themen: ["portal"], atlas: ["sd-zoll-einfuhr"], rueckfrage: null });
  assert.deepEqual(absichtLesen('```json\n{"bild":"bild-quatsch","eintraege":[],"rueckfrage":"Welcher Kontext?"}\n```', kand),
                   { bild: null, themen: [], atlas: [], rueckfrage: "Welcher Kontext?" });
  assert.equal(absichtLesen("kein JSON", kand), null);
  const m = absichtNachrichten("Wie hängt das zusammen?", kand, "gewählt: Lagerhof [sd-lagerhof]", "vorher");
  assert.ok(m[1].content.includes("Bezug des Gesprächs: gewählt: Lagerhof [sd-lagerhof]")
            && m[1].content.includes("sd-zoll-einfuhr = Subdomäne: Zoll & Einfuhr") && m[1].content.endsWith("Frage: Wie hängt das zusammen?"));
});

test("Absicht: der Chat folgt dem Modell – Genanntes vor Bezug, Teilnamen, Rückfrage; Zeichnen bleibt Code", async () => {
  const gewaehlt = { atlas: ["sd-lagerhof"], herkunft: "gewählt" };
  const { fn, gesehen } = attrappe({
    "und ein bild vom zoll und einfur context": '{"bild":"bild-kontexte","eintraege":["sd-zoll-einfuhr"],"rueckfrage":null}',
    "wie hängen kontrolle und anmeldung zusammen? als diagramm":
      '{"bild":"bild-kontexte","eintraege":["ctx-einfuhrkontrolle","ctx-zollanmeldung"],"rueckfrage":null}',
    "zeichne den lager-kontext": '{"bild":"bild-kontexte","eintraege":[],"rueckfrage":"Meinst du Lagerhof oder Verladung?"}',
    "Sag mal, wo steht das Portal?": '{"bild":null,"eintraege":["thema:portal"],"rueckfrage":null}',
    "kannst du ein bild des contexts bauen": '{"bild":"bild-kontexte","eintraege":[],"rueckfrage":null}',
    "zeichne den zoll-kontext": '{"bild":"bild-kontexte","eintraege":["ctx-zollanmeldung","ctx-einfuhrkontrolle","ctx-zolllager"],"rueckfrage":null}',
  });
  const src = vault();
  const a = await ask({ frage: "und ein bild vom zoll und einfur context", bezug: gewaehlt }, opts(src, fn));
  assert.ok(a.antwort?.startsWith("**Zoll & Einfuhr** – Domain Atlas"), a.antwort);
  assert.ok(gesehen[0].includes("Bezug des Gesprächs: gewählt: Lagerhof [sd-lagerhof]"), gesehen[0]);
  // zwei Kontexte derselben Subdomaene, beide nur teilweise genannt: das Modell loest sie auf
  const b = await ask({ frage: "wie hängen kontrolle und anmeldung zusammen? als diagramm" }, opts(src, fn));
  assert.ok(b.antwort?.startsWith("**Einfuhrkontrolle ↔ Zollanmeldung** – Domain Atlas: 1 Nachricht"), b.antwort);
  const c = await ask({ frage: "zeichne den lager-kontext", bezug: gewaehlt }, opts(src, fn));
  assert.equal(c.antwort, "Meinst du Lagerhof oder Verladung?");
  assert.deepEqual(c.bezug?.atlas, ["sd-lagerhof"], "Rückfrage: der Bezug bleibt");
  const d = await ask({ frage: "Sag mal, wo steht das Portal?" }, opts(src, fn));
  assert.deepEqual([d.grund, d.bezug?.themen], ["Kein Modell", ["portal"]], "kein Bild, das Thema als Bezug");
  // "den Kontext" ohne Namen: der Bezug - hier das offene Thema Lagerhof -> Subdomaene
  const e = await ask({ frage: "kannst du ein bild des contexts bauen", ziel: { datei: "entities/projects/lagerhof.md" } },
                      opts(src, fn));
  assert.ok(e.antwort?.startsWith("**Lagerhof** – Domain Atlas"), e.antwort);
  // alle Kontexte einer Subdomaene gewaehlt: die Subdomaene
  const f = await ask({ frage: "zeichne den zoll-kontext" }, opts(src, fn));
  assert.ok(f.antwort?.startsWith("**Zoll & Einfuhr** – Domain Atlas"), f.antwort);
  assert.deepEqual(f.bezug?.atlas, ["sd-zoll-einfuhr"]);
});

test("Absicht: ohne Modell, mit Fehler oder unbrauchbarer Antwort gelten die Regeln", async () => {
  const src = vault();
  const kaputt = async () => "das ist kein JSON";
  const weg = async () => { throw new Error("Zeitlimit"); };
  for (const fn of [undefined, kaputt, weg]) {
    const r = await ask({ frage: "und ein bild vom zoll und einfur context" }, opts(src, fn));
    assert.ok(r.antwort?.startsWith("**Zoll & Einfuhr** – Domain Atlas"), `${fn?.name ?? "ohne"}: ${r.antwort}`);
  }
});

// Vergleich an echten Fragen (nur mit SB_ABSICHT=1 und SB_VAULT; liest, schreibt nichts)
const VAULT = process.env.SB_VAULT ?? "";
const FRAGEN = VAULT ? join(VAULT, ".2ndbrain", "chat-fragen.json") : "";
test("Vergleich Absicht: Regeln gegen Modell an echten Fragen", { skip: !process.env.SB_ABSICHT || !FRAGEN || !existsSync(FRAGEN) }, async () => {
  interface Fall { frage: string; datei?: string; bezug?: Record<string, unknown>; erwartet: { bild: string | null; atlas?: string[]; themen?: string[] } }
  const faelle = JSON.parse(readFileSync(FRAGEN, "utf-8")) as Fall[];
  const cfg = JSON.parse(readFileSync(join(VAULT, ".2ndbrain", "llm.config.json"), "utf-8")) as { url: string; model: string };
  const fms: Record<string, Record<string, unknown>> = {};
  const src = new FsSource(VAULT, new Proxy(fms, { get: (_t, p: string) => fms[p] ??= simpleFrontmatter(readFileSync(join(VAULT, p), "utf-8")) }));
  const modell = async (messages: { role: string; content: string }[]) => {
    const r = await fetch(`${cfg.url.replace(/\/$/, "")}/v1/chat/completions`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: cfg.model, messages, max_tokens: 300, temperature: 0.1, stream: false, enable_thinking: false,
                             chat_template_kwargs: { enable_thinking: false } }) });
    return ((await r.json()) as { choices: { message: { content: string } }[] }).choices[0].message.content;
  };
  const trifft = (a: { skill?: string | null; bezug?: { atlas?: string[]; themen?: string[] } }, e: Fall["erwartet"]) =>
    (a.skill ?? null) === (e.bild ?? null)
    && (!e.atlas || JSON.stringify([...(a.bezug?.atlas ?? [])].sort()) === JSON.stringify([...e.atlas].sort()))
    && (!e.themen || e.themen.every((t) => a.bezug?.themen?.includes(t)));
  let [regeln, mitModell] = [0, 0];
  for (const f of faelle) {
    const req = { frage: f.frage, ziel: { datei: f.datei ?? "" }, bezug: f.bezug as never };
    const o = { src, today: "2026-09-29", me: "", beschreibung: "", skills: [], llm: null, files: () => new Set<string>() };
    const r = await ask(req, o);
    const m = await ask(req, { ...o, absicht: modell });
    regeln += Number(trifft(r, f.erwartet));
    mitModell += Number(trifft(m, f.erwartet));
    console.log(`${trifft(r, f.erwartet) ? "✓" : "✗"} Regeln  ${trifft(m, f.erwartet) ? "✓" : "✗"} Modell  ${f.frage.slice(0, 70)}`);
    for (const [wer, a] of [["Regeln", r], ["Modell", m]] as const) {
      if (!trifft(a, f.erwartet)) {
        console.log(`    ${wer}: Bild ${a.skill ?? "-"} · Atlas ${JSON.stringify(a.bezug?.atlas ?? [])} · Themen `
          + `${JSON.stringify(a.bezug?.themen ?? [])} · ${(a.antwort ?? a.grund ?? "").split("\n")[0].slice(0, 110)}`);
      }
    }
  }
  console.log(`Treffer: Regeln ${regeln}/${faelle.length}, Modell ${mitModell}/${faelle.length}`);
});
