// Das Plugin: Ansichten, Befehle, Zustand. Lesen, Erfassen und Chat rechnet es selbst (src/core);
// fuer alles andere startet es am Desktop die Python-Engine (src/desktop).
import { FileSystemAdapter, Notice, Platform, Plugin, TAbstractFile, TFile, WorkspaceLeaf, debounce, normalizePath, requestUrl } from "obsidian";
import {
  CaptureResult as CoreCaptureResult, appendNotes, capturable, setEntfallen, setSkip, setWrapupRequest,
} from "./core/nacherfassen";
import { ChatAnswer, ChatRequest, Fortschritt, ask } from "./core/chat";
import { localIsoDate } from "./core/datum";
import { Graph, baueGraph } from "./core/graph";
import { HttpPost, complete, completeTools, stripThink } from "./core/modell";
import type { MeetingInfo, RiskRow, TaskInfo } from "./core/ansicht";
import { RISK_WINDOW_DAYS, riskRows } from "./core/risiken";
import { SKILL_DIR, SkillRecipe, parseSkills } from "./core/rezepte";
import { CompleteResult, completable, completeInText, isOpen, scanTasks } from "./core/aufgaben";
import { VaultIndex } from "./core/vaultIndex";
import { withoutAssigned } from "./core/themen";
import type { DesktopServices, Likec4Paths, PythonInfo } from "./desktop";
import { EngineApi, NUR_DESKTOP, OfflineEngine } from "./engineApi";
import { ObsidianSource } from "./obsidianSource";
import { DEFAULT_SETTINGS, SecondBrainSettingTab, SecondBrainSettings, Spiegel } from "./einstellungen";
import { CAL_CONFIG, Json, LLM_CONFIG, LOCAL_CONFIG, readConfig, updateConfig } from "./konfiguration";
import { CaptureModal, WrapupResultModal } from "./views/nacherfassen";
import { ChatState, ChatView, VIEW_TYPE_CHAT, newChatState } from "./views/chat";
import { AnleitungView, VIEW_TYPE_ANLEITUNG } from "./views/anleitung";
import { COCKPIT_BLOCK, CockpitBlock } from "./views/cockpit";
import { PersonPickerModal, PersonSuggestion } from "./views/personen";
import { TopicPersonSuggest } from "./views/sofortsuche";
import { TodayView, VIEW_TYPE_TODAY } from "./views/heute";
import { TopicPickerModal, TopicState, TopicSuggestion, TopicTarget } from "./views/themen";

/** Reihe/Termin ohne Thema (`2ndbrain thema --offen --json`). */
export interface OpenSeries {
  reihe: string;
  titel: string;
  naechster: string;
  zeit: string;
  anzahl: number;
  note: string | null;
  wiederkehrend?: boolean;   // Reihe (mehr als ein Tag) - sonst Einzeltermin, Thema nur in der Notiz
  vorkommen?: number;
  vorschlaege: TopicSuggestion[];
}

interface AutoStep { step: string; ok: boolean; skipped?: boolean; detail?: string; changed?: number }
/** `2ndbrain einrichten --json` */
export interface EinrichtenErgebnis { ok: boolean; schritte: { ok: boolean; schritt: string; text: string }[]; mcp?: string }
/** Engine: installiert, passende Version? */
export interface EngineStatus { state: "unbekannt" | "fehlt" | "abweichend" | "ok"; version: string | null; text: string }
interface AutoResult { ok: boolean; llm?: boolean; seconds?: number; skipped?: string; steps: AutoStep[] }
export interface CaptureResult { ok: boolean; grund?: string; geaendert?: boolean; aktion?: string; note?: string }
export interface UndoInfo {
  ok: boolean;
  status: string;
  undo: { at: string; events: Record<string, string[]> } | null;
}

/** Nachbereitung im Hintergrund - die Seitenleiste zeigt ihren Stand. */
export interface WrapupJob {
  meeting: MeetingInfo;
  state: "wartet" | "läuft" | "fertig" | "fehler";
  detail: string;
  started: Date;
}

/** Verbindung zum Modell-Server (llama.cpp, OpenAI-kompatibel). */
export interface LlmConnection { url: string; model: string; timeoutS: number }

const MAX_FINISHED_JOBS = 5;
// Engine-Paket je Plugin-Version (GitHub-Release; das Wheel haengt dort an)
const ENGINE_REPO = "https://github.com/mdopp/2ndbrain";
// Kalender-Adresse im Obsidian-Schluesselbund (je Geraet, nicht in data.json, nicht im Vault-Ordner)
const CAL_SECRET = "2ndbrain-kalender-url";
// Sperre der Automatik (auto.py): solange sie laeuft, schreibt das Plugin keine Termin-/Themen-Dateien.
// Nur am Desktop - am Handy laeuft keine Engine, dort fuehrt der Sync zusammen.
const AUTO_LOCK = ".2ndbrain/daten/.auto.lock";
const AUTO_LOCK_MAX_AGE_MS = 30 * 60_000;
// Zeitlimit fuer die Absicht einer Chat-Frage (erster Aufruf nach einer Pause ~3 s, sonst < 1 s)
const ABSICHT_TIMEOUT_S = 15;

export default class SecondBrainPlugin extends Plugin {
  settings: SecondBrainSettings = { ...DEFAULT_SETTINGS };
  /** Nur am Desktop: Python-Engine, LikeC4, Python-Suche (src/desktop, dynamisch geladen). */
  desktop: DesktopServices | null = null;
  index!: VaultIndex;
  source!: ObsidianSource;     // Vault fuer die Logik in src/core (Aufgaben, Risiken, Nacherfassen, ...)
  tasks: TaskInfo[] = [];
  llmState = { ok: false, detail: "noch nicht geprüft" };
  llmModels: string[] = [];          // was der Server unter /v1/models anbietet (Auswahl in den Einstellungen)
  lastAuto: { at: Date; result: AutoResult | null } | null = null;
  jobs: WrapupJob[] = [];
  openTopics: OpenSeries[] = [];
  chatState: ChatState = newChatState();   // Gespraech - uebersteht den Wechsel klein/gross
  pythonInfo: PythonInfo | null = null;
  paths: Likec4Paths | null = null;   // `2ndbrain pfade --json`: Modell-Ordner, likec4-Befehl, Kalender ja/nein
  engineStatus: EngineStatus = { state: "unbekannt", version: null, text: "Noch nicht geprüft." };
  einrichtenErgebnis: EinrichtenErgebnis | null = null;
  tasksLoaded = false;
  cockpitBlocks = new Set<CockpitBlock>();   // offene ```2ndbrain-Ansichten (Aufgaben, Risiken)
  risks: { at: number; rows: RiskRow[]; window: number } | null = null;
  private readonly offline = new OfflineEngine();

  private autoTimer: number | null = null;
  private pythonLookup: Promise<PythonInfo | null> | null = null;
  private pythonCheckedAt = 0;
  private pythonWarned = false;
  private engineWarned = false;
  private statusEl: HTMLElement | null = null;
  // aus .2ndbrain/ (am Handy oft nicht vorhanden - dann gilt die Kopie in settings.spiegel)
  private llmCfg: { url: string; model: string; timeoutS: number } | null = null;
  private localCfg: { ich: string; beschreibung: string } | null = null;
  private skillCache: SkillRecipe[] | null = null;
  // Wissensgraph fuer die Werkzeuge des Chats - gebaut bei der ersten Frage, die ihn braucht, und nach
  // jeder Aenderung im Vault verworfen (neu gebaut erst bei der naechsten Frage)
  private graphCache: Promise<Graph> | null = null;

  /** Python-Engine (Desktop) - am Handy eine, die "nur am Desktop" antwortet. */
  get engine(): EngineApi {
    return this.desktop?.engine ?? this.offline;
  }

  get isDesktop(): boolean {
    return this.desktop !== null;
  }

  async onload(): Promise<void> {
    await this.loadSettings();
    this.source = new ObsidianSource(this.app);
    this.index = new VaultIndex(this.source);
    const adapter = this.app.vault.adapter;
    if (Platform.isDesktopApp && adapter instanceof FileSystemAdapter) {
      const { createDesktop } = await import("./desktop");
      this.desktop = createDesktop(adapter.getBasePath(), async () => (await this.resolvePython())?.executable ?? null,
                                   () => this.engineEnv(), (url) => this.isLikec4(url));
    }

    this.registerView(VIEW_TYPE_TODAY, (leaf) => new TodayView(leaf, this));
    this.registerView(VIEW_TYPE_CHAT, (leaf) => new ChatView(leaf, this));
    this.registerView(VIEW_TYPE_ANLEITUNG, (leaf) => new AnleitungView(leaf));
    // Cockpit-Seiten ohne JavaScript in der Notiz: ```2ndbrain aufgaben / risiken
    this.registerMarkdownCodeBlockProcessor(COCKPIT_BLOCK, (source, el, ctx) => {
      ctx.addChild(new CockpitBlock(el, this, source.trim().split(/\s+/)[0] ?? "", ctx.sourcePath));
    });
    this.addRibbonIcon("calendar-check", "2ndBrain: Heute", () => void this.activateToday());
    this.addRibbonIcon("message-circle", "2ndBrain: Fragen an den Vault", () => void this.activateChat());
    if (this.desktop) this.addRibbonIcon("network", "2ndBrain: Systemübersicht (LikeC4)", () => void this.openSystemOverview());
    this.statusEl = this.addStatusBarItem();
    this.addSettingTab(new SecondBrainSettingTab(this.app, this));
    this.registerCommands();

    // Abgehakte Punkte, neue Notizen: Punkte und Ansichten nach jeder Aenderung nachziehen - das
    // dauert Millisekunden (Frontmatter erst, wenn der Cache sie kennt: daher auch "changed").
    const refresh = debounce(() => void this.refreshFromVault(), 1_500, true);
    const onChange = (f: TAbstractFile) => {
      if (f.path.endsWith(".md")) this.graphCache = null;
      if (f.path.startsWith("active-meetings/") || f.path.startsWith("entities/")) refresh();
    };
    this.registerEvent(this.app.vault.on("modify", onChange));
    this.registerEvent(this.app.vault.on("create", onChange));
    this.registerEvent(this.app.vault.on("delete", onChange));
    this.registerEvent(this.app.vault.on("rename", onChange));
    this.registerEvent(this.app.metadataCache.on("changed", onChange));

    this.app.workspace.onLayoutReady(() => {
      void this.startup();
    });
    this.registerInterval(window.setInterval(() => void this.refreshLlm(), 5 * 60_000));
    // Obsidian schliesst: den Explorer mitnehmen (onunload kommt dann nicht immer)
    if (this.desktop) this.registerDomEvent(window, "beforeunload", () => this.desktop?.likec4.stop());
    // Kaesten in Bildern oeffnen ihre Notiz (Pfad im Hinweistext)
    this.registerDomEvent(document, "click", (evt) => this.openDiagramNode(evt), { capture: true });
  }

  onunload(): void {
    if (this.autoTimer !== null) window.clearInterval(this.autoTimer);
    this.desktop?.likec4.stop();
  }

  private async startup(): Promise<void> {
    await this.refreshTasks();                  // ohne Python, sofort
    await this.loadVaultConfig();
    await this.refreshLlm();
    if (!this.desktop) return;
    await this.resolvePython();
    await this.refreshEngine();
    if (this.engineStatus.state === "fehlt") {
      this.scheduleAutomatik();            // prueft bei jedem Lauf; nach der Installation geht es los
      return;
    }
    await this.refreshPaths();
    if (this.settings.likec4Autostart) void this.startLikec4(false);
    await this.refreshOpenTopics();
    this.scheduleAutomatik();
  }

  // ------------------------------------------------------------- Engine (Desktop)

  /** Ist die Engine in diesem Python installiert, und passt ihre Version zum Plugin? */
  async refreshEngine(): Promise<EngineStatus> {
    if (!this.desktop) return this.engineStatus;
    const r = await this.engine.json<{ version: string; python: string }>(["version", "--json"], { timeoutMs: 60_000 });
    const soll = this.manifest.version;
    if (!r?.version) {
      this.engineStatus = { state: "fehlt", version: null,
        text: this.pythonInfo ? `Nicht installiert in ${this.pythonInfo.executable}.` : "Kein Python gefunden." };
      if (!this.engineWarned && this.pythonInfo) {
        this.engineWarned = true;
        new Notice("2ndBrain: Die Engine fehlt noch – Einstellungen → 2ndBrain → Engine „Installieren“.", 15_000);
      }
    } else if (r.version !== soll) {
      this.engineStatus = { state: "abweichend", version: r.version,
        text: `Version ${r.version}, das Plugin ist ${soll} – „Aktualisieren“ holt die passende.` };
    } else {
      this.engineStatus = { state: "ok", version: r.version, text: `Version ${r.version} in ${r.python}.` };
    }
    return this.engineStatus;
  }

  /** Das Engine-Paket, das der Build neben main.js legt (`2ndbrain-<version>-py3-none-any.whl`) - voller
   *  Pfad, oder null, wenn es fehlt. */
  private async beigelegteEngine(v: string): Promise<string | null> {
    const adapter = this.app.vault.adapter;
    const rel = normalizePath(`${this.manifest.dir ?? `${this.app.vault.configDir}/plugins/${this.manifest.id}`}/2ndbrain-${v}-py3-none-any.whl`);
    return adapter instanceof FileSystemAdapter && (await adapter.exists(rel)) ? adapter.getFullPath(rel) : null;
  }

  /** Engine installieren oder aktualisieren: `python -m pip install --upgrade <Quelle>`. Quelle: eingetragen >
   *  dem Plugin beigelegt > GitHub-Release. Lehnt das Python des Systems pip ab (Homebrew, PEP 668), bekommt
   *  die Engine eine eigene Umgebung (~/.2ndbrain/venv), deren Python danach eingetragen ist. */
  async installEngine(): Promise<boolean> {
    if (!this.desktop) return false;
    const v = this.manifest.version;
    const quelle = this.settings.engineQuelle.trim() || (await this.beigelegteEngine(v))
      || `${ENGINE_REPO}/releases/download/${v}/2ndbrain-${v}-py3-none-any.whl`;
    const ziel = quelle.startsWith("-e ") ? ["-e", quelle.slice(3).trim()] : [quelle];
    new Notice("2ndBrain: Engine wird installiert …");
    const pip = () => this.engine.python(["-m", "pip", "install", "--upgrade", ...ziel], { timeoutMs: 10 * 60_000 });
    let r = await pip();
    if (r.code !== 0 && /externally-managed-environment/.test(r.stderr + r.stdout)) {
      const venv = this.desktop.venvDir();
      new Notice(`2ndBrain: Das Python des Systems ist verwaltet (etwa Homebrew) – die Engine bekommt eine eigene Umgebung in ${venv}.`, 10_000);
      const neu = await this.engine.python(["-m", "venv", venv], { timeoutMs: 5 * 60_000 });
      if (neu.code === 0) {
        this.settings.pythonPath = this.desktop.venvPython(venv);
        await this.saveSettings();
        this.pythonLookup = null;
        this.pythonInfo = null;
        await this.resolvePython();
        r = await pip();
      } else r = neu;
    }
    await this.refreshEngine();
    if (r.code !== 0) {
      const text = (r.stderr || r.stdout).trim();
      const hinweis = /\b404\b|Not Found/.test(text) && quelle.startsWith(ENGINE_REPO)
        ? "Das Engine-Paket liegt dem Plugin nicht bei, und GitHub liefert es nicht (Repo privat oder kein Release). "
          + "Plugin neu bauen (legt die Engine bei) oder unter Engine-Quelle „-e <Pfad>/2ndbrain-code/engine“ eintragen.\n"
        : "";
      new Notice(`2ndBrain: Installation fehlgeschlagen.\n${hinweis}${text.split("\n").slice(-3).join("\n")}`, 20_000);
      return false;
    }
    new Notice(`2ndBrain: ${this.engineStatus.text}`, 8000);
    if (this.engineStatus.state !== "fehlt") {
      await this.refreshPaths();
      await this.refreshOpenTopics();
    }
    return this.engineStatus.state !== "fehlt";
  }

  /** `2ndbrain einrichten`: fehlende Vorlagen, Pfade, Pruefungen; das Ergebnis zeigen die Einstellungen. */
  async einrichten(): Promise<EinrichtenErgebnis | null> {
    if (!this.desktop) return null;
    const r = await this.engine.json<EinrichtenErgebnis>(["einrichten", "--json"], { timeoutMs: 5 * 60_000 });
    this.einrichtenErgebnis = r;
    if (!r) {
      new Notice("2ndBrain: Einrichten lieferte kein Ergebnis – Engine prüfen.");
      return null;
    }
    const offen = r.schritte.filter((s) => !s.ok).map((s) => s.schritt);
    new Notice(`2ndBrain: eingerichtet${offen.length ? ` – offen: ${offen.join(", ")}` : ""}.`, 10_000);
    await this.loadVaultConfig();
    await this.refreshPaths();
    return r;
  }

  /** Termine/Reihen der naechsten 14 Tage ohne Thema (fuer "Nacharbeit") - Desktop. */
  async refreshOpenTopics(): Promise<void> {
    if (!this.desktop) return;
    const r = await this.engine.json<OpenSeries[]>(["thema", "--offen", "--json"], { timeoutMs: 120_000 });
    if (Array.isArray(r)) this.openTopics = r;
    await this.refreshViews();
  }

  private registerCommands(): void {
    this.addCommand({ id: "open-today", name: "Heute öffnen", callback: () => void this.activateToday() });
    this.addCommand({ id: "open-chat", name: "Fragen an den Vault (Chat)", callback: () => void this.activateChat() });
    this.addCommand({ id: "quick-look", name: "Sofortsuche: Thema oder Person", callback: () => this.openQuickLook() });
    this.addCommand({ id: "open-help", name: "Anleitung: so funktioniert 2ndBrain", callback: () => void this.openHelp() });
    this.addCommand({
      id: "wrapup-note", name: "Diesen Termin nacherfassen / nachbereiten",
      checkCallback: (checking) => {
        const f = this.app.workspace.getActiveFile();
        const ok = !!f && f.path.startsWith("active-meetings/");
        if (ok && !checking) void this.openCapture(f.path);
        return ok;
      },
    });
    if (!this.desktop) return;
    this.addCommand({ id: "run-automatik", name: "Automatik jetzt ausführen", callback: () => void this.runAutomatik(true) });
    this.addCommand({ id: "open-system-overview", name: "Systemübersicht öffnen (LikeC4)",
                      callback: () => void this.openSystemOverview() });
    this.addCommand({
      id: "set-topic", name: "Thema für diesen Termin festlegen",
      checkCallback: (checking) => {
        const f = this.app.workspace.getActiveFile();
        const ok = !!f && f.path.startsWith("active-meetings/");
        if (ok && !checking) this.openTopicPicker({ kind: "note", path: f.path });
        return ok;
      },
    });
    this.addCommand({
      id: "undo-wrapup", name: "Nachbereitung dieses Termins zurücknehmen",
      checkCallback: (checking) => {
        const f = this.app.workspace.getActiveFile();
        // auch archiviert: Zuruecknehmen holt die Notiz nach active-meetings/ zurueck
        const ok = !!f && (f.path.startsWith("active-meetings/") || f.path.startsWith("archive/meetings/"));
        if (ok && !checking) void this.undoFromCommand(f.path);
        return ok;
      },
    });
    this.addCommand({
      id: "refresh-stand", name: "Stand dieses Themas aktualisieren",
      checkCallback: (checking) => {
        const f = this.app.workspace.getActiveFile();
        const ok = !!f && f.path.startsWith("entities/projects/");
        if (ok && !checking) void this.refreshStand(f.basename);
        return ok;
      },
    });
  }

  // ------------------------------------------------------------ Einstellungen

  async loadSettings(): Promise<void> {
    const s = ((await this.loadData()) as Partial<SecondBrainSettings> | null) ?? {};
    this.settings = { ...DEFAULT_SETTINGS, ...s, spiegel: { ...DEFAULT_SETTINGS.spiegel, ...(s.spiegel ?? {}) } };
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  // ---------------------------------------- Konfiguration des Vaults, Kopie fuers Handy

  /** .2ndbrain/local.config.json, llm.config.json und die Chat-Rezepte lesen. Was gelesen werden
   *  konnte, kommt in die Kopie (settings.spiegel) - die synchronisiert mit den Plugin-Daten aufs
   *  Handy, wo die versteckten Ordner oft fehlen. */
  async loadVaultConfig(): Promise<void> {
    const adapter = this.app.vault.adapter;
    const local = await readConfig(adapter, LOCAL_CONFIG);
    this.localCfg = local ? { ich: String(local.ich ?? "").trim(), beschreibung: String(local.beschreibung ?? "").trim() } : null;
    const llm = await readConfig(adapter, LLM_CONFIG);
    this.llmCfg = llm ? { url: String(llm.url ?? ""), model: String(llm.model ?? ""),
                          timeoutS: Number(llm.timeout_s) || 240 } : null;
    this.skillCache = await this.readSkills();

    const s = this.settings.spiegel;
    const next: Spiegel = {
      ich: this.localCfg?.ich ?? s.ich, beschreibung: this.localCfg?.beschreibung ?? s.beschreibung,
      llmUrl: this.llmCfg?.url ?? s.llmUrl, llmModel: this.llmCfg?.model ?? s.llmModel,
      llmTimeoutS: this.llmCfg?.timeoutS ?? s.llmTimeoutS,
      skills: this.skillCache ?? s.skills, am: s.am,
    };
    const content = (x: Spiegel) => JSON.stringify({ ...x, am: "" });
    if (content(next) !== content(s)) {
      this.settings.spiegel = { ...next, am: localIsoDate() };
      await this.saveSettings();
    }
  }

  /** Rezepte aus .2ndbrain/chat-skills; null, wenn der Ordner fehlt (Handy). */
  private async readSkills(): Promise<SkillRecipe[] | null> {
    const adapter = this.app.vault.adapter;
    try {
      if (!(await adapter.exists(SKILL_DIR))) return null;
      const listed = await adapter.list(SKILL_DIR);
      const files = await Promise.all(listed.files.filter((p) => p.endsWith(".md"))
        .map(async (p) => ({ name: p.slice(p.lastIndexOf("/") + 1), text: await adapter.read(p) })));
      return parseSkills(files);
    } catch {
      return null;
    }
  }

  /** Wissensgraph ueber Notizen, Atlas und Systemuebersicht (core/graph.ts), zwischengespeichert. */
  graph(): Promise<Graph> {
    if (!this.graphCache) {
      const g = baueGraph(this.source, this.selfSlug);
      this.graphCache = g;
      g.catch(() => { if (this.graphCache === g) this.graphCache = null; });
    }
    return this.graphCache;
  }

  /** Frage an den Vault (src/core/chat.ts): Ausschnitt hier, Modell direkt ueber requestUrl -
   *  am Desktop wie am Handy; reicht der Ausschnitt nicht, schlaegt das Modell mit den Werkzeugen
   *  nach (Graph). Nur "Offene Fragen" (Atlas) geht ueber die Engine. */
  async askChat(req: ChatRequest, fortschritt?: (f: Fortschritt) => void): Promise<ChatAnswer> {
    return ask(req, {
      src: this.source, today: localIsoDate(), me: this.selfSlug, beschreibung: this.vaultDescription,
      skills: await this.chatSkills(),
      llm: async (messages) => stripThink(await complete(this.httpPost, this.llm, messages, { maxTokens: 900, temperature: 0.2 })),
      llmWerkzeuge: (messages, tools, wahl) =>
        completeTools(this.httpPost, this.llm, messages, tools, { maxTokens: 900, temperature: 0.2, wahl }),
      graph: () => this.graph(),
      fortschritt,
      files: () => new Set(this.app.vault.getMarkdownFiles().map((f) => f.basename.toLowerCase())),
      vault: this.app.vault.getName(),
      // Was gemeint ist, waehlt das Modell (kurz, mit eigenem Zeitlimit); ist es nicht erreichbar,
      // entscheiden sofort die Regeln
      absicht: this.llmState.ok
        ? async (messages) => stripThink(await complete(this.httpPost, { ...this.llm, timeoutS: ABSICHT_TIMEOUT_S }, messages,
                                                        { maxTokens: 300, temperature: 0.1 }))
        : undefined,
    });
  }

  /** Klick auf einen Kasten in einem Bild (Mermaid): der Hinweistext traegt den Pfad der Notiz
   *  (core/chatBilder.ts `klick`). Obsidians Mermaid entfernt obsidian://-Adressen, deshalb oeffnet
   *  das Plugin die Notiz selbst - im Chat wie in jeder Notiz, am Desktop wie am Handy. */
  private openDiagramNode(evt: MouseEvent): void {
    const target = evt.target as Element | null;
    const node = target?.closest?.(".mermaid .clickable[title]");
    const path = node?.getAttribute("title") ?? "";
    if (!path.endsWith(".md") || !(this.app.vault.getAbstractFileByPath(path) instanceof TFile)) return;
    evt.preventDefault();
    evt.stopPropagation();
    void this.app.workspace.openLinkText(path, "", evt.ctrlKey || evt.metaKey);
  }

  /** POST ueber Obsidians requestUrl (kein CORS, auch am Handy) - mit eigenem Zeitlimit. */
  private readonly httpPost: HttpPost = async (url, body, timeoutMs) => {
    let timer: number | null = null;
    const limit = new Promise<never>((_, reject) => {
      timer = window.setTimeout(() => reject(new Error(`keine Antwort nach ${Math.round(timeoutMs / 1000)} s`)), timeoutMs);
    });
    try {
      const r = await Promise.race([requestUrl({ url, method: "POST", contentType: "application/json",
                                                 body: JSON.stringify(body), throw: false }), limit]);
      let json: unknown = null;
      try {
        json = r.json;
      } catch {
        json = null;
      }
      return { status: r.status, json, text: r.text };
    } finally {
      if (timer !== null) window.clearTimeout(timer);
    }
  };

  /** Chat-Rezepte: aus dem Vault, sonst aus der Kopie. */
  async chatSkills(): Promise<SkillRecipe[]> {
    if (!this.skillCache) this.skillCache = await this.readSkills();
    return this.skillCache ?? this.settings.spiegel.skills;
  }

  /** Eigener Personen-Slug: "ich" aus der Vault-Konfiguration (am Handy aus ihrer Kopie). */
  get selfSlug(): string {
    return this.localCfg?.ich || this.paths?.ich || this.settings.spiegel.ich || "";
  }

  /** Worum es im Vault geht (fuer die Prompts). */
  get vaultDescription(): string {
    return this.localCfg?.beschreibung ?? this.settings.spiegel.beschreibung;
  }

  /** Modell-Server aus .2ndbrain/llm.config.json - am Handy aus der Kopie. */
  get llm(): LlmConnection {
    const s = this.settings.spiegel;
    return { url: (this.llmCfg?.url ?? s.llmUrl).replace(/\/$/, ""), model: this.llmCfg?.model ?? s.llmModel,
             timeoutS: this.llmCfg?.timeoutS ?? s.llmTimeoutS };
  }

  /** Adresse aus .2ndbrain/llm.config.json (Platzhalter in den Einstellungen). */
  get llmConfigUrl(): string {
    return this.llmCfg?.url ?? this.settings.spiegel.llmUrl;
  }

  // ------------------------------------------------------ Python, LikeC4 (Desktop)

  /** Python je Sitzung einmal suchen (eingetragen > py > python > python3); nach einem
   *  Fehlschlag eine Minute spaeter erneut - vielleicht wurde es inzwischen installiert. */
  resolvePython(): Promise<PythonInfo | null> {
    if (!this.desktop) return Promise.resolve(null);
    if (this.pythonLookup && (this.pythonInfo || Date.now() - this.pythonCheckedAt < 60_000)) return this.pythonLookup;
    this.pythonCheckedAt = Date.now();
    const configured = this.settings.pythonPath.trim();
    this.pythonLookup = this.desktop.findPython(configured).then((info) => {
      this.pythonInfo = info;
      if (!info && !this.pythonWarned) {
        this.pythonWarned = true;
        new Notice("2ndBrain: kein Python ≥ 3.10 gefunden (gesucht über den PATH und an den üblichen Orten wie "
          + "Homebrew, python.org, pyenv). Python installieren (python.org oder Homebrew) oder den Pfad in den "
          + "Einstellungen eintragen, am Mac etwa /opt/homebrew/bin/python3.", 15_000);
      } else if (info && configured && info.command !== configured) {
        new Notice(`2ndBrain: Python „${configured}“ geht nicht – nutze ${info.executable} (${info.version}).`, 10_000);
      }
      return info;
    });
    return this.pythonLookup;
  }

  /** Nach einer Aenderung in den Einstellungen neu suchen. */
  resetPython(): void {
    this.pythonLookup = null;
    this.pythonInfo = null;
    this.pythonWarned = false;
  }

  async refreshPaths(): Promise<void> {
    if (!this.desktop) return;
    const p = await this.engine.json<Likec4Paths>(["pfade", "--json"], { timeoutMs: 60_000 });
    if (p) this.paths = p;
  }

  /** Explorer starten (oder den laufenden nutzen); manual: Meldung, wenn es nicht geht. */
  async startLikec4(manual: boolean): Promise<string | null> {
    if (!this.desktop) return null;
    if (!this.paths?.likec4_model || !this.paths.likec4_befehl) await this.refreshPaths();
    if (!this.paths) {
      if (manual) new Notice("2ndBrain: Pfade nicht lesbar – Python/Engine prüfen.");
      return null;
    }
    const url = await this.desktop.likec4.start(this.paths, this.settings.likec4Port);
    if (!url && manual) new Notice(`2ndBrain: Systemübersicht nicht gestartet – ${this.desktop.likec4.detail}`, 10_000);
    return url;
  }

  async openSystemOverview(): Promise<void> {
    if (!this.desktop) return;
    if (this.desktop.likec4.state !== "läuft") new Notice("2ndBrain: Systemübersicht startet …", 4000);
    const url = await this.startLikec4(true);
    if (url) window.open(url);
  }

  /** Antwortet unter der Adresse ein LikeC4-Explorer (und nicht irgendein anderer Dienst)? Mit
   *  Zeitlimit: ein haengender Server nimmt die Verbindung an und antwortet nie. */
  private async isLikec4(url: string): Promise<boolean> {
    try {
      const r = await Promise.race([
        requestUrl({ url, method: "GET", throw: false }),
        new Promise<null>((resolve) => window.setTimeout(() => resolve(null), 5000)),
      ]);
      return !!r && r.status === 200 && /likec4/i.test(r.text);
    } catch {
      return false;
    }
  }

  /** Explorer neu starten (Einstellungen): auch einen haengenden von einer vorigen Sitzung. */
  async restartLikec4(): Promise<string | null> {
    if (!this.desktop) return null;
    if (!this.paths?.likec4_model || !this.paths.likec4_befehl) await this.refreshPaths();
    if (!this.paths) return null;
    new Notice("2ndBrain: Systemübersicht startet neu …", 4000);
    const url = await this.desktop.likec4.restart(this.paths, this.settings.likec4Port);
    new Notice(url ? "2ndBrain: Systemübersicht läuft." : `2ndBrain: Systemübersicht nicht gestartet – ${this.desktop.likec4.detail}`,
      url ? 4000 : 10_000);
    return url;
  }

  // ---------------------------------------------------------------- Zustand

  async refreshLlm(): Promise<void> {
    const { url, model } = this.llm;
    if (!url) {
      this.llmState = { ok: false, detail: "kein Server konfiguriert" };
    } else {
      try {
        const r = await requestUrl({ url: `${url}/v1/models`, method: "GET", throw: false });
        const ids = r.status === 200 ? ((r.json?.data ?? []) as { id: string }[]).map((m) => m.id) : [];
        this.llmModels = ids;
        this.llmState = r.status !== 200
          ? { ok: false, detail: `HTTP ${r.status}` }
          : { ok: !model || ids.includes(model), detail: model || "bereit" };
      } catch {
        this.llmModels = [];
        this.llmState = { ok: false, detail: "nicht erreichbar" };
      }
    }
    this.updateStatus();
  }

  /** Offene Punkte (src/core/aufgaben.ts) - in Millisekunden, ohne Python. */
  async refreshTasks(): Promise<void> {
    this.tasks = (await scanTasks(this.source)).filter(isOpen);
    this.tasksLoaded = true;
    await this.refreshViews();
  }

  /** Nach einer Aenderung im Vault: was das Plugin selbst rechnet, sofort nachziehen. */
  private async refreshFromVault(): Promise<void> {
    if (this.risks) await this.loadRisks();
    await this.refreshTasks();
  }

  /** Risiken aus dem Themen-Log (src/core/risiken.ts), bei jedem Aufruf frisch. */
  async loadRisks(): Promise<void> {
    this.risks = { at: Date.now(), rows: await riskRows(this.source, localIsoDate()), window: RISK_WINDOW_DAYS };
  }

  private updateStatus(): void {
    if (!this.statusEl) return;
    const dot = this.llmState.ok ? "●" : "○";
    const auto = this.lastAuto ? ` · Auto ${this.lastAuto.at.toTimeString().slice(0, 5)}` : "";
    const running = this.jobs.filter((j) => j.state === "wartet" || j.state === "läuft").length;
    const busy = running ? ` · Nachbereitung läuft (${running})` : this.engine.busy ? " · läuft …" : "";
    this.statusEl.setText(`2ndBrain ${dot}${auto}${busy}`);
    this.statusEl.setAttr("aria-label", `Modell: ${this.llmState.detail}`);
  }

  async refreshViews(): Promise<void> {
    this.updateStatus();
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE_TODAY)) {
      if (leaf.view instanceof TodayView) await leaf.view.render();
    }
    for (const block of [...this.cockpitBlocks]) await block.render();
  }

  // ------------------------------------------- Kalender (Schluesselbund), Konfiguration

  /** Kalender-Adresse aus dem Obsidian-Schluesselbund ("" = keine). Nie anzeigen, nie loggen. */
  calendarSecret(): string {
    try {
      return this.app.secretStorage?.getSecret(CAL_SECRET)?.trim() ?? "";
    } catch {
      return "";
    }
  }

  get hasSecretStorage(): boolean {
    return !!this.app.secretStorage;
  }

  /** Adresse im Schluesselbund setzen ("" = entfernen). */
  setCalendarSecret(url: string): void {
    this.app.secretStorage?.setSecret(CAL_SECRET, url.trim());
  }

  /** Adresse aus .2ndbrain/calendar.config.json in den Schluesselbund uebernehmen. Die Datei
   *  bleibt - loeschen entscheidet der Nutzer (Rueckfall fuer Aufrufe ohne Plugin). */
  async importCalendarFromFile(): Promise<boolean> {
    const cfg = await readConfig(this.app.vault.adapter, CAL_CONFIG);
    const url = typeof cfg?.ical_url === "string" ? cfg.ical_url.trim() : "";
    if (!url || !this.app.secretStorage) return false;
    this.setCalendarSecret(url);
    return true;
  }

  /** Umgebung fuer jeden Engine-Lauf: die Kalender-Adresse aus dem Schluesselbund. */
  private engineEnv(): Record<string, string> {
    const url = this.calendarSecret();
    return url ? { VAULT_CALENDAR_URL: url } : {};
  }

  async readVaultConfig(path: string): Promise<Json | null> {
    return readConfig(this.app.vault.adapter, path);
  }

  /** In .2ndbrain/*.json schreiben (dieselben Dateien, die die Engine liest); danach Pfade,
   *  Modell und Ansichten nachziehen. false = Datei unlesbar, nichts geschrieben. Nur am Desktop:
   *  am Handy entstuende sonst eine zweite Fassung, die der Sync ueber die des Desktops legt. */
  async updateVaultConfig(path: string, patch: Record<string, unknown>): Promise<boolean> {
    if (!this.desktop) return false;
    const ok = await updateConfig(this.app.vault.adapter, path, patch);
    if (ok) {
      await this.loadVaultConfig();
      void this.refreshLlm();
      void this.refreshPaths().then(() => this.refreshViews());
    }
    return ok;
  }

  // ------------------------------------------------------------- Automatik (Desktop)

  scheduleAutomatik(): void {
    if (this.autoTimer !== null) window.clearInterval(this.autoTimer);
    this.autoTimer = null;
    const minutes = this.settings.autoIntervalMin;
    if (this.desktop && minutes > 0) {
      this.autoTimer = window.setInterval(() => void this.runAutomatik(false), minutes * 60_000);
    }
  }

  async runAutomatik(manual: boolean): Promise<void> {
    if (!this.desktop || (!manual && this.engine.busy)) return;
    if (this.engineStatus.state === "fehlt" && (await this.refreshEngine()).state === "fehlt") {
      if (manual) new Notice("2ndBrain: Die Engine fehlt – Einstellungen → 2ndBrain → Engine „Installieren“.");
      return;
    }
    if (manual) new Notice("2ndBrain: Automatik läuft …");
    this.updateStatus();
    const result = await this.engine.json<AutoResult>(["auto", "--json"]);
    this.lastAuto = { at: new Date(), result };
    const changed = (result?.steps ?? []).filter((s) => (s.changed ?? 0) > 0 && !s.skipped);
    if (!result) {
      new Notice("2ndBrain: Automatik lieferte kein Ergebnis – Python/Engine prüfen.");
    } else if (manual || changed.length) {
      const text = changed.length
        ? changed.map((s) => `${s.step}: ${s.detail ?? ""}`).join("\n")
        : result.skipped ?? "keine Änderungen";
      new Notice(`2ndBrain Automatik\n${text}`, 8000);
    }
    await this.refreshTasks();
    await this.refreshOpenTopics();
    if ([...this.cockpitBlocks].some((b) => b.view === "risiken")) {
      await this.loadRisks();
      await this.refreshViews();
    }
  }

  // ------------------------------------------------ Nacherfassen / Nachbereiten

  /** Fenster "Nacherfassen" - Nachbereiten laeuft nur aus dem Fenster heraus. */
  async openCapture(path: string): Promise<void> {
    const m = await this.index.meeting(path);
    if (!m) {
      new Notice("Keine Termin-Notiz.");
      return;
    }
    new CaptureModal(this.app, this, m).open();
  }

  /** Eine Aenderung an einer Termin-Notiz (src/core/nacherfassen.ts), unter der Sperre der Automatik. */
  private async applyCapture(path: string, op: (text: string) => CoreCaptureResult): Promise<CaptureResult> {
    const file = this.app.vault.getAbstractFileByPath(path);
    if (!capturable(path) || !(file instanceof TFile)) return { ok: false, grund: `Keine Termin-Notiz: ${path}` };
    if (!(await this.acquireAutoLock())) return { ok: false, grund: "Die Automatik läuft gerade – gleich noch einmal." };
    try {
      let result: CoreCaptureResult = { ok: false, grund: "Nicht geschrieben." };
      await this.app.vault.process(file, (current) => {
        result = op(current);
        return result.ok && result.text !== undefined ? result.text : current;
      });
      return { ok: result.ok, grund: result.grund, aktion: result.aktion };
    } finally {
      await this.releaseAutoLock();
    }
  }

  async captureNotes(path: string, text: string): Promise<CaptureResult> {
    const today = localIsoDate();
    return this.applyCapture(path, (t) => appendNotes(t, text, today));
  }

  async setEntfallen(path: string, on: boolean): Promise<CaptureResult> {
    return this.applyCapture(path, (t) => setEntfallen(t, on, null));
  }

  /** Ueberspringen: keine Notizen noetig (privat, gesellig) - `skip_meeting`. */
  async setSkip(path: string, on: boolean): Promise<CaptureResult> {
    return this.applyCapture(path, (t) => setSkip(t, on));
  }

  /** Nachbereiten vormerken (Handy): die Automatik am Desktop arbeitet es beim naechsten Lauf ab. */
  async requestWrapup(path: string, on = true): Promise<CaptureResult> {
    return this.applyCapture(path, (t) => setWrapupRequest(t, on));
  }

  /** Nachbereitung dieses Termins (Modell, Sync ins Themen-Log, Stand). Rueckgabe: Kurztext. */
  async wrapupNow(path: string, onStart?: () => void): Promise<string> {
    if (!this.desktop) return NUR_DESKTOP;
    const r = await this.engine.json<AutoResult>(
      ["auto", "--only", "nachbereiten,themenlog,stand", "--force", "--note", path, "--json"], { onStart });
    await this.refreshTasks();
    const w = r?.steps.find((s) => s.step === "nachbereiten");
    return r?.skipped ?? w?.detail ?? "Engine lieferte kein Ergebnis";
  }

  /** Nachbereitung im Hintergrund: das Fenster ist zu, die Seitenleiste zeigt
   *  wartet / laeuft / fertig, am Ende eine Meldung mit Link aufs Ergebnis. */
  startWrapup(meeting: MeetingInfo): void {
    const active = (j: WrapupJob) => j.state === "wartet" || j.state === "läuft";
    if (this.jobs.some((j) => j.meeting.path === meeting.path && active(j))) {
      new Notice("Diese Nachbereitung läuft schon.");
      return;
    }
    const job: WrapupJob = { meeting, state: this.engine.busy ? "wartet" : "läuft", detail: "",
                             started: new Date() };
    this.jobs = [job, ...this.jobs.filter((j) => j.meeting.path !== meeting.path)];
    void this.ensureTodayView();
    void this.refreshViews();
    void (async () => {
      const detail = await this.wrapupNow(meeting.path, () => {
        job.state = "läuft";
        void this.refreshViews();
      });
      const info = await this.undoInfo(meeting.path);
      job.state = info?.status === "nachbereitet" ? "fertig" : "fehler";
      job.detail = detail;
      const finished = this.jobs.filter((j) => !active(j));
      this.jobs = this.jobs.filter((j) => active(j) || finished.indexOf(j) < MAX_FINISHED_JOBS);
      await this.refreshViews();
      new Notice(createFragment((f) => {
        f.appendText(job.state === "fertig" ? `Nachbereitet: ${meeting.title} · `
          : `Nicht nachbereitet: ${meeting.title} (${detail}) · `);
        const a = f.createEl("a", { text: job.state === "fertig" ? "Ergebnis ansehen" : "Notiz öffnen", href: "#" });
        a.onclick = (e) => {
          e.preventDefault();
          if (job.state === "fertig") this.showResult(job);
          else void this.openAt(meeting.path, null);
        };
      }), 10_000);
    })();
  }

  showResult(job: WrapupJob): void {
    new WrapupResultModal(this.app, this, job.meeting, job.detail).open();
  }

  dismissJob(job: WrapupJob): void {
    this.jobs = this.jobs.filter((j) => j !== job);
    void this.refreshViews();
  }

  /** Nach "Rueckgaengig": der Auftrag ist erledigt. */
  forgetJobs(path: string): void {
    this.jobs = this.jobs.filter((j) => j.meeting.path !== path);
    void this.refreshViews();
  }

  /** Seitenleiste "Heute" anlegen, ohne den Fokus zu nehmen. */
  private async ensureTodayView(): Promise<void> {
    if (this.app.workspace.getLeavesOfType(VIEW_TYPE_TODAY).length) return;
    const leaf = this.app.workspace.getRightLeaf(false);
    if (leaf) await leaf.setViewState({ type: VIEW_TYPE_TODAY, active: false });
  }

  // ------------------------------------------------------- Termin -> Thema (Desktop)

  openTopicPicker(target: TopicTarget): void {
    if (this.desktop) new TopicPickerModal(this.app, this, target).open();
  }

  async topicState(target: TopicTarget): Promise<TopicState | null> {
    const args = target.kind === "note"
      ? ["thema", "--note", target.path, "--vorschlag", "--json"]
      : ["thema", "--serie", target.key, "--titel", target.title, "--vorschlag", "--json"];
    return this.engine.json<TopicState>(args, { timeoutMs: 120_000 });
  }

  /** Themen setzen; danach Vorbereitung und Stand nachziehen (im Hintergrund). */
  async setTopics(target: TopicTarget, slugs: string[], forSeries: boolean): Promise<CaptureResult> {
    const args = target.kind === "note"
      ? ["thema", "--note", target.path, "--set", slugs.join(","), ...(forSeries ? ["--reihe"] : []), "--json"]
      : ["thema", "--serie", target.key, "--titel", target.title, "--set", slugs.join(","), "--json"];
    const r = await this.engine.json<CaptureResult>(args, { timeoutMs: 60_000 });
    if (r?.ok) {
      // Sofort sichtbar: der Eintrag verschwindet aus "Ohne Thema", die Liste kommt gleich
      // frisch aus der Engine - nicht erst nach Vorbereitung und Stand (die brauchen das Modell).
      this.openTopics = withoutAssigned(this.openTopics, target, forSeries);
      await this.refreshViews();
      await this.refreshOpenTopics();
      void (async () => {
        await this.engine.run(["auto", "--only", "vorbereiten,stand", "--force", "--json"]);
        await this.refreshOpenTopics();
      })();
    }
    return r ?? { ok: false, grund: this.desktop ? "Engine antwortet nicht" : NUR_DESKTOP };
  }

  /** "Mit wem?" - Vorschlaege holen, dann auswaehlen lassen. */
  async openPersonPicker(path: string): Promise<void> {
    if (!this.desktop) return;
    const r = await this.engine.json<{ ok: boolean; vorschlaege: PersonSuggestion[] }>(
      ["thema", "--note", path, "--personen", "--json"], { timeoutMs: 120_000 });
    new PersonPickerModal(this.app, this, path, r?.vorschlaege ?? []).open();
  }

  /** Gegenueber eines Jourfix fuer die Reihe setzen; Vorbereitung nachziehen. */
  async setPersons(path: string, slugs: string[]): Promise<CaptureResult> {
    const r = await this.engine.json<CaptureResult>(
      ["thema", "--note", path, "--mit", slugs.join(","), "--json"], { timeoutMs: 60_000 });
    if (r?.ok) {
      void (async () => {
        await this.engine.run(["auto", "--only", "vorbereiten", "--force", "--json"]);
        await this.refreshViews();
      })();
      await this.refreshViews();
    }
    return r ?? { ok: false, grund: this.desktop ? "Engine antwortet nicht" : NUR_DESKTOP };
  }

  // ------------------------------------------------------------- Aufgaben

  /** Punkt abhaken - nur, wenn die Zeile noch dieser Punkt ist. */
  async completeTask(t: TaskInfo): Promise<CaptureResult> {
    if (!t.path || t.line === null) return { ok: false, grund: "Ohne Fundstelle" };
    const r = await this.completeInPlugin(t.path, t.line, t.text);
    await this.refreshTasks();
    return r;
  }

  /** [x] und ✅ heute (wie `2ndbrain aufgaben --done`), unter der Sperre der Automatik. */
  private async completeInPlugin(path: string, line: number, text: string): Promise<CompleteResult> {
    const file = this.app.vault.getAbstractFileByPath(path);
    if (!completable(path) || !(file instanceof TFile)) return { ok: false, grund: "Kein Punkt in einer Termin- oder Themen-Datei." };
    const today = localIsoDate();
    const check = completeInText(await this.app.vault.read(file), line, text, today);
    if (!check.ok || check.text === undefined) return { ok: check.ok, grund: check.grund, aktion: check.aktion };
    if (!(await this.acquireAutoLock())) return { ok: false, grund: "Die Automatik läuft gerade – gleich noch einmal." };
    try {
      let result: CompleteResult = check;
      await this.app.vault.process(file, (current) => {
        result = completeInText(current, line, text, today);
        return result.ok && result.text !== undefined ? result.text : current;
      });
      return { ok: result.ok, grund: result.grund, aktion: result.aktion };
    } finally {
      await this.releaseAutoLock();
    }
  }

  /** Sperre wie `auto.acquire_lock`: frei, wenn keine Datei da oder sie aelter als 30 min ist.
   *  Am Handy nie - dort laeuft keine Engine, und eine Sperrdatei vom Handy saehe der Desktop nach
   *  dem Sync als laufende Automatik. */
  private async acquireAutoLock(): Promise<boolean> {
    if (!this.desktop) return true;
    const adapter = this.app.vault.adapter;
    try {
      const st = await adapter.stat(AUTO_LOCK);
      if (st && Date.now() - st.mtime < AUTO_LOCK_MAX_AGE_MS) return false;
    } catch {
      // keine Sperre
    }
    await adapter.write(AUTO_LOCK, `${this.desktop.pid} ${localIsoDate()} (Obsidian-Plugin)\n`);
    return true;
  }

  private async releaseAutoLock(): Promise<void> {
    if (!this.desktop) return;
    try {
      await this.app.vault.adapter.remove(AUTO_LOCK);
    } catch {
      // schon weg
    }
  }

  // ---------------------------------------------------------- Rueckgaengig, Stand (Desktop)

  async undoInfo(path: string): Promise<UndoInfo | null> {
    if (!this.desktop) return null;
    return this.engine.json<UndoInfo>(["nacherfassen", "--note", path, "--info", "--json"], { timeoutMs: 60_000 });
  }

  async undoWrapup(path: string, force: boolean): Promise<CaptureResult> {
    if (!this.desktop) return { ok: false, grund: NUR_DESKTOP };
    const r = await this.engine.json<CaptureResult>(
      ["nacherfassen", "--note", path, "--undo", ...(force ? ["--force"] : []), "--json"], { timeoutMs: 120_000 });
    if (r?.ok) this.forgetJobs(path);
    return r ?? { ok: false, grund: "Engine antwortet nicht" };
  }

  private async undoFromCommand(path: string): Promise<void> {
    const info = await this.undoInfo(path);
    if (!info?.undo) {
      new Notice("Für diesen Termin ist keine Nachbereitung zum Zurücknehmen gespeichert.");
      return;
    }
    let r = await this.undoWrapup(path, false);
    if (!r.ok && r.geaendert && window.confirm("Die Notiz wurde nach der Nachbereitung geändert. "
        + "Trotzdem zurücknehmen? Deine geänderte Fassung wird gesichert.")) {
      r = await this.undoWrapup(path, true);
    }
    new Notice(r.ok ? "Nachbereitung zurückgenommen." : `Nicht zurückgenommen: ${r.grund ?? "Fehler"}`, 6000);
    if (r.ok && r.note && r.note !== path) await this.openAt(r.note, null);   // aus dem Archiv zurueckgeholt
    await this.refreshTasks();
  }

  async refreshStand(slug: string): Promise<void> {
    if (!this.desktop) return;
    const r = await this.engine.run(["stand", "--topic", slug]);
    new Notice(r.code === 0 ? "2ndBrain: Stand aktualisiert" : `2ndBrain: Stand fehlgeschlagen\n${r.stderr.slice(-300)}`);
    await this.refreshTasks();
  }

  // ---------------------------------------------------------------- Ansichten

  openQuickLook(): void {
    new TopicPersonSuggest(this.app, this).open();
  }

  /** Die Anleitung - eingebaut ins Plugin (views/anleitung.ts), als eigener Tab. */
  async openHelp(): Promise<void> {
    const leaf = this.app.workspace.getLeavesOfType(VIEW_TYPE_ANLEITUNG)[0] ?? this.app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: VIEW_TYPE_ANLEITUNG, active: true });
    await this.app.workspace.revealLeaf(leaf);
  }

  async activateToday(): Promise<void> {
    const existing = this.app.workspace.getLeavesOfType(VIEW_TYPE_TODAY)[0];
    const leaf = existing ?? this.app.workspace.getRightLeaf(false);
    if (!leaf) return;
    if (!existing) await leaf.setViewState({ type: VIEW_TYPE_TODAY, active: true });
    await this.app.workspace.revealLeaf(leaf);
  }

  /** Chat als eigener Tab in der rechten Seitenleiste - tauschbar mit "Heute", Rueckverweisen, Tags. */
  async activateChat(): Promise<void> {
    const existing = this.app.workspace.getLeavesOfType(VIEW_TYPE_CHAT)[0];
    const leaf = existing ?? this.app.workspace.getRightLeaf(false);
    if (!leaf) return;
    if (!existing) await leaf.setViewState({ type: VIEW_TYPE_CHAT, active: true });
    await this.app.workspace.revealLeaf(leaf);
  }

  /** Gross = im Hauptbereich (nicht in einer Seitenleiste). */
  chatIsLarge(leaf: WorkspaceLeaf): boolean {
    const root = leaf.getRoot();
    return root !== this.app.workspace.rightSplit && root !== this.app.workspace.leftSplit;
  }

  /** Chat klein (Tab in der rechten Seitenleiste) <-> gross (Hauptbereich, neben der offenen
   *  Notiz). Das Gespraech bleibt erhalten (chatState). */
  async toggleChatSize(): Promise<void> {
    const ws = this.app.workspace;
    const old = ws.getLeavesOfType(VIEW_TYPE_CHAT)[0];
    let leaf: WorkspaceLeaf | null;
    if (!old || !this.chatIsLarge(old)) {
      const main = ws.getMostRecentLeaf(ws.rootSplit);
      leaf = main ? ws.createLeafBySplit(main, "vertical") : ws.getLeaf("tab");
    } else {
      leaf = ws.getRightLeaf(false);
    }
    if (!leaf) return;
    await leaf.setViewState({ type: VIEW_TYPE_CHAT, active: true });
    old?.detach();
    await ws.revealLeaf(leaf);
  }

  /** Alle Chat-Ansichten neu zeichnen (nach einer Antwort, auch nach einem Wechsel klein/gross). */
  refreshChats(): void {
    for (const l of this.app.workspace.getLeavesOfType(VIEW_TYPE_CHAT)) {
      if (l.view instanceof ChatView) l.view.refresh();
    }
  }

  /** Datei oeffnen und (wenn bekannt) zur Zeile springen. */
  async openAt(path: string, line: number | null): Promise<void> {
    const file = this.app.vault.getAbstractFileByPath(path);
    if (!(file instanceof TFile)) return;
    const leaf = this.app.workspace.getLeaf(false);
    await leaf.openFile(file, line !== null ? { eState: { line } } : undefined);
  }
}
