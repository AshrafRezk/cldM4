"""Every Family D reject string is refused. A grouped CSV query is not."""

from __future__ import annotations

import pytest

from app.errors import CloudiatorError
from app.sql_sandbox import execute_query, lock_connection, parse_table, prepare_sql

REJECTED = [
    "COPY (SELECT 1) TO '/tmp/x.csv';",
    "SELECT * FROM read_csv_auto('/etc/passwd');",
    "SELECT * FROM read_parquet('s3://bucket/key');",
    "ATTACH '/Users/me/Cloudiator/queue.db' AS q;",
    "INSTALL httpfs; LOAD httpfs;",
    "PRAGMA database_list;",
    "SELECT 1; DROP TABLE t;",
    "SELECT /* comment */ * FROM read_csv_auto('/etc/hosts');",
]


@pytest.mark.parametrize("sql", REJECTED)
def test_family_d_statements_are_refused(sql):
    with pytest.raises(CloudiatorError) as caught:
        prepare_sql(sql)
    assert caught.value.code == "sql_not_allowed"


def test_a_semicolon_inside_a_string_is_still_one_statement():
    prepare_sql("SELECT ';' AS mark FROM data")


def test_group_by_on_caller_csv():
    csv_text = "kind,n\napples,2\napples,3\npears,4\n"
    table, columns, rows = parse_table({"csv": csv_text})
    result = execute_query(
        "SELECT kind, SUM(n) AS total FROM data GROUP BY kind ORDER BY kind",
        table,
        columns,
        rows,
    )
    assert result["columns"] == ["kind", "total"]
    assert result["rows"] == [["apples", "5"], ["pears", "4"]]
    assert result["truncated"] is False


def test_more_than_the_preview_returns_the_cap_flag(monkeypatch):
    monkeypatch.setattr("app.sql_sandbox.PREVIEW_ROWS", 2)
    columns = ["n"]
    rows = [[index] for index in range(5)]
    result = execute_query("SELECT n FROM data ORDER BY n", "data", columns, rows)
    assert result["row_count"] == 5
    assert len(result["rows"]) == 2
    assert result["truncated"] is True


def test_locked_connection_cannot_read_a_local_file(tmp_path):
    import duckdb

    target = tmp_path / "secret.csv"
    target.write_text("h\nsecret\n", encoding="utf-8")
    connection = duckdb.connect(database=":memory:")
    try:
        lock_connection(connection)
        with pytest.raises(Exception):
            connection.execute(f"SELECT * FROM read_csv_auto('{target}')").fetchall()
    finally:
        connection.close()
