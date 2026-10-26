# Motivating Examples (m33 run, specs 0021–0031)

Testers rebuilt these in the session scratchpad each round. Each should have been one registered tool.

| Throwaway (scratchpad) | Capability | Durable tool |
|---|---|---|
| `mockoauth/mock.py`, `tscripts/mock.py` (rewritten per round): fake OAuth authorization server plus ChatGPT `/codex/responses` backend | `ext.mock.oauth`, `ext.mock.chatgpt` | `be/cmd/fake-oauth` and `be/cmd/fake-chatgpt`: authorize/token/refresh and responses endpoints, scripted errors (`invalid_grant`, slow, 500), request log as JSON |
| `tscripts/lib.py` + `s1–s6.py`, `rt/r1–r3.py`: users, login, API calls, and assertions per scenario | `be.seed`, `data.cleanup` | `be/cmd/seed` for users and fixtures; scenarios become `flow` files or Go tests, not scripts |
| Mock MCP server | `ext.mock.mcp` | `be/cmd/fake-mcp`: declared tools, slow and failing tools, discovery changes |
| `tst23/scripts/*.cjs`, `test24/scripts/t*.cjs`: Playwright scripts and screenshotters | `fe.drive`, `fe.inspect` | `fe/tools/fe-drive` ([fe-driver.md](fe-driver.md)) |
| `models/main.go` + `overlay.json`: `go -overlay` program planted into `be/cmd` to read stored credentials and plant state | `be.seed`, `be.inspect` | `be/cmd/seed` (named fixtures, explicit `--target`, refuses the dev DB) and an inspection command for the state |
| `lane24/sync.sh`: private fe copy with port rewrites | `env.isolate` | `tools/isolate`: private copy or worktree on a free port, test DB per lane |
| `tscripts/startbe.sh`, `rt/startbe.sh`: start/stop backend | `env.isolate`, `be.fault` | `tools/isolate` + `be/cmd/fault` (kill, restart, clock shift) |
| Seed and cleanup scripts | `be.seed`, `data.cleanup` | `be/cmd/seed`, `be/cmd/seed cleanup --tag <run>` (idempotent) |
| `tscripts/insp.sh`: wrapper around the inspection CLI | `be.inspect` | Existing inspection CLI (spec 0019); add the missing command instead |

The retro over that session (`tools.adhoc`) found 58 scripts written outside the project in 7 runs (testers 45), about 57k tokens of script text and ~0.5M weighted tokens; `mock.py`, `s*.py`, `lib.py`, and `insp.sh` were rebuilt in several runs.
