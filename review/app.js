(function () {
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
  const datasetId = "ptt_candidate";
  const REFRESH_MS = 45000;

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

  async function api(url, options) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options && options.headers) },
      ...options,
    });
    let data = {};
    try {
      data = await response.json();
    } catch (e) {
      data = {};
    }
    if (response.status === 401) {
      const err = new Error(data.error || "需要登入");
      err.code = 401;
      throw err;
    }
    if (!response.ok) {
      const err = new Error(data.error || "請求失敗");
      err.code = response.status;
      err.locked = data.locked;
      throw err;
    }
    return data;
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

  function deriveLocalPttStatus(contentRelevant, urlRelevant, keywords) {
    if (keywords && keywords.length) return "temp";
    if (contentRelevant === "no" && (urlRelevant === "no" || urlRelevant === "none")) {
      return "non_match";
    }
    return "temp";
  }

  function isFilled(item) {
    if (!item) return false;
    const cr = (item.content_relevant || "").trim();
    const ur = (item.url_relevant || "").trim();
    if (!cr || !ur) return false;
    const keywords = Array.isArray(item.keywords)
      ? item.keywords
      : parseKeywordsText(item.keywords);
    if (cr === "yes" || ur === "yes") return keywords.length > 0;
    return true;
  }

  function isLocked(item) {
    return !!(item && (item.review_locked || (isFilled(item) && item.review_status === "reviewed")));
  }

  function updateProgress() {
    const done = items.filter(isFilled).length;
    const total = items.length;
    const remaining = Math.max(total - done, 0);
    document.getElementById("progressText").textContent =
      "總共 " + total + " 篇 · 已完成 " + done + " · 剩 " + remaining;
    let hint = "按「儲存」後會寫入 Render 伺服器，全組共用";
    if (dirty) hint = "有未儲存變更，請先按「儲存」";
    if (!total) hint = "尚未匯入 PTT Temp 候選，請先執行 pipeline";
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
    return {
      content_relevant: contentBtn ? contentBtn.getAttribute("data-value") : "",
      url_relevant: urlBtn ? urlBtn.getAttribute("data-value") : "",
      keywords: keywords,
      human_notes: humanNotes.value.trim(),
      reviewer: reviewerInput.value.trim(),
    };
  }

  function applyLocalFormToItem() {
    const item = currentItem();
    const form = collectForm();
    if (!item || !form) return;
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
    if (keywordsInput) {
      keywordsInput.value = keywordsToText(item.keywords);
    }
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

    applyLocalFormToItem();
    updateProgress();

    saveStatus.textContent = "儲存中…";
    try {
      const result = await api("/api/review/save", {
        method: "POST",
        body: JSON.stringify({
          dataset: datasetId,
          review_id: item.review_id,
          ...form,
        }),
      });
      const saved = result.answer || {};
      Object.assign(item, saved);
      item.review_locked = isFilled(item) && item.review_status === "reviewed";
      item.status = deriveLocalPttStatus(
        form.content_relevant,
        form.url_relevant,
        form.keywords
      );
      dirty = false;
      saveStatus.textContent = opts.silent ? "" : "已永久保存（全組共用）";
      renderDoneBanner(item);
      updateProgress();
      return true;
    } catch (err) {
      if (err.code === 401) {
        showLogin("登入已失效，請重新輸入密碼");
        return false;
      }
      if (err.code === 409 || err.locked) {
        await reloadItems({ keepIndex: true });
        saveStatus.textContent = err.message || "這篇已由其他組員完成";
        return false;
      }
      saveStatus.textContent = "存檔失敗：" + err.message;
      return false;
    }
  }

  async function reloadItems(options) {
    const opts = options || {};
    const currentId = currentItem() ? currentItem().review_id : null;
    const data = await api("/api/review/items?dataset=" + encodeURIComponent(datasetId));
    items = data.items || [];
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
    if (!opts.silent) {
      saveStatus.textContent = "已重新載入全組進度";
    }
    render();
  }

  async function loadItems() {
    await reloadItems({ silent: true });
    showApp();
  }

  function startAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(function () {
      if (dirty) return;
      reloadItems({ silent: true }).catch(function () {
        // ignore transient errors
      });
    }, REFRESH_MS);
  }

  async function tryResumeSession() {
    try {
      await api("/api/review/session");
      await loadItems();
      startAutoRefresh();
    } catch (err) {
      showLogin();
    }
  }

  loginBtn.addEventListener("click", async function () {
    loginError.hidden = true;
    try {
      await api("/api/review/login", {
        method: "POST",
        body: JSON.stringify({ password: passwordInput.value }),
      });
      passwordInput.value = "";
      await loadItems();
      startAutoRefresh();
    } catch (err) {
      showLogin(err.message || "密碼錯誤");
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

  logoutBtn.addEventListener("click", async function () {
    if (dirty) {
      const ok = window.confirm("還有未儲存變更，確定登出？");
      if (!ok) return;
    }
    if (refreshTimer) clearInterval(refreshTimer);
    try {
      await api("/api/review/logout", { method: "POST", body: "{}" });
    } catch (e) {
      // ignore
    }
    items = [];
    showLogin();
  });

  document.querySelectorAll(".choice-grid").forEach(function (grid) {
    grid.addEventListener("click", function (event) {
      const btn = event.target.closest("button[data-value]");
      if (!btn || btn.disabled) return;
      const field = grid.getAttribute("data-field");
      setChoice(field, btn.getAttribute("data-value"));
      markDirty();
    });
  });

  humanNotes.addEventListener("input", markDirty);
  reviewerInput.addEventListener("input", markDirty);
  if (keywordsInput) {
    keywordsInput.addEventListener("input", markDirty);
  }

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

  tryResumeSession();
})();
