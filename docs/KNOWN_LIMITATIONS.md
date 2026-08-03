# Known limitations — read before deployment

1. This Linux session cannot build a genuine Windows EXE/installer because PyInstaller Windows packaging and Inno Setup require Windows.
2. Android SDK/Gradle dependency downloads are unavailable here, so the APK, Android lint, and full Android compilation could not run locally. CI/build scripts are included.
3. Windows and Android WebRTC peers are implemented in source, but they have not been exercised against a deployed WSS signaling service and real TURN server.
4. Supabase, Firebase, signaling, and TURN were not deployed in this session. Remote alerts, remote history, voice, and Live View need real credentials and physical integration tests.
5. The HOG fallback is less accurate than YOLO ONNX. A compatible model is not redistributed.
6. Detection/exclusion zones work in configuration, but the Windows UI does not yet have a drag-to-draw editor.
7. Windows remote mode currently uses a configured owner Supabase access token; automatic refresh-token enrollment is not finished.
8. Android biometric app unlock is not implemented.
9. Voice uses bounded PCM WAV for compatibility; Ogg Opus compression is not implemented.
10. Multi-camera support and a polished first-run Windows wizard are incomplete.
11. Notification image previews depend on authenticated cloud media availability and Android/OEM behavior.
12. Face recognition is probabilistic and must never be treated as proof of identity.
13. Existing pre-0.4 pairings used non-UUID local IDs and must be paired again for device-bound remote Live View.
14. Stream sessions expire automatically, but physical mobile-data/TURN cleanup behavior still requires soak testing.
