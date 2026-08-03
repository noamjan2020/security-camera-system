import express from "express";
import helmet from "helmet";
import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { WebSocketServer } from "ws";
import { createClient } from "@supabase/supabase-js";
import { z } from "zod";
import { RoomRegistry, SlidingWindowRateLimiter, type Peer } from "./roomRegistry.mjs";

const port = Number(process.env.PORT ?? 8787);
const supabaseUrl = process.env.SUPABASE_URL ?? "";
const supabaseKey = process.env.SUPABASE_ANON_KEY ?? "";
const allowedOrigin = process.env.ALLOWED_ORIGIN ?? "";
if (!supabaseUrl || !supabaseKey) throw new Error("Supabase configuration is required");
const supabase = createClient(supabaseUrl, supabaseKey, { auth: { persistSession: false } });

function log(level: string, message: string, fields: Record<string, unknown> = {}): void {
  console.log(JSON.stringify({ ts: new Date().toISOString(), level, service: "signaling", message, ...fields }));
}

const app = express();
app.disable("x-powered-by");
app.use(helmet());
app.get("/health", (_req, res) => res.json({ status: "ok", version: "0.4.0" }));
const server = createServer(app);
const wss = new WebSocketServer({ noServer: true, maxPayload: 32 * 1024, perMessageDeflate: false });
const registry = new RoomRegistry();

const Signal = z.object({
  sessionId: z.string().uuid(),
  type: z.enum(["join", "offer", "answer", "ice", "leave", "ping"]),
  requestId: z.string().min(8).max(100),
  payload: z.unknown().optional(),
});
const JoinPayload = z.object({
  role: z.enum(["publisher", "viewer"]),
  deviceId: z.string().uuid(),
});

type AuthorizedSession = {
  camera_device_id: string;
  viewer_device_id: string;
};

function bearerToken(header: string | undefined): string | null {
  if (!header?.startsWith("Bearer ")) return null;
  const token = header.slice(7).trim();
  return token.length >= 20 ? token : null;
}

async function authorizeSession(sessionId: string, userId: string, token: string): Promise<AuthorizedSession | null> {
  const scoped = createClient(supabaseUrl, supabaseKey, {
    global: { headers: { Authorization: `Bearer ${token}` } },
    auth: { persistSession: false },
  });
  const { data, error } = await scoped
    .from("stream_sessions")
    .select("camera_device_id,viewer_device_id")
    .eq("id", sessionId)
    .eq("owner_id", userId)
    .eq("status", "active")
    .gt("expires_at", new Date().toISOString())
    .maybeSingle();
  if (error) {
    log("warn", "Stream authorization query failed", { sessionId, error: error.message });
    return null;
  }
  return data as AuthorizedSession | null;
}

server.on("upgrade", async (request, socket, head) => {
  const connectionId = randomUUID();
  try {
    if (allowedOrigin && request.headers.origin !== allowedOrigin) {
      log("warn", "Rejected WebSocket origin", { connectionId, origin: request.headers.origin });
      socket.destroy();
      return;
    }
    const token = bearerToken(request.headers.authorization);
    if (!token) {
      log("warn", "Rejected WebSocket without bearer token", { connectionId });
      socket.destroy();
      return;
    }
    const { data, error } = await supabase.auth.getUser(token);
    if (error || !data.user) {
      log("warn", "Rejected invalid WebSocket session", { connectionId });
      socket.destroy();
      return;
    }
    wss.handleUpgrade(request, socket, head, ws => {
      const peer = ws as Peer;
      peer.userId = data.user.id;
      peer.isAlive = true;
      Object.assign(peer, { connectionId, accessToken: token });
      wss.emit("connection", peer);
    });
  } catch (error) {
    log("error", "WebSocket upgrade failed", { connectionId, error: String(error) });
    socket.destroy();
  }
});

wss.on("connection", (peer: Peer) => {
  const connectionId = String((peer as unknown as { connectionId: string }).connectionId);
  const accessToken = String((peer as unknown as { accessToken: string }).accessToken);
  const limiter = new SlidingWindowRateLimiter(40, 10_000);
  log("info", "Peer connected", { connectionId, userId: peer.userId });

  peer.on("pong", () => { peer.isAlive = true; });
  peer.on("message", async raw => {
    if (!limiter.allow()) {
      log("warn", "Peer rate limit exceeded", { connectionId });
      peer.close(1008, "Rate limit exceeded");
      return;
    }
    let signal: z.infer<typeof Signal>;
    try {
      signal = Signal.parse(JSON.parse(raw.toString()));
    } catch (error) {
      log("warn", "Invalid signaling message", { connectionId, error: String(error) });
      peer.close(1008, "Invalid signal");
      return;
    }

    if (signal.type === "join") {
      if (peer.sessionId && peer.sessionId !== signal.sessionId) {
        peer.close(1008, "Already joined another session");
        return;
      }
      const join = JoinPayload.safeParse(signal.payload);
      if (!join.success) {
        peer.close(1008, "Invalid join identity");
        return;
      }
      const authorized = await authorizeSession(signal.sessionId, peer.userId ?? "", accessToken);
      const expectedDeviceId = join.data.role === "publisher"
        ? authorized?.camera_device_id
        : authorized?.viewer_device_id;
      if (!authorized || expectedDeviceId !== join.data.deviceId) {
        log("warn", "Unauthorized stream session join", {
          connectionId,
          sessionId: signal.sessionId,
          role: join.data.role,
          deviceId: join.data.deviceId,
        });
        peer.close(1008, "Unauthorized session device");
        return;
      }
      try {
        registry.join(signal.sessionId, peer, join.data.role);
      } catch (error) {
        log("warn", "Stream room rejected peer", { connectionId, sessionId: signal.sessionId, role: join.data.role, error: String(error) });
        peer.close(1013, "Room role unavailable");
        return;
      }
      const peers = registry.size(signal.sessionId);
      peer.send(JSON.stringify({ type: "joined", sessionId: signal.sessionId, requestId: signal.requestId, peers }));
      registry.broadcast(signal.sessionId, peer, JSON.stringify({
        type: "peer_joined",
        sessionId: signal.sessionId,
        requestId: signal.requestId,
        peers,
      }));
      log("info", "Peer joined session", { connectionId, sessionId: signal.sessionId, peers });
      return;
    }

    if (!peer.sessionId || peer.sessionId !== signal.sessionId) {
      peer.close(1008, "Join required");
      return;
    }
    if (signal.type === "leave") {
      registry.leave(peer);
      return;
    }
    if (signal.type === "ping") {
      peer.send(JSON.stringify({ type: "pong", sessionId: signal.sessionId, requestId: signal.requestId }));
      return;
    }
    const delivered = registry.broadcast(signal.sessionId, peer, JSON.stringify(signal));
    log("debug", "Signal relayed", { connectionId, sessionId: signal.sessionId, type: signal.type, delivered });
  });

  peer.on("close", (code, reason) => {
    const sessionId = registry.leave(peer);
    if (sessionId) {
      registry.broadcast(sessionId, peer, JSON.stringify({
        type: "peer_left",
        sessionId,
        requestId: randomUUID(),
        peers: registry.size(sessionId),
      }));
    }
    log("info", "Peer disconnected", { connectionId, sessionId, code, reason: reason.toString() });
  });
  peer.on("error", error => log("error", "Peer error", { connectionId, error: error.message }));
});

const heartbeat = setInterval(() => {
  for (const socket of wss.clients) {
    const peer = socket as Peer;
    if (peer.isAlive === false) {
      log("warn", "Terminating stale peer", { sessionId: peer.sessionId });
      peer.terminate();
      continue;
    }
    peer.isAlive = false;
    peer.ping();
  }
}, 30_000);

server.on("close", () => clearInterval(heartbeat));
server.listen(port, () => log("info", "HomeGuard signaling listening", { port }));
