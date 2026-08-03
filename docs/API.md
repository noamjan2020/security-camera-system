# API reference

The local Windows API is documented interactively at `/docs`. Every endpoint except pairing requires `Authorization: Bearer <device credential>`. Owner-only endpoints require the protected Windows owner credential.

## Pairing and devices

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | `/pair/claim` | one-time code | claim a temporary QR offer and receive a revocable phone credential |
| GET | `/devices` | owner | list paired phones |
| DELETE | `/devices/{device_id}` | owner | revoke a phone immediately |
| POST | `/push/register` | paired phone | register/refresh the phone FCM token through the PC |

## Status, privacy and diagnostics

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | camera, FPS, AI FPS, queue, cloud and disk status |
| GET | `/state` | privacy/emergency state |
| POST | `/privacy/pause` | pause camera processing |
| POST | `/privacy/resume` | resume unless emergency-disabled |
| POST | `/emergency/disable` | deliberately rejected; emergency controls are local-only |
| GET | `/logs/tail?lines=200` | recent rotating Windows log lines |

## Events and camera

| Method | Path | Purpose |
|---|---|---|
| GET | `/events?minutes=15&limit=100` | recent events |
| GET | `/events/{id}` | event details |
| POST | `/events/{id}/viewed` | mark viewed |
| DELETE | `/events/{id}` | delete event and local media |
| GET | `/events/{id}/image` | protected JPEG |
| GET | `/snapshot` | current protected JPEG; unavailable while paused/emergency-disabled |

## Face whitelist

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/whitelist` | owner | list enrolled names/sample counts and model state |
| POST | `/whitelist/enroll-current` | owner | enroll a clear face from the current frame |
| POST | `/whitelist/test-current` | owner | test current face without changing data |
| DELETE | `/whitelist/{name}` | owner | remove all local samples for a person |

Face embeddings remain local and encrypted/protected by the Windows account.

## Audio

| Method | Path | Purpose |
|---|---|---|
| POST | `/audio/upload` | bounded WAV upload |
| POST | `/audio/play` | expiring replay-protected playback command |
| GET | `/audio/receipt/{command_id}` | received/playing/completed/stopped/failed receipt |
| POST | `/audio/stop` | stop current playback |

## Cloud records

Supabase REST is used directly under RLS for `events`, `devices`, `push_tokens`, `voice_messages`, `remote_commands`, `command_receipts`, `stream_sessions`, and settings. Storage buckets are private. Clients use owner access tokens; the service-role key is limited to Edge Functions.
