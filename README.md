# ldgstack

Agent skills for Claude Code and OpenCode. Each plugin keeps one set of skills, scripts, and guards, with a thin adapter per platform.

| Plugin | Description |
|---|---|
| [spec-workflow](plugins/spec-workflow) | Spec-driven development with an autonomous plan → implement → review → test → fix loop and CLI-enforced gates |

## Install

**Claude Code**

```text
/plugin marketplace add typegaro/ldgstack
/plugin install spec-workflow@ldgstack
```

Update with `/plugin marketplace update ldgstack`.

**OpenCode** (add to `opencode.json`, then restart)

```jsonc
{ "plugin": ["spec-workflow@git+https://github.com/typegaro/ldgstack.git"] }    // 1.x
{ "plugins": ["spec-workflow@git+https://github.com/typegaro/ldgstack.git"] }   // 2.x
```

OpenCode 2.x also needs the agents linked once; see [spec-workflow › Install](plugins/spec-workflow/README.md#opencode).

## Layout

```text
.claude-plugin/marketplace.json     Claude Code marketplace
package.json, index.js              OpenCode package entry (→ plugins/spec-workflow/opencode/plugin.js)
plugins/spec-workflow/
  skills/ agents/ hooks/ bin/       shared source (Claude Code format)
  .claude-plugin/                   Claude Code manifest
  opencode/                         OpenCode plugin, generated agents, build.py, install.sh
  tests/                            Python and Node suites
```

## Development

```bash
python3 plugins/spec-workflow/opencode/build.py           # after changing agents/ or the version
python3 -m unittest discover -s plugins/spec-workflow/tests
```
