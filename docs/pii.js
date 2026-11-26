// 由 scripts/pii_patterns.py 產生。請改 pii_patterns.json 後重新匯出。
(function (root, factory) {
  var api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.AntiScamPii = api;
  }
})(typeof window !== "undefined" ? window : globalThis, function () {
  var RULES = [
  {
    "name": "url",
    "mode": "strip_url",
    "pattern": "https?://[^\\s<>\"']+",
    "flags": "gi"
  },
  {
    "name": "email",
    "pattern": "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}",
    "flags": "gi",
    "replacement": "[EMAIL]"
  },
  {
    "name": "national_id",
    "pattern": "(?<![A-Za-z0-9])[A-Za-z][12][0-9]{8}(?![0-9])",
    "flags": "gi",
    "replacement": "[NATIONAL_ID]"
  },
  {
    "name": "mobile_886",
    "pattern": "(?<![0-9])\\+886[-\\s.]?9[0-9]{2}[-\\s.]?[0-9]{3}[-\\s.]?[0-9]{3}(?![0-9])",
    "flags": "g",
    "replacement": "[PHONE]"
  },
  {
    "name": "mobile",
    "pattern": "(?<![0-9])09[-\\s.]?[0-9]{2}[-\\s.]?[0-9]{3}[-\\s.]?[0-9]{3}(?![0-9])",
    "flags": "g",
    "replacement": "[PHONE]"
  },
  {
    "name": "landline",
    "pattern": "(?<![0-9])\\(?0[2-8][0-9]?\\)?[-\\s.]?[0-9]{3,4}[-\\s.]?[0-9]{3,4}(?![0-9])",
    "flags": "g",
    "replacement": "[PHONE]"
  },
  {
    "name": "chat_id",
    "pattern": "(?:line\\s*id|line\\s*帳號|微信號|wechat\\s*id|telegram\\s*id|tg\\s*id)\\s*[:：]?\\s*[A-Za-z][A-Za-z0-9._-]{2,31}",
    "flags": "gi",
    "replacement": "[CHAT_ID]"
  },
  {
    "name": "account",
    "pattern": "(?:帳號|卡號|帳戶|帳户|匯款帳號)\\s*[:：]?\\s*[0-9](?:[-\\s]?[0-9]){9,15}",
    "flags": "g",
    "replacement": "[ACCOUNT]"
  },
  {
    "name": "long_digits",
    "pattern": "(?<![0-9])[0-9]{13,16}(?![0-9])",
    "flags": "g",
    "replacement": "[ACCOUNT]"
  },
  {
    "name": "my_name",
    "pattern": "我叫[\\s]*[\\u4e00-\\u9fff]{2,4}",
    "flags": "g",
    "replacement": "我叫[NAME]"
  }
];

  function stripUrl(raw) {
    var trimmed = String(raw || "").replace(/[),.;:!?，。、]+$/g, "");
    if (/line\.me|lin\.ee/i.test(trimmed)) return "[CHAT_ID]";
    try {
      var parsed = new URL(trimmed);
      var path = parsed.pathname === "/" ? "" : parsed.pathname;
      return parsed.protocol + "//" + parsed.host + path;
    } catch (err) {
      return "[URL]";
    }
  }

  function redact(text) {
    var output = text == null ? "" : String(text);
    var index;
    for (index = 0; index < RULES.length; index += 1) {
      var rule = RULES[index];
      var matcher = new RegExp(rule.pattern, rule.flags || "g");
      if (rule.mode === "strip_url") {
        output = output.replace(matcher, function (url) {
          return stripUrl(url);
        });
      } else {
        output = output.replace(matcher, rule.replacement || "");
      }
    }
    return output;
  }

  function containsPii(text) {
    return redact(text) !== (text == null ? "" : String(text));
  }

  return {
    redact: redact,
    containsPii: containsPii,
  };
});
