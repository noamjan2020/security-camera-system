# HomeGuard manual test report

## Build information

- Date:
- Tester:
- Git commit:
- HomeGuard version:
- APK filename and SHA-256:
- EXE/installer filename and SHA-256:
- Windows version:
- PC CPU/RAM/GPU:
- Camera model:
- Android model/version:
- Network used:
- Supabase project/test environment:
- Signaling/TURN environment:

## Automated checks

| Check | Expected | Result | Notes |
|---|---:|---|---|
| Static checks | 401+ |  |  |
| Windows tests | 44 pass |  |  |
| Signaling tests | 3 pass |  |  |
| Android pure Kotlin | Pass |  |  |
| TypeScript syntax | Pass |  |  |
| Android unit tests | Pass |  |  |
| Android lint | Pass |  |  |
| APK build | Pass |  |  |
| Windows EXE build | Pass |  |  |
| Windows installer build | Pass |  |  |

## Manual tests

Use `PASS`, `FAIL`, `BLOCKED`, or `NOT RUN`.

| ID | Test | Result | Failure time | Notes/evidence |
|---|---|---|---|---|
| HG-001 | Clean startup |  |  |  |
| HG-002 | Single instance |  |  |  |
| HG-003 | Camera disconnect recovery |  |  |  |
| HG-004 | Webcam already in use |  |  |  |
| HG-010 | Unknown person event |  |  |  |
| HG-011 | Short appearance ignored |  |  |  |
| HG-012 | Continuous-person cooldown |  |  |  |
| HG-013 | Multiple people |  |  |  |
| HG-014 | Pet/object false positive |  |  |  |
| HG-015 | Low-light detection |  |  |  |
| HG-020 | Detection zone |  |  |  |
| HG-021 | Exclusion zone |  |  |  |
| HG-030 | Face enrollment |  |  |  |
| HG-031 | Whitelisted suppression |  |  |  |
| HG-032 | Unknown face |  |  |  |
| HG-033 | Hidden/unclear face |  |  |  |
| HG-034 | Similar-looking person |  |  |  |
| HG-035 | Remove whitelist entry |  |  |  |
| HG-040 | Android event timeline |  |  |  |
| HG-041 | Event detail |  |  |  |
| HG-042 | Delete event |  |  |  |
| HG-043 | Retention cleanup |  |  |  |
| HG-050 | Privacy pause |  |  |  |
| HG-051 | Resume |  |  |  |
| HG-052 | Persistent emergency disable |  |  |  |
| HG-060 | Microphone permission behavior |  |  |  |
| HG-061 | Local voice playback |  |  |  |
| HG-062 | Volume restoration |  |  |  |
| HG-063 | Remote stop |  |  |  |
| HG-064 | Audio limits |  |  |  |
| HG-100 | Background FCM |  |  |  |
| HG-101 | Notification deep link |  |  |  |
| HG-102 | Mobile-data event access |  |  |  |
| HG-103 | PC outage queue |  |  |  |
| HG-104 | Phone offline recovery |  |  |  |
| HG-105 | Second-account isolation |  |  |  |
| HG-110 | Home Wi-Fi Live View |  |  |  |
| HG-111 | Mobile-data TURN |  |  |  |
| HG-112 | Restrictive-network TURN |  |  |  |
| HG-113 | Session expiry |  |  |  |
| HG-114 | Privacy/emergency stream denial |  |  |  |
| HG-115 | Unauthorized stream join |  |  |  |
| HG-120 | Mobile-data voice playback |  |  |  |
| HG-121 | Expired remote command |  |  |  |
| HG-122 | Replay rejection |  |  |  |
| HG-123 | Revoked phone rejection |  |  |  |
| HG-200 | 24-hour soak |  |  |  |
| HG-201 | Weak-PC profile |  |  |  |
| HG-202 | Android lifecycle stress |  |  |  |
| HG-203 | Storage pressure |  |  |  |

## Performance observations

| Time | RAM MB | Idle CPU % | Detection CPU % | Capture FPS | AI FPS | Queue | Data MB | Logs MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Start |  |  |  |  |  |  |  |  |
| 1 hour |  |  |  |  |  |  |  |  |
| 4 hours |  |  |  |  |  |  |  |  |
| 8 hours |  |  |  |  |  |  |  |  |
| 12 hours |  |  |  |  |  |  |  |  |
| 24 hours |  |  |  |  |  |  |  |  |

## Bugs found

### BUG-001

- Related test:
- Severity:
- Steps to reproduce:
- Expected:
- Actual:
- Reproduction rate:
- Logs/evidence:
- Workaround:

## Release decision

- [ ] Approved for another internal test
- [ ] Approved for beta
- [ ] Blocked

Blocking issues:

