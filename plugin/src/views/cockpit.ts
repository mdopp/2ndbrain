import { MarkdownRenderChild, MarkdownRenderer, Notice, setIcon } from "obsidian";
import type SecondBrainPlugin from "../main";
import {
  OwnerGroup, TaskInfo, cockpitTasks, dayLabel, daysBetween, localIsoDate, riskSummary, sortAltbestand,
  weekdayDate,
} from "../core/ansicht";

export const COCKPIT_BLOCK = "2ndbrain";
const PER_PERSON = 5;          // Nachfassen/Fragen: so viele Punkte je Person

/** Cockpit-Ansicht als Codeblock in einer Notiz:
 *
 *     ```2ndbrain
 *     aufgaben        (oder: risiken)
 *     ```
 *
 * Die Logik steckt im Plugin (core/aufgaben.ts, core/risiken.ts), nicht als JavaScript in der
 * Notiz. So kann Dataview-JavaScript aus bleiben: ein dataviewjs-Block aus einer fremden Mail
 * liefe sonst beim Anzeigen mit vollen Rechten. */
export class CockpitBlock extends MarkdownRenderChild {
  private loading = false;

  constructor(el: HTMLElement, private readonly plugin: SecondBrainPlugin, readonly view: string,
              private readonly sourcePath: string) {
    super(el);
  }

  onload(): void {
    this.plugin.cockpitBlocks.add(this);
    void this.render();
  }

  onunload(): void {
    this.plugin.cockpitBlocks.delete(this);
  }

  async render(): Promise<void> {
    const el = this.containerEl;
    el.empty();
    el.addClass("sb-cockpit");
    if (this.view === "aufgaben") await this.renderAufgaben(el);
    else if (this.view === "risiken") await this.renderRisiken(el);
    else el.createDiv({ cls: "sb-muted", text: `2ndBrain: unbekannte Ansicht „${this.view}“ – möglich: aufgaben, risiken` });
  }

  // ------------------------------------------------------------- Aufgaben

  private async renderAufgaben(el: HTMLElement): Promise<void> {
    if (!this.plugin.tasksLoaded) {
      el.createDiv({ cls: "sb-muted", text: "Aufgaben werden geladen …" });
      return;
    }
    const today = localIsoDate();
    const c = cockpitTasks(this.plugin.tasks, this.plugin.selfSlug, today);

    el.createEl("h2", { text: `Meine Aufgaben (${c.mineCount})` });
    for (const b of c.mine) {
      el.createEl("h3", { text: `${b.label} (${b.tasks.length})` });
      await this.taskList(el, b.tasks, today);
    }
    if (!c.mineCount) el.createEl("p", { text: "Nichts offen." });

    el.createEl("h2", { text: `Nachfassen – was andere zugesagt haben (${c.othersCount} bei ${c.others.length} Personen)` });
    await this.perPerson(el, c.others, "", today);

    el.createEl("h2", { text: `Fragen (${c.questionsCount})` });
    await this.perPerson(el, c.questions, "ohne Adressat", today);

    const alt = sortAltbestand(this.plugin.index.altbestand());
    el.createEl("h2", { text: `Altbestand – ungeprüft (${alt.reduce((n, a) => n + a.altbestand, 0)} Punkte `
      + `in ${alt.length} Themen)` });
    el.createEl("p", { text: "Der nächste Termin zum Thema legt sie zum Abhaken vor. Ohne Termin: im Thema durchgehen." });
    const body = this.table(el, ["Thema", "ungeprüft", "nächster Termin"]);
    for (const a of alt) {
      const tr = body.createEl("tr");
      this.link(tr.createEl("td"), a.path, a.title);
      tr.createEl("td", { text: String(a.altbestand) });
      tr.createEl("td", { text: a.nextMeeting ? weekdayDate(a.nextMeeting) : "noch keiner vorbereitet" });
    }

    el.createEl("h2", { text: `Person unklar (${c.unclear.length})` });
    const byFile = new Map<string, TaskInfo[]>();
    for (const t of c.unclear) {
      const list = byFile.get(t.path ?? "");
      if (list) list.push(t);
      else byFile.set(t.path ?? "", [t]);
    }
    for (const [path, ts] of byFile) {
      const h = el.createEl("h4");
      if (path) this.link(h, path, path.split("/").pop()?.replace(/\.md$/, "") ?? path);
      else h.setText("ohne Fundstelle");
      await this.taskList(el, ts, today, false);
    }
  }

  private async perPerson(el: HTMLElement, groups: OwnerGroup[], noneLabel: string, today: string): Promise<void> {
    for (const g of groups) {
      const h = el.createEl("h4");
      const person = `entities/people/${g.owner}.md`;
      if (g.owner) this.link(h, person, this.plugin.index.personName(g.owner));
      else h.appendText(noneLabel);
      h.appendText(` · ${g.tasks.length} offen${g.overdue ? `, ${g.overdue} überfällig` : ""}`);
      await this.taskList(el, g.tasks.slice(0, PER_PERSON), today);
      if (g.tasks.length > PER_PERSON) {
        const p = el.createEl("p", { cls: "sb-more" });
        p.appendText(`… und ${g.tasks.length - PER_PERSON} weitere`);
        if (g.owner) {
          p.appendText(" – alle auf ");
          this.link(p, person, this.plugin.index.personName(g.owner));
        }
      }
    }
  }

  /** Punkte mit Kaestchen: Abhaken schreibt direkt in die Quelle - nur, wenn die Zeile noch
   *  dieser Punkt ist (core/aufgaben.ts). */
  private async taskList(el: HTMLElement, tasks: TaskInfo[], today: string, showSource = true): Promise<void> {
    const ul = el.createEl("ul", { cls: "sb-ctasks" });
    for (const t of tasks) {
      const late = !!t.due && t.due < today;
      const li = ul.createEl("li", { cls: `sb-ctask${late ? " sb-overdue" : ""}` });
      const box = li.createEl("input", { type: "checkbox", cls: "task-list-item-checkbox" });
      box.onclick = async (e) => {
        e.stopPropagation();
        box.disabled = true;
        const r = await this.plugin.completeTask(t);
        if (!r.ok) {
          box.checked = false;
          box.disabled = false;
          new Notice(`Nicht abgehakt: ${r.grund ?? "Fehler"}`);
        }
      };
      const text = li.createDiv({ cls: "sb-ctask-text" });
      await MarkdownRenderer.render(this.plugin.app, t.text, text, this.sourcePath, this);
      const meta: string[] = [];
      if (t.due) meta.push(late ? `seit ${daysBetween(t.due, today)} T überfällig` : `fällig ${dayLabel(t.due, today)}`);
      else if (t.created) meta.push(`seit ${daysBetween(t.created, today)} T offen`);
      const m = text.createDiv({ cls: "sb-ctask-meta", text: meta.join(" · ") });
      if (showSource && t.path) {
        if (meta.length) m.appendText(" · ");
        const a = m.createEl("a", { cls: "sb-link", text: t.path.split("/").pop()?.replace(/\.md$/, "") ?? t.path,
                                    attr: { title: "Zur Fundstelle" } });
        a.onclick = (e) => { e.preventDefault(); void this.plugin.openAt(t.path!, t.line); };
      }
    }
  }

  // -------------------------------------------------------------- Risiken

  private async renderRisiken(el: HTMLElement): Promise<void> {
    const r = this.plugin.risks;
    if (!r) {
      el.createDiv({ cls: "sb-muted", text: "Risiken werden geladen …" });
      if (!this.loading) {
        this.loading = true;
        // Ein Lesefehler darf die Anzeige nicht bei "wird geladen" stehen lassen
        void this.plugin.loadRisks().catch(() => undefined).then(() => {
          this.loading = false;
          if (this.plugin.risks) void this.render();
          else {
            el.empty();
            el.createDiv({ cls: "sb-muted", text: "Risiken nicht lesbar – Themen-Seiten prüfen (Event Log)." });
          }
        });
      }
      return;
    }
    const s = riskSummary(r.rows);
    const head = el.createDiv({ cls: "sb-chead" });
    const p = head.createEl("p");
    p.createEl("strong", { text: `${s.total} Risiken` });
    p.appendText(` in ${s.orte} Projekten/Gremien · `);
    p.createEl("strong", { text: `${s.aktiv} aktiv` });
    p.appendText(` (≤ ${r.window} Tage) · ${s.total - s.aktiv} älter`);
    const reload = head.createEl("button", { cls: "clickable-icon", attr: { "aria-label": "Neu laden" } });
    setIcon(reload, "refresh-cw");
    reload.onclick = async () => {
      reload.disabled = true;
      await this.plugin.loadRisks();
      await this.render();
    };
    const body = this.table(el, ["Alter", "Datum", "Status", "Art", "Projekt", "Risiko", "Quelle"]);
    for (const row of r.rows) {
      const tr = body.createEl("tr");
      tr.createEl("td", { text: `${row.alter} T` });
      tr.createEl("td", { text: row.datum });
      tr.createEl("td", { text: row.aktiv ? "🟡 aktiv" : "⚪ älter" });
      tr.createEl("td", { text: row.art });
      this.link(tr.createEl("td"), row.pfad, row.titel);
      await MarkdownRenderer.render(this.plugin.app, row.text, tr.createEl("td", { cls: "sb-ctext" }), this.sourcePath, this);
      const q = tr.createEl("td");
      if (row.quelle) this.link(q, row.quelle, row.quelle);
    }
  }

  // ------------------------------------------------------------- Bausteine

  private table(el: HTMLElement, headers: string[]): HTMLElement {
    const table = el.createEl("table", { cls: "sb-ctable" });
    const tr = table.createEl("thead").createEl("tr");
    for (const h of headers) tr.createEl("th", { text: h });
    return table.createEl("tbody");
  }

  private link(parent: HTMLElement, target: string, text: string): void {
    const a = parent.createEl("a", { text, cls: "sb-link sb-clink", attr: { title: target } });
    a.onclick = (e) => {
      e.preventDefault();
      void this.plugin.app.workspace.openLinkText(target, this.sourcePath, e.ctrlKey || e.metaKey);
    };
  }
}
