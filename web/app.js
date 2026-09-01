/* mcp-news dashboard.
 *
 * Hash router, fetch client, direct DOM rendering. No framework, no build step,
 * no bundler, no CDN, no remote font, no analytics.
 *
 * Every user-visible string comes from the catalogue in /i18n/<lang>.json.
 * There is no English literal anywhere below this comment that a reader can see;
 * if you add one, you have broken the thing this file is most careful about.
 */

/* ======================= internationalisation ========================= */
const FALLBACK_LANG = "en";
let LANG = FALLBACK_LANG;
let STRINGS = {};
let LOCALES = [{ code: "en", name: "English", endonym: "English", dir: "ltr" }];

const interpolate = (template, params) =>
  params ? template.replace(/\{(\w+)\}/g, (m, k) => (k in params ? String(params[k]) : m))
         : template;

/** Translate. An unknown key renders as the key itself, which is obvious on
 *  screen and tells whoever must fix it exactly what to add. */
const t = (key, params) => interpolate(STRINGS[key] ?? key, params);

/** Some counts read better with a dedicated singular. The catalogue supplies
 *  a `.one` key when it matters; this picks it without any plural machinery. */
const tn = (key, count, params) =>
  (count === 1 && (key + ".one") in STRINGS)
    ? t(key + ".one", { ...params, count })
    : t(key, { ...params, count });

async function loadCatalogue(lang) {
  const fetchOne = async (code) => {
    try {
      const r = await fetch(`/i18n/${encodeURIComponent(code)}.json`, { cache: "no-cache" });
      return r.ok ? await r.json() : {};
    } catch { return {}; }
  };
  const base = await fetchOne(FALLBACK_LANG);
  const chosen = lang && lang !== FALLBACK_LANG ? await fetchOne(lang) : {};
  /* English underneath, the locale on top: a partial translation degrades
     rather than showing raw dot-paths. */
  STRINGS = { ...base, ...chosen };
  LANG = lang || FALLBACK_LANG;
  const meta = LOCALES.find((l) => l.code === LANG);
  document.documentElement.lang = LANG;
  document.documentElement.dir = (meta && meta.dir) || "ltr";
  applyStatic();
}

function applyStatic() {
  document.querySelectorAll("[data-i18n]").forEach((n) => {
    n.textContent = t(n.getAttribute("data-i18n"));
  });
  document.title = t("app.name");
}

/* ============================ dom helpers ============================= */
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v === true) n.setAttribute(k, "");
    else n.setAttribute(k, v);
  }
  /* Deep flatten: a render function that returns a list of rows is a normal
     thing to nest inside another list, and a stray array reaching replaceChildren
     stringifies to "[object HTMLElement]" on screen. */
  kids.flat(Infinity).forEach((c) => {
    if (c == null || c === false) return;
    n.append(c?.nodeType ? c : document.createTextNode(String(c)));
  });
  return n;
};
const view = () => document.getElementById("view");
const clear = (...nodes) =>
  view().replaceChildren(...nodes.flat(Infinity).filter((n) => n != null && n !== false));

let toastTimer = null;
function toast(message) {
  const box = document.getElementById("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 4000);
}

/** A labelled control with its own plain-language explanation, collapsed by
 *  default so the screen stays calm and expandable by anyone who needs it. */
function withHelp(control, helpKey) {
  if (!helpKey) return control;
  const body = el("p", { class: "help-body", hidden: true }, t(helpKey));
  const toggle = el("button", {
    type: "button", class: "help-toggle", "aria-expanded": "false",
    onclick: (e) => {
      const open = body.hidden;
      body.hidden = !open;
      e.target.textContent = open ? t("common.help_hide") : t("common.help_show");
      e.target.setAttribute("aria-expanded", String(open));
    },
  }, t("common.help_show"));
  return el("div", {}, control, toggle, body);
}

function field(labelKey, control, helpKey) {
  const id = control.id || `f${Math.random().toString(36).slice(2, 9)}`;
  control.id = id;
  return el("div", { class: "field" },
    withHelp(el("div", {}, el("label", { for: id }, t(labelKey)), control), helpKey));
}

const input = (attrs = {}) => el("input", { type: "text", ...attrs });
const csv = (list) => (list || []).join(", ");
const uncsv = (value) => (value || "").split(",").map((s) => s.trim()).filter(Boolean);

function when(iso) {
  if (!iso) return t("common.never");
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16).replace("T", " ");
  return d.toLocaleString(LANG, { dateStyle: "medium", timeStyle: "short" });
}
function bytes(n) {
  if (n == null) return t("common.unknown");
  const units = ["B", "kB", "MB", "GB", "TB"];
  let i = 0, v = Number(n);
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

/* ============================= api client ============================= */
async function api(path, { params, method = "GET", body } = {}) {
  const url = new URL(path, location.origin);
  Object.entries(params || {}).forEach(([k, v]) => v != null && url.searchParams.set(k, v));
  let r;
  try {
    r = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw { key: "err.unreachable", params: {} };
  }
  let data = null;
  try { data = await r.json(); } catch { data = null; }
  if (!r.ok) {
    const err = data && data.error ? data.error : { key: "err.generic", params: {} };
    err.status = r.status;
    throw err;
  }
  return data;
}

const say = (err) => toast(t(err?.key || "err.generic", err?.params));

/* ============================ setup wizard ============================ */
const setupState = {
  step: 0, language: FALLBACK_LANG, data_dir: "", archive_dir: "",
  bundles: [], starter: "tech", interests: [],
};
const STARTER_TERMS = {
  tech: [
    ["Artificial intelligence", "artificial intelligence, machine learning, large language model"],
    ["AI governance", "AI Act, AI regulation, algorithmic accountability"],
    ["Semiconductor policy", "export control, lithography, ASML, TSMC"],
  ],
  world: [
    ["Elections and democracy", "general election, referendum, electoral commission"],
    ["Climate and energy", "emissions, renewable energy, grid capacity, climate policy"],
    ["Trade and sanctions", "tariff, sanctions, trade agreement, export ban"],
  ],
  security: [
    ["Actively exploited vulnerabilities", "actively exploited, zero-day, known exploited"],
    ["Ransomware and intrusion", "ransomware, data breach, supply chain attack"],
    ["Critical infrastructure", "power grid, water utility, industrial control system"],
  ],
  blank: [],
};
const SETUP_STEPS = 5;

async function renderSetup() {
  document.getElementById("topbar").hidden = true;
  document.getElementById("foot").hidden = true;
  const state = await api("/api/setup/state");
  const options = await api("/api/setup/options");
  LOCALES = options.locales;
  if (!setupState.data_dir) setupState.data_dir = state.defaults.data_dir;
  if (!setupState.archive_dir) setupState.archive_dir = state.defaults.archive_dir;
  if (!setupState.interests.length) applyStarter(setupState.starter);
  drawSetup(state, options);
}

function applyStarter(key) {
  setupState.starter = key;
  setupState.interests = (STARTER_TERMS[key] || []).map(([name, match]) => ({ name, match }));
  if (!setupState.interests.length) setupState.interests = [{ name: "", match: "" }];
}

function progress(step) {
  return el("div", { class: "steps" },
    Array.from({ length: SETUP_STEPS }, (_, i) =>
      el("span", { class: i <= step ? "done" : "" })));
}

function drawSetup(state, options) {
  const s = setupState;
  const nav = (backFn, nextFn, nextKey, nextDisabled) => el("div", { class: "actions" },
    backFn && el("button", { type: "button", onclick: backFn }, t("common.back")),
    el("button", {
      type: "button", class: "primary", disabled: nextDisabled === true,
      onclick: nextFn,
    }, t(nextKey || "common.next")));

  const go = (n) => { s.step = n; drawSetup(state, options); };
  const head = (titleKey, bodyKey) => [
    progress(s.step),
    el("p", { class: "stepno" }, t("setup.step_of", { current: s.step + 1, total: SETUP_STEPS })),
    el("h1", {}, t(titleKey)),
    bodyKey ? el("p", { class: "lede" }, t(bodyKey)) : null,
  ];

  let body;
  if (s.step === 0) {
    body = el("div", { class: "wizard" },
      progress(0),
      el("h1", {}, t("setup.welcome.title")),
      el("p", { class: "lede" }, t("setup.welcome.body")),
      el("p", { class: "notice ok" }, t("setup.welcome.privacy")),
      el("div", { class: "actions" },
        el("button", { class: "primary", type: "button", onclick: () => go(1) },
          t("setup.welcome.start"))));
  } else if (s.step === 1) {
    const choices = el("div", { class: "choices" },
      LOCALES.map((loc) => el("label", { class: "choice" },
        el("input", {
          type: "radio", name: "lang", value: loc.code, checked: s.language === loc.code,
          onchange: async () => {
            s.language = loc.code;
            await loadCatalogue(loc.code);
            drawSetup(state, options);
          },
        }),
        el("span", {}, el("strong", {}, loc.endonym),
          el("span", { class: "meta" }, loc.name)))));
    body = el("div", { class: "wizard" },
      head("setup.language.title", "setup.language.body"),
      withHelp(choices, "setup.language.help"),
      nav(() => go(0), () => go(2)));
  } else if (s.step === 2) {
    const dataIn = input({ value: s.data_dir, oninput: (e) => { s.data_dir = e.target.value; } });
    const archIn = input({
      value: s.archive_dir, oninput: (e) => { s.archive_dir = e.target.value; },
    });
    const result = el("p", { class: "meta" });
    const check = async () => {
      result.textContent = t("common.testing");
      try {
        const a = await api("/api/setup/check-path", { method: "POST", body: { path: s.data_dir } });
        const b = await api("/api/setup/check-path",
          { method: "POST", body: { path: s.archive_dir } });
        result.className = a.ok && b.ok ? "notice ok" : "notice bad";
        result.textContent = a.ok && b.ok
          ? t("setup.storage.ok", { free: bytes(b.free_bytes ?? a.free_bytes) })
          : t((a.ok ? b : a).message_key || "err.generic");
      } catch (e) { result.className = "notice bad"; result.textContent = t(e.key, e.params); }
    };
    body = el("div", { class: "wizard" },
      head("setup.storage.title", "setup.storage.body"),
      state.in_container ? el("p", { class: "notice" }, t("setup.storage.docker_note")) : null,
      withHelp(el("div", {},
        field("setup.storage.data_label", dataIn),
        field("setup.storage.archive_label", archIn)), "setup.storage.help"),
      el("div", { class: "actions" },
        el("button", { type: "button", onclick: check }, t("setup.storage.test"))),
      result,
      nav(() => go(1), () => go(3)));
  } else if (s.step === 3) {
    const list = el("div", { class: "choices" },
      options.bundles.filter((b) => b.name !== "local").map((b) => el("label", { class: "choice" },
        el("input", {
          type: "checkbox", checked: s.bundles.includes(b.name),
          onchange: (e) => {
            s.bundles = e.target.checked
              ? [...s.bundles, b.name] : s.bundles.filter((x) => x !== b.name);
            document.getElementById("bundle-next").disabled = s.bundles.length === 0;
          },
        }),
        el("span", {},
          el("strong", {}, b.name),
          el("span", { class: "meta" }, b.description),
          el("span", { class: "meta" },
            t("setup.bundles.source_count", { count: b.source_count }))))));
    body = el("div", { class: "wizard" },
      head("setup.bundles.title", "setup.bundles.body"),
      withHelp(list, "setup.bundles.help"),
      s.bundles.length ? null : el("p", { class: "meta" }, t("setup.bundles.none_selected")),
      el("div", { class: "actions" },
        el("button", { type: "button", onclick: () => go(2) }, t("common.back")),
        el("button", {
          id: "bundle-next", class: "primary", type: "button",
          disabled: s.bundles.length === 0, onclick: () => go(4),
        }, t("common.next"))));
  } else {
    const rows = el("div", {});
    const draw = () => {
      rows.replaceChildren(...s.interests.map((rule, i) => el("div", { class: "rule-editor" },
        el("div", { class: "field" },
          input({
            value: rule.name, placeholder: t("setup.profile.name_placeholder"),
            oninput: (e) => { rule.name = e.target.value; },
          })),
        el("div", { class: "field" },
          input({
            value: rule.match, placeholder: t("setup.profile.match_placeholder"),
            oninput: (e) => { rule.match = e.target.value; },
          })),
        el("button", {
          type: "button", class: "quiet danger",
          onclick: () => { s.interests.splice(i, 1); draw(); },
        }, t("common.remove")))));
    };
    draw();
    const starters = el("div", { class: "row" },
      ["tech", "world", "security", "blank"].map((key) => el("button", {
        type: "button", class: s.starter === key ? "primary" : "",
        onclick: () => { applyStarter(key); draw(); drawSetup(state, options); },
      }, t(`setup.profile.starter.${key}`))));

    const finish = async () => {
      const interests = s.interests
        .filter((r) => r.name.trim())
        .map((r) => ({ name: r.name.trim(), match: uncsv(r.match), weight: 4 }));
      if (!interests.length) { toast(t("setup.profile.need_one")); return; }
      clear(el("div", { class: "wizard" },
        el("p", { class: "lede" }, el("span", { class: "spinner" }), " ", t("setup.working"))));
      try {
        await api("/api/setup/complete", {
          method: "POST",
          body: {
            language: s.language, data_dir: s.data_dir, archive_dir: s.archive_dir,
            bundles: s.bundles, interests,
          },
        });
      } catch (e) { say(e); drawSetup(state, options); return; }
      clear(el("div", { class: "wizard" },
        el("h1", {}, t("setup.done.title")),
        el("p", { class: "lede" }, t("setup.done.body")),
        el("div", { class: "actions" },
          el("button", {
            class: "primary", type: "button",
            onclick: () => { location.hash = "#/today"; location.reload(); },
          }, t("setup.done.open")))));
    };

    body = el("div", { class: "wizard" },
      head("setup.profile.title", "setup.profile.body"),
      el("p", { class: "meta" }, t("setup.profile.starter")),
      starters,
      withHelp(rows, "setup.profile.help"),
      el("button", {
        type: "button", class: "quiet",
        onclick: () => { s.interests.push({ name: "", match: "" }); draw(); },
      }, t("setup.profile.add_interest")),
      el("div", { class: "actions" },
        el("button", { type: "button", onclick: () => go(3) }, t("common.back")),
        el("button", { class: "primary", type: "button", onclick: finish },
          t("common.finish"))));
  }
  clear(body);
}

/* ============================== today ================================= */
const WINDOWS = [24, 72, 168, 720];
let todayHours = 72;

async function renderToday() {
  clear(el("p", { class: "meta" }, t("common.loading")));
  let data;
  try { data = await api("/api/foryou", { params: { hours: todayHours, limit: 40 } }); }
  catch (e) { return renderError(e); }

  const picker = el("div", { class: "row spread" },
    el("div", { class: "row" },
      el("label", { for: "win" }, t("today.window")),
      el("select", {
        id: "win", style: "width:auto",
        onchange: (e) => { todayHours = Number(e.target.value); renderToday(); },
      }, WINDOWS.map((h) => el("option", {
        value: h, selected: h === todayHours,
      }, t(`today.window.${h}`))))),
    el("button", {
      type: "button",
      onclick: async (e) => {
        e.target.disabled = true;
        e.target.textContent = t("today.collecting_now");
        try { await api("/api/collect", { method: "POST" }); toast(t("today.collecting_now")); }
        catch (err) { say(err); }
        setTimeout(renderToday, 6000);
      },
    }, t("today.collect_now")));

  const frag = [el("h1", {}, t("today.title")), picker];
  if (!data.items.length) {
    frag.push(el("p", { class: "notice" },
      data.collecting || data.total_articles === 0 ? t("today.collecting") : t("today.empty")));
  }
  for (const item of data.items) frag.push(articleCard(item));
  if (data.items.length) {
    frag.push(el("p", { class: "end-of-feed" }, tn("today.end", data.items.length)));
  }
  clear(frag);
}

function articleCard(item) {
  const chips = (item.matched_rules || []).filter((r) => r.section !== "source").map((r) =>
    el("button", {
      class: `chip${r.in_title ? " title-hit" : ""}`,
      title: `${t(`today.section.${r.section}`)} · ${t("common.weight")} ${r.weight}` +
             (r.in_title ? ` · ${t("today.matched_in_title")}` : ""),
      onclick: () => { location.hash = `#/profile`; },
    }, `${r.name} +${Number(r.points).toFixed(1)}`));

  return el("article", { class: "item" },
    el("h2", {}, el("a", { href: `#/article/${item.article_id}` },
      item.title_translated || item.title)),
    el("p", { class: "meta" },
      `${item.domain} · ${when(item.published_at)} · ` +
      t("today.score", { score: Number(item.display_score ?? item.interest_score).toFixed(1) })),
    item.summary ? el("p", {}, item.summary) : null,
    chips.length ? el("div", { class: "chips" }, chips) : null);
}

/* ============================== search ================================ */
let searchState = { q: "", days: 90 };

async function renderSearch() {
  const box = el("input", {
    type: "search", value: searchState.q, placeholder: t("search.placeholder"),
    onkeydown: (e) => { if (e.key === "Enter") run(); },
  });
  const days = el("select", { style: "width:auto" },
    [30, 90, 365, 0].map((d) => el("option", {
      value: d, selected: d === searchState.days,
    }, t(`search.days.${d || "all"}`))));
  const results = el("div", {});

  const run = async () => {
    searchState = { q: box.value.trim(), days: Number(days.value) };
    if (!searchState.q) { results.replaceChildren(); return; }
    results.replaceChildren(el("p", { class: "meta" }, t("common.loading")));
    let data;
    try {
      data = await api("/api/search", {
        params: { q: searchState.q, days: searchState.days || 0, limit: 40 },
      });
    } catch (e) { results.replaceChildren(el("p", { class: "notice bad" }, t(e.key, e.params))); return; }

    const nodes = [
      el("p", { class: "meta" },
        `${tn("search.results", data.count)} · ${t(`search.mode.${data.mode}`)}`),
      data.note_key ? el("p", { class: "notice" }, t(data.note_key)) : null,
    ];
    if (!data.count) nodes.push(el("p", { class: "notice" }, t("search.empty")));
    for (const hit of data.results) {
      nodes.push(el("article", { class: "item" },
        el("h2", {}, el("a", { href: `#/article/${hit.article_id}` },
          hit.title_translated || hit.title)),
        el("p", { class: "meta" }, `${hit.domain} · ${when(hit.published_at)}`),
        hit.snippet ? el("p", {}, hit.snippet) : null));
    }
    results.replaceChildren(...nodes.filter(Boolean));
  };

  clear([
    el("h1", {}, t("search.title")),
    el("div", { class: "inline" },
      el("div", { class: "field grow" }, box),
      el("div", { class: "field" }, el("label", {}, t("search.days")), days),
      el("button", { class: "primary", type: "button", onclick: run }, t("search.submit"))),
    results,
  ]);
  if (searchState.q) run();
}

/* ============================== article =============================== */
async function renderArticle(id) {
  clear(el("p", { class: "meta" }, t("common.loading")));
  let a, why;
  try {
    a = await api(`/api/article/${id}`);
    why = await api(`/api/explain/${id}`);
  } catch (e) { return renderError(e); }

  const rules = (why.rules || []).map((r) => el("li", {},
    t("article.rule_line", {
      name: r.name, points: Number(r.points).toFixed(1), hits: r.hits,
    })));

  clear([
    el("button", { class: "quiet", type: "button", onclick: () => history.back() },
      t("article.back")),
    el("h1", {}, a.title_translated || a.title),
    el("p", { class: "meta" },
      `${a.domain} · ${t("article.published", { when: when(a.published_at) })} · ` +
      t("article.collected", { when: when(a.fetched_at) })),
    el("p", {}, el("a", { href: a.url, target: "_blank", rel: "noopener noreferrer" },
      t("article.open_original"))),
    a.body
      ? el("div", { class: "article-body" },
          a.body.split("\n").filter((p) => p.trim()).map((p) => el("p", {}, p)))
      : el("p", { class: "notice" }, t("article.no_body")),
    el("h2", {}, t("article.why", { score: Number(why.total).toFixed(1) })),
    rules.length ? el("ul", {}, rules) : el("p", { class: "meta" }, t("common.none")),
  ]);
}

/* ============================== sources =============================== */
async function renderSources() {
  clear(el("p", { class: "meta" }, t("common.loading")));
  let data;
  try { data = await api("/api/sources"); } catch (e) { return renderError(e); }

  const rows = data.sources.map((s) => {
    const badges = [el("span", { class: "badge" }, t(`sources.status.${s.status}`))];
    if (s.failing) badges.push(el("span", { class: "badge bad" },
      t("sources.failures", { count: s.consecutive_failures })));
    if (s.expired) badges.push(el("span", { class: "badge warn" },
      t("sources.expired", { date: s.expires })));
    if (s.replaced_by) badges.push(el("span", { class: "badge warn" },
      t("sources.replaced_by", { id: s.replaced_by })));

    const on = s.status === "active" || s.status === "deprecated";
    return el("article", { class: "item" },
      el("div", { class: "row spread" },
        el("div", { class: "grow" },
          el("strong", {}, s.name),
          el("p", { class: "meta" },
            `${s.bundle} · ${s.kind} · ${s.lang} · ` +
            t("sources.interval_minutes", { minutes: s.interval_min })),
          el("p", { class: "meta" }, s.last_ok_at
            ? t("sources.last_ok", { when: when(s.last_ok_at) })
            : t("sources.never_succeeded")),
          el("div", { class: "chips" }, badges)),
        el("div", { class: "row" },
          el("button", {
            type: "button",
            onclick: async (e) => {
              e.target.disabled = true;
              try {
                await api(`/api/sources/${encodeURIComponent(s.id)}`, {
                  method: "PATCH", body: { status: on ? "paused" : "active" },
                });
                renderSources();
              } catch (err) { say(err); e.target.disabled = false; }
            },
          }, on ? t("common.disable") : t("common.enable")),
          s.bundle === "local" ? el("button", {
            type: "button", class: "quiet danger",
            onclick: async () => {
              if (!confirm(t("sources.delete_confirm", { name: s.name }))) return;
              try {
                await api(`/api/sources/${encodeURIComponent(s.id)}`, { method: "DELETE" });
                renderSources();
              } catch (err) { say(err); }
            },
          }, t("common.delete")) : null)));
  });

  clear([
    el("h1", {}, t("sources.title")),
    el("p", { class: "lede" }, t("sources.check.ok", {
      ok: data.ok, failing: data.failing, expired: data.expired,
    })),
    ...(data.bundle_errors || []).map((e) => el("p", { class: "notice bad" }, e)),
    addSourceForm(data.kinds),
    rows.length ? rows : el("p", { class: "notice" }, t("sources.empty")),
  ]);
}

function addSourceForm(kinds) {
  const url = input({ type: "url", placeholder: t("sources.url_placeholder") });
  const name = input({});
  const kind = el("select", {},
    [el("option", { value: "auto" }, t("sources.kind.auto")),
      ...kinds.map((k) => el("option", { value: k }, k))]);
  const lang = input({ value: "en" });
  const region = input({ value: "global" });
  const interval = el("input", { type: "number", value: 60, min: 1 });
  const result = el("p", { class: "meta" });

  const test = async () => {
    result.className = "meta";
    result.textContent = t("common.testing");
    try {
      const r = await api("/api/sources/test", {
        method: "POST", body: { url: url.value, kind: kind.value, name: name.value },
      });
      result.className = "notice ok";
      result.textContent = t("sources.test.ok", { count: r.count, title: r.items[0]?.title || "" });
      if (!name.value) name.value = r.name;
    } catch (e) { result.className = "notice bad"; result.textContent = t(e.key, e.params); }
  };
  const add = async () => {
    try {
      await api("/api/sources", {
        method: "POST",
        body: {
          url: url.value, name: name.value, kind: kind.value, lang: lang.value,
          region: region.value, interval_min: Number(interval.value) || 60,
        },
      });
      toast(t("common.saved"));
      renderSources();
    } catch (e) { say(e); }
  };

  return el("details", { class: "card" },
    el("summary", {}, t("sources.add")),
    el("div", { style: "margin-top:14px" },
      withHelp(el("div", {},
        field("sources.url_label", url),
        field("sources.name_label", name),
        field("sources.kind_label", kind),
        field("sources.lang_label", lang),
        field("sources.region_label", region),
        field("sources.interval_label", interval, "sources.help.interval")), "sources.help"),
      el("div", { class: "actions" },
        el("button", { type: "button", onclick: test }, t("sources.test")),
        el("button", { type: "button", class: "primary", onclick: add }, t("common.add"))),
      result));
}

/* ============================== profile =============================== */
const SECTIONS = ["identity", "interests", "places", "organisations"];

async function renderProfile() {
  clear(el("p", { class: "meta" }, t("common.loading")));
  let p;
  try { p = await api("/api/profile"); } catch (e) { return renderError(e); }

  const model = {
    identity: p.identity, interests: p.interests, places: p.places,
    organisations: p.organisations,
    mute_domains: p.mute_domains, mute_keywords: p.mute_keywords,
    source_boost: p.source_boost, source_penalty: p.source_penalty,
    min_score: p.min_score, cap_per_rule: p.cap_per_rule,
    default_half_life_h: p.default_half_life_h,
  };

  const container = el("div", {});
  const draw = () => {
    const nodes = [];
    for (const section of SECTIONS) {
      nodes.push(el("h2", {}, t(`profile.section.${section}`)));
      model[section].forEach((rule, i) => nodes.push(ruleEditor(section, rule, () => {
        model[section].splice(i, 1); draw();
      })));
      nodes.push(el("button", {
        type: "button", class: "quiet",
        onclick: () => {
          model[section].push({ name: "", match: [], must_include: [], exclude: [],
            weight: 3, in_title_multiplier: 2 });
          draw();
        },
      }, t("profile.add_rule")));
    }

    nodes.push(el("h2", {}, t("profile.section.mute")));
    nodes.push(withHelp(el("div", {},
      field("profile.mute.domains", input({
        value: csv(model.mute_domains),
        oninput: (e) => { model.mute_domains = uncsv(e.target.value); },
      })),
      field("profile.mute.keywords", input({
        value: csv(model.mute_keywords),
        oninput: (e) => { model.mute_keywords = uncsv(e.target.value); },
      }))), "profile.help.mute"));

    nodes.push(el("h2", {}, t("profile.section.sources")));
    nodes.push(withHelp(el("div", {},
      field("profile.sources.boost", input({
        value: Object.entries(model.source_boost).map(([d, v]) => `${d}=${v}`).join(", "),
        oninput: (e) => { model.source_boost = parseWeighted(e.target.value); },
      })),
      field("profile.sources.penalty", input({
        value: Object.entries(model.source_penalty).map(([d, v]) => `${d}=${v}`).join(", "),
        oninput: (e) => { model.source_penalty = parseWeighted(e.target.value); },
      }))), "profile.help.sources"));

    nodes.push(el("h2", {}, t("settings.section.collection")));
    nodes.push(field("profile.threshold", numberInput(model, "min_score", 0, 100, 0.5),
      "profile.help.threshold"));
    nodes.push(field("profile.cap", numberInput(model, "cap_per_rule", 1, 1000, 1),
      "profile.help.cap"));
    nodes.push(field("profile.half_life", numberInput(model, "default_half_life_h", 0, 8760, 1),
      "profile.help.half_life"));

    const preview = el("div", {});
    nodes.push(el("div", { class: "actions" },
      el("button", {
        class: "primary", type: "button",
        onclick: async (e) => {
          e.target.disabled = true;
          try {
            const r = await api("/api/profile", { method: "PUT", body: model });
            toast(`${t("common.saved")} · ${tn("common.count_articles", r.rescored)}`);
          } catch (err) { say(err); }
          e.target.disabled = false;
        },
      }, t("common.save")),
      el("button", {
        type: "button",
        onclick: async () => {
          preview.replaceChildren(el("p", { class: "meta" }, t("common.loading")));
          try {
            const r = await api("/api/profile/preview", { method: "POST", body: model,
              params: { hours: 168, limit: 15 } });
            preview.replaceChildren(
              el("p", { class: "notice" }, t("profile.preview.note")),
              ...r.items.map(articleCard));
          } catch (err) { preview.replaceChildren(); say(err); }
        },
      }, t("profile.preview"))));
    nodes.push(preview);
    nodes.push(el("p", { class: "meta" }, t("settings.about.config_location", { path: p.path })));
    container.replaceChildren(...nodes);
  };
  draw();

  clear([el("h1", {}, t("profile.title")), el("p", { class: "lede" }, t("profile.body")),
    container]);
}

function numberInput(model, key, min, max, step) {
  return el("input", {
    type: "number", value: model[key], min, max, step,
    oninput: (e) => { model[key] = Number(e.target.value); },
  });
}

function parseWeighted(value) {
  const out = {};
  uncsv(value).forEach((pair) => {
    const [domain, weight] = pair.split("=").map((x) => (x || "").trim());
    if (domain && weight && !Number.isNaN(Number(weight))) out[domain] = Number(weight);
  });
  return out;
}

function ruleEditor(section, rule, remove) {
  return el("div", { class: "rule-editor" },
    field("profile.rule.name", input({
      value: rule.name, oninput: (e) => { rule.name = e.target.value; },
    })),
    field("profile.rule.match", input({
      value: csv(rule.match), oninput: (e) => { rule.match = uncsv(e.target.value); },
    }), "profile.help.match"),
    field("profile.rule.must_include", input({
      value: csv(rule.must_include),
      oninput: (e) => { rule.must_include = uncsv(e.target.value); },
    }), "profile.help.must_include"),
    field("profile.rule.exclude", input({
      value: csv(rule.exclude), oninput: (e) => { rule.exclude = uncsv(e.target.value); },
    }), "profile.help.exclude"),
    el("div", { class: "inline" },
      field("profile.rule.weight", el("input", {
        type: "number", min: 1, max: 5, step: 0.5, value: rule.weight,
        oninput: (e) => { rule.weight = Number(e.target.value); },
      }), "profile.help.weight"),
      field("profile.rule.in_title_multiplier", el("input", {
        type: "number", min: 0, max: 10, step: 0.5, value: rule.in_title_multiplier ?? 2,
        oninput: (e) => { rule.in_title_multiplier = Number(e.target.value); },
      }), "profile.help.in_title_multiplier")),
    el("button", { type: "button", class: "quiet danger", onclick: remove },
      t("common.remove")));
}

/* ============================== settings ============================== */
async function renderSettings() {
  clear(el("p", { class: "meta" }, t("common.loading")));
  let s, prov;
  try {
    s = await api("/api/settings");
    prov = await api("/api/providers");
  } catch (e) { return renderError(e); }

  const nodes = [el("h1", {}, t("settings.title"))];

  /* --- language --- */
  nodes.push(el("h2", {}, t("settings.section.language")));
  const langSel = el("select", {
    onchange: async (e) => {
      await api("/api/settings", { method: "PUT", body: { language: e.target.value } });
      await loadCatalogue(e.target.value);
      toast(t("common.saved"));
      renderSettings();
    },
  }, s.locales.map((l) => el("option", {
    value: l.code, selected: l.code === s.language,
  }, `${l.endonym} — ${l.name}`)));
  nodes.push(field("settings.language.label", langSel, "settings.language.help"));

  /* --- storage --- */
  nodes.push(el("h2", {}, t("settings.section.storage")));
  const dataIn = input({ value: s.data_dir });
  const archIn = input({ value: s.archive_dir });
  nodes.push(withHelp(el("div", {},
    field("setup.storage.data_label", dataIn),
    field("setup.storage.archive_label", archIn),
    el("p", { class: "meta" },
      `${t("status.database")}: ${s.database.path} · ${bytes(s.database.size_bytes)}`),
    el("p", { class: "meta" },
      `${t("status.archive")}: ${s.blob.location || s.blob.kind} · ` +
      t("settings.storage.usage", { size: bytes(s.blob.usage_bytes) }))),
    "settings.storage.help"));

  /* --- bundles --- */
  nodes.push(el("h2", {}, t("settings.section.bundles")));
  const chosen = new Set(s.bundles);
  nodes.push(withHelp(el("div", { class: "choices" },
    s.available_bundles.filter((b) => b.name !== "local").map((b) =>
      el("label", { class: "choice" },
        el("input", {
          type: "checkbox", checked: chosen.has(b.name),
          onchange: (e) => (e.target.checked ? chosen.add(b.name) : chosen.delete(b.name)),
        }),
        el("span", {}, el("strong", {}, b.name),
          el("span", { class: "meta" }, b.description),
          el("span", { class: "meta" },
            t("setup.bundles.source_count", { count: b.source_count })))))),
    "setup.bundles.help"));

  /* --- collection --- */
  nodes.push(el("h2", {}, t("settings.section.collection")));
  const interval = el("input", { type: "number", min: 1, max: 1440,
    value: s.collection.interval_min });
  const conc = el("input", { type: "number", min: 1, max: 64, value: s.collection.concurrency });
  const robots = el("input", { type: "checkbox", checked: s.collection.respect_robots });
  const fulltext = el("input", { type: "checkbox", checked: s.collection.fetch_fulltext });
  nodes.push(field("settings.collection.interval", interval, "settings.collection.help"));
  nodes.push(field("settings.collection.concurrency", conc,
    "settings.collection.help_concurrency"));
  nodes.push(withHelp(el("div", { class: "check" }, robots,
    el("label", {}, t("settings.collection.robots"))), "settings.collection.help_robots"));
  nodes.push(withHelp(el("div", { class: "check" }, fulltext,
    el("label", {}, t("settings.collection.fulltext"))), "settings.collection.help_fulltext"));

  nodes.push(el("div", { class: "actions" }, el("button", {
    class: "primary", type: "button",
    onclick: async (e) => {
      e.target.disabled = true;
      try {
        await api("/api/settings", {
          method: "PUT",
          body: {
            data_dir: dataIn.value, archive_dir: archIn.value, bundles: [...chosen],
            collection: {
              interval_min: Number(interval.value), concurrency: Number(conc.value),
              respect_robots: robots.checked, fetch_fulltext: fulltext.checked,
            },
          },
        });
        toast(t("common.saved"));
      } catch (err) { say(err); }
      e.target.disabled = false;
    },
  }, t("common.save"))));

  /* --- providers --- */
  nodes.push(el("h2", {}, t("settings.section.providers")));
  nodes.push(el("p", { class: "help-body" }, t("settings.providers.help")));
  const draft = JSON.parse(JSON.stringify(prov.providers));
  for (const [slot, cfg] of Object.entries(draft)) {
    const base = input({ value: cfg.base_url,
      oninput: (e) => { cfg.base_url = e.target.value; } });
    const model = input({ value: cfg.model, oninput: (e) => { cfg.model = e.target.value; } });
    const keyEnv = input({ value: cfg.api_key_env,
      oninput: (e) => { cfg.api_key_env = e.target.value; } });
    const state = el("span", { class: `badge ${cfg.configured ? "ok" : ""}` },
      cfg.configured ? t("status.provider.closed") : t("status.provider.unconfigured"));
    nodes.push(el("details", { class: "card" },
      el("summary", {}, `${slot} — ${cfg.function}`),
      el("div", { style: "margin-top:12px" },
        el("div", { class: "chips" }, state),
        field("settings.providers.base_url", base),
        field("settings.providers.model", model),
        field("settings.providers.api_key_env", keyEnv,
          "settings.providers.help_api_key_env"),
        el("div", { class: "actions" }, el("button", {
          type: "button",
          onclick: async (e) => {
            e.target.disabled = true;
            e.target.textContent = t("common.testing");
            try {
              const r = await api("/api/providers/test", { method: "POST", body: { slot } });
              toast(t(r.message_key));
            } catch (err) { say(err); }
            e.target.disabled = false;
            e.target.textContent = t("settings.providers.test");
          },
        }, t("settings.providers.test"))))));
  }
  nodes.push(withHelp(el("p", { class: "meta" },
    Object.entries(prov.chains).map(([k, v]) => `${k}: ${v.join(" → ")}`).join(" · ")),
    "settings.providers.help_chains"));
  nodes.push(el("div", { class: "actions" }, el("button", {
    class: "primary", type: "button",
    onclick: async (e) => {
      e.target.disabled = true;
      try {
        await api("/api/providers", {
          method: "PUT", body: { providers: draft, chains: prov.chains },
        });
        toast(t("common.saved"));
        renderSettings();
      } catch (err) { say(err); e.target.disabled = false; }
    },
  }, t("common.save"))));

  /* --- about --- */
  nodes.push(el("h2", {}, t("settings.section.about")));
  nodes.push(el("p", { class: "meta" }, t("settings.about.version", { version: s.version })));
  nodes.push(el("p", { class: "notice" }, t("settings.about.no_auth")));
  nodes.push(el("p", { class: "meta" },
    t("settings.about.config_location", { path: s.config_dir })));
  nodes.push(el("div", { class: "actions" }, el("button", {
    type: "button", class: "quiet",
    onclick: async () => {
      if (!confirm(t("settings.reset.confirm"))) return;
      await api("/api/setup/reset", { method: "POST" });
      location.hash = "#/setup";
      location.reload();
    },
  }, t("settings.reset"))));

  clear(nodes);
}

/* =============================== status =============================== */
async function renderStatus() {
  clear(el("p", { class: "meta" }, t("common.loading")));
  let s;
  try { s = await api("/api/status"); } catch (e) { return renderError(e); }

  const rows = [
    [t("status.tier"), `${t("tier.label", { tier: s.tier })} — ${t(`tier.${s.tier}.name`)}`],
    [t("status.articles"), s.articles.toLocaleString(LANG)],
    [t("status.enriched"), s.enriched.toLocaleString(LANG)],
    [t("status.queued"), s.queued.toLocaleString(LANG)],
    [t("status.sources_active"), s.sources_active],
    [t("status.sources_failing"), s.sources_failing],
    [t("status.database"), s.database],
    [t("status.archive"), s.archive.location || s.archive.kind],
    [t("status.last_collection"), when(s.last_collection)],
  ];

  clear([
    el("h1", {}, t("status.title")),
    el("p", { class: "lede" }, t(`tier.${s.tier}.desc`)),
    el("div", { class: "table-wrap" },
      el("table", {}, el("tbody", {}, rows.map(([k, v]) =>
        el("tr", {}, el("th", {}, k), el("td", {}, String(v))))))),
    el("h2", {}, t("status.providers")),
    el("div", { class: "table-wrap" },
      el("table", {},
        el("tbody", {}, s.providers.map((p) => el("tr", {},
          el("th", {}, `${p.slot} (${p.chain})`),
          el("td", {}, t(`status.provider.${p.state}`))))))),
    ...(s.bundle_errors || []).map((e) => el("p", { class: "notice bad" }, e)),
  ]);
}

/* =============================== router =============================== */
function renderError(err) {
  if (err && err.status === 409 && err.key === "err.setup.required") {
    location.hash = "#/setup";
    return;
  }
  clear(el("p", { class: "notice bad" }, t(err?.key || "err.generic", err?.params)));
}

const routes = {
  "/setup": renderSetup,
  "/today": renderToday,
  "/search": renderSearch,
  "/article": renderArticle,
  "/sources": renderSources,
  "/profile": renderProfile,
  "/settings": renderSettings,
  "/status": renderStatus,
};

async function route() {
  const raw = location.hash.slice(1).split("?")[0] || "/today";
  const [, head, arg] = raw.match(/^\/([^/]*)\/?(.*)$/) || [];
  const path = `/${head || "today"}`;
  const chrome = path !== "/setup";
  document.getElementById("topbar").hidden = !chrome;
  document.getElementById("foot").hidden = !chrome;
  document.querySelectorAll(".tabs a").forEach((a) => {
    if (a.getAttribute("href") === `#${path}`) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  const fn = routes[path] || routes["/today"];
  try { await fn(arg); } catch (e) { renderError(e); }
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const tier = document.getElementById("tier");
    tier.textContent = `${t("tier.label", { tier: s.tier })} · ${t(`tier.${s.tier}.name`)}`;
    tier.title = t(`tier.${s.tier}.desc`);
    document.getElementById("status-line").textContent =
      `${tn("common.count_articles", s.articles)} · ` +
      `${t("status.queued")}: ${s.queued.toLocaleString(LANG)} · ` +
      `${t("status.sources_active")}: ${s.sources_active}`;
  } catch {
    document.getElementById("status-line").textContent = t("err.unreachable");
  }
}

async function boot() {
  let state = { configured: false, language: FALLBACK_LANG };
  try {
    const [locales, setup] = await Promise.all([api("/api/locales"), api("/api/setup/state")]);
    LOCALES = locales.locales;
    state = setup;
  } catch { /* the catalogue still loads, so the error is at least readable */ }

  const stored = (() => { try { return localStorage.getItem("mcpnews.lang"); } catch { return null; } })();
  await loadCatalogue(state.language || stored || FALLBACK_LANG);
  try { localStorage.setItem("mcpnews.lang", LANG); } catch { /* private mode */ }

  if (!state.configured) location.hash = "#/setup";
  else if (!location.hash) location.hash = "#/today";

  await route();
  if (state.configured) refreshStatus();
}

addEventListener("hashchange", route);
boot();
/* Optional chaining, not a presence check: some contexts expose the property
   without an implementation behind it, and a dashboard that fails to render
   because offline caching is unavailable would be a poor trade. */
navigator.serviceWorker?.register("/sw.js").catch(() => {});
