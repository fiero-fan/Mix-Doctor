#!/usr/bin/env python3
"""
Talk to Ableton Live through the AbletonMCP Remote Script (127.0.0.1:9877).
Same commands the ableton MCP server uses; handy when its tools aren't loaded.

  python3 tools/live.py get_session_info
  python3 tools/live.py get_track_info '{"track_index": 2}'
  python3 tools/live.py set_device_parameter '{"track_index": 2, "device_index": 0, "parameter_index": 1, "value": 64}'
"""
import json, socket, sys


def call(command, **params):
    s = socket.create_connection(("127.0.0.1", 9877), timeout=10)
    s.sendall(json.dumps({"type": command, "params": params}).encode())
    buf = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
        try:
            return json.loads(buf.decode())
        except ValueError:
            pass
    return json.loads(buf.decode())


if __name__ == "__main__":
    print(json.dumps(call(sys.argv[1], **json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")), indent=1))
