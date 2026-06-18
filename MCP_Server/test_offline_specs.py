import json
import socket
import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_DIR = ROOT / "MCP_Server"
TCP_DIR = ROOT / "Remote_TCP_Bridge"
for path in (str(MCP_DIR), str(TCP_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class Recorder:
    def __init__(self):
        self.calls = []

    def send(self, method, params=None):
        self.calls.append((method, params or {}))
        return {"success": True, "method": method, "params": params or {}}


class FakeSocket:
    def __init__(self, chunks=(), error=None):
        self.chunks = list(chunks)
        self.error = error
        self.sent = b""
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def recv(self, size):
        if self.error:
            raise self.error
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) > size:
            self.chunks.insert(0, chunk[size:])
            return chunk[:size]
        return chunk

    def sendall(self, data):
        self.sent += data


def frame(payload):
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


class ToolSpecTests(unittest.TestCase):
    def test_tool_specs_match_lua_dispatcher(self):
        import ce_tool_specs

        lua = (MCP_DIR / "ce_mcp_bridge.lua").read_text(encoding="utf-8")
        handlers = set()
        for line in lua.splitlines():
            stripped = line.strip()
            if " = cmd_" in stripped:
                handlers.add(stripped.split("=", 1)[0].strip())

        missing = sorted(
            spec.method for spec in ce_tool_specs.TOOL_SPECS if spec.method not in handlers
        )
        self.assertEqual([], missing)

    def test_generated_tool_payloads_use_lua_wire_names(self):
        import ce_tool_specs

        mcp = FakeMCP()
        recorder = Recorder()
        ce_tool_specs.register_ce_tools(mcp, recorder.send, lambda result: result)

        mcp.tools["read_pointer_chain"]("0x1000", [4, 8])
        self.assertEqual(
            ("read_pointer_chain", {"base": "0x1000", "offsets": [4, 8]}),
            recorder.calls[-1],
        )

        mcp.tools["read_pointer"]("0x1000")
        self.assertEqual(
            ("read_pointer_chain", {"base": "0x1000", "offsets": [0]}),
            recorder.calls[-1],
        )

        mcp.tools["write_memory"]("0x1000", [0x90, 0xCC])
        self.assertEqual(
            ("write_memory", {"address": "0x1000", "bytes": [0x90, 0xCC]}),
            recorder.calls[-1],
        )

        mcp.tools["remove_breakpoint"]("bp-main")
        self.assertEqual(
            ("remove_breakpoint", {"id": "bp-main"}),
            recorder.calls[-1],
        )

    def test_remote_legacy_unsupported_tools_are_not_in_specs(self):
        import ce_tool_specs

        legacy = {"get_version", "list_processes", "attach_process", "get_module_base"}
        self.assertTrue(legacy.isdisjoint(ce_tool_specs.TOOL_NAMES))

    def test_bridge_status_is_shared_ce_tool(self):
        import ce_tool_specs

        self.assertIn("get_bridge_status", ce_tool_specs.TOOL_NAMES)
        status_spec = next(spec for spec in ce_tool_specs.TOOL_SPECS if spec.name == "get_bridge_status")
        self.assertEqual("get_bridge_status", status_spec.method)

        mcp = FakeMCP()
        recorder = Recorder()
        ce_tool_specs.register_ce_tools(mcp, recorder.send, lambda result: result)
        mcp.tools["get_bridge_status"]()
        self.assertEqual(("get_bridge_status", {}), recorder.calls[-1])


class TcpProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import ce_tcp_bridge_server
        except SystemExit:
            ce_tcp_bridge_server = None
        cls.tcp_server = ce_tcp_bridge_server

    def setUp(self):
        if self.tcp_server is None:
            self.skipTest("pywin32 is required to import ce_tcp_bridge_server")

    def test_read_framed_message_accepts_chunked_payload(self):
        payload = b'{"jsonrpc":"2.0","method":"ping"}'
        sock = FakeSocket([frame(payload)[:2], frame(payload)[2:9], frame(payload)[9:]])
        header, body = self.tcp_server.read_framed_message(sock)
        self.assertEqual(struct.pack("<I", len(payload)), header)
        self.assertEqual(payload, body)

    def test_read_framed_message_rejects_short_header(self):
        sock = FakeSocket([b"\x01", b""])
        with self.assertRaises(ConnectionError):
            self.tcp_server.read_framed_message(sock)

    def test_read_framed_message_rejects_oversized_body(self):
        sock = FakeSocket([struct.pack("<I", self.tcp_server.MAX_MESSAGE_SIZE + 1)])
        with self.assertRaises(ValueError):
            self.tcp_server.read_framed_message(sock)

    def test_read_framed_message_converts_socket_timeout(self):
        sock = FakeSocket(error=socket.timeout("slow client"))
        with self.assertRaises(TimeoutError):
            self.tcp_server.read_framed_message(sock)

    def test_authenticate_client_accepts_correct_token(self):
        request = {
            "jsonrpc": "2.0",
            "method": self.tcp_server.AUTH_METHOD,
            "params": {"token": "secret"},
            "id": "auth",
        }
        sock = FakeSocket([frame(request)])
        self.assertTrue(self.tcp_server.authenticate_client(sock, "secret"))
        _, body = self.tcp_server.read_frame_from_bytes(sock.sent)
        response = json.loads(body.decode("utf-8"))
        self.assertTrue(response["result"]["success"])

    def test_authenticate_client_rejects_bad_token(self):
        request = {
            "jsonrpc": "2.0",
            "method": self.tcp_server.AUTH_METHOD,
            "params": {"token": "bad"},
            "id": "auth",
        }
        sock = FakeSocket([frame(request)])
        self.assertFalse(self.tcp_server.authenticate_client(sock, "secret"))
        _, body = self.tcp_server.read_frame_from_bytes(sock.sent)
        response = json.loads(body.decode("utf-8"))
        self.assertIn("error", response)

    def test_transport_status_has_safe_fields(self):
        status = self.tcp_server.build_transport_status()
        self.assertTrue(status["success"])
        self.assertIn("uptime_seconds", status)
        self.assertIn("auth_enabled", status)
        self.assertIn("active_client_count", status)
        encoded = json.dumps(status)
        self.assertNotIn("CE_BRIDGE_TOKEN", encoded)
        self.assertNotIn("secret", encoded)

    def test_status_request_is_handled_without_pipe(self):
        request = {
            "jsonrpc": "2.0",
            "method": self.tcp_server.STATUS_METHOD,
            "params": {},
            "id": 7,
        }
        sock = FakeSocket([frame(request)])
        handled, first_frame = self.tcp_server.handle_internal_request(sock)
        self.assertTrue(handled)
        self.assertIsNone(first_frame)
        _, body = self.tcp_server.read_frame_from_bytes(sock.sent)
        response = json.loads(body.decode("utf-8"))
        self.assertEqual(7, response["id"])
        self.assertTrue(response["result"]["success"])

    def test_status_request_after_auth_is_handled_without_pipe(self):
        auth = {
            "jsonrpc": "2.0",
            "method": self.tcp_server.AUTH_METHOD,
            "params": {"token": "secret"},
            "id": "auth",
        }
        request = {
            "jsonrpc": "2.0",
            "method": self.tcp_server.STATUS_METHOD,
            "params": {},
            "id": "status",
        }
        sock = FakeSocket([frame(auth), frame(request)])
        self.assertTrue(self.tcp_server.authenticate_client(sock, "secret"))
        handled, first_frame = self.tcp_server.handle_internal_request(sock)
        self.assertTrue(handled)
        self.assertIsNone(first_frame)

        first_header, first_body = self.tcp_server.read_frame_from_bytes(sock.sent)
        remaining = sock.sent[4 + struct.unpack("<I", first_header)[0]:]
        _, second_body = self.tcp_server.read_frame_from_bytes(remaining)
        self.assertTrue(json.loads(first_body.decode("utf-8"))["result"]["success"])
        self.assertTrue(json.loads(second_body.decode("utf-8"))["result"]["success"])


if __name__ == "__main__":
    unittest.main()
