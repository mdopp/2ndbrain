// Chat: Bildwunsch, Atlas (Kontexte und Nachrichten aus dem Kontext-Verzeichnis), anklickbare Kaesten.
// Namen und Daten sind erfunden.
import assert from "node:assert/strict";
import { test } from "node:test";
import { ask } from "../src/core/chat";
import { pictureWish } from "../src/core/chatBilder";
import { matchAtlas, parseAtlas } from "../src/core/atlas";
import { MemorySource } from "./quellen";

const INDEX = [
  "---", "type: contexts-index", "generated: true", "---", "", "# Domain-Atlas-Kontexte", "",
  "## Subdomänen", "", "| Subdomäne | Name | Kontexte |", "|---|---|---|",
  "| `sd-auftragswesen` | Auftragswesen | 1 |", "| `sd-lagerhof` | Lagerhof | 2 |", "",
  "## Kontexte", "", "| Kontext | Subdomain | Owner |", "|---|---|---|",
  "| `ctx-auftragsannahme` Auftragsannahme | sd-auftragswesen | team-auftrag |",
  "| `ctx-verladung` Verladung | sd-lagerhof |  |",
  "| `ctx-wareneingang` Wareneingang | sd-lagerhof | team-lager, team-halle |", "",
  "## Nachrichten", "", "| Nachricht | Typ | Reife | von | an |", "|---|---|---|---|---|",
  "| `msg-sendung-suchen` finde \"Sendung\" nach Nummer | query | review | `ctx-wareneingang`, `ctx-verladung` | `ctx-auftragsannahme` |",
  "| `msg-palette-gebildet` Palette gebildet | event | agreed | `ctx-verladung` | `ctx-auftragsannahme`, `ctx-wareneingang` (proposed) |",
  "| `msg-alt` Alte Meldung | event | retired | `ctx-verladung` | `ctx-auftragsannahme` |", "",
].join("\n");

function vault(): MemorySource {
  return new MemorySource({
    "entities/contexts/_index.md": INDEX,
    "entities/projects/auftragswesen.md": "---\ntype: project\ntitle: Auftragswesen (Bereich)\n---\n# Auftragswesen\n",
    "entities/glossary/wareneingang.md": "---\ntype: glossary_term\nterm: Wareneingang\natlas_id: ctx-wareneingang\n---\n",
    "entities/systems/lagerbox.md": "---\ntype: system\nname: Lagerbox\natlas_kontexte: [ctx-wareneingang, ctx-verladung]\n---\n",
    "entities/systems/auftragsportal.md": "---\ntype: system\nname: Auftragsportal\natlas_kontexte: [ctx-auftragsannahme]\n"
      + "ersetzt: '[[lagerbox]]'\n---\n",
  });
}

const opts = (src: MemorySource) => ({ src, today: "2026-09-29", me: "", beschreibung: "", skills: [], llm: null,
                                       files: () => new Set<string>(), vault: "Test Vault" });

test("Chat: Bildwunsch – Kontexte ins Atlas-Bild, 'Sag mal' und 'Zeig mir die offenen Punkte' sind keine Bilder", () => {
  const frage = "kannst du mir ein mermaid diagram malen, das zeigt wie die kontexte a und b zusammen interagieren?";
  assert.equal(pictureWish(frage, { themen: ["a"], atlas: ["sd-a", "sd-b"] }), "bild-kontexte");
  assert.equal(pictureWish(frage, { themen: ["a"] }), null, "Kontexte ohne Atlas-Treffer: nie der Themenbaum");
  assert.equal(pictureWish("Sag mal, wo steht das Portal?", { themen: ["p"] }), null);
  assert.equal(pictureWish("Zeig mir die offenen Punkte vom Portal", { themen: ["p"] }), null);
  assert.equal(pictureWish("Zeig mir die Beteiligten", {}), "bild-beteiligte");
  assert.equal(pictureWish("Zeig mir den Themenbaum", { themen: ["p"] }), "bild-baum");
  assert.equal(pictureWish("Zeichne das Portal", { themen: ["p"] }), "bild-baum");
  assert.equal(pictureWish("Zeichne den Lagerhof", { atlas: ["sd-lagerhof"] }), "bild-kontexte");
  assert.equal(pictureWish("Welche Systeme setzen den Lagerhof um? Als Bild bitte", { atlas: ["sd-lagerhof"] }), "bild-kontexte");
  assert.equal(pictureWish("Mal die Reihen auf", {}), "bild-reihen");
  assert.equal(pictureWish("Kannst du das aufmalen?", { themen: ["p"] }), "bild-baum");
});

test("Atlas: Verzeichnis lesen, Namen in der Frage finden (eindeutig, längster zuerst)", () => {
  const atlas = parseAtlas(INDEX)!;
  assert.deepEqual([...atlas.subdomaenen.keys()], ["sd-auftragswesen", "sd-lagerhof"]);
  assert.deepEqual(atlas.kontexte.get("ctx-wareneingang"), { id: "ctx-wareneingang", name: "Wareneingang", sd: "sd-lagerhof",
                                                             owner: ["team-lager", "team-halle"] });
  const pal = atlas.nachrichten.find((m) => m.id === "msg-palette-gebildet")!;
  assert.deepEqual([pal.typ, pal.reife, pal.von, pal.an, [...pal.kantenReife]],
                   ["event", "agreed", ["ctx-verladung"], ["ctx-auftragsannahme", "ctx-wareneingang"], [["ctx-wareneingang", "proposed"]]]);
  assert.deepEqual(matchAtlas("Wie spielen der Lagerhof und das Auftragswesen zusammen?", atlas), ["sd-lagerhof", "sd-auftragswesen"]);
  assert.deepEqual(matchAtlas("Was schickt der Wareneingang?", atlas), ["ctx-wareneingang"]);
  assert.deepEqual(matchAtlas("Wo steht das Portal?", atlas), []);
  // aeltere Verzeichnisse ohne Subdomaenen-Tabelle: Name aus der ID
  const alt = parseAtlas("| Kontext | Subdomain | Owner |\n|---|---|---|\n| `ctx-x` X-Kontext | sd-zoll-wesen |  |\n")!;
  assert.equal(alt.subdomaenen.get("sd-zoll-wesen")?.name, "Zoll Wesen");
});

test("Chat: Bild Kontexte – Nachrichten zwischen Subdomänen, Systeme darunter, Kästen öffnen die Notiz", async () => {
  const r = await ask({ frage: "kannst du mir ein mermaid diagram malen, das zeigt wie die kontexte lagerhof und "
                               + "auftragswesen zusammen interagieren?" }, opts(vault()));
  assert.equal(r.ok, true, r.grund);
  assert.equal(r.skill, "bild-kontexte");
  const a = r.antwort!;
  assert.match(a, /\*\*Lagerhof ↔ Auftragswesen\*\* – Domain Atlas: 2 Nachrichten \(1 Query, 1 Event\); alle von Lagerhof an Auftragswesen/);
  assert.ok(a.includes('subgraph g0["Lagerhof · 2 Kontexte"]'), a);
  // beide Lagerhof-Kontexte fragen: eine Kante vom Rahmen; offen = gestrichelt
  assert.ok(a.includes('g0 -.->|"Query: finde Sendung nach Nummer · review"| k1_0'), a);
  // Kontexte in der Reihenfolge des Verzeichnisses: k0_0 Verladung, k0_1 Wareneingang
  assert.ok(a.includes('k0_0 -->|"Event: Palette gebildet"| k1_0'), a);
  assert.ok(!a.includes("Alte Meldung") && a.includes("1 stillgelegte nicht gezeigt"), "stillgelegt wird nicht gezeichnet");
  assert.ok(a.includes('click k0_1 "obsidian://open?vault=Test%20Vault&file=entities%2Fglossary%2Fwareneingang.md" '
                       + '"entities/glossary/wareneingang.md"'), "Kontext mit Glossar-Seite");
  assert.ok(a.includes('"entities/contexts/_index.md"'), "Kontext ohne Seite: das Verzeichnis");
  // Software darunter: Systeme ueber atlas_kontexte, Nachrichten auf die Systeme uebertragen
  assert.ok(a.includes("**Software (C4):** 2 Systeme setzen diese Kontexte um"), a);
  assert.ok(a.includes('s1 -->|"finde Sendung nach Nummer, Palette gebildet"| s0'), a);
  assert.ok(a.includes('s0 -.->|"löst ab"| s1'), a);
  assert.ok(a.includes('"entities/systems/lagerbox.md"'), "System anklickbar");
  assert.deepEqual(r.bezug?.atlas, ["sd-lagerhof", "sd-auftragswesen"]);
  assert.ok(r.bezug?.anzeige.includes("Lagerhof (Atlas)"), String(r.bezug?.anzeige));
});

test("Chat: Fragen ohne Bild – 'Sag mal' geht ans Modell, Atlas-Fragen bekommen die Nachrichten in den Ausschnitt", async () => {
  const src = vault();
  const r1 = await ask({ frage: "Sag mal, wo steht Auftragswesen?" }, opts(src));
  assert.equal(r1.grund, "Kein Modell");
  assert.ok(!r1.ausschnitt?.includes("Domain Atlas"), "keine Atlas-Frage");
  const r2 = await ask({ frage: "Welche Nachrichten tauschen Lagerhof und Auftragswesen aus?" }, opts(src));
  assert.ok(r2.ausschnitt?.startsWith("## Domain Atlas (Kontext-Verzeichnis)"), r2.ausschnitt);
  assert.ok(r2.ausschnitt?.includes("- query „finde \"Sendung\" nach Nummer“ (review): Wareneingang, Verladung → Auftragsannahme"),
            r2.ausschnitt);
  // eine allein: ihre Kontexte und die Nachrichten ueber die Grenze, Partner je Subdomaene
  const r3 = await ask({ frage: "Zeichne die Kontexte vom Lagerhof" }, opts(src));
  assert.ok(r3.antwort?.includes('x0["Auftragswesen"]:::grau') && r3.antwort.includes("k0_0 -.->|\"Event: Palette gebildet · proposed\"| k0_1")
            && r3.antwort.includes('g0 -.->|"Query: finde Sendung nach Nummer · review"| x0'), r3.antwort);
});

test("Chat: 'Bild des Contexts' ohne Namen – der Kontext des offenen Themas oder der offenen Atlas-Seite", async () => {
  const src = vault();
  assert.equal(pictureWish("kannst du ein bild des contexts bauen", { themen: ["auftragswesen"], atlas: ["sd-auftragswesen"] }),
               "bild-kontexte");
  // offenes Thema "Auftragswesen (Bereich)" -> gleichnamige Subdomaene sd-auftragswesen
  const r = await ask({ frage: "kannst du ein bild des contexts bauen", ziel: { datei: "entities/projects/auftragswesen.md" } },
                      opts(src));
  assert.equal(r.skill, "bild-kontexte", r.antwort);
  assert.ok(r.antwort?.startsWith("**Auftragswesen** – Domain Atlas: 2 Nachrichten"), r.antwort);
  assert.deepEqual(r.bezug?.atlas, ["sd-auftragswesen"]);
  // offene Glossar-Seite mit atlas_id
  const g = await ask({ frage: "Zeichne den Kontext", ziel: { datei: "entities/glossary/wareneingang.md" } }, opts(src));
  assert.equal(g.skill, "bild-kontexte", g.antwort);
  assert.ok(g.antwort?.startsWith("**Wareneingang** – Domain Atlas"), g.antwort);
  // dieselbe Seite bei einer Frage ohne Kontext: kein Bezug daraus
  const n = await ask({ frage: "Was ist neu?", ziel: { datei: "entities/glossary/wareneingang.md" } }, opts(src));
  assert.deepEqual([n.bezug?.atlas, n.bezug?.herkunft], [[], ""]);
  // Thema ohne Atlas-Gegenstueck: kein Bild, das Modell antwortet
  const src2 = new MemorySource({ "entities/contexts/_index.md": INDEX,
                                  "entities/projects/portal.md": "---\ntype: project\ntitle: Portal\n---\n" });
  const p = await ask({ frage: "kannst du ein bild des contexts bauen", ziel: { datei: "entities/projects/portal.md" } }, opts(src2));
  assert.equal(p.grund, "Kein Modell", "nie der Themenbaum für eine Frage nach dem Kontext");
});

test("Chat: Bezug von Hand gewählt – gilt für die Frage, Teile einzeln, Herkunft bleibt 'gewählt'", async () => {
  const src = vault();
  // gewaehlt: nur die Subdomaene Lagerhof; die Frage nennt nichts
  const r = await ask({ frage: "kannst du ein bild des contexts bauen", bezug: { atlas: ["sd-lagerhof"], herkunft: "gewählt" } },
                      opts(src));
  assert.equal(r.skill, "bild-kontexte", r.antwort);
  assert.ok(r.antwort?.startsWith("**Lagerhof** – Domain Atlas"), r.antwort);
  assert.equal(r.bezug?.herkunft, "gewählt");
  assert.deepEqual(r.bezug?.teile, [{ art: "atlas", id: "sd-lagerhof", name: "Lagerhof" }]);
  // Teile aus einer Frage: Thema und Atlas getrennt, jeweils mit Namen
  const f = await ask({ frage: "Wie interagieren Lagerhof und Auftragswesen?" }, opts(src));
  assert.deepEqual(f.bezug?.teile?.map((t) => `${t.art}:${t.id}:${t.name}`),
                   ["thema:auftragswesen:Auftragswesen (Bereich)", "atlas:sd-lagerhof:Lagerhof", "atlas:sd-auftragswesen:Auftragswesen"]);
  assert.equal(f.bezug?.herkunft, "aus der Frage");
});

const INDEX2 = [
  "## Subdomänen", "", "| Subdomäne | Name | Kontexte |", "|---|---|---|",
  "| `sd-lagerhof` | Lagerhof | 1 |", "| `sd-zoll-einfuhr` | Zoll & Einfuhr | 1 |", "",
  "## Kontexte", "", "| Kontext | Subdomain | Owner |", "|---|---|---|",
  "| `ctx-verladung` Verladung | sd-lagerhof |  |", "| `ctx-zollanmeldung` Zollanmeldung | sd-zoll-einfuhr |  |", "",
  "## Nachrichten", "", "| Nachricht | Typ | Reife | von | an |", "|---|---|---|---|---|",
  "| `msg-ware-verladen` Ware verladen | event | agreed | `ctx-verladung` | `ctx-zollanmeldung` |", "",
].join("\n");

test("Chat: Namen mit 'und'/'&' und Tippfehler erkennen; Ungefähres führt zur Rückfrage, nie zum alten Bezug", async () => {
  const atlas = parseAtlas(INDEX2)!;
  assert.deepEqual(matchAtlas("und ein bild vom zoll und einfur context", atlas), ["sd-zoll-einfuhr"]);
  assert.deepEqual(matchAtlas("Zoll and Einfuhr", atlas), ["sd-zoll-einfuhr"]);
  assert.deepEqual(matchAtlas("ein Bild vom Lagerhoff", atlas), ["sd-lagerhof"], "ein Tippfehler im Namen");
  const src = new MemorySource({ "entities/contexts/_index.md": INDEX2 });
  const gewaehlt = { atlas: ["sd-lagerhof"], herkunft: "gewählt" };
  // was die Frage nennt, geht vor dem gewaehlten Bezug
  const r = await ask({ frage: "und ein bild vom zoll und einfur context", bezug: gewaehlt }, opts(src));
  assert.equal(r.skill, "bild-kontexte");
  assert.ok(r.antwort?.startsWith("**Zoll & Einfuhr** – Domain Atlas"), r.antwort);
  // nur ein Teil des Namens: nachfragen, der Bezug bleibt
  const q = await ask({ frage: "Zeichne den Einfuhr-Kontext", bezug: gewaehlt }, opts(src));
  assert.ok(q.antwort?.startsWith("Welchen Kontext meinst du?") && q.antwort.includes("**Zoll & Einfuhr** (Subdomäne)"), q.antwort);
  assert.deepEqual([q.bezug?.atlas, q.bezug?.herkunft], [["sd-lagerhof"], "gewählt"]);
  // ohne Namen: der gewaehlte Bezug
  const b = await ask({ frage: "kannst du ein bild des contexts bauen", bezug: gewaehlt }, opts(src));
  assert.ok(b.antwort?.startsWith("**Lagerhof** – Domain Atlas"), b.antwort);
});

test("Bilder: Themenbaum-Kästen tragen den Pfad ihrer Notiz", async () => {
  const src = new MemorySource({
    "entities/projects/dach.md": "---\ntype: project\ntitle: Dach\n---\n",
    "entities/projects/portal.md": "---\ntype: project\ntitle: Portal\nparent: '[[dach]]'\nhealth: red\n---\n",
  });
  const r = await ask({ frage: "Zeichne den Themenbaum" }, opts(src));
  assert.ok(r.antwort?.includes('"entities/projects/portal.md"') && r.antwort.includes("click t"), r.antwort);
});
