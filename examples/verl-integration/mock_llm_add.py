#!/usr/bin/env python3
"""Mock LLM server that always returns a correct `add(a, b)` solution."""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler


class MockLLMHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            payload = json.loads(body.decode())
            response = {
                "choices": [
                    {
                        "message": {
                            "content": "```python\ndef add(a, b):\n    return a + b\n```"
                        },
                        "logprobs": {
                            "content": [
                                {"token": "def", "logprob": -0.1},
                                {"token": " add", "logprob": -0.1},
                                {"token": "(", "logprob": -0.1},
                                {"token": "a", "logprob": -0.1},
                                {"token": ",", "logprob": -0.1},
                                {"token": " b", "logprob": -0.1},
                                {"token": ")", "logprob": -0.1},
                                {"token": ":", "logprob": -0.1},
                                {"token": " return", "logprob": -0.1},
                                {"token": " a", "logprob": -0.1},
                                {"token": " +", "logprob": -0.1},
                                {"token": " b", "logprob": -0.1},
                            ]
                        },
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 12},
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
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()
    server = HTTPServer((args.host, args.port), MockLLMHandler)
    print(f"Mock LLM (add demo) serving on http://{args.host}:{args.port}/v1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
