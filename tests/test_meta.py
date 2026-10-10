import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from listener import sources  # noqa: E402

# Shapes from https://treg.to/catalog/endpoints/<id> example_response
FB_POSTS = {"code": 0, "data": {"cursor": "abc", "results": [
    {"post_id": "1687", "url": "https://www.facebook.com/x/posts/1687", "message": "Looking for an agency, ChatGPT ignores us",
     "timestamp": 1785202291, "comments_count": 3, "reactions_count": 99,
     "author": {"name": "Button Willow Store", "url": "https://www.facebook.com/bw"}},
    {"post_id": "1688", "message": ""}]}}
FB_GROUP = {"output": {"data": {"nextCursor": "n1", "posts": [
    {"authorId": "726", "authorName": "Jane", "commentCount": 2, "id": "3792", "publishTime": int(time.time()) - 3600,
     "reactionCount": 5, "text": "Any recommendations for SEO help?", "url": "https://www.facebook.com/groups/127/permalink/3792/"},
    {"authorId": "727", "authorName": "Old", "id": "1", "publishTime": 1000, "text": "ancient post", "url": ""},
    {"authorId": "728", "authorName": "Img", "id": "2", "publishTime": int(time.time()), "text": "", "url": ""}]}, "found": True}}
IG_TAG = {"output": {"data": {"nextCursor": "c2", "posts": [
    {"caption": "3 step skincare routine #skincare", "comments": 5, "createdUtc": 1787778132, "id": "397249",
     "likes": 754, "shortcode": "DchIV", "url": "https://www.instagram.com/reel/DchIV/", "username": "dylan"}]}}}
IG_REELS = {"output": {"data": {"nextCursor": "c3", "reels": [
    {"caption": "How I got my brand into ChatGPT", "comments": 288, "createdUtc": int(time.time()) - 7200, "likes": 5161,
     "shortcode": "DcaexE", "url": "https://www.instagram.com/reel/DcaexE/", "username": "plottwist"}]}}}


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.last = None

    def call(self, endpoint, query=None, body=None, method=None, idempotency_seed=None):
        self.last = (endpoint, query, body)
        return self.resp, 0


class MetaParserTests(unittest.TestCase):
    def test_facebook_posts(self):
        [r] = sources.parse_facebook_posts(FB_POSTS, "q")  # empty message skipped
        self.assertEqual((r["source"], r["author"], r["engagement"]), ("facebook", "Button Willow Store", 102))
        rows, nxt = sources.fetch_facebook_posts(FakeClient(FB_POSTS), "q", 7)
        self.assertEqual((len(rows), nxt), (1, "abc"))

    def test_facebook_group_drops_old_and_empty(self):
        client = FakeClient(FB_GROUP)
        rows, nxt = sources.fetch_facebook_group(client, "https://www.facebook.com/groups/127/", 7)
        self.assertEqual([r["external_id"] for r in rows], ["3792"])
        self.assertEqual(rows[0]["community"], "FB group · 127")
        self.assertEqual(nxt, "n1")
        self.assertEqual(client.last[2]["url"], "https://www.facebook.com/groups/127/")

    def test_instagram_hashtag_strips_hash(self):
        client = FakeClient(IG_TAG)
        rows, nxt = sources.fetch_instagram_hashtag(client, "#skin care", 7)
        self.assertEqual(client.last[2]["hashtag"], "skincare")
        self.assertEqual((rows[0]["community"], rows[0]["author_url"], nxt),
                         ("#skincare", "https://www.instagram.com/dylan/", "c2"))

    def test_instagram_reels(self):
        rows, nxt = sources.fetch_instagram_reels(FakeClient(IG_REELS), "ChatGPT SEO", 7)
        self.assertEqual((rows[0]["source"], rows[0]["external_id"], nxt), ("instagram_reels", "DcaexE", "c3"))
        # Reels endpoint has no date filter, so old reels are dropped locally.
        old = {"output": {"data": {"reels": [dict(IG_REELS["output"]["data"]["reels"][0], createdUtc=1000)]}}}
        self.assertEqual(sources.fetch_instagram_reels(FakeClient(old), "q", 7)[0], [])


if __name__ == "__main__":
    unittest.main()
