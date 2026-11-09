(function () {
  const cfg = window.REVIEW_CONFIG || {};
  const PAGE_SIZE = 12;
  const LINK_LIMIT = 15;

  const loading = document.getElementById("loading");
  const loadError = document.getElementById("loadError");
  const dashboard = document.getElementById("dashboard");

  let model = null;
  let npa = null;
  let catalog = null;
  let selection = null;
  let page = 0;
  let casePage = 0;
  let supabase = null;
  let chartInstances = [];
  let activeView = "overview";
  const DATASET_LABELS = {
    ptt_crawl: "PTT 爬蟲",
    stage1: "第一階段",
    stage2: "第二階段",
    team_keywords: "team keywords",
  };
  const VIEW_TITLES = {
    overview: "資料總覽",
    overlap: "清單交叉",
    years: "年份",
    sources: "來源",
    review: "人工審查",
    official: "官方名單",
    cases: "案例查詢",
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
    if (row.catalogStatus) {
      bits.push('<span class="tag">' + escapeHtml(row.catalogStatus) + "</span></p>");
      if (row.catalogNote) bits.push("<p>" + escapeHtml(row.catalogNote) + "</p>");
    } else if (row.phase === "第二階段") {
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

  function datasetName(id) {
    return DATASET_LABELS[id] || id;
  }

  function stageMaps() {
    const stage1 = {};
    const stage2 = {};
    model.stage1.forEach(function (row) { stage1[row.reviewId] = row; });
    model.stage2.forEach(function (row) { stage2[row.reviewId] = row; });
    return { stage1: stage1, stage2: stage2 };
  }

  function articleReview(article, maps) {
    const parts = [];
    const first = article.stage1_review_id ? maps.stage1[article.stage1_review_id] : null;
    const second = article.stage2_review_id ? maps.stage2[article.stage2_review_id] : null;
    if (first) {
      if (!first.complete) parts.push({ id: "stage1_todo", text: "第一階段尚未審查" });
      else if (first.contentRelevant === "yes") parts.push({ id: "stage1_yes", text: "有詐騙相關內容" });
      else if (first.contentRelevant === "no") parts.push({ id: "stage1_no", text: "沒有詐騙相關內容" });
      else parts.push({ id: "stage1_other", text: "第一階段已填答" });
    }
    if (second) {
      if (second.grade) parts.push({ id: "stage2_graded", text: "第二階段 " + second.grade });
      else parts.push({ id: "stage2_todo", text: "第二階段尚未審查" });
    }
    if (!first && !second) parts.push({ id: "not_in_review", text: "未進入審查清單" });
    if (article.official_exact_status) parts.push({ id: "official_exact", text: "exact_match" });
    return parts;
  }

  function catalogArticleRow(article, maps) {
    const parts = articleReview(article, maps);
    return {
      phase: "研究清單",
      title: article.title || "（無標題）",
      board: (article.boards || []).join("、") || "—",
      url: article.url,
      content: "",
      catalogStatus: parts.map(function (part) { return part.text; }).join("、"),
      catalogNote: "出現在：" + article.datasets.map(datasetName).join("、") + (article.year ? "。年份 " + article.year : "。沒有可解析的日期"),
    };
  }

  function renderCatalog() {
    if (!catalog) return;
    const byId = {};
    catalog.datasets.forEach(function (item) { byId[item.id] = item; });
    document.getElementById("overviewTable").innerHTML = catalog.datasets.map(function (item) {
      return "<tr><td>" + escapeHtml(item.label) + "</td><td>" + item.rows + "</td><td>" + escapeHtml(item.source) + "</td><td>" + escapeHtml(item.file_updated_at) + "</td></tr>";
    }).join("");
    document.getElementById("overviewUnion").textContent =
      "四份清單去掉重複網址後有 " + catalog.overlap.union_urls + " 個文章網址。這不是案例總數，也不是把 " +
      catalog.datasets.map(function (item) { return item.rows; }).join("、") + " 加總。";
    document.getElementById("overlapTable").innerHTML = catalog.overlap.pairs.map(function (pair) {
      return "<tr><td>" + escapeHtml(datasetName(pair.a) + " × " + datasetName(pair.b)) + "</td><td>" + pair.both + "</td><td>" + pair.only_a + "</td><td>" + pair.only_b + "</td></tr>";
    }).join("");
    const onlyText = Object.keys(catalog.overlap.only).map(function (key) {
      return datasetName(key) + " " + catalog.overlap.only[key] + " 篇";
    }).join("、");
    document.getElementById("overlapNote").textContent =
      "扣掉另外三份之後，只出現在單一一份清單的文章：" + onlyText + "。第二階段旗標和第一階段網址不一致的有 " + catalog.overlap.stage1_flag_mismatches + " 篇。";

    const years = catalog.years;
    document.getElementById("yearMissing").textContent = "日期無法解析或空白：" + years.missing + " 篇。長條圖合計 " + years.counts.reduce(function (sum, item) { return sum + item.rows; }, 0) + " 篇。";
    horizontalBars(
      "yearChart",
      "years",
      years.counts.map(function (item) { return String(item.year); }),
      years.counts.map(function (item) { return item.rows; }),
      years.counts.map(function () { return ""; }),
      years.counts.map(function () { return "#60a5fa"; })
    );

    document.getElementById("sourceCaption").textContent =
      "看板和 PTT 搜尋關鍵字只算 " + byId.ptt_crawl.source + " 的 " + byId.ptt_crawl.rows + " 篇。team keywords 來自 " + byId.team_keywords.source + "，共 " + byId.team_keywords.rows + " 篇，是另一份搜尋結果。";
    horizontalBars(
      "boardChart",
      "sources",
      catalog.boards.counts.map(function (item) { return item.name; }),
      catalog.boards.counts.map(function (item) { return item.rows; }),
      catalog.boards.counts.map(function () { return ""; }),
      ["#5eead4", "#60a5fa", "#fbbf24", "#fb7185"]
    );
    horizontalBars(
      "crawlKeywordChart",
      "sources",
      catalog.search_keywords.counts.map(function (item) { return item.name; }),
      catalog.search_keywords.counts.map(function (item) { return item.rows; }),
      catalog.search_keywords.counts.map(function () { return ""; }),
      ["#34d399", "#fbbf24", "#a78bfa"]
    );
    const teamTop = catalog.team_search_keywords.counts.slice(0, 15);
    horizontalBars(
      "teamKeywordChart",
      "sources",
      teamTop.map(function (item) { return item.name; }),
      teamTop.map(function (item) { return item.rows; }),
      teamTop.map(function () { return ""; }),
      teamTop.map(function () { return "#a78bfa"; })
    );

    const incomplete = model.stage1.filter(function (row) { return !row.complete; });
    doughnut(
      "reviewChart",
      "review",
      ["有詐騙相關內容", "沒有詐騙相關內容", "尚未審查"],
      [model.contentYes.length, model.contentNo.length, incomplete.length],
      ["count:yes", "count:no", "count:todo"],
      ["#5eead4", "#fbbf24", "#64748b"]
    );
    document.getElementById("reviewStats").innerHTML = [
      statButton("count:yes", model.contentYes.length, "有詐騙相關內容"),
      statButton("count:no", model.contentNo.length, "沒有詐騙相關內容"),
      statButton("count:todo", incomplete.length, "第一階段尚未審查"),
    ].join("");
    const exactArticles = catalog.articles.filter(function (article) { return article.official_exact_status; });
    remember("official-exact", "文章狀態 exact_match", exactArticles.map(function (article) { return catalogArticleRow(article, stageMaps()); }), "這是官方比對後的文章狀態，不是審查者勾選的「有詐騙相關內容」。");
    document.getElementById("reviewOfficial").innerHTML =
      "官方比對的 exact_match 有 " + catalog.official.article_exact_status + " 篇，停止解析名單的精確網址列數是 " + catalog.official.weburl_exact_url_rows + "。" +
      " <button type=\"button\" class=\"text-link\" data-select=\"official-exact\">查看 exact_match 文章</button>";

    const official = catalog.official;
    const sameFake = exactArticles.length > 0 && exactArticles.every(function (article) { return article.official_fake_invest_match; });
    const rows = [
      [official.weburl.label, official.weburl.rows + " 列／" + official.weburl.unique_hosts + " 個不重複網域值", official.weburl.meaning + official.weburl.host_rule + " 快照 " + official.weburl.snapshot_date + "。"],
      [official.fake_invest.label, official.fake_invest.rows + " 列／" + official.fake_invest.unique_hosts + " 個不重複網域", official.fake_invest.meaning + " 快照 " + official.fake_invest.snapshot_date + "。"],
      [official.runtime_blacklist.label, official.runtime_blacklist.rows + " 列／" + official.runtime_blacklist.unique_hosts + " 個不重複網域", official.runtime_blacklist.meaning],
      ["停止解析名單精確網址列", String(official.weburl_exact_url_rows), "從 PTT 文章抽出的網址，精確命中停止解析名單的列數。"],
      ["文章狀態 exact_match", String(official.article_exact_status), "交叉比對寫入的文章狀態。不是審查圓餅圖的一部分。" + (sameFake ? " 這幾篇同時命中假投資名單。" : "")],
      ["假投資名單命中文章", String(official.fake_invest_match_articles), "文章網址對上假投資名單的篇數。"],
      ["模糊比對", official.fuzzy_url_rows + " 個網址列／" + official.fuzzy_articles + " 篇文章", official.fuzzy_meaning],
    ];
    document.getElementById("officialTable").innerHTML = rows.map(function (row) {
      return "<tr><td>" + escapeHtml(row[0]) + "</td><td>" + escapeHtml(row[1]) + "</td><td>" + escapeHtml(row[2]) + "</td></tr>";
    }).join("");
    renderCases();
  }

  function filteredArticles() {
    const maps = stageMaps();
    const query = document.getElementById("caseQuery").value.trim().toLowerCase();
    const dataset = document.getElementById("caseDataset").value;
    const review = document.getElementById("caseReview").value;
    return catalog.articles.filter(function (article) {
      if (dataset !== "all" && article.datasets.indexOf(dataset) < 0) return false;
      const parts = articleReview(article, maps);
      if (review !== "all" && !parts.some(function (part) { return part.id === review; })) return false;
      if (!query) return true;
      return (article.title || "").toLowerCase().indexOf(query) >= 0 || (article.url || "").toLowerCase().indexOf(query) >= 0;
    });
  }

  function renderCases() {
    if (!catalog || !model) return;
    const maps = stageMaps();
    const rows = filteredArticles().sort(function (a, b) { return (b.year || 0) - (a.year || 0); });
    const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    if (casePage >= pages) casePage = pages - 1;
    if (casePage < 0) casePage = 0;
    const start = casePage * PAGE_SIZE;
    const slice = rows.slice(start, start + PAGE_SIZE);
    document.getElementById("caseMeta").textContent = "符合條件 " + rows.length + " 篇，現在顯示 " + (rows.length ? start + 1 : 0) + "–" + (start + slice.length) + "。每頁 " + PAGE_SIZE + " 篇。";
    document.getElementById("caseTable").innerHTML = slice.map(function (article) {
      const parts = articleReview(article, maps);
      const id = "case:" + article.case_id;
      remember(id, article.title || "（無標題）", [catalogArticleRow(article, maps)], parts.map(function (part) { return part.text; }).join("、"));
      const when = article.year ? String(article.year) : "日期缺失";
      return "<tr><td><button type=\"button\" data-select=\"" + escapeHtml(id) + "\">" + escapeHtml(article.title || "（無標題）") + "</button></td><td>" +
        escapeHtml(article.datasets.map(datasetName).join("、")) + "</td><td>" + escapeHtml(when) + "</td><td><a href=\"" +
        escapeHtml(article.url) + "\" target=\"_blank\" rel=\"noopener\">" + escapeHtml(article.url) + "</a></td><td>" +
        escapeHtml(parts.map(function (part) { return part.text; }).join("、")) + "</td></tr>";
    }).join("");
    const pager = document.getElementById("casePager");
    pager.innerHTML = pages > 1
      ? '<button type="button" id="casePrev" class="btn"' + (casePage === 0 ? " disabled" : "") + ">上一頁</button><button type=\"button\" id=\"caseNext\" class=\"btn\"" + (casePage >= pages - 1 ? " disabled" : "") + ">下一頁</button>"
      : "";
    const prev = document.getElementById("casePrev");
    const next = document.getElementById("caseNext");
    if (prev) prev.addEventListener("click", function () { casePage -= 1; renderCases(); });
    if (next) next.addEventListener("click", function () { casePage += 1; renderCases(); });
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
    renderCatalog();
    renderCases();
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
    const [items, stage2Rows, answers1, answers2, npaPayload, catalogPayload] = await Promise.all([
      parseCsv(itemsUrl),
      parseCsv(stage2Url),
      fetchAnswers(cfg.DATASET_ID || "ptt_candidate"),
      fetchAnswers(cfg.STAGE2_DATASET_ID || "ptt_stage2_keyword"),
      fetch("npa_type_counts.json").then(function (response) {
        if (!response.ok) throw new Error("無法讀取 165 彙總");
        return response.json();
      }),
      fetch("research_catalog.json").then(function (response) {
        if (!response.ok) throw new Error("無法讀取研究清單彙總");
        return response.json();
      }),
    ]);
    npa = npaPayload;
    catalog = catalogPayload;
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

  ["caseQuery", "caseDataset", "caseReview"].forEach(function (id) {
    document.getElementById(id).addEventListener("input", function () {
      casePage = 0;
      renderCases();
    });
    document.getElementById(id).addEventListener("change", function () {
      casePage = 0;
      renderCases();
    });
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
