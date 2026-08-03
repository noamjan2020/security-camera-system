import { createClient } from "npm:@supabase/supabase-js@2.55.0";

const headers = { "content-type": "application/json" };
const encoder = new TextEncoder();
function log(level: string, message: string, fields: Record<string, unknown> = {}) {
  console.log(JSON.stringify({ ts: new Date().toISOString(), level, function: "pair-device", message, ...fields }));
}
async function sha256(value: string): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
  return Array.from(digest, value => value.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async req => {
  const requestId = crypto.randomUUID();
  try {
    if (req.method !== "POST") return new Response(JSON.stringify({ error: "Method not allowed" }), { status: 405, headers });
    const authorization = req.headers.get("authorization") ?? "";
    const token = authorization.startsWith("Bearer ") ? authorization.slice(7) : "";
    const url = Deno.env.get("SUPABASE_URL")!;
    const anon = Deno.env.get("SUPABASE_ANON_KEY")!;
    const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const authClient = createClient(url, anon, { global: { headers: { Authorization: authorization } } });
    const admin = createClient(url, service, { auth: { persistSession: false } });
    const { data: userData, error: userError } = await authClient.auth.getUser(token);
    if (userError || !userData.user) return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401, headers });

    const body = await req.json();
    const action = String(body.action ?? "");
    if (action === "create") {
      const initiatorDeviceId = String(body.initiator_device_id ?? "");
      const { data: device } = await admin.from("devices").select("id").eq("id", initiatorDeviceId).eq("owner_id", userData.user.id).is("revoked_at", null).single();
      if (!device) return new Response(JSON.stringify({ error: "Device not found" }), { status: 404, headers });
      const code = `${crypto.randomUUID()}${crypto.randomUUID()}`.replaceAll("-", "");
      const expiresAt = new Date(Date.now() + 2 * 60_000).toISOString();
      const { data, error } = await admin.from("device_pairings").insert({
        owner_id: userData.user.id,
        initiator_device_id: initiatorDeviceId,
        code_hash: await sha256(code),
        expires_at: expiresAt,
      }).select("id,expires_at").single();
      if (error) throw error;
      log("info", "Pairing challenge created", { requestId, pairingId: data.id, ownerId: userData.user.id });
      return new Response(JSON.stringify({ pairing_id: data.id, code, expires_at: data.expires_at }), { status: 201, headers });
    }
    if (action === "claim") {
      const code = String(body.code ?? "");
      const claimedDeviceId = String(body.claimed_device_id ?? "");
      if (code.length < 40) return new Response(JSON.stringify({ error: "Invalid code" }), { status: 400, headers });
      const { data: claimedDevice } = await admin.from("devices").select("id").eq("id", claimedDeviceId).eq("owner_id", userData.user.id).is("revoked_at", null).single();
      if (!claimedDevice) return new Response(JSON.stringify({ error: "Device not found" }), { status: 404, headers });
      const now = new Date().toISOString();
      const { data: pairing, error } = await admin.from("device_pairings")
        .update({ claimed_device_id: claimedDeviceId, claimed_at: now })
        .eq("owner_id", userData.user.id)
        .eq("code_hash", await sha256(code))
        .gt("expires_at", now)
        .is("claimed_at", null)
        .select("id,initiator_device_id,claimed_device_id,claimed_at")
        .maybeSingle();
      if (error) throw error;
      if (!pairing) return new Response(JSON.stringify({ error: "Pairing code expired or already used" }), { status: 409, headers });
      log("info", "Pairing challenge claimed", { requestId, pairingId: pairing.id, ownerId: userData.user.id });
      return new Response(JSON.stringify(pairing), { status: 200, headers });
    }
    return new Response(JSON.stringify({ error: "Invalid action" }), { status: 400, headers });
  } catch (error) {
    log("error", "Pairing function failed", { requestId, error: String(error) });
    return new Response(JSON.stringify({ error: "Pairing failed", request_id: requestId }), { status: 500, headers });
  }
});
