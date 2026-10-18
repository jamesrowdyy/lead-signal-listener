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


if __name__ == "__main__":
    unittest.main()
