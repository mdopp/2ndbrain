import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";
import { MeetingInfo, materialText, sectionLines } from "../core/ansicht";

const WEEKDAYS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];

function when(m: MeetingInfo): string {
  const [y, mo, d] = m.date.split("-").map(Number);
  const wd = WEEKDAYS[new Date(y, mo - 1, d).getDay()];
  return `${wd} ${m.date.slice(8, 10)}.${m.date.slice(5, 7)}.${m.time ? ` ${m.time}` : ""}`;
}

/** Nacherfassen: erst Notizen, dann (auf Ansage) nachbereiten - so lassen sich Notizen
 *  nachtragen, bevor das Modell laeuft. */
export class CaptureModal extends Modal {
  private area!: HTMLTextAreaElement;
  private errorEl!: HTMLElement;
  private buttons: HTMLButtonElement[] = [];
  private material = "";

  constructor(app: App, private readonly plugin: SecondBrainPlugin, private readonly meeting: MeetingInfo) {
    super(app);
  }

  async onOpen(): Promise<void> {
    const m = this.meeting;
    this.titleEl.setText(`Nacherfassen · ${m.title}`);
    const el = this.contentEl;
    el.addClass("sb-capture");

    const titles = (m.topics ?? (m.topic ? [m.topic] : []))
      .map((s) => this.plugin.index.topic(s)?.title ?? s);
    const people = m.persons.map((p) => this.plugin.index.personName(p)).slice(0, 6).join(", ");
    const desk = this.plugin.isDesktop;
    const meta = el.createDiv({ cls: "sb-muted", text: [when(m), titles.length ? `Thema: ${titles.join(", ")}`
      : "kein Thema", people].filter(Boolean).join(" · ") + (desk ? " · " : "") });
    if (desk) {                                  // Thema setzt die Engine (Desktop)
      const change = meta.createEl("a", { text: titles.length ? "Thema ändern" : "Thema wählen", href: "#" });
      change.onclick = (e) => {
        e.preventDefault();
        this.plugin.openTopicPicker({ kind: "note", path: m.path });
      };
    }
    if (m.nachbereiten === "angefordert") {
      el.createDiv({ cls: "sb-muted sb-hint", text: "Zum Nachbereiten vorgemerkt – der Desktop erledigt es beim nächsten Lauf." });
    }

    this.material = materialText(await this.app.vault.adapter.read(m.path));
    if (this.material) {
      const det = el.createEl("details", { cls: "sb-material" });
      det.createEl("summary", { text: `Schon in der Notiz: ${this.material.length} Zeichen (Teams, Notizen)` });
      det.createEl("pre", { text: this.material });
    }

    el.createDiv({ cls: "sb-label", text: this.material ? "Ergänzen" : "Deine Notizen" });
    this.area = el.createEl("textarea", {
      attr: { rows: "10", placeholder: "Stichpunkte reichen, z. B.\nEntscheidung: Englisch als Arbeitssprache im Atlas\n"
        + "Ines: Begriffsliste liefern bis 2.10.\nOffen: Wer entscheidet über das Routing?" },
    });
    el.createDiv({ cls: "sb-muted sb-hint", text: desk
      ? "Entscheidungen und Aufgaben erkennt die Nachbereitung. Danach siehst du das Ergebnis und kannst es zurücknehmen."
      : "Entscheidungen und Aufgaben erkennt die Nachbereitung am Desktop – „Speichern und vormerken“, sie läuft "
        + "beim nächsten Lauf der Automatik." });
    this.errorEl = el.createDiv({ cls: "sb-error" });
    this.area.addEventListener("input", () => this.errorEl.setText(""));

    const bar = el.createDiv({ cls: "sb-buttons" });
    this.button(bar, "Fand nicht statt", () => this.entfallen());
    this.button(bar, "Nur speichern", () => this.save(false));
    this.button(bar, desk ? "Speichern und nachbereiten" : "Speichern und vormerken", () => this.save(true), true);
    this.area.focus();
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private button(bar: HTMLElement, text: string, onClick: () => Promise<void>, cta = false): void {
    const b = bar.createEl("button", { text, cls: cta ? "mod-cta" : "" });
    b.onclick = () => void onClick();
    this.buttons.push(b);
  }

  private busy(text: string | null): void {
    for (const b of this.buttons) b.disabled = text !== null;
    this.errorEl.setText(text ?? "");
    this.errorEl.toggleClass("sb-working", text !== null);
  }

  private async entfallen(): Promise<void> {
    if (this.area.value.trim()) {
      this.errorEl.setText("Du hast Notizen eingetragen – erst speichern oder leeren.");
      return;
    }
    this.busy("Speichere …");
    const r = await this.plugin.setEntfallen(this.meeting.path, true);
    if (!r.ok) {
      this.busy(null);
      this.errorEl.setText(r.grund ?? "Hat nicht geklappt.");
      return;
    }
    new Notice(`„${this.meeting.title}“: fand nicht statt`);
    this.close();
    await this.plugin.refreshTasks();
  }

  private async save(wrapup: boolean): Promise<void> {
    const text = this.area.value.trim();
    const fail = (msg: string) => { this.busy(null); this.errorEl.setText(msg); };
    if (!text && !wrapup) return fail("Noch keine Notizen eingetragen.");
    if (!text && !this.material) return fail("Erst Notizen eintragen – ohne Text gibt es nichts nachzubereiten.");
    const desk = this.plugin.isDesktop;
    if (wrapup && desk && !this.plugin.llmState.ok) {
      return fail(`Modell nicht erreichbar (${this.plugin.llmState.detail}) – „Nur speichern“ und später nachbereiten.`);
    }
    if (text) {
      this.busy("Speichere …");
      const r = await this.plugin.captureNotes(this.meeting.path, text);
      if (!r.ok) return fail(r.grund ?? "Speichern fehlgeschlagen.");
    }
    if (!wrapup) {
      new Notice("Notizen gespeichert");
      this.close();
      await this.plugin.refreshTasks();
      return;
    }
    if (!desk) {                                 // Handy: vormerken, der Desktop bereitet nach
      const r = await this.plugin.requestWrapup(this.meeting.path);
      if (!r.ok) return fail(r.grund ?? "Vormerken fehlgeschlagen.");
      new Notice("Gespeichert und zum Nachbereiten vorgemerkt – der Desktop erledigt es beim nächsten Lauf.", 6000);
      this.close();
      await this.plugin.refreshTasks();
      return;
    }
    // Nicht warten: das Fenster geht zu, die Seitenleiste zeigt den Fortschritt
    this.close();
    this.plugin.startWrapup(this.meeting);
  }
}

/** Was die Nachbereitung geschrieben hat - mit "Rueckgaengig". */
export class WrapupResultModal extends Modal {
  constructor(app: App, private readonly plugin: SecondBrainPlugin, private readonly meeting: MeetingInfo,
              private readonly detail: string) {
    super(app);
  }

  async onOpen(): Promise<void> {
    const m = this.meeting;
    this.titleEl.setText(`Nachbereitet · ${m.title}`);
    const el = this.contentEl;
    el.addClass("sb-capture");
    const text = await this.app.vault.adapter.read(m.path);
    const info = await this.plugin.undoInfo(m.path);
    if (info?.status !== "nachbereitet") {
      el.createDiv({ text: `Keine Nachbereitung geschrieben: ${this.detail}` });
      this.buttons(el, false);
      return;
    }
    const decisions = sectionLines(text, "## Entscheidungen").filter((l) => l.startsWith("- [E]"));
    const tasks = sectionLines(text, "## Actions").filter((l) => /^- \[.\] /.test(l));
    this.list(el, `Entscheidungen (${decisions.length})`, decisions.map((l) => l.replace(/^- \[E\]\s*/, "")));
    this.list(el, `Aufgaben (${tasks.length})`, tasks.map((l) => l.replace(/^- \[.\]\s*/, "")
      .replace(/\s*➕ \d{4}-\d{2}-\d{2}/, "")));
    const events = Object.entries(info.undo?.events ?? {});
    this.list(el, "Ins Themen-Log", events.map(([slug, lines]) =>
      `${this.plugin.index.topic(slug)?.title ?? slug}: ${lines.length} Eintrag/Einträge`));
    const kopf = /^---\n([\s\S]*?)\n---/.exec(text)?.[1] ?? "";
    const pruefer = /^geprueft_von:\s*["']?([^"'\n]+?)["']?\s*$/m.exec(kopf)?.[1];
    if (pruefer) {
      el.createDiv({ cls: "sb-muted sb-hint", text: `Geprüft von ${pruefer}: Entwurf gegen das ganze Material abgeglichen.` });
    }
    el.createDiv({ cls: "sb-muted sb-hint", text: "Stimmt etwas nicht? In der Notiz korrigieren – oder alles zurücknehmen. "
      + "„Unklar“ (?) heißt: Person nicht eindeutig." });
    this.buttons(el, !!info.undo);
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private list(el: HTMLElement, title: string, items: string[]): void {
    el.createDiv({ cls: "sb-label", text: title });
    const ul = el.createEl("ul");
    if (!items.length) ul.createEl("li", { cls: "sb-muted", text: "keine" });
    for (const i of items) ul.createEl("li", { text: i });
  }

  private buttons(el: HTMLElement, canUndo: boolean): void {
    const bar = el.createDiv({ cls: "sb-buttons" });
    if (canUndo) {
      const undo = bar.createEl("button", { text: "Rückgängig machen" });
      undo.onclick = () => void this.undo(undo);
    }
    const open = bar.createEl("button", { text: "Notiz öffnen", cls: "mod-cta" });
    open.onclick = () => { this.close(); void this.plugin.openAt(this.meeting.path, null); };
    const done = bar.createEl("button", { text: "Fertig" });
    done.onclick = () => this.close();
  }

  private async undo(btn: HTMLButtonElement): Promise<void> {
    btn.disabled = true;
    let r = await this.plugin.undoWrapup(this.meeting.path, false);
    if (!r.ok && r.geaendert
        && window.confirm("Die Notiz wurde nach der Nachbereitung geändert. Trotzdem zurücknehmen? "
                          + "Deine geänderte Fassung wird gesichert.")) {
      r = await this.plugin.undoWrapup(this.meeting.path, true);
    }
    if (!r.ok) {
      btn.disabled = false;
      new Notice(`Nicht zurückgenommen: ${r.grund ?? "Fehler"}`, 8000);
      return;
    }
    new Notice("Nachbereitung zurückgenommen – Notiz wie vorher, Themen-Log bereinigt.", 6000);
    this.close();
    await this.plugin.refreshTasks();
  }
}
