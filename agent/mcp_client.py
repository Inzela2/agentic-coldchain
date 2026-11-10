"""
MCP CLIENT: the agent's "hands".

The agent never imports the server's code. It starts the server as a separate
process and talks to it with JSON-RPC messages over stdin/stdout. That is the
whole point of MCP: tools are pluggable, swap the server and the agent gets
new abilities without code changes.

Lifecycle:
  1. start()       -> launch server process, send "initialize", then "notifications/initialized"
  2. list_tools()  -> discover what the server can do
  3. call_tool()   -> use a tool
  4. close()       -> shut the server down
"""
import json
import subprocess

PROTOCOL_VERSION = "2024-11-05"


class MCPError(Exception):
    pass


class MCPClient:
    def __init__(self, command, on_message=None):
        """
        command    : how to start the server, e.g. ["python", "mcp_server/server.py"]
        on_message : optional callback(direction, message) to watch raw protocol traffic
        """
        self.command = command
        self.on_message = on_message
        self.proc = None
        self.server_info = {}
        self._next_id = 0

    # ---- lifecycle ---------------------------------------------------------
    def start(self):
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # server logs go to stderr; hide them in the demo
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "demo-agent", "version": "1.0.0"},
        })
        self.server_info = result.get("serverInfo", {})
        self._notify("notifications/initialized")
        return result

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- public API --------------------------------------------------------
    def list_tools(self):
        return self._request("tools/list").get("tools", [])

    def call_tool(self, name, arguments):
        """Returns (text, is_error)."""
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(
            block.get("text", "") for block in result.get("content", []) if block.get("type") == "text"
        )
        return text, bool(result.get("isError"))

    # ---- JSON-RPC plumbing -------------------------------------------------
    def _send(self, message):
        if self.on_message:
            self.on_message("->", message)
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def _notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}  # no "id" = notification
        if params is not None:
            message["params"] = params
        self._send(message)

    def _request(self, method, params=None):
        self._next_id += 1
        request_id = self._next_id
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise MCPError("Server closed the connection")
            response = json.loads(line)
            if self.on_message:
                self.on_message("<-", response)
            if response.get("id") != request_id:
                continue  # not our answer (e.g. a server notification)
            if "error" in response:
                err = response["error"]
                raise MCPError(f"{err.get('message')} (code {err.get('code')})")
            return response["result"]
