import json

from .policy import validate_tool_call, write_asset_tool


def run_tool_loop(provider, system, user, grant, on_write, max_turns=8):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    tool = write_asset_tool(grant["write_set"])
    count = 0
    for _ in range(max_turns):
        response = provider.complete(messages, [tool])
        calls = response.get("tool_calls") or []
        if not calls:
            return {"message": response.get("content", ""), "toolCalls": count}
        raw = response.get("raw_tool_calls") or [
            {"id": call["id"], "type": "function", "function": {"name": call["name"], "arguments": json.dumps(call["args"])}}
            for call in calls
        ]
        messages.append({"role": "assistant", "content": response.get("content") or None, "tool_calls": raw})
        for call in calls:
            count += 1
            if count > grant["max_tool_calls"]:
                raise ValueError("Tool-call budget exhausted")
            validate_tool_call(call, grant)
            artifact = on_write(call["args"]["path"], call["args"]["content"])
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"ok": True, "path": call["args"]["path"], "hash": artifact["hash"]})})
    raise ValueError("Agent turn budget exhausted")


def run_semantic_review(provider, system, user):
    response = provider.complete([
        {"role": "system", "content": system + '\nReturn only JSON: {"verdict":"pass|fail|uncertain","reasons":["..."]}.'},
        {"role": "user", "content": user},
    ])
    try:
        result = json.loads(response.get("content") or "")
        if result["verdict"] not in ("pass", "fail", "uncertain") or not isinstance(result["reasons"], list):
            raise ValueError("Invalid verdict")
        return {"verdict": result["verdict"], "reasons": [str(value) for value in result["reasons"][:8]]}
    except (ValueError, KeyError, TypeError):
        return {"verdict": "uncertain", "reasons": ["Semantic checker returned invalid output"]}
