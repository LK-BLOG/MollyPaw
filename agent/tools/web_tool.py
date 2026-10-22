"""Web search and fetch tools for the agent."""
import base64
import html
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

import requests


class _TextExtractor(HTMLParser):
    """Extract visible text from an HTML document."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "template"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and tag.lower() in {"p", "div", "br", "li", "h1", "h2", "h3", "h4"}:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def text(self):
        value = html.unescape(" ".join(self._parts))
        value = re.sub(r"[ \t\r\f\v]+", " ", value)
        value = re.sub(r"\n\s*\n+", "\n\n", value)
        return value.strip()


class WebTool:
    """Bing HTML search and safe URL fetching."""

    def __init__(self, timeout=20):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the live web using Bing international HTML results. Use this for current information and source discovery.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "count": {"type": "integer", "description": "Number of results, 1-10. Default 5."},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch",
                "description": "Fetch a public http/https URL and return readable text or JSON. Localhost, private networks, and unsafe redirects are blocked.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Public http or https URL."},
                        "max_chars": {"type": "integer", "description": "Maximum returned characters, 1000-50000. Default 20000."},
                    },
                    "required": ["url"],
                },
            },
        },
    ]

    def execute(self, func_name, arguments):
        if func_name == "web_search":
            return self.web_search(**arguments)
        if func_name == "fetch":
            return self.fetch(**arguments)
        return f"Error: WebTool has no method '{func_name}'"

    def web_search(self, query, count=5):
        query = str(query or "").strip()
        if not query:
            return "Error: query is required."
        try:
            count = max(1, min(int(count), 10))
        except (TypeError, ValueError):
            count = 5
        try:
            response = requests.get(
                "https://www.bing.com/search",
                params={"q": query, "setlang": "en-US", "cc": "US", "mkt": "en-US", "ensearch": "1", "count": count},
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            results = self._parse_bing_results(response.text, count)
        except Exception as exc:
            return f"Error searching Bing: {exc}"
        if not results:
            return "No search results found."
        chunks = []
        for index, item in enumerate(results, 1):
            chunks.append(f"{index}. {item['title']}\n{item['url']}\n{item['snippet']}")
        return "\n\n".join(chunks)

    def fetch(self, url, max_chars=20000):
        try:
            max_chars = max(1000, min(int(max_chars), 50000))
        except (TypeError, ValueError):
            max_chars = 20000
        try:
            response, raw = self._public_get(url)
            content_type = (response.headers.get("Content-Type") or "").lower()
            encoding = response.encoding or response.apparent_encoding or "utf-8"
            text = raw.decode(encoding, errors="replace")
            if "html" in content_type or "<html" in text[:1000].lower():
                parser = _TextExtractor()
                parser.feed(text)
                text = parser.text()
            elif "json" in content_type:
                try:
                    text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    pass
            elif not ("text/" in content_type or "xml" in content_type):
                return f"Error: unsupported content type: {content_type or 'unknown'}"
            suffix = "\n\n[truncated]" if len(text) > max_chars else ""
            return f"URL: {response.url}\n\n{text[:max_chars]}{suffix}"
        except Exception as exc:
            return f"Error fetching URL: {exc}"

    def _public_get(self, url):
        current = str(url or "").strip()
        for _ in range(6):
            self._validate_public_url(current)
            response = requests.get(
                current,
                headers=self.headers,
                timeout=self.timeout,
                allow_redirects=False,
                stream=True,
            )
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise ValueError("redirect response has no Location header")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            self._validate_public_url(response.url)
            chunks = []
            size = 0
            for chunk in response.iter_content(8192):
                if not chunk:
                    continue
                chunks.append(chunk)
                size += len(chunk)
                if size >= 2 * 1024 * 1024:
                    break
            response.close()
            return response, b"".join(chunks)
        raise ValueError("too many redirects")

    @staticmethod
    def _validate_public_url(url):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("only http and https URLs are allowed")
        if not parsed.hostname:
            raise ValueError("URL has no hostname")
        if parsed.username or parsed.password:
            raise ValueError("credentials in URLs are not allowed")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror as exc:
            raise ValueError(f"cannot resolve host: {exc}") from exc
        for info in addresses:
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                raise ValueError("private, local, or reserved network targets are blocked")

    @staticmethod
    def _clean_html(value):
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()

    @staticmethod
    def _unwrap_bing_url(url):
        parsed = urlparse(url)
        if "bing.com" not in (parsed.hostname or "") or not parsed.path.startswith("/ck/a"):
            return url
        encoded = parse_qs(parsed.query).get("u", [""])[0]
        if not encoded.startswith("a1"):
            return url
        try:
            value = encoded[2:]
            value += "=" * (-len(value) % 4)
            return base64.urlsafe_b64decode(value).decode("utf-8")
        except Exception:
            return url

    def _parse_bing_results(self, page, count):
        results = []
        blocks = re.findall(r'<li[^>]+class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>', page, re.S | re.I)
        for block in blocks:
            link = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
            if not link:
                continue
            url = self._unwrap_bing_url(html.unescape(link.group(1)).strip())
            if not url.startswith(("http://", "https://")):
                continue
            title = self._clean_html(link.group(2))
            snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.S | re.I)
            snippet = self._clean_html(snippet_match.group(1)) if snippet_match else ""
            if title:
                results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= count:
                break
        return results
