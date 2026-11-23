/* 使用手冊與換版說明共用：目錄標示目前位置、離線搜尋（比對標題與內文）。
 * 工具對 HTML 套用 CSP（script-src 'self'），所以放在外部檔，不 inline；雙擊直接開啟時也一樣用相對路徑載入。 */
(() => {
  const body = document.getElementById("manualBody");
  const input = document.getElementById("manualSearch");
  const list = document.getElementById("manualResults");
  const links = [...document.querySelectorAll("nav.sidebar a")];
  const heads = [...body.querySelectorAll("h2[id], h3[id], h4[id]")];

  // 每個標題連同到下一個標題之前的內文當成一段，搜尋時比對標題與內文
  const norm = (text) => text.toLowerCase().replace(/\s+/g, " ");
  const chapterOf = new Map();
  let chapter = "";
  const sections = heads.map((head, i) => {
    if (head.tagName === "H2") chapter = head.textContent;
    chapterOf.set(head, chapter);
    let text = "";
    for (let node = head.nextElementSibling; node && !/^H[2-4]$/.test(node.tagName); node = node.nextElementSibling) {
      text += ` ${node.textContent}`;
    }
    text = text.replace(/\s+/g, " ").trim();
    return { id: head.id, title: head.textContent.trim(), chapter: chapterOf.get(head), text, lower: norm(text), titleLower: norm(head.textContent) };
  });

  const escapeHtml = (text) => text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const mark = (text, query) => {
    const at = text.toLowerCase().indexOf(query);
    if (at < 0) return escapeHtml(text);
    return `${escapeHtml(text.slice(0, at))}<mark>${escapeHtml(text.slice(at, at + query.length))}</mark>${escapeHtml(text.slice(at + query.length))}`;
  };
  const snippet = (section, query) => {
    const at = section.lower.indexOf(query);
    if (at < 0) return section.text.slice(0, 60);
    const start = Math.max(0, at - 24);
    return (start ? "…" : "") + section.text.slice(start, at + query.length + 56);
  };

  function search(raw) {
    const query = norm(raw.trim());
    list.textContent = "";
    if (!query) { list.hidden = true; return; }
    const hits = sections
      .map((s) => ({ s, score: s.titleLower.includes(query) ? 2 : s.lower.includes(query) ? 1 : 0 }))
      .filter((hit) => hit.score)
      .sort((a, b) => b.score - a.score)
      .slice(0, 20);
    if (!hits.length) {
      const none = document.createElement("li");
      none.className = "none";
      none.textContent = "找不到符合的內容";
      list.append(none);
    }
    for (const { s } of hits) {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = `#${s.id}`;
      link.innerHTML = `${mark(s.title, query)}<small>${escapeHtml(s.chapter === s.title ? "" : s.chapter)}${s.chapter === s.title ? "" : "：" }${mark(snippet(s, query), query)}</small>`;
      link.addEventListener("click", () => { list.hidden = true; });
      item.append(link);
      list.append(item);
    }
    list.hidden = false;
  }

  input.addEventListener("input", () => search(input.value));
  input.addEventListener("keydown", (event) => {
    const anchors = [...list.querySelectorAll("a")];
    if (event.key === "Escape") { list.hidden = true; input.blur(); }
    else if (event.key === "Enter" && anchors[0]) { event.preventDefault(); anchors[0].click(); }
    else if (event.key === "ArrowDown" && anchors[0]) { event.preventDefault(); anchors[0].focus(); }
  });
  list.addEventListener("keydown", (event) => {
    const anchors = [...list.querySelectorAll("a")];
    const at = anchors.indexOf(document.activeElement);
    if (event.key === "ArrowDown" && anchors[at + 1]) { event.preventDefault(); anchors[at + 1].focus(); }
    if (event.key === "ArrowUp") { event.preventDefault(); (anchors[at - 1] || input).focus(); }
    if (event.key === "Escape") { list.hidden = true; input.focus(); }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) { event.preventDefault(); input.focus(); }
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search")) list.hidden = true;
  });
  input.addEventListener("focus", () => { if (input.value.trim()) search(input.value); });

  // 目錄標示目前位置：標題頂端已經捲過畫面上緣 90px 的最後一個
  const byId = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
  const tracked = heads.filter((h) => byId.has(h.id));
  let current = null;
  function track() {
    let active = tracked[0];
    for (const head of tracked) {
      if (head.getBoundingClientRect().top <= 90) active = head; else break;
    }
    if (!active || active === current) return;
    current = active;
    for (const a of links) a.removeAttribute("aria-current");
    const link = byId.get(active.id);
    link.setAttribute("aria-current", "true");
    link.scrollIntoView({ block: "nearest" });
  }
  window.addEventListener("scroll", track, { passive: true });
  window.addEventListener("hashchange", () => setTimeout(track, 50));
  track();
})();
