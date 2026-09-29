import { ItemView, MarkdownRenderer, Menu, WorkspaceLeaf, setIcon } from "obsidian";
import type SecondBrainPlugin from "../main";
import type { ChatRequest } from "../core/chat";
import { exampleTopics } from "../core/ansicht";

export const VIEW_TYPE_CHAT = "2ndbrain-chat";

/** Rezept aus `.2ndbrain/chat-skills` (gelesen in core/rezepte.ts). */
export interface ChatSkill { name: string; label: string; beschreibung: string; ziel: string; quelle: string }

interface Bezug { themen: string[]; personen: string[]; termin: string | null; anzeige: string[]; atlas?: string[];
                  /** "aus der Frage" | "aus der offenen Notiz" | "aus der vorigen Antwort" */
                  herkunft?: string }

/** Eine offene Frage im Frage-Modus (Skill "Offene Fragen", `kanon_vorschlaege.py`). */
interface Karte { id: string; typ: string; markdown: string; optionen: { key: string; label: string }[]; offen: number }

/** Antwort des Chats (core/chat.ts) oder, im Frage-Modus, von `2ndbrain frage --json`. */
export interface ChatAnswer {
  ok: boolean;
  antwort?: string;
  grund?: string;
  ausschnitt?: string;         // wenn das Modell fehlt: was es bekommen haette
  bezug?: Bezug;
  quellen?: string[];
  dauer_s?: number;
  karte?: Karte | null;        // Frage-Modus: naechste Frage (null = keine mehr)
  ueberspringen?: string[];    // im Gespraech mit "später" uebergangen
}

interface Turn { rolle: "nutzer" | "assistent"; text: string; meta?: string; fehler?: boolean; karte?: Karte }

/** Das Gespraech - beim Plugin, nicht in der Ansicht: es uebersteht den Wechsel klein <-> gross. */
export interface ChatState { turns: Turn[]; bezug: Bezug | null; karte: Karte | null; skip: string[]; busy: boolean }

export function newChatState(): ChatState {
  return { turns: [], bezug: null, karte: null, skip: [], busy: false };
}

const FRAGEN_SKILL: ChatSkill = { name: "offene-fragen", label: "Offene Fragen", beschreibung: "", ziel: "keins",
                                  quelle: "fragen" };
const PLACEHOLDER = "Frage stellen … (Enter sendet)";
const PLACEHOLDER_KARTE = "Einordnung oder Anmerkung zur Frage … (Enter speichert)";
const MAX_INPUT_PX = 160;          // so hoch waechst das Eingabefeld hoechstens

/** Pfade, deren Notiz ein Bezug sein kann: Thema, Person, Reihe, Termin. */
const SCOPE_RE = /^(entities\/(projects|people|forums)\/|active-meetings\/|archive\/meetings\/)/;


/** "Fragen an den Vault": Chat mit dem lokalen Modell. Der Code (core/chat.ts) sucht den
 *  Ausschnitt aus vorhandenen Ergebnissen, das Modell formuliert nur daraus. Klein in der
 *  Seitenleiste, auf Knopfdruck gross im Hauptbereich neben der Notiz. */
export class ChatView extends ItemView {
  private useActive = true;
  private lastFile: string | null = null;
  private listEl!: HTMLElement;
  private inputEl!: HTMLTextAreaElement;
  private barEl!: HTMLElement;
  private skills: ChatSkill[] = [];

  constructor(leaf: WorkspaceLeaf, private readonly plugin: SecondBrainPlugin) {
    super(leaf);
  }

  getViewType(): string { return VIEW_TYPE_CHAT; }
  getDisplayText(): string { return "Fragen"; }
  getIcon(): string { return "message-circle"; }

  private get s(): ChatState { return this.plugin.chatState; }

  async onOpen(): Promise<void> {
    const root = this.contentEl;
    root.empty();
    root.addClass("sb-chat");
    this.listEl = root.createDiv({ cls: "sb-chat-list" });
    this.listEl.addEventListener("click", (e) => this.followLink(e));
    this.barEl = root.createDiv({ cls: "sb-chat-bar" });
    const form = root.createDiv({ cls: "sb-chat-form" });
    const vorlagen = form.createEl("button", { text: "Vorlagen ▾", cls: "sb-btn-small sb-chat-vorlagen",
                                               attr: { "aria-label": "Rezepte und Bilder" } });
    vorlagen.onclick = (e) => this.showTemplates(e);
    this.inputEl = form.createEl("textarea", { attr: { rows: "1", placeholder: PLACEHOLDER } });
    this.inputEl.addEventListener("input", () => this.grow());
    this.inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void this.ask(this.inputEl.value);
      }
    });
    const send = form.createEl("button", { cls: "sb-icon-btn sb-chat-send", attr: { "aria-label": "Fragen" } });
    setIcon(send, "send");
    send.onclick = () => void this.ask(this.inputEl.value);
    this.registerEvent(this.app.workspace.on("active-leaf-change", () => this.renderBar()));
    this.setPlaceholder();
    this.renderBar();
    this.renderTurns();
    this.skills = (await this.plugin.chatSkills())
      .filter((s) => s.quelle !== "fragen" || this.plugin.isDesktop);     // Frage-Modus schreibt ins Atlas-Repo
  }

  async onClose(): Promise<void> {
    this.contentEl.empty();
  }

  /** Alles neu zeichnen (auch aus einer anderen Chat-Ansicht heraus, nach einer Antwort). */
  refresh(): void {
    this.setPlaceholder();
    this.renderTurns();
    this.renderBar();
  }

  private grow(): void {
    this.inputEl.setCssStyles({ height: "auto" });
    this.inputEl.setCssStyles({ height: `${Math.min(this.inputEl.scrollHeight, MAX_INPUT_PX)}px` });
  }

  /** Rezepte und Bilder als Menue - statt elf Knoepfen im Kopf. */
  private showTemplates(e: MouseEvent): void {
    const menu = new Menu();
    const bilder = this.skills.filter((s) => s.name.startsWith("bild-"));
    for (const s of this.skills.filter((x) => !x.name.startsWith("bild-"))) {
      menu.addItem((i) => i.setTitle(s.label).setIcon("message-square").onClick(() => void this.ask(this.inputEl.value, s)));
    }
    if (bilder.length) menu.addSeparator();
    for (const s of bilder) {
      menu.addItem((i) => i.setTitle(`Bild: ${s.label.replace(/^Bild:\s*/, "")}`).setIcon("image")
        .onClick(() => void this.ask(this.inputEl.value, s)));
    }
    if (!this.skills.length) menu.addItem((i) => i.setTitle("Keine Vorlagen gefunden").setDisabled(true));
    menu.showAtMouseEvent(e);
  }

  /** Aktive Notiz als Bezug, solange der Nutzer ihn nicht weggeklickt hat. */
  private activeScopeFile(): string | null {
    const f = this.app.workspace.getActiveFile();
    const path = f && SCOPE_RE.test(f.path) ? f.path : null;
    if (path !== this.lastFile) {
      this.lastFile = path;
      this.useActive = true;                  // neue Notiz: Bezug wieder an
    }
    return this.useActive ? path : null;
  }

  /** Eine schmale Zeile ueber der Eingabe: Bezug als Chip, rechts Neues Gespraech und klein/gross. */
  private renderBar(): void {
    this.barEl.empty();
    const f = this.activeScopeFile();
    if (f) {
      const chip = this.barEl.createDiv({ cls: "sb-chat-chip", attr: { title: f } });
      chip.createSpan({ cls: "sb-muted", text: "Bezug:" });
      chip.createSpan({ cls: "sb-chat-scope-name", text: f.split("/").pop()?.replace(/\.md$/, "") ?? f });
      const x = chip.createEl("button", { cls: "sb-icon-btn", attr: { "aria-label": "Ohne diese Notiz fragen" } });
      setIcon(x, "x");
      x.onclick = () => { this.useActive = false; this.renderBar(); };
    } else if (this.s.bezug?.anzeige?.length) {
      this.barEl.createDiv({ cls: "sb-chat-chip sb-muted", text: `Gespräch über: ${this.s.bezug.anzeige.join(", ")}` });
    }
    this.barEl.createDiv({ cls: "sb-chat-spacer" });
    const reset = this.barEl.createEl("button", { cls: "sb-icon-btn", attr: { "aria-label": "Neues Gespräch" } });
    setIcon(reset, "rotate-ccw");
    reset.onclick = () => this.reset();
    const gross = this.plugin.chatIsLarge(this.leaf);
    const size = this.barEl.createEl("button", { cls: "sb-icon-btn",
                                                 attr: { "aria-label": gross ? "Kleiner (Seitenleiste)" : "Größer (neben der Notiz)" } });
    setIcon(size, gross ? "minimize-2" : "maximize-2");
    size.disabled = this.s.busy;
    size.onclick = () => void this.plugin.toggleChatSize();
  }

  private reset(): void {
    Object.assign(this.s, { turns: [], bezug: null, karte: null, skip: [] });
    this.refresh();
  }

  private setKarte(k: Karte | null): void {
    this.s.karte = k;
    this.setPlaceholder();
  }

  private setPlaceholder(): void {
    if (this.inputEl) this.inputEl.placeholder = this.s.karte ? PLACEHOLDER_KARTE : PLACEHOLDER;
  }

  /** Knopf unter einer Frage-Karte: Antwort an die Engine, die naechste Frage kommt zurueck. */
  private answerCard(key: string, label: string): void {
    if (!this.s.karte) return;
    void this.ask("", FRAGEN_SKILL, { karte: { id: this.s.karte.id, key }, anzeige: `→ ${label}` });
  }

  private renderTurns(): void {
    this.listEl.empty();
    if (!this.s.turns.length) {
      const empty = this.listEl.createDiv({ cls: "sb-chat-empty" });
      empty.createDiv({ cls: "sb-muted", text: "Antworten nur aus deinem Vault, mit Links zu den Quellen." });
      // Beispiele aus dem Vault: Themen mit dem naechsten Termin (keine festen Namen im Code)
      const [a, b] = exampleTopics(this.plugin.index.topics());
      const examples = ["Was habe ich offen?",
                        a ? `Wo steht ${a}?` : "Wo steht mein wichtigstes Thema?",
                        b ? `Was ist seit letzter Woche bei ${b} passiert?` : "Was hat sich seit letzter Woche bewegt?"];
      const chips = empty.createDiv({ cls: "sb-chat-examples" });
      for (const q of examples) {
        const btn = chips.createEl("button", { text: q, cls: "sb-btn-small sb-chat-example" });
        btn.onclick = () => void this.ask(q);
      }
      return;
    }
    const last = this.s.turns[this.s.turns.length - 1];
    for (const t of this.s.turns) {
      const el = this.listEl.createDiv({ cls: `sb-chat-msg sb-chat-${t.rolle}${t.fehler ? " sb-chat-error" : ""}` });
      if (t.rolle === "assistent") {
        void MarkdownRenderer.render(this.app, t.text, el.createDiv({ cls: "sb-chat-md" }), this.lastFile ?? "", this);
        if (t.meta) el.createDiv({ cls: "sb-chat-meta", text: t.meta });
        // Knoepfe nur an der aktuell offenen Frage
        if (t.karte && this.s.karte && t.karte.id === this.s.karte.id && t === last) {
          const opts = el.createDiv({ cls: "sb-chat-options" });
          for (const o of t.karte.optionen) {
            const b = opts.createEl("button", { text: o.label, cls: "sb-btn-small" });
            b.onclick = () => this.answerCard(o.key, o.label);
          }
          const end = opts.createEl("button", { text: "Frage-Modus beenden", cls: "sb-btn-small sb-chat-end" });
          end.onclick = () => { this.setKarte(null); this.renderTurns(); };
        }
      } else {
        el.setText(t.text);
      }
    }
    if (this.s.busy) {
      this.listEl.createDiv({ cls: "sb-chat-msg sb-chat-assistent sb-chat-pending", text: "denkt nach …" });
    }
    this.listEl.scrollTop = this.listEl.scrollHeight;
  }

  /** Interne Links in gerenderten Antworten oeffnen (in eigenen Views nicht automatisch). */
  private followLink(e: MouseEvent): void {
    const a = (e.target as HTMLElement).closest("a.internal-link");
    const href = a?.getAttribute("data-href") ?? a?.getAttribute("href");
    if (!href) return;
    e.preventDefault();
    void this.app.workspace.openLinkText(href, this.lastFile ?? "", e.ctrlKey || e.metaKey);
  }

  private async ask(text: string, skill?: ChatSkill,
                    extra?: { karte?: { id: string; key: string }; anzeige?: string }): Promise<void> {
    const frage = text.trim();
    if (this.s.busy || (!frage && !skill)) return;
    this.s.busy = true;
    this.inputEl.value = "";
    this.grow();
    const history = this.s.turns.filter((t) => !t.fehler).slice(-4).map((t) => ({ rolle: t.rolle, text: t.text }));
    // Frage-Modus: getippter Text ist eine Einordnung zur offenen Frage, keine neue Frage
    const inCard = this.s.karte !== null && !skill && frage !== "";
    const cardMode = inCard || skill?.quelle === "fragen";
    this.s.turns.push({ rolle: "nutzer",
                        text: extra?.anzeige ?? (skill ? `${skill.label}${frage ? ` – ${frage}` : ""}` : frage) });
    this.renderTurns();
    this.renderBar();
    const viaEngine = cardMode;                  // nur der Frage-Modus (Atlas) laeuft in der Engine
    const pending = this.listEl.querySelector(".sb-chat-pending") as HTMLElement | null;
    pending?.setText(viaEngine ? "wartet auf die Engine …" : "sucht im Vault …");
    const started = Date.now();
    let timer: number | null = null;
    const req: Record<string, unknown> = { frage, skill: skill?.name ?? (inCard ? FRAGEN_SKILL.name : null),
                                           ziel: { datei: this.activeScopeFile() ?? "" }, bezug: this.s.bezug,
                                           verlauf: history };
    if (cardMode) req.ueberspringen = this.s.skip;
    if (extra?.karte) req.karte = extra.karte;
    if (inCard && this.s.karte) req.karte_offen = this.s.karte.id;
    const onStart = () => {
      pending?.setText("denkt nach …");
      timer = window.setInterval(() => pending?.setText(`denkt nach … ${Math.round((Date.now() - started) / 1000)} s`), 1000);
    };
    let r: ChatAnswer | null;
    if (!viaEngine) {
      onStart();
      r = await this.plugin.askChat(req as ChatRequest);
    } else if (!this.plugin.isDesktop) {
      r = { ok: false, grund: "„Offene Fragen“ gibt es nur am Desktop – dort läuft die Engine." };
    } else {
      r = await this.plugin.engine.json<ChatAnswer>(["frage", "--json"], { input: JSON.stringify(req), timeoutMs: 300_000, onStart });
    }
    if (timer !== null) window.clearInterval(timer);
    if (r?.ok && r.antwort) {
      this.s.bezug = r.bezug ?? this.s.bezug;
      if (r.karte !== undefined) {                 // Frage-Modus: naechste Frage (oder keine mehr)
        this.setKarte(r.karte ?? null);
        this.s.skip = r.ueberspringen ?? this.s.skip;
      } else if (skill) {
        this.setKarte(null);                       // ein anderer Skill beendet den Frage-Modus
      }
      const woher = r.bezug?.herkunft ? ` (${r.bezug.herkunft})` : "";
      const meta = [r.bezug?.anzeige?.length ? `Bezug${woher}: ${r.bezug.anzeige.join(", ")}` : "",
                    r.karte ? `${r.karte.offen} offen` : "",
                    r.dauer_s ? `${r.dauer_s} s` : ""].filter(Boolean).join(" · ");
      this.s.turns.push({ rolle: "assistent", text: r.antwort, meta, karte: r.karte ?? undefined });
    } else {
      const grund = r?.grund ?? "Keine Antwort von der Engine.";
      this.s.turns.push({ rolle: "assistent", fehler: true,
                          text: r?.ausschnitt ? `${grund}\n\nDas hätte das Modell bekommen:\n\n${r.ausschnitt}` : grund });
    }
    this.s.busy = false;
    this.plugin.refreshChats();                  // auch eine inzwischen gross/klein gewechselte Ansicht
  }
}
