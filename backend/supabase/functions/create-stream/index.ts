import { createClient } from "npm:@supabase/supabase-js@2.55.0";

const JSON_HEADERS = { "content-type": "application/json" };
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type IceServer = { urls: string[]; username?: string; credential?: string };

function log(level: string, message: string, fields: Record<string, unknown> = {}) {
  console.log(JSON.stringify({ ts: new Date().toISOString(), level, function: "create-stream", message, ...fields }));
}

function bearer(req: Request): string | null {
  const value = req.headers.get("authorization") ?? "";
  return value.startsWith("Bearer ") ? value.slice(7).trim() : null;
}

function csv(name: string): string[] {
  return (Deno.env.get(name) ?? "").split(",").map(value => value.trim()).filter(Boolean);
}

function base64(bytes: ArrayBuffer): string {
  let raw = "";
  for (const value of new Uint8Array(bytes)) raw += String.fromCharCode(value);
  return btoa(raw);
}

async function hmacSha1(secret: string, value: string): Promise<string> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-1" },
    false,
    ["sign"],
  );
  return base64(await crypto.subtle.sign("HMAC", key, encoder.encode(value)));
}

async function iceServers(ownerId: string, expiresEpoch: number): Promise<IceServer[]> {
  const servers: IceServer[] = [];
  const stun = csv("STUN_URLS").filter(url => /^stuns?:/i.test(url));
  if (stun.length) servers.push({ urls: stun });

  const turn = csv("TURN_URLS").filter(url => /^turns?:/i.test(url));
  const secret = Deno.env.get("TURN_SHARED_SECRET") ?? "";
  if (turn.length && secret) {
    const username = `${expiresEpoch}:${ownerId}`;
    servers.push({ urls: turn, username, credential: await hmacSha1(secret, username) });
  }
  return servers;
}

Deno.serve(async req => {
  const requestId = req.headers.get("x-request-id") ?? crypto.randomUUID();
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed", request_id: requestId }), { status: 405, headers: JSON_HEADERS });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  const signalingUrl = (Deno.env.get("SIGNALING_URL") ?? "").trim();
  if (!supabaseUrl || !anonKey || !serviceKey || !/^wss:\/\//i.test(signalingUrl)) {
    log("error", "Stream service configuration is incomplete", { requestId });
    return new Response(JSON.stringify({ error: "Stream service unavailable", request_id: requestId }), { status: 503, headers: JSON_HEADERS });
  }

  const token = bearer(req);
  if (!token) return new Response(JSON.stringify({ error: "Authentication required", request_id: requestId }), { status: 401, headers: JSON_HEADERS });

  try {
    const scoped = createClient(supabaseUrl, anonKey, {
      global: { headers: { Authorization: `Bearer ${token}` } },
      auth: { persistSession: false },
    });
    const { data: userData, error: userError } = await scoped.auth.getUser(token);
    if (userError || !userData.user) {
      return new Response(JSON.stringify({ error: "Invalid session", request_id: requestId }), { status: 401, headers: JSON_HEADERS });
    }

    const body = await req.json().catch(() => ({})) as Record<string, unknown>;
    const viewerDeviceId = String(body.viewer_device_id ?? "");
    const requestedCameraId = String(body.camera_device_id ?? "");
    if (!UUID_RE.test(viewerDeviceId) || (requestedCameraId && !UUID_RE.test(requestedCameraId))) {
      return new Response(JSON.stringify({ error: "Invalid device ID", request_id: requestId }), { status: 400, headers: JSON_HEADERS });
    }

    const admin = createClient(supabaseUrl, serviceKey, { auth: { persistSession: false } });
    const ownerId = userData.user.id;
    const now = Date.now();
    const { data: viewer, error: viewerError } = await admin.from("devices")
      .select("id")
      .eq("id", viewerDeviceId)
      .eq("owner_id", ownerId)
      .eq("device_type", "android")
      .is("revoked_at", null)
      .maybeSingle();
    if (viewerError) throw viewerError;
    if (!viewer) return new Response(JSON.stringify({ error: "Viewer device is not authorized", request_id: requestId }), { status: 403, headers: JSON_HEADERS });

    let cameraQuery = admin.from("devices")
      .select("id")
      .eq("owner_id", ownerId)
      .eq("device_type", "windows_agent")
      .is("revoked_at", null);
    if (requestedCameraId) cameraQuery = cameraQuery.eq("id", requestedCameraId);
    const { data: cameras, error: cameraError } = await cameraQuery
      .gt("last_seen_at", new Date(now - 90_000).toISOString())
      .order("last_seen_at", { ascending: false, nullsFirst: false })
      .order("created_at", { ascending: false })
      .limit(1);
    if (cameraError) throw cameraError;
    const cameraDeviceId = cameras?.[0]?.id;
    if (!cameraDeviceId) return new Response(JSON.stringify({ error: "No recently active Windows camera device is registered", request_id: requestId }), { status: 409, headers: JSON_HEADERS });

    const sessionId = crypto.randomUUID();
    const expiresAt = new Date(now + 5 * 60_000);
    const expiresEpoch = Math.floor(expiresAt.getTime() / 1000);
    const servers = await iceServers(ownerId, expiresEpoch);
    const { error: sessionError } = await admin.from("stream_sessions").insert({
      id: sessionId,
      owner_id: ownerId,
      camera_device_id: cameraDeviceId,
      viewer_device_id: viewerDeviceId,
      status: "active",
      expires_at: expiresAt.toISOString(),
    });
    if (sessionError) throw sessionError;

    const commandId = crypto.randomUUID();
    const { error: commandError } = await admin.from("remote_commands").insert({
      id: commandId,
      owner_id: ownerId,
      target_device_id: cameraDeviceId,
      command_type: "start_stream",
      payload: {
        session_id: sessionId,
        signaling_url: signalingUrl,
        ice_servers: servers,
        max_fps: 15,
        camera_device_id: cameraDeviceId,
        viewer_device_id: viewerDeviceId,
      },
      nonce: crypto.randomUUID().replaceAll("-", "") + crypto.randomUUID().replaceAll("-", ""),
      expires_at: expiresAt.toISOString(),
      status: "pending",
    });
    if (commandError) {
      await admin.from("stream_sessions").delete().eq("id", sessionId).eq("owner_id", ownerId);
      throw commandError;
    }

    log("info", "Stream session created", { requestId, sessionId, commandId, ownerId, cameraDeviceId, viewerDeviceId, iceServerGroups: servers.length });
    return new Response(JSON.stringify({
      session_id: sessionId,
      signaling_url: signalingUrl,
      ice_servers: servers,
      expires_at: expiresAt.toISOString(),
    }), { status: 201, headers: JSON_HEADERS });
  } catch (error) {
    log("error", "Stream session creation failed", { requestId, error: String(error) });
    return new Response(JSON.stringify({ error: "Stream session creation failed", request_id: requestId }), { status: 500, headers: JSON_HEADERS });
  }
});
