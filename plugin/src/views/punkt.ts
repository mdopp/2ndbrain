import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";
import type { TaskInfo } from "../core/ansicht";

/** Ein offener Punkt mit eigenem Satz: erledigt, verworfen oder nur ein Hinweis. Der Satz steht als Unterpunkt
 *  an der Quelle - und, wenn gewuenscht, als Eintrag im Log des Themas. Geht auch am Handy. */
export class PunktModal extends Modal {
  constructor(app: App, private readonly plugin: SecondBrainPlugin, private readonly task: TaskInfo) {
    super(app);
  }

  onOpen(): void {
    const el = this.contentEl;
    el.addClass("sb-capture");
    this.titleEl.setText("Punkt abschließen – mit Hinweis");
    const t = this.task;
    el.createDiv({ cls: "sb-task-text", text: t.text });
    const thema = t.topics[0] ? this.plugin.index.topic(t.topics[0]) : null;
    const meta = [thema?.title ?? "", t.due ? `Frist ${t.due}` : "", t.created ? `seit ${t.created}` : ""].filter(Boolean).join(" · ");
    if (meta) el.createDiv({ cls: "sb-muted", text: meta });

    const feld = el.createEl("textarea", { cls: "sb-kurz", attr: { rows: "3", placeholder: "Hinweis: was ist daraus geworden? (freiwillig)" } });
    let insLog: HTMLInputElement | null = null;
    if (thema) {
      const zeile = el.createEl("label", { cls: "sb-muted sb-check" });
      insLog = zeile.createEl("input", { type: "checkbox" });
      zeile.appendText(` auch als Eintrag ins Log von „${thema.title}“ (nur mit Hinweis)`);
    }

    const knoepfe = el.createDiv({ cls: "sb-buttons" });
    const tun = (als: "erledigt" | "verworfen" | "hinweis") => async () => {
      const hinweis = feld.value.trim();
      if (als === "hinweis" && !hinweis) {
        new Notice("2ndBrain: Für „Nur Hinweis“ fehlt der Hinweis.");
        return;
      }
      knoepfe.querySelectorAll("button").forEach((b) => { (b as HTMLButtonElement).disabled = true; });
      const r = await this.plugin.punktAendern(t, { als, hinweis, log: !!insLog?.checked });
      if (!r.ok) {
        new Notice(`2ndBrain: nicht geschrieben – ${r.grund ?? "Fehler"}`, 8000);
        knoepfe.querySelectorAll("button").forEach((b) => { (b as HTMLButtonElement).disabled = false; });
        return;
      }
      this.close();
    };
    knoepfe.createEl("button", { text: "Erledigt", cls: "mod-cta" }).onclick = tun("erledigt");
    knoepfe.createEl("button", { text: "Verwerfen" }).onclick = tun("verworfen");
    knoepfe.createEl("button", { text: "Nur Hinweis" }).onclick = tun("hinweis");
    knoepfe.createEl("button", { text: "Abbrechen" }).onclick = () => this.close();
    feld.focus();
  }

  onClose(): void {
    this.contentEl.empty();
  }
}
