// 公開投稿入口。金鑰只讀伺服器環境變數，不回傳原文。
import { createClient } from "jsr:@supabase/supabase-js@2";
import { redact } from "./redact.ts";

const PROMPT_VERSION = "v2_rules_user_submission_1";
const MODEL_NAME = "gemini-2.5-flash";
const MIN_CHARS = 80;
const MAX_CHARS = 4000;
const DAILY_LIMIT = 3;
const GAP_MS = 60 * 1000;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Content-Type": "application/json; charset=utf-8",
};

const CASE_NATURES = ["我是當事人", "我轉述親友", "我僅提供手法觀察"];
const OUTCOMES = ["有損失", "沒有損失", "不確定"];
const AMOUNTS = ["", "0", "1–1千", "1千–1萬", "1萬–10萬", "10萬–100萬", "100萬以上", "不願提供"];
const CHANNELS = ["電話", "簡訊", "LINE", "Facebook", "IG", "購物平台", "ATM／超商", "電子郵件", "Threads", "抖音 / TikTok", "交友 App", "賣貨便", "其他"];
const REGIONS = [
  "",
  "台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市", "基隆市", "新竹市", "嘉義市",
  "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣",
  "台東縣", "澎湖縣", "金門縣", "連江縣", "不願提供",
];

const AI_CASE = ["當事人親身經歷", "他人案例", "新聞報導", "手法討論", "防詐宣導"];
const AI_OUTCOME = ["successful", "attempted", "unknown"];
const AI_EVIDENCE = ["confirmed_case", "suspected_case", "related_article", "cannot_determine"];
const AI_CONFIDENCE = ["high", "medium", "low"];

type SubmissionInput = {
  display_name?: string;
  is_anonymous?: boolean;
  year_or_period?: string;
  region?: string;
  case_nature_self?: string;
  outcome_self?: string;
  amount_range?: string;
  channels?: string[];
  already_reported?: string;
  narrative?: string;
  consent_research?: boolean;
  consent_ai?: boolean;
  company_website?: string;
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: CORS });
}

function oneOf(value: unknown, allowed: string[]): string {
  const text = String(value || "").trim();
  return allowed.indexOf(text) >= 0 ? text : "";
}

async function sha256(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((item) => item.toString(16).padStart(2, "0")).join("");
}

function clientIp(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for") || "";
  const first = forwarded.split(",")[0].trim();
  return first || request.headers.get("cf-connecting-ip") || request.headers.get("x-real-ip") || "";
}

function handleName(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(4));
  let out = "匿名-";
  for (const value of bytes) out += alphabet[value % alphabet.length];
  return out;
}

function stringList(value: unknown, limit: number): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) {
    const text = redact(String(item || "")).trim().slice(0, 40);
    if (!text || out.indexOf(text) >= 0) continue;
    out.push(text);
    if (out.length >= limit) break;
  }
  return out;
}

function keepQuoted(quotes: unknown, narrative: string): { quotes: string[]; ok: boolean } {
  const kept: string[] = [];
  if (!Array.isArray(quotes)) return { quotes: kept, ok: false };
  for (const item of quotes) {
    const text = String(item || "").trim();
    if (!text || text.length > 200) continue;
    if (narrative.indexOf(text) < 0) continue;
    if (kept.indexOf(text) >= 0) continue;
    kept.push(text);
    if (kept.length >= 6) break;
  }
  return { quotes: kept, ok: kept.length > 0 };
}

function mentionsReportOnly(basis: string, narrative: string, reported: string): boolean {
  const label = basis.toLowerCase();
  if (label === "c5" || label === "report" || label.indexOf("報案") >= 0 || label.indexOf("提告") >= 0) {
    return true;
  }
  if (reported !== "是" && reported !== "yes") return false;
  const paid = /匯款|轉帳|交出|被盜|損失|付了|繳了|買了/.test(narrative);
  return !paid;
}

function applyAiRules(raw: Record<string, unknown>, narrative: string, reported: string) {
  const flags: string[] = ["self_report_no_independent_verification"];
  let evidence = AI_EVIDENCE.indexOf(String(raw.evidence_level || "")) >= 0
    ? String(raw.evidence_level)
    : "cannot_determine";
  let confidence = AI_CONFIDENCE.indexOf(String(raw.confidence || "")) >= 0
    ? String(raw.confidence)
    : "low";
  const basis = String(raw.confirmation_basis || "");
  if (evidence === "confirmed_case" && mentionsReportOnly(basis, narrative, reported)) {
    evidence = "suspected_case";
    flags.push("c5_report_is_not_confirmation");
  }
  if (evidence === "confirmed_case" && ["c1", "c2", "c3", "c4"].indexOf(basis) < 0) {
    evidence = "suspected_case";
    flags.push("confirmed_without_c1_c4_basis");
  }
  if (evidence === "suspected_case" && confidence === "high") {
    confidence = "medium";
    flags.push("suspected_confidence_capped");
  }
  const quoteCheck = keepQuoted(raw.evidence_quotes, narrative);
  if (!quoteCheck.ok) flags.push("quotes_not_verbatim");
  const platforms = stringList(raw.platforms, 8).filter((item) => {
    if (item === "165" || item.toLowerCase() === "ptt") return false;
    return narrative.indexOf(item) >= 0;
  });
  return {
    article_relevance: String(raw.article_relevance || ""),
    case_nature: AI_CASE.indexOf(String(raw.case_nature || "")) >= 0 ? String(raw.case_nature) : "",
    evidence_level: evidence,
    incident_outcome: AI_OUTCOME.indexOf(String(raw.incident_outcome || "")) >= 0
      ? String(raw.incident_outcome)
      : "unknown",
    outcome_subject: redact(String(raw.outcome_subject || "")).slice(0, 80),
    outcome_notes: redact(String(raw.outcome_notes || "")).slice(0, 400),
    scam_type: stringList(raw.scam_type, 8),
    scam_tactics: stringList(raw.scam_tactics, 8),
    victim_situation: redact(String(raw.victim_situation || "")).slice(0, 400),
    platforms,
    suspicious_signals: stringList(raw.suspicious_signals, 8),
    keywords: stringList(raw.keywords, 12),
    event_summary: redact(String(raw.event_summary || "")).slice(0, 500),
    evidence_quotes: quoteCheck.quotes,
    confidence,
    reasoning: redact(String(raw.reasoning || "")).slice(0, 1200),
    qa_flags: flags,
    source_type: "user_submission",
    ai_row_status: quoteCheck.ok ? "ready_for_review" : "qa_failed",
  };
}

function promptFor(narrative: string, meta: Record<string, unknown>): string {
  return [
    "你是研究助理，只根據下面這篇已經去識別化的群眾自述做結構化抽取。",
    "沒有寫到的金額、平台、機關、對話，留空陣列或 unknown／cannot_determine，禁止補造。",
    "source_type 必須是 user_submission。",
    "case_nature 只能是：當事人親身經歷、他人案例、新聞報導、手法討論、防詐宣導。",
    "incident_outcome 只能是 successful、attempted、unknown。錢已交出才是 successful。沒寫結果就是 unknown。",
    "evidence_level 只能是 confirmed_case、suspected_case、related_article、cannot_determine。",
    "confirmed_case 需要 C1 官方查證、C2 可驗證測試、C3 起訴或判決，或 C4 當事人具體描述依冒充指示交款且不像交易糾紛。",
    "C5：報案、提告、向 165 諮詢或備案本身不是 confirmed_case。若只有報案，confirmation_basis 填 c5，evidence_level 填 suspected_case。",
    "confidence 只能是 high、medium、low。suspected_case 不可為 high。",
    "platforms 只列接觸、冒用、交款管道，不要列事後求助的 165，也不要列 PTT，除非它就是接觸管道。",
    "evidence_quotes 每一則都必須是正文的逐字片段，不可改寫，不可使用遮蔽前的文字。",
    "只回傳 JSON，不要 Markdown。",
    "JSON 欄位：article_relevance, case_nature, evidence_level, incident_outcome, outcome_subject, outcome_notes, scam_type, scam_tactics, victim_situation, platforms, suspicious_signals, keywords, event_summary, evidence_quotes, confidence, reasoning, confirmation_basis, source_type。",
    "",
    "表單（只能當背景，不能拿來添增正文沒有的事實）：",
    JSON.stringify(meta),
    "",
    "正文：",
    narrative,
  ].join("\n");
}

async function callGemini(narrative: string, meta: Record<string, unknown>, apiKey: string) {
  const url = "https://generativelanguage.googleapis.com/v1beta/models/" +
    MODEL_NAME + ":generateContent?key=" + apiKey;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: AbortSignal.timeout(25000),
    body: JSON.stringify({
      contents: [{ role: "user", parts: [{ text: promptFor(narrative, meta) }] }],
      generationConfig: { temperature: 0, responseMimeType: "application/json" },
    }),
  });
  if (!response.ok) {
    throw new Error("gemini http " + response.status);
  }
  const payload = await response.json();
  const text = payload?.candidates?.[0]?.content?.parts?.[0]?.text || "";
  const cleaned = String(text).replace(/```json/gi, "").replace(/```/g, "").trim();
  const parsed = JSON.parse(cleaned);
  const usage = payload.usageMetadata || {};
  return {
    parsed,
    tokenInput: usage.promptTokenCount || null,
    tokenOutput: usage.candidatesTokenCount || null,
  };
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (request.method !== "POST") return json({ ok: false, message: "只接受 POST" }, 405);

  let body: SubmissionInput;
  try {
    body = await request.json();
  } catch (_err) {
    return json({ ok: false, message: "請送 JSON" }, 400);
  }
  if (body.company_website) return json({ ok: false, message: "無法接受這次送出" }, 400);
  if (body.consent_research !== true || body.consent_ai !== true) {
    return json({ ok: false, message: "請先勾選兩項同意" }, 400);
  }

  const narrativeRaw = String(body.narrative || "").trim();
  if (narrativeRaw.length < MIN_CHARS || narrativeRaw.length > MAX_CHARS) {
    return json({ ok: false, message: "經驗描述請介於 80 到 4000 字" }, 400);
  }
  const year = redact(String(body.year_or_period || "").trim()).slice(0, 40);
  if (!year) return json({ ok: false, message: "請填大約發生的時間" }, 400);
  const caseNature = oneOf(body.case_nature_self, CASE_NATURES);
  const outcome = oneOf(body.outcome_self, OUTCOMES);
  if (!caseNature || !outcome) return json({ ok: false, message: "請選擇你的角色與結果" }, 400);

  const narrative = redact(narrativeRaw);
  const channels = Array.isArray(body.channels)
    ? body.channels.map((item) => String(item)).filter((item) => CHANNELS.indexOf(item) >= 0)
    : [];
  const reported = oneOf(body.already_reported, ["是", "否", "不確定", ""]);
  const displayName = redact(String(body.display_name || "").trim()).slice(0, 20);
  const isAnonymous = body.is_anonymous !== false;
  const region = oneOf(body.region, REGIONS);
  const amount = oneOf(body.amount_range, AMOUNTS);

  const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) {
    return json({ ok: false, message: "投稿服務還沒完成設定" }, 500);
  }
  const admin = createClient(supabaseUrl, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const salt = Deno.env.get("SUBMISSION_HASH_SALT") || "anti-scam-submission-v0";
  const ipHash = await sha256(salt + "|ip|" + clientIp(request));
  const agentHash = await sha256(salt + "|ua|" + (request.headers.get("user-agent") || ""));
  const narrativeHash = await sha256(normalizeSpace(narrative));

  const dayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const { count, error: countError } = await admin
    .from("scam_submissions")
    .select("submission_id", { count: "exact", head: true })
    .eq("ip_hash", ipHash)
    .gte("created_at", dayAgo);
  if (countError) return json({ ok: false, message: "暫時無法送出，請稍後再試" }, 500);
  if ((count || 0) >= DAILY_LIMIT) {
    return json({ ok: false, message: "今天送出次數已達上限，請明天再試" }, 429);
  }
  const { data: recent } = await admin
    .from("scam_submissions")
    .select("created_at")
    .eq("ip_hash", ipHash)
    .order("created_at", { ascending: false })
    .limit(1);
  if (recent && recent[0]) {
    const delta = Date.now() - new Date(recent[0].created_at).getTime();
    if (delta >= 0 && delta < GAP_MS) {
      return json({ ok: false, message: "送出太快了，請稍等一分鐘" }, 429);
    }
  }
  const { data: dupes } = await admin
    .from("scam_submissions")
    .select("submission_id")
    .eq("narrative_hash", narrativeHash)
    .limit(1);

  let anonymousHandle = handleName();
  let saved: { submission_id: string } | null = null;
  let lastError = "";
  for (let attempt = 0; attempt < 5; attempt += 1) {
    anonymousHandle = handleName();
    const inserted = await admin
      .from("scam_submissions")
      .insert({
        status: "pending",
        ai_status: "pending_key",
        display_name: displayName,
        anonymous_handle: anonymousHandle,
        public_handle: !isAnonymous && displayName ? displayName : anonymousHandle,
        is_anonymous: isAnonymous,
        year_or_period: year,
        region,
        case_nature_self: caseNature,
        outcome_self: outcome,
        amount_range: amount,
        channels,
        already_reported: reported,
        narrative_redacted: narrative,
        narrative_hash: narrativeHash,
        possible_duplicate: Boolean(dupes && dupes.length),
        consent_research: true,
        consent_ai: true,
        source_type: "user_submission",
        ip_hash: ipHash,
        user_agent_hash: agentHash,
      })
      .select("submission_id")
      .single();
    if (!inserted.error && inserted.data) {
      saved = inserted.data;
      break;
    }
    lastError = inserted.error ? inserted.error.message : "";
  }
  if (!saved) {
    console.error("submission insert failed", lastError);
    return json({ ok: false, message: "寫入失敗" }, 500);
  }

  const geminiKey = Deno.env.get("GEMINI_API_KEY") || "";
  let aiStatus = "pending_key";
  if (!geminiKey) {
    return json({
      ok: true,
      submission_id: saved.submission_id,
      ai_status: aiStatus,
      message: "已送出，待研究小組審核。目前不會出現在公開排行榜。",
    });
  }

  const meta = {
    year_or_period: year,
    region,
    case_nature_self: caseNature,
    outcome_self: outcome,
    amount_range: amount,
    channels,
    already_reported: reported,
  };
  try {
    let result;
    try {
      result = await callGemini(narrative, meta, geminiKey);
    } catch (_err) {
      result = await callGemini(narrative, meta, geminiKey);
    }
    const checked = applyAiRules(result.parsed || {}, narrative, reported);
    aiStatus = checked.ai_row_status === "ready_for_review" ? "ready" : "qa_failed";
    const aiInsert = await admin.from("scam_submission_ai").insert({
      submission_id: saved.submission_id,
      model_name: MODEL_NAME,
      prompt_version: PROMPT_VERSION,
      source_type: "user_submission",
      article_relevance: checked.article_relevance,
      case_nature: checked.case_nature,
      evidence_level: checked.evidence_level,
      incident_outcome: checked.incident_outcome,
      outcome_subject: checked.outcome_subject,
      outcome_notes: checked.outcome_notes,
      scam_type: checked.scam_type,
      scam_tactics: checked.scam_tactics,
      victim_situation: checked.victim_situation,
      platforms: checked.platforms,
      suspicious_signals: checked.suspicious_signals,
      keywords: checked.keywords,
      event_summary: checked.event_summary,
      evidence_quotes: checked.evidence_quotes,
      confidence: checked.confidence,
      reasoning: checked.reasoning,
      qa_flags: checked.qa_flags,
      token_input: result.tokenInput,
      token_output: result.tokenOutput,
      status: checked.ai_row_status,
    });
    if (aiInsert.error) aiStatus = "error";
    await admin.from("scam_submissions").update({ ai_status: aiStatus }).eq("submission_id", saved.submission_id);
  } catch (_err) {
    aiStatus = "error";
    await admin.from("scam_submissions").update({ ai_status: "error" }).eq("submission_id", saved.submission_id);
  }

  return json({
    ok: true,
    submission_id: saved.submission_id,
    ai_status: aiStatus,
    message: "已送出，待研究小組審核。目前不會出現在公開排行榜。",
  });
});

function normalizeSpace(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}
