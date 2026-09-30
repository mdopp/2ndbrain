import { ItemView, Notice, WorkspaceLeaf, setIcon } from "obsidian";
import type SecondBrainPlugin from "../main";
import type { TopicTarget } from "./themen";
import {
  MeetingInfo, PHASE_LABEL, TaskInfo, TopicInfo, dayLabel, daysBetween, followUps, healthEmoji,
  isPersonMeeting,
  localIsoDate, meetingPhase, meetingsOn, missingNotes, myTasks, nextMeetingDay, pendingWrapups,
  radarAttention, radarCounts, shortReason, taskBuckets, weekdayDate,
} from "../core/ansicht";

export const VIEW_TYPE_TODAY = "2ndbrain-today";

const MAX_MINE = 6;
const MAX_RADAR = 6;
const MAX_BACKLOG = 25;
const BACKLOG_DAYS = 3650;         // Nacharbeit: alles Vergangene, was noch offen in active-meetings/ liegt
const TASKS_NOTE = "01_Aufgaben.md";
const RADAR_NOTE = "00_Themen-Radar.base";
// Phasen, die nichts Besonderes sind - kein Chip
const QUIET_PHASES = new Set(["vorbereitet", "vorbereiten"]);

/** Tagesstart, in der Reihenfolge, in der man es braucht: wo stehen die Themen,
 *  was ist meins, welche Termine kommen - und zugeklappt, was nachzuarbeiten ist.
 *  Keine Modell-Aufrufe: alles aus dem Vault, am Desktop dazu "ohne Thema" aus der Engine. */
export class TodayView extends ItemView {
  constructor(leaf: WorkspaceLeaf, private readonly plugin: SecondBrainPlugin) {
    super(leaf);
  }

  getViewType(): string { return VIEW_TYPE_TODAY; }
  getDisplayText(): string { return "Heute"; }
  getIcon(): string { return "calendar-check"; }

  async onOpen(): Promise<void> {
    await this.render();
  }

  async render(): Promise<void> {
    const root = this.contentEl;
    root.empty();
    root.addClass("sb-today");
    const today = localIsoDate();
    const meetings = await this.plugin.index.meetings(today);
    const topics = this.plugin.index.topics();
    const bySlug = new Map(topics.map((t) => [t.slug, t]));

    this.renderHeader(root, today);
    this.renderJobs(root);
    this.renderMissing(root, meetings, today);
    this.renderRadar(root, topics);
    this.renderMine(root, today);
    this.renderMeetings(root, meetings, today, bySlug);
    this.renderBacklog(root, meetings, today);
  }

  // ------------------------------------------------------------ Bausteine

  /** Aufklappbarer Abschnitt; der Zustand bleibt in den Einstellungen. */
  private section(root: HTMLElement, key: string, title: string): { sum: HTMLElement; body: HTMLElement } {
    const det = root.createEl("details", { cls: "sb-section" });
    det.open = !this.plugin.settings.collapsed[key];
    det.addEventListener("toggle", () => {
      this.plugin.settings.collapsed[key] = !det.open;
      void this.plugin.saveSettings();
    });
    const sum = det.createEl("summary", { cls: "sb-summary" });
    sum.createSpan({ cls: "sb-summary-title", text: title });
    return { sum, body: det.createDiv({ cls: "sb-section-body" }) };
  }

  /** Knopf in einer Abschnitts-Kopfzeile - klappt den Abschnitt nicht um. */
  private headButton(sum: HTMLElement, text: string, onClick: () => void): void {
    const b = sum.createEl("button", { text, cls: "sb-btn-small sb-head-btn" });
    b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); onClick(); };
  }

  private iconButton(parent: HTMLElement, icon: string, label: string, onClick: () => void): void {
    const b = parent.createEl("button", { cls: "sb-icon-btn clickable-icon", attr: { "aria-label": label } });
    setIcon(b, icon);
    b.onclick = (e) => { e.preventDefault(); e.stopPropagation(); onClick(); };
  }

  private link(parent: HTMLElement, path: string, text: string, cls = ""): HTMLElement {
    const a = parent.createEl("a", { text, cls: `sb-link ${cls}`.trim(), attr: { title: text } });
    a.onclick = (e) => {
      e.preventDefault();
      this.app.workspace.openLinkText(path, "", e.ctrlKey || e.metaKey);
    };
    return a;
  }

  // ----------------------------------------------------------------- Kopf

  private renderHeader(root: HTMLElement, today: string): void {
    const head = root.createDiv({ cls: "sb-head" });
    head.createEl("h3", { text: `Heute · ${weekdayDate(today)}` });
    const tools = head.createDiv({ cls: "sb-tools" });
    if (this.plugin.isDesktop) {
      this.iconButton(tools, "refresh-cw", this.plugin.engine.busy ? "Automatik läuft …" : "Automatik jetzt",
                      () => void this.plugin.runAutomatik(true));
    }
    this.iconButton(tools, "search", "Sofortsuche: Thema oder Person", () => this.plugin.openQuickLook());
    this.iconButton(tools, "help-circle", "Anleitung: so funktioniert 2ndBrain", () => void this.plugin.openHelp());

    const status = root.createDiv({ cls: "sb-status" });
    const llm = this.plugin.llmState;
    status.createSpan({ cls: `sb-dot ${llm.ok ? "sb-ok" : "sb-off"}` });
    status.createSpan({ text: llm.ok ? "Modell bereit" : `Modell aus (${llm.detail})` });
    const last = this.plugin.lastAuto;
    if (last) {
      const hh = last.at.toTimeString().slice(0, 5);
      status.createSpan({ text: ` · Automatik ${hh}${last.result?.ok === false ? " mit Fehlern" : ""}` });
    }
  }

  /** Nachbereitungen im Hintergrund: wartet / laeuft / fertig (mit Ergebnis) / Fehler - davor, was auf
   *  einen Termin wartet, der gerade nachbereitet wird. */
  private renderJobs(root: HTMLElement): void {
    const wartend = this.plugin.settings.wartend;
    if (!this.plugin.jobs.length && !wartend.length) return;
    const sec = root.createDiv({ cls: "sb-jobs" });
    for (const w of wartend) {
      const row = sec.createDiv({ cls: "sb-row sb-job sb-job-wartet" });
      setIcon(row.createSpan({ cls: "sb-icon" }), "clock");
      row.createSpan({ text: `${w.art === "notizen" ? "Notizen warten" : "Änderung wartet"}`
        + `${w.nachbereiten ? ", dann nachbereiten" : ""}: ` });
      this.link(row, w.pfad, w.titel, "sb-grow");
    }
    const icon = { "wartet": "clock", "läuft": "loader", "fertig": "check", "fehler": "x" } as const;
    const label = { "wartet": "Nachbereitung wartet", "läuft": "Nachbereitung läuft",
                    "fertig": "Nachbereitet", "fehler": "Nicht nachbereitet" } as const;
    for (const job of this.plugin.jobs) {
      const row = sec.createDiv({ cls: `sb-row sb-job sb-job-${job.state === "läuft" ? "laeuft" : job.state}` });
      setIcon(row.createSpan({ cls: "sb-icon" }), icon[job.state]);
      row.createSpan({ text: `${label[job.state]}: ` });
      this.link(row, job.meeting.path, job.meeting.title, "sb-grow");
      if (job.state === "fehler" && job.detail) row.createSpan({ cls: "sb-muted", text: job.detail });
      if (job.state === "fertig") {
        const b = row.createEl("button", { text: "Ergebnis", cls: "sb-btn-small" });
        b.onclick = () => this.plugin.showResult(job);
      }
      if (job.state === "fertig" || job.state === "fehler") {
        this.iconButton(row, "x", "Ausblenden", () => this.plugin.dismissJob(job));
      }
    }
  }

  // ---------------------------------------------------------------- Radar

  private renderRadar(root: HTMLElement, topics: TopicInfo[]): void {
    const c = radarCounts(topics);
    const { sum, body } = this.section(root, "radar", "Themen-Radar");
    sum.createSpan({ cls: "sb-summary-meta", text: `🔴 ${c.red}  🟡 ${c.yellow}  🟢 ${c.green}` });
    this.headButton(sum, "Radar", () => void this.app.workspace.openLinkText(RADAR_NOTE, "", false));
    const hot = radarAttention(topics, MAX_RADAR);
    if (!hot.length) {
      body.createDiv({ cls: "sb-muted", text: "Alles grün." });
      return;
    }
    for (const t of hot) {
      const row = body.createDiv({ cls: "sb-line" });
      row.createSpan({ cls: "sb-health", text: healthEmoji(t.health) });
      this.link(row, t.path, t.title, "sb-name");
      row.createSpan({ cls: "sb-muted sb-ellipsis", text: shortReason(t), attr: { title: t.reason } });
    }
    const rest = c.red + c.yellow - hot.length;
    if (rest > 0) body.createDiv({ cls: "sb-more", text: `… und ${rest} weitere gelbe – im Radar` });
  }

  // ------------------------------------------------------- Meine Aufgaben

  private renderMine(root: HTMLElement, today: string): void {
    const { list, overdue } = myTasks(this.plugin.tasks, this.plugin.selfSlug, today);
    const { sum, body } = this.section(root, "mine", "Meine Aufgaben");
    sum.createSpan({ cls: `sb-summary-meta${overdue ? " sb-alert" : ""}`,
                     text: `${list.length}${overdue ? ` · ${overdue} überfällig` : ""}` });
    this.headButton(sum, "Alle", () => void this.app.workspace.openLinkText(TASKS_NOTE, "", false));
    if (!list.length) {
      body.createDiv({ cls: "sb-muted", text: "Nichts offen." });
      return;
    }
    for (const g of taskBuckets(list, today, MAX_MINE)) {
      body.createDiv({ cls: "sb-group", text: g.label });
      for (const t of g.tasks) this.renderMyTask(body, t, today);
    }
    if (list.length > MAX_MINE) {
      const more = body.createDiv({ cls: "sb-more sb-link", text: `… und ${list.length - MAX_MINE} weitere` });
      more.onclick = () => void this.app.workspace.openLinkText(TASKS_NOTE, "", false);
    }
  }

  private renderMyTask(parent: HTMLElement, t: TaskInfo, today: string): void {
    const late = !!t.due && t.due < today;
    const row = parent.createDiv({ cls: `sb-task-row${late ? " sb-overdue" : ""}` });
    const box = row.createEl("input", { type: "checkbox", cls: "task-list-item-checkbox" });
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
    const main = row.createDiv({ cls: "sb-task-main" });
    const text = main.createDiv({ cls: "sb-task-text sb-link", text: t.text, attr: { title: t.text } });
    text.onclick = () => { if (t.path) void this.plugin.openAt(t.path, t.line); };
    const bits: string[] = [];
    const topic = t.topics[0] ? this.plugin.index.topic(t.topics[0])?.title ?? t.topics[0] : "";
    if (topic) bits.push(topic);
    if (t.due) bits.push(late ? `seit ${daysBetween(t.due, today)} T überfällig` : `fällig ${dayLabel(t.due, today)}`);
    else if (t.created) bits.push(`seit ${daysBetween(t.created, today)} T offen`);
    main.createDiv({ cls: "sb-task-meta", text: bits.join(" · ") });
  }

  // -------------------------------------------------------------- Termine

  private renderMeetings(root: HTMLElement, meetings: MeetingInfo[], today: string,
                         topics: Map<string, TopicInfo>): void {
    const todays = meetingsOn(meetings, today).filter((m) => !m.skip);
    if (todays.length) {
      const { sum, body } = this.section(root, "termine-heute", "Termine heute");
      sum.createSpan({ cls: "sb-summary-meta", text: String(todays.length) });
      for (const m of todays) this.renderMeeting(body, m, today, topics, true);
    }
    const next = nextMeetingDay(meetings, today);
    if (next) {
      const list = meetingsOn(meetings, next).filter((m) => !m.skip && m.status !== "entfallen");
      const { sum, body } = this.section(root, "termine-naechste", `Termine ${dayLabel(next, today)}`);
      sum.createSpan({ cls: "sb-summary-meta", text: String(list.length) });
      for (const m of list) this.renderMeeting(body, m, today, topics, false);
    }
    if (!todays.length && !next) root.createDiv({ cls: "sb-muted sb-pad", text: "Keine Termine in den nächsten Tagen." });
  }

  private renderMeeting(parent: HTMLElement, m: MeetingInfo, today: string,
                        topics: Map<string, TopicInfo>, isToday: boolean): void {
    const card = parent.createDiv({ cls: "sb-meeting" });
    const top = card.createDiv({ cls: "sb-line" });
    top.createSpan({ cls: "sb-time", text: m.time || "–" });
    this.link(top, m.path, m.title, "sb-name");
    const phase = meetingPhase(m, today);
    if (m.nachbereiten === "angefordert" && phase !== "nachbereitet") {
      top.createSpan({ cls: "sb-chip sb-phase-vorgemerkt", text: "vorgemerkt",
                       attr: { title: "Zum Nachbereiten vorgemerkt – der Desktop erledigt es beim nächsten Lauf" } });
    } else if (!QUIET_PHASES.has(phase)) {
      top.createSpan({ cls: `sb-chip sb-phase-${phase}`, text: PHASE_LABEL[phase] });
    }
    if (isToday && phase !== "nachbereitet" && phase !== "entfallen") {
      this.iconButton(top, "pencil", "Notizen / nacherfassen", () => void this.plugin.openCapture(m.path));
    }

    // Zweite Zeile: Themen mit Ampel (oder "Thema wählen"), Altbestand, Nachfassen
    const ts = (m.topics ?? (m.topic ? [m.topic] : []))
      .map((s) => topics.get(s)).filter((x): x is TopicInfo => !!x);
    const fus = followUps(this.plugin.tasks, m.persons, this.plugin.selfSlug, today, 99);
    const meta = card.createDiv({ cls: "sb-meeting-meta" });
    const pick = () => this.plugin.openTopicPicker({ kind: "note", path: m.path });
    const desk = this.plugin.isDesktop;       // Thema und Gegenueber setzt die Engine
    if (!ts.length && isPersonMeeting(m.title, m.type)) {
      // Jourfix/1:1: die Person statt eines Themas
      const others = m.persons.filter((p) => p !== this.plugin.selfSlug);
      if (!others.length && desk) {
        const b = meta.createEl("button", { text: "Mit wem?", cls: "sb-btn-small sb-choose" });
        b.onclick = () => void this.plugin.openPersonPicker(m.path);
      }
      for (const p of others.slice(0, 2)) {
        const span = meta.createSpan({ cls: "sb-topic" });
        span.createSpan({ text: "👤 " });
        this.link(span, `entities/people/${p}.md`, this.plugin.index.personName(p));
      }
      const alt = this.plugin.tasks.filter((t) => t.pruefen && !!t.owner && others.includes(t.owner)).length;
      if (alt) meta.createSpan({ cls: "sb-chip sb-chip-alt", text: `${alt} Altbestand` });
    } else if (!ts.length && desk) {
      const b = meta.createEl("button", { text: "Thema wählen", cls: "sb-btn-small sb-choose" });
      b.onclick = pick;
    }
    for (const t of ts.slice(0, 2)) {
      const span = meta.createSpan({ cls: "sb-topic" });
      span.createSpan({ text: `${healthEmoji(t.health)} ` });
      this.link(span, t.path, t.title);
    }
    if (ts.length > 2) meta.createSpan({ cls: "sb-muted", text: `+${ts.length - 2}` });
    const alt = ts.reduce((n, t) => n + t.altbestand, 0);
    if (alt) meta.createSpan({ cls: "sb-chip sb-chip-alt", text: `${alt} Altbestand` });
    if (fus.length) meta.createSpan({ cls: "sb-chip", text: `Nachfassen ${fus.length}` });
    if (ts.length && desk) this.iconButton(meta, "tag", "Thema ändern", pick);

    if (!isToday || !fus.length) return;
    const list = card.createDiv({ cls: "sb-followups" });
    for (const f of fus.slice(0, 3)) {
      const row = list.createDiv({ cls: `sb-fu${f.overdue ? " sb-overdue" : ""}` });
      setIcon(row.createSpan({ cls: "sb-icon" }), f.kind === "frage" ? "help-circle" : "check-square");
      row.createSpan({ cls: "sb-ellipsis", text: `${this.plugin.index.personName(f.person)}: ${f.task.text}`,
                       attr: { title: f.task.text } });
      if (f.task.path) row.onclick = () => this.plugin.openAt(f.task.path!, f.task.line);
    }
  }

  // ------------------------------------------------------------ Nacharbeit

  /** Vergangene Termine ohne Notizen - ganz oben: ohne Notizen gibt es keine Nachbereitung und
   *  keine Fragen. Die Liste soll leer sein: Notizen nachtragen oder den Termin ueberspringen. */
  private renderMissing(root: HTMLElement, meetings: MeetingInfo[], today: string): void {
    const missing = missingNotes(meetings, today, BACKLOG_DAYS);
    if (!missing.length) return;
    const { sum, body } = this.section(root, "ohne-notizen", "Ohne Notizen");
    sum.createSpan({ cls: "sb-summary-meta sb-alert", text: `${missing.length}` });
    body.createDiv({ cls: "sb-hint sb-muted",
                     text: "Notizen nachtragen oder überspringen – ohne Notizen keine Nachbereitung und keine Fragen." });
    for (const m of missing.slice(0, MAX_BACKLOG)) {
      const row = body.createDiv({ cls: "sb-line" });
      row.createSpan({ cls: "sb-time", text: dayLabel(m.date, today) });
      this.link(row, m.path, m.title, "sb-name");
      this.iconButton(row, "pencil", "Nacherfassen", () => void this.plugin.openCapture(m.path));
      this.iconButton(row, "skip-forward", "Überspringen – keine Notizen nötig", () => void this.skip(m));
    }
    if (missing.length > MAX_BACKLOG) body.createDiv({ cls: "sb-more", text: `… und ${missing.length - MAX_BACKLOG} weitere` });
  }

  private renderBacklog(root: HTMLElement, meetings: MeetingInfo[], today: string): void {
    const inWork = new Set([...this.plugin.jobs.filter((j) => j.state === "wartet" || j.state === "läuft")
      .map((j) => j.meeting.path), ...this.plugin.settings.wartend.filter((w) => w.nachbereiten).map((w) => w.pfad)]);
    const pending = pendingWrapups(meetings, today, BACKLOG_DAYS).filter((m) => m.date < today && !inWork.has(m.path));
    const open = this.plugin.openTopics;
    if (!pending.length && !open.length) return;

    const { sum, body } = this.section(root, "nacharbeit", "Nacharbeit");
    sum.createSpan({ cls: "sb-summary-meta",
                     text: [pending.length ? `${pending.length} nachbereiten` : "",
                            open.length ? `${open.length} ohne Thema` : ""].filter(Boolean).join(" · ") });
    if (open.length) {
      body.createDiv({ cls: "sb-group", text: "Ohne Thema – nächste 14 Tage" });
      for (const s of open.slice(0, MAX_BACKLOG)) {
        const target: TopicTarget = s.note ? { kind: "note", path: s.note }
          : { kind: "serie", key: s.reihe, title: s.titel };
        const row = body.createDiv({ cls: "sb-line" });
        row.createSpan({ cls: "sb-time", text: dayLabel(s.naechster, today) });
        if (s.note) this.link(row, s.note, s.titel, "sb-name");
        else row.createSpan({ cls: "sb-name sb-muted", text: s.titel,
                              attr: { title: `${s.titel} – die Notiz entsteht kurz vor dem Termin; `
                                + "ein Thema gilt schon jetzt für die ganze Reihe" } });
        // Reihe: fuer alle Termine merken; Einzeltermin (steht erst mit Notiz hier): nur die Notiz
        const forSeries = s.wiederkehrend !== false;
        const scope = forSeries ? "für die Reihe" : "für diesen Termin";
        const best = s.vorschlaege[0];
        if (best && best.score >= 0.5) {
          const q = row.createEl("button", { text: `→ ${best.titel}`, cls: "sb-btn-small sb-suggest",
                                             attr: { title: `${best.gruende.join(" · ")} – ${scope} übernehmen` } });
          q.onclick = () => void this.plugin.setTopics(target, [best.slug], forSeries);
        }
        this.iconButton(row, "tag", "Thema wählen", () => this.plugin.openTopicPicker(target));
        this.iconButton(row, "circle-slash", `Kein Thema nötig – ${scope} merken`,
                        () => void this.plugin.setTopics(target, [], forSeries));
      }
    }
    if (pending.length) {
      body.createDiv({ cls: "sb-group", text: "Notizen da – nachbereiten" });
      for (const m of pending) {
        const row = body.createDiv({ cls: "sb-line" });
        row.createSpan({ cls: "sb-time", text: dayLabel(m.date, today) });
        this.link(row, m.path, m.title, "sb-name");
        this.iconButton(row, "pencil", "Nacherfassen / nachbereiten", () => void this.plugin.openCapture(m.path));
      }
    }
  }

  private async skip(m: MeetingInfo): Promise<void> {
    const r = await this.plugin.setSkip(m.path, true, m.title);
    if (!r.ok) {
      new Notice(`Nicht geändert: ${r.grund ?? "Fehler"}`);
      return;
    }
    if (r.wartet) {
      new Notice(`„${m.title}“ wird gerade nachbereitet – „übersprungen“ kommt danach dazu.`);
      return;
    }
    new Notice(createFragment((f) => {
      f.appendText(`„${m.title}“: übersprungen · `);
      const undo = f.createEl("a", { text: "rückgängig", href: "#" });
      undo.onclick = async (e) => {
        e.preventDefault();
        await this.plugin.setSkip(m.path, false);
        await this.plugin.refreshTasks();
      };
    }), 8000);
    await this.plugin.refreshTasks();
  }
}
