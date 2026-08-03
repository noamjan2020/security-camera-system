export class RoomRegistry {
  #rooms = new Map();

  join(sessionId, peer, role = "unknown") {
    const room = this.#rooms.get(sessionId) ?? new Set();
    if (room.size >= 2 && !room.has(peer)) throw new Error("Room is full");
    for (const existing of room) {
      if (existing !== peer && existing.role === role) throw new Error("Role is already present");
    }
    room.add(peer);
    peer.sessionId = sessionId;
    peer.role = role;
    this.#rooms.set(sessionId, room);
  }

  broadcast(sessionId, sender, message) {
    const room = this.#rooms.get(sessionId);
    if (!room) return 0;
    let delivered = 0;
    for (const peer of room) {
      if (peer !== sender && peer.readyState === peer.OPEN) {
        peer.send(message);
        delivered += 1;
      }
    }
    return delivered;
  }

  leave(peer) {
    const sessionId = peer.sessionId;
    if (!sessionId) return undefined;
    const room = this.#rooms.get(sessionId);
    room?.delete(peer);
    if (room?.size === 0) this.#rooms.delete(sessionId);
    peer.sessionId = undefined;
    peer.role = undefined;
    return sessionId;
  }

  size(sessionId) {
    return this.#rooms.get(sessionId)?.size ?? 0;
  }

  roomCount() {
    return this.#rooms.size;
  }
}

export class SlidingWindowRateLimiter {
  #timestamps = [];
  constructor(maxEvents, windowMs) {
    this.maxEvents = maxEvents;
    this.windowMs = windowMs;
  }

  allow(now = Date.now()) {
    const cutoff = now - this.windowMs;
    this.#timestamps = this.#timestamps.filter(value => value > cutoff);
    if (this.#timestamps.length >= this.maxEvents) return false;
    this.#timestamps.push(now);
    return true;
  }
}
