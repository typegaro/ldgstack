// spec-workflow for OpenCode 1.x (named export, `server`) and 2.x (default `setup`), from one file.
// Registers the shared skills (and, on 1.x, the agents), runs hooks/guard_paths.py before file and shell tools, puts
// bin/ on PATH, and adds a short note mapping the Claude Code tool names in the skills to OpenCode's.
// Helpers live in core.js: 1.x may treat any exported function here as a plugin.
import { SKILLS, denial, guardEvents, loadAgents, loadSkills, mapping, MARK, withBin } from "./core.js"

const log = (message, error) => console.error(`[spec-workflow] ${message}`, error ?? "")

function check(tool, args, session) {
  for (const event of guardEvents(tool, args, session)) {
    const reason = denial(event)
    // A thrown hook error rejects the tool call and reaches the model.
    if (reason !== null) throw new Error(reason)
  }
}

/** OpenCode 1.x. */
export const SpecWorkflowPlugin = async ({ client, directory }) => {
  const sessions = new Map()
  const agents = new Map()

  const session = async (id) => {
    if (!sessions.has(id)) {
      let parent
      try {
        const result = await client.session.get({ path: { id } })
        parent = (result?.data ?? result)?.parentID
      } catch (error) {
        log("session lookup failed; treating the session as the parent", error)
      }
      sessions.set(id, { id, directory, subagent: typeof parent === "string" && parent.length > 0 })
    }
    return { ...sessions.get(id), agent: agents.get(id) }
  }

  return {
    config: async (config) => {
      if (!Array.isArray(config.skills)) {
        config.skills ??= {}
        config.skills.paths ??= []
        if (!config.skills.paths.includes(SKILLS)) config.skills.paths.push(SKILLS)
      }
      config.agent ??= {}
      for (const { name, config: agent } of loadAgents()) config.agent[name] = { ...agent, ...config.agent[name] }
    },
    "chat.message": async (input) => {
      if (input?.agent) agents.set(input.sessionID, input.agent)
    },
    "experimental.chat.system.transform": async (_input, output) => {
      if (!output.system.some((part) => part.includes(MARK))) output.system.push(mapping("v1"))
    },
    "tool.execute.before": async (input, output) => {
      check(input.tool, output.args, await session(input.sessionID))
    },
    "shell.env": async (_input, output) => {
      output.env.PATH = withBin(output.env.PATH)
    },
  }
}

/** OpenCode 2.x. Agents can't be added by a plugin there; opencode/install.sh links them. */
async function setup(ctx) {
  // 1.x also calls default.setup with a context that lacks these domains; it is served by SpecWorkflowPlugin.
  if (!ctx?.skill?.transform || !ctx?.tool?.hook || !ctx?.session?.hook) return

  try {
    const skills = loadSkills()
    await ctx.skill.transform((draft) => {
      for (const skill of skills) {
        // A throw escaping this callback disables the whole plugin, so contain it per skill.
        try {
          draft.add(skill)
        } catch (error) {
          log(`skill ${skill.id} rejected by the host`, error)
        }
      }
    })
  } catch (error) {
    log("skill registration failed", error)
  }

  const sessions = new Map()
  const session = async (id, agent) => {
    if (!sessions.has(id)) {
      let state = { id, directory: ctx.location.directory, subagent: false }
      try {
        const info = await ctx.session.get({ sessionID: id })
        state = { id, directory: info.location?.directory ?? ctx.location.directory, subagent: info.parentID != null }
      } catch (error) {
        log("session lookup failed; treating the session as the parent", error)
      }
      sessions.set(id, state)
    }
    return { ...sessions.get(id), agent }
  }

  await ctx.tool.hook("execute.before", async (event) => {
    check(event.tool, event.input, await session(event.sessionID, event.agent))
  })
  await ctx.shell?.hook?.("create.before", (event) => {
    event.env.PATH = withBin(event.env.PATH)
  })
  await ctx.session.hook("context", async (event) => {
    try {
      const first = event.messages?.find((message) => message.role === "user")
      if (!first || first.content?.some((part) => part.type === "text" && part.text?.includes(MARK))) return
      first.content.unshift({ type: "text", text: mapping("v2") })
    } catch (error) {
      log("context hook failed", error)
    }
  })
}

export default { id: "spec-workflow", server: SpecWorkflowPlugin, setup }
