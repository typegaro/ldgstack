# Frontend Driver (`fe.drive`, `fe.inspect`, `fe.audit`)

A CLI over Playwright that agents call one step at a time instead of writing scripts. Each call is short, returns compact JSON, and leaves the browser open for the next call. Lives in the frontend repo, e.g. `fe/tools/fe-drive/`, with its own `package.json` script.

## Session

The browser persists between calls through a small session server (or a CDP endpoint) started by `session start`. State lives in a session file under `.fe-drive/` (gitignored): server URL, PID, base URL, viewport.

```bash
fe-drive session start --base-url http://localhost:3200 --viewport 1280x800 [--session <name>]
fe-drive session stop [--session <name>]          # idempotent
fe-drive session status
```

`--session` lets parallel lanes keep separate browsers. Every command takes `--session`, defaulting to `default`.

## Steps

```bash
fe-drive login --email test@test.com --password-env FE_TEST_PASSWORD   # never take a password as an argument
fe-drive goto /agents/new
fe-drive act click --role button --name "Create agent"
fe-drive act fill  --role textbox --name "Name" --value "demo"
fe-drive act press --key Enter
fe-drive wait --role heading --name "demo" [--timeout 5000]
```

Locate by role and accessible name (Playwright `getByRole`), never CSS selectors; a missing name is itself an a11y finding. Each step returns `{"ok":true,"url":...,"title":...,"console_errors":N,"failed_requests":N}` or a JSON error with a stable code (`not_found`, `ambiguous`, `timeout`, `navigation_failed`).

## Snapshot (`fe.inspect`)

```bash
fe-drive snapshot --json [--root main] [--max-nodes 200]
```

Returns, bounded and in document order:

- `a11y`: pruned accessibility tree (role, name, state; drops generic wrappers and text-only leaves beyond a limit).
- `scroll_containers`: elements with `overflow: auto|scroll` and scrollHeight > clientHeight, with their role/name and whether the page itself also scrolls (catches nested-scroll and "page scrolls instead of the panel" bugs).
- `overflow`: elements wider than their container or the viewport (horizontal overflow offenders).
- `focus`: the focused element's role and name.
- `console_errors` and `failed_requests` (method, path, status) since the previous step; URLs stripped of query strings and tokens.

## Audits (`fe.audit`)

```bash
fe-drive audit layout   # overflow, clipped text, overlapping interactive elements, viewport sweep (e.g. 375, 768, 1280)
fe-drive audit a11y     # axe-core violations: id, impact, count, first 3 targets
fe-drive audit links    # internal links reachable, no 4xx/5xx
```

Output is a list of findings with severity and a stable ID, so a tester can cite them in a bug.

## Screenshots and flows

```bash
fe-drive screenshot --out shots/agents-new.png [--full-page] [--diff-against baseline.png --threshold 0.01]
fe-drive flow run fe/tools/fe-drive/flows/create-agent.json
```

A flow is a JSON list of the same steps (`{"goto": "/agents/new"}`, `{"act": "fill", "role": "textbox", "name": "Name", "value": "demo"}`, `{"snapshot": true}`), so reusable scenarios are data, not scripts. `flow run` stops at the first failing step and reports its index.

## Rules

- Output stays small: a step result is one line; a snapshot is capped by `--max-nodes` with a truncation marker.
- Deterministic: fixed viewport, reduced motion, fixed locale and timezone, animations disabled.
- No secrets in output, flows, or screenshots' file names; credentials come from environment variables.
- Smoke test: `session start` against the dev server, `goto /`, `snapshot --max-nodes 5`, `session stop`.
- Port isolation (`env.isolate`) is a separate tool: a private frontend copy on a free port, replacing ad hoc `sync.sh` rewrites.
