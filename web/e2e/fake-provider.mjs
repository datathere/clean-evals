// A fake OpenAI-compatible provider for browser tests. Node stdlib only.
// Mirrors tests/integration/conftest.py: deterministic labels, no cost,
// so the golden-path e2e flow runs with zero API spend.
import { createServer } from "node:http";

const PORT = Number(process.env.FAKE_PROVIDER_PORT ?? 11499);

function classify(prompt) {
  const low = prompt.toLowerCase();
  if (/(positive|love|great)/.test(low)) return "positive";
  if (/(negative|hate|terrible)/.test(low)) return "negative";
  return "neutral";
}

createServer((req, res) => {
  const json = (status, body) => {
    const data = JSON.stringify(body);
    res.writeHead(status, { "content-type": "application/json" });
    res.end(data);
  };

  if (req.method === "GET" && req.url.replace(/\/$/, "").endsWith("/models")) {
    json(200, { object: "list", data: [{ id: "fake-1", object: "model" }] });
    return;
  }

  if (req.method === "POST") {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      const body = JSON.parse(raw || "{}");
      const messages = body.messages ?? [];
      const user = [...messages].reverse().find((m) => m.role === "user")?.content ?? "";
      const wantsJson = body.response_format?.type === "json_object";
      const label = classify(user);
      const content = wantsJson ? JSON.stringify({ label }) : label;
      json(200, {
        id: "chatcmpl-fake",
        choices: [{ index: 0, message: { role: "assistant", content } }],
        usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 },
      });
    });
    return;
  }

  json(404, { error: "not found" });
}).listen(PORT, "127.0.0.1", () => {
  // Playwright waits on this URL.
  console.log(`fake provider on http://127.0.0.1:${PORT}/v1`);
});
