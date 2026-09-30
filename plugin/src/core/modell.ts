// Aufruf des lokalen Modells (llama.cpp, OpenAI-kompatibel) - wie in der Engine modell.py (`complete`),
// modell_ausgabe.py (`llama_params`, `strip_think`) und fremdtext.py (`entschaerfen`). Das HTTP selbst
// kommt von aussen: in Obsidian requestUrl (Desktop und Handy), in Tests ein Ersatz.

/** Nachricht im OpenAI-Format; `tool_calls` (Antwort des Modells) und `tool_call_id` (Ergebnis eines
 *  Werkzeugs) nur in der Schleife der Werkzeuge (core/chat.ts). */
export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  tool_calls?: { id: string; type: "function"; function: { name: string; arguments: string } }[];
  tool_call_id?: string;
}

/** Ein Werkzeug, wie das Modell es sieht (Name, Beschreibung, JSON-Schema der Parameter). */
export interface WerkzeugSpec { name: string; beschreibung: string; parameter: Record<string, unknown> }
export interface WerkzeugAufruf { id: string; name: string; argumente: string }
/** Antwort des Modells in der Schleife: Text und/oder Werkzeug-Aufrufe. */
export interface ModellZug { text: string; aufrufe: WerkzeugAufruf[] }

export type HttpPost = (url: string, body: unknown, timeoutMs: number) => Promise<{ status: number; json: unknown; text: string }>;

export class LlmError extends Error {}

/** Sampling wie `llama_params`: Denk-Modus aus, Temperatur niedrig. */
export function llamaParams(temperature: number): Record<string, unknown> {
  return { temperature, top_p: 0.9, enable_thinking: false, chat_template_kwargs: { enable_thinking: false } };
}

const THINK_RE = /<think\b[^>]*>[\s\S]*?<\/think\s*>/gi;
const THINK_OPEN_RE = /<think\b[^>]*>[\s\S]*$/i;

/** <think>-Bloecke entfernen, auch unbalancierte (abgeschnittene Antwort). */
export function stripThink(text: string): string {
  return text.replace(THINK_RE, "").replace(THINK_OPEN_RE, "");
}

// Zeilenanfang eines Codezauns - auch eingerueckt, im Zitat (>) oder hinter einem Listenpunkt
const ZAUN = /^([ \t>]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+[ \t>]*)*)(`{3,}|~{3,})[ \t]*([^\s`]*)([^\n]*)$/gm;

/** Codeblock-Sprachen, die ein Plugin beim Anzeigen ausfuehrt (Dataview-JS, JS Engine, run-...). */
export function executable(lang: string): boolean {
  const s = lang.toLowerCase();
  return s === "dataviewjs" || s.startsWith("js-engine") || s.startsWith("run-");
}

/** Fremdtext entschaerfen: ausfuehrbare Codebloecke werden gewoehnliche (```text dataviewjs). */
export function defuse(text: string): string {
  if (!text || (!text.includes("```") && !text.includes("~~~"))) return text;
  return text.replace(ZAUN, (all: string, vor: string, zaun: string, lang: string, rest: string) =>
    (executable(lang) ? `${vor}${zaun}text ${lang}${rest}` : all));
}

// HTML, das beim Anzeigen etwas laedt oder ausfuehrt - nur <br> bleibt
const HTML_TAG = /<(?!br\s*\/?>)(\/?[a-zA-Z][\w-]*)/g;
const BILD_EXTERN = /!\[([^\]]*)\]\(\s*<?(?:https?:|\/\/|data:)[^)]*\)/gi;

/** Antwort des Modells entschaerfen, bevor Obsidian sie zeichnet: Bilder von aussen und HTML werden
 *  Text. Sonst koennte eine praeparierte Mail im Vault das Modell dazu bringen, Inhalte in die Adresse
 *  eines Bildes zu schreiben, das Obsidian beim Anzeigen laedt. Codebloecke bleiben unberuehrt. */
export function entschaerfeBilder(text: string): string {
  let out = "";
  let last = 0;
  const fix = (s: string) => s.replace(BILD_EXTERN, (_all, alt: string) => `[Bild${alt ? `: ${alt}` : ""}]`)
    .replace(HTML_TAG, "&lt;$1");
  for (const m of text.matchAll(/```[\s\S]*?(?:```|$(?![\s\S]))/g)) {
    out += fix(text.slice(last, m.index)) + m[0];
    last = (m.index ?? 0) + m[0].length;
  }
  return out + fix(text.slice(last));
}

async function anfrage(post: HttpPost, conn: { url: string; model: string; timeoutS: number },
                       payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  if (!conn.url) throw new LlmError("kein Modell-Server eingetragen (.2ndbrain/llm.config.json: \"url\")");
  let r;
  try {
    r = await post(`${conn.url.replace(/\/$/, "")}/v1/chat/completions`, { model: conn.model, stream: false, ...payload },
                   conn.timeoutS * 1000);
  } catch (e) {
    throw new LlmError(String(e instanceof Error ? e.message : e));
  }
  if (r.status !== 200) {
    const msg = (r.json as { error?: { message?: string } } | null)?.error?.message;
    throw new LlmError(msg ? `HTTP ${r.status}: ${msg}` : `HTTP ${r.status}`);
  }
  return ((r.json as { choices?: { message?: Record<string, unknown> }[] } | null)?.choices?.[0]?.message) ?? {};
}

/** Ein Chat-Aufruf; Rueckgabe: Text der Antwort, entschaerft. */
export async function complete(post: HttpPost, conn: { url: string; model: string; timeoutS: number },
                               messages: ChatMessage[], opts: { maxTokens: number; temperature: number }): Promise<string> {
  const m = await anfrage(post, conn, { messages, max_tokens: opts.maxTokens, ...llamaParams(opts.temperature) });
  return defuse(typeof m.content === "string" ? m.content : "");
}

// Werkzeug-Aufruf als Text, falls der Server ihn nicht selbst erkennt - als JSON
// (<tool_call>{"name": …, "arguments": …}</tool_call>) oder im XML-Format neuerer Qwen-Modelle
// (<tool_call><function=name><parameter=schluessel>wert</parameter></function></tool_call>)
const TOOL_CALL_TEXT = /<tool_call>\s*(\{[\s\S]*?\})\s*<\/tool_call>/g;
const TOOL_CALL_XML = /<tool_call>\s*<function=([\w-]+)>([\s\S]*?)<\/function>\s*(?:<\/tool_call>|$)/g;
const TOOL_PARAM_XML = /<parameter=([\w-]+)>\s*([\s\S]*?)\s*<\/parameter>/g;
const TOOL_CALL_REST = /<tool_call>[\s\S]*?(?:<\/tool_call>|$)/g;

/** Werkzeug-Aufrufe, die als Text in der Antwort stehen (JSON oder XML). */
export function aufrufeImText(text: string): WerkzeugAufruf[] {
  const out: WerkzeugAufruf[] = [];
  for (const t of text.matchAll(TOOL_CALL_TEXT)) {
    try {
      const j = JSON.parse(t[1]) as { name?: string; arguments?: unknown };
      if (j.name) out.push({ id: `call_t${out.length}`, name: j.name, argumente: JSON.stringify(j.arguments ?? {}) });
    } catch { /* kein Aufruf */ }
  }
  for (const t of text.matchAll(TOOL_CALL_XML)) {
    const args: Record<string, string> = {};
    for (const p of t[2].matchAll(TOOL_PARAM_XML)) args[p[1]] = p[2];
    out.push({ id: `call_t${out.length}`, name: t[1], argumente: JSON.stringify(args) });
  }
  return out;
}

/** Text ohne Werkzeug-Aufrufe - fuer eine Antwort, die keine mehr enthalten darf. */
export function ohneAufrufe(text: string): string {
  return text.replace(TOOL_CALL_REST, "").trim();
}

/** Wie frei das Modell in einem Schritt ist: `auto` antworten oder nachschlagen, `none` antworten - die
 *  Werkzeuge bleiben dann im Prompt (der Server nimmt ihn weiter aus dem Zwischenspeicher), aufrufen darf
 *  das Modell sie nicht mehr. (`required` setzte der Server nicht verlaesslich durch - wo es darauf
 *  ankommt, schlaegt der Code selbst vorab nach: chat.vorabAbfrage.) */
export type Werkzeugwahl = "auto" | "none";

/** Ein Schritt der Schleife: das Modell antwortet oder ruft Werkzeuge auf. Text ohne <think>, entschaerft. */
export async function completeTools(post: HttpPost, conn: { url: string; model: string; timeoutS: number },
                                    messages: ChatMessage[], tools: WerkzeugSpec[],
                                    opts: { maxTokens: number; temperature: number; wahl: Werkzeugwahl }): Promise<ModellZug> {
  const antworten = opts.wahl === "none";
  const m = await anfrage(post, conn, {
    messages, max_tokens: opts.maxTokens, ...llamaParams(opts.temperature),
    tools: tools.map((t) => ({ type: "function", function: { name: t.name, description: t.beschreibung, parameters: t.parameter } })),
    tool_choice: opts.wahl, parallel_tool_calls: true,
  });
  let text = stripThink(typeof m.content === "string" ? m.content : "");
  const aufrufe: WerkzeugAufruf[] = [];
  for (const [i, c] of (Array.isArray(m.tool_calls) ? m.tool_calls : []).entries()) {
    const f = (c as { function?: { name?: string; arguments?: unknown } }).function;
    if (!f?.name) continue;
    const args = typeof f.arguments === "string" ? f.arguments : JSON.stringify(f.arguments ?? {});
    aufrufe.push({ id: String((c as { id?: string }).id || `call_${i}`), name: f.name, argumente: args });
  }
  if (!aufrufe.length && !antworten) aufrufe.push(...aufrufeImText(text));
  // Aufrufe als Text gehoeren nie in eine Antwort (auch nicht, wenn das Modell trotz Verbot eins schreibt)
  text = ohneAufrufe(text);
  return { text: defuse(text), aufrufe: antworten ? [] : aufrufe };
}
