// 公開網站的分頁、資料集、投稿表單與排行榜。
// 檢測按鈕仍由 app.js 處理。這裡沒有任何 API 金鑰。
(function () {
  var SECTIONS = ["detect", "analysis", "dataset", "share", "leaderboard"];
  var cfg = window.REVIEW_CONFIG || {};
  var crowdClient = null;

  function $(id) {
    return document.getElementById(id);
  }

  function show(name) {
    if (SECTIONS.indexOf(name) < 0) name = "detect";
    SECTIONS.forEach(function (id) {
      var section = $(id);
      if (section) section.hidden = id !== name;
    });
    document.querySelectorAll("[data-nav]").forEach(function (link) {
      link.classList.toggle("is-active", link.getAttribute("data-nav") === name);
    });
    if (name === "analysis") {
      window.dispatchEvent(new Event("analysis-shown"));
    }
    if (name === "leaderboard") loadCrowd();
    if (name === "dataset") loadDataset();
  }

  function route() {
    var name = (location.hash || "#detect").replace("#", "");
    show(name);
  }

  function supabaseClient() {
    if (crowdClient) return crowdClient;
    if (!window.supabase || !cfg.SUPABASE_URL || !cfg.SUPABASE_ANON_KEY) return null;
    crowdClient = window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);
    return crowdClient;
  }

  function functionUrl() {
    return String(cfg.SUPABASE_URL || "").replace(/\/$/, "") + "/functions/v1/submit-scam-experience";
  }

  function loadDataset() {
    var box = $("datasetFiles");
    var meta = $("datasetMeta");
    if (!box || box.dataset.loaded === "1") return;
    fetch("dataset/dataset_manifest.json")
      .then(function (response) {
        if (!response.ok) throw new Error("讀不到資料集清單");
        return response.json();
      })
      .then(function (manifest) {
        var counts = manifest.counts || {};
        meta.textContent =
          "版本 " + manifest.version +
          " · 凍結日 " + manifest.frozen_at +
          " · 授權 " + manifest.license +
          " · 第一階段 " + counts.stage1_rows +
          " 列 · 第二階段 " + counts.stage2_rows +
          " 列 · 網址重疊 " + counts.overlap_urls +
          " · 官方 exact 命中 " + counts.official_exact_match_rows + " 列";
        var names = Object.keys(manifest.files || {});
        box.innerHTML = names.map(function (name) {
          var info = manifest.files[name];
          var href = "dataset/" + name;
          return (
            '<article class="file-card"><strong>' + name + "</strong>" +
            "<p>SHA-256</p><p class=\"hash\">" + info.sha256 + "</p>" +
            "<p>" + info.bytes + " bytes" +
            (info.rows == null ? "" : " · " + info.rows + " 列") + "</p>" +
            '<p><a href="' + href + '">下載</a></p></article>'
          );
        }).join("");
        box.dataset.loaded = "1";
      })
      .catch(function (err) {
        meta.textContent = err.message || "資料集清單讀取失敗";
      });
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
    var text = $("narrativeInput").value;
    if (!window.AntiScamPii) {
      note.hidden = true;
      return;
    }
    var hit = window.AntiScamPii.containsPii(text);
    note.hidden = !hit;
  }

  function bindForm() {
    var form = $("shareForm");
    if (!form) return;
    $("narrativeInput").addEventListener("input", warnPii);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      sendStory();
    });
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
      status.textContent = "剛剛才送出過，請等一分鐘。伺服器也會再擋一次。";
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
          return { ok: response.ok, status: response.status, data: data };
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

  function loadCrowd() {
    var stats = $("crowdStats");
    var table = $("leaderTable");
    var list = $("crowdList");
    var client = supabaseClient();
    if (!client) {
      stats.textContent = "還沒設定 Supabase 公開網址，排行榜先留空。";
      return;
    }
    stats.textContent = "讀取中…";
    Promise.all([
      client.rpc("crowd_public_stats"),
      client.rpc("crowd_leaderboard"),
      client.from("scam_submissions_public").select("submission_id,public_handle,year_or_period,region,outcome_self,evidence_level,incident_outcome,scam_type,event_summary,source_type").limit(30),
    ]).then(function (results) {
      var statResult = results[0];
      var boardResult = results[1];
      var listResult = results[2];
      if (statResult.error || boardResult.error) {
        stats.textContent = "排行榜尚未開放。請先在 Supabase 執行遷移 SQL。";
        table.innerHTML = "";
        list.innerHTML = "";
        return;
      }
      var info = statResult.data || {};
      stats.textContent =
        "已核准 " + (info.approved_count || 0) + " 則。標示：" +
        (info.label || "群眾自述（未獨立查證）") + "。" +
        (info.note || "與 PTT 人審清單不可加總。");
      var rows = boardResult.data || [];
      if (!rows.length) {
        table.innerHTML = "<tr><td colspan=\"3\">還沒有核准的投稿。</td></tr>";
      } else {
        table.innerHTML = rows.map(function (row, index) {
          return "<tr><td>" + (index + 1) + "</td><td>" + escapeHtml(row.public_handle) +
            "</td><td>" + row.approved_count + "</td></tr>";
        }).join("");
      }
      var cards = listResult.data || [];
      list.innerHTML = cards.map(function (row) {
        var types = Array.isArray(row.scam_type) ? row.scam_type.join("、") : "";
        return (
          '<article class="mini-card"><span class="tag-note">群眾自述（未獨立查證）</span>' +
          "<h3>" + escapeHtml(row.public_handle || "匿名") + "</h3>" +
          "<p>" + escapeHtml(row.year_or_period || "時間未填") +
          " · " + escapeHtml(row.region || "地區未填") +
          " · 自述結果 " + escapeHtml(row.outcome_self || "—") + "</p>" +
          "<p>證據等級 " + escapeHtml(row.evidence_level || "尚無") +
          " · 結果 " + escapeHtml(row.incident_outcome || "unknown") +
          (types ? " · " + escapeHtml(types) : "") + "</p>" +
          "<p>" + escapeHtml(row.event_summary || "尚無 AI 摘要") + "</p></article>"
        );
      }).join("");
    }).catch(function () {
      stats.textContent = "排行榜讀取失敗。";
    });
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  document.querySelectorAll("[data-nav]").forEach(function (link) {
    link.addEventListener("click", function () {
      show(link.getAttribute("data-nav"));
    });
  });
  window.addEventListener("hashchange", route);
  bindForm();
  route();
})();
