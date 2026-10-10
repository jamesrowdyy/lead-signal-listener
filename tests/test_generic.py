import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from listener import generic  # noqa: E402

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>r/SaaS</title>
<item><title>Organic traffic dropped after AI Overviews</title><link>https://reddit.com/r/SaaS/1</link>
<guid>t3_1</guid><description>&lt;p&gt;Any recommendations?&lt;/p&gt;</description><pubDate>Wed, 08 Oct 2026 12:00:00 GMT</pubDate></item>
<item><title>Unrelated post</title><link>https://reddit.com/r/SaaS/2</link></item>
</channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Alerts</title>
<entry><id>tag:1</id><title>ChatGPT doesn't mention us</title><link href="https://example.com/a"/>
<content>We need help</content><author><name>jane</name></author><published>2026-10-08T12:00:00Z</published></entry></feed>"""
YT = {"output": {"videos": [{"video_id": "abc", "title": "My store isn't in ChatGPT", "author": "Steve",
                             "number_of_views": "50", "published_time": "2 weeks ago", "description": "help"}],
                 "next_cursor": None}}


class GenericTests(unittest.TestCase):
    def test_rss_with_keyword_filter(self):
        rows = generic.parse_feed(RSS, "https://reddit.com/r/SaaS/.rss", ["ai overviews"])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["external_id"], r["community"], r["text"]), ("t3_1", "r/SaaS", "Any recommendations?"))
        self.assertIsNotNone(r["created_utc"])
        self.assertEqual(len(generic.parse_feed(RSS, "u")), 2)

    def test_atom(self):
        [r] = generic.parse_feed(ATOM, "u")
        self.assertEqual((r["url"], r["author"], r["community"]), ("https://example.com/a", "jane", "Alerts"))

    def test_custom_mapping_and_url_template(self):
        src = {"name": "youtube", "kind": "pain", "url_template": "https://www.youtube.com/watch?v={id}",
               "fields": {"id": "video_id", "created": "published_time"}}
        [r] = generic.map_items(generic.find_items(YT), src, "q")
        self.assertEqual(r["url"], "https://www.youtube.com/watch?v=abc")
        self.assertEqual((r["source"], r["author"], r["engagement"]), ("youtube", "Steve", 50))
        self.assertGreater(r["created_utc"], 0)

    def test_fill_template(self):
        self.assertEqual(generic._fill({"q": "{q}", "n": "{days}", "x": ["a {q}"]}, "geo", 7),
                         {"q": "geo", "n": 7, "x": ["a geo"]})

    def test_import(self):
        rows = generic.normalize_imported({"signals": [
            {"url": "https://x.com/a/status/1", "text": "need a GEO agency", "author": "a", "source": "agent"},
            {"title": "missing id and url"}]})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["source"], rows[0]["external_id"]), ("agent", "https://x.com/a/status/1"))


if __name__ == "__main__":
    unittest.main()
