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


if __name__ == "__main__":
    unittest.main()
