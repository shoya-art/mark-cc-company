/**
 * 会員のアクションを Database Webhook 経由で受け取り、LINE Messaging API（push）で通知する。
 *
 * Secrets（Supabase Dashboard → Edge Functions → Secrets）:
 *   LINE_CHANNEL_ACCESS_TOKEN … チャネルアクセストークン（長期）
 *   LINE_TO_USER_ID           … 通知先のユーザーID（あなたのLINEユーザーID）
 *   SUPABASE_URL
 *   SERVICE_ROLE_KEY または SUPABASE_SERVICE_ROLE_KEY … profiles 参照用
 *
 * 任意:
 *   WEBHOOK_SECRET … 設定した場合、リクエストヘッダー x-webhook-secret と一致させる
 *   CHECKIN_NOTIFY_ON_UPDATE … "true" のときのみ、checkins の UPDATE でも通知（省略時は INSERT のみ）
 *   DAILY_REPORT_NOTIFY_ON_UPDATE … "true" のときのみ、daily_reports の UPDATE でも通知（省略時は INSERT のみ）
 *   DIARY_NOTIFY_ON_UPDATE … "true" のときのみ、diary_entries の UPDATE でも通知（省略時は INSERT のみ）
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.8";

type WebhookPayload = {
  type?: string;
  table?: string;
  schema?: string;
  record?: Record<string, unknown> | null;
  old_record?: Record<string, unknown> | null;
};

const WEBHOOK_SECRET = (Deno.env.get("WEBHOOK_SECRET") ?? "").trim();
const LINE_CHANNEL_ACCESS_TOKEN = (Deno.env.get("LINE_CHANNEL_ACCESS_TOKEN") ?? "").trim();
const LINE_TO_USER_ID = (Deno.env.get("LINE_TO_USER_ID") ?? "").trim();
const SUPABASE_URL = (Deno.env.get("SUPABASE_URL") ?? "").trim();
const SERVICE_ROLE_KEY = (
  Deno.env.get("SERVICE_ROLE_KEY") ?? Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? ""
).trim();

const CHECKIN_NOTIFY_ON_UPDATE =
  (Deno.env.get("CHECKIN_NOTIFY_ON_UPDATE") ?? "").toLowerCase() === "true";
const DAILY_REPORT_NOTIFY_ON_UPDATE =
  (Deno.env.get("DAILY_REPORT_NOTIFY_ON_UPDATE") ?? "").toLowerCase() === "true";
const DIARY_NOTIFY_ON_UPDATE =
  (Deno.env.get("DIARY_NOTIFY_ON_UPDATE") ?? "").toLowerCase() === "true";

/** 講義ID → タイトル（未登録は ID のまま） */
const LECTURE_TITLES: Record<string, string> = {
  "1-1": "復縁の全体像とは？",
  "1-2": "復縁の全体像の理解",
  "2-1": "なぜ復縁に自己肯定感が必要なのか？",
  "2-2": "あなたの生活に影響を与える自己肯定感",
  "3-1": "自己肯定感ってそもそも何？",
  "3-2": "あなたの自己肯定感をチェックする",
  "3-3": "自己肯定感のチェックシート",
  "3-4": "自己肯定感が低い人の特徴",
  "3-5": "彼の言葉に対する受け取り方",
  "3-6": "自分軸で生きることの大切さ",
  "3-7a": "ワーク（自己肯定感）",
  "3-7b": "自己肯定感は常に変化する",
  "3-9": "ワーク（自己肯定感）",
  "4-1": "彼との関係が上手くいかなった理由",
  "4-2": "辛い事があった時の対処法",
  "4-3": "ワーク（自己肯定感をプラスに）",
  "4-4": "現在の自分に目を向ける",
  "4-5": "ワーク（自己肯定感をプラスに）",
  "4-6": "自分の過去を振り返る",
  "4-7": "ワーク（自己肯定感をプラスに）",
  "4-7b": "ワーク（自己肯定感をプラスに）",
  "4-8": "あなただけの軸を作る",
  "4-9": "ワーク（自己肯定感をプラスに）",
  "4-10": "ワーク（自己肯定感をプラスに）",
  "4-11": "彼との正しい距離を知る",
  "4-12": "ワーク（自己肯定感をプラスに）",
  "4-13": "彼との理想の未来を描いてみる",
  "4-14": "ワーク（自己肯定感をプラスに）",
  "4-15": "幸せを邪魔する自分を倒す",
  "4-16": "ワーク（自己肯定感をプラスに）",
  "4-17": "小さな成長を認めてあげる",
  "4-18": "ワーク（自己肯定感をプラスに）",
  "5-1": "彼への素直な気持ちをチェック",
  "5-2": "彼をより理解しよう",
  "5-3": "ワーク（復縁に向けた行動）",
  "5-6": "彼と別れた原因分析を行う",
  "5-7": "ワーク（復縁に向けた行動）",
  "5-8a": "ワーク（復縁に向けた行動）",
  "5-8b": "失敗を許容する",
  "5-9": "新しい事にどんどん挑戦する",
  "5-10": "今後に向けて",
  "test-lecture-3": "テスト講義",
};

const corsHeaders: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-webhook-secret",
};

function lectureIdAndTitle(id: string): string {
  const title = LECTURE_TITLES[id];
  return title ? `${id} ${title}` : id;
}

function truncate(s: string, max: number): string {
  const t = s.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  return t.slice(0, max) + "…";
}

/** DBの timestamptz は UTC。日本時間（JST）で表示する */
function formatJaDateTimeJST(iso: string | undefined | null): string {
  if (!iso) return "（日時なし）";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  // en-CA で数字が安定（ja-JP 環境差で hour が取れないケースを避ける）
  const f = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: false,
  });
  const parts = f.formatToParts(d);
  const pick = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? "";
  const y = pick("year");
  const mo = pick("month");
  const day = pick("day");
  const h = pick("hour");
  const min = pick("minute").padStart(2, "0");
  return `${y}年${mo}月${day}日 ${h}時${min}分`;
}

/** 気分スタンプが二重（同じ絵文字連続）のとき1つに。Intl.Segmenter は Edge Deno で未対応のことがあるため使わない */
function moodSingleDisplay(mood: unknown): string {
  if (mood == null) return "";
  const s = String(mood).trim();
  if (!s) return "";
  const chars = [...s];
  if (chars.length >= 2 && chars.every((c) => c === chars[0])) return chars[0] ?? s;
  return s;
}

/** ワーク回答 JSON を読みやすい1行〜数行に要約（失敗時は原文トリム） */
function summarizeWorkAnswer(raw: string, max: number): string {
  const t = raw.replace(/\s+/g, " ").trim();
  if (!t) return "";
  try {
    const j = JSON.parse(raw) as Record<string, unknown>;
    if (Array.isArray(j.scores)) {
      const nums = j.scores.map((x) => Number(x)).filter((n) => !Number.isNaN(n));
      const total = j.total != null ? ` 合計:${j.total}` : "";
      return truncate(`スコア: [${nums.join(", ")}]${total}`, max);
    }
    if (typeof j === "object" && j !== null) {
      return truncate(JSON.stringify(j).replace(/\s+/g, " "), max);
    }
  } catch {
    /* プレーンテキスト */
  }
  return truncate(t, max);
}

function dailyReportAllFields(record: Record<string, unknown>): string {
  const blocks: string[] = [];
  const add = (label: string, v: unknown, eachMax = 800) => {
    if (v == null || v === "") return;
    const s = String(v).trim();
    if (!s) return;
    blocks.push(`${label}\n${truncate(s, eachMax)}`);
  };
  add("【良かったこと①】", record.good1);
  add("【良かったこと②】", record.good2);
  add("【良かったこと③】", record.good3);
  add("【自分へのねぎらいの言葉】", record.self_praise);
  add("【彼・状況に対して取った行動】", record.action_toward);
  add("【成長を感じたこと】", record.growth);
  add("【投げ出したくなった瞬間】", record.give_up_moment);
  add("【自分の弱み】", record.weak_point);
  if (record.self_esteem_score != null && record.self_esteem_score !== "") {
    blocks.push(`【自己肯定感スコア（1〜10）】\n${String(record.self_esteem_score)}`);
  }
  if (record.positive_score != null && record.positive_score !== "") {
    blocks.push(`【前向きさスコア（1〜10）】\n${String(record.positive_score)}`);
  }
  if (blocks.length === 0) return "（日報レコードにテキストがありません。Webhookのペイロードを確認してください）";
  return blocks.join("\n\n");
}

async function linePush(text: string): Promise<{ ok: boolean; detail?: string }> {
  if (!LINE_CHANNEL_ACCESS_TOKEN || !LINE_TO_USER_ID) {
    return { ok: false, detail: "LINE_CHANNEL_ACCESS_TOKEN または LINE_TO_USER_ID が未設定です" };
  }
  const res = await fetch("https://api.line.me/v2/bot/message/push", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${LINE_CHANNEL_ACCESS_TOKEN}`,
    },
    body: JSON.stringify({
      to: LINE_TO_USER_ID,
      messages: [{ type: "text", text: text.slice(0, 4500) }],
    }),
  });
  if (!res.ok) {
    const t = await res.text();
    return { ok: false, detail: `LINE API ${res.status}: ${t}` };
  }
  return { ok: true };
}

async function memberDisplayName(
  sb: ReturnType<typeof createClient>,
  userId: string,
): Promise<string> {
  const { data: profile } = await sb.from("profiles").select("name, email").eq("id", userId).maybeSingle();
  const name = (profile?.name as string | undefined)?.trim();
  const email = (profile?.email as string | undefined)?.trim();
  if (name && email) return `${name}（${email}）`;
  if (name) return name;
  if (email) return email;
  return `ユーザー ${userId.slice(0, 8)}…`;
}

/** メッセージを組み立てる。null のときは通知スキップ */
function buildLineMessage(
  table: string,
  type: string,
  record: Record<string, unknown>,
): string | null {
  const userNamePlaceholder = "{{NAME}}";
  const t = type.toUpperCase();

  switch (table) {
    case "lecture_views": {
      if (t !== "INSERT") return null;
      const lectureId = String(record.lecture_id ?? "不明");
      const viewedAt = String(record.viewed_at ?? "");
      return [
        "🎓 新しい講義視聴がありました！",
        "",
        "👤 名前",
        userNamePlaceholder,
        "",
        "📚 講義",
        lectureIdAndTitle(lectureId),
        "",
        "⏰ 視聴完了",
        formatJaDateTimeJST(viewedAt),
      ].join("\n");
    }
    case "work_answers": {
      if (t !== "INSERT" && t !== "UPDATE") return null;
      const lectureId = String(record.lecture_id ?? "不明");
      const head =
        t === "INSERT" ? "📝 新しいワーク回答がありました！" : "📝 ワーク回答が更新されました！";
      const answerRaw = String(record.answer ?? "");
      const answerBlock = summarizeWorkAnswer(answerRaw, 2000);
      return [
        head,
        "",
        "👤 名前",
        userNamePlaceholder,
        "",
        "📚 講義",
        lectureIdAndTitle(lectureId),
        "",
        "✍️ 回答内容",
        answerBlock || "（回答が空です）",
      ].join("\n");
    }
    case "checkins": {
      if (t === "UPDATE" && !CHECKIN_NOTIFY_ON_UPDATE) return null;
      if (t !== "INSERT" && t !== "UPDATE") return null;
      const action = t === "INSERT" ? "チェックインを登録しました" : "チェックインを更新しました";
      const date = String(record.date ?? "");
      const mood = record.mood != null ? String(record.mood) : "-";
      const act = record.action != null ? String(record.action) : "-";
      const state = record.state != null ? String(record.state) : "-";
      const note = record.note ? truncate(String(record.note), 120) : "";
      const tags = Array.isArray(record.tags) && record.tags.length
        ? record.tags.join(", ")
        : "";
      return [
        "✅ " + action,
        "",
        "👤 " + userNamePlaceholder,
        "",
        "📅 日付: " + date,
        `気分 / 行動 / 状態: ${mood} / ${act} / ${state}`,
        tags ? "🏷️ " + tags : "",
        note ? "💬 " + note : "",
      ].filter(Boolean).join("\n");
    }
    case "daily_reports": {
      if (t === "UPDATE" && !DAILY_REPORT_NOTIFY_ON_UPDATE) return null;
      if (t !== "INSERT" && t !== "UPDATE") return null;
      const head = t === "INSERT" ? "📘 新しい日報が届きました！" : "📘 日報が更新されました！";
      const date = String(record.date ?? "");
      const body = dailyReportAllFields(record);
      return [
        head,
        "",
        "👤 名前",
        userNamePlaceholder,
        "",
        "📅 日付",
        date,
        "",
        "📝 内容",
        body,
      ].join("\n");
    }
    case "diary_entries": {
      if (t === "UPDATE" && !DIARY_NOTIFY_ON_UPDATE) return null;
      if (t !== "INSERT" && t !== "UPDATE") return null;
      const head = t === "INSERT" ? "📔 新しい日記投稿があります！" : "📔 日記が更新されました！";
      const date = String(record.date ?? "");
      const moodOne = moodSingleDisplay(record.mood);
      const preview = truncate(String(record.content ?? ""), 2500);
      const lines = [
        head,
        "",
        "👤 名前",
        userNamePlaceholder,
        "",
        "📅 日付",
        date,
      ];
      if (moodOne) {
        lines.push("", "😊 気分", moodOne);
      }
      lines.push("", "📝 内容", preview || "（本文なし）");
      return lines.join("\n");
    }
    case "question_memos": {
      if (t !== "INSERT") return null;
      const lectureId = String(record.lecture_id ?? "不明");
      const q = truncate(String(record.question ?? ""), 400);
      return [
        "❓ 講義に質問メモが投稿されました",
        "",
        "👤 名前",
        userNamePlaceholder,
        "",
        "📚 講義",
        lectureIdAndTitle(lectureId),
        "",
        q,
      ].join("\n");
    }
    default:
      return null;
  }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  if (WEBHOOK_SECRET) {
    const sent = (req.headers.get("x-webhook-secret") ?? "").trim();
    if (sent !== WEBHOOK_SECRET) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }
  }

  let payload: WebhookPayload;
  try {
    payload = (await req.json()) as WebhookPayload;
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const table = payload.table ?? "";
  const type = (payload.type ?? "").toUpperCase();
  const record = payload.record;

  if (!table || !record || type === "DELETE") {
    return new Response(JSON.stringify({ ok: true, skipped: true, reason: "no table or record or DELETE" }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const userId = record.user_id == null ? "" : String(record.user_id).trim();
  if (!userId) {
    return new Response(JSON.stringify({ ok: true, skipped: true, reason: "no user_id on record" }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  if (!SUPABASE_URL || !SERVICE_ROLE_KEY) {
    return new Response(JSON.stringify({ error: "SUPABASE_URL または SERVICE_ROLE_KEY が未設定です" }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  try {
    const template = buildLineMessage(table, type, record);
    if (template === null) {
      return new Response(JSON.stringify({ ok: true, skipped: true, table, type }), {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    const sb = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, {
      auth: { autoRefreshToken: false, persistSession: false },
    });
    const displayName = await memberDisplayName(sb, userId);
    const message = template.replaceAll("{{NAME}}", displayName).trim() || "（通知本文が空でした）";

    const lineRes = await linePush(message);
    if (!lineRes.ok) {
      return new Response(JSON.stringify({ ok: false, line: lineRes }), {
        status: 502,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    return new Response(JSON.stringify({ ok: true, line: lineRes }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const stack = e instanceof Error ? e.stack : undefined;
    console.error("[notify-instructor]", msg, stack ?? "");
    return new Response(JSON.stringify({ ok: false, error: msg }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
