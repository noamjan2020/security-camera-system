import type { WebSocket } from "ws";
export type Peer = WebSocket & { userId?: string; sessionId?: string; isAlive?: boolean };
export class RoomRegistry {
  join(sessionId: string, peer: Peer): void;
  broadcast(sessionId: string, sender: Peer, message: string): number;
  leave(peer: Peer): void;
  size(sessionId: string): number;
  roomCount(): number;
}
export class SlidingWindowRateLimiter {
  constructor(maxEvents: number, windowMs: number);
  allow(now?: number): boolean;
}
