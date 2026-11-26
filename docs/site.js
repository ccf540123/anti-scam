// 分享經驗的表單。頁面切換在 dashboard.js。這裡沒有 API 金鑰。
(function () {
  var cfg = window.REVIEW_CONFIG || {};

  function $(id) {
    return document.getElementById(id);
  }

  function functionUrl() {
    return String(cfg.SUPABASE_URL || "").replace(/\/$/, "") + "/functions/v1/submit-scam-experience";
  }

  function checkedChannels() {
    var picked = [];
    document.querySelectorAll('input[name="channel"]:checked').forEach(function (box) {
      picked.push(box.value);
    });
    return picked;
  }

  function warnPii() {
    var note = $("piiWarning");
    var field = $("narrativeInput");
    if (!note || !field || !window.AntiScamPii) return;
    note.hidden = !window.AntiScamPii.containsPii(field.value);
  }

  function sendStory() {
    var status = $("submitStatus");
    var button = $("submitBtn");
    status.textContent = "";
    if ($("companyWebsite").value) {
      status.textContent = "無法送出。";
      return;
    }
    if (!$("consentResearch").checked || !$("consentAi").checked) {
      status.textContent = "請先勾選兩項同意。";
      return;
    }
    var last = Number(sessionStorage.getItem("scam_submit_at") || "0");
    if (Date.now() - last < 60000) {
      status.textContent = "剛剛才送出過，請等一分鐘。";
      return;
    }
    var payload = {
      display_name: $("displayName").value.trim(),
      is_anonymous: $("isAnonymous").checked,
      year_or_period: $("yearOrPeriod").value.trim(),
      region: $("regionInput").value,
      case_nature_self: $("caseNatureSelf").value,
      outcome_self: $("outcomeSelf").value,
      amount_range: $("amountRange").value,
      channels: checkedChannels(),
      already_reported: $("alreadyReported").value,
      narrative: $("narrativeInput").value.trim(),
      consent_research: true,
      consent_ai: true,
      company_website: "",
    };
    button.disabled = true;
    status.textContent = "送出中…";
    fetch(functionUrl(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        apikey: cfg.SUPABASE_ANON_KEY,
        Authorization: "Bearer " + cfg.SUPABASE_ANON_KEY,
      },
      body: JSON.stringify(payload),
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          status.textContent = (result.data && result.data.message) || "送出失敗";
          return;
        }
        sessionStorage.setItem("scam_submit_at", String(Date.now()));
        $("narrativeInput").value = "";
        status.textContent = result.data.message || "已送出，待審核。";
      })
      .catch(function () {
        status.textContent = "連不到投稿服務。請確認 Edge Function 已部署。";
      })
      .then(function () {
        button.disabled = false;
      });
  }

  var form = $("shareForm");
  if (form) {
    $("narrativeInput").addEventListener("input", warnPii);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      sendStory();
    });
  }
})();
