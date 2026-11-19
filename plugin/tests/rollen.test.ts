// Rolle je Thema (core/rollen.ts): Vererbung, Sichtbarkeit in "Nachfassen", Vorschlag aus den Punkten. Namen erfunden.
import assert from "node:assert/strict";
import { test } from "node:test";
import { RollenThema, ausgeblendet, rollenVon, sichtbar, sichtbare, vorschlaege } from "../src/core/rollen";

const thema = (slug: string, x: Partial<RollenThema> = {}): RollenThema =>
  ({ slug, path: `topics/${slug}.md`, title: slug, fokus: null, ...x });
const punkt = (owner: string | null, thema_: string, kind = "aufgabe") => ({ owner, topics: thema_ ? [thema_] : [], kind });

test("Rolle: eigene Angabe, sonst die des Dachs, sonst fuehre; Unsinn zaehlt nicht", () => {
  const r = rollenVon([
    thema("dach", { rolle: "beobachte" }), thema("kind", { parent: "dach" }),
    thema("enkel", { parent: "kind", rolle: "Beteiligt" }), thema("frei"), thema("quatsch", { rolle: "chef" }),
    thema("kreis-a", { parent: "kreis-b" }), thema("kreis-b", { parent: "kreis-a" }),
  ]);
  assert.equal(r.get("dach"), "beobachte");
  assert.equal(r.get("kind"), "beobachte");
  assert.equal(r.get("enkel"), "beteiligt");
  assert.equal(r.get("frei"), "fuehre");
  assert.equal(r.get("quatsch"), "fuehre");
  assert.equal(r.get("kreis-a"), "fuehre");
});

test("Sichtbar: meine immer; die anderer nur, wo ich fuehre; ohne bekanntes Thema bleibt der Punkt", () => {
  const r = rollenVon([thema("lager", { rolle: "beteiligt" }), thema("hafen")]);
  assert.equal(sichtbar(punkt("ich", "lager"), "ich", r), true);
  assert.equal(sichtbar(punkt("rita", "lager"), "ich", r), false);
  assert.equal(sichtbar(punkt(null, "lager"), "ich", r), false);
  assert.equal(sichtbar(punkt("rita", "hafen"), "ich", r), true);
  assert.equal(sichtbar(punkt("rita", "ohne-seite"), "ich", r), true);
  assert.equal(sichtbar(punkt("rita", ""), "ich", r), true);
  assert.equal(sichtbar({ owner: "rita", topics: ["lager", "hafen"], kind: "aufgabe" }, "ich", r), true);
  const alle = [punkt("ich", "lager"), punkt("rita", "lager"), punkt("otto", "lager", "frage"), punkt("rita", "hafen")];
  assert.equal(sichtbare(alle, "ich", r).length, 2);
  assert.equal(ausgeblendet(alle, "ich", r), 1, "Fragen zaehlen nicht mit");
});

test("Vorschlag: Fokus, verantwortlich oder hoher eigener Anteil = fuehre; nie ein eigener Punkt = beobachte", () => {
  const themen = [
    thema("fokus", { fokus: 1 }), thema("meins", { verantwortlich: "ich" }), thema("viel"), thema("wenig"),
    thema("fremd"), thema("leer"), thema("klein"),
  ];
  const tasks = [
    ...Array.from({ length: 3 }, () => punkt("ich", "viel")), ...Array.from({ length: 3 }, () => punkt("rita", "viel")),
    punkt("ich", "wenig"), ...Array.from({ length: 9 }, () => punkt("rita", "wenig")),
    ...Array.from({ length: 4 }, () => punkt("otto", "fremd")), punkt("ich", "fremd", "frage"),
    punkt("ich", "klein"), punkt("rita", "klein"),
  ];
  const v = new Map(vorschlaege(themen, tasks, "ich").map((x) => [x.slug, x]));
  assert.equal(v.get("fokus")?.vorschlag, "fuehre");
  assert.equal(v.get("meins")?.grund, "du bist als verantwortlich eingetragen");
  assert.equal(v.get("viel")?.vorschlag, "fuehre");
  assert.equal(v.get("viel")?.grund, "3 von 6 Punkten sind deine");
  assert.equal(v.get("wenig")?.vorschlag, "beteiligt");
  assert.equal(v.get("fremd")?.vorschlag, "beobachte");
  assert.equal(v.get("fremd")?.grund, "4 Punkte, keiner davon deiner");
  assert.equal(v.get("leer")?.grund, "keine Punkte");
  assert.equal(v.get("klein")?.vorschlag, "beteiligt", "zu wenige Punkte fuer 'fuehre' aus dem Anteil");
  assert.equal(vorschlaege(themen, tasks, "ich")[0].slug, "wenig", "die Themen mit den meisten Punkten zuerst");
});
