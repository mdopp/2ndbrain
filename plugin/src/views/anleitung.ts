import { ItemView, MarkdownRenderer } from "obsidian";
import ANLEITUNG from "../../anleitung.md";

export const VIEW_TYPE_ANLEITUNG = "2ndbrain-anleitung";

/** Die Anleitung fuer Benutzer - eingebaut ins Plugin (`plugin/anleitung.md`): sie passt immer zur
 *  Version und braucht keine Datei im Vault. Obsidian laedt beim Installieren nur main.js,
 *  manifest.json und styles.css, und Dateien unter .obsidian oeffnet es nicht als Notiz - deshalb
 *  steckt der Text in main.js. */
export class AnleitungView extends ItemView {
  getViewType(): string { return VIEW_TYPE_ANLEITUNG; }
  getDisplayText(): string { return "Anleitung: 2ndBrain"; }
  getIcon(): string { return "help-circle"; }

  async onOpen(): Promise<void> {
    const root = this.contentEl;
    root.empty();
    root.addClass("sb-anleitung", "markdown-rendered");
    root.addEventListener("click", (e) => this.followLink(e));
    await MarkdownRenderer.render(this.app, ANLEITUNG, root.createDiv({ cls: "sb-anleitung-text" }), "", this);
  }

  async onClose(): Promise<void> {
    this.contentEl.empty();
  }

  /** Links auf Notizen ([[01_Aufgaben]]) oeffnen - in eigenen Ansichten nicht automatisch. */
  private followLink(e: MouseEvent): void {
    const a = (e.target as HTMLElement).closest("a.internal-link");
    const href = a?.getAttribute("data-href") ?? a?.getAttribute("href");
    if (!href) return;
    e.preventDefault();
    void this.app.workspace.openLinkText(href, "", e.ctrlKey || e.metaKey);
  }
}
