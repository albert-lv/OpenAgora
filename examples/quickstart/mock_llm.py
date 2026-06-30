#!/usr/bin/env python3
"""Mock LLM server for quickstart testing."""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler


class MockLLMHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence logs

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            payload = json.loads(body.decode())
            response = {
                "choices": [
                    {
                        "message": {"content": "print('hello')"},
                        "logprobs": {
                            "content": [
                                {"token": "print", "logprob": -0.1},
                                {"token": "(", "logprob": -0.1},
                                {"token": "'", "logprob": -0.1},
                                {"token": "hello", "logprob": -0.1},
                                {"token": "'", "logprob": -0.1},
                                {"token": ")", "logprob": -0.1},
                            ]
                        },
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), MockLLMHandler)
    print(f"Mock LLM serving on http://127.0.0.1:{args.port}/v1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
