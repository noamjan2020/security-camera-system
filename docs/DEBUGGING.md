# Debug logging

Every critical path emits structured logs:

- process startup/shutdown;
- camera open/read/reconnect;
- detector selection and inference failures;
- face-match decisions without storing embeddings in logs;
- event creation and retention cleanup;
- local API request IDs and status codes;
- cloud request IDs, paths, timing and status codes;
- upload retries and queue depth;
- pairing creation/claim/revocation;
- remote command claim/replay/expiry/rejection;
- audio validation/playback/volume restoration/receipts;
- FCM receipt, token refresh and screenshot-preview failures;
- Android recording and uncaught exceptions.

Enable verbose Windows logs with:

```powershell
$env:HOMEGUARD_DEBUG="true"
.\scripts\dev-run.ps1
```

Do not post full logs publicly without reviewing them. Although secrets are deliberately excluded, camera names, device IDs, timestamps and local network addresses may still be sensitive.
