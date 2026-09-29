import { App, FuzzySuggestModal } from "obsidian";
import type SecondBrainPlugin from "../main";
import { loadAtlas } from "../core/atlas";
import type { BezugTeil } from "../core/chat";

interface Wahl extends BezugTeil { art2: string; aliases: string[] }

/** Bezug des Gespraechs von Hand waehlen: Thema, Person oder ein Eintrag des Domain Atlas
 *  (Subdomaene, Kontext). Die Wahl ersetzt den bisherigen Bezug. */
export class BezugModal extends FuzzySuggestModal<Wahl> {
  private constructor(app: App, private readonly items: Wahl[], private readonly onChoose: (t: BezugTeil) => void) {
    super(app);
    this.setPlaceholder("Worüber sprechen wir? Thema, Person, Subdomäne oder Kontext …");
  }

  static async open(app: App, plugin: SecondBrainPlugin, onChoose: (t: BezugTeil) => void): Promise<void> {
    const items: Wahl[] = plugin.index.entries().map((e) => ({
      art: e.kind === "topic" ? "thema" : "person", art2: e.kind === "topic" ? "Thema" : "Person",
      id: e.slug, name: e.title, aliases: e.aliases,
    }));
    const atlas = await loadAtlas(plugin.source);
    for (const s of atlas?.subdomaenen.values() ?? []) {
      items.push({ art: "atlas", art2: "Subdomäne", id: s.id, name: s.name, aliases: [] });
    }
    for (const k of atlas?.kontexte.values() ?? []) {
      const sd = atlas?.subdomaenen.get(k.sd)?.name;
      items.push({ art: "atlas", art2: sd ? `Kontext in ${sd}` : "Kontext", id: k.id, name: k.name, aliases: [] });
    }
    new BezugModal(app, items, onChoose).open();
  }

  getItems(): Wahl[] {
    return this.items;
  }

  getItemText(w: Wahl): string {
    return `${w.name} (${w.art2})${w.aliases.length ? " · " + w.aliases.join(", ") : ""}`;
  }

  onChooseItem(w: Wahl): void {
    this.onChoose({ art: w.art, id: w.id, name: w.name });
  }
}
