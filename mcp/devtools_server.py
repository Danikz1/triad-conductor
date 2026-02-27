"""MCP devtools server — stdio JSON-RPC 2.0 server.

Exposes tools:
- run_tests
- run_lint
- run_typecheck
- take_screenshot
- summarize_diff
- collect_logs

The builder model connects to this server via --mcp-config to call tools during BUILD.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _json_rpc_response(id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _json_rpc_error(id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def _run_cmd(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> dict:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:5000],
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}


# Tool implementations

def tool_run_tests(params: dict) -> dict:
    cmd = params.get("command", "python -m pytest -q").split()
    cwd = params.get("cwd")
    return _run_cmd(cmd, cwd=cwd)


def tool_run_lint(params: dict) -> dict:
    cmd = params.get("command", "python -m flake8 --max-line-length=120 .").split()
    cwd = params.get("cwd")
    return _run_cmd(cmd, cwd=cwd)


def tool_run_typecheck(params: dict) -> dict:
    cmd = params.get("command", "python -m mypy .").split()
    cwd = params.get("cwd")
    return _run_cmd(cmd, cwd=cwd)


def tool_take_screenshot(params: dict) -> dict:
    output_path = params.get("output_path", "/tmp/screenshot.png")
    result = _run_cmd(["screencapture", "-x", output_path])
    if result["exit_code"] == 0:
        return {"path": output_path, "success": True}
    return {"path": output_path, "success": False, "error": result["stderr"]}


def tool_summarize_diff(params: dict) -> dict:
    cwd = params.get("cwd")
    base = params.get("base", "HEAD~1")
    head = params.get("head", "HEAD")
    result = _run_cmd(["git", "diff", "--stat", f"{base}...{head}"], cwd=cwd)
    return {"summary": result["stdout"], "exit_code": result["exit_code"]}


def tool_collect_logs(params: dict) -> dict:
    log_dir = params.get("log_dir", ".")
    pattern = params.get("pattern", "*.log")
    path = Path(log_dir)
    logs = {}
    for f in sorted(path.glob(pattern))[:10]:  # Cap at 10 files
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            logs[str(f)] = content[:5000]  # Truncate
        except Exception as e:
            logs[str(f)] = f"Error reading: {e}"
    return {"logs": logs}


TOOLS = {
    "run_tests": {
        "handler": tool_run_tests,
        "description": "Run test suite and return exit code + output",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Test command to run"},
                "cwd": {"type": "string", "description": "Working directory"},
            },
        },
    },
    "run_lint": {
        "handler": tool_run_lint,
        "description": "Run linter and return results",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
            },
        },
    },
    "run_typecheck": {
        "handler": tool_run_typecheck,
        "description": "Run type checker and return results",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
            },
        },
    },
    "take_screenshot": {
        "handler": tool_take_screenshot,
        "description": "Take a screenshot of the screen",
        "inputSchema": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string"},
            },
        },
    },
    "summarize_diff": {
        "handler": tool_summarize_diff,
        "description": "Get a summary of git diff between two refs",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cwd": {"type": "string"},
                "base": {"type": "string"},
                "head": {"type": "string"},
            },
        },
    },
    "collect_logs": {
        "handler": tool_collect_logs,
        "description": "Collect log files from a directory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "log_dir": {"type": "string"},
                "pattern": {"type": "string"},
            },
        },
    },
}


def handle_request(request: dict) -> dict:
    """Handle a single JSON-RPC 2.0 request."""
    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        return _json_rpc_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "triad-devtools", "version": "0.1.0"},
        })

    if method == "tools/list":
        tool_list = []
        for name, spec in TOOLS.items():
            tool_list.append({
                "name": name,
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
            })
        return _json_rpc_response(req_id, {"tools": tool_list})

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        if tool_name not in TOOLS:
            return _json_rpc_error(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            result = TOOLS[tool_name]["handler"](tool_args)
            return _json_rpc_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            })
        except Exception as e:
            return _json_rpc_error(req_id, -32000, str(e))

    if method == "notifications/initialized":
        return None  # Notifications don't get responses

    return _json_rpc_error(req_id, -32601, f"Method not found: {method}")


def main():
    """Run the MCP server on stdio."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = _json_rpc_error(None, -32700, "Parse error")
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
