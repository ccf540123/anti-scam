// 研究小組審核群眾投稿。只有登入後的 team_members 讀得到全文。
(function () {
  var client = null;
  var member = null;

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function message(text) {
    var box = document.getElementById("crowdMessage");
    if (box) box.textContent = text || "";
  }

  function channelsText(value) {
    if (Array.isArray(value)) return value.join("、");
    return String(value || "");
  }

  async function load() {
    if (!client) return;
    var filter = document.getElementById("crowdFilter");
    var status = filter ? filter.value : "pending";
    message("讀取中…");
    var query = client
      .from("scam_submissions")
      .select("submission_id,created_at,status,ai_status,public_handle,year_or_period,region,case_nature_self,outcome_self,amount_range,channels,already_reported,narrative_redacted,possible_duplicate,source_type,rejection_reason")
      .order("created_at", { ascending: false })
      .limit(80);
    if (status !== "all") query = query.eq("status", status);
    var result = await query;
    if (result.error) {
      message("讀取失敗：" + result.error.message);
      return;
    }
    var rows = result.data || [];
    var ids = rows.map(function (row) { return row.submission_id; });
    var aiMap = {};
    if (ids.length) {
      var aiResult = await client
        .from("scam_submission_ai")
        .select("submission_id,evidence_level,incident_outcome,confidence,event_summary,qa_flags,status,evidence_quotes,source_type")
        .in("submission_id", ids);
      if (!aiResult.error) {
        (aiResult.data || []).forEach(function (row) {
          aiMap[row.submission_id] = row;
        });
      }
    }
    render(rows, aiMap);
    message(rows.length ? "共 " + rows.length + " 筆" : "這個狀態目前沒有投稿");
  }

  function render(rows, aiMap) {
    var list = document.getElementById("crowdList");
    if (!list) return;
    list.innerHTML = rows.map(function (row) {
      var ai = aiMap[row.submission_id] || {};
      var quotes = Array.isArray(ai.evidence_quotes) ? ai.evidence_quotes.join("\n") : "";
      var flags = Array.isArray(ai.qa_flags) ? ai.qa_flags.join("、") : "";
      return (
        '<article class="crowd-card" data-id="' + escapeHtml(row.submission_id) + '">' +
        "<h3>" + escapeHtml(row.public_handle) + "</h3>" +
        "<p>狀態 " + escapeHtml(row.status) +
        " · AI " + escapeHtml(row.ai_status || "—") +
        (row.possible_duplicate ? " · 可能重複" : "") +
        " · " + escapeHtml(row.source_type || "user_submission") + "</p>" +
        "<p>" + escapeHtml(row.year_or_period) + " · " + escapeHtml(row.region || "未填地區") +
        " · " + escapeHtml(row.case_nature_self) + " · " + escapeHtml(row.outcome_self) +
        " · 曾報案 " + escapeHtml(row.already_reported || "未填") + "</p>" +
        "<p>管道：" + escapeHtml(channelsText(row.channels) || "未填") +
        " · 金額區間 " + escapeHtml(row.amount_range || "未填") + "</p>" +
        "<p>AI 證據 " + escapeHtml(ai.evidence_level || "尚無") +
        " · 信心 " + escapeHtml(ai.confidence || "—") +
        " · 結果 " + escapeHtml(ai.incident_outcome || "—") +
        (flags ? " · 旗標 " + escapeHtml(flags) : "") + "</p>" +
        "<p>摘要：" + escapeHtml(ai.event_summary || "尚無") + "</p>" +
        (quotes ? "<p>核對用引句（不公開）：<br>" + escapeHtml(quotes).replace(/\n/g, "<br>") + "</p>" : "") +
        '<label>去識別化正文<textarea class="crowd-text" rows="8">' + escapeHtml(row.narrative_redacted) + "</textarea></label>" +
        '<label>退回原因<input class="crowd-reason" type="text" value="' + escapeHtml(row.rejection_reason || "") + '"></label>' +
        '<div class="crowd-actions">' +
        '<button type="button" class="btn primary" data-act="approved">核准</button>' +
        '<button type="button" class="btn" data-act="needs_redaction">需要再遮蔽</button>' +
        '<button type="button" class="btn" data-act="rejected">退回</button>' +
        '<button type="button" class="btn" data-act="pending">改回待審</button>' +
        '<button type="button" class="btn" data-act="save">只存正文</button>' +
        "</div></article>"
      );
    }).join("");
  }

  async function updateCard(card, status) {
    var id = card.getAttribute("data-id");
    var text = card.querySelector(".crowd-text").value;
    var reason = card.querySelector(".crowd-reason").value.trim();
    var patch = {
      narrative_redacted: text,
      reviewed_by: member && member.email ? member.email : "",
      reviewed_at: new Date().toISOString(),
    };
    if (status) {
      patch.status = status;
      if (status === "rejected") patch.rejection_reason = reason || "未通過審核";
    }
    message("儲存中…");
    var result = await client.from("scam_submissions").update(patch).eq("submission_id", id);
    if (result.error) {
      message("儲存失敗：" + result.error.message);
      return;
    }
    if (status === "approved" || status === "rejected") {
      await client.from("scam_submission_ai").update({ status: status }).eq("submission_id", id);
    }
    message("已更新");
    await load();
  }

  function open(nextClient, nextMember) {
    client = nextClient;
    member = nextMember || null;
    load().catch(function (err) {
      message(err.message || "讀取失敗");
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("#crowdPanel [data-act]");
    if (!button) return;
    var card = button.closest(".crowd-card");
    var act = button.getAttribute("data-act");
    updateCard(card, act === "save" ? "" : act).catch(function (err) {
      message(err.message || "儲存失敗");
    });
  });

  var filter = document.getElementById("crowdFilter");
  if (filter) {
    filter.addEventListener("change", function () {
      if (client) load();
    });
  }
  var reload = document.getElementById("crowdReload");
  if (reload) {
    reload.addEventListener("click", function () {
      if (client) load();
    });
  }

  window.CrowdReview = { open: open };
})();
