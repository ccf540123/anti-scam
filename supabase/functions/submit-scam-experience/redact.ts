// 與 scripts/pii_patterns.py 相同的規則順序。規則檔是 pii_patterns.json。

type PiiRule = {
  name: string;
  mode?: string;
  pattern: string;
  flags?: string;
  replacement?: string;
};

const rulesPayload = JSON.parse(
  Deno.readTextFileSync(new URL("./pii_patterns.json", import.meta.url)),
) as { rules: PiiRule[] };

export function stripUrl(raw: string): string {
  const trimmed = String(raw || "").replace(/[),.;:!?，。、]+$/g, "");
  if (/line\.me|lin\.ee/i.test(trimmed)) return "[CHAT_ID]";
  try {
    const parsed = new URL(trimmed);
    const path = parsed.pathname === "/" ? "" : parsed.pathname;
    return parsed.protocol + "//" + parsed.host + path;
  } catch (_err) {
    return "[URL]";
  }
}

export function redact(text: string): string {
  let output = text == null ? "" : String(text);
  for (const rule of rulesPayload.rules) {
    const matcher = new RegExp(rule.pattern, rule.flags || "g");
    if (rule.mode === "strip_url") {
      output = output.replace(matcher, (url) => stripUrl(url));
    } else {
      output = output.replace(matcher, rule.replacement || "");
    }
  }
  return output;
}

export function containsPii(text: string): boolean {
  return redact(text) !== (text == null ? "" : String(text));
}
