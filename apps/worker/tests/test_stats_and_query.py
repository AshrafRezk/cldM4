"""Stats actions and the query route, including the scope check."""

from __future__ import annotations

from app import main
from tools.stats.handler import run as stats_run


async def test_describe_ttest_ols_monte_carlo_and_npv():
    described = await stats_run({"values": [1, 2, 3, 4]})
    assert described["count"] == 4
    assert described["mean"] == 2.5
    assert described["min"] == 1
    assert described["max"] == 4

    tested = await stats_run({"action": "ttest", "a": [1, 2, 3, 4], "b": [1, 2, 3, 4]})
    assert tested["pvalue"] > 0.9

    fitted = await stats_run({"action": "ols", "y": [1, 2, 3, 4], "x": [1, 2, 3, 4]})
    assert abs(fitted["rsquared"] - 1) < 1e-8
    assert abs(fitted["coefficients"][0]) < 1e-8
    assert abs(fitted["coefficients"][1] - 1) < 1e-8

    drawn = await stats_run({"action": "monte_carlo", "n": 2000, "mean": 0, "std": 1, "seed": 1})
    assert drawn["n"] == 2000
    assert abs(drawn["mean"]) < 0.1

    worth = await stats_run({"action": "npv", "rate": 0.1, "cashflows": [-100, 110]})
    assert abs(worth["npv"]) < 1e-9


async def test_query_route_groups_a_csv_and_chart_uses_those_numbers(make_client, install_key):
    _record, headers = install_key()
    async with make_client(headers) as client:
        queried = await client.post(
            "/v1/tools/query",
            json={
                "sql": "SELECT kind, SUM(n) AS total FROM data GROUP BY kind ORDER BY kind",
                "csv": "kind,n\napples,2\napples,3\npears,4\n",
            },
        )
        assert queried.status_code == 200, queried.text
        body = queried.json()
        assert body["rows"] == [["apples", "5"], ["pears", "4"]]
        chart = await client.post(
            "/v1/tools/chart",
            json={
                "kind": "bar",
                "title": "Fruit",
                "x": [row[0] for row in body["rows"]],
                "series": [{"name": "total", "values": [float(row[1]) for row in body["rows"]]}],
            },
        )
        assert chart.status_code == 200, chart.text
        path = chart.json()["url"].removeprefix(main.settings.public_base_url)
        png = await client.get(path)
    assert png.status_code == 200
    assert png.content.startswith(b"\x89PNG")


async def test_query_without_data_scope_is_403(make_client, install_key):
    _record, headers = install_key(capabilities=["chat"])
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/tools/query",
            json={"sql": "SELECT 1", "csv": "n\n1\n"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "scope_denied"


async def test_a_long_result_is_previewed_and_stored_as_parquet(make_client, install_key, monkeypatch):
    monkeypatch.setattr("app.sql_sandbox.PREVIEW_ROWS", 2)
    _record, headers = install_key()
    csv_text = "n\n" + "\n".join(str(index) for index in range(5)) + "\n"
    async with make_client(headers) as client:
        response = await client.post(
            "/v1/tools/query",
            json={"sql": "SELECT n FROM data ORDER BY n", "csv": csv_text},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["truncated"] is True
        assert len(body["rows"]) == 2
        assert body["row_count"] == 5
        path = body["url"].removeprefix(main.settings.public_base_url)
        parquet = await client.get(path)
    assert parquet.status_code == 200
    assert parquet.content.startswith(b"PAR1")
    assert parquet.headers["x-content-type-options"] == "nosniff"
