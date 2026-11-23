"use strict";
/* 進階功能的實地練習（labs）。
 *
 * 一般 <script src> 載入，放在 spotlights.js 之後、app.js 之前（CSP 不允許 inline script 與 eval）。
 * 練習用的 PDF、練習範本與預期值在 app/pdfmapper/demo/labs.json，由 /api/demo-samples（mode: "lab"）送來。
 * 步驟資料格式和新手關卡完全一樣（見 spotlights.js），指令條、浮標、虛線靶框與推關規則共用同一套引擎，
 * 只是導覽的 view 叫 "lab"（guideView()）。進度不存檔，只有「做完過」的 id 會記在 prefs.labsDone。
 * 練習範本不寫入 workspace/templates、不存草稿；回到我的工作時，原本的文件與範本（含未儲存的修改）原樣接回。
 */

// 練習前的狀態，回到我的工作時整組放回去（範本物件本身不會被練習改到，練習用的是另一份）
const LAB_STASH_KEYS = [
  "docs", "referenceId", "docId", "page", "zoom", "tool", "pending", "selected", "template", "undo",
  "savedTemplate", "savedId", "tests", "read", "checkDraft", "drawerOpen", "outputPanel", "columnPreview",
  "showcase", "tableTab", "openColumn", "fieldAdvancedOpen", "checksOpen", "recovery", "focusRef",
];
const labStash = () => ({
  view: state.view,
  state: Object.fromEntries(LAB_STASH_KEYS.map((key) => [key, state[key]])),
});

/* ---------- 練習的狀態與驗證 ---------- */
const labColumn = (id) => firstTable()?.columns.find((c) => c.id === id) || null;
// 使用者自己新增的欄位（不含練習範本一開始就有的）
const labNewFields = () => T().fields.filter((f) => !state.guide.lab?.baseFieldIds.includes(f.id));
const labNorm = (text) => String(text ?? "").replace(/\r\n/g, "\n");
const labShow = (text) => `「${labNorm(text).replace(/\n/g, "↵")}」`;

function labHint(hints, got, expect) {
  for (const hint of hints || []) {
    const when = hint.when;
    const hit = when === "empty" ? got === ""
      : when === "partof" ? got !== "" && got !== expect && expect.includes(got)
        : when === "wider" ? got !== expect && got.includes(expect)
          : when.startsWith("contains:") ? got.includes(when.slice(9))
            : when === "other";
    if (hit) return hint.text;
  }
  return "";
}
/* 用實際的試抓結果驗證：none 還沒試抓、stale 結果對不上現在的設定、wrong 有差異、ok 全對。
 * 比對前 \r\n 一律轉成 \n（Windows 與其他系統的換行不同）。 */
function labCheck() {
  const L = state.guide.lab;
  if (!L) return null;
  const result = state.tests.find((r) => r.doc_id === state.referenceId);
  if (!result) return { status: "none" };
  const v = L.data.verify;
  const hints = L.data.hints;
  let got;
  if (v.kind === "new_field") {
    const mine = labNewFields();
    if (!mine.length) return { status: "wrong", message: "還沒有你新增的欄位。用 P 在頁面右上角框住單號，再按測試。" };
    const field = result.fields.find((f) => f.id === mine[mine.length - 1].id);
    if (!field) return { status: "stale", message: "欄位改過了，再按一次測試。" };
    got = [labNorm(field.value)];
  } else {
    const table = result.tables.find((t) => t.id === v.table);
    if (!table || !table.columns.some((c) => c.id === v.column)) {
      return { status: "stale", message: "這份結果和現在的設定對不上，再按一次測試。" };
    }
    got = table.rows.map((row) => labNorm(row.cells[v.column]?.value));
  }
  const expect = v.expect === undefined ? [] : Array.isArray(v.expect) ? v.expect.map(labNorm) : [labNorm(v.expect)];
  if (got.length !== expect.length) {
    return { status: "wrong", message: `抓到 ${got.length} 列，預期 ${expect.length} 列。表格範圍或判斷新一列的欄位被改到了，請改回來。` };
  }
  for (let i = 0; i < expect.length; i += 1) {
    if (got[i] === expect[i]) continue;
    const where = v.kind === "new_field" ? "抓到" : `第 ${i + 1} 列抓到`;
    const hint = labHint(hints, got[i], expect[i]);
    return {
      status: "wrong",
      message: `${where}${labShow(got[i])}，預期${labShow(expect[i])}。${hint}改好後再按一次測試。`,
    };
  }
  return { status: "ok", values: expect };
}
// 最後一步的完成條件：驗證通過。結果記下來給完成畫面用
function labVerified() {
  const check = labCheck();
  if (check?.status !== "ok") return false;
  state.guide.lab.okValues = check.values;
  return true;
}
const labWrong = () => labCheck()?.status === "wrong";
function labVerifyTip(idle) {
  const check = labCheck();
  if (!check || check.status === "none") return idle;
  return check.message || idle;
}
// 規則試算區（卡片）算出預期的值，就算「在試算區試過」
function labTrialResult(mode, data) {
  const L = state.guide.lab;
  if (!L || mode !== "extract" || !data.ok || !data.found) return;
  const expect = Array.isArray(L.data.verify.expect) ? L.data.verify.expect[0] : null;
  if (expect && data.value === expect) { L.flags.trial = true; scheduleGuide(); }
}

/* ---------- 步驟共用的小零件 ---------- */
function labSelectTable() {
  const t0 = firstTable();
  if (!t0) return;
  Object.assign(state, { selected: { type: "table", id: t0.id }, outputPanel: false, tableTab: "columns", openColumn: null });
  renderRight();
  renderOverlay();
}
// 指到某一欄的設定：先點表格，再點這一欄的「設定」，打開後指到要操作的那一格
function labColumnTarget(columnId, name, sel, label) {
  if (state.selected?.type !== "table") return { sel: "#right .items li:last-child button", label: "點表格" };
  if (state.openColumn !== columnId) return { sel: `button.column-more[aria-label="${name} 的設定"]`, label: "點「設定」" };
  return sel ? { sel, label } : null;
}
const labOpened = (columnId) => state.selected?.type === "table" && state.openColumn === columnId;
// 最後一步：按測試，結果錯了就指回去改
function labTestTarget() {
  if (labWrong() && rightShowsList()) return { sel: "#right .items li:last-child button", label: "回去改設定" };
  return state.selected ? null : { sel: "#testBtn", label: "按這裡試抓" };
}
function labVerifyStep(id, tip) {
  return {
    id, tab: "train", title: "試抓驗證", action: "按「用 1 份範例測試」，看結果對不對",
    tip: () => labVerifyTip(tip), wrong: labWrong, target: labTestTarget, sticky: true, done: labVerified,
  };
}
const LAB_PO_BOX = [0.64, 0.05, 0.82, 0.076];   // 練習 PDF 右上角的單號

/* ---------- 步驟 ---------- */
const LAB_STEPS = {
  "pos-field": [
    {
      id: "lab-pos-field-1", tab: "train", title: "切到只有值的欄位",
      action: "按 P，切到「只有值的欄位」", tip: "這種值旁邊沒有標題，靠定位點找位置。",
      target: () => (state.tool !== "pos" ? { sel: '[data-tool="pos"]', label: "按 P 或點這裡" } : null),
      sticky: true, done: () => state.tool === "pos" || labNewFields().length > 0,
    },
    {
      id: "lab-pos-field-2", tab: "train", title: "框住單號",
      action: "在頁面右上角框住單號", tip: "框大一點沒關係，但不要包到其他字。",
      ghost: () => (labNewFields().length ? [] : [{ page: 0, box: LAB_PO_BOX, label: "框住右上角的單號" }]),
      target: () => (state.tool !== "pos" && !labNewFields().length ? { sel: '[data-tool="pos"]', label: "按 P 或點這裡" } : null),
      sticky: true, done: () => labNewFields().length > 0,
    },
    labVerifyStep("lab-pos-field-3", "結果會列在下面，這份練習 PDF 的單號是 PO 開頭。"),
  ],
  "cell-extract": [
    {
      id: "lab-cell-extract-1", tab: "train", title: "打開 Spec 欄",
      action: "點 Spec 欄的「設定」", tip: "每一欄怎麼取值，都在這一欄的設定裡。",
      setup: labSelectTable,
      target: () => (labOpened("spec") ? null : labColumnTarget("spec", "Spec")),
      sticky: true, done: () => labOpened("spec"),
    },
    {
      id: "lab-cell-extract-2", tab: "train", title: "選開頭文字",
      action: "「這一欄怎麼取值」選「開頭文字」", tip: "這格有兩行，只要 ECCN 的值。",
      target: () => labColumnTarget("spec", "Spec", '#right select[aria-label="這一欄怎麼取值"]', "選開頭文字"),
      sticky: true, done: () => !!labColumn("spec") && valueMode(labColumn("spec")) === "start",
    },
    {
      id: "lab-cell-extract-3", tab: "train", title: "填開頭文字",
      action: "開頭文字填 ECCN:", tip: "和 PDF 上寫的一樣，包含冒號。",
      target: () => labColumnTarget("spec", "Spec", '#right input[aria-label="開頭文字"]', "填 ECCN:"),
      assist: () => ({
        label: "幫我填",
        run: () => {
          const column = labColumn("spec");
          if (!column) return;
          snapshot();
          if (valueMode(column) !== "start") setValueMode(firstTable(), column, "start");
          column.start = "ECCN:";
          state.openColumn = column.id;
          renderRight();
        },
      }),
      sticky: true, done: () => !!labColumn("spec") && valueMode(labColumn("spec")) === "start" && !!(labColumn("spec").start || "").trim(),
    },
    labVerifyStep("lab-cell-extract-4", "每一列只該抓到 ECCN 後面的值。"),
  ],
  regex: [
    {
      id: "lab-regex-1", tab: "train", title: "選正規表達式",
      action: "展開 Ref 欄，取值方式選「正規表達式」", tip: "Ref 這格有 Ref、單號和 rev，只要中間的單號。",
      setup: labSelectTable,
      target: () => labColumnTarget("ref", "Ref", '#right select[aria-label="這一欄怎麼取值"]', "選正規表達式"),
      sticky: true, done: () => !!labColumn("ref") && valueMode(labColumn("ref")) === "regex",
    },
    {
      id: "lab-regex-2", tab: "train", title: "在試算區試規則",
      action: "點規則旁的 ?，試出 INV-2026-0301",
      tip: "原始內容貼 Ref INV-2026-0301 rev2，規則只描述單號的樣子。",
      target: () => labColumnTarget("ref", "Ref", '#right .help-hint[data-spotlight="feat-regex"]', "點這個 ?"),
      sticky: true, done: () => !!state.guide.lab?.flags.trial,
    },
    {
      id: "lab-regex-3", tab: "train", title: "套用到這一欄",
      action: "把試好的規則套用到 Ref 欄", tip: "試算區的「套用到這一欄」，或直接貼進規則欄。",
      target: () => labColumnTarget("ref", "Ref", '#right input[aria-label="正規表達式"]', "貼上規則"),
      assist: () => ({
        label: "幫我填",
        run: () => {
          const column = labColumn("ref");
          if (!column) return;
          snapshot();
          if (valueMode(column) !== "regex") setValueMode(firstTable(), column, "regex");
          column.extract = String.raw`INV-\d{4}-\d{4}`;
          state.openColumn = column.id;
          renderRight();
        },
      }),
      sticky: true, done: () => !!labColumn("ref") && valueMode(labColumn("ref")) === "regex" && !!(labColumn("ref").extract || "").trim(),
    },
    labVerifyStep("lab-regex-4", "每一列只該抓到 INV 開頭的單號。"),
  ],
};

/* ---------- 指令條：缺文件與完成畫面 ---------- */
function labMissingDoc(step, index) {
  const lab = state.guide.lab;
  return {
    key: [step.id, "no-doc"],
    nodes: [
      h("span", { class: "mission-badge", "aria-hidden": "true" }, String(index + 1)),
      h("div", { class: "mission-text" },
        h("p", { class: "mission-action" }, "練習用的 PDF 被關掉了"),
        h("p", { class: "mission-tip" }, "按「再練一次」重新載入。")),
      h("div", { class: "mission-controls" },
        h("button", { type: "button", class: "btn", id: "labRetryBtn", onclick: () => startLab(lab.id) }, "再練一次")),
    ],
  };
}
function labCompletion() {
  const lab = state.guide.lab;
  const values = lab.okValues || [];
  const shown = values.map((v) => labNorm(v).replace(/\n/g, "↵")).join("、");
  return {
    key: ["done", lab.id, shown],
    nodes: [
      h("span", { class: "mission-badge done", "aria-hidden": "true" }, "✓"),
      h("div", { class: "mission-text" },
        h("p", { class: "mission-action", id: "labResult" }, `✓ 抓到 ${shown}`),
        h("p", { class: "mission-tip", id: "labLearned" }, lab.data.learned)),
      h("div", { class: "mission-controls" },
        lab.data.manual ? h("a", {
          class: "linkish card-manual", id: "labManualLink", href: `${MANUAL_URL}#${lab.data.manual}`, target: "_blank", rel: "noopener",
        }, "看手冊 ↗") : null,
        h("button", { type: "button", class: "btn", id: "labRetryBtn", onclick: () => startLab(lab.id) }, "再練一次"),
        h("button", { type: "button", class: "btn primary", id: "labBackBtn", onclick: () => exitLab() }, "回到我的工作")),
    ],
  };
}

/* ---------- 開始與離開 ---------- */
// 有已載入的文件或未儲存的範本時先問（沿用新手導覽的作法），練習中再開另一個練習不用再問
function requestLab(id, trigger) {
  const busy = !state.guide.lab && (state.docs.length > 0 || hasUnsavedTemplate());
  if (!busy) { startLab(id); return; }
  const card = $("coachCard");
  if (typeof closeSpotlight === "function") closeSpotlight(false);
  showFloatCard(card, trigger, [
    h("h2", {}, "要開始實地練習嗎？"),
    h("p", {}, "練習會暫時換成練習用的 PDF 與範本。按「回到我的工作」後，目前的檔案與範本（含還沒儲存的修改）會原樣接回來。"),
    h("div", { class: "card-actions" },
      h("button", { type: "button", class: "btn", id: "labCancelBtn", onclick: () => hideFloatCard(card) }, "取消"),
      h("button", {
        type: "button", class: "btn primary", id: "labConfirmBtn",
        onclick: () => { hideFloatCard(card, false); startLab(id); },
      }, "開始練習")),
  ]);
  positionFloatCard(card, trigger || $("helpBtn") || $("stage"), ["bottom", "right", "left", "top"]);
}
// guard 在 app.js 裡，載入時還沒有，所以包一層，呼叫時才取用
const startLab = (id) => guard(startLabNow)(id);
async function startLabNow(id) {
  const g = state.guide;
  if (g.loadingDemo) return;
  if (state.run && !state.run.finished) { toast("解析進行中，完成後再開始練習", true); return; }
  g.loadingDemo = true;
  try {
    const data = await api("/api/demo-samples", { json: { mode: "lab", lab: id } });
    closeHelp(false);
    closeSpotlight(false);
    const previous = g.lab;
    // 再練一次：先收掉上一輪的練習 PDF；第一次練習才記下目前的工作
    if (previous) for (const doc of state.docs) await api(`/api/docs/${doc.id}`, { method: "DELETE" }).catch(() => null);
    const stash = previous ? previous.stash : labStash();
    if (state.view !== "train") setView("train");
    const first = data.docs[0];
    Object.assign(state, {
      template: { ...blankTemplate(), ...data.template }, savedTemplate: null, savedId: null, undo: [],
      docs: data.docs, referenceId: first.id, docId: first.id, page: 0, zoom: 1, tests: [],
      tool: "select", pending: null, selected: null, read: null, checkDraft: null, drawerOpen: false,
      outputPanel: false, columnPreview: null, showcase: false, openColumn: null, tableTab: "columns",
      fieldAdvancedOpen: false, checksOpen: false, recovery: null, focusRef: null,
    });
    state.savedTemplate = comparable(T());  // 練習範本一開始不算「未儲存」
    g.lab = { id, data: data.lab, stash, flags: {}, baseFieldIds: T().fields.map((f) => f.id), okValues: null };
    Object.assign(state.onboarding, { labStep: null, labSkipped: [], labDone: false });
    Object.assign(g, { pinned: false, stripKey: "", stripStep: "", barKey: "", ghostKey: "[]", ghosts: [] });
    g.on.lab = true;
    g.demo.lab = true;
    g.current.lab = null;
    g.latched.lab = [];
    renderAll();
  } finally {
    g.loadingDemo = false;
  }
}
// 回到我的工作：練習用的 PDF 刪掉，練習前的文件、範本、草稿與畫面位置原樣放回
const exitLab = () => guard(exitLabNow)();
async function exitLabNow() {
  const g = state.guide;
  const lab = g.lab;
  if (!lab) return;
  closeHelp(false);
  closeSpotlight(false);
  for (const doc of state.docs) await api(`/api/docs/${doc.id}`, { method: "DELETE" }).catch(() => null);
  g.lab = null;
  g.on.lab = false;
  g.demo.lab = false;
  g.current.lab = null;
  g.latched.lab = [];
  Object.assign(g, { stripKey: "", stripStep: "", barKey: "", ghostKey: "[]", ghosts: [] });
  Object.assign(state, lab.stash.state, { view: lab.stash.view });
  renderAll();
  scheduleGuide();
  toast("已回到你的工作");
}
