import json
import math
import os
import re
from pathlib import Path

import requests

CONFIG_PATH = Path(__file__).resolve().parent / "mcp_config.json"


def _normalize_token(raw: str) -> str:
    """Accept bare JWT, or a pasted mcpServers JSON blob; return Authorization value only."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.lower().startswith("bearer "):
        s = s[7:].strip()
    # User sometimes pastes the whole Cursor/MCP config JSON into the Secret.
    if s.startswith("{") and ("mcpServers" in s or "Authorization" in s):
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            m = re.search(r'"Authorization"\s*:\s*"([^"]+)"', s)
            return (m.group(1) if m else "").strip()
        servers = obj.get("mcpServers") if isinstance(obj, dict) else None
        if isinstance(servers, dict):
            for key in (
                "hexin-ifind-ds-mcp",
                "hexin-ifind-ds-stock-mcp",
                "kuaicha-enterprise-mcp",
            ):
                node = servers.get(key) or {}
                headers = node.get("headers") if isinstance(node, dict) else None
                if isinstance(headers, dict) and headers.get("Authorization"):
                    return str(headers["Authorization"]).strip()
            for node in servers.values():
                if not isinstance(node, dict):
                    continue
                headers = node.get("headers") or {}
                if isinstance(headers, dict) and headers.get("Authorization"):
                    return str(headers["Authorization"]).strip()
        if isinstance(obj, dict) and obj.get("Authorization"):
            return str(obj["Authorization"]).strip()
        m = re.search(r'"Authorization"\s*:\s*"([^"]+)"', s)
        return (m.group(1) if m else "").strip()
    # Reject multi-line garbage that would break HTTP headers
    if "\n" in s or "\r" in s:
        m = re.search(r"(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", s)
        return m.group(1) if m else ""
    return s


def _load_config():
    """Prefer env (GitHub Actions secrets), then local mcp_config.json."""
    primary = _normalize_token(os.environ.get("IFIND_AUTH_TOKEN") or "")
    backup = _normalize_token(os.environ.get("IFIND_AUTH_TOKEN_BACKUP") or "")
    slot = (os.environ.get("IFIND_ACTIVE_SLOT") or "primary").strip() or "primary"
    if primary or backup:
        return {
            "auth_token": primary,
            "auth_token_backup": backup,
            "active_slot": slot if (slot == "backup" and backup) or (slot == "primary" and primary) else (
                "primary" if primary else "backup"
            ),
        }
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    raise RuntimeError("缺少 IFIND_AUTH_TOKEN / mcp_config.json")


def _save_config(cfg):
    # In CI, do not persist failover onto disk secrets; keep in-memory only.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


CONFIG = _load_config()


def _token_for_slot(cfg, slot):
    if slot == "backup":
        return _normalize_token(cfg.get("auth_token_backup") or "")
    return _normalize_token(cfg.get("auth_token") or "")


def _active_token(cfg=None):
    cfg = cfg or CONFIG
    slot = cfg.get("active_slot") or "primary"
    tok = _token_for_slot(cfg, slot)
    if tok:
        return slot, tok
    # fall back to whichever is present
    for s in ("primary", "backup"):
        t = _token_for_slot(cfg, s)
        if t:
            return s, t
    raise RuntimeError("无可用 IFIND_AUTH_TOKEN / auth_token_backup")


_ACTIVE_SLOT, AUTH_TOKEN = _active_token(CONFIG)


def _load_agent_name():
    name = (os.environ.get("IFIND_USER_AGENT") or "").strip()
    if name:
        return name
    try:
        cfg = json.loads((Path(__file__).resolve().parent / "skill_env_config.json").read_text(encoding="utf-8"))
        name = cfg.get("agent_name", "")
        return name if isinstance(name, str) else ""
    except Exception:
        return "cta-path-a"


AGENT_NAME = _load_agent_name()

BASE = "https://api-mcp.51ifind.com:8643/ds-mcp-servers"
SERVERS = {
    "stock": f"{BASE}/hexin-ifind-ds-stock-mcp",
    "fund": f"{BASE}/hexin-ifind-ds-fund-mcp",
    "edb": f"{BASE}/hexin-ifind-ds-edb-mcp",
    "news": f"{BASE}/hexin-ifind-ds-news-mcp",
    "bond": f"{BASE}/hexin-ifind-ds-bond-mcp",
    "global_stock": f"{BASE}/hexin-ifind-ds-global-stock-mcp",
    "index": f"{BASE}/hexin-ifind-ds-index-mcp",
    "future": f"{BASE}/hexin-ifind-ds-futures-mcp",
    "enterprise": f"{BASE}/kuaicha-enterprise-mcp",
    "law": f"{BASE}/hexin-law-mcp",
}

_sessions = {}
_req_ids = {}
_tool_sets = {}
BLOCKED_KEYS = {"__proto__", "prototype", "constructor"}

_QUOTA_RE = re.compile(
    r"quota|额度|次数|limit|exceed|unauthorized|forbidden|401|403|expired|过期|无效|余额不足",
    re.I,
)


def _next_id(t):
    _req_ids[t] = _req_ids.get(t, 0) + 1
    return _req_ids[t]


def _headers(t=None):
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": AUTH_TOKEN,
        "User-Agent": AGENT_NAME,
    }
    if t in _sessions:
        h["Mcp-Session-Id"] = _sessions[t]
    return h


def _clear_sessions():
    _sessions.clear()
    _tool_sets.clear()


def _switch_to_backup(reason):
    """Switch active_slot to backup if available. Returns True if switched."""
    global AUTH_TOKEN, _ACTIVE_SLOT, CONFIG
    cfg = _load_config()
    backup = _token_for_slot(cfg, "backup")
    if not backup:
        return False
    if (cfg.get("active_slot") or "primary") == "backup" and AUTH_TOKEN == backup:
        return False
    cfg["active_slot"] = "backup"
    cfg["failover_reason"] = str(reason)[:300]
    _save_config(cfg)
    CONFIG = cfg
    _ACTIVE_SLOT = "backup"
    AUTH_TOKEN = backup
    _clear_sessions()
    print(f"[ifind] switched to backup key: {reason}")
    return True


def _looks_like_quota_or_auth_fail(resp, data):
    if resp is not None and resp.status_code in (401, 403, 429):
        return True
    blob = ""
    if isinstance(data, dict):
        blob = json.dumps(data, ensure_ascii=False)
    elif isinstance(data, str):
        blob = data
    return bool(_QUOTA_RE.search(blob))


def _post(t, payload, timeout=60):
    resp = requests.post(
        SERVERS[t],
        json=payload,
        headers=_headers(t),
        timeout=timeout,
    )
    data = None
    if resp.text.strip():
        try:
            data = resp.json()
        except Exception:
            data = resp.text
    return resp, data


def _post_with_failover(t, payload, timeout=60):
    resp, data = _post(t, payload, timeout=timeout)
    if _looks_like_quota_or_auth_fail(resp, data):
        if _switch_to_backup(f"http {getattr(resp, 'status_code', '?')} / {str(data)[:120]}"):
            resp, data = _post(t, payload, timeout=timeout)
    return resp, data


def _validate_params(params):
    if not isinstance(params, dict):
        raise TypeError("input must be a JSON object")

    def walk(value):
        if value is None:
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in BLOCKED_KEYS:
                    raise TypeError("input contains blocked field")
                walk(item)
            return
        if isinstance(value, float) and not math.isfinite(value):
            raise TypeError("input contains invalid number")
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError("input contains unsupported value type")

    walk(params)
    json.dumps(params, allow_nan=False)


def _init(t):
    if t in _sessions:
        return

    payload = {
        "jsonrpc": "2.0",
        "id": _next_id(t),
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "http-client", "version": "1.0.0"},
        },
    }

    resp, data = _post_with_failover(t, payload, timeout=30)
    resp.raise_for_status()

    session_id = resp.headers.get("Mcp-Session-Id")
    if not session_id:
        raise RuntimeError(f"initialize 成功但未返回 Mcp-Session-Id: {data}")

    _sessions[t] = session_id

    notify = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    requests.post(
        SERVERS[t],
        json=notify,
        headers=_headers(t),
        timeout=10,
    )


def _load_tool_set(server_type):
    if server_type in _tool_sets:
        return _tool_sets[server_type]

    res = list_tools(server_type)
    tools = res.get("data", {}).get("result", {}).get("tools")
    if not isinstance(tools, list):
        raise RuntimeError("Invalid tools/list response")

    tool_set = {
        tool.get("name")
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("name"), str) and tool.get("name")
    }
    _tool_sets[server_type] = tool_set
    return tool_set


def call(server_type, tool_name, params):
    if server_type not in SERVERS:
        raise ValueError(f"unknown server_type: {server_type}")

    _validate_params(params)
    allowed_tools = _load_tool_set(server_type)
    if tool_name not in allowed_tools:
        raise ValueError(f"toolName not allowed for server_type {server_type}: {tool_name}")

    payload = {
        "jsonrpc": "2.0",
        "id": _next_id(server_type),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": params,
        },
    }

    resp, data = _post_with_failover(server_type, payload)

    if isinstance(data, dict) and "error" in data:
        if _looks_like_quota_or_auth_fail(resp, data) and _switch_to_backup(data.get("error")):
            _init(server_type)
            resp, data = _post(server_type, payload)
            if isinstance(data, dict) and "error" in data:
                return {
                    "ok": False,
                    "status_code": resp.status_code,
                    "error": data["error"],
                    "raw": data,
                    "active_slot": _ACTIVE_SLOT,
                }
        else:
            return {
                "ok": False,
                "status_code": resp.status_code,
                "error": data["error"],
                "raw": data,
                "active_slot": _ACTIVE_SLOT,
            }

    resp.raise_for_status()
    return {
        "ok": True,
        "status_code": resp.status_code,
        "data": data,
        "active_slot": _ACTIVE_SLOT,
    }


def list_tools(server_type):
    if server_type not in SERVERS:
        raise ValueError(f"unknown server_type: {server_type}")

    _init(server_type)

    payload = {
        "jsonrpc": "2.0",
        "id": _next_id(server_type),
        "method": "tools/list",
        "params": {},
    }

    resp, data = _post_with_failover(server_type, payload)

    if isinstance(data, dict) and "error" in data:
        return {
            "ok": False,
            "status_code": resp.status_code,
            "error": data["error"],
            "raw": data,
            "active_slot": _ACTIVE_SLOT,
        }

    resp.raise_for_status()

    return {
        "ok": True,
        "status_code": resp.status_code,
        "data": data,
        "active_slot": _ACTIVE_SLOT,
    }


if __name__ == "__main__":
    print("未调用工具函数及输入查询参数，请按照说明文档发起请求")
