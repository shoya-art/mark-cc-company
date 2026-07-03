/** Relay a preformatted Threads analysis message to the existing LINE account. */

const THREADS_NOTIFY_SECRET = (Deno.env.get("THREADS_NOTIFY_SECRET") ?? "").trim();
const LINE_CHANNEL_ACCESS_TOKEN = (Deno.env.get("LINE_CHANNEL_ACCESS_TOKEN") ?? "").trim();
const LINE_TO_USER_ID = (Deno.env.get("LINE_TO_USER_ID") ?? "").trim();

function jsonResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

Deno.serve(async (request: Request) => {
  if (request.method !== "POST") {
    return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  }
  if (!THREADS_NOTIFY_SECRET) {
    return jsonResponse(500, { ok: false, error: "relay_secret_not_configured" });
  }
  if (request.headers.get("x-threads-notify-secret") !== THREADS_NOTIFY_SECRET) {
    return jsonResponse(401, { ok: false, error: "unauthorized" });
  }
  if (!LINE_CHANNEL_ACCESS_TOKEN || !LINE_TO_USER_ID) {
    return jsonResponse(500, { ok: false, error: "line_secrets_not_configured" });
  }

  let message = "";
  try {
    const payload = await request.json() as { message?: unknown };
    message = typeof payload.message === "string" ? payload.message.trim() : "";
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }
  if (!message) {
    return jsonResponse(400, { ok: false, error: "message_required" });
  }

  const lineResponse = await fetch("https://api.line.me/v2/bot/message/push", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${LINE_CHANNEL_ACCESS_TOKEN}`,
    },
    body: JSON.stringify({
      to: LINE_TO_USER_ID,
      messages: [{ type: "text", text: message.slice(0, 4500) }],
    }),
  });
  if (!lineResponse.ok) {
    const detail = (await lineResponse.text()).slice(0, 300);
    return jsonResponse(502, {
      ok: false,
      error: "line_api_error",
      status: lineResponse.status,
      detail,
    });
  }
  return jsonResponse(200, { ok: true });
});
