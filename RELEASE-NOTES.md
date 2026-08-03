# HomeGuard 0.4 release notes

## Added

- optional lazy-loaded Windows WebRTC publisher
- Android system-WebView WebRTC viewer with origin-scoped bridge
- short-lived stream sessions and coturn REST credentials
- exact viewer/camera device binding in signaling
- duplicate role rejection
- WebRTC state in Windows health diagnostics
- optional WebRTC setup/build switches
- expanded static security checks

## Improved

- version alignment across Windows, Android, signaling, API, and installer
- cloud/Live View documentation
- CI includes Windows WebRTC dependencies
- backend configuration examples

## Compatibility

Phones paired before 0.4 should pair again because remote stream authorization now requires UUID device identities.

## Verification status

All tests executable in this Linux session pass. Platform packaging, Android full compilation, and physical cloud/TURN tests remain unverified here.
