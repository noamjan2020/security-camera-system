import type { WebSocket } from "ws";

export type PeerRole = "publisher" | "viewer" | "unknown";

export type Peer = WebSocket & {
  userId?: string;
  sessionId?: string;
  isAlive?: boolean;
  role?: PeerRole;
  connectionId?: string;
  accessToken?: string;
};

export class RoomRegistry {
  join(sessionId: string, peer: Peer, role?: PeerRole): void;
  broadcast(sessionId: string, sender: Peer, message: string): number;
  leave(peer: Peer): string | undefined;
  size(sessionId: string): number;
  roomCount(): number;
}

export class SlidingWindowRateLimiter {
  constructor(maxEvents: number, windowMs: number);
  allow(now?: number): boolean;
}
