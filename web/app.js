/* mcp-news dashboard.
 *
 * Hash router, fetch client, direct DOM rendering. No framework, no build.
 * Kept small enough that any contributor can read all of it in one sitting.
 */

const api = async (path, params) => {
  const url = new URL(path, location.origin);
  Object.entries(params || {}).forEach(([k, v]) => v != null && url.searchParams.set(k, v));
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v != null) n.setAttribute(k, v);
  }
  kids.flat().forEach(c => n.append(c?.nodeType ? c : document.createTextNode(c ?? "")));
  return n;
};

const view = () => document.getElementById("view");

/* ---- Today: a finite, ranked, explained list --------------------------- */
async function renderToday() {
  view().replaceChildren(el("p", { class: "meta" }, "Loading…"));
  let data;
  try {
    data = await api("/api/foryou", { hours: 72, limit: 30 });
  } catch (e) {
    view().replaceChildren(el("p", { class: "meta" }, `Could not load: ${e.message}`));
    return;
  }

  const frag = document.createDocumentFragment();
  if (!data.items.length) {
    frag.append(el("p", { class: "meta" },
      "Nothing above your relevance threshold in this window. Widen the hours, " +
      "or lower min_score in profile.yaml."));
  }

  for (const it of data.items) {
    const chips = (it.matched_rules || []).map(r =>
      el("button", {
        class: "chip",
        title: `${r.section} · weight ${r.weight}${r.in_title ? " · matched in headline" : ""}`,
        onclick: () => location.hash = `#/profile?rule=${encodeURIComponent(r.name)}`
      }, `${r.name} +${r.weight}`));

    frag.append(el("article", { class: "item" },
      el("h2", {}, el("a", { href: it.url, rel: "noopener noreferrer", target: "_blank" },
        it.title_translated || it.title)),
      el("p", { class: "meta" },
        `${it.domain} · ${(it.published_at || "").slice(0, 16).replace("T", " ")} · score ${it.interest_score}`),
      it.summary ? el("p", {}, it.summary) : "",
      el("div", { class: "chips" }, chips)
    ));
  }

  /* An ending, on purpose. */
  frag.append(el("p", { class: "end-of-feed" },
    `That's all ${data.items.length} items above your threshold. Nothing more is being withheld.`));

  view().replaceChildren(frag);
}

const routes = {
  "/today": renderToday,
  "/search": async () => view().replaceChildren(el("p", { class: "meta" }, "Search — phase 3.")),
  "/sources": async () => view().replaceChildren(el("p", { class: "meta" }, "Sources — phase 3.")),
  "/profile": async () => view().replaceChildren(el("p", { class: "meta" }, "Profile editor — phase 3.")),
};

async function route() {
  const path = (location.hash.slice(1).split("?")[0]) || "/today";
  document.querySelectorAll(".tabs a").forEach(a =>
    a.toggleAttribute("aria-current", a.getAttribute("href") === `#${path}`));
  await (routes[path] || routes["/today"])();
}

/* Tier and provider health, so degraded operation is visible rather than
   silently worse. */
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const names = { 0: "collect", 1: "index", 2: "understand" };
    document.getElementById("tier").textContent = `tier ${s.tier} · ${names[s.tier] ?? ""}`;
    document.getElementById("status-line").textContent =
      `${s.articles.toLocaleString()} articles · ${s.queued.toLocaleString()} pending · ` +
      `${s.sources_active} sources active`;
  } catch {
    document.getElementById("status-line").textContent = "API unreachable";
  }
}

addEventListener("hashchange", route);
addEventListener("DOMContentLoaded", () => { route(); refreshStatus(); });
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
