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
  if (typeof GENERAL_SPOTLIGHTS !== "undefined") lists.push(GENERAL_SPOTLIGHTS);
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
  if (state.onboarding[`${view}Done`] && steps.length) {
    // 完成後維持完成狀態，之後改了範本也不會被拉回某一步；要重看從說明選單開始
    return { view, steps, done: steps.map(() => true), skipped, index: -1, step: null, complete: true };
  }
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
    // 虛線靶框在畫面外時捲過去，使用者才看得到要框哪裡
    document.querySelector("#overlay .guide-ghost, #overlay .guide-ghost-line")?.scrollIntoView({ block: "center", inline: "nearest" });
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
  if (!info || (!info.step && !info.complete)) { strip.hidden = true; g.stripKey = ""; return; }
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
// 目前指向的元素（不影響外觀，方便測試與輔助工具辨識）
function markPointed(el) {
  for (const node of document.querySelectorAll(".guide-pointed")) if (node !== el) node.classList.remove("guide-pointed");
  el?.classList.add("guide-pointed");
}
function syncEmphasis(step) {
  const g = state.guide;
  const pointer = $("missionPointer");
  const cardOpen = g.popoverOpen || !$("coachCard").hidden;
  if (g.spotlight) {
    // Spotlight 開著：只框它的目標，浮標退讓
    const target = resolveTarget(g.spotlight.step);
    setOutline(g.spotlight.opts.inPlace ? null : target?.el || null, `spot|${g.spotlight.step.id}`);
    markPointed(null);
    pointer.hidden = true;
    return;
  }
  if (!step || cardOpen || ghostVisible()) {
    markPointed(null);
    setOutline(null);
    pointer.hidden = true;
    return;
  }
  const target = resolveTarget(step);
  markPointed(target?.el || null);
  if (!target) { setOutline(null); pointer.hidden = true; return; }
  const where = visibility(target.el);
  // 三者互斥（虛線 > 浮標 > 外框）：有浮標文字就只用浮標，沒有文字才用外框
  const usePointer = !!target.label || where !== "visible";
  setOutline(!usePointer && where === "visible" && !g.outlineHidden ? target.el : null, target.key);
  if (usePointer && !g.outlineHidden) positionPointerToTarget(target.el, target.label || "在這裡", where);
  else pointer.hidden = true;
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
function showFloatCard(card, trigger, nodes, focus = true) {
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
  // 非 modal：焦點移到卡內第一個按鈕，Tab 不困在卡內。自己跳出的卡（新功能）不搶焦點
  if (focus) setTimeout(() => card.querySelector("button, a[href]")?.focus({ preventScroll: true }), 0);
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

/* ---------- 建立範本 8 步 ----------
 * 完成條件綁定真實的 state。示範模式（用示範發票）才畫虛線靶框與一鍵帶入；
 * 在自己的 PDF 上做時只用浮標指按鈕，完成條件放寬（例如表格切 2 欄就算）。
 */
const demoMode = (view) => state.guide.demo[view];
const guideField = (name) => state.guide.guideTemplate?.fields.find((f) => f.name === name) || null;
const guideTable = () => state.guide.guideTemplate?.tables[0] || null;
const hasFieldLike = (word) => T().fields.some((f) => f.name.includes(word) || (f.label?.text || "").includes(word));
const firstTable = () => T().tables[0] || null;
const editingReference = () => state.view === "train" && isReference();
// 有標題欄位的虛線：先框標題，記下標題後切到值的位置
function keyValueGhost(name) {
  const f = guideField(name);
  if (!f || !editingReference()) return [];
  if (state.pending?.label) return [{ page: f.ref_page, box: f.value_box, label: "再框住它的值" }];
  return [{ page: f.ref_page, box: f.label.box, label: `按 K，框住「${name}」` }];
}
const toolAssist = (tool, label) => () => (state.tool === tool || !editingReference() ? null : { label, run: () => setTool(tool) });
// 定位點：欄位標題也算。至少 3 個，而且至少 2 個中心落在頁面不同象限（分散才對得準）
function anchorSpread() {
  const boxes = [...T().anchors.map((a) => a.box), ...T().fields.filter((f) => f.kind === "key_value").map((f) => f.label.box)];
  const quadrants = new Set(boxes.map((b) => ((b[0] + b[2]) / 2 < 0.5 ? 0 : 1) + ((b[1] + b[3]) / 2 < 0.5 ? 0 : 2)));
  return { count: boxes.length, quadrants: quadrants.size };
}
const rightShowsList = () => !state.selected && !state.outputPanel;
const backToList = { sel: "#rightBackBtn", label: "回到欄位清單" };

const TRAIN_MISSIONS = [
  {
    id: "train-1", tab: "train", title: "命名",
    action: "在左欄輸入範本名稱",
    tip: "名稱也是存檔的檔名，之後可以改。",
    target: "#templateName", pointer: "輸入範本名稱",
    assist: () => ({ label: "幫我填", run: () => { setTemplateName("商業發票（練習）"); renderLeft(); } }),
    done: () => !!T().template_id,
  },
  {
    id: "train-2", tab: "train", title: "框有標題的欄位",
    action: "按 K，先框「發票號碼」標題",
    tip: () => (state.pending?.label ? "標題記下了，再框住右邊的值，框大一點沒關係。" : "標題是每份都一樣的字，用來找到值的位置。"),
    target: () => (state.tool !== "kv" && editingReference() ? { sel: '[data-tool="kv"]', label: "按 K 或點這裡" } : null),
    ghost: () => keyValueGhost("發票號碼"),
    assistAlways: toolAssist("kv", "切到有標題的欄位"),
    done: () => T().fields.length >= 1,
  },
  {
    id: "train-3", tab: "train", title: "設資料類型",
    action: "框「開立日期」，類型改成日期",
    tip: "日期格式不同沒關係，解析時會照原樣取值。",
    target: () => {
      if (document.querySelector('#right select[aria-label="資料類型"]')) return { sel: '#right select[aria-label="資料類型"]', label: "改選「日期」" };
      if (T().fields.length >= 2 && state.tool === "select") return { sel: "#right .items li:last-child button", label: "打開欄位設定" };
      return state.tool !== "kv" && editingReference() ? { sel: '[data-tool="kv"]', label: "按 K 或點這裡" } : null;
    },
    ghost: () => (hasFieldLike("開立日期") ? [] : keyValueGhost("開立日期")),
    assistAlways: () => (hasFieldLike("開立日期") || !demoMode("train") ? null : toolAssist("kv", "切到有標題的欄位")()),
    done: () => T().fields.some((f) => f.type === "date"),
  },
  {
    id: "train-4", tab: "train", title: "表格與切直欄",
    action: "按 T 框住明細，再點虛線切欄",
    tip: () => (firstTable() ? "在表格內點一下就切出一條直欄，雙擊可刪。" : "框資料區就好，不含標題列。"),
    target: () => {
      const t0 = firstTable();
      if (!t0) return state.tool !== "table" && editingReference() ? { sel: '[data-tool="table"]', label: "按 T 或點這裡" } : null;
      if (state.selected?.type !== "table") return { sel: "#overlay .box.table", label: "點表格，再切直欄" };
      return null;
    },
    ghost: () => {
      const guide = guideTable();
      if (!guide || !editingReference()) return [];
      const region = guide.regions[0];
      const t0 = firstTable();
      if (!t0) return [{ page: region.ref_page, box: region.box, label: "按 T，框住明細" }];
      if (state.selected?.type !== "table") return [];
      const mine = t0.regions.find((r) => r.ref_page === state.page) || t0.regions[0];
      // 每切一條就隱藏那一條虛線
      return region.dividers.slice(1, -1)
        .filter((x) => x > mine.box[0] && x < mine.box[2] && !mine.dividers.some((d) => Math.abs(d - x) < 0.02))
        .map((x) => ({ page: mine.ref_page, line: [x, mine.box[1], mine.box[3]] }));
    },
    assistAlways: () => (firstTable() ? null : toolAssist("table", "切到表格")()),
    done: () => {
      const t0 = firstTable();
      return !!t0 && (demoMode("train") ? t0.columns.length >= 4 : t0.columns.length >= 2);
    },
  },
  {
    id: "train-5", tab: "train", title: "判斷新的一列",
    action: "選第 1 欄當判斷新列的欄",
    tip: "通常是項次或序號，每一列都有、而且只出現一次。",
    setup() {
      const t0 = firstTable();
      if (!t0) return;
      state.selected = { type: "table", id: t0.id };
      state.outputPanel = false;
      state.tableTab = "columns";
      renderRight();
      renderOverlay();
    },
    target: () => (document.querySelector("#keyColumn") ? { sel: "#keyColumn", label: "選第 1 欄" }
      : firstTable() ? { sel: "#overlay .box.table", label: "點表格打開設定" } : null),
    done: () => T().tables.some((t) => !!t.key_column),
  },
  {
    id: "train-6", tab: "train", title: "定位點",
    action: "按「自動找」，刪掉會變的字",
    tip: () => {
      const { count, quadrants } = anchorSpread();
      return count >= 3 && quadrants < 2 ? "定位點都擠在一角，再加一個在頁面另一側。" : "定位點要分散在頁面四周，對位才準。";
    },
    setup() { state.selected = null; state.outputPanel = false; renderRight(); renderOverlay(); },
    target: () => (rightShowsList() ? { sel: "#suggestAnchorsBtn", label: "自動找定位點" } : backToList),
    done: () => { const { count, quadrants } = anchorSpread(); return count >= 3 && quadrants >= 2; },
  },
  {
    id: "train-7", tab: "train", title: "總金額與檢查",
    action: "框總金額，加一條加總檢查",
    tip: () => (state.checksOpen ? "選「表格某欄加總」，金額要等於總金額。" : "數字對不上時，結果會標記給人確認。"),
    target: () => {
      if (demoMode("train") && !hasFieldLike("總金額")) {
        return state.tool !== "kv" && editingReference() ? { sel: '[data-tool="kv"]', label: "按 K 或點這裡" } : null;
      }
      if (!rightShowsList()) return backToList;
      return state.checksOpen ? { sel: "#checkAddBtn", label: "選好後按加入檢查" } : { sel: "#checksDetails > summary", label: "展開新增檢查" };
    },
    ghost: () => (hasFieldLike("總金額") ? [] : keyValueGhost("總金額")),
    done: () => T().validations.length > 0,
  },
  {
    id: "train-8", tab: "train", title: "測試與儲存",
    action: "按測試看結果，再按儲存",
    tip: () => (state.tests.length ? "結果在下方表格，橘色是要檢查的值。" : "測試不會存檔，可以一直改一直測。"),
    target: () => (!state.tests.length ? { sel: "#testBtn", label: "按測試看結果" } : { sel: "#saveButton", label: "按儲存範本" }),
    done: () => state.tests.length > 0 && !!state.savedId && !hasUnsavedTemplate(),
  },
];

// 完成狀態的按鈕：主要是下一步，刪除練習範本只在示範模式出現
function completionActions(view) {
  const actions = [];
  if (view === "train") {
    actions.push({ label: "帶著這個範本去解析 PDF", class: "btn primary", id: "goRunBtn", run: goRunWithTemplate });
    if (demoMode("train") && state.savedId && T().name.endsWith("（練習）")) {
      actions.push({ label: "刪除練習範本", class: "linkish", id: "deletePracticeBtn", run: deletePracticeTemplate });
    }
  }
  if (typeof openHelp === "function") {
    actions.push({ label: "看進階功能", class: "btn ghost", id: "seeAdvancedBtn", run: (e) => openHelp("advanced", e.currentTarget) });
  }
  return actions;
}
function goRunWithTemplate() {
  const id = state.savedId;
  if (id && !state.templateIds.includes(id)) state.templateIds.push(id);
  setView("run");
}

/* ---------- 解析 PDF 6 步 ----------
 * 第 2 步不用「處理過」當完成條件（A5）：直接處理示警時，處理動作本身會把 runInspectedAlert 設為 true。
 * 第 3 步要處理過 1 筆、而且看見藍色處理紀錄（或按過還原），還原的教學才不會被跳過。
 * 第 4 到 6 步做過一次就算完成，之後點到別的格子不會被拉回去。
 */
const runFinished = () => !!state.run?.finished;
const runValues = () => (state.run?.results || []).flatMap((r) => allValues(r));
const isPending = (value) => ["review", "missing"].includes(value.status);
const handledAny = () => runValues().some((e) => isHandled(e.value));
const unflaggedCorrected = () => runValues().some((e) => e.value.status === "corrected" && !e.value.flag);
const noAlerts = () => runFinished() && !state.guide.batchHadAlerts;
function selectedNormal() {
  const result = activeResult();
  const entry = result && state.focusRef ? allValues(result).find((e) => e.ref === state.focusRef) : null;
  return !!entry && entry.value.status === "ok" && !isHandled(entry.value);
}
const NORMAL_CELL = "#drawer td[data-ref]:not(.review):not(.missing):not(.handled)";

const RUN_MISSIONS = [
  {
    id: "run-1", tab: "run", title: "準備與解析",
    action: "勾範本、加 PDF、按開始解析",
    tip: "選多個範本時，每份 PDF 會自動用最符合的。",
    target: () => {
      if (state.run && !state.run.finished) return null;
      if (!state.templateIds.length && !state.run?.demo) return { sel: "#left .template-picks input", label: "勾選範本" };
      if (!state.runDocs.length) return { sel: "#left .drop", label: "加入 PDF" };
      return { sel: "#runStartBtn", label: "開始解析" };
    },
    done: runFinished,
  },
  {
    id: "run-2", tab: "run", title: "看懂示警顏色",
    action: "點橘色項目，看它在原圖哪裡",
    legend: true,
    target: () => {
      const result = activeResult();
      if (result && allValues(result).some((e) => isPending(e.value))) {
        return { sel: "#right .review-item:not(.handled):not(.selected) button.locate", label: "點這裡看原圖" };
      }
      return { sel: ".docs li:has(.meta.warn) .doc-open", label: "這份有待檢查" };
    },
    done: () => runFinished() && (state.guide.runInspectedAlert || noAlerts()),
  },
  {
    id: "run-3", tab: "run", title: "修改或確認，再試還原",
    action: "改對按 Enter，或按確認",
    tip: () => (handledAny() ? "藍色是處理過的，按「還原」可放回待檢查。" : "改錯也沒關係，處理過的都能還原。"),
    target: () => (handledAny()
      ? { sel: "#right .review-item.handled .linkish", label: "可以還原" }
      : { sel: "#right .review-item:not(.handled):not(.selected) textarea", label: "改對按 Enter" }),
    done: () => runFinished() && ((handledAny() && state.guide.runSawHandled) || noAlerts()),
  },
  {
    id: "run-4", tab: "run", title: "點選正常格子",
    action: "點結果表格任一正常格",
    tip: "正常的值也能改，點一下會在原圖標出位置。",
    note: () => (noAlerts() ? "這批沒有示警，可以跳過看顏色的步驟。" : null),
    target: () => ({ sel: NORMAL_CELL, label: "點一格正常的" }),
    sticky: true,
    done: () => runFinished() && (selectedNormal() || !!document.querySelector("#drawer .cell-edit")
      || state.guide.runFineTuned || unflaggedCorrected()),
  },
  {
    id: "run-5", tab: "run", title: "微調並儲存",
    action: "改字後按「儲存修改」",
    tip: "修改會保留抓到的原值，之後可以還原。",
    target: () => {
      if (document.querySelector("#drawer .cell-edit")) return { sel: "#drawer .cell-edit", label: "按 Enter 儲存" };
      if (document.querySelector("#right .review-item.selected textarea")) return { sel: "#right .review-item.selected textarea", label: "改字後按儲存修改" };
      return { sel: NORMAL_CELL, label: "先點一格" };
    },
    sticky: true,
    done: () => runFinished() && (unflaggedCorrected() || state.guide.runFineTuned),
  },
  {
    id: "run-6", tab: "run", title: "瀏覽與匯出",
    action: "試「跳到待檢查」，再匯出",
    tip: "匯出後也會在 workspace/output 留一份。",
    target: () => (runValues().some((e) => isPending(e.value)) && !state.guide.runUsedNextFlagged
      ? { sel: "#nextFlaggedBtn", label: "跳到待檢查" }
      : { sel: "#exportExcelBtn", label: "匯出檢查用 Excel" }),
    sticky: true,
    done: () => !!state.run?.exported,
  },
];

/* 第 3 步：藍色處理紀錄出現在畫面上至少 600ms，才算看見（IntersectionObserver） */
let handledObserver = null;
let handledTimer = 0;
let handledNodes = [];
function watchHandledRecords(step) {
  const g = state.guide;
  const want = step?.id === "run-3" && !g.runSawHandled && "IntersectionObserver" in window;
  const nodes = want ? [...document.querySelectorAll("#right .review-item.handled")] : [];
  if (nodes.length === handledNodes.length && nodes.every((n, i) => n === handledNodes[i])) return;
  handledObserver?.disconnect();
  clearTimeout(handledTimer);
  handledNodes = nodes;
  if (!nodes.length) return;
  const seen = new Set();
  handledObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) seen.add(entry.target); else seen.delete(entry.target);
    }
    clearTimeout(handledTimer);
    if (seen.size) handledTimer = setTimeout(() => { g.runSawHandled = true; scheduleGuide(); }, 600);
  }, { threshold: 0.5 });
  nodes.forEach((node) => handledObserver.observe(node));
}

/* ---------- 進階功能（說明選單與右欄 ? 共用） ----------
 * needs：doc 要有 PDF、result 要有解析結果、table 要有表格。沒有時浮動卡改顯示「用示範發票看」。
 */
function selectFirstTable(tab, openColumn) {
  const t0 = firstTable();
  if (!t0) return;
  state.selected = { type: "table", id: t0.id };
  state.outputPanel = false;
  state.tableTab = tab;
  if (openColumn) state.openColumn = t0.columns[0]?.id || null;
  renderRight();
  renderOverlay();
}
function showList() { state.selected = null; state.outputPanel = false; renderRight(); renderOverlay(); }
const FEATURE_SPOTLIGHTS = [
  {
    id: "feat-pos-field", tab: "train", title: "只有值的欄位、續頁與取行規則",
    body: "沒有標題的值用「只有值的欄位」（P）框，靠定位點找位置。欄位設定可勾內容接到下一頁、只取第幾行。",
    target: '[data-tool="pos"]',
  },
  {
    id: "feat-cell-extract", tab: "train", title: "表格 6 種取值與一格拆多欄", needs: "table",
    body: "一格有好幾個值時，可依第幾行、開頭文字、正規表達式、空格或字距取值，也能把同一格拆成多欄。",
    setup: () => selectFirstTable("columns", true),
    target: '#right select[aria-label="這一欄怎麼取值"]',
  },
  {
    id: "feat-column-preview", tab: "train", title: "試抓這一欄（免全檔重跑）", needs: "table",
    body: "改了取值方式後，用基準範例試抓這一欄，馬上看到前幾列的結果，不用整份重新測試。",
    setup: () => selectFirstTable("columns", true),
    target: "#right .column-preview-btn",
  },
  {
    id: "feat-cross-page", tab: "train", title: "跨頁表格、表頭浮動、表尾結束", needs: "table",
    body: "明細接到下一頁時切到那頁加範圍；起始位置不固定就框表頭；遇到「合計」這類文字就結束。",
    setup: () => selectFirstTable("place", false),
    target: "#right .region-card",
  },
  {
    id: "feat-output", tab: "train", title: "輸出整理：乾淨資料與檢查用 Excel",
    body: "設定乾淨資料要輸出哪些欄、欄名與順序；檢查用 Excel 一律保留完整內容給人核對。",
    setup: showList,
    target: "#outputBtn",
  },
];
const RUN_SPOTLIGHTS = [
  {
    id: "run-alert-legend", tab: "run", title: "示警顏色速查",
    body: "表格、PDF 上的框與 Excel 都照這個顏色規則。滑過色塊可看原因。",
    legend: true,
  },
  {
    id: "run-next-flagged", tab: "run", title: "跳到下一個待檢查", needs: "result",
    body: "結果表格右上角，依檔案與頁面順序跨頁跨檔跳轉，處理完再按一次。",
    target: "#nextFlaggedBtn",
  },
  {
    id: "run-inline-edit", tab: "run", title: "結果表格就地修改", needs: "result",
    body: "按兩下任一格就能改字，Shift+Enter 換行。改過的變藍色並保留原值，可以還原。",
    target: "#drawer td[data-ref]",
  },
  {
    id: "run-popout", tab: "run", title: "雙視窗核對", needs: "result",
    body: "PDF 和結果表格都能移到新視窗，兩個螢幕對照，選取與修改會同步。",
    target: "#popTableBtn",
  },
  {
    id: "run-clean-export", tab: "run", title: "只輸出已確認的資料", needs: "result",
    body: "勾選後，乾淨資料只輸出人確認或修改過的值；檢查用 Excel 仍保留全部給人核對。",
    target: "#right .check-line",
  },
  {
    id: "run-multi-template", tab: "run", title: "多個範本自動挑選",
    body: "勾選多個範本時，每份 PDF 會比對定位點，自動用最符合的範本解析。",
    target: "#left .template-picks",
  },
];
// 觀摩做好的範本：一段 Spotlight 序列，不另寫邏輯
const SHOWCASE_SPOTLIGHTS = [
  {
    id: "show-fields", tab: "train", title: "框好的欄位",
    body: "觀摩範本已經框好 3 個欄位和 1 個表格，點清單裡任一項就能看它的設定。",
    setup: showList,
    target: "#right .items",
  },
  {
    id: "show-table", tab: "train", title: "表格的直欄與判斷列",
    body: "明細切成 4 個直欄，用「序號」判斷新的一列；在表格內點一下可以再切一欄。",
    setup: () => selectFirstTable("columns", false),
    target: "#keyColumn",
  },
  {
    id: "show-check", tab: "train", title: "加總檢查",
    body: "金額欄加總要等於總金額，對不上時結果會標記給人確認。",
    setup: showList,
    target: "#right .checks",
  },
  {
    id: "show-save", tab: "train", title: "測試與另存",
    body: "按測試看看結果。觀摩範本不會被改到，要自己用就按「另存成我的範本」。",
    target: "#testBtn",
  },
];
function startShowcaseTour() {
  const ids = SHOWCASE_SPOTLIGHTS.map((s) => s.id);
  openSpotlight(ids[0], { sequence: { index: 0, ids } });
}

function missingFor(step) {
  if (step.needs === "doc" && !currentDoc()) return "需要先載入 PDF";
  if (step.needs === "result" && !(state.view === "run" && activeResult())) return "需要先解析 PDF";
  if (step.needs === "table" && !(state.view === "train" && isReference() && T().tables.length)) return "需要先有表格";
  return null;
}
// 打開一個 Spotlight：切到對應分頁與右欄介面、框住目標、在旁邊開浮動卡。inPlace 時不切換畫面（右欄 ?）
function openSpotlight(id, opts = {}) {
  const step = findSpotlight(id);
  if (!step) return;
  closeHelp(false);
  const g = state.guide;
  if (!opts.inPlace && step.tab && state.view !== step.tab) setView(step.tab);
  const missing = opts.inPlace ? null : missingFor(step);
  if (!opts.inPlace && !missing) { try { step.setup?.(); } catch (_e) { /* 設定失敗不影響說明 */ } }
  g.spotlight = { step, opts, missing };
  const seen = state.onboarding.spotlightsSeen;
  if (!seen.includes(id)) { seen.push(id); saveOnboardingPrefs(); }
  const seq = opts.sequence;
  const actions = [];
  if (missing) {
    actions.push(h("button", {
      type: "button", class: "btn primary", id: "spotDemoBtn",
      onclick: async () => {
        closeSpotlight(false);
        await startDemo(step.tab === "run" ? "run" : "showcase", { guide: false });
        openSpotlight(id, opts);
      },
    }, "用示範發票看"));
  }
  if (seq) {
    const last = seq.index >= seq.ids.length - 1;
    actions.push(h("span", { class: "card-count" }, `${seq.index + 1} / ${seq.ids.length}`), h("span", { class: "spring" }));
    if (!last) {
      actions.push(h("button", {
        type: "button", class: "btn primary", id: "spotNextBtn",
        onclick: () => openSpotlight(seq.ids[seq.index + 1], { ...opts, sequence: { ...seq, index: seq.index + 1 } }),
      }, "下一項"));
    }
    actions.push(h("button", { type: "button", class: "btn", id: "spotEndBtn", onclick: () => { closeSpotlight(); seq.onEnd?.(); } }, last ? "完成" : "結束"));
  } else if (!missing) {
    actions.push(h("span", { class: "spring" }), h("button", { type: "button", class: "btn", onclick: () => closeSpotlight() }, "知道了"));
  } else {
    actions.push(h("button", { type: "button", class: "btn", onclick: () => closeSpotlight() }, "關閉"));
  }
  const card = $("coachCard");
  card.dataset.spotlight = id;
  showFloatCard(card, opts.anchor || $("helpBtn"), [
    h("h2", {}, step.title),
    h("p", {}, step.body),
    step.legend ? h("div", { class: "card-legend" }, alertLegendRow()) : null,
    missing ? h("p", { class: "card-missing" }, `${missing}才能指給你看。`) : null,
    h("div", { class: "card-actions" }, actions),
  ]);
  scheduleGuide();
  requestAnimationFrame(() => {
    const target = !opts.inPlace && !missing ? resolveTarget(step) : null;
    if (target && visibility(target.el) !== "visible") target.el.scrollIntoView({ block: "nearest", inline: "nearest" });
    positionOpenCards();
  });
}
function closeSpotlight(restoreFocus = true) {
  const g = state.guide;
  const card = $("coachCard");
  g.spotlight = null;
  delete card.dataset.spotlight;
  hideFloatCard(card, restoreFocus);
  setOutline(null);
  scheduleGuide();
}
// 浮動卡跟著目標移動（捲動、右欄重畫後重新定位）
function positionOpenCards() {
  const g = state.guide;
  const card = $("coachCard");
  if (g.spotlight && !card.hidden) {
    const { step, opts, missing } = g.spotlight;
    const target = !opts.inPlace && !missing ? resolveTarget(step) : null;
    const anchor = opts.anchor?.isConnected ? opts.anchor : target && visibility(target.el) === "visible" ? target.el : $("helpBtn");
    positionFloatCard(card, anchor, anchor === $("helpBtn") ? ["bottom", "left"] : ["right", "bottom", "left", "top"]);
  }
  const help = $("helpPopover");
  if (!help.hidden) positionFloatCard(help, $("helpBtn"), ["bottom", "left"]);
}

/* ---------- 說明選單（頂列，導覽關閉後也一直在） ---------- */
function guideStatus(view) {
  const prefs = state.onboarding;
  const steps = missionsFor(view);
  if (prefs[`${view}Done`]) return { text: "已完成 ✓", action: "重看" };
  const index = steps.findIndex((s) => s.id === prefs[`${view}Step`]);
  if (index >= 0) return { text: `進行到 ${index + 1}/${steps.length}`, action: "繼續" };
  return { text: "未開始", action: "開始" };
}
function resumeOrStartGuide(view, trigger) {
  closeHelp(false);
  const prefs = state.onboarding;
  const status = guideStatus(view);
  if (status.action === "繼續") {
    if (state.view !== view) setView(view);
    prefs.dismissed = false;
    state.guide.on[view] = true;
    saveOnboardingPrefs();
    scheduleGuide();
    return;
  }
  if (state.view !== view) setView(view);
  requestGuide(view, trigger);
}
function renderHelpPopover(section) {
  const seen = state.onboarding.spotlightsSeen;
  const here = state.view === "run" ? RUN_SPOTLIGHTS : FEATURE_SPOTLIGHTS;
  const there = state.view === "run" ? FEATURE_SPOTLIGHTS : RUN_SPOTLIGHTS;
  const guideRow = (view, label) => {
    const status = guideStatus(view);
    return h("li", {}, h("button", {
      type: "button", class: "help-row", id: `helpGuide-${view}`,
      onclick: (e) => resumeOrStartGuide(view, e.currentTarget),
    }, h("span", {}, label), h("span", { class: "help-meta" }, status.text)));
  };
  const featureRow = (step) => h("li", {}, h("button", {
    type: "button", class: "help-row", dataset: { spotlight: step.id },
    onclick: () => openSpotlight(step.id),
  }, h("span", {}, step.title), seen.includes(step.id) ? h("span", { class: "help-meta seen" }, "已看過") : null));
  const whatsNew = typeof whatsNewHelpRow === "function" ? whatsNewHelpRow() : null;
  return [
    h("h2", {}, "說明"),
    h("section", { class: "help-section", "aria-label": "新手導覽" },
      h("h3", {}, "新手導覽"),
      h("ul", {}, guideRow("train", "建立範本 8 步"), guideRow("run", "解析 PDF 6 步"))),
    h("section", { class: "help-section", id: "helpAdvanced", "aria-label": "進階功能" },
      h("h3", {}, "進階功能"),
      h("ul", {}, here.map(featureRow), there.map(featureRow))),
    whatsNew ? h("section", { class: "help-section" }, whatsNew) : null,
    h("section", { class: "help-section" },
      h("ul", {}, h("li", {}, h("a", { class: "help-row", href: "/manual", target: "_blank", rel: "noopener", id: "helpManual" },
        h("span", {}, "使用手冊"), h("span", { class: "help-meta", "aria-hidden": "true" }, "↗"))))),
  ];
}
function openHelp(section, trigger) {
  closeSpotlight(false);
  const pop = $("helpPopover");
  state.guide.popoverOpen = true;
  $("helpBtn").setAttribute("aria-expanded", "true");
  pop.classList.toggle("help-history", section === "whatsnew");
  const nodes = section === "whatsnew" && typeof renderWhatsNewHistory === "function" ? renderWhatsNewHistory() : renderHelpPopover(section);
  showFloatCard(pop, trigger || $("helpBtn"), nodes);
  positionFloatCard(pop, $("helpBtn"), ["bottom", "left"]);
  if (section === "advanced") {
    // 從導覽列的「功能點我看」進來：直接捲到進階功能
    const block = $("helpAdvanced");
    pop.scrollTop = block ? block.offsetTop - 12 : 0;
    setTimeout(() => block?.querySelector("button")?.focus({ preventScroll: true }), 0);
  }
  scheduleGuide();
}
function closeHelp(restoreFocus = true) {
  const pop = $("helpPopover");
  if (pop.hidden) return;
  state.guide.popoverOpen = false;
  $("helpBtn").setAttribute("aria-expanded", "false");
  hideFloatCard(pop, restoreFocus);
  scheduleGuide();
}
// 右欄設定旁的 ?：開該項的說明卡，不切換畫面
function helpHint(id, label) {
  return h("button", {
    type: "button", class: "help-hint", "aria-label": `說明：${label}`, title: `說明：${label}`, dataset: { spotlight: id },
    onclick: (e) => { e.preventDefault(); e.stopPropagation(); openSpotlight(id, { inPlace: true, anchor: e.currentTarget }); },
  }, "?");
}

/* Esc 依序關閉：說明選單 → 浮動教學卡 → 新功能小卡 → 浮標與外框。輸入框裡的 Esc 交給輸入框。 */
function handleGuideEscape() {
  const g = state.guide;
  if (!$("helpPopover").hidden) { closeHelp(); return true; }
  if (!$("coachCard").hidden) { closeSpotlight(); return true; }
  const card = $("whatsNewCard");
  if (card && !card.hidden && typeof dismissWhatsNewCard === "function") { dismissWhatsNewCard(); return true; }
  if (!g.outlineHidden && (!$("missionPointer").hidden || document.querySelector(".guide-target"))) {
    g.outlineHidden = true;
    $("missionPointer").hidden = true;
    setOutline(null);
    return true;
  }
  return false;
}
function setupHelpMenu() {
  if (POPOUT) return;
  $("helpBtn").addEventListener("click", (e) => {
    if ($("helpPopover").hidden) openHelp("all", e.currentTarget); else closeHelp();
  });
  // 點選單外面就收起（非 modal）
  document.addEventListener("pointerdown", (e) => {
    const pop = $("helpPopover");
    if (!pop.hidden && !pop.contains(e.target) && !$("helpBtn").contains(e.target)
      && !e.target.closest?.("#featureMenuBtn, #seeAdvancedBtn")) closeHelp(false);
  });
}

/* ---------- 新功能（whatsnew.json） ----------
 * 第一次使用的人不跳新功能（他們走新手導覽），直接記成目前版本。
 * 升級後：說明按鈕出現小點；1.2 秒後頂列下方滑出小卡（只出現一次）。新手導覽進行中只亮小點。
 * 逐項導覽用同一份 Spotlight 資料；看完最後一項、按結束或打開新功能清單，就記成看過。
 */
const GENERAL_SPOTLIGHTS = [
  {
    id: "help-menu", title: "說明選單",
    body: "新手導覽、進階功能、新功能與使用手冊都在這裡，關閉導覽後也找得到。",
    target: "#helpBtn",
  },
  {
    id: "welcome-demo", tab: "train", title: "用示範發票邊做邊學",
    body: "還沒開檔案時，可以跟著示範發票一步步做出範本；解析 PDF 頁也能練習核對與匯出。",
    target: "#demoStartBtn",
  },
];
const WHATSNEW_TOUR_LIMIT = 5;
function compareVersions(a, b) {
  const pa = String(a).split(".").map((n) => parseInt(n, 10) || 0);
  const pb = String(b).split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
  }
  return 0;
}
const shortVersion = (v) => String(v).split(".").slice(0, 2).join(".");
function cleanVersions(data) {
  const list = Array.isArray(data?.versions) ? data.versions : [];
  return list.filter((v) => typeof v?.version === "string" && Array.isArray(v.items)).map((v) => ({
    version: v.version,
    date: typeof v.date === "string" ? v.date : "",
    items: v.items.filter((i) => typeof i?.title === "string" && typeof i?.spotlight === "string"),
  })).sort((a, b) => compareVersions(b.version, a.version));
}
async function loadWhatsNew(version) {
  if (POPOUT || !version) return;
  let data;
  try {
    const response = await fetch("/web/whatsnew.json", { cache: "no-cache" });  // 同源靜態檔
    data = await response.json();
  } catch (_e) { return; }
  const prefs = state.onboarding;
  const versions = cleanVersions(data).filter((v) => compareVersions(v.version, version) <= 0);
  state.whatsnew = { current: version, versions, pending: [] };
  if (!prefs.whatsnewSeen && onboardingFirstUse) {
    prefs.whatsnewSeen = version;  // 第一次使用：走新手導覽，不跳新功能
    saveOnboardingPrefs();
    return;
  }
  const seen = prefs.whatsnewSeen;
  const fresh = versions.filter((v) => (seen ? compareVersions(v.version, seen) > 0 : v.version === version));
  const items = fresh.flatMap((v) => v.items);  // 新的在前
  if (!items.length) {
    if (!seen || compareVersions(version, seen) > 0) { prefs.whatsnewSeen = version; saveOnboardingPrefs(); }
    return;
  }
  state.whatsnew.pending = items;
  state.whatsnew.fresh = fresh;
  renderWhatsNewDot();
  const guideRunning = guideVisible("train") || guideVisible("run");
  if (prefs.whatsnewCardShown !== version && !guideRunning) setTimeout(showWhatsNewCard, 1200);
}
function renderWhatsNewDot() {
  const dot = document.querySelector("#helpBtn .help-dot");
  if (dot) dot.hidden = !state.whatsnew?.pending.length;
}
function showWhatsNewCard() {
  const wn = state.whatsnew;
  if (!wn?.pending.length || guideVisible(state.view)) return;
  state.onboarding.whatsnewCardShown = wn.current;  // 小卡只出現一次，重新整理後不再跳出
  saveOnboardingPrefs();
  const items = wn.pending;
  const titles = items.slice(0, 2).map((i) => i.title).join("、") + (items.length > 2 ? "…" : "");
  const card = $("whatsNewCard");
  showFloatCard(card, document.activeElement, [
    h("div", { class: "whatsnew-head" },
      h("h2", {}, `${shortVersion(wn.current)} 更新了 ${items.length} 項`),
      h("button", { type: "button", class: "whatsnew-close", "aria-label": "關閉", onclick: dismissWhatsNewCard }, "✕")),
    h("p", { class: "whatsnew-titles" }, titles),
    h("div", { class: "card-actions" },
      h("button", { type: "button", class: "btn primary", id: "whatsNewTourBtn", onclick: startWhatsNewTour }, "看看"),
      h("button", { type: "button", class: "btn ghost", id: "whatsNewLaterBtn", onclick: dismissWhatsNewCard }, "之後再說"),
      items.length > WHATSNEW_TOUR_LIMIT ? h("button", { type: "button", class: "linkish", onclick: () => { dismissWhatsNewCard(); openHelp("whatsnew"); } }, "看全部") : null),
  ], false);
}
// 之後再說：收起小卡，小點保留到在說明選單看過新功能為止
function dismissWhatsNewCard() { hideFloatCard($("whatsNewCard"), false); }
function markWhatsNewSeen() {
  const wn = state.whatsnew;
  if (!wn) return;
  state.onboarding.whatsnewSeen = wn.current;
  saveOnboardingPrefs();
  wn.pending = [];
  renderWhatsNewDot();
}
function startWhatsNewTour() {
  dismissWhatsNewCard();
  const items = (state.whatsnew?.pending || []).slice(0, WHATSNEW_TOUR_LIMIT);
  const ids = items.map((i) => i.spotlight).filter((id) => findSpotlight(id));
  if (!ids.length) { markWhatsNewSeen(); return; }
  openSpotlight(ids[0], { sequence: { index: 0, ids, onEnd: markWhatsNewSeen } });
}
function whatsNewHelpRow() {
  const wn = state.whatsnew;
  if (!wn?.versions.length) return null;
  const count = wn.pending.length || wn.versions[0].items.length;
  const label = wn.pending.length ? `${shortVersion(wn.current)} 新增 ${count} 項` : `${shortVersion(wn.versions[0].version)} 有 ${count} 項`;
  return h("ul", {}, h("li", {}, h("button", {
    type: "button", class: "help-row", id: "helpWhatsNew", onclick: (e) => openHelp("whatsnew", e.currentTarget),
  }, h("span", {}, "新功能"), h("span", { class: "help-meta" }, label,
    wn.pending.length ? h("span", { class: "help-row-dot", "aria-label": "有還沒看的新功能" }) : null))));
}
// 新功能清單：所有版本由新到舊，每版可展開；每項可單獨導覽。打開就算看過
function renderWhatsNewHistory() {
  const wn = state.whatsnew;
  markWhatsNewSeen();
  return [
    h("div", { class: "whatsnew-head" },
      h("h2", {}, "新功能"),
      h("button", { type: "button", class: "linkish", id: "whatsNewBack", onclick: (e) => openHelp("all", e.currentTarget) }, "‹ 說明")),
    (wn?.versions || []).map((v, i) => h("details", { class: "whatsnew-version", open: i === 0 },
      h("summary", {}, `${v.version}`, h("span", { class: "help-meta" }, `${v.date ? `${v.date}，` : ""}${v.items.length} 項`)),
      v.items.length ? h("ul", {}, v.items.map((item) => h("li", {}, h("button", {
        type: "button", class: "help-row whatsnew-item", dataset: { spotlight: item.spotlight },
        onclick: () => openSpotlight(item.spotlight),
      }, h("span", {}, h("strong", {}, item.title), h("small", {}, item.body))))))
        : h("p", { class: "help-empty" }, "這版沒有畫面上的改變。"))),
  ];
}
