// OpenCode adapter: drives plugin.js through fake 1.x and 2.x hosts against a temporary project and the real guard.
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { test } from "node:test"
import plugin, { SpecWorkflowPlugin } from "../opencode/plugin.js"
import { BIN, MARK, SKILLS, loadAgents, loadSkills } from "../opencode/core.js"

function project() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "spec-workflow-oc-"))
  for (const directory of ["specs", "implementation/active", "src"]) fs.mkdirSync(path.join(root, directory), { recursive: true })
  fs.writeFileSync(path.join(root, "AGENTS.md"), "# Test\n")
  fs.writeFileSync(path.join(root, "specs", "0001-first.md"), "---\nid: 1\n---\n# First\n")
  return root
}

const client = (parents) => ({ session: { get: async ({ path: { id } }) => ({ data: { id, parentID: parents[id] } }) } })

test("skills and agents load from the shared plugin", () => {
  const skills = loadSkills()
  const expected = fs.readdirSync(SKILLS).filter((name) => fs.existsSync(path.join(SKILLS, name, "SKILL.md")))
  assert.deepEqual(skills.map((skill) => skill.id).sort(), expected.sort())
  assert.ok(skills.every((skill) => skill.description && !skill.content.startsWith("---")))

  const agents = Object.fromEntries(loadAgents().map(({ name, config }) => [name, config]))
  assert.equal(Object.keys(agents).length, 6)
  assert.equal(agents["spec-tester"].permission.edit, "deny")
  assert.equal(agents["spec-reviewer"].permission.edit, "deny")
  assert.equal(agents["spec-planner"].permission.edit, "deny")
  assert.equal(agents["spec-implementer"].permission.edit, "allow")
  assert.ok(Object.values(agents).every((agent) => agent.mode === "subagent" && agent.permission.task === "deny"))
  assert.ok(Object.values(agents).every((agent) => !agent.prompt.includes("spec-workflow:") && !agent.prompt.startsWith("<!--")))
})

test("1.x: config registers skills and agents, keeping user overrides", async () => {
  const hooks = await SpecWorkflowPlugin({ client: client({}), directory: project() })
  const config = { agent: { "spec-planner": { model: "provider/deep" } } }
  await hooks.config(config)
  await hooks.config(config)
  assert.deepEqual(config.skills.paths, [SKILLS])
  assert.equal(config.agent["spec-planner"].model, "provider/deep")
  assert.equal(config.agent["spec-planner"].mode, "subagent")
  assert.equal(Object.keys(config.agent).length, 6)
})

test("1.x: the guard denies workflow-state and spec edits, and subagent spec edits", async () => {
  const root = project()
  const hooks = await SpecWorkflowPlugin({ client: client({ child: "parent" }), directory: root })
  const call = (tool, args, sessionID = "parent") => hooks["tool.execute.before"]({ tool, sessionID, callID: "c" }, { args })

  await assert.rejects(call("write", { filePath: "implementation/active/0001-first.json" }), /Workflow state/)
  await assert.rejects(call("bash", { command: "echo {} > implementation/toolkit.json" }), /Workflow state/)
  await assert.rejects(call("apply_patch", { patchText: "*** Begin Patch\n*** Add File: implementation/archive/x.json\n+{}\n*** End Patch" }), /Workflow state/)
  await assert.rejects(call("edit", { filePath: path.join(root, "specs", "0001-first.md") }), /audited/)
  await assert.rejects(call("edit", { filePath: "specs/0001-first.md" }, "child"), /Subagents must not modify specs/)
  await assert.rejects(call("bash", { command: "spec new --title X" }, "child"), /only the parent/)
  await call("write", { filePath: "src/main.go" })
  await call("write", { filePath: "specs/.drafts/idea.md" })
  await call("bash", { command: "go test ./..." })
  await call("read", { filePath: "implementation/toolkit.json" })
})

test("1.x: the mapping note is added once and bin/ is on PATH", async () => {
  const hooks = await SpecWorkflowPlugin({ client: client({}), directory: project() })
  const output = { system: ["base"] }
  await hooks["experimental.chat.system.transform"]({}, output)
  await hooks["experimental.chat.system.transform"]({}, output)
  assert.equal(output.system.filter((part) => part.includes(MARK)).length, 1)
  assert.match(output.system[1], /subagent_type/)

  const env = { env: { PATH: "/usr/bin" } }
  await hooks["shell.env"]({ cwd: "/" }, env)
  await hooks["shell.env"]({ cwd: "/" }, env)
  assert.equal(env.env.PATH, `${BIN}${path.delimiter}/usr/bin`)
})

test("2.x: setup registers skills, guards tools, and adds the mapping note", async () => {
  const root = project()
  const added = []
  const hooks = {}
  const ctx = {
    location: { directory: root },
    skill: { transform: async (edit) => edit({ add: (skill) => added.push(skill.id) }) },
    tool: { hook: async (name, handler) => { hooks[`tool.${name}`] = handler } },
    shell: { hook: async (name, handler) => { hooks[`shell.${name}`] = handler } },
    session: {
      hook: async (name, handler) => { hooks[`session.${name}`] = handler },
      get: async ({ sessionID }) => ({ id: sessionID, parentID: sessionID === "child" ? "parent" : undefined }),
    },
  }
  await plugin.setup(ctx)
  assert.equal(added.length, loadSkills().length)

  const before = hooks["tool.execute.before"]
  await assert.rejects(before({ tool: "write", sessionID: "parent", agent: "build", input: { path: "implementation/spec-archive.json" } }), /Workflow state/)
  await assert.rejects(before({ tool: "shell", sessionID: "child", agent: "spec-tester", input: { command: "rm specs/0001-first.md" } }), /Subagents/)
  await before({ tool: "edit", sessionID: "child", agent: "spec-implementer", input: { path: "src/a.ts" } })

  const event = { messages: [{ role: "user", content: [{ type: "text", text: "go" }] }] }
  await hooks["session.context"](event)
  await hooks["session.context"](event)
  assert.equal(event.messages[0].content.length, 2)
  assert.match(event.messages[0].content[0].text, /`subagent` with `agent:/)

  const shell = { env: { PATH: "/bin" } }
  hooks["shell.create.before"](shell)
  assert.ok(shell.env.PATH.startsWith(BIN))
})

test("1.x hosts calling default.setup are ignored", async () => {
  await plugin.setup({ client: {}, directory: "/" })
})
