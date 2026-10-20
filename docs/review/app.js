(function () {
  const cfg = window.REVIEW_CONFIG || {};
  const loginView = document.getElementById("loginView");
  const appView = document.getElementById("appView");
  const passwordInput = document.getElementById("passwordInput");
  const loginBtn = document.getElementById("loginBtn");
  const loginError = document.getElementById("loginError");
  const logoutBtn = document.getElementById("logoutBtn");
  const refreshBtn = document.getElementById("refreshBtn");
  const prevBtn = document.getElementById("prevBtn");
  const nextBtn = document.getElementById("nextBtn");
  const jumpBtn = document.getElementById("jumpBtn");
  const saveBtn = document.getElementById("saveBtn");
  const humanNotes = document.getElementById("humanNotes");
  const reviewerInput = document.getElementById("reviewerInput");
  const keywordsInput = document.getElementById("keywordsInput");
  const saveStatus = document.getElementById("saveStatus");
  const emptyState = document.getElementById("emptyState");
  const reviewMain = document.getElementById("reviewMain");
  const lockedNotice = document.getElementById("lockedNotice");
  const donePill = document.getElementById("donePill");
  const doneByLine = document.getElementById("doneByLine");

  let items = [];
  let index = 0;
  let dirty = false;
  let refreshTimer = null;
  let supabase = null;
  const DATASETS = {
    ptt_candidate: {
      id: "ptt_candidate",
      eyebrow: "第一階段 Temp 審查",
      heading: "一筆一筆手動抽 Keyword",
      itemsUrl: cfg.ITEMS_CSV_URL || "items.csv",
      mode: "stage1",
    },
    ptt_stage2_keyword: {
      id: cfg.STAGE2_DATASET_ID || "ptt_stage2_keyword",
      eyebrow: "第二階段 Keyword 審查",
      heading: "依 A／B／C 人工審查",
      itemsUrl: cfg.STAGE2_ITEMS_CSV_URL || "stage2_items.csv",
      mode: "stage2",
    },
  };
  const DATASET_SESSION_KEY = "ptt_review_dataset_v1";
  let datasetId = sessionStorage.getItem(DATASET_SESSION_KEY) || cfg.DATASET_ID || "ptt_candidate";
  if (!DATASETS[datasetId]) datasetId = "ptt_candidate";
  const REFRESH_MS = 45000;
  const SESSION_KEY = "ptt_review_auth_v1";
  const GRADES = ["A", "B", "C"];

  function currentDataset() {
    return DATASETS[datasetId];
  }

  function isStage2() {
    return currentDataset().mode === "stage2";
  }

  function configReady() {
    return !!(
      cfg.SUPABASE_URL &&
      cfg.SUPABASE_ANON_KEY &&
      !String(cfg.SUPABASE_URL).includes("YOUR_PROJECT") &&
      !String(cfg.SUPABASE_ANON_KEY).includes("YOUR_SUPABASE")
    );
  }

  function getClient() {
    if (supabase) return supabase;
    if (!window.supabase || !window.supabase.createClient) {
      throw new Error("Supabase SDK 尚未載入");
    }
    if (!configReady()) {
      throw new Error("請先在 docs/review/config.js 填入 SUPABASE_URL 與 SUPABASE_ANON_KEY");
    }
    supabase = window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);
    return supabase;
  }

  function showLogin(message) {
    appView.hidden = true;
    loginView.hidden = false;
    if (message) {
      loginError.hidden = false;
      loginError.textContent = message;
    } else {
      loginError.hidden = true;
      loginError.textContent = "";
    }
  }

  function showApp() {
    loginView.hidden = true;
    appView.hidden = false;
  }

  function isAuthed() {
    return sessionStorage.getItem(SESSION_KEY) === "1";
  }

  function setAuthed(ok) {
    if (ok) sessionStorage.setItem(SESSION_KEY, "1");
    else sessionStorage.removeItem(SESSION_KEY);
  }

  function parseKeywordsText(text) {
    const lines = String(text || "")
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .replace(/\|/g, "\n")
      .replace(/、/g, "\n")
      .split("\n");
    const out = [];
    const seen = {};
    lines.forEach(function (line) {
      const keyword = line.trim();
      if (!keyword || seen[keyword]) return;
      seen[keyword] = true;
      out.push(keyword);
    });
    return out;
  }

  function keywordsToText(value) {
    if (Array.isArray(value)) return value.join("\n");
    return String(value || "");
  }

  function normalizeKeywords(value) {
    if (Array.isArray(value)) return parseKeywordsText(value.join("\n"));
    return parseKeywordsText(value);
  }

  function deriveLocalPttStatus(contentRelevant, urlRelevant, keywords) {
    if (keywords && keywords.length) return "temp";
    if (contentRelevant === "no" && (urlRelevant === "no" || urlRelevant === "none")) {
      return "non_match";
    }
    return "temp";
  }

  function isFilled(item) {
    if (!item) return false;
    if (isStage2()) {
      return GRADES.indexOf((item.content_relevant || "").trim()) >= 0;
    }
    const cr = (item.content_relevant || "").trim();
    const ur = (item.url_relevant || "").trim();
    if (!cr || !ur) return false;
    const keywords = normalizeKeywords(item.keywords);
    if (cr === "yes" || ur === "yes") return keywords.length > 0;
    return true;
  }

  function isLocked(item) {
    return !!(
      item &&
      (item.review_locked ||
        (isFilled(item) && (item.review_status || "").trim() === "reviewed"))
    );
  }

  function updateProgress() {
    const total = items.length;
    const done = items.filter(isFilled).length;
    const remaining = Math.max(total - done, 0);
    if (isStage2()) {
      const grades = { A: 0, B: 0, C: 0 };
      items.forEach(function (item) {
        const grade = (item.content_relevant || "").trim();
        if (grades[grade] !== undefined) grades[grade] += 1;
      });
      document.getElementById("progressText").textContent =
        "總共 " + total + " 篇 · 已審查 " + done + " · 未審查 " + remaining +
        " · A " + grades.A + " · B " + grades.B + " · C " + grades.C;
    } else {
      document.getElementById("progressText").textContent =
        "總共 " + total + " 篇 · 已完成 " + done + " · 剩 " + remaining;
    }
    let hint = isStage2()
      ? "A／B／C 與備註寫入 Supabase 的第二階段分類，不會改到第一階段"
      : "按「儲存」後寫入 Supabase，全組共用";
    if (dirty) hint = "有未儲存變更，請先按「儲存」";
    if (!total) hint = isStage2() ? "尚未載入第二階段清單" : "尚未匯入 PTT Temp 候選";
    document.getElementById("progressHint").textContent = hint;
    const pct = total ? Math.round((done / total) * 100) : 0;
    document.getElementById("progressBar").style.width = pct + "%";
  }

  function setFormDisabled(disabled) {
    document.querySelectorAll(".choice-grid button").forEach(function (btn) {
      btn.disabled = disabled;
    });
    if (keywordsInput) keywordsInput.disabled = disabled;
    humanNotes.disabled = disabled;
    reviewerInput.disabled = disabled;
    saveBtn.disabled = disabled;
    nextBtn.disabled = disabled;
  }

  function setChoice(field, value) {
    const root = document.querySelector('.choice-grid[data-field="' + field + '"]');
    if (!root) return;
    root.querySelectorAll("button").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-value") === value);
    });
  }

  function currentItem() {
    return items[index] || null;
  }

  function collectForm() {
    const item = currentItem();
    if (!item) return null;
    const contentBtn = document.querySelector(
      '.choice-grid[data-field="content_relevant"] button.active'
    );
    const urlBtn = document.querySelector(
      '.choice-grid[data-field="url_relevant"] button.active'
    );
    const keywords = parseKeywordsText(keywordsInput ? keywordsInput.value : "");
    const gradeBtn = document.querySelector(
      '.choice-grid[data-field="grade"] button.active'
    );
    return {
      content_relevant: contentBtn ? contentBtn.getAttribute("data-value") : "",
      url_relevant: urlBtn ? urlBtn.getAttribute("data-value") : "",
      keywords: keywords,
      grade: gradeBtn ? gradeBtn.getAttribute("data-value") : "",
      human_notes: humanNotes.value.trim(),
      reviewer: reviewerInput.value.trim(),
    };
  }

  function applyLocalFormToItem() {
    const item = currentItem();
    const form = collectForm();
    if (!item || !form) return;
    if (isStage2()) {
      item.content_relevant = form.grade;
      item.url_relevant = "";
      item.keywords = [];
      item.status = "stage2";
      item.human_notes = form.human_notes;
      item.reviewer = form.reviewer;
      item.review_status = isFilled(item) ? "reviewed" : "pending";
      return;
    }
    item.content_relevant = form.content_relevant;
    item.url_relevant = form.url_relevant;
    item.keywords = form.keywords;
    item.human_notes = form.human_notes;
    item.reviewer = form.reviewer;
    item.status = deriveLocalPttStatus(
      form.content_relevant,
      form.url_relevant,
      form.keywords
    );
    item.review_status = isFilled(item) ? "reviewed" : "pending";
    const pill = document.getElementById("pttStatusPill");
    if (pill) pill.textContent = item.status || "temp";
  }

  function markDirty() {
    dirty = true;
    updateProgress();
  }

  function renderEmpty() {
    emptyState.hidden = false;
    reviewMain.hidden = true;
    updateProgress();
  }

  function renderDoneBanner(item) {
    const locked = isLocked(item);
    donePill.hidden = !locked;
    if (locked) {
      const who = (item.reviewer || "").trim() || "（未留名）";
      doneByLine.hidden = false;
      doneByLine.textContent =
        "已完成 · 檢視者：" + who + (item.saved_at ? " · " + item.saved_at : "");
    } else {
      doneByLine.hidden = true;
      doneByLine.textContent = "";
    }
    lockedNotice.hidden = !locked;
    setFormDisabled(locked);
  }

  function render() {
    if (!items.length) {
      renderEmpty();
      return;
    }
    emptyState.hidden = true;
    reviewMain.hidden = false;

    const item = currentItem();
    if (!item) return;

    document.getElementById("itemId").textContent = "#" + item.review_id;
    document.getElementById("hostPill").textContent = item.source_board || "PTT";
    document.getElementById("itemTitle").textContent = item.title || "（無標題）";
    document.getElementById("itemDate").textContent = item.published_at || "—";
    document.getElementById("itemBoard").textContent = item.source_board || "—";
    document.getElementById("itemKeyword").textContent = item.search_keyword || "—";
    const stage1Pill = document.getElementById("stage1Pill");
    const pttAnnotate = document.getElementById("pttAnnotate");
    const stage2Annotate = document.getElementById("stage2Annotate");
    if (pttAnnotate) pttAnnotate.hidden = isStage2();
    if (stage2Annotate) stage2Annotate.hidden = !isStage2();
    if (isStage2()) {
      stage1Pill.hidden = false;
      stage1Pill.textContent = item.stage1_flag || "新文章";
      stage1Pill.classList.toggle("warn", item.stage1_flag === "第一階段已存在");
      setChoice("grade", GRADES.indexOf(item.content_relevant) >= 0 ? item.content_relevant : "");
    } else if (stage1Pill) {
      stage1Pill.hidden = true;
    }

    const articleLink = document.getElementById("articleLink");
    const openArticleBtn = document.getElementById("openArticleBtn");
    articleLink.href = item.article_url || "#";
    articleLink.textContent = item.article_url || "—";
    openArticleBtn.href = item.article_url || "#";

    const content = (item.content || "").trim();
    document.getElementById("itemContent").textContent = content
      ? content
      : "（此筆沒有對到正文，請改開 PTT 原文）";

    setChoice("content_relevant", item.content_relevant || "");
    setChoice("url_relevant", item.url_relevant || "");
    if (keywordsInput) keywordsInput.value = keywordsToText(item.keywords);
    const pill = document.getElementById("pttStatusPill");
    if (pill) pill.textContent = item.status || "temp";
    humanNotes.value = item.human_notes || "";
    reviewerInput.value = item.reviewer || "";
    dirty = false;
    saveStatus.textContent = "";
    renderDoneBanner(item);
    updateProgress();
  }

  function findNextUnfilled(fromIndex) {
    for (let i = fromIndex + 1; i < items.length; i += 1) {
      if (!isFilled(items[i])) return i;
    }
    for (let j = 0; j <= fromIndex; j += 1) {
      if (!isFilled(items[j])) return j;
    }
    return -1;
  }

  function rowToAnswer(row) {
    return {
      content_relevant: row.content_relevant || "",
      url_relevant: row.url_relevant || "",
      keywords: normalizeKeywords(row.keywords),
      status: row.status || "temp",
      human_notes: row.human_notes || "",
      reviewer: row.reviewer || "",
      review_status: row.review_status || "pending",
      article_type: row.article_type || "",
      saved_at: row.saved_at || "",
    };
  }

  async function fetchAnswersMap() {
    const client = getClient();
    const { data, error } = await client
      .from("ptt_review_answers")
      .select("*")
      .eq("dataset_id", datasetId);
    if (error) throw new Error(error.message || "讀取 Supabase 失敗");
    const map = {};
    (data || []).forEach(function (row) {
      if (row.review_id) map[String(row.review_id)] = rowToAnswer(row);
    });
    return map;
  }

  async function fetchOneAnswer(reviewId) {
    const client = getClient();
    const { data, error } = await client
      .from("ptt_review_answers")
      .select("*")
      .eq("dataset_id", datasetId)
      .eq("review_id", reviewId)
      .maybeSingle();
    if (error) throw new Error(error.message || "讀取單筆失敗");
    return data ? rowToAnswer(data) : null;
  }

  function loadItemsCsv() {
    const url = currentDataset().itemsUrl;
    return new Promise(function (resolve, reject) {
      if (!window.Papa) {
        reject(new Error("PapaParse 尚未載入"));
        return;
      }
      Papa.parse(url, {
        download: true,
        header: true,
        skipEmptyLines: true,
        complete: function (results) {
          if (results.errors && results.errors.length) {
            // Papa 對大檔偶發警告；有資料就繼續
            if (!results.data || !results.data.length) {
              reject(new Error(results.errors[0].message || "CSV 解析失敗"));
              return;
            }
          }
          resolve(results.data || []);
        },
        error: function (err) {
          reject(err || new Error("無法載入 items.csv"));
        },
      });
    });
  }

  function mergeItems(rows, answers) {
    const merged = [];
    rows.forEach(function (row) {
      const reviewId = String(row.review_id || "").trim();
      if (!reviewId) return;
      if (String(row.status || "temp").trim() === "exact_match") return;
      const answer = answers[reviewId] || {};
      const fields = {
        content_relevant: answer.content_relevant || "",
        url_relevant: answer.url_relevant || "",
        keywords: normalizeKeywords(answer.keywords),
        status: answer.status || row.status || "temp",
        human_notes: answer.human_notes || "",
        reviewer: answer.reviewer || "",
        review_status: answer.review_status || "pending",
        article_type: answer.article_type || "",
      };
      const item = {
        review_id: reviewId,
        article_id: reviewId,
        dataset_id: datasetId,
        title: row.title || "",
        article_url: row.article_url || "",
        url: row.article_url || "",
        content: row.content || "",
        published_at: row.published_at || "",
        source: row.source || "ptt",
        source_board: row.source_board || "",
        search_keyword: row.search_keyword || "",
        stage1_flag: row.stage1_flag || "",
        sort_order: row.sort_order || "",
        imported_at: row.imported_at || "",
        saved_at: answer.saved_at || "",
        review_locked: false,
        ...fields,
      };
      item.review_locked = isLocked(item);
      merged.push(item);
    });
    if (isStage2()) {
      merged.sort(function (a, b) {
        return Number(a.sort_order || 0) - Number(b.sort_order || 0);
      });
    } else {
      merged.sort(function (a, b) {
        return String(a.review_id).localeCompare(String(b.review_id));
      });
    }
    return merged;
  }

  async function reloadItems(options) {
    const opts = options || {};
    const currentId = currentItem() ? currentItem().review_id : null;
    const [rows, answers] = await Promise.all([loadItemsCsv(), fetchAnswersMap()]);
    items = mergeItems(rows, answers);
    if (currentId) {
      const pos = items.findIndex(function (row) {
        return row.review_id === currentId;
      });
      if (pos >= 0) index = pos;
    } else {
      const firstEmpty = items.findIndex(function (item) {
        return !isFilled(item);
      });
      index = firstEmpty >= 0 ? firstEmpty : 0;
    }
    if (!opts.silent) saveStatus.textContent = "已重新載入全組進度";
    render();
  }

  async function saveCurrent(options) {
    const opts = options || {};
    const item = currentItem();
    const form = collectForm();
    if (!item || !form) return false;

    if (isLocked(item)) {
      saveStatus.textContent = "這篇已完成，請改審其他文章";
      return false;
    }
    if (!form.reviewer) {
      saveStatus.textContent = "請先填「檢視者」再儲存";
      return false;
    }
    if (isStage2() && GRADES.indexOf(form.grade) < 0) {
      saveStatus.textContent = "請先選 A、B 或 C 再儲存";
      return false;
    }
    if (isStage2() && String(item.review_id).indexOf("ptt2_") !== 0) {
      saveStatus.textContent = "這筆不是第二階段編號，已停止儲存";
      return false;
    }

    applyLocalFormToItem();
    updateProgress();
    saveStatus.textContent = "儲存中…";

    try {
      const existing = await fetchOneAnswer(item.review_id);
      if (existing && isLocked(existing)) {
        await reloadItems({ keepIndex: true, silent: true });
        saveStatus.textContent = "這篇已由其他組員完成";
        return false;
      }

      const savedAt = new Date().toISOString();
      const payload = isStage2()
        ? {
            review_id: item.review_id,
            dataset_id: datasetId,
            content_relevant: form.grade,
            url_relevant: "",
            keywords: [],
            status: "stage2",
            human_notes: form.human_notes || "",
            reviewer: form.reviewer || "",
            review_status: "reviewed",
            article_type: "",
            saved_at: savedAt,
            updated_at: savedAt,
          }
        : {
            review_id: item.review_id,
            dataset_id: datasetId,
            content_relevant: form.content_relevant || "",
            url_relevant: form.url_relevant || "",
            keywords: form.keywords || [],
            status: deriveLocalPttStatus(
              form.content_relevant,
              form.url_relevant,
              form.keywords
            ),
            human_notes: form.human_notes || "",
            reviewer: form.reviewer || "",
            review_status: isFilled({
              content_relevant: form.content_relevant,
              url_relevant: form.url_relevant,
              keywords: form.keywords,
            })
              ? "reviewed"
              : "pending",
            article_type: item.article_type || "",
            saved_at: savedAt,
            updated_at: savedAt,
          };

      const client = getClient();
      const { data, error } = await client
        .from("ptt_review_answers")
        .upsert(payload, { onConflict: "review_id" })
        .select("*")
        .maybeSingle();

      if (error) {
        // RLS 擋住已完成列的更新
        if (/policy|permission|row-level/i.test(error.message || "")) {
          await reloadItems({ silent: true });
          saveStatus.textContent = "這篇已完成，無法覆寫";
          return false;
        }
        throw new Error(error.message || "Supabase 寫入失敗");
      }

      const saved = data ? rowToAnswer(data) : rowToAnswer(payload);
      Object.assign(item, saved);
      item.review_locked = isLocked(item);
      dirty = false;
      saveStatus.textContent = opts.silent ? "" : "已永久保存到 Supabase（全組共用）";
      renderDoneBanner(item);
      updateProgress();
      return true;
    } catch (err) {
      saveStatus.textContent = "存檔失敗：" + (err.message || err);
      return false;
    }
  }

  function startAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(function () {
      if (dirty) return;
      reloadItems({ silent: true }).catch(function () {});
    }, REFRESH_MS);
  }

  function applyDatasetChrome() {
    const ds = currentDataset();
    document.getElementById("datasetEyebrow").textContent = ds.eyebrow;
    document.getElementById("datasetHeading").textContent = ds.heading;
    document.querySelectorAll(".dataset-btn").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-dataset") === datasetId);
    });
    const hint = document.getElementById("emptyStateHint");
    const cmd = document.getElementById("emptyStateCmd");
    const emptyTitle = emptyState ? emptyState.querySelector("h2") : null;
    if (isStage2()) {
      if (emptyTitle) emptyTitle.textContent = "還沒有第二階段文章";
      if (hint) hint.textContent = "第二階段清單是 stage2_items.csv，與第一階段 items.csv 分開。";
      if (cmd) cmd.hidden = true;
    } else {
      if (emptyTitle) emptyTitle.textContent = "還沒有 Temp 候選文章";
      if (hint) hint.textContent = "請先執行第一階段 pipeline，把 temp 文章同步到 GitHub Pages 後再來審查。";
      if (cmd) cmd.hidden = false;
    }
  }

  async function switchDataset(nextId) {
    if (!DATASETS[nextId] || nextId === datasetId) return;
    if (dirty) {
      const ok = window.confirm("有未儲存變更，切換分類會捨棄本機編輯。繼續？");
      if (!ok) return;
      dirty = false;
    }
    datasetId = nextId;
    sessionStorage.setItem(DATASET_SESSION_KEY, datasetId);
    index = 0;
    items = [];
    applyDatasetChrome();
    await reloadItems({ silent: true });
  }

  async function enterApp() {
    applyDatasetChrome();
    await reloadItems({ silent: true });
    showApp();
    startAutoRefresh();
  }

  loginBtn.addEventListener("click", async function () {
    loginError.hidden = true;
    try {
      if (!configReady()) {
        throw new Error("請先設定 docs/review/config.js 的 Supabase 公開金鑰");
      }
      const expected = String(cfg.REVIEW_PASSWORD || "");
      if (!expected || passwordInput.value !== expected) {
        throw new Error("密碼錯誤");
      }
      getClient();
      setAuthed(true);
      passwordInput.value = "";
      await enterApp();
    } catch (err) {
      showLogin(err.message || "登入失敗");
    }
  });

  passwordInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") loginBtn.click();
  });

  refreshBtn.addEventListener("click", async function () {
    if (dirty) {
      const ok = window.confirm("有未儲存變更，重新載入會捨棄本機編輯。繼續？");
      if (!ok) return;
      dirty = false;
    }
    await reloadItems();
  });

  logoutBtn.addEventListener("click", function () {
    if (dirty) {
      const ok = window.confirm("還有未儲存變更，確定登出？");
      if (!ok) return;
    }
    if (refreshTimer) clearInterval(refreshTimer);
    setAuthed(false);
    items = [];
    showLogin();
  });

  document.querySelectorAll(".dataset-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      switchDataset(btn.getAttribute("data-dataset")).catch(function (err) {
        saveStatus.textContent = "切換失敗：" + (err.message || err);
      });
    });
  });

  document.querySelectorAll(".choice-grid").forEach(function (grid) {
    grid.addEventListener("click", function (event) {
      const btn = event.target.closest("button[data-value]");
      if (!btn || btn.disabled) return;
      setChoice(grid.getAttribute("data-field"), btn.getAttribute("data-value"));
      markDirty();
    });
  });

  humanNotes.addEventListener("input", markDirty);
  reviewerInput.addEventListener("input", markDirty);
  if (keywordsInput) keywordsInput.addEventListener("input", markDirty);

  saveBtn.addEventListener("click", function () {
    saveCurrent();
  });

  prevBtn.addEventListener("click", function () {
    index = Math.max(0, index - 1);
    render();
  });

  nextBtn.addEventListener("click", async function () {
    const ok = await saveCurrent();
    if (!ok) return;
    const next = findNextUnfilled(index);
    if (next === -1) {
      saveStatus.textContent = "全部完成，沒有未填文章";
      return;
    }
    index = next;
    render();
  });

  jumpBtn.addEventListener("click", function () {
    const next = findNextUnfilled(index);
    if (next === -1) {
      saveStatus.textContent = "全部完成，沒有未填文章";
      return;
    }
    index = next;
    render();
  });

  window.addEventListener("beforeunload", function (event) {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  if (isAuthed()) {
    enterApp().catch(function (err) {
      setAuthed(false);
      showLogin(err.message || "請重新登入");
    });
  } else {
    showLogin();
  }
})();
