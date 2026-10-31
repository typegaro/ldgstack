"use strict";
/* ldgstack / spec-workflow dashboard. Read-only single-page app: hash routes, no build step.
   Every piece of data reaches the DOM through textContent or attributes, never innerHTML. */

const STAGES = [
  ["draft", "Draft"], ["ready", "Ready"], ["planning", "Planning"], ["implementing", "Implementing"], ["review", "In review"],
  ["test", "Testing"], ["merge", "Merge queue"], ["accepted", "Accepted"], ["deferred", "Deferred"],
];
const STAGE_PILL = { implementing: "impl", planning: "plan", review: "review", test: "test", merge: "merge", accepted: "accepted", draft: "draft", ready: "ready", deferred: "deferred" };
const STAGE_LABEL = Object.fromEntries(STAGES);
const EVENT_ICONS = { created: "P", plan: "◇", work: "▲", check_pass: "✓", check_fail: "!", check_other: "○", question: "?", answer: "A", generation: "↻", merge: "⇢", spec: "S" };

const store = { meta: null, prs: null, queues: null, specs: null };
const view = { prState: "open", prFilter: "", prStatus: "", prArea: "", stage: "all", kind: "all", tab: "", token: 0, live: false };

// DOM helpers ---------------------------------------------------------------------------------------------

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

const span = (cls, text) => h("span", { class: cls, text });
const lbl = (text, cls) => h("span", { class: "lbl " + (cls || ""), text });
const link = (href, text, cls) => h("a", { href, class: cls, text });

function ago(iso) {
  const then = Date.parse(iso || "");
  if (Number.isNaN(then)) return "";
  const s = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function dur(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "–";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

function since(iso) {
  const then = Date.parse(iso || "");
  return Number.isNaN(then) ? null : (Date.now() - then) / 1000;
}

function when(iso) {
  const node = h("span", { class: "meta", text: ago(iso) || (iso || "") });
  if (iso) node.title = iso;
  return node;
}

function shortDate(iso) {
  const d = new Date(iso || "");
  if (Number.isNaN(d.getTime())) return iso || "";
  const today = new Date();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  return d.toDateString() === today.toDateString() ? `today ${time}` : d.toLocaleDateString([], { day: "numeric", month: "short" });
}

const num = (n) => Number(n || 0).toLocaleString("en-US");
const specLabel = (id) => String(id).padStart(4, "0");

// Data ----------------------------------------------------------------------------------------------------

async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

async function loadBase() {
  const [meta, prs, queues, specs] = await Promise.all([api("/api/meta"), api("/api/prs"), api("/api/queues"), api("/api/specs")]);
  Object.assign(store, { meta, prs, queues, specs });
}

const prList = () => (store.prs ? store.prs.prs : []);
const openPrs = () => prList().filter((pr) => pr.state === "open");
const specById = (id) => (store.specs ? store.specs.specs.find((s) => s.id === Number(id)) : null);
const prByFeature = (feature) => prList().find((pr) => pr.feature === feature);

// Shared pieces -------------------------------------------------------------------------------------------

function pillFor(pr) {
  const queue = pr.queue;
  let label = pr.pill.label;
  if (pr.pill.key === "waitTest" && queue && queue.name === "test" && queue.position) label += ` · #${queue.position}`;
  if (pr.pill.key === "merge" && queue && queue.name === "merge" && queue.position) label = `Queued to merge · #${queue.position}`;
  return lbl(label, "pill-" + pr.pill.key);
}

function repoArea(pr) {
  const repos = Object.keys(pr.repos || {});
  return repos.length ? repos.join(" + ") : "–";
}

function conflicts(pr) {
  return Object.values(pr.repos || {}).some((repo) => Array.isArray(repo.conflicts) && repo.conflicts.length);
}

function ciCell(pr) {
  const ci = pr.fast_ci;
  if (ci && Array.isArray(ci.commands) && ci.commands.length) {
    const ok = ci.commands.filter((c) => c.exit === 0).length;
    return [ci.result === "failed" || ok < ci.commands.length ? `✗ ${ok}/${ci.commands.length}` : `✓ ${ok}/${ci.commands.length}`, ci.result === "failed" || ok < ci.commands.length ? "t-bad" : "t-good"];
  }
  if (ci && ci.result === "running") return ["running", "t-warn"];
  const c = pr.checks || { total: 0 };
  if (!c.total) return ["–", "t-muted"];
  return c.failed ? [`✗ ${c.passed}/${c.total}`, "t-bad"] : [`✓ ${c.passed}/${c.total}`, "t-good"];
}

function reviewCell(pr) {
  if (pr.stage === "planning" || (pr.stage === "implementing" && !pr.review_rounds)) return "–";
  if (pr.stage === "review") return `round ${Math.max(1, pr.review_rounds || 1)}`;
  return pr.review_rounds ? (pr.stage === "implementing" ? `round ${pr.review_rounds}` : "passed") : "–";
}

function bugsCell(pr) {
  const total = (pr.bugs && pr.bugs.total) || 0;
  const open = (pr.bugs && pr.bugs.open) || 0;
  if (!total && (pr.stage === "planning" || pr.stage === "implementing")) return ["–", "t-muted"];
  return [`${open} open`, open ? "t-bad" : "t-muted"];
}

function emptyBox(text) {
  return h("div", { class: "empty", text });
}

// Header --------------------------------------------------------------------------------------------------

function renderNav(route) {
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  const agents = store.queues ? store.queues.agents.length : 0;
  const items = [
    ["pulls", "#/pulls", "Pull requests", store.prs ? openPrs().length : null],
    ["queues", "#/queues", "Queues", store.queues ? agents : null],
    ["specs", "#/specs", "Specs", store.specs ? store.specs.specs.length : null],
    ["activity", "#/activity", "Activity", null],
  ];
  const section = { pull: "pulls", spec: "specs" }[route.name] || route.name;
  for (const [id, href, text, count] of items) {
    const a = h("a", { href }, text, count === null ? null : lbl(String(count)));
    if (id === section) a.setAttribute("aria-current", "page");
    nav.append(a);
  }
  document.querySelector(".brand .project")?.remove();
  if (store.meta) document.querySelector(".brand").append(h("span", { class: "project", text: "· " + store.meta.project }));
  renderLive();
}

function renderLive() {
  const el = document.getElementById("live");
  el.replaceChildren();
  el.classList.toggle("off", !view.live);
  const heads = store.meta ? Object.entries(store.meta.main || {}).map(([repo, sha]) => `${repo} ${sha}`).join(" · ") : "";
  append(el, [h("span", { class: "dot" }), h("span", { class: "project-chip", text: store.meta ? store.meta.project : "" }),
    h("span", { text: (view.live ? "· Live" : "· Reconnecting…") + (heads ? " · main " + heads : "") })]);
}

// Routes --------------------------------------------------------------------------------------------------

function parseRoute() {
  const parts = (location.hash.replace(/^#\/?/, "") || "pulls").split("/").map(decodeURIComponent);
  return { name: parts[0] || "pulls", arg: parts[1] || "" };
}

async function render() {
  const token = ++view.token;
  const route = parseRoute();
  const app = document.getElementById("app");
  const focus = document.activeElement && document.activeElement.id;
  const caret = document.activeElement && document.activeElement.selectionStart;
  const scroll = window.scrollY;
  try {
    await loadBase();
    let content;
    if (route.name === "pull" && route.arg) content = await pullView(route.arg);
    else if (route.name === "spec" && route.arg) content = await specView(route.arg);
    else if (route.name === "queues") content = queuesView();
    else if (route.name === "specs") content = specsView();
    else if (route.name === "activity") content = await activityView();
    else content = pullsView();
    if (token !== view.token) return;
    renderNav(route);
    app.replaceChildren(content);
    document.title = `${route.name === "pulls" ? "Pull requests" : route.name[0].toUpperCase() + route.name.slice(1)} · ldgstack / spec-workflow`;
  } catch (error) {
    if (token !== view.token) return;
    app.replaceChildren(h("div", { class: "banner", role: "alert", text: `Could not load: ${error.message}` }));
  }
  window.scrollTo(0, scroll);
  if (focus) {
    const again = document.getElementById(focus);
    if (again) {
      again.focus();
      if (typeof caret === "number" && again.setSelectionRange) again.setSelectionRange(caret, caret);
    }
  }
}

function tabBar(tabs, label, rerender) {
  if (!tabs.some(([id]) => id === view.tab)) view.tab = tabs[0][0];
  const bar = h("div", { class: "tabs", role: "tablist", "aria-label": label });
  for (const [id, text, count] of tabs) {
    bar.append(h("button", { type: "button", role: "tab", "aria-selected": String(view.tab === id), onclick: () => { view.tab = id; rerender(); } },
      text, count === undefined ? null : lbl(String(count))));
  }
  return bar;
}

// Pull requests -------------------------------------------------------------------------------------------

function pullsView() {
  const root = h("div");
  const prs = prList();
  const draw = () => {
    root.replaceChildren(...pullsParts(prs, draw));
  };
  draw();
  return root;
}

function pullsParts(prs, redraw) {
  const search = h("input", { id: "pr-filter", type: "text", value: view.prFilter, placeholder: "Filter by title, number, branch or role", autocomplete: "off",
    oninput: (e) => { view.prFilter = e.target.value; updateList(); } });
  const statusSelect = select("pr-status", "Status", [["", "Status: all"], ...[...new Set(prs.map((p) => p.pill.key + "|" + p.pill.label.split(" · ")[0]))].map((v) => v.split("|"))], view.prStatus,
    (v) => { view.prStatus = v; updateList(); });
  const areas = [...new Set(prs.map(repoArea))];
  const areaSelect = select("pr-area", "Area", [["", "Area: all"], ...areas.map((a) => [a, a])], view.prArea, (v) => { view.prArea = v; updateList(); });
  const toolbar = h("div", { class: "toolbar" },
    h("label", { class: "search" }, h("span", { class: "meta", text: "Filter" }), search), statusSelect, areaSelect);
  const open = prs.filter((p) => p.state === "open");
  const merged = prs.filter((p) => p.state === "merged");
  const toggle = (state, text, list) => h("button", { type: "button", "aria-pressed": String(view.prState === state), onclick: () => { view.prState = state; redraw(); } },
    h("span", { class: "dot dot-" + (state === "open" ? "impl" : "merged") }), `${list.length} ${text}`);
  const list = h("div");
  const box = h("div", { class: "box" },
    h("div", { class: "box-head" }, toggle("open", "Open", open), toggle("merged", "Merged", merged), h("span", { class: "grow" }),
      span("meta col", "Checks"), span("meta col", "Review"), span("meta col narrow", "Bugs")), list);
  function updateList() {
    const needle = view.prFilter.trim().toLowerCase();
    const rows = (view.prState === "open" ? open : merged).filter((pr) => {
      if (view.prStatus && pr.pill.key !== view.prStatus) return false;
      if (view.prArea && repoArea(pr) !== view.prArea) return false;
      const hay = `${pr.title} ${pr.spec_id} ${pr.feature} ${pr.current_role || ""} ${pr.pill.label}`.toLowerCase();
      return !needle || needle.split(/\s+/).every((word) => hay.includes(word));
    });
    list.replaceChildren(...(rows.length ? rows.map(prRow) : [emptyBox(view.prState === "open" ? "No open pull requests." : "No merged pull requests.")]));
  }
  updateList();
  const note = h("p", { class: "meta", text: "Updates live from implementation/ and the git worktrees. Read-only: actions stay in the CLI." });
  const banner = store.prs && !store.prs.pr_status_available
    ? h("p", { class: "banner", text: "Pull request data comes from the implementation records (no `pr status` command in this tracker yet), so branch diff stats and fast-CI results are not shown." })
    : null;
  return [banner, toolbar, box, note];
}

function select(id, label, options, value, onchange) {
  const el = h("select", { id, class: "select", "aria-label": label, onchange: (e) => onchange(e.target.value) });
  for (const [v, text] of options) {
    const option = h("option", { value: v, text });
    if (v === value) option.selected = true;
    el.append(option);
  }
  return el;
}

function prRow(pr) {
  const [ci, ciClass] = ciCell(pr);
  const [bugs, bugClass] = bugsCell(pr);
  const branch = Object.values(pr.repos || {}).map((r) => r.branch).find(Boolean) || pr.feature;
  const stamp = pr.state === "merged" ? "merged " + ago(pr.merged_at) : "updated " + ago(pr.updated_at);
  return h("div", { class: "row" },
    h("span", { class: "dot dot-" + pr.pill.key, "aria-hidden": "true" }),
    h("div", { class: "main" },
      h("div", { class: "titleline" }, link("#/pull/" + encodeURIComponent(pr.feature), pr.title, "title"), pillFor(pr), lbl(repoArea(pr)),
        pr.risk === "high" ? lbl("high risk", "warn") : null, conflicts(pr) ? lbl("conflicts with main", "bad") : null),
      span("meta", `#${pr.spec_id} · ${branch} · ${stamp}${pr.current_role && pr.state === "open" ? " · " + pr.current_role + (pr.model ? ` (${pr.model})` : "") : ""}`)),
    span("col " + ciClass, ci), span("col", reviewCell(pr)), span("col narrow " + bugClass, bugs));
}

// Pull request detail -------------------------------------------------------------------------------------

async function pullView(feature) {
  const data = await api("/api/record/" + encodeURIComponent(feature));
  const pr = data.pr;
  const root = h("div");
  const draw = () => root.replaceChildren(...pullParts(data, pr, draw));
  draw();
  return root;
}

function repoStat(name, repo) {
  if (typeof repo.additions !== "number") return null;
  return h("span", {}, ` · ${name} `, span("t-good", "+" + num(repo.additions)), " ", span("t-bad", "−" + num(repo.deletions)));
}

function pullParts(data, pr, redraw) {
  const repos = Object.entries(pr.repos || {});
  const files = Object.entries(data.files || {});
  const fileCount = repos.reduce((n, [, r]) => n + (r.files || 0), 0) || files.reduce((n, [, list]) => n + list.length, 0);
  const tabs = [["conv", "Conversation", data.timeline.length], ["checks", "Checks", data.checks.length], ["reqs", "Requirements", data.requirements.length],
    ["bugs", "Bugs", data.bugs.length], ["files", "Files changed", fileCount], ["plan", "Plan", data.plan ? data.plan.batches.length : 0]];
  const bar = tabBar(tabs, "Pull request sections", redraw);
  const branch = repos.map(([, r]) => r.branch).find(Boolean) || data.feature;
  const head = [
    h("h1", { class: "page" }, pr.title, " ", span("num", "#" + pr.spec_id)),
    h("div", { class: "subline" }, lbl(pr.pill.label, "big solid pill-" + pr.pill.key),
      h("span", { class: "meta" }, span("mono-soft", branch), " → ", span("mono-soft", "main"), repos.map(([name, repo]) => repoStat(name, repo)),
        repos.length ? (conflicts(pr) ? " · conflicts with main" : " · no conflicts") : null),
      pr.risk === "high" ? lbl("high risk", "warn") : null, link("#/spec/" + pr.spec_id, "Spec #" + pr.spec_id)),
  ];
  let body;
  if (view.tab === "conv") body = conversation(data);
  else if (view.tab === "checks") body = checksTab(data);
  else if (view.tab === "reqs") body = requirementsTab(data);
  else if (view.tab === "bugs") body = bugsTab(data);
  else if (view.tab === "files") body = filesTab(pr, data);
  else body = planTab(data);
  return [...head, bar, h("div", { class: "layout" }, h("section", { class: "content", "aria-label": "Details" }, body), prSidebar(data, pr))];
}

function conversation(data) {
  if (!data.timeline.length) return emptyBox("Nothing recorded yet.");
  const list = h("ol", { class: "timeline" });
  for (const event of data.timeline) {
    list.append(h("li", {},
      h("span", { class: "ev-icon ev-" + event.kind, "aria-hidden": "true", text: EVENT_ICONS[event.kind] || "•" }),
      h("div", { class: "ev-body" }, h("span", {}, span("who", event.who), " ", span("what", event.what)),
        event.note ? span("note", event.note) : null, when(event.at))));
  }
  return list;
}

function checksTab(data) {
  if (!data.checks.length) return emptyBox("No checks recorded.");
  const box = h("div", { class: "box" });
  for (const check of data.checks) {
    const [mark, cls] = check.result === "passed" ? ["✓", "t-good"] : check.result === "failed" ? ["✗", "t-bad"] : check.result === "not_run" ? ["○", "t-muted"] : ["–", "t-muted"];
    box.append(h("div", { class: "item-row" },
      span(cls, mark), h("div", { class: "grow" }, span("mono", check.name), span("meta", [check.role, check.method, check.evidence].filter(Boolean).join(" · "))),
      check.seconds ? span("meta", dur(check.seconds)) : when(check.at), check.log ? span("meta mono", check.log) : null));
  }
  return box;
}

function requirementsTab(data) {
  if (!data.requirements.length) return emptyBox("No requirements tracked.");
  const box = h("div", { class: "box" });
  for (const req of data.requirements) {
    box.append(h("div", { class: "detail" },
      h("div", { class: "titleline", style: "display:flex;gap:8px;flex-wrap:wrap;align-items:center" }, span("mono", req.id), span("meta", req.spec_ref),
        lbl(req.implemented ? "implemented" : "not implemented", req.implemented ? "good" : ""), lbl(req.tested ? "tested" : "not tested", req.tested ? "good" : "")),
      h("p", { text: req.text }),
      req.implementation_evidence ? span("meta", "Implementation: " + req.implementation_evidence) : null,
      req.test_evidence ? span("meta", "Test: " + req.test_evidence) : null));
  }
  return box;
}

function bugsTab(data) {
  if (!data.bugs.length) return emptyBox("No bugs recorded.");
  const box = h("div", { class: "box" });
  for (const bug of data.bugs) {
    const terminal = ["verified", "closed_not_a_bug", "follow_up"].includes(bug.status);
    box.append(h("div", { class: "detail" },
      h("div", { style: "display:flex;gap:8px;flex-wrap:wrap;align-items:center" }, span("mono", bug.id.replace(/^BUG-\d{4}-[a-z0-9-]*?(\d{3})$/, "BUG-$1")),
        lbl(bug.severity || "?", bug.severity === "high" || bug.severity === "critical" ? "bad" : "warn"), lbl(bug.status.replace("_", " "), terminal ? "good" : "bad"),
        span("meta", "found by " + (bug.found_by || "?"))),
      h("p", { text: bug.title }),
      bug.reproduction ? span("meta", "Reproduction: " + bug.reproduction) : null, bug.fix ? span("meta", "Fix: " + bug.fix) : null,
      bug.retest ? span("meta", "Retest: " + bug.retest) : null));
  }
  return box;
}

function filesTab(pr, data) {
  const repos = Object.entries(pr.repos || {});
  const files = data.files || {};
  const names = [...new Set([...repos.map(([n]) => n), ...Object.keys(files)])];
  if (!names.length) return emptyBox("No changed files recorded.");
  return h("div", {}, names.map((name) => {
    const repo = (pr.repos || {})[name] || {};
    const list = files[name] || [];
    return h("div", { class: "filegroup" },
      h("h2", { class: "meta", style: "margin:0 0 6px" }, name, repo.branch ? ` · ${repo.branch}` : "", typeof repo.files === "number" ? ` · ${repo.files} files` : "",
        typeof repo.additions === "number" ? [" · ", span("t-good", "+" + num(repo.additions)), " ", span("t-bad", "−" + num(repo.deletions))] : null,
        typeof repo.ahead === "number" ? ` · ${repo.ahead} ahead, ${repo.behind || 0} behind` : null),
      repo.conflicts && repo.conflicts.length ? h("p", { class: "banner" }, "Conflicts: " + repo.conflicts.join(", ")) : null,
      list.length ? h("div", { class: "box" }, h("ul", {}, list.map((f) => h("li", { text: f })))) : null);
  }));
}

function planTab(data) {
  if (!data.plan) return emptyBox("No plan stored.");
  return h("div", { class: "stack" }, h("p", { class: "meta", text: `Plan v${data.plan.version} · ${data.plan.batches.length} batches` }),
    data.plan.batches.map((batch) => h("div", { class: "box plan-batch" },
      h("div", { class: "box-head" }, h("strong", { text: `Batch ${batch.number}${batch.title ? ": " + batch.title : ""}` }),
        span("meta", (batch.requirements || []).join(", "))),
      h("div", { class: "detail md" }, markdown(batch.text, {})))));
}

function prSidebar(data, pr) {
  const side = data.sidebar;
  const reqs = pr.requirements || { total: 0, implemented: 0, tested: 0 };
  const total = Math.max(reqs.total, 1);
  const bar = h("div", { class: "bar", role: "img", "aria-label": `${reqs.implemented} of ${reqs.total} implemented, ${reqs.tested} tested` },
    h("span", { class: "a", style: `width:${(reqs.tested / total) * 100}%` }), h("span", { class: "b", style: `width:${((reqs.implemented - reqs.tested) / total) * 100}%` }));
  const running = side.running.length ? side.running.map((r) => span("", `${r.role}${r.batch ? " · batch " + r.batch : ""} · ${dur(since(r.since))}`))
    : [span("t-muted", pr.state === "merged" ? "merged" : "nothing running")];
  const finders = Object.entries(side.bugs_by_finder).map(([f, n]) => `${n} by ${f}`).join(" · ");
  const fixed = side.bugs_by_status.verified || 0;
  return h("aside", { "aria-label": "Summary" },
    h("div", { class: "side" }, h("h2", { text: "Now" }), running, pr.queue && pr.queue.name ? span("meta", `${pr.queue.name} queue${pr.queue.position ? " #" + pr.queue.position : ""}`) : null),
    h("div", { class: "side" }, h("h2", { text: "Requirements" }), bar, span("meta", `${reqs.implemented} implemented · ${reqs.tested} tested of ${reqs.total}`)),
    h("div", { class: "side" }, h("h2", { text: "Bugs" }), h("span", {}, span("t-good", `${fixed} fixed`), " · ", span(pr.bugs.open ? "t-bad" : "t-muted", `${pr.bugs.open} open`)),
      finders ? span("meta", finders) : null),
    h("div", { class: "side" }, h("h2", { text: "Rounds" }), span("", `${side.batches} batches · ${side.reviews} reviews · ${side.fixes} fixes`),
      span("meta", `${pr.state === "merged" ? "open for" : "open for"} ${dur(side.open_seconds)}`)),
    h("div", { class: "side" }, h("h2", { text: "Depends on" }),
      side.depends_on.length ? side.depends_on.map((d) => h("span", {}, link("#/spec/" + d.id, "#" + specLabel(d.id)), " ", span("meta", d.title), " ",
        lbl(d.status === "accepted" ? "merged" : d.status, d.status === "accepted" ? "violet" : ""))) : span("meta", "none")));
}

// Queues ---------------------------------------------------------------------------------------------------

function queuesView() {
  const q = store.queues;
  const titleOf = (feature) => {
    const pr = prByFeature(feature);
    return `#${feature.slice(0, 4)} ${pr ? pr.title : feature}`;
  };
  const featureLink = (feature) => link("#/pull/" + encodeURIComponent(feature), titleOf(feature));
  const card = (key, title, extra) => {
    const data = q.queues[key] || { slots: {}, holders: [], waiting: [] };
    const classes = Object.keys(data.slots || {});
    const chips = classes.map((c) => lbl(`${c === "default" ? "slots" : c} ${data.holders.filter((x) => (x.class || "default") === c).length}/${data.slots[c]}`));
    const items = [
      ...data.holders.map((x) => h("div", { class: "item" }, h("span", { class: "dot dot-" + key }), featureLink(x.feature),
        span("meta", `${x.class && x.class !== "default" ? x.class + " · " : ""}${dur(since(x.since))}`))),
      ...data.waiting.map((x, i) => h("div", { class: "item" }, span("meta pos", String(x.position || i + 1)), featureLink(x.feature),
        span("meta", `waiting ${dur(since(x.since))}`))),
    ];
    if (!items.length) items.push(h("div", { class: "item" }, span("meta", key === "review" ? "No PRs waiting for review" : "Nothing queued")));
    return h("section", { class: "card", "aria-labelledby": "q-" + key }, h("div", { class: "card-head", id: "q-" + key }, title,
      data.holders.length && !classes.length ? lbl(`${data.holders.length} running`) : null, chips, extra && extra(data)), items);
  };
  const waitingForMerge = (data) => (data.waiting[0] ? lbl("next: #" + data.waiting[0].feature.slice(0, 4)) : null);
  const mergeLast = (data) => (data.last ? lbl(`last: ${data.last.result}`, data.last.result === "merged" ? "violet" : "bad") : null);
  const cards = h("div", { class: "cards" }, card("review", "Review"), card("test", "Test"),
    card("merge", "Merge", (d) => [waitingForMerge(d), mergeLast(d)]));
  const mergeCard = cards.lastChild;
  mergeCard.append(h("div", { class: "item" }, span("meta", `After merge: re-check ${openPrs().length} open PRs for conflicts`)));
  const rows = q.agents.map((a) => h("tr", {}, h("td", { text: a.role }), h("td", {}, link("#/pull/" + encodeURIComponent(a.feature), "#" + a.feature.slice(0, 4))),
    h("td", { text: a.model || "–" }), h("td", { class: "mono-soft", text: a.assignment + (a.batch ? ` · batch ${a.batch}` : "") }),
    h("td", { text: a.claimed_at ? new Date(a.claimed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }) : "–" }),
    h("td", { text: dur(since(a.claimed_at)) })));
  const agents = h("section", { class: "box", "aria-labelledby": "agents-h" },
    h("div", { class: "card-head", id: "agents-h", style: "background:var(--surface-2)" }, "Running agents", lbl(String(q.agents.length))),
    q.agents.length ? h("div", { class: "scroll" }, h("table", {}, h("thead", {}, h("tr", {}, ["Role", "Spec", "Model", "Assignment", "Started", "Elapsed"].map((t) => h("th", { text: t })))),
      h("tbody", {}, rows))) : emptyBox("No agents running."));
  const c = q.counters;
  const finders = Object.entries(c.bugs_by_finder).map(([f, n]) => `${n} ${f}`).join(" · ");
  const totalBugs = Object.values(c.bugs_by_finder).reduce((a, b) => a + b, 0);
  const counter = (title, value, note) => h("div", { class: "card counter" }, span("meta", title), span("big", value), span("meta", note));
  const counters = h("section", { class: "cards", "aria-label": "Counters" },
    counter("Merged today", String(c.merged_today), `median open → merged ${dur(c.median_seconds_to_merge)}`),
    counter("Review rounds per spec", c.review_rounds_per_spec === null ? "–" : String(c.review_rounds_per_spec), `last ${c.review_rounds_sample} specs`),
    counter("Bugs found", num(totalBugs), finders || "none"),
    counter("Test slot wait", dur(c.median_test_wait_seconds), "median, review → first tester"));
  const banner = q.available ? null : h("p", { class: "banner", role: "status", text: "Queues not available: this tracker has no `queue status` command yet. Showing what the records say; slots and order are unknown." });
  return h("div", { class: "stack" }, banner, cards, agents, counters);
}

// Specs ----------------------------------------------------------------------------------------------------

function specsView() {
  const root = h("div", { class: "stack" });
  const draw = () => root.replaceChildren(...specsParts(draw));
  draw();
  return root;
}

function specsParts(redraw) {
  const data = store.specs;
  const strip = h("div", { class: "stages" }, STAGES.map(([key, name]) => h("button", { type: "button", class: "stagebtn", "aria-pressed": String(view.stage === key),
    onclick: () => { view.stage = view.stage === key ? "all" : key; redraw(); } },
  h("span", { class: "name" }, h("span", { class: "dot dot-" + STAGE_PILL[key] }), name), span("count", String(data.stages[key] || 0)))));
  const pipeline = h("section", { class: "pipeline", "aria-label": "Pipeline" },
    h("div", { style: "display:flex;gap:8px;align-items:center" }, h("strong", { text: "Pipeline" }), span("meta", "every spec, by stage")), strip);
  const kinds = ["all", ...data.kinds];
  const kindBar = h("div", { class: "toolbar", style: "margin:0", role: "group", "aria-label": "Kind" }, span("meta", "Kind"),
    kinds.map((k) => h("button", { type: "button", class: "chipbtn", "aria-pressed": String(view.kind === k), onclick: () => { view.kind = k; redraw(); } }, k === "all" ? "All" : k)),
    h("span", { class: "grow" }), span("meta", "Showing: " + (view.stage === "all" ? "all stages" : STAGE_LABEL[view.stage])));
  const rows = data.specs.filter((s) => (view.stage === "all" || s.stage === view.stage) && (view.kind === "all" || s.kind === view.kind));
  const table = h("section", { class: "box", "aria-label": "Specs" }, rows.length ? h("div", { class: "scroll" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Spec", "Kind", "Stage", "Depends on", "Wave", "Updated"].map((t) => h("th", { text: t })))),
    h("tbody", {}, rows.map((s) => h("tr", {},
      h("td", { class: "wrap" }, link("#/spec/" + s.id, s.title), " ", span("meta", "#" + specLabel(s.id))),
      h("td", {}, lbl(s.kind)), h("td", {}, lbl(STAGE_LABEL[s.stage], "pill-" + STAGE_PILL[s.stage])),
      h("td", { class: "meta" }, s.depends_on.length ? s.depends_on.map((d, i) => [i ? ", " : "", link("#/spec/" + d, specLabel(d))]) : "—"),
      h("td", { class: "meta", text: s.wave || "—" }), h("td", { class: "meta", text: shortDate(s.updated) })))))) : emptyBox("No specs match."));
  return [pipeline, kindBar, table];
}

// Spec reader ----------------------------------------------------------------------------------------------

async function specView(id) {
  const data = await api("/api/spec/" + encodeURIComponent(id));
  const root = h("div");
  const draw = () => root.replaceChildren(...specParts(data, draw));
  draw();
  return root;
}

function specParts(data, redraw) {
  const spec = data.spec;
  const marks = data.requirements;
  const tabs = [["spec", "Spec", Object.keys(marks).length || (data.body.match(/\*\*R\d+\*\*/g) || []).length], ["effective", "Effective text", data.effective.length],
    ["history", "History", data.history.length], ["decisions", "Decisions", data.decisions.length]];
  const bar = tabBar(tabs, "Spec sections", redraw);
  const accepted = data.stage === "accepted";
  const head = [
    h("h1", { class: "page" }, spec.title, " ", span("num", "#" + specLabel(spec.id))),
    h("div", { class: "subline" }, lbl(spec.status === "superseded" ? "Superseded" : STAGE_LABEL[data.stage], "big solid pill-" + STAGE_PILL[data.stage]), lbl(spec.kind),
      span("meta", `${spec.path} · created ${spec.created}${accepted ? "" : ""}`)),
    h("section", { class: "stepper-box", "aria-label": "Lifecycle" }, h("ol", { class: "stepper" }, data.lifecycle.map((step) =>
      h("li", { class: step.done ? (step.name === "Restored" ? "done restored" : "done") : "todo" },
        h("div", { class: "rail" }, h("span", { class: "node" }), h("span", { class: "line" })), span("nm", step.name),
        span("meta", step.at ? shortDate(step.at) : "—"))))),
    bar,
  ];
  let body;
  if (view.tab === "spec") body = h("article", { class: "md" }, markdown(data.body, { marks }));
  else if (view.tab === "effective") body = effectiveTab(data);
  else if (view.tab === "history") body = historyTab(data);
  else body = decisionsTab(data);
  return [...head, h("div", { class: "layout" }, h("div", { class: "content" }, body), specSidebar(data))];
}

function effectiveTab(data) {
  if (!data.effective.length) return emptyBox("No effective text available.");
  return h("div", { class: "md" }, data.effective.map((part) => h("section", {},
    h("div", { class: "eff-head" }, lbl(part.relation || "self"), part.id !== undefined ? link("#/spec/" + part.id, "#" + specLabel(part.id)) : null, span("meta mono", part.path || "")),
    markdown(String(part.content || "").replace(/^---\n[\s\S]*?\n---\n?/, ""), {}))));
}

function historyTab(data) {
  const list = h("ol", { class: "hist" });
  for (const event of data.history) {
    list.append(h("li", {}, h("span", { class: "hd " + (event.action || "") }),
      h("div", { class: "body" }, h("span", {}, h("strong", { text: (event.action || "").replace(/^./, (c) => c.toUpperCase()) }), " ", span("what", event.detail || "")),
        event.user_decision ? span("note", "User decision: " + event.user_decision) : null, event.at ? span("meta", `${shortDate(event.at)} · ${event.at}`) : null)));
  }
  return list;
}

function decisionsTab(data) {
  if (!data.decisions.length) return emptyBox("No user decisions recorded for this spec.");
  return h("ol", { class: "hist" }, data.decisions.map((d) => h("li", {}, h("span", { class: "hd edit" }),
    h("div", { class: "body" }, h("span", {}, h("strong", { text: d.source }), " ", span("what", d.reason || "")), span("note", d.text), d.at ? when(d.at) : null))));
}

function specSidebar(data) {
  const links = data.links;
  const group = (title, items, empty) => h("div", { class: "side" }, h("h2", { text: title }),
    items.length ? items.map((s) => h("span", {}, link("#/spec/" + s.id, "#" + specLabel(s.id)), " ", span("meta", s.title),
      s.status === "superseded" ? [" ", lbl("superseded")] : null)) : span("meta", empty));
  const pr = data.pr;
  const impl = h("div", { class: "side" }, h("h2", { text: "Implementation" }),
    pr ? [h("span", {}, link("#/pull/" + encodeURIComponent(pr.feature), "Pull request #" + pr.spec_id), " ", lbl(pr.state === "merged" ? "merged" : "open", pr.state === "merged" ? "violet" : "")),
      span("meta", `${pr.review_rounds} review rounds · ${(pr.bugs && pr.bugs.total) || 0} bugs`)] : span("meta", "No implementation record yet"));
  return h("aside", { "aria-label": "Spec links" }, impl, group("Depends on", links.depends_on, "none"), group("Amends", links.amends, "none"),
    group("References", links.references, "none"), group("Amended by", links.amended_by, "none yet"),
    links.supersedes.length || links.superseded_by.length ? group("Supersession", [...links.supersedes, ...links.superseded_by], "none") : null);
}

// Activity -------------------------------------------------------------------------------------------------

async function activityView() {
  const data = await api("/api/activity");
  if (!data.events.length) return emptyBox("No activity yet.");
  const box = h("div", { class: "box" });
  for (const event of data.events) {
    const target = event.kind === "spec" ? "#/spec/" + Number(event.feature.slice(0, 4)) : "#/pull/" + encodeURIComponent(event.feature);
    box.append(h("div", { class: "row" }, h("span", { class: "ev-icon ev-" + event.kind, "aria-hidden": "true", text: EVENT_ICONS[event.kind] || "•" }),
      h("div", { class: "main" }, h("span", {}, link(target, event.feature, "title"), " ", span("meta", `${event.who} ${event.what}`)), event.note ? span("meta", event.note) : null),
      when(event.at)));
  }
  return box;
}

// Markdown (escape-by-construction: only DOM nodes and text) -----------------------------------------------

const INLINE = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)|(?<![\w/#.:-])#?(\d{4})(?![\w-])/g;

function inline(text, node) {
  let last = 0;
  INLINE.lastIndex = 0;
  for (let m = INLINE.exec(text); m; m = INLINE.exec(text)) {
    node.append(document.createTextNode(text.slice(last, m.index)));
    last = m.index + m[0].length;
    if (m[1] !== undefined) node.append(h("code", { text: m[1] }));
    else if (m[2] !== undefined) node.append(h("strong", { text: m[2] }));
    else if (m[3] !== undefined) {
      const url = m[4];
      if (/^#\//.test(url)) node.append(link(url, m[3]));
      else if (/^https?:\/\//i.test(url)) node.append(h("a", { href: url, text: m[3], rel: "noopener noreferrer", target: "_blank" }));
      else node.append(document.createTextNode(m[0]));
    } else if (specById(Number(m[5]))) node.append(link("#/spec/" + Number(m[5]), m[0]));
    else node.append(document.createTextNode(m[0]));
  }
  node.append(document.createTextNode(text.slice(last)));
  return node;
}

function markdown(text, options) {
  const marks = (options && options.marks) || {};
  const out = document.createDocumentFragment();
  const lines = String(text || "").replace(/\r/g, "").split("\n");
  let i = 0;
  const isBlockStart = (line) => /^(#{1,6}\s|```|>\s?|\s*([-*]|\d+\.)\s|\s*\|.*\||---+\s*$)/.test(line);
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const fence = /^```(.*)$/.exec(line);
    if (fence) {
      const code = [];
      for (i++; i < lines.length && !/^```/.test(lines[i]); i++) code.push(lines[i]);
      i++;
      out.append(h("pre", {}, h("code", { text: code.join("\n") })));
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) { out.append(inline(heading[2], h("h" + heading[1].length))); i++; continue; }
    if (/^---+\s*$/.test(line)) { out.append(h("hr")); i++; continue; }
    if (/^>\s?/.test(line)) {
      const quote = [];
      for (; i < lines.length && /^>\s?/.test(lines[i]); i++) quote.push(lines[i].replace(/^>\s?/, ""));
      out.append(h("blockquote", {}, markdown(quote.join("\n"), options)));
      continue;
    }
    if (/^\s*\|.*\|/.test(line) && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1] || "")) {
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const header = cells(line);
      const body = [];
      for (i += 2; i < lines.length && /^\s*\|/.test(lines[i]); i++) body.push(cells(lines[i]));
      out.append(h("div", { class: "tablebox" }, h("table", {}, h("thead", {}, h("tr", {}, header.map((c) => inline(c, h("th"))))),
        h("tbody", {}, body.map((r) => h("tr", {}, r.map((c) => inline(c, h("td", { style: "white-space:normal" })))))))));
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s/.test(line)) {
      const items = [];
      for (; i < lines.length; i++) {
        const m = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(lines[i]);
        if (m) items.push({ indent: m[1].length, ordered: /\d/.test(m[2]), text: m[3] });
        else if (items.length && lines[i].trim() && /^\s+\S/.test(lines[i]) && !isBlockStart(lines[i])) items[items.length - 1].text += " " + lines[i].trim();
        else break;
      }
      out.append(buildList(items, marks));
      continue;
    }
    const para = [];
    for (; i < lines.length && lines[i].trim() && (!isBlockStart(lines[i]) || !para.length); i++) para.push(lines[i].trim());
    out.append(inline(para.join(" "), h("p")));
  }
  return out;
}

function buildList(items, marks) {
  const root = h(items[0].ordered ? "ol" : "ul");
  const stack = [{ indent: items[0].indent, list: root, last: null }];
  for (const item of items) {
    let top = stack[stack.length - 1];
    if (item.indent > top.indent && top.last) {
      const nested = h(item.ordered ? "ol" : "ul");
      top.last.append(nested);
      stack.push({ indent: item.indent, list: nested, last: null });
    } else {
      while (stack.length > 1 && item.indent < top.indent) { stack.pop(); top = stack[stack.length - 1]; }
    }
    top = stack[stack.length - 1];
    const li = inline(item.text, h("li"));
    const requirement = /^\*\*(R\d+)\*\*/.exec(item.text);
    const mark = requirement && marks[requirement[1]];
    if (mark) {
      li.append(h("span", { class: "chips" }, lbl(mark.implemented ? "implemented" : "not implemented", mark.implemented ? "good" : ""),
        lbl(mark.tested ? "tested" : "not tested", mark.tested ? "good" : ""), mark.amends ? lbl("amends " + mark.amends, "violet") : null));
    }
    top.list.append(li);
    top.last = li;
  }
  return root;
}

// Live updates ---------------------------------------------------------------------------------------------

function connect() {
  const source = new EventSource("/api/events");
  let timer = null;
  source.addEventListener("hello", () => { view.live = true; renderLive(); });
  source.addEventListener("change", () => {
    clearTimeout(timer);
    timer = setTimeout(render, 250);
  });
  source.onerror = () => { view.live = false; renderLive(); };
  source.onopen = () => { view.live = true; renderLive(); };
}

window.addEventListener("hashchange", () => { view.tab = ""; render(); });
render();
connect();
