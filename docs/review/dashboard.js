(function () {
  const cfg = window.REVIEW_CONFIG || {};
  const SESSION_KEY = "ptt_review_auth_v1";
  const PRIORITY = ["網拍詐騙", "約定轉帳", "簡訊詐騙", "ATM詐騙", "三方詐騙", "釣魚網站", "假冒警察", "解除分期付款"];
  const PAGE_SIZE = 12;

  const loginView = document.getElementById("loginView");
  const appView = document.getElementById("appView");
  const loginForm = document.getElementById("loginForm");
  const loginError = document.getElementById("loginError");
  const loading = document.getElementById("loading");
  const loadError = document.getElementById("loadError");
  const dashboard = document.getElementById("dashboard");

  let model = null;
  let npa = null;
  let selection = null;
  let page = 0;
  let supabase = null;
  let chartInstances = [];
  let activeView = "overview";
  const VIEW_TITLES = {
    overview: "總覽",
    progress: "審查進度",
    judgments: "第一階段審查",
    keywords: "人工 Keyword",
    stage2: "第二階段 Keyword",
    npa: "165 官方名單",
    quality: "資料品質",
  };
  const PALETTE = ["#5eead4", "#60a5fa", "#fbbf24", "#fb7185", "#a78bfa", "#34d399", "#fb923c", "#38bdf8", "#f472b6", "#a3e635"];

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
    if (value === "yes") return "有";
    if (value === "no") return "沒有";
    return "未填";
  }

  function urlLabel(value) {
    if (value === "yes") return "有";
    if (value === "no") return "沒有";
    if (value === "none") return "無 URL";
    return "未填";
  }

  function showLogin(message) {
    appView.hidden = true;
    loginView.hidden = false;
    if (message) {
      loginError.hidden = false;
      loginError.textContent = message;
    } else {
      loginError.hidden = true;
    }
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

  function countBy(rows, getKey) {
    const map = new Map();
    rows.forEach(function (row) {
      const key = getKey(row) || "（空白）";
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(row);
    });
    return Array.from(map.entries()).sort(function (a, b) { return b[1].length - a[1].length; });
  }

  function buildModel(items, stage2Rows, answers1, answers2) {
    const stage1 = items.filter(function (row) { return String(row.review_id || "").trim(); }).map(function (row) {
      return toStage1(row, answers1);
    });
    const stage2 = stage2Rows.filter(function (row) { return String(row.review_id || "").trim(); }).map(function (row) {
      return toStage2(row, answers2);
    });
    const stage1Urls = new Set(stage1.map(function (row) { return row.canon; }).filter(Boolean));
    const overlap = stage2.filter(function (row) { return row.canon && stage1Urls.has(row.canon); });
    const complete = stage1.filter(function (row) { return row.complete; });
    const keywordMap = new Map();
    complete.forEach(function (row) {
      row.keywords.forEach(function (keyword) {
        if (!keywordMap.has(keyword)) keywordMap.set(keyword, []);
        keywordMap.get(keyword).push(row);
      });
    });
    const keywordRank = Array.from(keywordMap.entries()).sort(function (a, b) {
      return b[1].length - a[1].length || a[0].localeCompare(b[0], "zh-Hant");
    });
    return { stage1: stage1, stage2: stage2, overlap: overlap, complete: complete, keywordRank: keywordRank };
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
          label: "篇數或列數",
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

  function renderProgress() {
    const incomplete = model.stage1.filter(function (row) { return !row.complete; });
    const stage2Reviewed = model.stage2.filter(function (row) { return row.grade; });
    const stage2Pending = model.stage2.filter(function (row) { return !row.grade; });
    remember("s1-all", "第一階段清單", model.stage1, "items.csv 全部列。未審查不是 Clean。");
    remember("s1-done", "第一階段已完成", model.complete, "內容與 URL 都已填，且選「有」時有 keyword。");
    remember("s1-todo", "第一階段未完成", incomplete, "含尚未儲存答案，以及答案未填完的文章。這不是 Clean。");
    remember("s2-all", "第二階段清單", model.stage2, "stage2_items.csv。A／B／C 與第一階段的有／沒有分開。");
    remember("s2-done", "第二階段已有 A／B／C", stage2Reviewed, "只計算第二階段答案裡的 A、B、C。");
    remember("s2-todo", "第二階段尚未審查", stage2Pending, "沒有 A／B／C 答案。不是 Clean，也不是第一階段的「沒有」。");
    const stage1Labels = ["已完成", "未完成"];
    const stage1Values = [model.complete.length, incomplete.length];
    const stage1Ids = ["s1-done", "s1-todo"];
    const stage1Colors = ["#5eead4", "#64748b"];
    const stage2Labels = ["已審查", "尚未審查"];
    const stage2Values = [stage2Reviewed.length, stage2Pending.length];
    const stage2Ids = ["s2-done", "s2-todo"];
    const stage2Colors = ["#a3e635", "#94a3b8"];
    doughnut("ovStage1", "overview", stage1Labels, stage1Values, stage1Ids, stage1Colors);
    doughnut("ovStage2", "overview", stage2Labels, stage2Values, stage2Ids, stage2Colors);
    doughnut("prStage1", "progress", stage1Labels, stage1Values, stage1Ids, stage1Colors);
    doughnut("prStage2", "progress", stage2Labels, stage2Values, stage2Ids, stage2Colors);
    document.getElementById("overviewNote").textContent =
      "第一階段清單 " + model.stage1.length + " 篇，已完成 " + model.complete.length + "、未完成 " + incomplete.length +
      "。第二階段清單 " + model.stage2.length + " 篇，已審查 " + stage2Reviewed.length + "、尚未審查 " + stage2Pending.length + "。";
  }

  function renderJudgments() {
    const content = countBy(model.complete, function (row) { return contentLabel(row.contentRelevant); });
    const urls = countBy(model.complete, function (row) { return urlLabel(row.urlRelevant); });
    const statuses = countBy(model.complete, function (row) { return row.status || "（空白）"; });
    content.forEach(function (pair) {
      remember("content:" + pair[0], "內容" + pair[0], pair[1], "已完成審查的篇數");
    });
    urls.forEach(function (pair) {
      remember("url:" + pair[0], "URL " + pair[0], pair[1], "已完成審查的篇數");
    });
    statuses.forEach(function (pair) {
      remember("status:" + pair[0], pair[0], pair[1], "已完成審查的篇數。temp 與 non_match 都不是 Spam／Clean。");
    });
    doughnut("pieContent", "judgments", content.map(function (pair) { return pair[0]; }), content.map(function (pair) { return pair[1].length; }), content.map(function (pair) { return "content:" + pair[0]; }), ["#34d399", "#fb7185", "#94a3b8"]);
    doughnut("pieUrl", "judgments", urls.map(function (pair) { return pair[0]; }), urls.map(function (pair) { return pair[1].length; }), urls.map(function (pair) { return "url:" + pair[0]; }), ["#a78bfa", "#fbbf24", "#60a5fa"]);
    doughnut("pieStatus", "judgments", statuses.map(function (pair) { return pair[0]; }), statuses.map(function (pair) { return pair[1].length; }), statuses.map(function (pair) { return "status:" + pair[0]; }), ["#38bdf8", "#fb923c", "#e879f9"]);
  }

  function renderKeywords() {
    const top40 = model.keywordRank.slice(0, 40);
    const top20 = model.keywordRank.slice(0, 20);
    const max = top40.length ? top40[0][1].length : 1;
    document.getElementById("wordCloud").innerHTML = top40.map(function (pair) {
      const id = "kw:" + pair[0];
      remember(id, "Keyword：" + pair[0], pair[1], "已完成審查中，寫到這個詞的篇數。同一篇只算一次。");
      const size = 13 + Math.round((pair[1].length / max) * 26);
      const selected = selectedId() === id ? " is-selected" : "";
      return '<button type="button" class="cloud-word' + selected + '" data-select="' + id + '" style="font-size:' + size + 'px">' + pair[0] + '</button>';
    }).join("");
    top20.forEach(function (pair) {
      remember("kw:" + pair[0], "Keyword：" + pair[0], pair[1], "已完成審查中寫到這個詞的篇數。同一篇只算一次。");
    });
    horizontalBars(
      "keywordBar",
      "keywords",
      top20.map(function (pair) { return pair[0]; }),
      top20.map(function (pair) { return pair[1].length; }),
      top20.map(function (pair) { return "kw:" + pair[0]; }),
      top20.map(function (pair, index) { return PALETTE[index % PALETTE.length]; })
    );
  }

  function renderStage2() {
    const grades = { A: 0, B: 0, C: 0 };
    model.stage2.forEach(function (row) { if (row.grade) grades[row.grade] += 1; });
    const pending = model.stage2.length - grades.A - grades.B - grades.C;
    document.getElementById("stage2ReviewLine").textContent =
      "A／B／C 尚未審查 " + pending + " 篇。已填 A " + grades.A + "、B " + grades.B + "、C " + grades.C + "。沒有答案時不會自動填寫。";
    const series = PRIORITY.map(function (keyword) {
      const rows = model.stage2.filter(function (row) { return row.keywords.indexOf(keyword) >= 0; });
      const fresh = rows.filter(function (row) { return row.stage1Flag === "新文章"; });
      const old = rows.filter(function (row) { return row.stage1Flag === "第一階段已存在"; });
      const other = rows.filter(function (row) { return row.stage1Flag !== "新文章" && row.stage1Flag !== "第一階段已存在"; });
      remember("p8:" + keyword + ":all", keyword + " 全部", rows, "第二階段這個 keyword 的文章。");
      remember("p8:" + keyword + ":new", keyword + " 新文章", fresh, "stage1_flag 為新文章。");
      remember("p8:" + keyword + ":old", keyword + " 第一階段已存在", old, "網址已在第一階段 CSV。仍留在第二階段清單。");
      return { keyword: keyword, rows: rows, fresh: fresh, old: old, other: other };
    });
    addChart("stage2Bar", "stage2", {
      type: "bar",
      data: {
        labels: series.map(function (item) { return item.keyword; }),
        datasets: [
          { label: "新文章", data: series.map(function (item) { return item.fresh.length; }), backgroundColor: "#5eead4" },
          { label: "第一階段已存在", data: series.map(function (item) { return item.old.length; }), backgroundColor: "#fbbf24" },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true },
          y: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: "文章數（篇）" } },
        },
        onClick: function (event, elements) {
          if (!elements.length) return;
          const item = series[elements[0].index];
          choose(elements[0].datasetIndex === 1 ? "p8:" + item.keyword + ":old" : "p8:" + item.keyword + ":new");
        },
      },
    });
  }

  function renderNpa() {
    const caption = document.getElementById("npaCaption");
    if (!npa) {
      caption.textContent = "找不到 npa_type_counts.json。";
      return;
    }
    caption.textContent = "來源 " + npa.source_file + " 的「" + npa.source_field + "」，單位是 " + npa.unit + "。快照日期 " + npa.snapshot_date + "，共 " + npa.row_total + " 列、" + npa.unique_host_total + " 個不重複網域；" + npa.hosts_with_multiple_types + " 個網域有一種以上性質，所以各類列數不能換成網域數後相加。線上偵測用的 " + npa.runtime_blacklist_file + " 沒有網站性質欄。第一階段 " + npa.stage1_articles_checked + " 篇與第二階段 " + npa.stage2_articles_checked + " 篇的正文網域，對這份名單和 165 黑名單的精確網域命中都是 " + npa.stage1_articles_exact_host_in_npa + "／" + npa.stage2_articles_exact_host_in_npa + " 與 " + npa.stage1_articles_exact_host_in_165 + "／" + npa.stage2_articles_exact_host_in_165 + "。新聞網域不會出現在這張圖。";
    npa.counts.forEach(function (item) {
      const id = "npa:" + item.type;
      model.selections[id] = {
        id: id,
        title: "官方名單：" + item.type,
        rows: [],
        note: item.type + " 有 " + item.rows + " 列。這是官方 165 名單的列數，不是 PTT 文章，也不是文章裡出現的詐騙網域。",
      };
    });
    horizontalBars(
      "npaBar",
      "npa",
      npa.counts.map(function (item) { return item.type; }),
      npa.counts.map(function (item) { return item.rows; }),
      npa.counts.map(function (item) { return "npa:" + item.type; }),
      npa.counts.map(function (item, index) { return PALETTE[index % PALETTE.length]; })
    );
  }

  function duplicateGroups(rows) {
    const map = new Map();
    rows.forEach(function (row) {
      if (!row.canon) return;
      if (!map.has(row.canon)) map.set(row.canon, []);
      map.get(row.canon).push(row);
    });
    const groups = [];
    map.forEach(function (list) {
      if (list.length > 1) groups.push(list);
    });
    return groups;
  }

  function renderQuality() {
    const dup1 = duplicateGroups(model.stage1);
    const dup2 = duplicateGroups(model.stage2);
    const dup1Rows = dup1.reduce(function (all, list) { return all.concat(list); }, []);
    const dup2Rows = dup2.reduce(function (all, list) { return all.concat(list); }, []);
    const multiHuman = model.complete.filter(function (row) { return row.keywords.length >= 2; });
    const multiSearch = model.stage2.filter(function (row) { return row.keywords.length >= 2; });
    const union = new Set(model.stage1.map(function (row) { return row.canon; }).concat(model.stage2.map(function (row) { return row.canon; })));
    remember("dup1", "第一階段重複網址", dup1Rows, "同一正規化 URL 出現超過一次的列。");
    remember("dup2", "第二階段重複網址", dup2Rows, "同一正規化 URL 出現超過一次的列。");
    remember("overlap", "兩階段網址重疊", model.overlap, "這些第二階段文章的 URL 已在第一階段清單。合併篇數時只算一次，這裡仍列出以便對照。");
    remember("multi-human", "第一階段一篇多個人工 Keyword", multiHuman, "已完成審查且 keyword 至少兩個。");
    remember("multi-search", "第二階段一篇多個搜尋 Keyword", multiSearch, "search_keyword 以「、」拆開後至少兩個。");
    document.getElementById("qualityStats").innerHTML = [
      statButton("dup1", dup1.length, "第一階段重複網址（組）"),
      statButton("dup2", dup2.length, "第二階段重複網址（組）"),
      statButton("overlap", model.overlap.length, "兩階段網址重疊（篇）"),
      statButton("multi-human", multiHuman.length, "已完成且含 2 個以上人工 Keyword"),
      statButton("multi-search", multiSearch.length, "第二階段含 2 個以上搜尋 Keyword"),
      '<div class="stat"><strong>' + union.size + '</strong><span>去重後聯集（篇）</span></div>',
    ].join("");
    const boards1 = countBy(model.stage1, function (row) { return row.board; });
    const boards2 = countBy(model.stage2, function (row) { return row.board; });
    boards1.forEach(function (pair) { remember("b1:" + pair[0], pair[0], pair[1], "第一階段清單篇數"); });
    boards2.forEach(function (pair) { remember("b2:" + pair[0], pair[0], pair[1], "第二階段清單篇數"); });
    horizontalBars("board1", "quality", boards1.map(function (pair) { return pair[0]; }), boards1.map(function (pair) { return pair[1].length; }), boards1.map(function (pair) { return "b1:" + pair[0]; }), ["#5eead4", "#60a5fa", "#fbbf24", "#fb7185"]);
    horizontalBars("board2", "quality", boards2.map(function (pair) { return pair[0]; }), boards2.map(function (pair) { return pair[1].length; }), boards2.map(function (pair) { return "b2:" + pair[0]; }), ["#a78bfa", "#34d399", "#fb923c", "#38bdf8"]);
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
      bits.push('<span class="tag warn">未審查</span></p><p>內容與 URL 判斷：未審查。這不是「沒有」或 Clean。</p>');
    } else {
      bits.push('<span class="tag">內容' + contentLabel(row.contentRelevant) + "</span>");
      bits.push('<span class="tag">URL ' + urlLabel(row.urlRelevant) + "</span>");
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
      meta.textContent = "點進度、長條、詞雲或 keyword，這裡列出對應文章。官方名單的網站性質沒有 PTT 文章可列。";
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
    renderProgress();
    renderJudgments();
    renderKeywords();
    renderStage2();
    renderNpa();
    renderQuality();
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

  loginForm.addEventListener("submit", function (event) {
    event.preventDefault();
    const expected = String(cfg.REVIEW_PASSWORD || "");
    if (!expected || document.getElementById("passwordInput").value !== expected) {
      showLogin("密碼錯誤");
      return;
    }
    sessionStorage.setItem(SESSION_KEY, "1");
    document.getElementById("passwordInput").value = "";
    loginView.hidden = true;
    appView.hidden = false;
    load().catch(function (err) {
      loadError.hidden = false;
      loadError.textContent = err.message || String(err);
      loading.hidden = true;
    });
  });

  if (sessionStorage.getItem(SESSION_KEY) === "1") {
    loginView.hidden = true;
    appView.hidden = false;
    load().catch(function (err) {
      loadError.hidden = false;
      loadError.textContent = err.message || String(err);
      loading.hidden = true;
    });
  } else {
    showLogin();
  }
})();
