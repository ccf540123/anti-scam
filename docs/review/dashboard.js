(function () {
  const cfg = window.REVIEW_CONFIG || {};
  const PAGE_SIZE = 12;
  const LINK_LIMIT = 15;

  const loading = document.getElementById("loading");
  const loadError = document.getElementById("loadError");
  const dashboard = document.getElementById("dashboard");

  let model = null;
  let npa = null;
  let selection = null;
  let page = 0;
  let supabase = null;
  let chartInstances = [];
  let activeView = "counts";
  const VIEW_TITLES = {
    counts: "數量",
    keywords: "關鍵字",
    links: "文中的網站",
  };
  function canon(url) {
    const raw = String(url || "").trim();
    if (!raw) return "";
    try {
      const parsed = new URL(raw);
      const path = parsed.pathname.replace(/\/+$/, "");
      return parsed.protocol + "//" + parsed.host.toLowerCase() + path;
    } catch (err) {
      return raw;
    }
  }

  function keywordList(value) {
    if (Array.isArray(value)) {
      return value.map(function (item) { return String(item).trim(); }).filter(Boolean);
    }
    if (!value) return [];
    if (typeof value === "string") {
      try {
        const parsed = JSON.parse(value);
        if (Array.isArray(parsed)) return keywordList(parsed);
      } catch (err) {
        /* 不是 JSON 就依分隔符拆 */
      }
      return value.split(/\n|、|\|/).map(function (item) { return item.trim(); }).filter(Boolean);
    }
    return [];
  }

  function hostsIn(text) {
    const matches = String(text || "").match(/https?:\/\/[^\s<>"'）】\]]+/g) || [];
    const hosts = [];
    matches.forEach(function (raw) {
      const cleaned = raw.replace(/[),.;:!?，。、]+$/g, "");
      let host = "";
      try {
        host = new URL(cleaned).hostname.toLowerCase();
      } catch (err) {
        return;
      }
      if (host.indexOf("www.") === 0) host = host.slice(4);
      if (!host || host === "ptt.cc" || host.slice(-7) === ".ptt.cc") return;
      hosts.push(host);
    });
    return unique(hosts);
  }

  function unique(list) {
    const seen = {};
    const out = [];
    list.forEach(function (item) {
      if (!item || seen[item]) return;
      seen[item] = true;
      out.push(item);
    });
    return out;
  }

  function isComplete(answer) {
    if (!answer) return false;
    const content = String(answer.content_relevant || "").trim();
    const url = String(answer.url_relevant || "").trim();
    if (!content || !url) return false;
    if (content === "yes" || url === "yes") return keywordList(answer.keywords).length > 0;
    return true;
  }

  function gradeOf(answer) {
    const value = String((answer && answer.content_relevant) || "").trim();
    return value === "A" || value === "B" || value === "C" ? value : "";
  }

  function contentLabel(value) {
    if (value === "yes") return "有詐騙相關內容";
    if (value === "no") return "沒有詐騙相關內容";
    return "未填";
  }

  function urlLabel(value) {
    if (value === "yes") return "有詐騙相關資訊";
    if (value === "no") return "沒有詐騙相關資訊";
    if (value === "none") return "沒有網址";
    return "未填";
  }

  function getClient() {
    if (supabase) return supabase;
    supabase = window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);
    return supabase;
  }

  function parseCsv(url) {
    return new Promise(function (resolve, reject) {
      window.Papa.parse(url, {
        download: true,
        header: true,
        skipEmptyLines: true,
        complete: function (result) {
          resolve(result.data || []);
        },
        error: function (err) {
          reject(err || new Error("無法讀取 " + url));
        },
      });
    });
  }

  async function fetchAnswers(datasetId) {
    const { data, error } = await getClient()
      .from("ptt_review_answers")
      .select("review_id,dataset_id,content_relevant,url_relevant,keywords,status,human_notes,reviewer,review_status")
      .eq("dataset_id", datasetId)
      .limit(2000);
    if (error) throw new Error(error.message || "讀取審查答案失敗");
    const map = {};
    (data || []).forEach(function (row) {
      map[String(row.review_id)] = row;
    });
    return map;
  }

  function cleanRow(row) {
    const out = {};
    Object.keys(row || {}).forEach(function (key) {
      out[String(key).replace(/^\uFEFF/, "")] = row[key];
    });
    return out;
  }

  function toStage1(row, answers) {
    row = cleanRow(row);
    const answer = answers[String(row.review_id || "").trim()] || null;
    const complete = isComplete(answer);
    return {
      phase: "第一階段",
      reviewId: row.review_id || "",
      title: row.title || "（無標題）",
      board: row.source_board || "（看板空白）",
      url: row.article_url || "",
      canon: canon(row.article_url || ""),
      content: row.content || "",
      hosts: hostsIn(row.content || ""),
      complete: complete,
      contentRelevant: complete ? String(answer.content_relevant || "").trim() : "",
      urlRelevant: complete ? String(answer.url_relevant || "").trim() : "",
      status: complete ? String(answer.status || "").trim() : "",
      keywords: complete ? unique(keywordList(answer.keywords)) : [],
      reviewer: complete ? (answer.reviewer || "") : "",
      notes: complete ? (answer.human_notes || "") : "",
      searchKeyword: row.search_keyword || "",
    };
  }

  function toStage2(row, answers) {
    row = cleanRow(row);
    const answer = answers[String(row.review_id || "").trim()] || null;
    const grade = gradeOf(answer);
    return {
      phase: "第二階段",
      reviewId: row.review_id || "",
      title: row.title || "（無標題）",
      board: row.source_board || "（看板空白）",
      url: row.article_url || "",
      canon: canon(row.article_url || ""),
      content: row.content || "",
      complete: Boolean(grade),
      grade: grade,
      keywords: unique(String(row.search_keyword || "").split("、").map(function (item) { return item.trim(); }).filter(Boolean)),
      stage1Flag: row.stage1_flag || "",
      reviewer: answer ? (answer.reviewer || "") : "",
      notes: answer ? (answer.human_notes || "") : "",
      searchKeyword: row.search_keyword || "",
    };
  }

  function buildModel(items, stage2Rows, answers1, answers2) {
    const stage1 = items.filter(function (row) { return String(row.review_id || "").trim(); }).map(function (row) {
      return toStage1(row, answers1);
    });
    const stage2 = stage2Rows.filter(function (row) { return String(row.review_id || "").trim(); }).map(function (row) {
      return toStage2(row, answers2);
    });
    const complete = stage1.filter(function (row) { return row.complete; });
    const contentYes = complete.filter(function (row) { return row.contentRelevant === "yes"; });
    const contentNo = complete.filter(function (row) { return row.contentRelevant === "no"; });
    const keywordRank = rankRows(contentYes, function (row) { return row.keywords; });
    const linkRank = rankRows(contentYes, function (row) { return row.hosts; });
    return {
      stage1: stage1,
      stage2: stage2,
      complete: complete,
      contentYes: contentYes,
      contentNo: contentNo,
      keywordRank: keywordRank,
      linkRank: linkRank,
    };
  }

  function rankRows(rows, getKeys) {
    const map = new Map();
    rows.forEach(function (row) {
      getKeys(row).forEach(function (key) {
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(row);
      });
    });
    return Array.from(map.entries()).sort(function (a, b) {
      return b[1].length - a[1].length || String(a[0]).localeCompare(String(b[0]), "zh-Hant");
    });
  }

  function selectedId() {
    return selection ? selection.id : "";
  }

  function statButton(id, value, label, rows, note) {
    const selected = selectedId() === id ? " is-selected" : "";
    return '<button type="button" class="stat' + selected + '" data-select="' + id + '"><strong>' + value + '</strong><span>' + label + '</span></button>';
  }

  function remember(id, title, rows, note) {
    model.selections[id] = { id: id, title: title, rows: rows, note: note || "" };
  }

  function destroyCharts() {
    chartInstances.forEach(function (chart) { chart.destroy(); });
    chartInstances = [];
  }

  function chartDefaults() {
    if (!window.Chart) return;
    window.Chart.defaults.color = "#c5d0da";
    window.Chart.defaults.borderColor = "#2c3440";
    window.Chart.defaults.font.family = '"Avenir Next", "PingFang TC", "Noto Sans TC", sans-serif';
  }

  function addChart(canvasId, panel, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !window.Chart) return;
    const chart = new window.Chart(canvas, config);
    chart.$panel = panel;
    chartInstances.push(chart);
  }

  function doughnut(canvasId, panel, labels, values, ids, colors) {
    addChart(canvasId, panel, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: colors,
          borderColor: "#12161c",
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom" } },
        onClick: function (event, elements) {
          if (!elements.length) return;
          choose(ids[elements[0].index]);
        },
      },
    });
  }

  function horizontalBars(canvasId, panel, labels, values, ids, colors) {
    addChart(canvasId, panel, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: "篇數",
          data: values,
          backgroundColor: colors,
          borderWidth: 0,
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: "數量" } },
          y: { ticks: { autoSkip: false } },
        },
        onClick: function (event, elements) {
          if (!elements.length) return;
          choose(ids[elements[0].index]);
        },
      },
    });
  }

  function showView(name) {
    if (!VIEW_TITLES[name]) return;
    activeView = name;
    document.querySelectorAll("[data-panel]").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-panel") !== name;
    });
    document.querySelectorAll("#sideNav button").forEach(function (button) {
      button.classList.toggle("is-active", button.getAttribute("data-view") === name);
    });
    const title = document.getElementById("viewTitle");
    if (title) title.textContent = VIEW_TITLES[name];
    window.requestAnimationFrame(function () {
      chartInstances.forEach(function (chart) {
        if (chart.$panel === name) chart.resize();
      });
    });
  }

  function renderCounts() {
    const incomplete = model.stage1.filter(function (row) { return !row.complete; });
    const pending2 = model.stage2.filter(function (row) { return !row.grade; }).length;
    remember("count:yes", "有詐騙相關內容", model.contentYes, "已完成審查，而且「文章內容是否包含詐騙相關資訊」選了有。這不是 Spam。");
    remember("count:no", "沒有詐騙相關內容", model.contentNo, "已完成審查，而且「文章內容是否包含詐騙相關資訊」選了沒有。這不是 Clean。");
    remember("count:todo", "尚未審查", incomplete, "第一階段還沒審完。這不是 Clean。");
    doughnut(
      "countChart",
      "counts",
      ["有詐騙相關內容", "沒有詐騙相關內容", "尚未審查"],
      [model.contentYes.length, model.contentNo.length, incomplete.length],
      ["count:yes", "count:no", "count:todo"],
      ["#5eead4", "#fbbf24", "#64748b"]
    );
    document.getElementById("countStats").innerHTML = [
      statButton("count:yes", model.contentYes.length, "有詐騙相關內容"),
      statButton("count:no", model.contentNo.length, "沒有詐騙相關內容"),
      statButton("count:todo", incomplete.length, "尚未審查"),
    ].join("");
    document.getElementById("countNote").textContent =
      "第一階段清單 " + model.stage1.length + " 篇，已完成審查 " + model.complete.length + " 篇。第二階段 " + model.stage2.length + " 篇裡有 " + pending2 + " 篇尚未審查，沒有放進這張圖。";
  }

  function renderKeywords() {
    const top40 = model.keywordRank.slice(0, 40);
    const top20 = model.keywordRank.slice(0, 20);
    const max = top40.length ? top40[0][1].length : 1;
    const note = "有詐騙相關內容的文章裡，審查者寫到這個詞的篇數。同一篇只算一次。";
    document.getElementById("wordCloud").innerHTML = top40.map(function (pair) {
      const id = "kw:" + pair[0];
      remember(id, pair[0], pair[1], note);
      const size = 14 + Math.round((pair[1].length / max) * 18);
      const selected = selectedId() === id ? " is-selected" : "";
      return '<button type="button" class="cloud-word' + selected + '" data-select="' + escapeHtml(id) + '" style="font-size:' + size + 'px">' + escapeHtml(pair[0]) + "</button>";
    }).join("");
    horizontalBars(
      "keywordBar",
      "keywords",
      top20.map(function (pair) { return pair[0]; }),
      top20.map(function (pair) { return pair[1].length; }),
      top20.map(function (pair) { return "kw:" + pair[0]; }),
      top20.map(function () { return "#7dd3fc"; })
    );
  }

  function renderLinks() {
    const top = model.linkRank.slice(0, LINK_LIMIT);
    const withLink = model.contentYes.filter(function (row) { return row.hosts.length > 0; }).length;
    const hit = npa ? npa.stage1_articles_exact_host_in_165 : 0;
    document.getElementById("linkCaption").textContent =
      "下面是「有詐騙相關內容」的 " + model.contentYes.length + " 篇文章裡寫到的網站。已去掉 PTT 自己的網域，同一篇同一個網站只算一次。其中 " + withLink + " 篇有外部網站。這些網站還沒被核對成詐騙網站；和 165 官方名單完全比對，命中 " + hit + " 篇。";
    top.forEach(function (pair) {
      remember("host:" + pair[0], pair[0], pair[1], "有詐騙相關內容的文章裡，出現這個網站的篇數。同一篇只算一次。");
    });
    horizontalBars(
      "linkBar",
      "links",
      top.map(function (pair) { return pair[0]; }),
      top.map(function (pair) { return pair[1].length; }),
      top.map(function (pair) { return "host:" + pair[0]; }),
      top.map(function () { return "#fb923c"; })
    );
    document.getElementById("linkTable").innerHTML = top.map(function (pair) {
      const id = "host:" + pair[0];
      const selected = selectedId() === id ? " is-selected" : "";
      return "<tr><td><button type=\"button\" class=\"" + selected.trim() + "\" data-select=\"" + escapeHtml(id) + "\">" + escapeHtml(pair[0]) + "</button></td><td>" + pair[1].length + "</td></tr>";
    }).join("");
  }

  function articleCard(row) {
    const bits = ['<article class="article"><h3>' + escapeHtml(row.title) + "</h3><p>"];
    bits.push('<span class="tag">' + row.phase + "</span>");
    bits.push('<span class="tag">' + escapeHtml(row.board) + "</span>");
    if (row.phase === "第二階段") {
      bits.push('<span class="tag warn">' + (row.grade ? "A／B／C：" + row.grade : "尚未審查") + "</span>");
      if (row.stage1Flag) bits.push('<span class="tag old">' + escapeHtml(row.stage1Flag) + "</span>");
      bits.push("</p><p>搜尋 keyword：" + escapeHtml(row.keywords.join("、") || "—") + "</p>");
    } else if (!row.complete) {
      bits.push('<span class="tag warn">尚未審查</span></p><p>這篇還沒填完，所以沒有內容判斷。這不是「沒有詐騙相關內容」，也不是 Clean。</p>');
    } else {
      bits.push('<span class="tag">內容：' + contentLabel(row.contentRelevant) + "</span>");
      bits.push('<span class="tag">網址：' + urlLabel(row.urlRelevant) + "</span>");
      bits.push('<span class="tag">' + escapeHtml(row.status || "—") + "</span></p>");
      bits.push("<p>人工 keyword：" + escapeHtml(row.keywords.join("、") || "—") + "</p>");
    }
    if (row.url) bits.push('<p><a href="' + escapeHtml(row.url) + '" target="_blank" rel="noopener">' + escapeHtml(row.url) + "</a></p>");
    if (row.content) bits.push("<pre>" + escapeHtml(row.content.slice(0, 700)) + (row.content.length > 700 ? "…" : "") + "</pre>");
    bits.push("</article>");
    return bits.join("");
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function renderExplorer() {
    const title = document.getElementById("explorerTitle");
    const meta = document.getElementById("explorerMeta");
    const list = document.getElementById("explorerList");
    const pager = document.getElementById("explorerPager");
    if (!selection) {
      title.textContent = "文章探索";
      meta.textContent = "點圓餅圖、關鍵字或網域，這裡列出對應文章。";
      list.innerHTML = "";
      pager.innerHTML = "";
      return;
    }
    title.textContent = selection.title;
    const total = selection.rows.length;
    const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (page >= pages) page = pages - 1;
    const start = page * PAGE_SIZE;
    const slice = selection.rows.slice(start, start + PAGE_SIZE);
    meta.textContent = (selection.note ? selection.note + " " : "") + (total ? "共 " + total + " 篇，現在顯示 " + (start + 1) + "–" + (start + slice.length) + "。" : "沒有可列出的 PTT 文章。");
    list.innerHTML = slice.map(articleCard).join("") || "<p class=\"caption\">此項目不是文章清單。</p>";
    pager.innerHTML = pages > 1
      ? '<button type="button" id="prevPage" class="btn"' + (page === 0 ? " disabled" : "") + '>上一頁</button><button type="button" id="nextPage" class="btn"' + (page >= pages - 1 ? " disabled" : "") + ">下一頁</button>"
      : "";
    const prev = document.getElementById("prevPage");
    const next = document.getElementById("nextPage");
    if (prev) prev.addEventListener("click", function () { page -= 1; renderExplorer(); });
    if (next) next.addEventListener("click", function () { page += 1; renderExplorer(); });
  }

  function render() {
    destroyCharts();
    chartDefaults();
    dashboard.hidden = false;
    loading.hidden = true;
    document.querySelectorAll("[data-panel]").forEach(function (panel) { panel.hidden = false; });
    model.selections = {};
    renderCounts();
    renderKeywords();
    renderLinks();
    if (selection && model.selections[selection.id]) selection = model.selections[selection.id];
    renderExplorer();
    showView(activeView);
  }

  function choose(id) {
    const next = model.selections[id];
    if (!next) return;
    selection = next;
    page = 0;
    render();
    document.getElementById("explorer").scrollIntoView({ block: "nearest" });
  }

  async function load() {
    loading.hidden = false;
    loadError.hidden = true;
    dashboard.hidden = true;
    const itemsUrl = cfg.ITEMS_CSV_URL || "items.csv";
    const stage2Url = cfg.STAGE2_ITEMS_CSV_URL || "stage2_items.csv";
    const [items, stage2Rows, answers1, answers2, npaPayload] = await Promise.all([
      parseCsv(itemsUrl),
      parseCsv(stage2Url),
      fetchAnswers(cfg.DATASET_ID || "ptt_candidate"),
      fetchAnswers(cfg.STAGE2_DATASET_ID || "ptt_stage2_keyword"),
      fetch("npa_type_counts.json").then(function (response) {
        if (!response.ok) throw new Error("無法讀取 165 彙總");
        return response.json();
      }),
    ]);
    npa = npaPayload;
    model = buildModel(items, stage2Rows, answers1, answers2);
    render();
  }

  window.addEventListener("resize", function () {
    chartInstances.forEach(function (chart) { chart.resize(); });
  });

  document.getElementById("sideNav").addEventListener("click", function (event) {
    const button = event.target.closest("[data-view]");
    if (!button) return;
    showView(button.getAttribute("data-view"));
    document.body.classList.remove("nav-open");
    document.getElementById("navScrim").hidden = true;
    document.getElementById("menuBtn").setAttribute("aria-expanded", "false");
  });

  document.getElementById("menuBtn").addEventListener("click", function () {
    const open = document.body.classList.toggle("nav-open");
    document.getElementById("navScrim").hidden = !open;
    document.getElementById("menuBtn").setAttribute("aria-expanded", open ? "true" : "false");
  });

  document.getElementById("navScrim").addEventListener("click", function () {
    document.body.classList.remove("nav-open");
    document.getElementById("navScrim").hidden = true;
    document.getElementById("menuBtn").setAttribute("aria-expanded", "false");
  });

  document.getElementById("dashboard").addEventListener("click", function (event) {
    const button = event.target.closest("[data-select]");
    if (!button) return;
    choose(button.getAttribute("data-select"));
  });

  document.getElementById("reloadBtn").addEventListener("click", function () {
    load().catch(function (err) {
      loadError.hidden = false;
      loadError.textContent = err.message || String(err);
    });
  });

  load().catch(function (err) {
    loadError.hidden = false;
    loadError.textContent = err.message || String(err);
    loading.hidden = true;
  });
})();
