#!/usr/bin/env bash
# OpenCode 2.x plugins can register skills but not agents: link the spec-workflow agents into an agents directory.
# OpenCode 1.x doesn't need this (the plugin registers the agents itself).
set -euo pipefail

SOURCE="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/agents"
TARGET="${OPENCODE_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode}/agents"
MODE=link
UNINSTALL=0

usage() {
  cat <<'EOF'
Usage: install.sh [--project DIR] [--copy] [--uninstall]

  --project DIR   Use DIR/.opencode/agents instead of the global ~/.config/opencode/agents.
  --copy          Copy the files instead of symlinking them (rerun after each update).
  --uninstall     Remove the spec-workflow agents from the target.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --project) [ $# -ge 2 ] || { usage >&2; exit 2; }; TARGET="$(CDPATH= cd -- "$2" && pwd)/.opencode/agents"; shift 2 ;;
    --copy) MODE=copy; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

mkdir -p "$TARGET"
for agent in "$SOURCE"/*.md; do
  destination="$TARGET/$(basename "$agent")"
  if [ "$UNINSTALL" -eq 1 ]; then
    rm -f "$destination"
  elif [ "$MODE" = copy ]; then
    cp -f "$agent" "$destination"
  else
    ln -sfn "$agent" "$destination"
  fi
done
echo "$([ "$UNINSTALL" -eq 1 ] && echo removed || echo installed) spec-workflow agents in $TARGET"
