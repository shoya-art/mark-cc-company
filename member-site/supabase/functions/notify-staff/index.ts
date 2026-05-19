import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.8";

type WebhookPayload = {
  type: "INSERT" | "UPDATE" | "DELETE";
  table: string;
  schema: string;
  record: Record<string, unknown> | null;
  old_record: Record<string, unknown> | null;
};

const corsHeaders: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-staff-webhook-secret",
};

function truncate(s: string, max: number): string {
  const t = s.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  return t.slice(0, max) + "…";
}

function tableLabel(table: string): string {
  const map: Record<string, string> = {
    diary_entries: "復縁日記",
    question_memos: "講義への質問",
    lecture_views: "講義視聴・完了",
    work_answers: "ワーク回答",
    checkins: "チェックイン",
    daily_reports: "日報",
  };
  return map[table] ?? table;
}

function buildMessageLines(
  type: string,
  table: string,
  record: Record<string, unknown>,
  memberName: string,
): string[] {
  const actionLabel = type === "INSERT" ? "（新規）" : type === "UPDATE" ? "（更新）" : "";
  const header = `【リリー会員サイト】${tableLabel(table)}${actionLabel}`;
  const who = `会員: ${memberName}`;

  switch (table) {
    case "diary_entries": {
      const date = String(record.date ?? "");
      const mood = record.mood ? ` 気分: ${record.mood}` : "";
      const preview = truncate(String(record.content ?? ""), 120);
      return [header, who, `日付: ${date}${mood}`, preview ? `内容: ${preview}` : ""].filter(
        Boolean,
      ) as string[];
    }
    case "question_memos": {
      const lid = String(record.lecture_id ?? "");
      const q = truncate(String(record.question ?? ""), 200);
      return [header, who, `講義ID: ${lid}`, q ? `質問: ${q}` : ""].filter(Boolean) as string[];
    }
    case "lecture_views": {
      const lid = String(record.lecture_id ?? "");
      return [header, who, `講義ID: ${lid}`, "講義を完了しました（初回の記録です）"];
    }
    case "work_answers": {
      const lid = String(record.lecture_id ?? "");
      const ans = truncate(String(record.answer ?? ""), 200);
      return [header, who, `講義ID: ${lid}`, ans ? `回答抜粋: ${ans}` : ""].filter(
        Boolean,
      ) as string[];
    }
    case "checkins": {
      const date = String(record.date ?? "");
      const mood = record.mood != null ? `気分:${record.mood}` : "";
      const action = record.action != null ? `行動:${record.action}` : "";
      const state = record.state != null ? `状態:${record.state}` : "";
      const note = record.note ? truncate(String(record.note), 100) : "";
      return [
        header,
        who,
        `日付: ${date}`,
        [mood, action, state].filter(Boolean).join(" "),
        note ? `メモ: ${note}` : "",
      ].filter(Boolean) as string[];
    }
    case "daily_reports": {
      const date = String(record.date ?? "");
      return [header, who, `日付: ${date}`, "日報が保存されました"];
    }
    default:
      return [header, who, truncate(JSON.stringify(record), 280)];
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

  const secret = Deno.env.get("STAFF_WEBHOOK_SECRET");
  const sent = req.headers.get("x-staff-webhook-secret") ?? "";
  if (!secret || sent !== secret) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  let payload: WebhookPayload;
  try {
    payload = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON" }), {
      status: 400,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const { type, table, record, old_record: _old } = payload;

  if (!table || !record || type === "DELETE") {
    return new Response(JSON.stringify({ ok: true, skipped: true }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  if (table === "lecture_views" && type !== "INSERT") {
    return new Response(JSON.stringify({ ok: true, skipped: true, reason: "lecture_views_updates_ignored" }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const userId = record.user_id as string | undefined;
  if (!userId) {
    return new Response(JSON.stringify({ ok: true, skipped: true }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !serviceKey) {
    return new Response(JSON.stringify({ error: "Server misconfigured" }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const sb = createClient(supabaseUrl, serviceKey);
  const { data: profile } = await sb.from("profiles").select("name, email").eq("id", userId).maybeSingle();

  const displayName =
    (profile?.name && String(profile.name).trim()) ||
    (profile?.email && String(profile.email)) ||
    `ユーザー ${userId.slice(0, 8)}…`;

  const text = buildMessageLines(type, table, record, displayName).join("\n");

  const slackUrl = Deno.env.get("SLACK_WEBHOOK_URL");
  const lineToken = Deno.env.get("LINE_NOTIFY_TOKEN");
  const discordUrl = Deno.env.get("DISCORD_WEBHOOK_URL");

  const tasks: Promise<Response>[] = [];

  if (slackUrl) {
    tasks.push(
      fetch(slackUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }),
    );
  }

  if (discordUrl) {
    tasks.push(
      fetch(discordUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: text }),
      }),
    );
  }

  if (lineToken) {
    tasks.push(
      fetch("https://notify-api.line.me/api/notify", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${lineToken}`,
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        body: new URLSearchParams({ message: text }).toString(),
      }),
    );
  }

  if (tasks.length === 0) {
    return new Response(
      JSON.stringify({
        ok: true,
        warning: "通知先が未設定です。SLACK_WEBHOOK_URL / LINE_NOTIFY_TOKEN / DISCORD_WEBHOOK_URL のいずれかを Secrets に設定してください。",
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }

  const results = await Promise.all(tasks);
  const failed = results.filter((r) => !r.ok);
  if (failed.length > 0) {
    const detail = await Promise.all(
      failed.map(async (r) => ({ status: r.status, body: await r.text().catch(() => "") })),
    );
    return new Response(JSON.stringify({ ok: false, notify_errors: detail }), {
      status: 502,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  return new Response(JSON.stringify({ ok: true }), {
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
});
