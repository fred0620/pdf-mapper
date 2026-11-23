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
  "runDocs", "run", "templateIds",
];
// 練習在哪個分頁進行：多數在建立範本，解析 PDF 的練習在解析分頁（結果列在那裡）
const LAB_RUN_VIEW = ["multi-template"];
const labViewOf = (id) => (LAB_RUN_VIEW.includes(id) ? "run" : "train");
const labView = () => labViewOf(state.guide.lab?.id);
const labDocs = () => (labView() === "run" ? state.runDocs : state.docs);
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
/* 一份結果和預期值的差異：沒差回傳 null，有差回傳要顯示的訊息。who 是「第 2 份」這類前綴（多份 PDF 時） */
function labDiff(got, expect, v, who, single) {
  if (got.length !== expect.length) {
    return `${who}抓到 ${got.length} 列，預期 ${expect.length} 列。${v.rows_hint || "表格範圍或判斷新一列的欄位被改到了，請改回來。"}`;
  }
  for (let i = 0; i < expect.length; i += 1) {
    if (got[i] === expect[i]) continue;
    const where = single ? `${who}抓到` : `${who}第 ${i + 1} 列抓到`;
    return `${where}${labShow(got[i])}，預期${labShow(expect[i])}。${labHint(state.guide.lab.data.hints, got[i], expect[i])}改好後再按一次測試。`;
  }
  return null;
}
const labList = (value) => (value === undefined ? [] : Array.isArray(value) ? value.map(labNorm) : [labNorm(value)]);
/* 格式檢查：值要被標記。規則還沒設、或設了仍讓值通過，依規則的現況給提示 */
function labFieldFlag(v, result) {
  const field = result.fields.find((f) => f.id === v.field);
  if (!field) return { status: "stale", message: "這份結果和現在的設定對不上，再按一次測試。" };
  if ((field.reasons || []).includes(v.reason)) return { status: "ok", values: [labNorm(field.value)] };
  const pattern = T().fields.find((f) => f.id === v.field)?.pattern || "";
  let passes = pattern === "";
  try { passes = passes || new RegExp(pattern).test(v.value); } catch (_e) { return { status: "stale", message: "規則寫法有誤，改好後再按一次測試。" }; }
  if (!passes) return { status: "stale", message: "格式檢查改過了，再按一次測試。" };
  const hint = labHint(state.guide.lab.data.hints, pattern, v.value);
  return { status: "wrong", message: `${field.name} 抓到${labShow(field.value)}，沒有被標記。${hint}改好後再按一次測試。` };
}
/* 數字檢查：要有一條「幾個欄位相加」，欄位與要等於的對象都對，而且試抓後那個欄位真的被標記 */
function labSumCheck(v, result) {
  const names = (ids) => ids.map((id) => T().fields.find((f) => f.id === id)?.name || id).join(" 和 ");
  const rule = T().validations.find((r) => r.type === "sum_fields");
  if (!rule) return { status: "wrong", message: "還沒有加入「幾個欄位相加」的檢查。到「新增檢查」設定後再測試。" };
  const same = rule.fields.length === v.fields.length && v.fields.every((id) => rule.fields.includes(id)) && rule.equals === v.equals;
  if (!same) {
    return { status: "wrong", message: `現在的檢查是 ${names(rule.fields)} = ${names([rule.equals])}。要相加的是 ${names(v.fields)}，要等於 ${names([v.equals])}。${labHint(state.guide.lab.data.hints, "x", "y")}` };
  }
  const field = result.fields.find((f) => f.id === v.equals);
  if (field && (field.reasons || []).includes(v.reason)) return { status: "ok", values: [labNorm(field.value)] };
  return { status: "stale", message: "檢查改過了，再按一次測試。" };
}
// 輸出設定：乾淨資料預覽的欄位（和實際輸出相同的規則）要依序等於預期
function labOutput(v) {
  const got = outputColumns(T().output?.fields, T().fields.map((f) => [f.id, f.name])).map((c) => c[1]);
  if (got.join("\n") === v.expect.join("\n")) return { status: "ok", values: got };
  // 找原因：多輸出了不要的欄、欄名不對、順序不對（欄名一樣只差順序）
  const extra = got.some((name) => name === "Internal Note");
  const sameSet = got.length === v.expect.length && v.expect.every((name) => got.includes(name));
  const why = extra ? "extra" : sameSet ? "order" : "name";
  const hint = (state.guide.lab.data.hints || []).find((h) => h.when === why)?.text || "";
  return { status: "wrong", message: `預覽的欄位是 ${got.join("、") || "（空的）"}，預期 ${v.expect.join("、")}。${hint}改好後再按一次測試。` };
}
// 解析 PDF：每份 PDF 用的範本要是它自己的
function labRunTemplates(v) {
  const run = state.run;
  if (!run?.finished || run.results.length < state.runDocs.length) return { status: "none" };
  const names = Object.fromEntries((state.guide.lab.templates || []).map((t) => [t.id, t.name]));
  for (let i = 0; i < state.runDocs.length; i += 1) {
    const result = run.results.find((r) => r.doc_id === state.runDocs[i].id);
    if (result?.template_id === v.expect[i]) continue;
    const used = names[result?.template_id] || "沒有範本";
    return { status: "wrong", message: `第 ${i + 1} 份（${state.runDocs[i].name}）用了「${used}」，預期「${names[v.expect[i]]}」。${labHint(state.guide.lab.data.hints, "x", "y")}` };
  }
  return { status: "ok", values: v.expect };
}
/* 用實際的試抓結果驗證：none 還沒試抓、stale 結果對不上現在的設定、wrong 有差異、ok 全對。
 * 比對前 \r\n 一律轉成 \n（Windows 與其他系統的換行不同）。 */
function labCheck() {
  const L = state.guide.lab;
  if (!L) return null;
  const v = L.data.verify;
  if (v.kind === "run_templates") return labRunTemplates(v);
  const docs = v.per_doc ? state.docs : state.docs.filter((d) => d.id === state.referenceId);
  const results = docs.map((d) => state.tests.find((r) => r.doc_id === d.id));
  if (!results.length || results.some((r) => !r)) return { status: "none" };
  if (v.kind === "field_flag") return labFieldFlag(v, results[0]);
  if (v.kind === "sum_check") return labSumCheck(v, results[0]);
  if (v.kind === "output") return labOutput(v);
  if (v.kind === "new_field") {
    const mine = labNewFields();
    if (!mine.length) return { status: "wrong", message: "還沒有你新增的欄位。用 P 在頁面右上角框住單號，再按測試。" };
    const field = results[0].fields.find((f) => f.id === mine[mine.length - 1].id);
    if (!field) return { status: "stale", message: "欄位改過了，再按一次測試。" };
    const message = labDiff([labNorm(field.value)], labList(v.expect), v, "", true);
    return message ? { status: "wrong", message } : { status: "ok", values: labList(v.expect) };
  }
  const expects = v.per_doc ? v.expect.map(labList) : [labList(v.expect)];
  for (let d = 0; d < results.length; d += 1) {
    const table = results[d].tables.find((t) => t.id === v.table);
    if (!table || !table.columns.some((c) => c.id === v.column)) {
      return { status: "stale", message: "這份結果和現在的設定對不上，再按一次測試。" };
    }
    const got = table.rows.map((row) => labNorm(row.cells[v.column]?.value));
    const who = v.per_doc ? `第 ${d + 1} 份（${docs[d].name}）` : "";
    const message = labDiff(got, expects[d], v, who, false);
    if (message) return { status: "wrong", message };
  }
  return { status: "ok", values: expects.flat() };
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
  const kind = state.guide.lab?.data.verify.kind;
  if (kind === "output") {  // 輸出設定的面板開著就直接在那裡改；關掉了才指回按鈕
    if (labWrong()) return state.outputPanel || !rightShowsList() ? null : { sel: "#outputBtn", label: "回去改輸出設定" };
    return state.selected ? null : { sel: "#testBtn", label: "按這裡試抓" };
  }
  if (kind === "sum_check" && labWrong()) return state.checksOpen || !rightShowsList() ? null : { sel: "#checksDetails > summary", label: "回去改檢查" };
  const back = state.guide.lab?.data.verify.kind === "field_flag" ? "first-child" : "last-child";  // 欄位排在清單最前面，表格最後面
  if (labWrong() && rightShowsList()) return { sel: `#right .items li:${back} button`, label: "回去改設定" };
  return state.selected ? null : { sel: "#testBtn", label: "按這裡試抓" };
}
function labVerifyStep(id, tip) {
  return {
    id, tab: "train", title: "試抓驗證", action: () => `按「用 ${state.docs.length} 份範例測試」，看結果對不對`,
    tip: () => labVerifyTip(tip), wrong: labWrong, target: labTestTarget, sticky: true, done: labVerified,
  };
}
// 數字檢查草稿勾了 Subtotal 和 Tax（或已加入檢查）
const labDraftFields = () => {
  const picked = state.checkDraft?.type === "sum_fields" ? state.checkDraft.fields || [] : [];
  return (picked.length === 2 && picked.includes("subtotal") && picked.includes("tax")) || T().validations.length > 0;
};
const labOutputList = () => outputList(T().output?.fields, T().fields.map((f) => [f.id, f.name]));
const labOutputEntry = (id) => labOutputList().find((e) => e.id === id);
const labOutputIndex = (id) => labOutputList().findIndex((e) => e.id === id);
const labPicked = () => (state.guide.lab?.templates || []).every((t) => state.templateIds.includes(t.id));
const LAB_PO_BOX = [0.64, 0.05, 0.82, 0.076];   // 練習 PDF 右上角的單號

const LAB_NEXT_BOX = [0.08, 0.22, 0.92, 0.6];     // 練習 PDF 第 2 頁的資料區
const LAB_HEADER_BOX = [0.085, 0.165, 0.17, 0.195];  // 出貨單表頭的「Line」
const LAB_END_BOX = [0.2, 0.5, 0.29, 0.54];       // 訂單明細表尾的「Total」
const labRegionCount = () => firstTable()?.regions.length || 0;
// 表格「位置」分頁裡的按鈕：還沒選表格就先指到表格，分頁不對就指到分頁
function labPlaceTarget(sel, label) {
  if (state.selected?.type !== "table") return { sel: "#right .items li:last-child button", label: "點表格" };
  if (state.tableTab !== "place") return { sel: '#right .subtabs [data-tab="place"]', label: "點「位置」" };
  return { sel, label };
}
const labPlaceStep = (id) => ({
  id, tab: "train", title: "切到「位置」分頁",
  action: "點表格，切到「位置」分頁", tip: "每一頁的資料範圍、表頭與表尾都在「位置」。",
  setup: labSelectTable,
  target: () => (state.selected?.type === "table" && state.tableTab === "place" ? null : labPlaceTarget()),
  sticky: true, done: () => state.selected?.type === "table" && state.tableTab === "place",
});

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
  "format-check": [
    {
      id: "lab-format-check-1", tab: "train", title: "打開 Tax ID 欄位",
      action: "點右邊清單的「Tax ID」", tip: "這個統一編號只有 7 碼，是故意少一碼的。",
      target: () => (state.selected?.type === "field" ? null : { sel: "#right .items li:first-child button", label: "點 Tax ID" }),
      sticky: true, done: () => state.selected?.type === "field" && state.selected.id === "tax_id",
    },
    {
      id: "lab-format-check-2", tab: "train", title: "展開進階設定",
      action: "展開「進階設定」", tip: "格式檢查在進階設定裡。",
      target: () => (state.selected?.type === "field" ? { sel: "#fieldAdvanced > summary", label: "點「進階設定」" } : { sel: "#right .items li:first-child button", label: "點 Tax ID" }),
      sticky: true, done: () => state.selected?.type === "field" && !!state.fieldAdvancedOpen,
    },
    {
      id: "lab-format-check-3", tab: "train", title: "填格式檢查",
      action: "「格式檢查」填 ^\\d{8}$", tip: "規則前後的 ^ 和 $ 代表整格都要符合；\\d{8} 是 8 個數字。",
      target: () => (document.querySelector("#fieldPatternInput") && state.selected?.type === "field"
        ? { sel: "#fieldPatternInput", label: "填 ^\\d{8}$" } : { sel: "#right .items li:first-child button", label: "點 Tax ID" }),
      assist: () => ({
        label: "幫我填",
        run: () => {
          const field = T().fields.find((f) => f.id === "tax_id");
          if (!field) return;
          snapshot();
          field.pattern = String.raw`^\d{8}$`;
          Object.assign(state, { selected: { type: "field", id: field.id }, fieldAdvancedOpen: true });
          renderRight();
        },
      }),
      sticky: true, done: () => !!(T().fields.find((f) => f.id === "tax_id")?.pattern || "").trim(),
    },
    labVerifyStep("lab-format-check-4", "不符合規則的值會被標記，結果列在下面。"),
  ],
  "cross-page": [
    labPlaceStep("lab-cross-page-1"),
    {
      id: "lab-cross-page-2", tab: "train", title: "翻到第 2 頁",
      action: "翻到第 2 頁", tip: "明細接到了第 2 頁，範圍要加在那一頁。",
      target: () => (state.page >= 1 ? null : { sel: '#toolbar button[aria-label="下一頁"]', label: "翻到第 2 頁" }),
      sticky: true, done: () => state.page >= 1,
    },
    {
      id: "lab-cross-page-3", tab: "train", title: "在第 2 頁加範圍",
      action: "按「在目前這一頁加範圍」，框住第 2 頁的資料區", tip: "只框表頭下面的資料，套用頁面維持「第 2 頁起」。",
      ghost: () => (labRegionCount() > 1 ? [] : [{ page: 1, box: LAB_NEXT_BOX, label: "框住第 2 頁的資料區" }]),
      target: () => (state.tool === "region" ? null : labPlaceTarget("#addRegionBtn", "按這裡，再框資料區")),
      sticky: true, done: () => labRegionCount() > 1,
    },
    labVerifyStep("lab-cross-page-4", "7 列都該抓到，包含第 2 頁的 3 列。"),
  ],
  header: [
    labPlaceStep("lab-header-1"),
    {
      id: "lab-header-2", tab: "train", title: "框選表頭",
      action: "按「框選表頭」，框住表頭的「Line」", tip: "乙的表格比甲低；表頭每份都一樣，用它定位。",
      ghost: () => (firstTable()?.regions[0]?.header ? [] : [{ page: 0, box: LAB_HEADER_BOX, label: "框住表頭「Line」" }]),
      target: () => (state.tool === "header" ? null : labPlaceTarget("#right .header-pick", "按這裡，再框表頭")),
      sticky: true, done: () => !!firstTable()?.regions[0]?.header,
    },
    labVerifyStep("lab-header-3", "兩份的明細都要抓完整，結果分兩份列在下面。"),
  ],
  "sum-fields": [
    {
      id: "lab-sum-fields-1", tab: "train", title: "展開「新增檢查」",
      action: "點「新增檢查」展開", tip: "Subtotal 加 Tax 應該等於 Total，這份單據的 Total 是故意寫錯的。",
      setup: () => { state.selected = null; state.outputPanel = false; renderRight(); renderOverlay(); },
      target: () => (!rightShowsList() ? { sel: "#rightBackBtn", label: "回到欄位清單" } : state.checksOpen ? null : { sel: "#checksDetails > summary", label: "點這裡展開" }),
      sticky: true, done: () => !!state.checksOpen,
    },
    {
      id: "lab-sum-fields-2", tab: "train", title: "勾選要相加的欄位",
      action: "「檢查方式」維持「幾個欄位相加」，勾 Subtotal 和 Tax", tip: "只勾要加起來的兩個，Total 是要比對的對象。",
      target: () => (state.checksOpen ? { sel: "#checkFields", label: "勾 Subtotal 和 Tax" } : { sel: "#checksDetails > summary", label: "點這裡展開" }),
      assist: () => ({
        label: "幫我勾",
        run: () => {
          state.checksOpen = true;
          state.checkDraft = { ...(state.checkDraft || {}), type: "sum_fields", fields: ["subtotal", "tax"] };
          renderRight();
        },
      }),
      sticky: true, done: () => labDraftFields(),
    },
    {
      id: "lab-sum-fields-3", tab: "train", title: "選要等於哪一欄",
      action: "「要等於」選 Total", tip: "加起來的結果要和單據上的 Total 比。",
      target: () => (state.checksOpen ? { sel: "#checkTargetSelect", label: "選 Total" } : { sel: "#checksDetails > summary", label: "點這裡展開" }),
      assist: () => ({
        label: "幫我選",
        run: () => {
          state.checksOpen = true;
          state.checkDraft = { ...(state.checkDraft || { type: "sum_fields", fields: [] }), target: "total" };
          renderRight();
        },
      }),
      sticky: true, done: () => state.checkDraft?.target === "total" || T().validations.length > 0,
    },
    {
      id: "lab-sum-fields-4", tab: "train", title: "加入檢查",
      action: "按「加入檢查」", tip: "加入後下面會列出這條檢查。",
      target: () => (state.checksOpen ? { sel: "#checkAddBtn", label: "按加入檢查" } : { sel: "#checksDetails > summary", label: "點這裡展開" }),
      sticky: true, done: () => T().validations.length > 0,
    },
    labVerifyStep("lab-sum-fields-5", "加總對不上的 Total 會被標記，結果列在下面。"),
  ],
  output: [
    {
      id: "lab-output-1", tab: "train", title: "打開輸出設定",
      action: "按「設定輸出欄位」", tip: "輸出設定只影響乾淨資料，檢查用 Excel 維持完整。",
      setup: () => { state.selected = null; state.outputPanel = false; renderRight(); renderOverlay(); },
      target: () => (state.outputPanel ? null : { sel: "#outputBtn", label: "按這裡" }),
      sticky: true, done: () => !!state.outputPanel,
    },
    {
      id: "lab-output-2", tab: "train", title: "取消不需要的欄位",
      action: "取消勾選 Internal Note", tip: "內部備註不用交給後續流程。",
      target: () => (state.outputPanel ? { sel: 'input[aria-label="輸出 Internal Note"]', label: "取消勾選" } : { sel: "#outputBtn", label: "按這裡" }),
      sticky: true, done: () => labOutputEntry("note")?.include === false,
    },
    {
      id: "lab-output-3", tab: "train", title: "改輸出欄名",
      action: "Invoice No 的輸出欄名填 Doc No", tip: "欄名留空就用原本的名稱。",
      target: () => (state.outputPanel ? { sel: 'input[aria-label="Invoice No 的輸出欄名"]', label: "填 Doc No" } : { sel: "#outputBtn", label: "按這裡" }),
      sticky: true, done: () => !!(labOutputEntry("invoice_no")?.name || "").trim(),
    },
    {
      id: "lab-output-4", tab: "train", title: "調整順序",
      action: "用箭頭把 Amount 移到 Customer 前面", tip: "按 Amount 旁的 ↑。",
      target: () => (state.outputPanel ? { sel: 'button[aria-label="Amount 上移"]', label: "按 ↑" } : { sel: "#outputBtn", label: "按這裡" }),
      sticky: true, done: () => labOutputIndex("amount") < labOutputIndex("customer"),
    },
    labVerifyStep("lab-output-5", "按測試後，面板下方的預覽就是乾淨資料的欄位。"),
  ],
  "multi-template": [
    {
      id: "lab-multi-template-1", tab: "run", title: "勾選兩個範本",
      action: "把「練習範本：發票」和「練習範本：裝箱單」都勾起來", tip: "左邊兩份 PDF 的版面不一樣，各有一個範本。",
      target: () => (labPicked() ? null : { sel: "#left .template-picks input:not(:checked)", label: "勾起來" }),
      sticky: true, done: labPicked,
    },
    {
      id: "lab-multi-template-2", tab: "run", title: "開始解析",
      action: "按「開始解析」", tip: "每份 PDF 會比對定位點，自動用最符合的範本。",
      target: () => (state.run ? null : { sel: "#runStartBtn", label: "按這裡" }),
      sticky: true, done: () => !!state.run?.finished,
    },
    {
      id: "lab-multi-template-3", tab: "run", title: "看每份用了哪個範本",
      action: "看左邊每份 PDF 用的範本",
      wrong: labWrong, tip: () => labVerifyTip("每份 PDF 下面會寫它用的範本。"),
      target: () => (labWrong() ? { sel: labPicked() ? "#runStartBtn" : "#left .template-picks input:not(:checked)", label: labPicked() ? "再按一次開始解析" : "勾起來" } : null),
      sticky: true, done: labVerified,
    },
  ],
  endmark: [
    labPlaceStep("lab-endmark-1"),
    {
      id: "lab-endmark-2", tab: "train", title: "框選表尾",
      action: "按「框選表尾」，框住「Total」", tip: "表格結束後緊接著的字，抓到那裡為止。",
      ghost: () => (firstTable()?.end_marker ? [] : [{ page: 0, box: LAB_END_BOX, label: "框住「Total」" }]),
      target: () => (state.tool === "endmark" ? null : labPlaceTarget("#right .endmark-pick", "按這裡，再框表尾")),
      sticky: true, done: () => !!firstTable()?.end_marker,
    },
    labVerifyStep("lab-endmark-3", "Total 那一列不該算進明細，只剩 5 列。"),
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
    key: ["done", lab.id, shown, lab.data.verify.done || ""],
    nodes: [
      h("span", { class: "mission-badge done", "aria-hidden": "true" }, "✓"),
      h("div", { class: "mission-text" },
        h("p", { class: "mission-action", id: "labResult" }, `✓ ${lab.data.verify.done || `抓到 ${shown}`}`),
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
  const run = labViewOf(id) === "run";
  const busy = !state.guide.lab && (run ? state.runDocs.length > 0 : state.docs.length > 0 || hasUnsavedTemplate());
  if (!busy) { startLab(id); return; }
  const card = $("coachCard");
  if (typeof closeSpotlight === "function") closeSpotlight(false);
  showFloatCard(card, trigger, [
    h("h2", {}, "要開始實地練習嗎？"),
    h("p", {}, run ? "練習會暫時換成練習用的 PDF 與範本。按「回到我的工作」後，目前的檔案與解析結果會原樣接回來。"
      : "練習會暫時換成練習用的 PDF 與範本。按「回到我的工作」後，目前的檔案與範本（含還沒儲存的修改）會原樣接回來。"),
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
    if (previous) for (const doc of labDocs()) await api(`/api/docs/${doc.id}`, { method: "DELETE" }).catch(() => null);
    const stash = previous ? previous.stash : labStash();
    const view = labViewOf(id);
    if (state.view !== view) setView(view);
    const first = data.docs[0];
    if (view === "run") {
      // 解析 PDF 的練習：練習用的 PDF 放在解析分頁的清單，範本選單換成練習範本（不寫入 workspace）
      Object.assign(state, {
        runDocs: data.docs, run: null, templateIds: [], docId: first.id, page: 0, zoom: 1, selected: null,
        focusRef: null, drawerOpen: false,
      });
    } else {
      Object.assign(state, {
        template: { ...blankTemplate(), ...data.template }, savedTemplate: null, savedId: null, undo: [],
        docs: data.docs, referenceId: first.id, docId: first.id, page: 0, zoom: 1, tests: [],
        tool: "select", pending: null, selected: null, read: null, checkDraft: null, drawerOpen: false,
        outputPanel: false, columnPreview: null, showcase: false, openColumn: null, tableTab: "columns",
        fieldAdvancedOpen: false, checksOpen: false, recovery: null, focusRef: null,
      });
      state.savedTemplate = comparable(T());  // 練習範本一開始不算「未儲存」
    }
    g.lab = { id, data: data.lab, stash, flags: {}, baseFieldIds: T().fields.map((f) => f.id), okValues: null, templates: data.templates || null };
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
  for (const doc of labDocs()) await api(`/api/docs/${doc.id}`, { method: "DELETE" }).catch(() => null);
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
