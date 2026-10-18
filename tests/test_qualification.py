"""Offline qualification contracts. Never call a real inference provider."""
import importlib.util
import json
import unittest
from unittest.mock import patch

SOURCE = {"title": "Need help", "text": "Our traffic dropped. Looking for an agency.",
          "score": 42, "persona": "saas", "status": "new"}


class QualificationTests(unittest.TestCase):
    def test_export_gets_grounded_manual_review_without_changing_baseline(self):
        self.assertIsNotNone(importlib.util.find_spec("listener.qualification"),
                             "Optional second-pass qualification is not implemented")
        from listener.qualification import qualify
        answer = {"verdict": "review", "evidence": [
            {"field": "text", "quote": "Looking for an agency."}],
            "missing": ["budget"]}
        with patch("listener.qualification.request_completion", return_value=json.dumps(answer)) as call:
            result = qualify(SOURCE, enabled=True, base_url="https://model.example/v1",
                             model="test-model", api_key="test-key")
        self.assertEqual(result["baseline"], SOURCE)
        self.assertEqual(result["qualification"]["evidence"], answer["evidence"])
        self.assertEqual(result["qualification"]["outreach"], "manual_only")
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(call.call_args.kwargs["model"], "test-model")

    def test_fail_closed_keeps_baseline_and_never_retries_elsewhere(self):
        from listener.qualification import qualify
        bad = ["not json", "[]", "null", '{}',
               json.dumps({"verdict": "review", "evidence": [{"field": "text", "quote": "Budget $1m"}], "missing": []}),
               json.dumps({"verdict": "review", "evidence": [], "missing": []}),
               json.dumps({"verdict": "review", "evidence": [{"field": "text", "quote": ""}], "missing": []}),
               json.dumps({"verdict": "unknown", "evidence": [], "missing": ["made up"]}),
               json.dumps({"verdict": "unknown", "evidence": [], "missing": [], "send_email": True})]
        for output in bad:
            with self.subTest(output=output), patch("listener.qualification.request_completion", return_value=output) as call:
                result = qualify(SOURCE, enabled=True, base_url="https://model.example/v1", model="test", api_key="key")
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["baseline"], SOURCE)
                self.assertIsNone(result["qualification"])
                self.assertEqual(call.call_count, 1)
        for error in [TimeoutError("secret"), OSError("secret"), ValueError("secret")]:
            with patch("listener.qualification.request_completion", side_effect=error) as call:
                result = qualify(SOURCE, enabled=True, base_url="https://model.example/v1", model="test", api_key="key")
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["baseline"], SOURCE)
                self.assertNotIn("secret", json.dumps(result))
                self.assertEqual(call.call_count, 1)

    def test_off_missing_config_and_insecure_http_never_call(self):
        from listener.qualification import qualify
        for options in [{}, {"enabled": True},
                        {"enabled": True, "base_url": "https://api.openai.com/v1", "model": "test"},
                        {"enabled": True, "base_url": "http://model.example/v1", "model": "test", "api_key": "key"}]:
            with self.subTest(options=options), patch("listener.qualification.request_completion") as call:
                result = qualify(SOURCE, **options)
                call.assert_not_called()
                self.assertEqual(result["baseline"], SOURCE)
                self.assertIsNone(result["qualification"])

    def test_cli_is_opt_in_and_reads_export_without_mutating_it(self):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'signals.json')
            with open(path, 'w') as file:
                json.dump([SOURCE], file)
            process = subprocess.run(['python', '-m', 'listener.qualification', path],
                                     text=True, capture_output=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(process.stdout.strip(), 'CLI must emit reviewed export JSON')
            self.assertEqual(json.loads(process.stdout)[0]['baseline'], SOURCE)
            self.assertEqual(json.loads(process.stdout)[0]['status'], 'disabled')
            with open(path) as file:
                self.assertEqual(json.load(file), [SOURCE])

    def test_http_transport_no_redirects_bounded_response_and_timeout(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from listener.qualification import qualify
        calls = []
        answer = {"verdict": "review", "evidence": [{"field": "text", "quote": "traffic dropped"}], "missing": ["budget"]}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                calls.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                if self.path.startswith('/redirect'):
                    self.send_response(307)
                    self.send_header('Location', '/good/chat/completions')
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                payload = {'choices': [{'message': {'content': json.dumps(answer)}, 'finish_reason': 'stop'}]}
                if self.path.startswith('/large'):
                    payload['padding'] = 'x' * 1000001
                if self.path.startswith('/truncated'):
                    payload['choices'][0]['finish_reason'] = 'length'
                if self.path.startswith('/bad-choice'):
                    payload = {'choices': [[]]}
                self.wfile.write(json.dumps(payload).encode())

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            options = dict(enabled=True, model='test', api_key='test', allow_insecure_http=True, timeout=1)
            url = f'http://127.0.0.1:{server.server_port}'
            self.assertEqual(qualify(SOURCE, base_url=url + '/good', **options)['status'], 'qualified')
            self.assertEqual(calls[0][1]['reasoning_effort'], 'medium')
            self.assertEqual(set(json.loads(calls[0][1]['messages'][1]['content'])), {'title', 'text', 'community'})
            for route in ['/redirect', '/large', '/truncated', '/bad-choice']:
                with self.subTest(route=route):
                    self.assertEqual(qualify(SOURCE, base_url=url + route, **options)['status'], 'failed')
            self.assertEqual(len(calls), 5, 'no redirected or fallback request')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
