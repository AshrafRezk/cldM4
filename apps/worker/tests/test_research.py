"""The research parameter calls fixed public APIs and returns those inputs."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import pytest

from app import main
from app.errors import CloudiatorError
from app.research import (
    ALLOWED_HOSTS,
    assert_allowed,
    cite_answer,
    parse_duckduckgo,
    parse_google_news,
    parse_open_library,
    parse_reddit_atom,
    parse_research_option,
    place_candidates,
    research_requested,
)


DDG = json.dumps(
    {
        "Heading": "Ada Lovelace",
        "Abstract": "English mathematician.",
        "AbstractURL": "https://en.wikipedia.org/wiki/Ada_Lovelace",
        "Answer": "",
        "RelatedTopics": [],
        "Results": [],
    }
).encode()
WIKI_SEARCH = json.dumps(
    {"query": {"search": [{"title": "Ada Lovelace", "snippet": "<span>Mathematician</span>"}]}}
).encode()
WIKI_SUMMARY = json.dumps(
    {
        "type": "standard",
        "title": "Ada Lovelace",
        "extract": "Ada Lovelace wrote notes on the Analytical Engine.",
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Ada_Lovelace"}},
    }
).encode()
REDDIT_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>State of Python</title>
    <link rel="alternate" href="https://www.reddit.com/r/Python/comments/abc/state"/>
    <category term="Python" label="r/Python"/>
    <content type="html">&lt;p&gt;Use uv.&lt;/p&gt;</content>
  </entry>
</feed>
"""
NEWS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>Cairo forecast</title><link>https://news.google.com/rss/articles/abc</link><source>Example</source></item>
</channel></rss>
"""
HN = json.dumps(
    {"hits": [{"title": "Cairo notes", "url": "https://example.com/cairo", "points": 3, "author": "ada"}]}
).encode()
GEO = json.dumps(
    {"results": [{"name": "Cairo", "country": "Egypt", "latitude": 30.06, "longitude": 31.25}]}
).encode()
FORECAST = json.dumps(
    {"current": {"temperature_2m": 29.4, "weather_code": 2, "wind_speed_10m": 11.0}}
).encode()
BOOKS = json.dumps(
    {
        "docs": [
            {
                "key": "/works/OL1W",
                "title": "Cairo",
                "author_name": ["Max Rodenbeck"],
                "first_publish_year": 1998,
            }
        ]
    }
).encode()


@pytest.fixture(autouse=True)
def _reset_research():
    main.research_client.cache.clear()
    main.research_client.outbound = 0
    yield
    main.research_client.cache.clear()
    main.research_client.outbound = 0


def _route(url: str) -> tuple[int, bytes]:
    host = urlsplit(url).hostname
    assert host in ALLOWED_HOSTS
    assert urlsplit(url).scheme == "https"
    if host == "api.duckduckgo.com":
        return 200, DDG
    if host == "en.wikipedia.org" and "/page/summary/" in url:
        return 200, WIKI_SUMMARY
    if host == "en.wikipedia.org":
        return 200, WIKI_SEARCH
    if host == "www.reddit.com" and "search.json" in url:
        return 403, b"blocked"
    if host == "www.reddit.com":
        return 200, REDDIT_ATOM
    if host == "news.google.com":
        return 200, NEWS
    if host == "hn.algolia.com":
        return 200, HN
    if host == "geocoding-api.open-meteo.com":
        if "name=Cairo" in url or "name=cairo" in url:
            return 200, GEO
        return 200, b"{}"
    if host == "api.open-meteo.com":
        return 200, FORECAST
    if host == "openlibrary.org":
        return 200, BOOKS
    return 404, b""


@pytest.fixture()
def fake_ollama(monkeypatch):
    async def installed_tags():
        return {"qwen3.5:9b", "nomic-embed-text"}

    async def chat(model, messages, *, options, tools=None, response_format=None):
        return {
            "model": model,
            "message": {"role": "assistant", "content": "hi"},
            "done_reason": "stop",
            "prompt_eval_count": 4,
            "eval_count": 1,
        }

    monkeypatch.setattr(main.ollama, "installed_tags", installed_tags)
    monkeypatch.setattr(main.ollama, "chat", chat)
    return chat


@pytest.fixture()
def recorded(monkeypatch):
    calls: list[str] = []

    async def fetch(url: str):
        calls.append(url)
        return _route(url)

    monkeypatch.setattr(main.research_client, "fetch", fetch)
    return calls


def test_research_flag_accepts_true_and_the_capitalised_alias():
    assert research_requested({"Research": True}) is True
    assert parse_research_option({"Research": True}).query is None
    assert parse_research_option({"research": {"q": "Cairo", "sources": ["weather"]}}).sources == (
        "weather",
    )
    assert research_requested({"research": False}) is False
    with pytest.raises(CloudiatorError):
        parse_research_option({"research": {"sources": ["google"]}})


def test_place_candidates_prefer_a_name_over_the_whole_sentence():
    assert place_candidates("what's the weather in Paris")[0] == "Paris"
    assert place_candidates("cairo weather")[0] == "cairo"


def test_allowlist_rejects_link_local_and_plaintext_http():
    with pytest.raises(CloudiatorError) as blocked:
        assert_allowed("http://169.254.169.254/latest/meta-data")
    assert blocked.value.code == "url_not_allowed"
    with pytest.raises(CloudiatorError):
        assert_allowed("https://evil.example/search")


def test_an_uncited_draft_gains_intext_markers_and_a_reference_list():
    refs = [
        {
            "n": 1,
            "title": "Cairo",
            "url": "https://openlibrary.org/works/OL1W",
            "snippet": "Max Rodenbeck wrote about the city.",
            "source": "openlibrary",
        }
    ]
    text = cite_answer("Cairo is warm.\n\nReferences\n[1] made up", refs)
    answer, _, bibliography = text.partition("\n\nReferences\n")
    assert answer == "Cairo is warm [1]."
    assert "made up" not in text
    assert "[1] Cairo. openlibrary. https://openlibrary.org/works/OL1W" in bibliography


def test_a_model_citation_is_kept_and_unknown_markers_are_removed():
    refs = [
        {
            "n": 1,
            "title": "Cairo",
            "url": "https://openlibrary.org/works/OL1W",
            "snippet": "A city.",
            "source": "openlibrary",
        }
    ]
    text = cite_answer("Rodenbeck describes the city [1] and not this [9].", refs)
    assert "describes the city [1]" in text
    assert "[9]" not in text
    assert text.count("References") == 1


def test_parsers_keep_titles_and_drop_markup():
    assert parse_duckduckgo(DDG)[0]["title"] == "Ada Lovelace"
    assert parse_reddit_atom(REDDIT_ATOM)[0]["snippet"].startswith("r/Python")
    assert "<" not in parse_reddit_atom(REDDIT_ATOM)[0]["snippet"]
    assert parse_google_news(NEWS)[0]["source"] == "google_news"
    assert parse_open_library(BOOKS)[0]["url"] == "https://openlibrary.org/works/OL1W"


async def test_weather_reads_the_place_out_of_the_sentence(recorded):
    bundle = await main.research_client.lookup("what's the weather in Cairo", ["weather"])
    assert bundle["weather"]["found"] is True
    assert bundle["weather"]["place"] == "Cairo, Egypt"
    assert bundle["weather"]["temperature_c"] == 29.4
    assert bundle["weather"]["summary"] == "Cloudy"
    assert {urlsplit(url).hostname for url in recorded} <= {
        "geocoding-api.open-meteo.com",
        "api.open-meteo.com",
    }


async def test_lookup_uses_only_allowlisted_hosts_and_caches(recorded):
    bundle = await main.research_client.lookup("http://127.0.0.1/secret cairo", None)
    assert bundle["query"].startswith("http://127.0.0.1/secret")
    assert bundle["web"][0]["source"] == "duckduckgo"
    assert bundle["reddit"][0]["title"] == "State of Python"
    assert bundle["news"][0]["source"] == "google_news"
    assert bundle["books"][0]["title"] == "Cairo"
    assert bundle["weather"]["found"] is False
    assert bundle["notes"] == []
    hosts = {urlsplit(url).hostname for url in recorded}
    assert hosts <= ALLOWED_HOSTS
    assert all(urlsplit(url).scheme == "https" for url in recorded)
    outbound = main.research_client.outbound
    again = await main.research_client.lookup("http://127.0.0.1/secret cairo", None)
    assert again["query"] == bundle["query"]
    assert main.research_client.outbound == outbound


async def test_a_failed_source_does_not_drop_the_others_or_get_cached(recorded):
    async def fetch(url: str):
        recorded.append(url)
        if "reddit" in urlsplit(url).hostname:
            return 403, b"no"
        return _route(url)

    main.research_client.fetch = fetch
    first = await main.research_client.lookup("partial cairo", ["web", "reddit"])
    assert first["web"]
    assert first["notes"][0]["source"] == "reddit"
    calls = len(recorded)
    await main.research_client.lookup("partial cairo", ["web", "reddit"])
    assert len(recorded) > calls


async def test_chat_research_returns_inputs_and_shows_them_to_the_model(
    make_client, cached_key, recorded, fake_ollama, monkeypatch
):
    seen: list[dict] = []
    tool_calls: list = []

    async def chat(model, messages, *, options, tools=None, response_format=None):
        seen.extend(messages)
        tool_calls.append(tools)
        return {
            "model": model,
            "message": {"role": "assistant", "content": "Cairo is warm."},
            "done_reason": "stop",
            "prompt_eval_count": 8,
            "eval_count": 2,
        }

    monkeypatch.setattr(main.ollama, "chat", chat)
    _, headers = cached_key
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen3.5:9b",
                "messages": [{"role": "user", "content": "books about Cairo"}],
                "max_tokens": 32,
                "research": {"sources": ["books"]},
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    answer = body["choices"][0]["message"]["content"]
    assert answer.startswith("Cairo is warm [1].")
    assert "\n\nReferences\n[1] Cairo. openlibrary." in answer
    assert body["research"]["references"][0]["n"] == 1
    assert body["research"]["references"][0]["url"] == "https://openlibrary.org/works/OL1W"
    assert body["research"]["books"][0]["title"] == "Cairo"
    assert response.headers["x-cloudiator-research"] == "1"
    assert tool_calls == [None]
    assert any("[1]" in (message.get("content") or "") for message in seen)
    assert any("Do not write a bibliography" in (message.get("content") or "") for message in seen)
    assert all(urlsplit(url).hostname == "openlibrary.org" for url in recorded)


async def test_research_without_the_scope_is_403_and_stays_offline(
    make_client, install_key, monkeypatch, fake_ollama
):
    async def fetch(url: str):
        raise AssertionError(url)

    monkeypatch.setattr(main.research_client, "fetch", fetch)
    _, headers = install_key(capabilities=["chat"])
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen3.5:9b",
                "messages": [{"role": "user", "content": "hi"}],
                "Research": True,
            },
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "scope_denied"


async def test_plain_chat_omits_research(make_client, cached_key, monkeypatch, fake_ollama):
    async def fetch(url: str):
        raise AssertionError(url)

    monkeypatch.setattr(main.research_client, "fetch", fetch)

    async def chat(model, messages, *, options, tools=None, response_format=None):
        return {
            "model": model,
            "message": {"role": "assistant", "content": "hi"},
            "done_reason": "stop",
            "prompt_eval_count": 4,
            "eval_count": 1,
        }

    monkeypatch.setattr(main.ollama, "chat", chat)
    _, headers = cached_key
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "qwen3.5:9b", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 200
    assert "research" not in response.json()


async def test_research_route_and_unknown_source(make_client, install_key, recorded):
    _, headers = install_key(capabilities=["tools.research"])
    async with make_client(headers) as client:
        ok = await client.post("/v1/tools/research", json={"q": "Ada Lovelace", "sources": ["web"]})
        bad = await client.post("/v1/tools/research", json={"q": "Ada", "sources": ["google"]})
        denied = await client.post(
            "/v1/tools/research",
            json={"q": "Ada"},
            headers={"Authorization": install_key(capabilities=["chat"])[1]["Authorization"]},
        )
    assert ok.status_code == 200, ok.text
    assert ok.json()["web"][0]["title"] == "Ada Lovelace"
    assert bad.status_code == 400
    assert denied.status_code == 403
