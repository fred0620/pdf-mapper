"use strict";
/* PDF 解析器前端。沒有外部相依，全部資料只在本機。 */

const $ = (id) => document.getElementById(id);
function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key in node && key !== "list") node[key] = value;
    else if (value !== undefined && value !== null && value !== false) node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child);
  }
  return node;
}
const fill = (node, ...items) => node.replaceChildren(
  ...items.flat(Infinity).filter((item) => item !== null && item !== undefined && item !== false));
const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const round5 = (v) => Math.round(v * 1e5) / 1e5;
const SOURCE = { text: "文字層", ocr: "影像辨識", manual: "人工", "": "" };
const TYPE_OPTIONS = [["text", "文字"], ["number", "數字"], ["date", "日期"]];
const TOOLS = [
  ["select", "選取", "V"], ["kv", "有標題的欄位", "K"], ["pos", "只有值的欄位", "P"],
  ["table", "表格", "T"], ["anchor", "定位點", "A"],
];

const blankTemplate = () => ({
  schema_version: 1, template_id: "", name: "", fields: [], tables: [], anchors: [], validations: [],
});

const state = {
  view: "train",
  reasons: {},
  ocr: true,
  docs: [],            // 建立範本時的範例
  runDocs: [],         // 要解析的 PDF
  referenceId: null,
  docId: null,
  page: 0,
  zoom: 1,
  tool: "select",
  pending: null,       // 正在標注中的半成品
  selected: null,      // {type: field|table|anchor, id}
  template: blankTemplate(),
  undo: [],
  savedTemplate: null, // 上次儲存時的內容，用來判斷有沒有未儲存的修改
  savedId: null,
  tests: [],           // 範例測試結果
  testing: false,
  read: null,          // 選取欄位的即時預覽
  templates: [],
  templateIds: [],     // 解析時選用的範本
  run: null,           // {id, total, done, current, results, finished}
  focusRef: null,
  showAllValues: false,
  drawerOpen: false,
  recovery: null,      // 上次關閉時未儲存的範本，等使用者決定要不要接著做
};

/* ---------- 伺服器 ---------- */
async function api(path, options = {}) {
  const init = { ...options };
  if (options.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(options.json);
    delete init.json;
  }
  const response = await fetch(path, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "伺服器沒有回應，請確認啟動視窗還開著");
  return data;
}
let toastTimer;
function toast(message, bad = false) {
  const node = $("toast");
  node.textContent = message;
  node.hidden = false;
  node.className = bad ? "toast bad" : "toast";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, bad ? 7000 : 3000);
}
const guard = (fn) => async (...args) => {
  try { return await fn(...args); } catch (error) { toast(error.message, true); }
};

/* ---------- 範本操作 ---------- */
const T = () => state.template;
const nextId = (prefix, list) => {
  let n = list.length + 1;
  while (list.some((item) => item.id === `${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
};
const defaultRule = () => (state.page === 0 ? "first" : "rest");
const cleanName = (text) => text.replace(/[(（]\s*\d+\s*[)）]/g, "").replace(/\s+/g, "").trim();
const currentDoc = () => {
  const list = state.view === "train" ? state.docs : state.runDocs;
  return list.find((d) => d.id === state.docId) || null;
};
const isReference = () => state.view === "train" && state.docId === state.referenceId;
function snapshot() {
  state.undo.push(JSON.stringify(state.template));
  if (state.undo.length > 40) state.undo.shift();
  saveDraft();
}
function undo() {
  const last = state.undo.pop();
  if (!last) return;
  state.template = JSON.parse(last);
  state.selected = null;
  renderAll();
}
// 草稿只為了意外關閉時救回未儲存的修改。已儲存或空白的範本不保留，
// 也不自動套用：重開時先詢問，避免上一次的名稱和框線留在新範本裡。
const DRAFT_KEY = "pdfmapper.draft";
function saveDraft() {
  state.recovery = null;
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ template: state.template, saved: state.savedTemplate }));
  } catch (_e) { /* 非必要 */ }
}
function dropDraft() {
  state.recovery = null;
  try { localStorage.removeItem(DRAFT_KEY); } catch (_e) { /* 非必要 */ }
}
function loadDraft() {
  try {
    const data = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
    if (!data) return;
    // 0.2.1 以前直接存範本本身
    const template = { ...blankTemplate(), ...(data.template || data) };
    const saved = data.template ? data.saved : null;
    const empty = !template.name && !template.fields.length && !template.tables.length
      && !template.anchors.length && !template.validations.length;
    if (empty || comparable(template) === saved) dropDraft();
    else state.recovery = { template, saved };
  } catch (_e) { dropDraft(); }
}
function resumeDraft() {
  const draft = state.recovery;
  if (!draft) { renderLeft(); return; }
  state.template = draft.template;
  state.savedTemplate = draft.saved;
  state.savedId = draft.saved ? draft.template.template_id : null;
  state.undo = [];
  state.selected = null;
  saveDraft();
  renderAll();
  toast(state.docs.length ? "已接著上次的範本" : "已接著上次的範本，請加入基準範例 PDF 才能看到框線");
}
function recoveryNotice() {
  const draft = state.recovery;
  if (!draft) return null;
  const name = draft.template.name ? `「${draft.template.name}」` : "";
  return h("div", { class: "recovery" },
    h("p", {}, `上次有未儲存的範本${name}，要接著做嗎？`),
    h("div", { class: "list-actions" },
      h("button", { class: "linkish", onclick: resumeDraft }, "接著做"),
      h("button", { class: "linkish", onclick: () => { dropDraft(); renderLeft(); } }, "捨棄")));
}
function selectedItem() {
  const sel = state.selected;
  if (!sel) return null;
  const list = { field: T().fields, table: T().tables, anchor: T().anchors }[sel.type];
  return list.find((item) => item.id === sel.id) || null;
}
const orderedItems = () => [
  ...T().fields.map((item) => ({ type: "field", item })),
  ...T().tables.map((item) => ({ type: "table", item })),
];
const numberOf = (id) => orderedItems().findIndex((e) => e.item.id === id) + 1;

async function readBox(box) {
  return api(`/api/docs/${state.docId}/read`, { json: { page: state.page, box } });
}

const onBox = guard(async (box) => {
  const tool = state.tool;
  if (tool === "kv") {
    if (!state.pending) {
      const read = await readBox(box);
      state.pending = { label: { text: cleanName(read.text), box } };
      renderHint(); renderOverlay();
      return;
    }
    snapshot();
    const field = {
      id: nextId("f", T().fields), name: state.pending.label.text || `欄位${T().fields.length + 1}`,
      kind: "key_value", page_rule: defaultRule(), ref_page: state.page,
      label: state.pending.label, value_box: box, type: "text", required: true,
    };
    T().fields.push(field);
    state.pending = null;
    selectItem("field", field.id);
    return;
  }
  if (tool === "pos") {
    snapshot();
    const field = {
      id: nextId("f", T().fields), name: `欄位${T().fields.length + 1}`, kind: "position",
      page_rule: defaultRule(), ref_page: state.page, value_box: box, type: "text", required: true,
    };
    T().fields.push(field);
    selectItem("field", field.id, true);
    return;
  }
  if (tool === "table") {
    snapshot();
    const table = {
      id: nextId("t", T().tables), name: `表格${T().tables.length + 1}`,
      columns: [{ id: "c1", name: "欄1", band: 0 }], key_column: null, key_position: "auto", required: true,
      regions: [{ page_rule: defaultRule(), ref_page: state.page, box, dividers: [box[0], box[2]] }],
    };
    T().tables.push(table);
    setTool("select");
    selectItem("table", table.id, true);
    return;
  }
  if (tool === "region") {
    const table = selectedItem();
    snapshot();
    const base = table.regions[0];
    const ratio = (x) => (x - base.box[0]) / (base.box[2] - base.box[0]);
    table.regions.push({
      page_rule: defaultRule(), ref_page: state.page, box,
      dividers: base.dividers.map((x) => round5(box[0] + ratio(x) * (box[2] - box[0]))),
    });
    setTool("select");
    renderAll();
    return;
  }
  if (tool === "continuation") {
    const field = selectedItem();
    snapshot();
    field.continuation = { box, ref_page: state.page };
    state.continuing = null;
    setTool("select");
    renderAll();
    return;
  }
  if (tool === "header") {
    const read = await readBox(box);
    const table = selectedItem();
    snapshot();
    table.regions[state.markerRegion].header = { text: cleanName(read.text), box };
    setTool("select");
    renderAll();
    return;
  }
  if (tool === "endmark") {
    const read = await readBox(box);
    const table = selectedItem();
    snapshot();
    table.end_marker = { text: cleanName(read.text), box, ref_page: state.page };
    setTool("select");
    renderAll();
    return;
  }
  if (tool === "anchor") {
    const read = await readBox(box);
    snapshot();
    const anchor = {
      id: nextId("a", T().anchors), text: cleanName(read.text), box,
      page_rule: defaultRule(), ref_page: state.page,
    };
    T().anchors.push(anchor);
    selectItem("anchor", anchor.id);
  }
});

function selectItem(type, id, focusName = false) {
  state.selected = { type, id };
  state.outputPanel = false;
  state.read = null;
  renderAll();
  refreshRead();
  if (focusName) setTimeout(() => $("itemName")?.select(), 0);
}
const refreshRead = guard(async () => {
  const item = selectedItem();
  if (!item || state.selected.type !== "field" || !isReference()) return;
  if (item.ref_page !== state.page) return;
  const id = item.id;
  const read = await readBox(item.value_box);
  if (selectedItem()?.id === id) { state.read = read; renderRight(); }
});
function deleteSelected() {
  const item = selectedItem();
  if (!item) return;
  snapshot();
  const key = { field: "fields", table: "tables", anchor: "anchors" }[state.selected.type];
  T()[key] = T()[key].filter((entry) => entry !== item);
  state.selected = null;
  renderAll();
}
function setTool(tool) {
  if (state.tool === "continuation" && tool !== "continuation") state.continuing = null;
  state.tool = tool;
  state.pending = null;
  renderToolbar(); renderHint(); renderOverlay();
}

/* 表格的分隔線：所有範圍同步增減 */
function addDivider(table, region, x) {
  snapshot();
  const fraction = (x - region.box[0]) / (region.box[2] - region.box[0]);
  const index = region.dividers.findIndex((v) => v > x);
  for (const r of table.regions) {
    const value = round5(r === region ? x : r.box[0] + fraction * (r.box[2] - r.box[0]));
    r.dividers.splice(index, 0, value);
  }
  for (const column of table.columns) if (column.band >= index) column.band += 1;
  table.columns.push({ id: nextId("c", table.columns), name: `欄${table.columns.length + 1}`, band: index });
  table.columns.sort((a, b) => a.band - b.band);
  renderAll();
}
function removeDivider(table, index) {
  snapshot();
  for (const r of table.regions) r.dividers.splice(index, 1);
  table.columns = table.columns.filter((c) => c.band !== index);
  for (const column of table.columns) if (column.band > index) column.band -= 1;
  if (!table.columns.some((c) => c.id === table.key_column)) table.key_column = null;
  renderAll();
}

/* ---------- 頁面繪製 ---------- */
function eventPoint(event) {
  const rect = $("overlay").getBoundingClientRect();
  return [clamp((event.clientX - rect.left) / rect.width), clamp((event.clientY - rect.top) / rect.height)];
}
function pctStyle(node, box) {
  node.style.left = `${box[0] * 100}%`;
  node.style.top = `${box[1] * 100}%`;
  node.style.width = `${(box[2] - box[0]) * 100}%`;
  node.style.height = `${(box[3] - box[1]) * 100}%`;
}
function dragHandler(onMove, onEnd) {
  return (event) => {
    event.stopPropagation();
    event.preventDefault();
    const start = eventPoint(event);
    let moved = false;
    const move = (e) => { moved = true; onMove(eventPoint(e), start); };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      onEnd?.(moved);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
}
function editableBox(node, getBox, setBox, afterEdit) {
  const finish = (moved) => { if (moved) { saveDraft(); afterEdit?.(); } };
  let origin = null;
  const begin = () => { snapshot(); origin = [...getBox()]; };
  node.addEventListener("pointerdown", (event) => {
    if (state.tool !== "select") return;
    begin();
    dragHandler(([x, y], [sx, sy]) => {
      const dx = clamp(x - sx, -origin[0], 1 - origin[2]);
      const dy = clamp(y - sy, -origin[1], 1 - origin[3]);
      setBox([origin[0] + dx, origin[1] + dy, origin[2] + dx, origin[3] + dy].map(round5));
      pctStyle(node, getBox());
    }, finish)(event);
  });
  for (const corner of ["nw", "ne", "sw", "se"]) {
    const handle = h("span", { class: `handle ${corner}` });
    handle.addEventListener("pointerdown", (event) => {
      begin();
      dragHandler(([x, y]) => {
        const box = [...origin];
        if (corner.includes("w")) box[0] = Math.min(x, box[2] - 0.004);
        if (corner.includes("e")) box[2] = Math.max(x, box[0] + 0.004);
        if (corner.includes("n")) box[1] = Math.min(y, box[3] - 0.004);
        if (corner.includes("s")) box[3] = Math.max(y, box[1] + 0.004);
        setBox(box.map(round5));
        pctStyle(node, getBox());
      }, finish)(event);
    });
    node.append(handle);
  }
}
function markBox(box, classes, tag, onClick) {
  const node = h("div", { class: `box ${classes}` }, tag ? h("span", { class: "tag" }, tag) : null);
  pctStyle(node, box);
  if (onClick) node.addEventListener("pointerdown", onClick);
  return node;
}
function renderDefinitions(layer) {
  const page = state.page;
  const selected = state.selected;
  for (const field of T().fields) {
    if (field.ref_page !== page) continue;
    const active = selected?.type === "field" && selected.id === field.id;
    const pick = () => { if (state.tool === "select" && !active) selectItem("field", field.id); };
    if (field.label) {
      const node = markBox(field.label.box, `label${active ? " selected" : ""}`, "", pick);
      if (active) {
        editableBox(node, () => field.label.box, (b) => {
          field.label.box = b; delete field.label.patch; delete field.label.text_center;
        });
      }
      layer.append(node);
    }
    const node = markBox(field.value_box, active ? "selected" : "", `(${numberOf(field.id)}) ${field.name}`, pick);
    if (active) editableBox(node, () => field.value_box, (b) => { field.value_box = b; }, refreshRead);
    layer.append(node);
  }
  for (const field of T().fields) {
    if (field.continuation?.ref_page !== page) continue;
    const active = selected?.type === "field" && selected.id === field.id;
    const node = markBox(field.continuation.box, active ? "selected" : "", `(${numberOf(field.id)}) ${field.name} 接續`,
      () => { if (state.tool === "select" && !active) selectItem("field", field.id); });
    if (active) editableBox(node, () => field.continuation.box, (b) => { field.continuation.box = b; });
    layer.append(node);
  }
  for (const anchor of T().anchors) {
    if (anchor.ref_page !== page) continue;
    const active = selected?.type === "anchor" && selected.id === anchor.id;
    const node = markBox(anchor.box, `anchor${active ? " selected" : ""}`, active ? "定位點" : "",
      () => { if (state.tool === "select" && !active) selectItem("anchor", anchor.id); });
    if (active) editableBox(node, () => anchor.box, (b) => { anchor.box = b; delete anchor.patch; delete anchor.text_center; });
    layer.append(node);
  }
  for (const table of T().tables) {
    for (const region of table.regions) {
      if (region.ref_page !== page) continue;
      layer.append(tableBox(table, region));
    }
    // 表頭和表尾要畫在表格之後，才點得到
    const active = selected?.type === "table" && selected.id === table.id;
    const markers = table.regions.filter((r) => r.header && r.ref_page === page).map((r) => [r.header, "表頭"]);
    if (table.end_marker && table.end_marker.ref_page === page) markers.push([table.end_marker, "表尾"]);
    for (const [marker, name] of markers) {
      const node = markBox(marker.box, `anchor marker${active ? " selected" : ""}`, name,
        () => { if (state.tool === "select" && !active) selectItem("table", table.id); });
      if (active) editableBox(node, () => marker.box, (b) => { marker.box = b; delete marker.patch; delete marker.text_center; });
      layer.append(node);
    }
  }
}
function tableBox(table, region) {
  const active = state.selected?.type === "table" && state.selected.id === table.id;
  const node = markBox(region.box, `table${active ? " selected" : ""}`, `(${numberOf(table.id)}) ${table.name}`);
  const width = region.box[2] - region.box[0];
  node.addEventListener("pointerdown", (event) => {
    if (state.tool !== "select") return;
    if (!active) { selectItem("table", table.id); return; }
    const [x] = eventPoint(event);
    const near = region.dividers.some((d) => Math.abs(d - x) < 0.006);
    if (!near) addDivider(table, region, round5(x));
  });
  for (let band = 0; band < region.dividers.length - 1; band += 1) {
    const names = table.columns.filter((c) => c.band === band).map((c) => c.name).join("、");
    const left = (region.dividers[band] - region.box[0]) / width * 100;
    const span = (region.dividers[band + 1] - region.dividers[band]) / width * 100;
    node.append(h("span", { class: "band-name", style: `left:${left}%;max-width:${span}%` }, names));
  }
  if (active) {
    region.dividers.forEach((value, index) => {
      if (index === 0 || index === region.dividers.length - 1) return;
      const bar = h("span", { class: "divider", title: "拖曳移動，雙擊刪除", style: `left:${(value - region.box[0]) / width * 100}%` });
      bar.addEventListener("pointerdown", (event) => {
        snapshot();
        dragHandler(([x]) => {
          const lo = region.dividers[index - 1] + 0.004;
          const hi = region.dividers[index + 1] - 0.004;
          region.dividers[index] = round5(clamp(x, lo, hi));
          bar.style.left = `${(region.dividers[index] - region.box[0]) / width * 100}%`;
        }, (moved) => { if (moved) renderOverlay(); })(event);
      });
      bar.addEventListener("dblclick", (event) => { event.stopPropagation(); removeDivider(table, index); });
      node.append(bar);
    });
    editableBox(node, () => region.box, (b) => {
      const scale = (b[2] - b[0]) / (region.box[2] - region.box[0]);
      region.dividers = region.dividers.map((d) => round5(b[0] + (d - region.box[0]) * scale));
      region.box = b;
    });
  }
  return node;
}
function activeResult() {
  if (state.view === "run") return state.run?.results.find((r) => r.doc_id === state.docId) || null;
  if (isReference() && !state.tests.length) return null;
  return state.tests.find((r) => r.doc_id === state.docId) || null;
}
function allValues(result) {
  const out = [];
  for (const field of result.fields) out.push({ ref: `f:${field.id}`, name: field.name, value: field });
  for (const table of result.tables) {
    table.rows.forEach((row, r) => {
      for (const column of table.columns) {
        const cell = row.cells[column.id];
        if (cell) out.push({ ref: `t:${table.id}:${r}:${column.id}`, name: `${table.name} 第 ${r + 1} 列 ${column.name}`, value: cell });
      }
    });
  }
  return out;
}
function renderResultBoxes(layer, result) {
  for (const entry of allValues(result)) {
    const { value, ref } = entry;
    if (!value.box || (value.status === "ok" && !value.value)) continue;
    const status = ["review", "missing"].includes(value.status) ? value.status : "ok";
    const places = [{ page: value.page, box: value.box }, ...(value.extra_boxes || [])];
    for (const place of places.filter((p) => p.page === state.page + 1)) {
      const node = markBox(place.box, `${status}${state.focusRef === ref ? " focus" : ""}`, "",
        () => focusValue(ref));
      node.title = `${entry.name}：${value.value || "（空白）"}`;
      layer.append(node);
    }
  }
}
function renderOverlay() {
  const layer = $("overlay");
  layer.replaceChildren();
  const editing = state.view === "train" && isReference();
  layer.className = `overlay${editing && state.tool !== "select" ? " drawing" : ""}`;
  if (state.pending?.label) layer.append(markBox(state.pending.label.box, "label selected"));
  if (editing) renderDefinitions(layer);
  const result = activeResult();
  if (result && (!editing || state.tool === "select" && !state.selected)) renderResultBoxes(layer, result);
}
function startDraw(event) {
  document.activeElement?.blur?.();
  if (state.view !== "train" || !isReference() || state.tool === "select") {
    if (state.tool === "select" && state.selected && event.target === $("overlay")) {
      state.selected = null; state.read = null; renderAll();
    }
    return;
  }
  const [sx, sy] = eventPoint(event);
  const rubber = h("div", { class: "rubber" });
  $("overlay").append(rubber);
  let box = [sx, sy, sx, sy];
  dragHandler(([x, y]) => {
    box = [Math.min(sx, x), Math.min(sy, y), Math.max(sx, x), Math.max(sy, y)];
    pctStyle(rubber, box);
  }, () => {
    rubber.remove();
    if (box[2] - box[0] < 0.006 || box[3] - box[1] < 0.004) return;
    onBox(box.map(round5));
  })(event);
}
function renderPage() {
  const doc = currentDoc();
  $("sheet").hidden = !doc;
  $("empty").hidden = !!doc;
  if (!doc) { renderEmpty(); return; }
  const url = `/api/docs/${doc.id}/page/${state.page}.png?dpi=150`;
  if ($("pageImage").getAttribute("src") !== url) $("pageImage").src = url;
  const [w, h_] = doc.sizes[state.page];
  const available = $("stage").clientWidth - 36;
  const fit = Math.min(available, ($("stage").clientHeight - 36) * (w / h_) * 1.6);
  $("sheet").style.width = `${Math.max(320, fit) * state.zoom}px`;
  renderOverlay();
}
function renderEmpty() {
  const train = state.view === "train";
  fill($("empty"), h("div", {},
    h("strong", {}, train ? "把範例 PDF 拖到這裡" : "把要解析的 PDF 拖到這裡"),
    train ? "第一份會成為基準範例，你在它上面標注；其他範例用來測試。" : "可以一次放多份。",
    h("br"),
    h("button", { class: "btn", onclick: () => $("filePicker").click() }, "選擇檔案")));
}

/* ---------- 工具列與提示 ---------- */
function setPage(index) {
  const doc = currentDoc();
  if (!doc) return;
  state.page = clamp(index, 0, doc.pages - 1);
  state.pending = null;
  renderToolbar(); renderHint(); renderPage(); renderLeft();
}
function renderToolbar() {
  const doc = currentDoc();
  const editing = isReference();
  const tools = state.view === "train" ? TOOLS.map(([id, label, key]) => h("button", {
    class: "tool", "aria-pressed": String(state.tool === id), disabled: !editing,
    onclick: () => setTool(id),
  }, label, h("kbd", {}, key))) : [];
  fill($("toolbar"), ...tools, h("span", { class: "spring" }),
    doc ? h("span", { class: "pager" },
      h("button", { disabled: state.page === 0, "aria-label": "上一頁", onclick: () => setPage(state.page - 1) }, "‹"),
      ` 第 ${state.page + 1} / ${doc.pages} 頁 `,
      h("button", { disabled: state.page >= doc.pages - 1, "aria-label": "下一頁", onclick: () => setPage(state.page + 1) }, "›"),
      h("button", { "aria-label": "縮小", onclick: () => zoomBy(0.85) }, "−"),
      h("button", { "aria-label": "放大", onclick: () => zoomBy(1.18) }, "+")) : "");
}
function zoomBy(factor) { state.zoom = clamp(state.zoom * factor, 0.5, 4); renderPage(); }
function renderHint() {
  let text = "";
  if (state.view === "train" && currentDoc()) {
    if (!isReference()) text = "這份是測試範例。切回基準範例才能標注。";
    else if (state.tool === "kv") text = state.pending
      ? `已記下「${state.pending.label.text || "標題"}」。再框住它的數值範圍，框大一點沒關係。按 Esc 取消。`
      : "先框住欄位名稱，例如「報單號碼」。";
    else if (state.tool === "pos") text = "框住數值的範圍。這類欄位沒有標題，靠定位點找位置。";
    else if (state.tool === "table") text = "框住表格的資料區，不含標題列。";
    else if (state.tool === "region") text = `框住這一頁的資料區，第 ${state.page + 1} 頁起會用這個範圍。`;
    else if (state.tool === "continuation") text = "框住內容在這一頁接續的範圍。按 Esc 取消。";
    else if (state.tool === "header") text = "框住表頭文字，例如第一欄的標題。要選每份都長得一樣的部分。按 Esc 取消。";
    else if (state.tool === "endmark") text = "框住表格結束後緊接著出現的文字，例如「合計」。按 Esc 取消。";
    else if (state.tool === "anchor") text = "框住每份都一樣的文字，例如表單標題。定位點越分散，對位越準。";
    else if (state.selected?.type === "table") text = "在表格內點一下加分隔線。拖曳分隔線可移動，雙擊可刪除。";
  }
  $("hint").textContent = text;
}

/* ---------- 左欄 ---------- */
function docRow(doc, meta, metaClass, onClick, extra) {
  const running = state.run && !state.run.finished;
  return h("li", { "aria-current": String(doc.id === state.docId) },
    h("button", { class: "doc-open", onclick: onClick }, h("span", { class: "name" }, doc.name),
      h("span", { class: `meta ${metaClass}` }, meta)),
    h("button", {
      class: "doc-remove", title: "移除這份 PDF", "aria-label": `移除 ${doc.name}`,
      disabled: running, onclick: () => removeDoc(doc.id),
    }, "×"),
    extra);
}
const hasDefinitions = () => T().fields.length + T().tables.length + T().anchors.length > 0;
// 範本座標屬於建立時的基準範例。換基準時用定位點對位，對得好的頁面把座標一次換算過來；
// 對不上的頁面和這份基準沒有的頁面都保留原樣，不會因為換一份範例就弄壞原本的設定。
const pageList = (pages) => pages.map((p) => p.page).join("、");
const alignToReference = guard(async () => {
  if (state.view !== "train" || !state.referenceId || !hasDefinitions()) return;
  const reference = state.referenceId;
  const request = (includeWeak) => api("/api/rebase", {
    json: { template: T(), reference, include_weak: includeWeak },
  });
  toast("正在依定位點對位");
  let result = await request(false);
  const weak = result.pages.filter((p) => p.status === "weak");
  if (weak.length && window.confirm(
    `第 ${pageList(weak)} 頁只找到部分定位點（${weak.map((p) => `${p.found}/${p.total}`).join("、")}），`
    + "位置可能不準。要照這個結果移動框線嗎？選「取消」會維持原位，之後自己調整。")) {
    result = await request(true);
  }
  if (state.referenceId !== reference) return;  // 對位期間又換了基準
  const applied = result.pages.filter((p) => p.applied);
  if (applied.length) {
    snapshot();
    state.template = result.template;
    state.tests = [];
    saveDraft();
    renderAll();
  }
  const lost = result.pages.filter((p) => p.status === "none");
  const bare = result.pages.filter((p) => p.status === "fixed");
  const messages = [];
  if (applied.length) messages.push(`已依定位點調整第 ${pageList(applied)} 頁的位置，可用 Ctrl+Z 復原`);
  if (lost.length) messages.push(`第 ${pageList(lost)} 頁對不上，框線維持原位，這份可能不是同一種文件`);
  if (bare.length) messages.push(`第 ${pageList(bare)} 頁沒有定位點，框線維持原位，請逐一確認`);
  if (result.beyond.length) messages.push(`第 ${result.beyond.join("、")} 頁的設定這份範例沒有，會保留不變`);
  if (messages.length) toast(messages.join("。"), !!(lost.length || bare.length));
  else $("toast").hidden = true;
});
const onReference = (page) => {
  const ref = state.docs.find((d) => d.id === state.referenceId);
  return !ref || page < ref.pages;
};
// 範本用到、但目前基準沒有的頁（從 1 起算）
function missingPages() {
  const ref = state.docs.find((d) => d.id === state.referenceId);
  if (!ref) return [];
  const pages = new Set();
  for (const f of T().fields) { pages.add(f.ref_page); if (f.continuation) pages.add(f.continuation.ref_page); }
  for (const a of T().anchors) pages.add(a.ref_page);
  for (const t of T().tables) {
    t.regions.forEach((r) => pages.add(r.ref_page));
    if (t.end_marker) pages.add(t.end_marker.ref_page);
  }
  return [...pages].filter((p) => p >= ref.pages).sort((a, b) => a - b).map((p) => p + 1);
}
function setReference(id) {
  if (id === state.referenceId) return;
  if (hasDefinitions() && !window.confirm(
    "改用這份當基準範例？會依定位點自動對位，對不上的頁面框線維持原位。")) return;
  state.referenceId = id;
  state.tests = [];
  state.docId = id;
  state.page = 0;
  state.selected = null;
  state.pending = null;
  saveDraft();
  renderAll();
  alignToReference();
}
const removeDoc = guard(async (id) => {
  const train = state.view === "train";
  const list = train ? state.docs : state.runDocs;
  const others = list.filter((d) => d.id !== id);
  if (train && id === state.referenceId && hasDefinitions() && others.length && !window.confirm(
    `移除基準範例後，會改用「${others[0].name}」當基準。已標注的框線不會自動移動，要繼續嗎？`)) return;
  await api(`/api/docs/${id}`, { method: "DELETE" });
  let realign = false;
  if (train) {
    state.docs = others;
    state.tests = state.tests.filter((r) => r.doc_id !== id);
    if (id === state.referenceId) {
      state.referenceId = others[0]?.id || null;
      if (others.length) { state.tests = []; saveDraft(); }
      realign = others.length > 0;
      state.selected = null;
      state.pending = null;
    }
  } else {
    state.runDocs = others;
    if (state.run) state.run.results = state.run.results.filter((r) => r.doc_id !== id);
    state.focusRef = null;
  }
  if (state.docId === id) { state.docId = others[0]?.id || null; state.page = 0; }
  renderAll();
  if (realign) alignToReference();
});
const removeAllDocs = guard(async () => {
  const train = state.view === "train";
  const list = train ? state.docs : state.runDocs;
  const lost = !train && hasUnsavedResults();
  if (!window.confirm(lost ? "全部移除？尚未匯出的解析結果也會一起清除。" : `移除全部 ${list.length} 份 PDF？範本不受影響。`)) return;
  for (const doc of list) await api(`/api/docs/${doc.id}`, { method: "DELETE" });
  if (train) {
    state.docs = [];
    state.referenceId = null;
    state.tests = [];
    state.selected = null;
    state.pending = null;
  } else {
    state.runDocs = [];
    state.run = null;
    state.focusRef = null;
  }
  state.docId = null;
  state.page = 0;
  state.drawerOpen = false;
  renderAll();
});
function listActions(count) {
  return h("div", { class: "list-actions" },
    h("button", { class: "linkish", onclick: () => $("filePicker").click() }, "再加入 PDF"),
    h("button", {
      class: "linkish", disabled: !count || (state.run && !state.run.finished), onclick: removeAllDocs,
    }, "全部移除"));
}
function thumbs() {
  const doc = currentDoc();
  if (!doc) return null;
  const pages = Array.from({ length: Math.min(doc.pages, 40) }, (_, i) => i);
  return [h("h2", {}, "頁面"), h("div", { class: "thumbs" }, pages.map((i) => h("button", {
    "aria-current": String(i === state.page), "aria-label": `第 ${i + 1} 頁`, onclick: () => setPage(i),
  }, h("img", { src: `/api/docs/${doc.id}/page/${i}.png?dpi=40`, alt: "", loading: "lazy" }), h("span", {}, String(i + 1)))))];
}
function openDoc(id) {
  state.docId = id;
  state.page = 0;
  state.selected = null;
  state.pending = null;
  renderAll();
}
function renderLeftTrain() {
  const list = state.docs.map((doc) => {
    const test = state.tests.find((r) => r.doc_id === doc.id);
    let meta = doc.id === state.referenceId ? "基準範例" : "測試範例";
    meta += `，${doc.pages} 頁`;
    if (!doc.has_text) meta += "，無文字層";
    let cls = "";
    if (test) {
      const pending = test.counts.review + test.counts.missing + blocking(test.issues).length;
      meta = pending ? `${meta}，${pending} 項待檢查` : `${meta}，全部通過`;
      cls = pending ? "warn" : "good";
    }
    const makeReference = doc.id === state.referenceId ? null
      : h("button", { class: "doc-reference", onclick: () => setReference(doc.id) }, "設為基準範例");
    return docRow(doc, meta, cls, () => openDoc(doc.id), makeReference);
  });
  fill($("left"),
    recoveryNotice(),
    h("h2", {}, "範本名稱"),
    h("input", {
      type: "text", value: T().name, autocomplete: "off", placeholder: "例如：進口報單", "aria-label": "範本名稱",
      oninput: (e) => { T().name = e.target.value; T().template_id = e.target.value.trim().replace(/[^\p{L}\p{N}_-]+/gu, "_"); saveDraft(); renderRightActions(); },
    }),
    h("h2", {}, "範例 PDF"),
    list.length ? [h("ul", { class: "docs" }, list), listActions(list.length)]
      : h("button", { class: "drop", onclick: () => $("filePicker").click() }, "加入 PDF"),
    h("h2", {}, "開啟已存的範本"),
    h("select", { "aria-label": "開啟已存的範本", onchange: (e) => openTemplate(e.target.value) },
      h("option", { value: "" }, "選擇範本"),
      state.templates.map((t) => h("option", { value: t.id }, t.name))),
    missingNote(),
    thumbs());
}
function missingNote() {
  const pages = missingPages();
  if (!pages.length) return null;
  return h("p", { class: "note" },
    `範本在第 ${pages.join("、")} 頁還有設定，這份基準範例沒有這幾頁。設定會保留不變，要修改時請換一份頁數夠的範例當基準。`);
}
// 影像圖塊是測試時自動補上的，不算使用者的修改
// 後端回傳的鍵順序可能不同，所以比對前先排序
const comparable = (template) => JSON.stringify(template, (key, value) => {
  if (key === "patch" || key === "text_center") return undefined;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => (a < b ? -1 : 1)));
  }
  return value;
});
function markSaved() {
  state.savedTemplate = comparable(T());
  state.savedId = T().template_id;
}
const templateIsEmpty = () => !hasDefinitions() && !T().name && !T().validations.length;
const hasUnsavedTemplate = () => !templateIsEmpty() && comparable(T()) !== state.savedTemplate;
const resetTemplate = guard(async () => {
  if (hasUnsavedTemplate() && !window.confirm("這個範本還沒儲存，開始新範本後，目前的標注會消失。要繼續嗎？")) return;
  for (const doc of state.docs) await api(`/api/docs/${doc.id}`, { method: "DELETE" });
  Object.assign(state, {
    template: blankTemplate(), savedTemplate: null, savedId: null, undo: [],
    docs: [], referenceId: null, tests: [], docId: null, page: 0, zoom: 1,
    tool: "select", pending: null, selected: null, read: null, checkDraft: null, drawerOpen: false,
    outputPanel: false, columnPreview: null,
  });
  saveDraft();
  renderAll();
  toast("已重置，可以開始建立新範本");
});
const openTemplate = guard(async (id) => {
  if (!id) return;
  snapshot();
  state.template = { ...blankTemplate(), ...await api(`/api/templates/${encodeURIComponent(id)}`) };
  markSaved();
  saveDraft();
  state.selected = null;
  state.tests = [];
  toast(state.docs.length ? "範本已開啟" : "範本已開啟，請加入基準範例 PDF 才能看到框線");
  renderAll();
  alignToReference();
});
function togglePick(id, checked) {
  state.templateIds = checked ? [...state.templateIds, id] : state.templateIds.filter((t) => t !== id);
  renderLeft();
}
function renderLeftRun() {
  const results = state.run?.results || [];
  const list = state.runDocs.map((doc) => {
    const result = results.find((r) => r.doc_id === doc.id);
    let meta = `${doc.pages} 頁`;
    let cls = "";
    if (result) {
      const pending = result.counts.review + result.counts.missing + blocking(result.issues).length;
      const used = result.template_name ? `${result.template_name}，` : "";
      if (result.status === "failed") { meta = "解析失敗"; cls = "bad"; }
      else if (pending) { meta = `${used}${pending} 項待檢查`; cls = "warn"; }
      else { meta = `${used}全部正常`; cls = "good"; }
    }
    return docRow(doc, meta, cls, () => {
      state.docId = doc.id; state.page = 0;
      state.focusRef = null;
      renderAll();
    });
  });
  const running = state.run && !state.run.finished;
  const picks = state.templates.map((t) => h("li", {}, h("label", {},
    h("input", {
      type: "checkbox", checked: state.templateIds.includes(t.id),
      onchange: (e) => togglePick(t.id, e.target.checked),
    }), t.name)));
  fill($("left"),
    h("h2", {}, "使用範本"),
    picks.length ? h("ul", { class: "template-picks" }, picks)
      : h("p", { class: "note" }, "還沒有範本，請先到「建立範本」。"),
    state.templates.length > 1 ? h("p", { class: "note" }, "可以複選。選多個時，每份 PDF 會自動用最符合的範本。") : null,
    h("h2", {}, "要解析的 PDF"),
    list.length ? [h("ul", { class: "docs" }, list), listActions(list.length)]
      : h("button", { class: "drop", onclick: () => $("filePicker").click() }, "加入 PDF"),
    h("div", { style: "margin-top:12px" },
      h("button", {
        class: "btn primary wide", disabled: !state.templateIds.length || !state.runDocs.length || running,
        onclick: startRun,
      }, running ? "解析中" : "開始解析")),
    running ? [h("div", { class: "progress" }, h("div", { style: `width:${state.run.done / state.run.total * 100}%` })),
      h("p", { class: "note" }, `${state.run.done}/${state.run.total}，${state.run.current}`)] : null,
    thumbs());
}
function renderLeft() { (state.view === "train" ? renderLeftTrain : renderLeftRun)(); }

/* ---------- 右欄：建立範本 ---------- */
function ruleSelect(item, onChange) {
  const custom = /^page:/.test(item.page_rule) ? item.page_rule : `page:${state.page + 1}`;
  return h("label", {}, "套用頁面", h("select", {
    onchange: (e) => { snapshot(); item.page_rule = e.target.value; onChange?.(); },
  }, [["first", "第 1 頁"], ["rest", "第 2 頁起"], ["last", "最後一頁"], ["all", "每一頁"],
    [custom, `只有第 ${custom.split(":")[1]} 頁`]].map(([value, label]) =>
    h("option", { value, selected: item.page_rule === value }, label))));
}
function bind(item, key, label, extra = {}) {
  return h("label", {}, label, h("input", {
    type: "text", value: item[key] ?? "", ...extra,
    oninput: (e) => { if (e.target.value) item[key] = e.target.value; else delete item[key]; saveDraft(); renderOverlay(); },
  }));
}
function typeSelect(item) {
  return h("select", { "aria-label": "資料類型", onchange: (e) => { item.type = e.target.value; saveDraft(); } },
    TYPE_OPTIONS.map(([value, label]) => h("option", { value, selected: (item.type || "text") === value }, label)));
}
function startContinuation(field) {
  const doc = currentDoc();
  if (field.ref_page + 1 >= doc.pages) {
    toast("基準範例沒有下一頁，請換一份有跨頁的範例", true);
    renderRight();
    return;
  }
  state.continuing = field.id;
  setPage(field.ref_page + 1);
  setTool("continuation");
  renderRight();
}
function fieldPanel(field) {
  const read = state.read;
  return [
    h("h2", {}, `(${numberOf(field.id)}) 欄位設定`),
    h("div", { class: "form" },
      h("label", {}, "欄位名稱", h("input", {
        id: "itemName", type: "text", value: field.name,
        oninput: (e) => { field.name = e.target.value; saveDraft(); renderOverlay(); },
      })),
      read ? h("div", { class: `grabbed${read.text ? "" : " empty-read"}` },
        read.text || "這個範圍沒有抓到內容",
        h("small", {}, [read.source ? SOURCE[read.source] : "", read.source === "ocr" ? `信心 ${Math.round(read.confidence * 100)}%` : "", ...read.notes].filter(Boolean).join("，"))) : null,
      h("label", {}, "資料類型", typeSelect(field)),
      ruleSelect(field),
      h("label", { class: "check" }, h("input", {
        type: "checkbox", checked: !!field.required, onchange: (e) => { field.required = e.target.checked; saveDraft(); },
      }), "必填，沒抓到就標記"),
      h("label", { class: "check" }, h("input", {
        type: "checkbox", checked: !!field.verify, onchange: (e) => { field.verify = e.target.checked; saveDraft(); },
      }), "重要欄位，用影像辨識再核對一次"),
      h("label", { class: "check" }, h("input", {
        type: "checkbox", checked: !!(field.continuation || state.continuing === field.id),
        onchange: (e) => {
          if (e.target.checked) startContinuation(field);
          else { snapshot(); delete field.continuation; state.continuing = null; setTool("select"); renderAll(); }
        },
      }), "內容可能接到下一頁"),
      field.continuation ? h("p", { class: "note" }, `接續範圍在第 ${field.continuation.ref_page + 1} 頁，接上時會標記給人確認。`) : null),
    h("details", {}, h("summary", {}, "進階設定"), h("div", { class: "form" },
      field.kind === "key_value" ? h("label", {}, "比對用的標題文字", h("input", {
        type: "text", value: field.label.text,
        oninput: (e) => { field.label.text = e.target.value; delete field.label.text_center; saveDraft(); },
      })) : null,
      h("label", {}, "取第幾行（1 是第一行，-1 是最後一行）", h("input", {
        type: "number", value: field.pick_line ?? "",
        oninput: (e) => { if (e.target.value) field.pick_line = Number(e.target.value); else delete field.pick_line; saveDraft(); },
      })),
      bind(field, "extract", "從內容擷取（正規表達式）", { placeholder: "例如：共\\s*(\\d+)\\s*頁" }),
      bind(field, "pattern", "格式檢查（正規表達式）", { placeholder: "例如：^\\d{8}$" }),
      h("label", {}, "資料來源", h("select", { onchange: (e) => { field.source = e.target.value; saveDraft(); } },
        [["auto", "自動"], ["text", "只用文字層"], ["ocr", "只用影像辨識"]].map(([value, label]) =>
          h("option", { value, selected: (field.source || "auto") === value }, label)))))),
    h("div", { style: "margin-top:10px" }, h("button", { class: "btn danger", onclick: deleteSelected }, "刪除欄位")),
  ];
}
function markerRow(label, marker, action, onPick, onRemove) {
  return h("div", { class: "row marker-row" },
    h("span", {}, marker ? `${label}：${marker.text || "已設定"}` : label),
    marker ? h("button", { class: "linkish", onclick: onRemove }, "移除")
      : h("button", { class: "linkish", onclick: onPick }, action));
}
const redraw = () => { saveDraft(); renderRight(); };
const VALUE_MODES = [
  ["whole", "整格內容（預設）"], ["line", "第幾行"], ["start", "開頭文字"],
  ["regex", "正規表達式"], ["space", "依空格分段"], ["gap", "依字距分段"],
];
function valueMode(column) {
  if (column.start !== undefined) return "start";
  if (column.extract !== undefined) return "regex";
  if (column.part_by) return column.part_by;
  if (column.pick_line) return "line";
  return "whole";
}
function setValueMode(table, column, mode) {
  for (const key of ["start", "end", "extract", "part_by", "part", "pick_line"]) delete column[key];
  const peers = table.columns.filter((c) => c.band === column.band && c !== column);
  if (mode === "line") column.pick_line = peers.filter((c) => c.pick_line).length + 1;
  if (mode === "start") { column.start = ""; column.end = "line"; }
  if (mode === "regex") column.extract = "";
  if (mode === "space" || mode === "gap") {
    column.part_by = mode;
    column.part = peers.filter((c) => c.part_by === mode).length + 1;
  }
}
function valueOptions(column) {
  const mode = valueMode(column);
  const text = (key, label, placeholder, note) => [
    h("label", {}, label, h("input", {
      type: "text", value: column[key] ?? "", placeholder, "aria-label": label,
      oninput: (e) => { column[key] = e.target.value; saveDraft(); },
    })),
    h("p", { class: "note" }, note),
  ];
  const number = (key, label, note) => [
    h("label", {}, label, h("input", {
      type: "number", value: column[key] ?? "", "aria-label": label,
      oninput: (e) => { if (e.target.value) column[key] = Number(e.target.value); saveDraft(); },
    })),
    note ? h("p", { class: "note" }, note) : null,
  ];
  if (mode === "line") return number("pick_line", "只取第幾行", "行數固定時使用。-1 是最後一行。");
  if (mode === "start") {
    return [
      text("start", "開頭文字", "例如：ECCN:", "只取開頭後面的值，不分大小寫，這格的其他內容不會帶進來。"),
      h("label", {}, "值到哪裡結束", h("select", {
        "aria-label": "值到哪裡結束",
        onchange: (e) => { column.end = e.target.value; saveDraft(); },
      }, [["line", "這一行結束"], ["word", "第一個空白"], ["next", "下一個開頭文字（可跨行）"]].map(([value, label]) =>
        h("option", { value, selected: (column.end || "next") === value }, label)))),
    ];
  }
  if (mode === "regex") {
    return text("extract", "正規表達式", "例如：ECCN:\\s*(\\S+)", "有括號時取第一組。比對不到時留空。");
  }
  if (mode === "space") return number("part", "取第幾段", "每段不能含空格。段數不對時，內容放在第一段並標記。");
  if (mode === "gap") return number("part", "取第幾段", "依字和字的實際距離分段，適合有文字層的 PDF。段數不對時，內容放在第一段並標記。");
  return null;
}
const previewColumn = guard(async (table, column) => {
  state.columnPreview = { id: column.id, loading: true };
  renderRight();
  try {
    const data = await api("/api/test", {
      json: { template: T(), reference: state.referenceId, docs: [state.referenceId] },
    });
    const rows = data.results[0]?.tables.find((t) => t.id === table.id)?.rows || [];
    state.columnPreview = {
      id: column.id,
      rows: rows.map((row) => row.cells[column.id]).filter(Boolean).slice(0, 6),
    };
  } catch (error) {
    state.columnPreview = null;
    throw error;
  } finally {
    renderRight();
  }
});
function previewRows(column) {
  const preview = state.columnPreview;
  if (preview?.id !== column.id) return null;
  if (preview.loading) return h("p", { class: "note" }, "試抓中");
  if (!preview.rows.length) return h("p", { class: "note" }, "沒有抓到任何列，請先確認表格範圍和判斷新一列的欄位。");
  return h("ol", { class: "preview-list" }, preview.rows.map((cell) => h("li", {},
    h("strong", {}, cell.value || "（空白）"),
    h("span", {}, cell.raw ?? cell.value))));
}
function columnDetail(table, column) {
  const siblings = table.columns.filter((c) => c.band === column.band);
  const split = siblings.length > 1;
  return h("div", { class: "form column-detail" },
    h("label", {}, "資料類型", typeSelect(column)),
    h("label", {}, "一格有多行時", h("select", {
      onchange: (e) => { if (e.target.value === "newline") column.join = "newline"; else delete column.join; saveDraft(); },
    }, [["space", "接成一行"], ["newline", "保留換行"]].map(([value, label]) =>
      h("option", { value, selected: (column.join || "space") === value }, label)))),
    h("label", { class: "check" }, h("input", {
      type: "checkbox", checked: !!column.row_required,
      onchange: (e) => { if (e.target.checked) column.row_required = true; else delete column.row_required; saveDraft(); },
    }), "每一列都一定有這欄"),
    h("p", { class: "note" }, "用來判斷跨頁：這欄沒抓到，代表這一列還沒結束。"),
    h("label", {}, "這一欄怎麼取值", h("select", {
      "aria-label": "這一欄怎麼取值",
      onchange: (e) => { snapshot(); setValueMode(table, column, e.target.value); renderRight(); },
    }, VALUE_MODES.map(([value, label]) =>
      h("option", { value, selected: valueMode(column) === value }, label)))),
    valueOptions(column),
    isReference() ? h("button", { class: "linkish", style: "text-align:left", onclick: () => previewColumn(table, column) }, "用基準範例試抓這一欄") : null,
    previewRows(column),
    h("div", { class: "row" },
      h("button", {
        class: "linkish", style: "text-align:left", onclick: () => {
          snapshot();
          const added = { id: nextId("c", table.columns), name: `欄${table.columns.length + 1}`, band: column.band };
          const mode = valueMode(column) === "whole" ? "line" : valueMode(column);
          if (valueMode(column) === "whole") setValueMode(table, column, "line");
          table.columns.push(added);
          setValueMode(table, added, mode);
          table.columns.sort((x, y) => x.band - y.band);
          renderAll();
        },
      }, "同一格拆成多欄"),
      split ? h("button", {
        class: "linkish", style: "flex:0 0 auto", onclick: () => {
          snapshot();
          table.columns = table.columns.filter((c) => c !== column);
          if (table.key_column === column.id) table.key_column = null;
          state.openColumn = null;
          renderAll();
        },
      }, "移除這欄") : null));
}
function columnsTab(table) {
  const rows = table.columns.map((column) => {
    const open = state.openColumn === column.id;
    return [
      h("div", { class: `column-row${open ? " open" : ""}` },
        h("span", { class: "column-band", title: `第 ${column.band + 1} 直欄` }, String(column.band + 1)),
        h("input", {
          type: "text", value: column.name, "aria-label": `第 ${column.band + 1} 直欄的欄名`,
          oninput: (e) => {
            column.name = e.target.value;
            const option = document.querySelector(`#keyColumn option[value="${column.id}"]`);
            if (option) option.textContent = column.name; // 上方的選單同步更新，輸入框保持焦點
            saveDraft();
            renderOverlay();
          },
        }),
        h("button", {
          class: "column-more", "aria-expanded": String(open), "aria-label": `${column.name} 的設定`,
          onclick: () => { state.openColumn = open ? null : column.id; renderRight(); },
        }, open ? "收合" : "設定")),
      open ? columnDetail(table, column) : null,
    ];
  });
  return [
    h("label", { class: "field-label" }, "用哪一欄判斷新的一列", h("select", {
      id: "keyColumn", "aria-label": "用哪一欄判斷新的一列",
      onchange: (e) => { table.key_column = e.target.value || null; saveDraft(); renderRight(); },
    }, h("option", { value: "" }, "請選擇，通常是項次"),
    table.columns.map((c) => h("option", { value: c.id, selected: table.key_column === c.id }, c.name)))),
    h("p", { class: "note" }, "在頁面的表格內點一下，可以切出新的直欄。"),
    rows,
  ];
}
function placementTab(table) {
  const regions = table.regions.map((region, i) => h("div", { class: "region-card" },
    h("div", { class: "row" },
      onReference(region.ref_page)
        ? h("button", { class: "linkish", style: "text-align:left", onclick: () => setPage(region.ref_page) }, `第 ${region.ref_page + 1} 頁的範圍`)
        : h("span", { class: "note" }, `第 ${region.ref_page + 1} 頁的範圍（這份範例沒有這頁，保留不變）`),
      i ? h("button", {
        class: "linkish", style: "flex:0 0 auto", onclick: () => { snapshot(); table.regions.splice(i, 1); renderAll(); },
      }, "移除") : null),
    ruleSelect(region, renderAll),
    markerRow("表頭", region.header, "框選表頭",
      () => {
        if (!onReference(region.ref_page)) { toast("這份基準範例沒有這一頁，請換一份頁數夠的範例", true); return; }
        state.markerRegion = i; setPage(region.ref_page); setTool("header");
      },
      () => { snapshot(); delete region.header; renderAll(); })));
  return [
    h("h3", {}, "每一頁的範圍"),
    regions,
    h("button", { class: "linkish", onclick: () => setTool("region") }, "在目前這一頁加範圍"),
    h("p", { class: "note" }, "明細接到下一頁時，切到那一頁再加。表格起始位置不固定時，框選表頭。"),
    h("h3", {}, "表格結尾"),
    markerRow("表尾標記", table.end_marker, "框選表尾",
      () => setTool("endmark"), () => { snapshot(); delete table.end_marker; renderAll(); }),
    h("div", { class: "form", style: "margin-top:6px" },
      bind(table, "stop_pattern", "或遇到這段文字就結束", { placeholder: "例如：以下空白" })),
    h("p", { class: "note" }, "都沒設定時，抓到範圍底部為止。"),
  ];
}
function advancedTab(table) {
  return [
    h("div", { class: "form" },
      h("label", {}, "列判斷欄的位置", h("select", { onchange: (e) => { table.key_position = e.target.value; saveDraft(); } },
        [["auto", "自動判斷"], ["middle", "在列的中間，或不固定"], ["top", "在列的最上方"]].map(([value, label]) =>
          h("option", { value, selected: table.key_position === value }, label)))),
      bind(table, "key_pattern", "新一列的格式（正規表達式）", { placeholder: "預設為純數字" }),
      h("label", {}, "資料來源", h("select", { onchange: (e) => { table.source = e.target.value; saveDraft(); } },
        [["auto", "自動"], ["text", "只用文字層"], ["ocr", "只用影像辨識"]].map(([value, label]) =>
          h("option", { value, selected: (table.source || "auto") === value }, label))))),
    h("div", { style: "margin-top:14px" }, h("button", { class: "btn danger", onclick: deleteSelected }, "刪除表格")),
  ];
}
function tablePanel(table) {
  const tabs = [["columns", "欄"], ["place", "位置"], ["more", "進階"]];
  const active = state.tableTab || "columns";
  const todo = [];
  if (table.columns.length < 2) todo.push("在表格內點一下切出直欄");
  if (!table.key_column) todo.push("選擇判斷新一列的欄位");
  return [
    h("h2", {}, `(${numberOf(table.id)}) 表格設定`),
    h("div", { class: "form" }, h("label", {}, "表格名稱", h("input", {
      id: "itemName", type: "text", value: table.name,
      oninput: (e) => { table.name = e.target.value; saveDraft(); renderOverlay(); },
    }))),
    todo.length ? h("p", { class: "todo" }, `還需要：${todo.join("，")}`) : null,
    h("div", { class: "subtabs", role: "tablist" }, tabs.map(([id, label]) => h("button", {
      role: "tab", "aria-selected": String(active === id),
      onclick: () => { state.tableTab = id; renderRight(); },
    }, label))),
    { columns: columnsTab, place: placementTab, more: advancedTab }[active](table),
  ];
}
function anchorPanel(anchor) {
  return [
    h("h2", {}, "定位點設定"),
    h("div", { class: "form" },
      h("label", {}, "比對文字", h("input", {
        type: "text", value: anchor.text,
        oninput: (e) => { anchor.text = e.target.value; delete anchor.text_center; saveDraft(); },
      })),
      ruleSelect(anchor)),
    h("div", { style: "margin-top:10px" }, h("button", { class: "btn danger", onclick: deleteSelected }, "刪除定位點")),
  ];
}
function valueBoxesOnPage() {
  const page = state.page;
  const boxes = T().fields.filter((f) => f.ref_page === page).map((f) => f.value_box);
  for (const t of T().tables) for (const r of t.regions) if (r.ref_page === page) boxes.push(r.box);
  return boxes;
}
const suggestAnchors = guard(async () => {
  toast("正在找這一頁的固定文字");
  const { anchors } = await api(`/api/docs/${state.docId}/suggest-anchors`, {
    json: { page: state.page, avoid: valueBoxesOnPage(), page_rule: defaultRule() },
  });
  snapshot();
  const existing = T().anchors.length;
  anchors.forEach((a, i) => { a.id = nextId("a", T().anchors); T().anchors.push(a); });
  toast(`加入 ${T().anchors.length - existing} 個定位點，刪掉會隨單據變動的項目`);
  renderAll();
});
function checksPanel() {
  const fields = T().fields;
  const describe = (rule) => {
    const name = (id) => fields.find((f) => f.id === id)?.name || id;
    if (rule.type === "page_count") return `總頁數要等於「${name(rule.field)}」`;
    if (rule.type === "sum_fields") return `${rule.fields.map(name).join(" + ")} = ${name(rule.equals)}`;
    const table = T().tables.find((t) => t.id === rule.table);
    return `${table?.name}「${table?.columns.find((c) => c.id === rule.column)?.name}」加總 = ${name(rule.equals)}`;
  };
  const draft = state.checkDraft || (state.checkDraft = { type: "sum_fields", fields: [] });
  const fieldOptions = fields.map((f) => h("option", { value: f.id }, f.name));
  const form = h("div", { class: "form" },
    h("label", {}, "檢查方式", h("select", {
      onchange: (e) => { state.checkDraft = { type: e.target.value, fields: [] }; renderRight(); },
    }, [["sum_fields", "幾個欄位相加"], ["sum_column", "表格某欄加總"], ["page_count", "比對總頁數"]].map(([value, label]) =>
      h("option", { value, selected: draft.type === value }, label)))),
    draft.type === "sum_fields" ? h("label", {}, "要相加的欄位（按住 Ctrl 或 Command 複選）", h("select", {
      multiple: true, size: Math.min(5, Math.max(2, fields.length)),
      onchange: (e) => { draft.fields = [...e.target.selectedOptions].map((o) => o.value); },
    }, fieldOptions)) : null,
    draft.type === "sum_column" ? h("label", {}, "表格欄", h("select", {
      onchange: (e) => { [draft.table, draft.column] = e.target.value.split("|"); },
    }, h("option", { value: "|" }, "選擇"), T().tables.flatMap((t) => t.columns.map((c) =>
      h("option", { value: `${t.id}|${c.id}` }, `${t.name}：${c.name}`))))) : null,
    h("label", {}, draft.type === "page_count" ? "寫著總頁數的欄位" : "要等於", h("select", {
      onchange: (e) => { draft.target = e.target.value; },
    }, h("option", { value: "" }, "選擇"), fieldOptions.map((o) => o.cloneNode(true)))),
    h("button", {
      class: "btn", onclick: () => {
        if (!draft.target) { toast("請選擇要比對的欄位", true); return; }
        snapshot();
        const rule = draft.type === "page_count" ? { type: "page_count", field: draft.target }
          : draft.type === "sum_fields" ? { type: "sum_fields", fields: draft.fields, equals: draft.target, tolerance: 1 }
            : { type: "sum_column", table: draft.table, column: draft.column, equals: draft.target, tolerance: 1 };
        T().validations.push(rule);
        state.checkDraft = null;
        renderRight();
      },
    }, "加入檢查"));
  return [
    h("ul", { class: "checks" }, T().validations.map((rule, i) => h("li", { class: "row note" }, h("span", {}, describe(rule)),
      h("button", { class: "linkish", style: "flex:0 0 auto", onclick: () => { snapshot(); T().validations.splice(i, 1); renderRight(); } }, "移除")))),
    h("details", {}, h("summary", {}, "新增檢查"), form),
  ];
}
/* 輸出設定：沒列在設定裡的欄位預設輸出，新增的欄位不會漏掉 */
function outputList(saved, available) {
  const names = new Map(available);
  const list = (saved || []).filter((entry) => names.has(entry.id));
  for (const [id] of available) if (!list.some((entry) => entry.id === id)) list.push({ id, include: true, name: "" });
  return list;
}
function outputGroup(title, available, read, write) {
  const names = new Map(available);
  const list = outputList(read(), available);
  const commit = () => { write(list); saveDraft(); };
  const move = (index, step) => {
    const target = index + step;
    if (target < 0 || target >= list.length) return;
    snapshot();
    [list[index], list[target]] = [list[target], list[index]];
    commit();
    renderRight();
  };
  return [
    h("h3", {}, title),
    list.map((entry, index) => h("div", { class: "output-row" },
      h("input", {
        type: "checkbox", checked: entry.include !== false, "aria-label": `輸出 ${names.get(entry.id)}`,
        onchange: (e) => { entry.include = e.target.checked; commit(); },
      }),
      h("input", {
        type: "text", value: entry.name || "", placeholder: names.get(entry.id), "aria-label": `${names.get(entry.id)} 的輸出欄名`,
        oninput: (e) => { entry.name = e.target.value; commit(); },
      }),
      h("button", { "aria-label": `${names.get(entry.id)} 上移`, disabled: index === 0, onclick: () => move(index, -1) }, "↑"),
      h("button", { "aria-label": `${names.get(entry.id)} 下移`, disabled: index === list.length - 1, onclick: () => move(index, 1) }, "↓"))),
  ];
}
function outputPanel() {
  const output = () => (T().output = T().output || {});
  const fields = T().fields.map((f) => [f.id, f.name]);
  return [
    h("button", { class: "linkish", style: "margin-bottom:8px", onclick: () => { state.outputPanel = false; renderRight(); } }, "回到欄位清單"),
    h("h2", {}, "輸出欄位"),
    h("p", { class: "note" }, "只影響「乾淨資料」，檢查用 Excel 維持完整內容。欄名留空就用原本的名稱。"),
    fields.length ? outputGroup("欄位", fields, () => T().output?.fields, (list) => { output().fields = list; }) : null,
    T().tables.map((table) => outputGroup(table.name, table.columns.map((c) => [c.id, c.name]),
      () => T().output?.tables?.[table.id], (list) => {
        output().tables = output().tables || {};
        output().tables[table.id] = list;
      })),
    !fields.length && !T().tables.length ? h("p", { class: "note" }, "還沒有欄位。") : null,
  ];
}
function renderRightTrain() {
  const item = selectedItem();
  let body;
  if (state.outputPanel) {
    body = outputPanel();
  } else if (item) {
    const panel = { field: fieldPanel, table: tablePanel, anchor: anchorPanel }[state.selected.type](item);
    body = [h("button", { class: "linkish", onclick: () => { state.selected = null; renderAll(); } }, "回到欄位清單"), panel];
    body[0].style.marginBottom = "8px";
  } else {
    const rows = orderedItems().map(({ type, item: entry }) => h("li", {},
      h("button", { onclick: () => { const doc = currentDoc(); const page = entry.ref_page ?? entry.regions[0].ref_page; if (doc && page < doc.pages) state.page = page; selectItem(type, entry.id); renderAll(); } },
        h("span", { class: "num" }, `(${numberOf(entry.id)})`), entry.name,
        h("span", { class: "kind" }, (type === "table" ? "表格" : entry.kind === "key_value" ? "有標題" : "只有值")
          + (onReference(entry.ref_page ?? entry.regions[0].ref_page) ? "" : "，這份範例沒有這頁")))));
    const anchorCount = T().anchors.length + T().fields.filter((f) => f.kind === "key_value").length;
    body = [
      h("h2", {}, "要抓的資料"),
      rows.length ? h("ul", { class: "items" }, rows)
        : h("p", { class: "note" }, "還沒有欄位。選上方的工具，在頁面上框出要抓的資料。"),
      h("h2", {}, "定位點"),
      h("p", { class: "note" }, `目前 ${anchorCount} 個（欄位標題也算）。每一頁至少要有 3 個，每份都不變的文字最適合。`),
      h("button", { class: "btn", disabled: !isReference(), onclick: suggestAnchors }, "自動找這一頁的定位點"),
      h("h2", {}, "數字檢查"),
      h("p", { class: "note" }, "對不上時，結果會標記給人確認。"),
      checksPanel(),
      h("h2", {}, "輸出"),
      h("p", { class: "note" }, "選擇乾淨資料要輸出哪些欄，以及欄名和順序。沒設定時全部輸出。"),
      h("button", { class: "btn", onclick: () => { state.outputPanel = true; renderRight(); } }, "設定輸出欄位"),
      state.tests.length ? testSummary() : null,
    ];
  }
  fill($("right"), body, actionsBar());
}
// level 為 notice 的整份疑點只是提示，不算進待檢查
const blocking = (issues) => issues.filter((issue) => issue.level !== "notice");
function issueRow(issue, withPage) {
  const notice = issue.level === "notice";
  const text = withPage && issue.page ? `第 ${issue.page} 頁：${issue.message}` : issue.message;
  return h("div", { class: notice ? "issue notice" : "issue" }, notice ? `提示：${text}` : text);
}
function testSummary() {
  const result = activeResult();
  return [
    h("h2", {}, "測試結果"),
    result ? [
      result.issues.map((issue) => issueRow(issue, false)),
      h("p", { class: "note" }, `${result.counts.total} 個值，${result.counts.review} 個需檢查，${result.counts.missing} 個缺值。`),
      result.align.map((a) => a.quality !== "good" && a.quality !== "fixed"
        ? h("p", { class: "note" }, `第 ${a.page} 頁對位不穩，找到 ${a.found}/${a.total} 個定位點`) : null),
    ] : h("p", { class: "note" }, "選左邊的範例看結果。"),
  ];
}
function actionsBar() {
  return h("div", { class: "actions", id: "actions" },
    h("button", {
      class: "btn primary wide", disabled: state.testing || !state.docs.length, onclick: testTemplate,
    }, state.testing ? "測試中" : `用 ${state.docs.length} 份範例測試`),
    h("button", { class: "btn wide", id: "saveButton", disabled: !T().template_id, onclick: saveTemplate },
      T().template_id ? "儲存範本" : "先填範本名稱才能儲存"),
    h("button", {
      class: "btn wide", id: "resetButton", disabled: templateIsEmpty() && !state.docs.length, onclick: resetTemplate,
    }, "開始新範本"));
}
function renderRightActions() {
  const current = $("actions");
  if (current) current.replaceWith(actionsBar());
}
const testTemplate = guard(async () => {
  if (!T().template_id) { T().template_id = "draft"; }
  state.testing = true;
  state.selected = null;
  renderRight();
  try {
    const data = await api("/api/test", {
      json: { template: T(), reference: state.referenceId, docs: state.docs.map((d) => d.id) },
    });
    state.template = data.template;
    state.tests = data.results;
    state.drawerOpen = true;
    saveDraft();
  } finally {
    state.testing = false;
    renderAll();
  }
});
const saveTemplate = guard(async () => {
  const id = T().template_id;
  if (id !== state.savedId && state.templates.some((t) => t.id === id)
    && !window.confirm(`已經有叫做「${T().name}」的範本，要覆蓋嗎？`)) return;
  await api("/api/templates", { json: { template: T(), reference: state.referenceId } });
  markSaved();
  saveDraft();
  await loadTemplates();
  if (!state.templateIds.includes(T().template_id)) state.templateIds.push(T().template_id);
  toast(`範本「${T().name}」已儲存。要做下一個範本時，按「開始新範本」`);
  renderLeft();
  renderRightActions();
});

/* ---------- 右欄：解析結果 ---------- */
function reasonLine(value) {
  return value.reasons.map((code) => state.reasons[code] || code).join("，");
}
function focusValue(ref) {
  state.focusRef = ref;
  const result = activeResult();
  const entry = result && allValues(result).find((e) => e.ref === ref);
  if (entry?.value.page && entry.value.page - 1 !== state.page) { state.page = entry.value.page - 1; renderToolbar(); renderLeft(); }
  renderPage();
  document.querySelector(".box.focus")?.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
}
const editValue = guard(async (ref, action, value) => {
  const index = state.run.results.findIndex((r) => r.doc_id === state.docId);
  const result = await api(`/api/runs/${state.run.id}/edit`, {
    json: { file_index: index, ref, action, value },
  });
  state.run.exported = false;
  state.run.results[index] = result;
  renderLeft(); renderRight(); renderOverlay(); renderDrawer();
});
function templateNote(result) {
  const match = result.match === null || result.match === undefined ? "" : `，符合 ${Math.round(result.match * 100)}%`;
  const candidates = result.selection?.candidates || [];
  return h("div", { class: "picked-template" },
    `${candidates.length ? "自動選用" : "使用範本"}：${result.template_name}${match}`,
    candidates.length ? h("small", {}, candidates.map((c) => `${c.name} ${Math.round(c.match * 100)}%`).join("，")) : null);
}
function renderRightRun() {
  const result = activeResult();
  if (!result) {
    fill($("right"), h("h2", {}, "待檢查"),
      h("p", { class: "note" }, "解析完成後，有疑慮的值會列在這裡，點一下就能看到它在頁面上的位置。"));
    return;
  }
  const pending = allValues(result).filter((e) => ["review", "missing"].includes(e.value.status));
  const items = pending.map((entry) => {
    // 用 textarea：單行輸入框會吃掉換行，按確認時多行內容就會黏在一起
    const lineCount = entry.value.value.split("\n").length;
    const input = h("textarea", {
      value: entry.value.value, rows: Math.min(Math.max(lineCount, 1), 6), "aria-label": `${entry.name} 的正確值`,
    });
    return h("article", { class: `review-item ${entry.value.status}` },
      h("button", { class: "locate", onclick: () => focusValue(entry.ref) },
        h("h3", {}, entry.name), h("span", { class: "why" }, reasonLine(entry.value))),
      entry.value.raw && entry.value.raw !== entry.value.value
        ? h("p", { class: "raw-text" }, "原始內容：", entry.value.raw) : null,
      h("div", { class: "row" }, input,
        h("button", { class: "btn", onclick: () => editValue(entry.ref, input.value === entry.value.value && entry.value.value ? "confirm" : "correct", input.value) }, "確認")));
  });
  const done = state.run.finished;
  fill($("right"), 
    h("h2", {}, `${result.file}`),
    h("p", { class: "note" }, `${result.pages} 頁，${result.counts.total} 個值。`),
    templateNote(result),
    result.issues.map((issue) => issueRow(issue, true)),
    h("h2", {}, `待檢查 ${pending.length} 項`),
    items.length ? items : h("p", { class: "note" }, "這份沒有需要檢查的值。"),
    h("div", { class: "actions" },
      h("a", {
        class: "btn primary wide", style: "text-align:center;text-decoration:none", download: "",
        href: done ? `/api/runs/${state.run.id}/excel` : undefined,
        onclick: () => { state.run.exported = true; },
      }, "匯出檢查用 Excel"),
      h("a", {
        class: "btn wide", style: "text-align:center;text-decoration:none", download: "",
        href: done ? `/api/runs/${state.run.id}/clean?only_confirmed=${state.onlyConfirmed ? 1 : 0}` : undefined,
        onclick: () => { state.run.exported = true; },
      }, "匯出乾淨資料"),
      h("label", { class: "check-line" }, h("input", {
        type: "checkbox", checked: !!state.onlyConfirmed,
        onchange: (e) => { state.onlyConfirmed = e.target.checked; renderRight(); },
      }), "乾淨資料只輸出已確認")));
}
function renderRight() { (state.view === "train" ? renderRightTrain : renderRightRun)(); }

/* ---------- 抓取結果 ---------- */
function dataCell(value, ref, text) {
  const status = ["review", "missing", "corrected"].includes(value?.status) ? value.status : "";
  return h("td", {
    class: status, title: value ? [text, reasonLine(value)].filter(Boolean).join("\n") : "",
    onclick: () => value && focusValue(ref),
  }, text ?? "");
}
function renderDrawer() {
  const result = activeResult();
  const drawer = $("drawer");
  drawer.hidden = !result || !state.drawerOpen;
  if (drawer.hidden) return;
  const fieldTable = result.fields.length ? [h("h3", {}, "欄位"), h("table", { class: "data" },
    h("thead", {}, h("tr", {}, result.fields.map((f) => h("th", {}, f.name)))),
    h("tbody", {}, h("tr", {}, result.fields.map((f) => dataCell(f, `f:${f.id}`, f.value)))))] : [];
  const tables = result.tables.map((table) => [
    h("h3", {}, `${table.name}，共 ${table.rows.length} 列`),
    h("table", { class: "data" },
      h("thead", {}, h("tr", {}, h("th", {}, "頁"), table.columns.map((c) => h("th", {}, c.name)))),
      h("tbody", {}, table.rows.map((row, r) => h("tr", {}, h("td", {}, String(row.page)),
        table.columns.map((c) => dataCell(row.cells[c.id], `t:${table.id}:${r}:${c.id}`, row.cells[c.id]?.value))))))]);
  fill(drawer, fieldTable, tables);
}

/* ---------- 解析流程 ---------- */
const startRun = guard(async () => {
  const docs = state.runDocs.map((d) => d.id);
  const { run_id: id } = await api("/api/runs", { json: { template_ids: state.templateIds, docs } });
  state.run = { id, total: docs.length, done: 0, current: "", results: [], finished: false };
  state.drawerOpen = true;
  renderLeft();
  while (!state.run.finished) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    const data = await api(`/api/runs/${id}`);
    state.run = { id, ...data };
    renderLeft();
    if (state.run.results.length && !state.focusRef) renderAll();
  }
  const pending = state.run.results.filter((r) => r.status !== "ok").length;
  toast(pending ? `完成，${pending} 份有待檢查項目` : "完成，全部正常");
  renderAll();
});

/* ---------- 檔案 ---------- */
const addFiles = guard(async (files) => {
  const pdfs = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) { toast("只能加入 PDF 檔", true); return; }
  const form = new FormData();
  pdfs.forEach((file) => form.append("files", file));
  toast("正在讀取 PDF");
  const { docs, failed } = await api("/api/docs", { method: "POST", body: form });
  failed.forEach((item) => toast(`${item.name}：${item.error}`, true));
  const list = state.view === "train" ? state.docs : state.runDocs;
  list.push(...docs);
  const newReference = state.view === "train" && !state.referenceId && docs.length > 0;
  if (newReference) state.referenceId = docs[0].id;
  if (!state.docId && docs.length) { state.docId = docs[0].id; state.page = 0; }
  renderAll();
  if (newReference) alignToReference();
});

/* ---------- 與本機程式的連線 ---------- */
/* 頁面全部關閉後，本機程式會自動結束，不會留在背景。 */
const clientId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
let heartbeatFailures = 0;
async function heartbeat() {
  try {
    const response = await fetch(`/api/heartbeat?client=${encodeURIComponent(clientId)}`, { method: "POST" });
    if (!response.ok) throw new Error();
    heartbeatFailures = 0;
  } catch (_error) {
    heartbeatFailures += 1;
    if (heartbeatFailures === 2) toast("工具已經關閉。請重新執行 run.bat，再重新整理這個頁面。", true);
  }
}
const hasUnsavedResults = () => !!state.run?.results.length && !state.run.exported;
function watchConnection() {
  heartbeat();
  setInterval(heartbeat, 15000);
  window.addEventListener("pagehide", () => navigator.sendBeacon(`/api/bye?client=${encodeURIComponent(clientId)}`));
  window.addEventListener("pageshow", (event) => { if (event.persisted) heartbeat(); });
  window.addEventListener("beforeunload", (event) => { if (hasUnsavedResults()) event.preventDefault(); });
}

/* ---------- 切換與啟動 ---------- */
function setView(view) {
  state.view = view;
  const list = view === "train" ? state.docs : state.runDocs;
  state.docId = list[0]?.id || null;
  state.page = 0;
  state.selected = null;
  state.focusRef = null;
  renderAll();
}
function renderAll() {
  $("tabTrain").setAttribute("aria-current", state.view === "train" ? "page" : "false");
  $("tabRun").setAttribute("aria-current", state.view === "run" ? "page" : "false");
  renderToolbar(); renderHint(); renderLeft(); renderRight(); renderPage(); renderDrawer();
}
async function loadTemplates() {
  state.templates = (await api("/api/templates")).templates;
}
function onKey(event) {
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName)) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); undo(); return; }
  if (event.ctrlKey || event.metaKey) return;
  const tool = TOOLS.find(([, , key]) => key === event.key.toUpperCase());
  if (tool && state.view === "train" && isReference()) { setTool(tool[0]); return; }
  if (event.key === "Escape") setTool("select");
  else if (event.key === "Delete" || event.key === "Backspace") deleteSelected();
  else if (event.key === "PageDown") setPage(state.page + 1);
  else if (event.key === "PageUp") setPage(state.page - 1);
}
async function main() {
  $("tabTrain").addEventListener("click", () => setView("train"));
  $("tabRun").addEventListener("click", () => setView("run"));
  $("overlay").addEventListener("pointerdown", startDraw);
  $("filePicker").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
  window.addEventListener("keydown", onKey);
  window.addEventListener("resize", () => renderPage());
  for (const name of ["dragenter", "dragover"]) {
    window.addEventListener(name, (e) => { e.preventDefault(); document.body.classList.add("dropping"); });
  }
  window.addEventListener("dragleave", (e) => { if (!e.relatedTarget) document.body.classList.remove("dropping"); });
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    document.body.classList.remove("dropping");
    addFiles(e.dataTransfer.files);
  });
  loadDraft();
  renderAll();
  watchConnection();
  try {
    const status = await api("/api/status");
    state.reasons = status.reasons;
    state.ocr = status.ocr;
    $("version").textContent = status.version ? `v${status.version}` : "";
    $("engine").textContent = status.ocr ? "只在這台電腦處理" : "影像辨識無法使用，只能讀文字層";
    $("engine").classList.toggle("bad", !status.ocr);
    await loadTemplates();
    renderAll();
  } catch (error) {
    toast(error.message, true);
  }
}
main();
