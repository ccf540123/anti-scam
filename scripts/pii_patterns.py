"""台灣常見個資樣式的規則遮蔽。

規則來源是 supabase/functions/submit-scam-experience/pii_patterns.json。
匯出腳本、測試與瀏覽器提示都用同一份規則。後端遮蔽才算數。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "supabase" / "functions" / "submit-scam-experience" / "pii_patterns.json"


@lru_cache(maxsize=1)
def load_rules() -> tuple[dict, ...]:
    payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    rules = payload.get("rules") or []
    return tuple(rules)


def _flags(text: str) -> int:
    flags = 0
    if "i" in (text or ""):
        flags |= re.IGNORECASE
    return flags


def strip_url(raw: str) -> str:
    """只留 scheme、host、path。LINE 短網址整段改成 [CHAT_ID]。"""
    trimmed = re.sub(r"[),.;:!?，。、]+$", "", raw or "")
    if re.search(r"(?:line\.me|lin\.ee)", trimmed, re.IGNORECASE):
        return "[CHAT_ID]"
    try:
        parts = urlsplit(trimmed)
    except ValueError:
        return "[URL]"
    if not parts.scheme or not parts.netloc:
        return "[URL]"
    path = parts.path or ""
    if path == "/":
        path = ""
    return f"{parts.scheme}://{parts.netloc}{path}"


def redact(text: str) -> str:
    output = "" if text is None else str(text)
    for rule in load_rules():
        pattern = re.compile(rule["pattern"], _flags(rule.get("flags") or ""))
        if rule.get("mode") == "strip_url":
            output = pattern.sub(lambda match: strip_url(match.group(0)), output)
        else:
            output = pattern.sub(rule.get("replacement") or "", output)
    return output


def contains_pii(text: str) -> bool:
    return redact(text) != ("" if text is None else str(text))


def render_browser_script() -> str:
    """產生瀏覽器與 Node 都能用的 docs/pii.js。規則內嵌，不另打一隻請求。"""
    rules_json = json.dumps(list(load_rules()), ensure_ascii=False, indent=2)
    return f"""// 由 scripts/pii_patterns.py 產生。請改 pii_patterns.json 後重新匯出。
(function (root, factory) {{
  var api = factory();
  if (typeof module !== "undefined" && module.exports) {{
    module.exports = api;
  }} else {{
    root.AntiScamPii = api;
  }}
}})(typeof window !== "undefined" ? window : globalThis, function () {{
  var RULES = {rules_json};

  function stripUrl(raw) {{
    var trimmed = String(raw || "").replace(/[),.;:!?，。、]+$/g, "");
    if (/line\\.me|lin\\.ee/i.test(trimmed)) return "[CHAT_ID]";
    try {{
      var parsed = new URL(trimmed);
      var path = parsed.pathname === "/" ? "" : parsed.pathname;
      return parsed.protocol + "//" + parsed.host + path;
    }} catch (err) {{
      return "[URL]";
    }}
  }}

  function redact(text) {{
    var output = text == null ? "" : String(text);
    var index;
    for (index = 0; index < RULES.length; index += 1) {{
      var rule = RULES[index];
      var matcher = new RegExp(rule.pattern, rule.flags || "g");
      if (rule.mode === "strip_url") {{
        output = output.replace(matcher, function (url) {{
          return stripUrl(url);
        }});
      }} else {{
        output = output.replace(matcher, rule.replacement || "");
      }}
    }}
    return output;
  }}

  function containsPii(text) {{
    return redact(text) !== (text == null ? "" : String(text));
  }}

  return {{
    redact: redact,
    containsPii: containsPii,
  }};
}});
"""
