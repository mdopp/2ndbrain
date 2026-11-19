import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";
import { isOpen, scanTasks } from "../core/aufgaben";
import {
  FELD, ROLLEN, ROLLEN_TEXT, ROLLEN_WIRKUNG, Rolle, RollenVorschlag, ausgeblendet, rollenVon, vorschlaege,
} from "../core/rollen";

const ERBT = "";

/** „Meine Rolle je Thema“: führe ich es, bin ich beteiligt, beobachte ich nur? Das Plugin schlägt je Thema eine
 *  Rolle vor (aus den Punkten im Vault, ohne Modell) - man korrigiert und speichert. Geschrieben wird
 *  `meine_rolle:` ins Frontmatter des Themas; Punkte bleiben stehen, die Rolle blendet in „Nachfassen“ aus. */
export class RollenModal extends Modal {
  private zeilen: RollenVorschlag[] = [];
  private wahl = new Map<string, Rolle | "">();
  private offene: { owner: string | null; topics: string[]; kind: string }[] = [];
  private summeEl!: HTMLElement;

  constructor(app: App, private readonly plugin: SecondBrainPlugin) {
    super(app);
  }

  onOpen(): void {
    this.modalEl.addClass("sb-auto-modal");
    this.contentEl.addClass("sb-capture");
    this.titleEl.setText("Meine Rolle je Thema");
    void this.laden();
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private async laden(): Promise<void> {
    const el = this.contentEl;
    el.empty();
    const ich = this.plugin.selfSlug;
    if (!ich) {
      el.createDiv({ cls: "sb-fehler", text: "Zuerst „Ich“ eintragen (Einstellungen → 2ndBrain → Vault-Konfiguration) – "
        + "ohne das weiß das Plugin nicht, welche Punkte deine sind." });
      return;
    }
    const alle = await scanTasks(this.plugin.source);
    this.offene = alle.filter(isOpen);
    this.zeilen = vorschlaege(this.plugin.index.topics(), alle, ich);
    for (const z of this.zeilen) this.wahl.set(z.slug, z.eigene || z.vorschlag);

    el.createDiv({ cls: "sb-muted", text: "Nicht jedes Thema, in dessen Terminen du sitzt, führst du. Die Rolle entscheidet, "
      + "wessen offene Punkte du nachhältst – deine eigenen siehst du immer, und nichts wird gelöscht." });
    const legende = el.createEl("ul", { cls: "sb-muted" });
    for (const r of ROLLEN) legende.createEl("li", { text: `${ROLLEN_TEXT[r]}: ${ROLLEN_WIRKUNG[r]}` });
    this.summeEl = el.createDiv({ cls: "sb-hint" });

    const offen = this.zeilen.filter((z) => !z.eigene).length;
    if (offen) el.createDiv({ cls: "sb-hint sb-muted", text: `${offen} Thema/Themen ohne Rolle – vorbelegt ist der Vorschlag. `
      + "Stimmt er nicht, ändere ihn; „erbt“ nimmt die Rolle des Oberthemas." });

    for (const z of this.zeilen) this.zeile(el, z);

    const knoepfe = el.createDiv({ cls: "sb-buttons" });
    const ok = knoepfe.createEl("button", { text: "Speichern", cls: "mod-cta" });
    ok.onclick = () => void this.speichern(ok);
    knoepfe.createEl("button", { text: "Abbrechen" }).onclick = () => this.close();
    this.summe();
  }

  private zeile(parent: HTMLElement, z: RollenVorschlag): void {
    const row = parent.createDiv({ cls: "sb-row sb-triage" });
    const main = row.createDiv({ cls: "sb-task-main" });
    const titel = main.createDiv({ cls: "sb-task-text sb-link", text: z.title, attr: { title: z.path } });
    titel.onclick = () => {
      this.close();
      void this.app.workspace.openLinkText(z.path, "", false);
    };
    main.createDiv({ cls: "sb-muted", text: (z.eigene ? `eingetragen: ${ROLLEN_TEXT[z.eigene]} · ` : "")
      + `Vorschlag: ${ROLLEN_TEXT[z.vorschlag]} – ${z.grund}` });
    const select = row.createEl("select", { cls: "dropdown", attr: { "aria-label": `Rolle für ${z.title}` } });
    for (const r of ROLLEN) select.createEl("option", { text: ROLLEN_TEXT[r], value: r });
    select.createEl("option", { text: "erbt vom Oberthema", value: ERBT });
    select.value = this.wahl.get(z.slug) ?? ERBT;
    select.onchange = () => {
      this.wahl.set(z.slug, select.value as Rolle | "");
      this.summe();
    };
  }

  /** Was die Auswahl bewirkt - vor dem Speichern sichtbar. */
  private summe(): void {
    const themen = this.plugin.index.topics().map((t) => ({ ...t, rolle: this.wahl.get(t.slug) ?? "" }));
    const n = ausgeblendet(this.offene, this.plugin.selfSlug, rollenVon(themen));
    const andere = this.offene.filter((t) => t.kind !== "frage" && !!t.owner && t.owner !== this.plugin.selfSlug).length;
    this.summeEl.setText(`Mit dieser Auswahl: ${andere - n} von ${andere} offenen Punkten anderer bleiben in „Nachfassen“, `
      + `${n} werden ausgeblendet.`);
  }

  private async speichern(button: HTMLButtonElement): Promise<void> {
    const changes = this.zeilen
      .filter((z) => (this.wahl.get(z.slug) ?? ERBT) !== z.eigene)
      .map((z) => ({ path: z.path, titel: z.title, updates: { [FELD]: this.wahl.get(z.slug) || null }, schritt: null }));
    if (!changes.length) {
      this.close();
      return;
    }
    button.disabled = true;
    const r = await this.plugin.fokusSpeichern(changes);
    if (r.fehler.length) new Notice(`Nicht gespeichert: ${r.fehler.join(", ")}`, 10_000);
    else new Notice(`Rolle für ${changes.length} Thema/Themen gespeichert.`);
    this.close();
  }
}
