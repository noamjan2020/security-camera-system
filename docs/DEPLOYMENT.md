# Deployment guide

## Supabase

1. Create a project.
2. Apply all migrations in numeric order.
3. Verify RLS on every HomeGuard table.
4. Verify `event-media` and `voice-media` buckets are private.
5. Deploy `notify-event`, `pair-device`, and `create-stream`.
6. Configure Edge Function secrets:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `FIREBASE_SERVICE_ACCOUNT_JSON`
   - `SIGNALING_URL` using `wss://`
   - `STUN_URLS`
   - `TURN_URLS`
   - `TURN_SHARED_SECRET`
7. Schedule `cleanup_expired_homeguard_rows()` with privileged server-side credentials.

## Firebase

1. Create an Android app for `com.noamjan.homeguard`.
2. Place `google-services.json` in `android-app/app` only in local/CI secret restoration.
3. Enable Cloud Messaging.
4. Give the backend service account only the required messaging permission.
5. Test token rotation and invalid-token cleanup.

## Signaling and TURN

Deploy `backend/signaling-server` behind HTTPS/WSS. Set:

```env
SUPABASE_URL=https://PROJECT.supabase.co
SUPABASE_ANON_KEY=PUBLIC_ANON_KEY
PORT=8787
ALLOWED_ORIGIN=
```

HomeGuard native clients authenticate with bearer tokens and a device-bound stream session. A room permits one `publisher` and one `viewer`. Use a TURN service supporting the coturn REST shared-secret mechanism; never ship its shared secret to either client.

## Windows

1. Install the signed agent.
2. Configure camera/detection locally.
3. Register a valid Windows device UUID for the owner.
4. Configure the owner’s public Supabase values and normal owner session—never a service-role key.
5. Install optional ONNX/WebRTC dependencies only when those features are needed.
6. Verify restart, startup, privacy pause, emergency persistence, and log rotation.

## Android

Build with the public Supabase URL/anon key and Firebase config. Use a release keystore outside the repository. Pair locally, sign into the same owner account, then verify alerts/history/live/voice on mobile data.
