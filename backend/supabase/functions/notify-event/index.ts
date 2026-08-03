import { createClient } from "npm:@supabase/supabase-js@2.55.0";

const corsHeaders = { "content-type": "application/json" };
const encoder = new TextEncoder();

function log(level: string, message: string, fields: Record<string, unknown> = {}) {
  console.log(JSON.stringify({ ts: new Date().toISOString(), level, function: "notify-event", message, ...fields }));
}

function base64Url(input: Uint8Array | string): string {
  const bytes = typeof input === "string" ? encoder.encode(input) : input;
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function importPrivateKey(pem: string): Promise<CryptoKey> {
  const body = pem.replace(/-----BEGIN PRIVATE KEY-----|-----END PRIVATE KEY-----|\s/g, "");
  const bytes = Uint8Array.from(atob(body), char => char.charCodeAt(0));
  return crypto.subtle.importKey(
    "pkcs8",
    bytes,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
}

async function googleAccessToken(serviceAccount: { client_email: string; private_key: string }): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const header = base64Url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claims = base64Url(JSON.stringify({
    iss: serviceAccount.client_email,
    scope: "https://www.googleapis.com/auth/firebase.messaging",
    aud: "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600,
  }));
  const unsigned = `${header}.${claims}`;
  const key = await importPrivateKey(serviceAccount.private_key);
  const signature = new Uint8Array(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, encoder.encode(unsigned)));
  const assertion = `${unsigned}.${base64Url(signature)}`;
  const response = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion }),
  });
  if (!response.ok) throw new Error(`Google OAuth failed: ${response.status} ${await response.text()}`);
  const payload = await response.json();
  return payload.access_token;
}

Deno.serve(async req => {
  const requestId = crypto.randomUUID();
  try {
    if (req.method !== "POST") return new Response(JSON.stringify({ error: "Method not allowed" }), { status: 405, headers: corsHeaders });
    const authorization = req.headers.get("authorization") ?? "";
    const token = authorization.startsWith("Bearer ") ? authorization.slice(7) : "";
    if (!token) return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401, headers: corsHeaders });

    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const anonKey = Deno.env.get("SUPABASE_ANON_KEY")!;
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const authClient = createClient(supabaseUrl, anonKey, { global: { headers: { Authorization: authorization } } });
    const admin = createClient(supabaseUrl, serviceKey, { auth: { persistSession: false } });
    const { data: userData, error: userError } = await authClient.auth.getUser(token);
    if (userError || !userData.user) return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401, headers: corsHeaders });

    const body = await req.json();
    const eventId = String(body.event_id ?? "");
    if (!/^[0-9a-f-]{32,36}$/i.test(eventId)) return new Response(JSON.stringify({ error: "Invalid event_id" }), { status: 400, headers: corsHeaders });
    const { data: event, error: eventError } = await admin
      .from("events")
      .select("id,owner_id,occurred_at,person_confidence,camera_id,cameras(name)")
      .eq("id", eventId)
      .eq("owner_id", userData.user.id)
      .single();
    if (eventError || !event) return new Response(JSON.stringify({ error: "Event not found" }), { status: 404, headers: corsHeaders });

    const { data: tokens, error: tokenError } = await admin
      .from("push_tokens")
      .select("id,token")
      .eq("owner_id", userData.user.id);
    if (tokenError) throw tokenError;
    if (!tokens?.length) return new Response(JSON.stringify({ sent: 0 }), { status: 200, headers: corsHeaders });

    const cameraRelation = event.cameras as { name?: string } | Array<{ name?: string }> | null;
    const cameraName = Array.isArray(cameraRelation)
      ? cameraRelation[0]?.name ?? "Home camera"
      : cameraRelation?.name ?? "Home camera";

    const serviceAccount = JSON.parse(Deno.env.get("FIREBASE_SERVICE_ACCOUNT_JSON") ?? "{}");
    const projectId = serviceAccount.project_id;
    if (!projectId || !serviceAccount.client_email || !serviceAccount.private_key) throw new Error("Firebase service account is incomplete");
    const accessToken = await googleAccessToken(serviceAccount);
    let sent = 0;
    for (const entry of tokens) {
      const response = await fetch(`https://fcm.googleapis.com/v1/projects/${projectId}/messages:send`, {
        method: "POST",
        headers: { authorization: `Bearer ${accessToken}`, "content-type": "application/json" },
        body: JSON.stringify({
          message: {
            token: entry.token,
            data: {
              event_id: event.id,
              camera_name: cameraName,
              detected_at: event.occurred_at,
              confidence: String(event.person_confidence),
            },
            notification: { title: "Unknown person detected", body: cameraName },
            android: { priority: "high", notification: { channel_id: "unknown_person_alerts", sound: "default" } },
          },
        }),
      });
      const responseText = await response.text();
      const status = response.ok ? "sent" : response.status === 404 ? "invalid_token" : "failed";
      await admin.from("push_delivery_attempts").insert({
        owner_id: userData.user.id,
        event_id: event.id,
        push_token_id: entry.id,
        status,
        provider_message_id: response.ok ? JSON.parse(responseText).name : null,
        error_detail: response.ok ? null : responseText.slice(0, 1000),
      });
      if (response.ok) {
        sent += 1;
      } else {
        log("warn", "FCM delivery failed", { requestId, eventId, statusCode: response.status });
        if (status === "invalid_token") {
          const { error: deleteError } = await admin.from("push_tokens").delete().eq("id", entry.id);
          if (deleteError) log("warn", "Invalid push token cleanup failed", { requestId, pushTokenId: entry.id });
          else log("info", "Invalid push token removed", { requestId, pushTokenId: entry.id });
        }
      }
    }
    log("info", "Notification dispatch completed", { requestId, eventId, sent, attempted: tokens.length });
    return new Response(JSON.stringify({ sent, attempted: tokens.length, request_id: requestId }), { status: 200, headers: corsHeaders });
  } catch (error) {
    log("error", "Notification function failed", { requestId, error: String(error) });
    return new Response(JSON.stringify({ error: "Notification failed", request_id: requestId }), { status: 500, headers: corsHeaders });
  }
});
