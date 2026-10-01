(function () {
  const loginView = document.getElementById("loginView");
  const appView = document.getElementById("appView");
  const passwordInput = document.getElementById("passwordInput");
  const loginBtn = document.getElementById("loginBtn");
  const loginError = document.getElementById("loginError");
  const logoutBtn = document.getElementById("logoutBtn");
  const exportBtn = document.getElementById("exportBtn");
  const prevBtn = document.getElementById("prevBtn");
  const nextBtn = document.getElementById("nextBtn");
  const jumpBtn = document.getElementById("jumpBtn");
  const humanNotes = document.getElementById("humanNotes");
  const reviewerInput = document.getElementById("reviewerInput");
  const saveStatus = document.getElementById("saveStatus");

  let items = [];
  let index = 0;
  let dirty = false;
  let saveTimer = null;

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
      throw new Error(data.error || "請求失敗");
    }
    return data;
  }

  function isFilled(item) {
    if (!item) return false;
    return !!(
      (item.destination_opened || "").trim() ||
      (item.destination_type || "").trim() ||
      (item.is_scam_related_destination || "").trim()
    );
  }

  function updateProgress() {
    const done = items.filter(isFilled).length;
    const total = items.length;
    document.getElementById("progressText").textContent =
      "已完成 " + done + " / " + total;
    document.getElementById("progressHint").textContent = dirty
      ? "有未存檔變更，離開前請先存檔"
      : "先開短網址，再點選三個標註";
    const pct = total ? Math.round((done / total) * 100) : 0;
    document.getElementById("progressBar").style.width = pct + "%";
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
    const openedBtn = document.querySelector(
      '.choice-grid[data-field="destination_opened"] button.active'
    );
    const typeBtn = document.querySelector(
      '.choice-grid[data-field="destination_type"] button.active'
    );
    const scamBtn = document.querySelector(
      '.choice-grid[data-field="is_scam_related_destination"] button.active'
    );
    return {
      destination_opened: openedBtn ? openedBtn.getAttribute("data-value") : "",
      destination_type: typeBtn ? typeBtn.getAttribute("data-value") : "",
      is_scam_related_destination: scamBtn ? scamBtn.getAttribute("data-value") : "",
      human_notes: humanNotes.value.trim(),
      reviewer: reviewerInput.value.trim(),
    };
  }

  function applyLocalFormToItem() {
    const item = currentItem();
    const form = collectForm();
    if (!item || !form) return;
    item.destination_opened = form.destination_opened;
    item.destination_type = form.destination_type;
    item.is_scam_related_destination = form.is_scam_related_destination;
    item.human_notes = form.human_notes;
    item.reviewer = form.reviewer;
    if (
      form.destination_opened ||
      form.destination_type ||
      form.is_scam_related_destination
    ) {
      item.review_status = "reviewed";
    }
  }

  function render() {
    const item = currentItem();
    if (!item) return;

    document.getElementById("itemId").textContent = "#" + item.review_id;
    document.getElementById("hostPill").textContent = item.shortener_host || "短網址";
    document.getElementById("itemTitle").textContent = item.title || "（無標題）";
    document.getElementById("itemDate").textContent = item.published_at || "—";

    const shortLink = document.getElementById("shortLink");
    const articleLink = document.getElementById("articleLink");
    const openShortBtn = document.getElementById("openShortBtn");
    const openArticleBtn = document.getElementById("openArticleBtn");

    shortLink.href = item.extracted_url || "#";
    shortLink.textContent = item.extracted_url || "—";
    articleLink.href = item.article_url || "#";
    articleLink.textContent = item.article_url || "—";
    openShortBtn.href = item.extracted_url || "#";
    openArticleBtn.href = item.article_url || "#";

    const content = (item.content || "").trim();
    document.getElementById("itemContent").textContent = content
      ? content
      : "（此筆沒有對到正文，請改開 PTT 原文）";

    setChoice("destination_opened", item.destination_opened || "");
    setChoice("destination_type", item.destination_type || "");
    setChoice("is_scam_related_destination", item.is_scam_related_destination || "");
    humanNotes.value = item.human_notes || "";
    if (item.reviewer) {
      reviewerInput.value = item.reviewer;
    }
    dirty = false;
    saveStatus.textContent = "";
    updateProgress();
  }

  async function saveCurrent(options) {
    const opts = options || {};
    const item = currentItem();
    const form = collectForm();
    if (!item || !form) return false;

    applyLocalFormToItem();
    updateProgress();

    saveStatus.textContent = "儲存中…";
    try {
      await api("/api/review/save", {
        method: "POST",
        body: JSON.stringify({
          review_id: item.review_id,
          ...form,
        }),
      });
      dirty = false;
      saveStatus.textContent = opts.silent ? "" : "已存檔";
      return true;
    } catch (err) {
      if (err.code === 401) {
        showLogin("登入已失效，請重新輸入密碼");
        return false;
      }
      saveStatus.textContent = "存檔失敗：" + err.message;
      return false;
    }
  }

  function scheduleSave() {
    dirty = true;
    updateProgress();
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      saveCurrent({ silent: true });
    }, 500);
  }

  async function loadItems() {
    const data = await api("/api/review/items");
    items = data.items || [];
    index = 0;
    const firstEmpty = items.findIndex(function (item) {
      return !isFilled(item);
    });
    if (firstEmpty >= 0) index = firstEmpty;
    showApp();
    render();
  }

  async function tryResumeSession() {
    try {
      await api("/api/review/session");
      await loadItems();
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
    } catch (err) {
      showLogin(err.message || "密碼錯誤");
    }
  });

  passwordInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") loginBtn.click();
  });

  logoutBtn.addEventListener("click", async function () {
    if (dirty) {
      const ok = window.confirm("還有未存檔變更，確定登出？");
      if (!ok) return;
      await saveCurrent();
    }
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
      if (!btn) return;
      const field = grid.getAttribute("data-field");
      setChoice(field, btn.getAttribute("data-value"));
      scheduleSave();
    });
  });

  humanNotes.addEventListener("input", scheduleSave);
  reviewerInput.addEventListener("input", scheduleSave);

  prevBtn.addEventListener("click", async function () {
    await saveCurrent({ silent: true });
    index = Math.max(0, index - 1);
    render();
  });

  nextBtn.addEventListener("click", async function () {
    const ok = await saveCurrent();
    if (!ok) return;
    if (index < items.length - 1) {
      index += 1;
      render();
    } else {
      saveStatus.textContent = "已經是最後一筆";
    }
  });

  jumpBtn.addEventListener("click", async function () {
    await saveCurrent({ silent: true });
    let found = -1;
    for (let i = 0; i < items.length; i += 1) {
      if (!isFilled(items[i])) {
        found = i;
        break;
      }
    }
    if (found === -1) {
      saveStatus.textContent = "都填過了，可匯出 CSV";
      return;
    }
    index = found;
    render();
  });

  exportBtn.addEventListener("click", async function () {
    await saveCurrent({ silent: true });
    try {
      const response = await fetch("/api/review/export.csv", {
        credentials: "same-origin",
      });
      if (response.status === 401) {
        showLogin("登入已失效，請重新輸入密碼");
        return;
      }
      if (!response.ok) throw new Error("匯出失敗");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "176455_fuzzy_manual_review.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      saveStatus.textContent = err.message;
    }
  });

  window.addEventListener("beforeunload", function (event) {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  tryResumeSession();
})();
