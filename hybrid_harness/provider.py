import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class ChatCompletionsProvider:
    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL") or "").rstrip("/")
        self.model = model or os.getenv("LLM_MODEL")
        if not all((self.api_key, self.base_url, self.model)):
            raise ValueError("Live provider requires LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL")
        self.name = "live:" + self.model

    def complete(self, messages, tools=None):
        body = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = [{"type": "function", "function": tool} for tool in tools]
            body["tool_choice"] = "auto"
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError("LLM API %s: %s" % (error.code, error.read(300).decode("utf-8", "replace"))) from error
        message = payload.get("choices", [{}])[0].get("message")
        if not message:
            raise ValueError("LLM API returned no message")
        calls = []
        for call in message.get("tool_calls") or []:
            try:
                args = json.loads(call["function"]["arguments"])
            except (KeyError, ValueError) as error:
                raise ValueError("LLM returned malformed tool arguments") from error
            calls.append({"id": call["id"], "name": call["function"]["name"], "args": args})
        return {"content": message.get("content") or "", "tool_calls": calls, "raw_tool_calls": message.get("tool_calls") or []}


class FixtureProvider:
    def __init__(self, fixture_dir, variant="pass", asset_names=None):
        self.fixture_dir = Path(fixture_dir)
        self.variant = variant
        self.asset_names = asset_names or ("index.html", "styles.css", "app.js")
        self.name = "fixture:" + variant

    def complete(self, messages, tools=None):
        if tools and not any(m["role"] == "tool" for m in messages):
            if self.variant == "escape":
                calls = [{"id": "fixture-1", "name": "write_asset", "args": {"path": "../escape.txt", "content": "denied"}}]
            else:
                calls = []
                for index, name in enumerate(self.asset_names, 1):
                    content = (self.fixture_dir / name).read_text(encoding="utf-8")
                    if self.variant == "missing-source" and name == "index.html":
                        content = '<html lang="zh-Hant-TW"><main><h1>缺少來源</h1></main></html>'
                    calls.append({"id": "fixture-" + str(index), "name": "write_asset", "args": {"path": name, "content": content}})
            return {"content": "", "tool_calls": calls}
        if not tools:
            verdict = "uncertain" if self.variant == "uncertain" else "pass"
            return {"content": json.dumps({"verdict": verdict, "reasons": ["Fixture semantic review"]}), "tool_calls": []}
        return {"content": "Candidate written", "tool_calls": []}
