---
name: ldgstack
description: ldgstack spec-workflow v0.17.0 - the plugin version this session loaded. Check it against the latest ldgstack before a spec run, after a plugin change, or when asked "are we on the latest ldgstack", and update when behind.
---

# ldgstack version

This session loaded **spec-workflow v0.17.0**. The version in the skill listing is fixed when the session starts or reloads plugins; this file on disk may be newer.

## Check

1. Loaded: the version in this skill's description in your skill listing (not this file).
2. On disk: `python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' <plugin root>/.claude-plugin/plugin.json`. The plugin root is the folder above this skill's `skills/` directory (the "Base directory" printed when the skill loads).
3. Published: in a git checkout of ldgstack, `git -C <repo> fetch -q && git -C <repo> log -1 --format=%s origin/main` (commit subjects end with "update to vX.Y.Z"); otherwise the latest version on github.com/typegaro/ldgstack.

Report all three. Loaded equal to published means up to date.

## Update

- Disk behind published: `git -C <repo> pull --ff-only` for a local checkout, or `/plugin marketplace update ldgstack` for an installed copy.
- Loaded behind disk: run `/reload-plugins` in Claude Code (reloads skills, agents and hooks), or restart OpenCode. Check again.
- Never update in the middle of an agent's assignment; do it between specs.
