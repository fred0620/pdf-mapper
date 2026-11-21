"use strict";
/* 新手導覽、進階功能與新功能導覽共用的 Spotlight 引擎與步驟資料。
 *
 * 一般 <script src> 載入，放在 app.js 之前（CSP 不允許 inline script 與 eval）。
 * 這裡的函式都在 app.js 載入後才會被呼叫，所以可以直接用 app.js 的 state、h、$、T 等。
 * 新手關卡、進階功能、新功能都是同一種步驟資料，定位、高亮與浮動卡只有一套。
 * 進度只存步驟 id 與旗標，不存任何 PDF 內容、檔名或抓到的值（和日誌原則一致）。
 */

/* ---------- 偏好與進度（localStorage） ---------- */
const ONBOARDING_KEY = "pdfmapper.onboarding.v1";
const LEGACY_DISMISSED_KEY = "pdfmapper.onboarding.dismissed";
const blankPrefs = () => ({
  dismissed: false,
  trainStep: null,
  runStep: null,
  trainDone: false,
  runDone: false,
  trainSkipped: [],
  runSkipped: [],
  spotlightsSeen: [],
  tipsSeen: { drawerTip: 0 },
  whatsnewSeen: null,
  whatsnewCardShown: null,
});
// 這個瀏覽器有沒有用過本工具：沒有任何紀錄時當作第一次使用，不跳新功能
let onboardingFirstUse = false;
function loadOnboardingPrefs() {
  const prefs = blankPrefs();
  onboardingFirstUse = false;
  try {
    const raw = localStorage.getItem(ONBOARDING_KEY);
    const legacy = localStorage.getItem(LEGACY_DISMISSED_KEY);
    const data = raw ? JSON.parse(raw) : null;
    if (data && typeof data === "object" && !Array.isArray(data)) {
      for (const key of ["dismissed", "trainDone", "runDone"]) prefs[key] = data[key] === true;
      for (const key of ["trainStep", "runStep", "whatsnewSeen", "whatsnewCardShown"]) {
        prefs[key] = typeof data[key] === "string" ? data[key].slice(0, 40) : null;
      }
      for (const key of ["trainSkipped", "runSkipped", "spotlightsSeen"]) {
        prefs[key] = Array.isArray(data[key]) ? data[key].filter((v) => typeof v === "string").slice(0, 50) : [];
      }
      const tip = Number(data.tipsSeen?.drawerTip);
      prefs.tipsSeen.drawerTip = Number.isFinite(tip) ? tip : 0;
    } else {
      // 舊版用過（有草稿或舊的關閉紀錄）就不是第一次，升級後要看得到新功能
      onboardingFirstUse = legacy === null && !localStorage.getItem(DRAFT_KEY);
    }
    if (legacy !== null) {
      if (legacy === "1") prefs.dismissed = true;
      localStorage.removeItem(LEGACY_DISMISSED_KEY);
      localStorage.setItem(ONBOARDING_KEY, JSON.stringify(prefs));
    }
  } catch (_e) {
    // 無痕模式、被清除或格式錯：一律當作新使用者
    onboardingFirstUse = true;
    return blankPrefs();
  }
  return prefs;
}
function saveOnboardingPrefs() {
  try { localStorage.setItem(ONBOARDING_KEY, JSON.stringify(state.onboarding)); } catch (_e) { /* 非必要 */ }
}

/* ---------- 執行中的導覽狀態（不存檔） ---------- */
const blankGuide = () => ({
  on: { train: false, run: false },        // 導覽列是否顯示
  demo: { train: false, run: false },      // 用示範檔案進行（顯示虛線靶框與一鍵帶入）
  current: { train: null, run: null },     // 目前停在哪一步
  latched: { train: [], run: [] },         // 做過就算完成的步驟（例如點過正常格）
  pinned: false,                           // 使用者主動回頭看，不自動拉走
  ghosts: [],                              // 畫布上的虛線靶框
  ghostKey: "[]",
  stripKey: "",
  stripStep: "",
  barKey: "",
  pointerKey: "",
  pulseKey: "",
  outlineHidden: false,                    // Esc 收起外框高亮，換步驟後恢復
  guideTemplate: null,                     // 示範範本的位置，只用來畫虛線靶框
  spotlight: null,                         // 開著的 Spotlight：{ step, opts }
  popoverOpen: false,
  runInspectedAlert: false,
  runSawHandled: false,
  runFineTuned: false,
  runUsedNextFlagged: false,
  batchHadAlerts: true,
  loadingDemo: false,
  justSavedTemplateId: null,
});

/* ---------- 步驟資料 ----------
 * 一個步驟的格式（新手關卡、進階功能、新功能共用）：
 * {
 *   id: "run-next-flagged",
 *   tab: "train" | "run",
 *   title: "跳到下一個待檢查",        // 導覽列與浮動卡標題
 *   action: "…",                      // 關卡的行動句（22 字內）
 *   tip: "…",                         // 關卡的提醒（30 字內）
 *   body: "…",                        // 浮動卡內文（60 字內）
 *   setup() {},                       // 選用：切換右欄、選取表格等（只能呼叫 renderRight / renderOverlay）
 *   target: "#nextFlaggedBtn",        // 選擇器，或 () => ({ sel, label }) / null
 *   pointer: "跳到下一個待檢查",       // 浮標文字（12 字內）；有虛線靶框時自動讓位
 *   ghost: () => [{ page, box, label } | { page, line: [x, y0, y1] }],
 *   assist: () => ({ label, run }),   // 選用：一鍵帶入
 *   done() { return false; },         // 只有關卡需要
 *   sticky: true,                     // 做過一次就算完成
 *   needs: "doc" | "result" | "table" // 需要先載入什麼才能示範
 * }
 */
function trainMissions() { return typeof TRAIN_MISSIONS === "undefined" ? [] : TRAIN_MISSIONS; }
function runMissions() { return typeof RUN_MISSIONS === "undefined" ? [] : RUN_MISSIONS; }
const missionsFor = (view) => (view === "train" ? trainMissions() : runMissions());
function allSpotlights() {
  const lists = [trainMissions(), runMissions()];
  if (typeof FEATURE_SPOTLIGHTS !== "undefined") lists.push(FEATURE_SPOTLIGHTS, RUN_SPOTLIGHTS);
  if (typeof SHOWCASE_SPOTLIGHTS !== "undefined") lists.push(SHOWCASE_SPOTLIGHTS);
  return lists.flat();
}
const findSpotlight = (id) => allSpotlights().find((step) => step.id === id) || null;

/* ---------- 推關 ---------- */
const guideVisible = (view) => !POPOUT && !state.onboarding.dismissed && state.guide.on[view];
function stepDone(view, step) {
  const latched = state.guide.latched[view];
  if (latched.includes(step.id)) return true;
  let done = false;
  try { done = !!step.done?.(); } catch (_e) { done = false; }
  if (done && step.sticky) latched.push(step.id);
  return done;
}
// 每次重算：使用者停在「剛剛還沒完成、現在完成」的步驟 → 跳到第一個未完成的步驟（不是 +1）；
// 主動回頭看已完成的步驟 → 留在原地。
function evaluateGuide(view) {
  const g = state.guide;
  const steps = missionsFor(view);
  const skipped = state.onboarding[`${view}Skipped`];
  const done = steps.map((step) => stepDone(view, step));
  const firstOpen = steps.findIndex((step, i) => !done[i] && !skipped.includes(step.id));
  let index = steps.findIndex((step) => step.id === g.current[view]);
  if (index < 0 || (!g.pinned && (done[index] || skipped.includes(steps[index].id)))) {
    index = firstOpen;
  }
  const complete = steps.length > 0 && firstOpen < 0 && (index < 0 || done[index] || skipped.includes(steps[index]?.id));
  const step = complete || index < 0 ? null : steps[index];
  if (step && step.id !== g.current[view]) {
    // 先記下新步驟，再呼叫 setup（setup 只會 renderRight / renderOverlay，不會遞迴回來）
    g.current[view] = step.id;
    g.outlineHidden = false;
    state.onboarding[`${view}Step`] = step.id;
    saveOnboardingPrefs();
    try { step.setup?.(); } catch (_e) { /* 設定失敗不影響導覽 */ }
  }
  if (complete && !state.onboarding[`${view}Done`]) {
    state.onboarding[`${view}Done`] = true;
    saveOnboardingPrefs();
  }
  return { view, steps, done, skipped, index, step, complete };
}
function goToStep(view, id, pinned) {
  state.guide.current[view] = id;
  state.guide.pinned = pinned;
  state.onboarding[`${view}Step`] = id;
  saveOnboardingPrefs();
  const step = missionsFor(view).find((s) => s.id === id);
  try { step?.setup?.(); } catch (_e) { /* 設定失敗不影響導覽 */ }
  scheduleGuide();
}
// 下一步在本步未完成時也能按，該步標成「已跳過」，不算完成
function skipStep(view) {
  const info = evaluateGuide(view);
  if (!info.step) return;
  const skipped = state.onboarding[`${view}Skipped`];
  if (!info.done[info.index] && !skipped.includes(info.step.id)) skipped.push(info.step.id);
  const next = info.steps[info.index + 1];
  if (next) goToStep(view, next.id, false);
  else { state.guide.pinned = false; saveOnboardingPrefs(); scheduleGuide(); }
}
function startGuide(view, demo) {
  const prefs = state.onboarding;
  prefs.dismissed = false;
  prefs[`${view}Done`] = false;
  prefs[`${view}Skipped`] = [];
  prefs[`${view}Step`] = null;
  const g = state.guide;
  g.on[view] = true;
  g.demo[view] = !!demo;
  g.current[view] = null;
  g.latched[view] = [];
  g.pinned = false;
  g.stripKey = "";
  g.barKey = "";
  if (view === "run") Object.assign(g, { runInspectedAlert: false, runSawHandled: false, runFineTuned: false, runUsedNextFlagged: false });
  saveOnboardingPrefs();
  scheduleGuide();
}
// 「關閉導覽」只收起導覽列與指令條，進度保留，從說明選單可以繼續
function dismissGuide() {
  state.onboarding.dismissed = true;
  saveOnboardingPrefs();
  state.guide.on = { train: false, run: false };
  scheduleGuide();
}

/* ---------- 排程與繪製 ---------- */
let guideFrame = 0;
// 同一畫格內的多次呼叫合併成一次
function scheduleGuide() {
  if (POPOUT || guideFrame) return;
  guideFrame = requestAnimationFrame(() => { guideFrame = 0; renderGuide(); });
}
function renderGuide() {
  const g = state.guide;
  const view = state.view;
  let info = null;
  if (guideVisible(view)) info = evaluateGuide(view);
  renderGuideBar(info);
  renderMissionStrip(info);
  const ghosts = info?.step?.ghost && g.demo[view] ? safeGhosts(info.step) : [];
  const key = JSON.stringify(ghosts);
  if (key !== g.ghostKey) {
    g.ghostKey = key;
    g.ghosts = ghosts;
    renderOverlay();
  }
  syncEmphasis(info?.step || null);
  if (typeof watchHandledRecords === "function") watchHandledRecords(info?.step || null);
  if (typeof positionOpenCards === "function") positionOpenCards();
}
function safeGhosts(step) {
  try { return (step.ghost() || []).filter(Boolean); } catch (_e) { return []; }
}

/* 導覽列：建立範本 ●──●──◐──○  3/8 設資料類型        功能點我看 ▾   關閉導覽 */
function renderGuideBar(info) {
  const bar = $("guideBar");
  if (!info) { bar.hidden = true; state.guide.barKey = ""; return; }
  const { steps, done, skipped, index, step, complete, view } = info;
  const states = steps.map((s, i) => (i === index && !complete ? "active" : done[i] ? "done" : skipped.includes(s.id) ? "skipped" : "todo"));
  const key = JSON.stringify([view, states, complete]);
  bar.hidden = false;
  if (key === state.guide.barKey) return;
  state.guide.barKey = key;
  const word = { active: "進行中", done: "已完成", skipped: "已跳過", todo: "未開始" };
  fill(bar,
    h("span", { class: "guide-name" }, view === "train" ? "建立範本" : "解析 PDF"),
    h("ol", { class: "guide-steps" }, steps.map((s, i) => h("li", {},
      h("button", {
        type: "button", class: `guide-step ${states[i]}`, title: s.title,
        "aria-label": `第 ${i + 1} 步：${s.title}，${word[states[i]]}`,
        "aria-current": states[i] === "active" ? "step" : false,
        onclick: () => goToStep(view, s.id, true),
      })))),
    h("span", { class: "guide-progress" }, complete ? `${steps.length}/${steps.length} 完成`
      : step ? `${index + 1}/${steps.length} ${step.title}` : ""),
    h("span", { class: "spring" }),
    h("div", { class: "guide-bar-actions" },
      typeof openHelp === "function" ? h("button", {
        type: "button", class: "btn ghost", id: "featureMenuBtn", "aria-haspopup": "dialog",
        onclick: (e) => openHelp("advanced", e.currentTarget),
      }, "功能點我看 ▾") : null,
      h("button", { type: "button", class: "btn ghost", id: "guideCloseBtn", onclick: dismissGuide }, "關閉導覽")));
}

/* 指令條：一句行動、一行提醒。內容沒變就不重畫，螢幕閱讀器才不會一直重念。 */
function renderMissionStrip(info) {
  const strip = $("missionStrip");
  const g = state.guide;
  if (!info) { strip.hidden = true; g.stripKey = ""; return; }
  const view = info.view;
  const content = info.complete ? completionContent(view) : stepContent(info);
  const key = JSON.stringify([view, content.key]);
  strip.hidden = false;
  if (key === g.stripKey) return;
  const stepKey = `${view}|${content.key[0]}`;
  const changed = stepKey !== g.stripStep;
  g.stripKey = key;
  g.stripStep = stepKey;
  fill(strip, content.nodes);
  if (changed && !reducedMotion()) {
    strip.classList.remove("mission-enter");
    void strip.offsetWidth;  // 重新觸發淡入
    strip.classList.add("mission-enter");
  }
}
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
function stepContent(info) {
  const { step, index, steps, view } = info;
  if (view === "train" && !state.docs.length) {
    // 重新整理後範例 PDF 不在了：先請使用者加入，或改用示範發票
    return {
      key: [step.id, "no-doc"],
      nodes: [
        h("span", { class: "mission-badge", "aria-hidden": "true" }, String(index + 1)),
        h("div", { class: "mission-text" },
          h("p", { class: "mission-action" }, "先加入範例 PDF",
            typeof startDemo === "function" ? h("button", { type: "button", class: "btn ghost mission-assist", onclick: () => startDemo("train") }, "用示範發票") : null),
          h("p", { class: "mission-tip" }, "加入後從目前這一步接著做。")),
        h("div", { class: "mission-controls" },
          h("button", { type: "button", class: "btn ghost", onclick: () => $("filePicker").click() }, "選擇 PDF…")),
      ],
    };
  }
  const assist = step.assist && state.guide.demo[view] ? safeCall(step.assist) : null;
  const custom = step.assistAlways ? safeCall(step.assistAlways) : null;
  const helper = assist || custom;
  const note = step.note ? safeCall(step.note) : null;
  const legend = step.legend ? alertLegendRow() : null;
  const tip = typeof step.tip === "function" ? safeCall(step.tip) : step.tip;
  const action = typeof step.action === "function" ? safeCall(step.action) : step.action;
  const nodes = [
    h("span", { class: "mission-badge", "aria-hidden": "true" }, String(index + 1)),
    h("div", { class: "mission-text" },
      note ? h("p", { class: "mission-note" }, note) : null,
      h("p", { class: "mission-action" }, h("span", { class: "sr-only" }, `第 ${index + 1} 步，`), action,
        helper ? h("button", { type: "button", class: "btn ghost mission-assist", onclick: helper.run }, helper.label) : null),
      legend || (tip ? h("p", { class: "mission-tip" }, tip) : null)),
    h("div", { class: "mission-controls" },
      h("button", { type: "button", class: "btn ghost", disabled: index === 0, onclick: () => goToStep(view, steps[index - 1].id, true) }, "上一步"),
      h("button", { type: "button", class: "btn ghost", onclick: () => skipStep(view) }, "下一步")),
  ];
  return { key: [step.id, action, tip, note, helper?.label || "", !!legend, index], nodes };
}
function completionContent(view) {
  const actions = typeof completionActions === "function" ? completionActions(view) : [];
  const nodes = [
    h("span", { class: "mission-badge done", "aria-hidden": "true" }, "✓"),
    h("div", { class: "mission-text" },
      h("p", { class: "mission-action" }, view === "train" ? "範本做好了" : "核對流程走完了"),
      h("p", { class: "mission-tip" }, view === "train" ? "可以拿它解析 PDF，或看看進階功能。" : "匯出的檔案也在 workspace/output。")),
    h("div", { class: "mission-controls" }, actions.map((a) => h("button", {
      type: "button", class: a.class || "btn ghost", id: a.id, onclick: a.run,
    }, a.label)), h("button", { type: "button", class: "btn ghost", onclick: dismissGuide }, "關閉導覽")),
  ];
  return { key: ["done", actions.map((a) => a.label).join("|")], nodes };
}
const safeCall = (fn) => { try { return fn(); } catch (_e) { return null; } };

/* 五色圖例：解析 PDF 第 2 步與速查卡共用。色塊之後一定有文字，看不出顏色也能辨識。 */
const ALERT_LEGEND = [
  ["sw-review", "待檢查", "加總不符、壓線、對位或 OCR 疑慮"],
  ["sw-missing", "缺值", "必填的欄位沒有抓到"],
  ["sw-handled", "已處理", "人工確認或修改過，可以還原"],
  ["sw-ok", "正常", "沒有疑慮的值"],
  ["sw-notice", "整份提示", "整份檔案的提醒，例如項次不連續"],
];
function alertLegendRow() {
  return h("ul", { class: "legend-row", "aria-label": "顏色說明" }, ALERT_LEGEND.map(([cls, label, why]) =>
    h("li", { class: "legend-chip", tabindex: "0", title: why, "aria-label": `${label}：${why}` },
      h("span", { class: `legend-swatch ${cls}`, "aria-hidden": "true" }), label)));
}

/* ---------- 強調：同一時間只有一個強調點 ----------
 * 有虛線靶框就只畫靶框；否則有可見目標就顯示浮標加外框；目標在畫面外時只顯示浮標並指向捲動方向。
 * 浮動卡（教學卡、說明選單）開著時，浮標與外框退讓。
 */
function ghostVisible() {
  const g = state.guide;
  return g.ghosts.length > 0 && state.view === "train" && isReference()
    && g.ghosts.some((ghost) => ghost.page === state.page) && !$("sheet").hidden;
}
function findVisible(sel) {
  if (!sel) return null;
  if (sel instanceof Element) return sel;
  for (const el of document.querySelectorAll(sel)) if (el.getClientRects().length) return el;
  return null;
}
function resolveTarget(step) {
  if (!step?.target) return null;
  const raw = typeof step.target === "function" ? safeCall(step.target) : { sel: step.target, label: step.pointer };
  if (!raw) return null;
  const el = findVisible(raw.sel);
  return el ? { el, label: raw.label ?? step.pointer ?? "", key: `${step.id}|${raw.sel}|${raw.label}` } : null;
}
function setOutline(el, key) {
  for (const node of document.querySelectorAll(".guide-target")) {
    if (node !== el) node.classList.remove("guide-target", "guide-pulse");
  }
  if (!el) return;
  el.classList.add("guide-target");
  if (key !== state.guide.pulseKey) {
    state.guide.pulseKey = key;
    if (!reducedMotion()) el.classList.add("guide-pulse");
  }
}
function syncEmphasis(step) {
  const g = state.guide;
  const pointer = $("missionPointer");
  const cardOpen = g.popoverOpen || !$("coachCard").hidden;
  if (g.spotlight) {
    // Spotlight 開著：只框它的目標，浮標退讓
    const target = resolveTarget(g.spotlight.step);
    setOutline(g.spotlight.opts.inPlace ? null : target?.el || null, `spot|${g.spotlight.step.id}`);
    pointer.hidden = true;
    return;
  }
  if (!step || cardOpen || ghostVisible()) {
    setOutline(null);
    pointer.hidden = true;
    return;
  }
  const target = resolveTarget(step);
  if (!target) { setOutline(null); pointer.hidden = true; return; }
  const where = visibility(target.el);
  setOutline(where === "visible" && !g.outlineHidden ? target.el : null, target.key);
  positionPointerToTarget(target.el, target.label, where);
  if (target.key !== g.pointerKey) {
    g.pointerKey = target.key;
    // 只在目標換了、而且使用者不在輸入時才捲動
    if (!/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "")) {
      target.el.scrollIntoView({ block: "nearest", inline: "nearest" });
      positionPointerToTarget(target.el, target.label, visibility(target.el));
    }
  }
}
const scrollBox = (el) => el.closest(".side, #stage, #drawer");
function visibility(el) {
  const r = el.getBoundingClientRect();
  if (!r.width && !r.height) return "hidden";
  const parent = scrollBox(el)?.getBoundingClientRect();
  const top = Math.max(parent ? parent.top : 0, 0);
  const bottom = Math.min(parent ? parent.bottom : innerHeight, innerHeight);
  if (r.bottom < top + 4) return "up";
  if (r.top > bottom - 4) return "down";
  return "visible";
}
const POINTER_GAP = 12;
function positionPointerToTarget(el, label, where = visibility(el)) {
  const pointer = $("missionPointer");
  if (!el || !label || where === "hidden") { pointer.hidden = true; return; }
  const r = el.getBoundingClientRect();
  pointer.hidden = false;
  pointer.textContent = where === "visible" ? label : `${where === "up" ? "↑" : "↓"} ${label}`;
  const w = pointer.offsetWidth;
  const ph = pointer.offsetHeight;
  let left;
  let top;
  let dir;
  if (where !== "visible") {
    const parent = scrollBox(el)?.getBoundingClientRect() || { top: 0, bottom: innerHeight };
    dir = where;
    left = r.left + r.width / 2 - w / 2;
    top = where === "up" ? Math.max(parent.top, 0) + 8 : Math.min(parent.bottom, innerHeight) - ph - 8;
  } else if (r.right + POINTER_GAP + w < innerWidth - 8 && (innerWidth - r.right >= r.left || r.left - POINTER_GAP - w < 8)) {
    dir = "left";
    left = r.right + POINTER_GAP;
    top = r.top + r.height / 2 - ph / 2;
  } else if (r.left - POINTER_GAP - w > 8) {
    dir = "right";
    left = r.left - POINTER_GAP - w;
    top = r.top + r.height / 2 - ph / 2;
  } else {
    dir = "down";
    left = r.left + r.width / 2 - w / 2;
    top = r.top - ph - 10;
  }
  pointer.dataset.dir = dir;
  pointer.style.left = `${clamp(left, 8, innerWidth - w - 8)}px`;
  pointer.style.top = `${clamp(top, 8, innerHeight - ph - 8)}px`;
}

/* 畫布虛線靶框：由 renderOverlay 呼叫，畫在範本框之上，不擋滑鼠 */
function renderGhostGuides(layer) {
  if (POPOUT || state.view !== "train" || !isReference()) return;
  for (const ghost of state.guide.ghosts) {
    if (ghost.page !== state.page) continue;
    if (ghost.line) {
      const [x, y0, y1] = ghost.line;
      const line = h("div", { class: "guide-ghost-line" }, h("span", { class: "guide-ghost-dot" }));
      line.style.left = `${x * 100}%`;
      line.style.top = `${y0 * 100}%`;
      line.style.height = `${(y1 - y0) * 100}%`;
      layer.append(line);
      continue;
    }
    const node = h("div", { class: "guide-ghost" }, ghost.label ? h("span", { class: "guide-ghost-tag" }, ghost.label) : null);
    pctStyle(node, ghost.box);
    layer.append(node);
  }
}

/* ---------- 浮動卡（教學卡、說明選單、新功能小卡共用 .float-card） ---------- */
const floatTriggers = new Map();  // 卡片 → 打開它的元素，關閉時焦點回去
function showFloatCard(card, trigger, nodes) {
  fill(card, nodes);
  const wasHidden = card.hidden;
  card.hidden = false;
  if (wasHidden) {
    floatTriggers.set(card, trigger || document.activeElement);
    if (!reducedMotion()) {
      card.classList.remove("float-enter");
      void card.offsetWidth;
      card.classList.add("float-enter");
    }
  }
  // 非 modal：焦點移到卡內第一個按鈕，Tab 不困在卡內
  setTimeout(() => card.querySelector("button, a[href]")?.focus({ preventScroll: true }), 0);
}
function hideFloatCard(card, restoreFocus = true) {
  if (card.hidden) return;
  card.hidden = true;
  const trigger = floatTriggers.get(card);
  floatTriggers.delete(card);
  if (restoreFocus && trigger?.isConnected) trigger.focus({ preventScroll: true });
}
// 錨定在目標旁：優先右、再下、再左，保持 8px；超出視窗時翻轉
function positionFloatCard(card, anchor, prefer = ["right", "bottom", "left", "top"]) {
  if (card.hidden || !anchor?.isConnected) return;
  const r = anchor.getBoundingClientRect();
  const w = card.offsetWidth;
  const ch = card.offsetHeight;
  const gap = 8;
  const fits = {
    right: r.right + gap + w <= innerWidth - 8,
    left: r.left - gap - w >= 8,
    bottom: r.bottom + gap + ch <= innerHeight - 8,
    top: r.top - gap - ch >= 8,
  };
  const side = prefer.find((s) => fits[s]) || "bottom";
  let left = side === "right" ? r.right + gap : side === "left" ? r.left - gap - w : r.right - w;
  let top = side === "bottom" ? r.bottom + gap : side === "top" ? r.top - gap - ch : r.top;
  left = clamp(left, 8, innerWidth - w - 8);
  top = clamp(top, 8, Math.max(8, innerHeight - ch - 8));
  card.style.left = `${left}px`;
  card.style.top = `${top}px`;
}

/* ---------- 版面變化時重算浮標與浮動卡位置 ---------- */
function watchGuideLayout() {
  if (POPOUT) return;
  let ticking = false;
  const tick = () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { ticking = false; renderGuide(); });
  };
  // 左欄、右欄、#stage、#drawer 的捲動都會觸發（捕獲階段收得到不冒泡的 scroll）
  document.addEventListener("scroll", tick, true);
  window.addEventListener("resize", tick);
  if ("ResizeObserver" in window) {
    const observer = new ResizeObserver(tick);
    observer.observe(document.body);
    observer.observe($("drawer"));
  }
}

/* 重新整理後接回導覽：進行中的那一頁導覽繼續顯示，完成條件一律從目前的畫面重算 */
function restoreGuide() {
  state.onboarding = loadOnboardingPrefs();
  const prefs = state.onboarding;
  for (const view of ["train", "run"]) {
    state.guide.on[view] = !prefs.dismissed && !!prefs[`${view}Step`] && !prefs[`${view}Done`];
    state.guide.current[view] = prefs[`${view}Step`];
  }
}
