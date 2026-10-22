import unittest
from unittest.mock import Mock, patch

from agent.tools.web_tool import WebTool


class WebToolTests(unittest.TestCase):
    def test_bing_html_results_are_parsed(self):
        page = """<li class="b_algo"><h2><a href="https://example.com/a">Example Title</a></h2><p>Example <b>snippet</b>.</p></li><li class="b_algo"><h2><a href="https://example.com/b">Second</a></h2><p>Second snippet.</p></li>"""
        results = WebTool()._parse_bing_results(page, 5)
        self.assertEqual(results[0]["title"], "Example Title")
        self.assertEqual(results[0]["url"], "https://example.com/a")
        self.assertEqual(results[0]["snippet"], "Example snippet .")

    def test_fetch_rejects_localhost(self):
        result = WebTool().fetch("http://127.0.0.1/private")
        self.assertIn("blocked", result)

    def test_fetch_strips_html(self):
        response = Mock()
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.encoding = "utf-8"
        response.url = "https://example.com/page"
        tool = WebTool()
        with patch.object(tool, "_public_get", return_value=(response, b"<html><body><h1>Title</h1><script>bad()</script><p>Hello world.</p></body></html>")):
            result = tool.fetch("https://example.com/page")
        self.assertIn("Title", result)
        self.assertIn("Hello world.", result)
        self.assertNotIn("bad()", result)


if __name__ == "__main__":
    unittest.main()
