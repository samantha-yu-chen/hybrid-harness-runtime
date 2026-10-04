import re


def validate_tool_call(call, grant):
    if call.get("name") != "write_asset" or "write_asset" not in grant["tools"]:
        raise ValueError("Tool denied")
    args = call.get("args")
    if not isinstance(args, dict) or set(args) != {"path", "content"}:
        raise ValueError("Invalid tool arguments")
    if args["path"] not in grant["write_set"]:
        raise ValueError("Write outside granted assets")
    content = args["content"]
    if not isinstance(content, str) or len(content.encode("utf-8")) > grant["max_asset_bytes"]:
        raise ValueError("Invalid asset content")
    if re.search(r'<script[^>]+src\s*=\s*["\']https?:|@import\s+url\(\s*["\']?https?:', content, re.I):
        raise ValueError("Remote executable asset denied")
    return call


def write_asset_tool(paths):
    return {
        "name": "write_asset",
        "description": "Write one candidate asset inside the granted write set.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "path": {"type": "string", "enum": paths},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    }


def check_candidate(assets, checks):
    results = []

    def add(name, passed, detail):
        results.append({"id": name, "pass": bool(passed), "detail": detail})

    expected = checks.get("assets", list(assets))
    content = assets.get(checks.get("content_asset", expected[0] if expected else "")) or ""
    add("assets.complete", all(isinstance(assets.get(p), str) and assets[p] for p in expected), "Required assets exist")
    add("content.required", all(text in content for text in checks.get("required_text", [])), "Required text")
    add("sources.present", all(url in content for url in checks.get("required_links", [])), "Required source links")
    add("scope.note", all(re.search(pattern, content) for pattern in checks.get("required_patterns", [])), "Scope and advice boundaries")
    add("assets.bounded", all(len((assets.get(name) or "").encode("utf-8")) <= checks.get("max_asset_bytes", 100_000) for name in expected), "Asset size limit")
    if checks.get("profile") == "web_page":
        html = content
        css = assets.get(checks.get("style_asset", "styles.css")) or ""
        language = checks.get("language", "zh-Hant-TW")
        add("html.semantic", bool(re.search(r'<html\b[^>]*lang=["\']' + re.escape(language) + r'["\']', html, re.I) and re.search(r"<main\b", html, re.I) and re.search(r"<h1\b", html, re.I)), "Language, main and h1")
        add("html.responsive", bool(re.search(r'name=["\']viewport["\']', html, re.I)), "Viewport meta")
        add("a11y.focus", ":focus-visible" in css and "prefers-reduced-motion" in css, "Keyboard focus and reduced motion")
        add("no.remote.code", not re.search(r'<script[^>]+src\s*=\s*["\']https?:', html, re.I) and not re.search(r'@import\s+url\(\s*["\']?https?:', css, re.I), "No remote executable assets")
    return {"pass": all(item["pass"] for item in results), "checks": results}
