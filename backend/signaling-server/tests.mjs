import assert from "node:assert/strict";
import test from "node:test";
import { RoomRegistry, SlidingWindowRateLimiter } from "./src/roomRegistry.mjs";

test("rate limiter blocks after configured burst", () => {
  const limiter = new SlidingWindowRateLimiter(2, 1000);
  assert.equal(limiter.allow(1000), true);
  assert.equal(limiter.allow(1001), true);
  assert.equal(limiter.allow(1002), false);
  assert.equal(limiter.allow(2002), true);
});

test("room registry caps rooms at two peers and cleans up", () => {
  const registry = new RoomRegistry();
  const peer = () => ({ OPEN: 1, readyState: 1, sent: [], send(value) { this.sent.push(value); } });
  const a = peer();
  const b = peer();
  const c = peer();
  registry.join("session", a, "publisher");
  registry.join("session", b, "viewer");
  assert.equal(registry.size("session"), 2);
  assert.throws(() => registry.join("session", c, "viewer"), /full|role/);
  assert.equal(registry.broadcast("session", a, "hello"), 1);
  assert.deepEqual(b.sent, ["hello"]);
  assert.equal(registry.leave(a), "session");
  assert.equal(registry.size("session"), 1);
  assert.equal(registry.leave(b), "session");
  assert.equal(registry.roomCount(), 0);
  assert.equal(registry.leave(c), undefined);
});


test("room registry rejects duplicate peer roles", () => {
  const registry = new RoomRegistry();
  const peer = () => ({ OPEN: 1, readyState: 1, sent: [], send(value) { this.sent.push(value); } });
  registry.join("session", peer(), "publisher");
  assert.throws(() => registry.join("session", peer(), "publisher"), /Role/);
});
