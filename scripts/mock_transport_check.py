"""Local HTTP integration test of transport. MOCK, not EXAONE/Qwen/API inference."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scope_lab.model_client import chat


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/v1/chat/completions" or self.headers.get("Authorization") != "Bearer local-mock-only":
            self.send_error(401)
            return
        answer = {"model": body["model"], "choices": [{"message": {"content": "READY"}, "finish_reason": "stop"}],
                  "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        raw = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["MOCK_ONLY_KEY"] = "local-mock-only"
    try:
        result = chat({"base_url": "http://127.0.0.1:{}/v1".format(server.server_port),
                       "model": "mock-not-a-model", "key_env": "MOCK_ONLY_KEY", "extra_body": {}},
                      [{"role": "user", "content": "Reply READY"}])
        assert result["content"] == "READY"
        print(json.dumps({"transport_integration": "passed", "is_mock": True, "real_inference_verified": False}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        os.environ.pop("MOCK_ONLY_KEY", None)


if __name__ == "__main__":
    main()
