# Security and threat model

## Protected assets

- live camera frames;
- event screenshots;
- local biometric embeddings;
- voice messages;
- remote command authority;
- owner and device credentials.

## Main threats and controls

| Threat | Control |
|---|---|
| Guessing a permanent local token | one-time QR claim; separate random credential per phone; revocation |
| Replaying a speaker command | unique nonce, expiry, local nonce database, cloud unique constraint |
| Cross-account cloud access | Supabase RLS plus cross-owner trigger guards |
| Public camera URL | no permanent stream URL; no router port-forwarding |
| Stolen phone storage | Android Keystore AES-GCM encrypted preferences |
| Stolen Windows token file | DPAPI on Windows; owner-only fallback permissions elsewhere |
| Hidden/unclear face accepted as known | fail closed: no usable face is `no_face`/unknown |
| Remote re-enable after emergency stop | only local Windows action clears persistent emergency state |
| Malicious audio file | private bucket, ownership query, size check, WAV parser, duration/rate/channel limits |
| Log credential leakage | structured request metadata only; authorization headers are redacted/omitted |
| Unlimited storage/queue growth | retention cleanup, bounded uploads, disk warnings, retry backoff |

## Important deployment rules

- Use HTTPS/WSS for anything outside a private LAN.
- Never ship `SUPABASE_SERVICE_ROLE_KEY` in Android or Windows.
- Keep Firebase service-account JSON only in the Edge Function secret store.
- Use a private Git repository until secrets and branding are reviewed.
- Rotate/revoke devices after a lost phone or compromised account.
- Face recognition is a convenience filter, not identity proof.
