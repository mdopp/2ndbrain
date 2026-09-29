import { App, Component, FuzzySuggestModal, MarkdownRenderer, Modal, TFile } from "obsidian";
import type SecondBrainPlugin from "../main";
import { TaskInfo, daysBetween, healthEmoji, localIsoDate, standBlock, tasksForPerson, tasksForTopic } from "../core/ansicht";
import type { Entry } from "../core/vaultIndex";

/** Sofortsuche: Thema oder Person finden - im Meeting in Sekunden
 *  auskunftsfaehig, ohne auf das Modell zu warten (alles ist vorberechnet). */
export class TopicPersonSuggest extends FuzzySuggestModal<Entry> {
  constructor(app: App, private readonly plugin: SecondBrainPlugin) {
    super(app);
    this.setPlaceholder("Thema oder Person …");
  }

  getItems(): Entry[] {
    return this.plugin.index.entries();
  }

  getItemText(item: Entry): string {
    const kind = item.kind === "topic" ? "Thema" : "Person";
    return `${item.title} (${kind})${item.aliases.length ? " · " + item.aliases.join(", ") : ""}`;
  }

  onChooseItem(item: Entry): void {
    new QuickLookModal(this.app, this.plugin, item).open();
  }
}

export class QuickLookModal extends Modal {
  private readonly component = new Component();

  constructor(app: App, private readonly plugin: SecondBrainPlugin, private readonly entry: Entry) {
    super(app);
  }

  async onOpen(): Promise<void> {
    this.component.load();
    const { contentEl, entry } = this;
    contentEl.addClass("sb-quicklook");
    const file = this.app.vault.getAbstractFileByPath(entry.path);
    const text = file instanceof TFile ? await this.app.vault.cachedRead(file) : "";

    const head = contentEl.createDiv({ cls: "sb-row" });
    head.createEl("h3", { text: `${entry.kind === "topic" ? healthEmoji(entry.health) + " " : ""}${entry.title}` });
    const open = head.createEl("button", { text: "Öffnen", cls: "sb-btn-small" });
    open.onclick = () => { this.close(); this.app.workspace.openLinkText(entry.path, "", false); };

    if (entry.kind === "topic") {
      const stand = standBlock(text);
      const box = contentEl.createDiv({ cls: "sb-stand" });
      if (stand) {
        await MarkdownRenderer.render(this.app, stand, box, entry.path, this.component);
      } else {
        box.createDiv({ cls: "sb-muted", text: "Noch kein Stand-Block – `2ndbrain stand` erzeugt ihn." });
      }
      this.renderTasks(contentEl, "Offene Punkte", tasksForTopic(this.plugin.tasks, entry.slug), true);
    } else {
      const meta = [entry.role, entry.team].filter(Boolean).join(" · ");
      if (meta) contentEl.createDiv({ cls: "sb-muted", text: meta });
      const mine = tasksForPerson(this.plugin.tasks, entry.slug);
      this.renderTasks(contentEl, "Offen bei dieser Person", mine.filter((t) => t.kind !== "frage"), false);
      this.renderTasks(contentEl, "Fragen an diese Person", mine.filter((t) => t.kind === "frage"), false);
    }
  }

  private renderTasks(parent: HTMLElement, title: string, tasks: TaskInfo[], showOwner: boolean): void {
    if (!tasks.length) return;
    const today = localIsoDate();
    parent.createEl("h4", { text: `${title} (${tasks.length})` });
    const list = parent.createDiv({ cls: "sb-tasklist" });
    const sorted = [...tasks].sort((a, b) => (a.created ?? "").localeCompare(b.created ?? ""));
    for (const t of sorted.slice(0, 25)) {
      const overdue = !!t.due && t.due < today;
      const row = list.createDiv({ cls: `sb-fu${overdue ? " sb-overdue" : ""}` });
      if (t.kind === "frage") row.createSpan({ text: "❓ " });
      row.createSpan({ cls: "sb-task", text: t.text });
      const who = showOwner ? (t.owner ? this.plugin.index.personName(t.owner) : t.owner_raw ?? "?") : "";
      const age = t.created ? `seit ${daysBetween(t.created, today)} T` : "";
      const parts = [who, t.due ? `📅 ${t.due}` : "", age].filter(Boolean);
      if (parts.length) row.createSpan({ cls: "sb-muted", text: ` · ${parts.join(" · ")}` });
      if (t.path) row.onclick = () => { this.close(); this.plugin.openAt(t.path!, t.line); };
    }
    if (sorted.length > 25) parent.createDiv({ cls: "sb-muted", text: `… ${sorted.length - 25} weitere` });
  }

  onClose(): void {
    this.component.unload();
    this.contentEl.empty();
  }
}
