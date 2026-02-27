"""Tests for mcp.devtools_server module."""

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from mcp.devtools_server import handle_request, TOOLS


def test_initialize():
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = handle_request(req)
    assert resp["id"] == 1
    assert "protocolVersion" in resp["result"]
    assert "capabilities" in resp["result"]


def test_tools_list():
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = handle_request(req)
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "run_tests" in names
    assert "run_lint" in names
    assert "run_typecheck" in names
    assert "take_screenshot" in names
    assert "summarize_diff" in names
    assert "collect_logs" in names


def test_tools_call_run_tests():
    req = {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "run_tests", "arguments": {"command": "echo ok"}},
    }
    resp = handle_request(req)
    content = resp["result"]["content"]
    assert len(content) > 0
    assert content[0]["type"] == "text"


def test_tools_call_unknown():
    req = {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "nonexistent", "arguments": {}},
    }
    resp = handle_request(req)
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_unknown_method():
    req = {"jsonrpc": "2.0", "id": 5, "method": "foo/bar", "params": {}}
    resp = handle_request(req)
    assert "error" in resp


def test_notification_no_response():
    req = {"jsonrpc": "2.0", "id": 6, "method": "notifications/initialized", "params": {}}
    resp = handle_request(req)
    assert resp is None


def test_collect_logs(tmp_path):
    (tmp_path / "test.log").write_text("log line 1\nlog line 2\n")
    req = {
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "collect_logs", "arguments": {"log_dir": str(tmp_path), "pattern": "*.log"}},
    }
    resp = handle_request(req)
    assert "content" in resp["result"]
