# Uninstallation

## Windows

1. Use the local emergency disable or privacy pause.
2. Exit HomeGuard from the tray.
3. Uninstall **HomeGuard Agent** from Windows Settings.
4. Remove the optional local data directory only when you want to delete events, logs, pairings and face embeddings:

```text
%LOCALAPPDATA%\HomeGuard
```

The installer should not silently delete personal event history.

## Android

1. Revoke the phone from the Windows **Pair phone** tab or cloud device list.
2. Sign out of cloud access.
3. Uninstall HomeGuard. Android removes its app-private Keystore-encrypted preferences/cache.

## Cloud account/data

Delete or revoke device rows, event/voice media, events, commands and push tokens through an authenticated account-deletion workflow or Supabase administration. Deleting the Supabase Auth user cascades HomeGuard database rows, but Storage objects should also be verified/cleaned.
