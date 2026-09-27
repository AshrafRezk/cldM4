"""Free public lookups for the `research` chat parameter.

The caller asks with `research: true` (or `Research`). The worker calls a fixed
set of keyless HTTPS APIs, then hands the hits to the model as inputs and
returns the same bundle on the completion. User text is a search string, never
a URL, and every request host is on the allowlist below.

Sources: DuckDuckGo instant answers and Wikipedia (web), Reddit's public
search feed, Google News RSS plus Hacker News, Open-Meteo (weather), and
Open Library (books). Google's paid Custom Search API is not used.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import sqlite3
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import CloudiatorError

log = logging.getLogger("cloudiator.research")

SOURCES = ("web", "reddit", "news", "weather", "books")
SOURCE_SET = frozenset(SOURCES)
ALLOWED_HOSTS = frozenset(
    {
        "api.duckduckgo.com",
        "en.wikipedia.org",
        "www.reddit.com",
        "news.google.com",
        "hn.algolia.com",
        "geocoding-api.open-meteo.com",
        "api.open-meteo.com",
        "openlibrary.org",
    }
)
MAX_QUERY_CHARS = 240
MAX_BODY_BYTES = 200_000
MAX_NOTE_CHARS = 1_800
MAX_SNIPPET = 280
REDIRECTS = {301, 302, 303, 307, 308}
ATOM = {"a": "http://www.w3.org/2005/Atom"}
_SPACE = re.compile(r"\s+")
_TAG = re.compile(r"<[^>]+>")
_NOISE = re.compile(
    r"\b(weather|forecast|temperature|temp|today|tomorrow|tonight|now|current|"
    r"please|what|whats|what's|how's|how|is|the|a|an|in|at|for|like|tell|me|about)\b",
    re.IGNORECASE,
)
_GATE = asyncio.Semaphore(6)

DEFAULT_USER_AGENT = "Cloudiator/1.0 (research; +https://cloudiator.org)"


def assert_allowed(url: str) -> None:
    """Research may only call the fixed public APIs. Never a caller-supplied URL."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or host not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise CloudiatorError(
            400,
            "url_not_allowed",
            "Research only calls its fixed public APIs.",
            param="research",
        )


def clean_query(query: str, *, truncate: bool = False) -> str:
    if not isinstance(query, str):
        raise CloudiatorError(400, "invalid_request_error", "q is required.", param="q")
    text = "".join(ch for ch in query if ch in "\n\t" or ord(ch) >= 32)
    text = _SPACE.sub(" ", text).strip()
    if not text:
        raise CloudiatorError(400, "invalid_request_error", "q is required.", param="q")
    if len(text) > MAX_QUERY_CHARS:
        if not truncate:
            raise CloudiatorError(
                400,
                "invalid_request_error",
                f"q must be {MAX_QUERY_CHARS} characters or fewer.",
                param="q",
            )
        text = text[:MAX_QUERY_CHARS].rsplit(" ", 1)[0] or text[:MAX_QUERY_CHARS]
    return text


def normalize_sources(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return SOURCES
    if isinstance(raw, str):
        raw = [raw]
    elif isinstance(raw, tuple):
        raw = list(raw)
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        raise CloudiatorError(
            400,
            "invalid_request_error",
            "sources must be an array of source names.",
            param="sources",
        )
    unknown = [item for item in raw if item not in SOURCE_SET]
    if unknown:
        names = ", ".join(SOURCES)
        raise CloudiatorError(
            400,
            "invalid_request_error",
            f"Unknown research source {unknown[0]!r}. Use {names}.",
            param="sources",
        )
    ordered: list[str] = []
    for item in raw:
        if item not in ordered:
            ordered.append(item)
    return tuple(ordered)


@dataclass(frozen=True)
class ResearchSpec:
    """`query` is None when the latest user message should be searched."""

    query: str | None
    sources: tuple[str, ...]


def _raw_flag(body: dict[str, Any]) -> Any:
    if "research" in body:
        return body.get("research")
    if "Research" in body:
        return body.get("Research")
    return None


def research_requested(body: dict[str, Any]) -> bool:
    if "research" not in body and "Research" not in body:
        return False
    raw = _raw_flag(body)
    return raw is not False and raw is not None and raw != ""


def parse_research_option(body: dict[str, Any]) -> ResearchSpec | None:
    """Return None when research is off. Raises 400 when the flag is malformed."""
    if not research_requested(body):
        return None
    raw = _raw_flag(body)
    if raw is True:
        return ResearchSpec(query=None, sources=SOURCES)
    if isinstance(raw, str):
        return ResearchSpec(query=clean_query(raw), sources=SOURCES)
    if isinstance(raw, dict):
        sources = normalize_sources(raw.get("sources"))
        supplied = raw.get("q", raw.get("query"))
        if supplied is None or supplied == "":
            return ResearchSpec(query=None, sources=sources)
        if not isinstance(supplied, str):
            raise CloudiatorError(
                400, "invalid_request_error", "research.q must be a string.", param="research"
            )
        return ResearchSpec(query=clean_query(supplied), sources=sources)
    raise CloudiatorError(
        400,
        "invalid_request_error",
        "research must be true or an object with q and sources.",
        param="research",
    )


def place_candidates(query: str) -> list[str]:
    """Pull a place name out of a sentence so weather search is not the whole prompt."""
    raw = query.strip()
    found: list[str] = []
    match = re.search(r"\bin\s+([A-Za-z][\w .,'-]{1,60})", raw)
    if match:
        found.append(match.group(1).strip(" ?.,"))
    stripped = _NOISE.sub(" ", raw)
    stripped = _SPACE.sub(" ", stripped).strip(" ?.,")
    if stripped and stripped.casefold() not in {item.casefold() for item in found}:
        if stripped.casefold() != raw.casefold():
            found.append(stripped)
    if raw and raw.casefold() not in {item.casefold() for item in found}:
        found.append(raw)
    return [item for item in found if len(item) >= 2][:2]


def plain(value: str) -> str:
    text = html.unescape(_TAG.sub(" ", value or ""))
    return _SPACE.sub(" ", text).strip()


def _clip(value: str, limit: int) -> str:
    text = plain(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _safe_url(url: str) -> str:
    parsed = urllib.parse.urlsplit((url or "").strip())
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url.strip()
    return ""


def _hit(title: str, url: str, snippet: str, source: str) -> dict[str, str]:
    return {
        "title": _clip(title, 180),
        "url": _safe_url(url),
        "snippet": _clip(snippet, MAX_SNIPPET),
        "source": source,
    }


def parse_duckduckgo(body: bytes) -> list[dict[str, str]]:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    hits: list[dict[str, str]] = []
    abstract = plain(str(payload.get("Abstract") or ""))
    if abstract:
        hits.append(
            _hit(
                str(payload.get("Heading") or "Instant answer"),
                str(payload.get("AbstractURL") or ""),
                abstract,
                "duckduckgo",
            )
        )
    answer = plain(str(payload.get("Answer") or ""))
    if answer:
        hits.append(_hit("Answer", "", answer, "duckduckgo"))
    _collect_topics(payload.get("RelatedTopics"), hits)
    for item in payload.get("Results") or []:
        if isinstance(item, dict):
            hits.append(
                _hit(str(item.get("Text") or ""), str(item.get("FirstURL") or ""), "", "duckduckgo")
            )
    return [hit for hit in hits if hit["title"] or hit["snippet"]][:4]


def _collect_topics(items: Any, hits: list[dict[str, str]]) -> None:
    if not isinstance(items, list) or len(hits) >= 4:
        return
    for item in items:
        if not isinstance(item, dict) or len(hits) >= 4:
            continue
        if isinstance(item.get("Topics"), list):
            _collect_topics(item["Topics"], hits)
            continue
        text = str(item.get("Text") or "")
        url = str(item.get("FirstURL") or "")
        if text or url:
            hits.append(_hit(text, url, "", "duckduckgo"))


def parse_wikipedia_search(body: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    rows = (((payload or {}).get("query") or {}).get("search") if isinstance(payload, dict) else None)
    if not isinstance(rows, list):
        return []
    found = []
    for row in rows[:2]:
        if isinstance(row, dict) and row.get("title"):
            found.append({"title": str(row["title"]), "snippet": plain(str(row.get("snippet") or ""))})
    return found


def parse_wikipedia_summary(body: bytes) -> dict[str, str] | None:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("type") == "disambiguation":
        return None
    title = str(payload.get("title") or "")
    extract = plain(str(payload.get("extract") or ""))
    if not title and not extract:
        return None
    content_urls = payload.get("content_urls") or {}
    desktop = content_urls.get("desktop") if isinstance(content_urls, dict) else None
    url = ""
    if isinstance(desktop, dict):
        url = str(desktop.get("page") or "")
    return _hit(title, url, extract, "wikipedia")


def parse_reddit_json(body: bytes) -> list[dict[str, str]] | None:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    children = (payload.get("data") or {}).get("children") if isinstance(payload.get("data"), dict) else None
    if not isinstance(children, list):
        return None
    hits = []
    for child in children[:5]:
        post = child.get("data") if isinstance(child, dict) else None
        if not isinstance(post, dict):
            continue
        permalink = str(post.get("permalink") or "")
        url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else str(post.get("url") or "")
        sub = str(post.get("subreddit_name_prefixed") or "")
        snippet = plain(str(post.get("selftext") or ""))
        if sub:
            snippet = f"{sub}. {snippet}".strip()
        hits.append(_hit(str(post.get("title") or ""), url, snippet, "reddit"))
    return hits


def parse_reddit_atom(body: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(body)
    hits = []
    for entry in root.findall("a:entry", ATOM)[:5]:
        title = entry.findtext("a:title", default="", namespaces=ATOM)
        link = ""
        for element in entry.findall("a:link", ATOM):
            if element.get("rel") in (None, "alternate"):
                link = element.get("href") or ""
                break
        content = entry.findtext("a:content", default="", namespaces=ATOM) or ""
        category = entry.find("a:category", ATOM)
        label = (category.get("label") if category is not None else "") or ""
        snippet = plain(content)
        if label:
            snippet = f"{label}. {snippet}".strip()
        hit = _hit(title or snippet[:80], link, snippet, "reddit")
        if hit["title"] or hit["snippet"]:
            hits.append(hit)
    return hits


def parse_google_news(body: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(body)
    hits = []
    for item in root.findall("./channel/item")[:4]:
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        source = item.findtext("source") or "Google News"
        hits.append(_hit(title, link, source, "google_news"))
    return [hit for hit in hits if hit["title"]]


def parse_hacker_news(body: bytes) -> list[dict[str, str]]:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    rows = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    hits = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "")
        if not url and row.get("objectID"):
            url = f"https://news.ycombinator.com/item?id={row['objectID']}"
        points = row.get("points")
        author = row.get("author") or ""
        snippet = f"{points} points · {author}".strip(" ·") if points is not None else str(author)
        hits.append(_hit(str(row.get("title") or ""), url, snippet, "hackernews"))
    return [hit for hit in hits if hit["title"]]


def parse_open_library(body: bytes) -> list[dict[str, str]]:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    docs = payload.get("docs") if isinstance(payload, dict) else None
    if not isinstance(docs, list):
        return []
    hits = []
    for doc in docs[:5]:
        if not isinstance(doc, dict):
            continue
        authors = doc.get("author_name") or []
        if not isinstance(authors, list):
            authors = []
        year = doc.get("first_publish_year")
        bits = [", ".join(str(name) for name in authors[:3])]
        if year:
            bits.append(str(year))
        key = str(doc.get("key") or "")
        url = f"https://openlibrary.org{key}" if key.startswith("/") else ""
        hits.append(_hit(str(doc.get("title") or ""), url, " · ".join(bit for bit in bits if bit), "openlibrary"))
    return [hit for hit in hits if hit["title"]]


def parse_geocode(body: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    try:
        lat = float(row["latitude"])
        lon = float(row["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    name = str(row.get("name") or "")
    country = str(row.get("country") or "")
    place = f"{name}, {country}".strip(", ") if country else name
    return {"place": place, "latitude": lat, "longitude": lon}


def weather_summary(code: int) -> str:
    if code == 0:
        return "Clear"
    if code in {1, 2, 3}:
        return "Cloudy"
    if code in {45, 48}:
        return "Fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "Rain"
    if 71 <= code <= 77:
        return "Snow"
    if code >= 95:
        return "Thunderstorm"
    return "Unknown"


def parse_forecast(body: bytes, place: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        payload = {}
    current = payload.get("current") if isinstance(payload, dict) else None
    if not isinstance(current, dict):
        current = {}
    try:
        code = int(current.get("weather_code"))
    except (TypeError, ValueError):
        code = -1
    temperature = current.get("temperature_2m")
    wind = current.get("wind_speed_10m")
    result: dict[str, Any] = {
        "found": True,
        "source": "open-meteo",
        "place": place["place"],
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "summary": weather_summary(code),
    }
    if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
        result["temperature_c"] = round(float(temperature), 1)
    if isinstance(wind, (int, float)) and not isinstance(wind, bool):
        result["wind_kmh"] = round(float(wind), 1)
    return result


def empty_weather() -> dict[str, Any]:
    return {"found": False, "source": "open-meteo", "place": "", "summary": ""}


def research_note(bundle: dict[str, Any]) -> str:
    lines = ["Research inputs for the next user message. Use them. Do not invent citations or sources."]
    for key in ("web", "reddit", "news", "books"):
        for hit in (bundle.get(key) or [])[:3]:
            if not isinstance(hit, dict):
                continue
            title = hit.get("title") or ""
            snippet = hit.get("snippet") or ""
            url = hit.get("url") or ""
            lines.append(f"{key}: {title} — {snippet} {url}".strip())
    weather = bundle.get("weather") or {}
    if isinstance(weather, dict) and weather.get("found"):
        lines.append(
            f"weather: {weather.get('place')} {weather.get('temperature_c')}°C, {weather.get('summary')}"
        )
    text = "\n".join(lines)
    if len(text) <= MAX_NOTE_CHARS:
        return text
    return text[: MAX_NOTE_CHARS - 3].rstrip() + "..."


def inject_research_notes(messages: list[dict[str, Any]], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Insert notes just before the last user turn so the system prefix stays stable."""
    note = {"role": "system", "content": research_note(bundle)}
    last_user = None
    for index, message in enumerate(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            last_user = index
    if last_user is None:
        return [*messages, note]
    return [*messages[:last_user], note, *messages[last_user:]]


def last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    text = part.get("text") or part.get("content")
                    if isinstance(text, str):
                        parts.append(text)
            return " ".join(part.strip() for part in parts if part.strip()).strip()
    return ""


def _cache_key(query: str, sources: tuple[str, ...]) -> str:
    return f"{_SPACE.sub(' ', query.strip()).casefold()}\n{','.join(sources)}"


class ResearchCache:
    def __init__(self, path: str, ttl_seconds: int) -> None:
        self.path = path
        self.ttl = ttl_seconds
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS research_cache (
                  q TEXT PRIMARY KEY,
                  body TEXT NOT NULL,
                  stored_at INTEGER NOT NULL
                )
                """
            )

    def get(self, key: str, *, now: float | None = None) -> dict[str, Any] | None:
        moment = int(now if now is not None else time.time())
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT body, stored_at FROM research_cache WHERE q = ?", (key,)
            ).fetchone()
        if row is None or moment - int(row[1]) > self.ttl:
            return None
        loaded = json.loads(row[0])
        return loaded if isinstance(loaded, dict) else None

    def put(self, key: str, body: dict[str, Any], *, now: float | None = None) -> None:
        moment = int(now if now is not None else time.time())
        with sqlite3.connect(self.path) as con:
            con.execute(
                """
                INSERT INTO research_cache (q, body, stored_at) VALUES (?, ?, ?)
                ON CONFLICT(q) DO UPDATE SET body = excluded.body, stored_at = excluded.stored_at
                """,
                (key, json.dumps(body), moment),
            )

    def clear(self) -> None:
        with sqlite3.connect(self.path) as con:
            con.execute("DELETE FROM research_cache")


class ResearchClient:
    def __init__(self, settings, *, fetch=None) -> None:
        self.settings = settings
        self.cache = ResearchCache(settings.research_cache_db, int(settings.research_cache_ttl_seconds))
        self.fetch = fetch or self._http_fetch
        self.outbound = 0
        self._client: httpx.AsyncClient | None = None
        agent = (getattr(settings, "research_user_agent", "") or "").strip()
        self.user_agent = agent or DEFAULT_USER_AGENT
        self.per_source = float(getattr(settings, "research_timeout_seconds", 8.0))

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, application/xml, application/atom+xml, */*",
        }

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=4.0, follow_redirects=False)
        return self._client

    async def _http_fetch(self, url: str) -> tuple[int, bytes]:
        client = self._ensure_client()
        current = url
        for _ in range(3):
            assert_allowed(current)
            response = await client.get(current, headers=self._headers())
            location = response.headers.get("location")
            if response.status_code in REDIRECTS and location:
                current = urllib.parse.urljoin(str(response.url), location)
                self.outbound += 1
                continue
            return response.status_code, response.content[:MAX_BODY_BYTES]
        return 310, b""

    async def _get(self, url: str) -> tuple[int, bytes]:
        assert_allowed(url)
        async with _GATE:
            self.outbound += 1
            try:
                status, body = await self.fetch(url)
            except CloudiatorError:
                raise
            except Exception:
                log.warning("research fetch failed host=%s", urllib.parse.urlsplit(url).hostname)
                return 0, b""
        if not isinstance(body, (bytes, bytearray)):
            return int(status), b""
        return int(status), bytes(body[:MAX_BODY_BYTES])

    async def lookup(
        self,
        query: str,
        sources: Any = None,
        *,
        truncate: bool = False,
    ) -> dict[str, Any]:
        text = clean_query(query, truncate=truncate)
        chosen = normalize_sources(sources)
        key = _cache_key(text, chosen)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        pieces = await asyncio.gather(*(self._run_source(name, text) for name in chosen))
        bundle: dict[str, Any] = {"query": text, "notes": []}
        for name, (payload, note) in zip(chosen, pieces, strict=True):
            bundle[name] = payload
            if note:
                bundle["notes"].append(note)
        if not bundle["notes"]:
            self.cache.put(key, bundle)
        log.info(
            "research sources=%s notes=%d outbound=%d",
            ",".join(chosen),
            len(bundle["notes"]),
            self.outbound,
        )
        return bundle

    async def _run_source(self, name: str, query: str) -> tuple[Any, dict[str, str] | None]:
        try:
            return await asyncio.wait_for(self._dispatch(name, query), timeout=self.per_source)
        except asyncio.TimeoutError:
            return self._blank(name), {"source": name, "message": f"{name} timed out."}
        except CloudiatorError as exc:
            return self._blank(name), {"source": name, "message": exc.message}
        except Exception:
            log.exception("research source %s failed", name)
            return self._blank(name), {"source": name, "message": f"{name} lookup failed."}

    @staticmethod
    def _blank(name: str) -> Any:
        if name == "weather":
            return empty_weather()
        return []

    async def _dispatch(self, name: str, query: str) -> tuple[Any, dict[str, str] | None]:
        if name == "web":
            return await self._web(query)
        if name == "reddit":
            return await self._reddit(query)
        if name == "news":
            return await self._news(query)
        if name == "weather":
            return await self._weather(query)
        if name == "books":
            return await self._books(query)
        return [], {"source": name, "message": "Unknown source."}

    async def _web(self, query: str) -> tuple[list[dict[str, str]], dict[str, str] | None]:
        quoted = urllib.parse.quote(query)
        ddg_url = (
            "https://api.duckduckgo.com/"
            f"?q={quoted}&format=json&no_html=1&skip_disambig=1&no_redirect=1"
        )
        wiki_url = (
            "https://en.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={quoted}&utf8=1&format=json&srlimit=2"
        )
        ddg_status, ddg_body = await self._get(ddg_url)
        wiki_status, wiki_body = await self._get(wiki_url)
        hits: list[dict[str, str]] = []
        notes: list[str] = []
        if ddg_status == 200:
            hits.extend(parse_duckduckgo(ddg_body))
        else:
            notes.append("DuckDuckGo")
        if wiki_status == 200:
            for row in parse_wikipedia_search(wiki_body)[:1]:
                title = urllib.parse.quote(row["title"].replace(" ", "_"), safe="")
                status, body = await self._get(
                    f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
                )
                summary = parse_wikipedia_summary(body) if status == 200 else None
                if summary:
                    hits.append(summary)
                elif row["snippet"]:
                    hits.append(
                        _hit(
                            row["title"],
                            f"https://en.wikipedia.org/wiki/{title}",
                            row["snippet"],
                            "wikipedia",
                        )
                    )
            for row in parse_wikipedia_search(wiki_body)[1:2]:
                title = urllib.parse.quote(row["title"].replace(" ", "_"), safe="")
                hits.append(
                    _hit(
                        row["title"],
                        f"https://en.wikipedia.org/wiki/{title}",
                        row["snippet"],
                        "wikipedia",
                    )
                )
        else:
            notes.append("Wikipedia")
        note = None
        if notes and not hits:
            note = {"source": "web", "message": f"{' and '.join(notes)} returned no inputs."}
        return hits[:4], note

    async def _reddit(self, query: str) -> tuple[list[dict[str, str]], dict[str, str] | None]:
        quoted = urllib.parse.quote(query)
        status, body = await self._get(
            "https://www.reddit.com/search.json"
            f"?q={quoted}&limit=5&sort=relevance&type=link&raw_json=1"
        )
        if status == 200:
            parsed = parse_reddit_json(body)
            if parsed is not None:
                return parsed, None
        status, body = await self._get(
            f"https://www.reddit.com/search.rss?q={quoted}&limit=5&sort=relevance"
        )
        if status != 200:
            code = "unreachable" if status == 0 else f"HTTP {status}"
            return [], {"source": "reddit", "message": f"Reddit returned {code}."}
        try:
            return parse_reddit_atom(body), None
        except ET.ParseError:
            return [], {"source": "reddit", "message": "Reddit feed could not be read."}

    async def _news(self, query: str) -> tuple[list[dict[str, str]], dict[str, str] | None]:
        quoted = urllib.parse.quote(query)
        google, hn = await asyncio.gather(
            self._get(
                "https://news.google.com/rss/search"
                f"?q={quoted}&hl=en-US&gl=US&ceid=US:en"
            ),
            self._get(f"https://hn.algolia.com/api/v1/search?query={quoted}&tags=story&hitsPerPage=3"),
        )
        hits: list[dict[str, str]] = []
        failed = []
        g_status, g_body = google
        if g_status == 200:
            try:
                hits.extend(parse_google_news(g_body))
            except ET.ParseError:
                failed.append("Google News")
        else:
            failed.append("Google News")
        h_status, h_body = hn
        if h_status == 200:
            hits.extend(parse_hacker_news(h_body))
        else:
            failed.append("Hacker News")
        note = None
        if failed and not hits:
            note = {"source": "news", "message": f"{' and '.join(failed)} returned no inputs."}
        return hits[:5], note

    async def _weather(self, query: str) -> tuple[dict[str, Any], dict[str, str] | None]:
        for candidate in place_candidates(query):
            status, body = await self._get(
                "https://geocoding-api.open-meteo.com/v1/search"
                f"?name={urllib.parse.quote(candidate)}&count=1&language=en&format=json"
            )
            if status != 200:
                code = "unreachable" if status == 0 else f"HTTP {status}"
                return empty_weather(), {"source": "weather", "message": f"Weather lookup returned {code}."}
            place = parse_geocode(body)
            if place is None:
                continue
            forecast_url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={place['latitude']:.4f}&longitude={place['longitude']:.4f}"
                "&current=temperature_2m,weather_code,wind_speed_10m&timezone=auto"
            )
            status, body = await self._get(forecast_url)
            if status != 200:
                return empty_weather(), {
                    "source": "weather",
                    "message": f"Weather lookup returned HTTP {status}.",
                }
            return parse_forecast(body, place), None
        missed = empty_weather()
        missed["summary"] = "No place matched this query."
        return missed, None

    async def _books(self, query: str) -> tuple[list[dict[str, str]], dict[str, str] | None]:
        status, body = await self._get(
            "https://openlibrary.org/search.json"
            f"?q={urllib.parse.quote(query)}&limit=5"
            "&fields=key,title,author_name,first_publish_year"
        )
        if status != 200:
            code = "unreachable" if status == 0 else f"HTTP {status}"
            return [], {"source": "books", "message": f"Open Library returned {code}."}
        return parse_open_library(body), None
