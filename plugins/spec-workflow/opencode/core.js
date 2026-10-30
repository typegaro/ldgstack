// Host-independent logic of the OpenCode adapter: paths, agent loading, the tool-mapping note, and translation of
// OpenCode tool calls into the Claude Code hook events that hooks/guard_paths.py already decides on.
import { spawnSync } from "node:child_process"
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HERE = path.dirname(fileURLToPath(import.meta.url))
export const PLUGIN = path.resolve(HERE, "..")
export const REPO = path.resolve(PLUGIN, "..", "..")
export const SKILLS = path.join(PLUGIN, "skills")
export const AGENTS = path.join(HERE, "agents")
export const BIN = path.join(PLUGIN, "bin")
const GUARD = path.join(PLUGIN, "hooks", "guard_paths.py")
export const MARK = "[spec-workflow: OpenCode tool mapping]"

const FILE_TOOLS = new Set(["edit", "write", "multiedit"])
const PATCH_TOOLS = new Set(["patch", "apply_patch"])
const SHELL_TOOLS = new Set(["bash", "shell"])
const PATCH_LINE = /^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$/gm

export function mapping(flavor) {
  const delegate = flavor === "v2"
    ? '`subagent` with `agent: "spec-implementer"` (resume an agent by passing its `sessionID`)'
    : '`task` with `subagent_type: "spec-implementer"` (resume an agent by passing its `task_id`)'
  return `${MARK}
The spec-workflow skills and agents are written for Claude Code. In OpenCode:
- \`spec-workflow:<name>\` names the skill or agent \`<name>\` (\`spec-workflow:spec-tracker\` is the skill \`spec-tracker\`). Load skills with the \`skill\` tool.
- Delegating to a subagent (the Agent tool, \`spec-workflow:spec-implementer\`) → ${delegate}. "Resume with SendMessage" means the same.
- AskUserQuestion → the \`question\` tool when available; otherwise ask in text and wait.
- CLAUDE.md → AGENTS.md (either marks the project root). \`spec\` and \`spec-tracker\` are on PATH in every shell command.
- workflow-retro reads Claude Code transcripts only.`
}

export function frontmatter(text) {
  const match = text.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
  if (!match) return { fields: {}, body: text }
  const fields = {}
  for (const line of match[1].split("\n")) {
    const index = line.indexOf(": ")
    if (index > 0 && !/^\s/.test(line)) fields[line.slice(0, index)] = line.slice(index + 2)
  }
  return { fields, body: match[2] }
}

/** Generated OpenCode agents as V1 config entries: read-only roles get `edit: deny`, and no role may nest subagents. */
export function loadAgents(directory = AGENTS) {
  if (!fs.existsSync(directory)) return []
  return fs.readdirSync(directory).filter((name) => name.endsWith(".md")).sort().map((name) => {
    const text = fs.readFileSync(path.join(directory, name), "utf8")
    const { fields, body } = frontmatter(text)
    const writer = /action: "edit"\n\s+resource: "\*"\n\s+effect: allow/.test(text)
    return {
      name: name.slice(0, -3),
      config: {
        description: fields.description,
        mode: "subagent",
        prompt: body.replace(/^<!--[\s\S]*?-->\n+/, ""),
        permission: { edit: writer ? "allow" : "deny", webfetch: "deny", task: "deny" },
      },
    }
  })
}

export function loadSkills(directory = SKILLS) {
  if (!fs.existsSync(directory)) return []
  return fs.readdirSync(directory, { withFileTypes: true }).filter((entry) => entry.isDirectory()).flatMap((entry) => {
    const file = path.join(directory, entry.name, "SKILL.md")
    if (!fs.existsSync(file)) return []
    const { fields, body } = frontmatter(fs.readFileSync(file, "utf8"))
    return [{ id: entry.name, name: fields.name || entry.name, description: fields.description, path: file, content: body }]
  })
}

/**
 * Claude Code PreToolUse events for one OpenCode tool call, or [] when the guard has nothing to decide.
 * `session` is { directory, subagent, agent, id }: a child session is a subagent, identified by its session ID.
 */
export function guardEvents(tool, args, session) {
  if (args === null || typeof args !== "object") return []
  const base = { cwd: session.directory, ...(session.subagent ? { agent_id: session.id, agent_type: session.agent ?? "" } : {}) }
  if (SHELL_TOOLS.has(tool) && typeof args.command === "string") {
    const cwd = typeof args.workdir === "string" ? path.resolve(session.directory, args.workdir) : session.directory
    return [{ ...base, cwd, tool_name: "Bash", tool_input: { command: args.command } }]
  }
  let files = []
  if (FILE_TOOLS.has(tool)) files = [args.filePath ?? args.file_path ?? args.path].filter((file) => typeof file === "string" && file)
  if (PATCH_TOOLS.has(tool)) files = [...String(args.patchText ?? args.patch ?? "").matchAll(PATCH_LINE)].map((match) => match[1].trim())
  return files.map((file) => ({ ...base, tool_name: "Write", tool_input: { file_path: path.resolve(session.directory, file) } }))
}

/** Runs hooks/guard_paths.py; returns the denial reason, or null. Fails open when Python can't run, like the Claude hook. */
export function denial(event) {
  const env = { ...process.env }
  // A package-manager install is a release artifact, like the Claude plugin cache: never patch it in place.
  if (/[\\/](node_modules|\.cache)[\\/]/.test(REPO)) env.SPEC_WORKFLOW_PLUGIN_CACHE = REPO
  const result = spawnSync("python3", [GUARD], { input: JSON.stringify(event), encoding: "utf8", timeout: 15000, env })
  if (result.error || result.status !== 2) return null
  return result.stderr.trim() || "Denied by the spec-workflow guard."
}

export function withBin(current) {
  const value = current ?? process.env.PATH ?? ""
  return value.split(path.delimiter).includes(BIN) ? value : [BIN, value].filter(Boolean).join(path.delimiter)
}
