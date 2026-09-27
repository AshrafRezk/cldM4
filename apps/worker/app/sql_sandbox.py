"""DuckDB over caller-supplied rows only (PLAN.md §9 Family D).

The connection is locked with configuration before any user SQL runs. The
keyword prefilter is defence in depth: a statement the configuration would
also refuse is rejected here so the error is `sql_not_allowed`, not a
filesystem read.
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal
from typing import Any

from .errors import CloudiatorError, sql_not_allowed

PREVIEW_ROWS = 10_000
MAX_RESULT_ROWS = 100_000
MAX_INPUT_ROWS = 100_000
HEAVY_INPUT_ROWS = 10_000
DEFAULT_TABLE = "data"

_ALLOWED_LEADING = {"SELECT", "WITH", "DESCRIBE", "SUMMARIZE"}
_FORBIDDEN = {
    "ATTACH",
    "COPY",
    "CREATE",
    "DELETE",
    "DROP",
    "EXPORT",
    "INSERT",
    "INSTALL",
    "LOAD",
    "PRAGMA",
    "SET",
    "UPDATE",
}
_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def prepare_sql(sql: str) -> str:
    """Return the original SQL, or raise sql_not_allowed."""
    if not isinstance(sql, str) or not sql.strip():
        raise sql_not_allowed("SQL is required.")
    neutral = _neutralize(sql).strip()
    if neutral.endswith(";"):
        neutral = neutral[:-1].rstrip()
    if not neutral:
        raise sql_not_allowed("SQL is required.")
    if ";" in neutral:
        raise sql_not_allowed("Only one SQL statement is allowed.")
    leading = re.match(r"([A-Za-z_]+)", neutral)
    if leading is None or leading.group(1).upper() not in _ALLOWED_LEADING:
        raise sql_not_allowed("SQL must start with SELECT, WITH, DESCRIBE, or SUMMARIZE.")
    upper = neutral.upper()
    for token in sorted(_FORBIDDEN):
        if re.search(rf"\b{token}\b", upper):
            raise sql_not_allowed(f"SQL contains {token}, which is not allowed.")
    if re.search(r"\bREAD_[A-Z0-9_]*\s*\(", upper):
        raise sql_not_allowed("SQL reads an external file, which is not allowed.")
    return sql.strip()


def _neutralize(sql: str) -> str:
    """Blank comments and quoted literals so the prefilter sees the real tokens."""
    out: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end == -1:
                break
            out.append(" ")
            index = end + 2
            continue
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            if end == -1:
                break
            out.append(" ")
            index = end
            continue
        if sql[index] == "'":
            index = _skip_quoted(sql, index, "'")
            out.append("''")
            continue
        if sql[index] == '"':
            index = _skip_quoted(sql, index, '"')
            out.append('""')
            continue
        out.append(sql[index])
        index += 1
    return "".join(out)


def _skip_quoted(sql: str, index: int, quote: str) -> int:
    index += 1
    length = len(sql)
    pair = quote + quote
    while index < length:
        if sql.startswith(pair, index):
            index += 2
            continue
        if sql[index] == quote:
            return index + 1
        index += 1
    return index


def parse_table(arguments: dict[str, Any]) -> tuple[str, list[str], list[list[Any]]]:
    name = arguments.get("table") or DEFAULT_TABLE
    if not isinstance(name, str) or not _TABLE_NAME.match(name):
        raise CloudiatorError(400, "invalid_request_error", "table must be a plain identifier.", param="table")
    if name.upper() in _FORBIDDEN or name.upper() in _ALLOWED_LEADING:
        raise CloudiatorError(400, "invalid_request_error", "table name is reserved.", param="table")
    csv_text = arguments.get("csv")
    if isinstance(csv_text, str) and csv_text.strip():
        columns, rows = _parse_csv(csv_text)
    else:
        columns, rows = _parse_rows(arguments.get("columns"), arguments.get("rows"))
    if len(rows) > MAX_INPUT_ROWS:
        raise CloudiatorError(
            400,
            "invalid_request_error",
            f"At most {MAX_INPUT_ROWS} input rows.",
            param="rows",
        )
    return name, columns, rows


def _parse_csv(text: str) -> tuple[list[str], list[list[Any]]]:
    try:
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
    except (csv.Error, StopIteration) as exc:
        raise CloudiatorError(400, "invalid_request_error", "csv needs a header row.", param="csv") from exc
    columns = [_column_name(cell, index) for index, cell in enumerate(header)]
    if len(set(columns)) != len(columns):
        raise CloudiatorError(400, "invalid_request_error", "csv columns must be unique.", param="csv")
    rows: list[list[Any]] = []
    width = len(columns)
    for line in reader:
        if not line or (len(line) == 1 and line[0] == ""):
            continue
        if len(line) != width:
            raise CloudiatorError(400, "invalid_request_error", "csv rows must match the header.", param="csv")
        rows.append([_coerce(cell) for cell in line])
    if not rows:
        raise CloudiatorError(400, "invalid_request_error", "csv has no data rows.", param="csv")
    return columns, _homogenize(rows)


def _parse_rows(columns: Any, rows: Any) -> tuple[list[str], list[list[Any]]]:
    if not isinstance(columns, list) or not columns or not all(isinstance(item, str) for item in columns):
        raise CloudiatorError(
            400, "invalid_request_error", "Send csv, or columns plus rows.", param="columns"
        )
    names = [_column_name(item, index) for index, item in enumerate(columns)]
    if len(set(names)) != len(names):
        raise CloudiatorError(400, "invalid_request_error", "columns must be unique.", param="columns")
    if not isinstance(rows, list) or not rows:
        raise CloudiatorError(400, "invalid_request_error", "rows must be a non-empty array.", param="rows")
    width = len(names)
    parsed: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != width:
            raise CloudiatorError(400, "invalid_request_error", "each row must match columns.", param="rows")
        parsed.append([_coerce(cell) if isinstance(cell, str) else _number_or_text(cell) for cell in row])
    return names, _homogenize(parsed)


def _column_name(value: str, index: int) -> str:
    name = value.strip()
    if not _TABLE_NAME.match(name):
        raise CloudiatorError(
            400, "invalid_request_error", f"column {index + 1} is not a plain identifier.", param="columns"
        )
    return name


def _coerce(value: str) -> Any:
    text = value.strip()
    if text == "":
        return None
    try:
        if any(mark in text.lower() for mark in (".", "e")):
            return float(text)
        return int(text)
    except ValueError:
        return text


def _homogenize(rows: list[list[Any]]) -> list[list[Any]]:
    """One Arrow type per column. Mixed text and numbers become text."""
    if not rows:
        return rows
    width = len(rows[0])
    typed: list[list[Any]] = [[] for _ in range(width)]
    for index in range(width):
        cells = [row[index] for row in rows]
        if any(isinstance(cell, str) for cell in cells):
            typed[index] = [None if cell is None else str(cell) for cell in cells]
        elif any(isinstance(cell, float) for cell in cells):
            typed[index] = [None if cell is None else float(cell) for cell in cells]
        else:
            typed[index] = cells
    return [[typed[index][row_index] for index in range(width)] for row_index in range(len(rows))]


def _number_or_text(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _coerce(value)
    raise CloudiatorError(400, "invalid_request_error", "row values must be strings or numbers.", param="rows")


def lock_connection(connection) -> None:
    """Configuration lockdown. Nothing after this can turn the filesystem back on."""
    connection.execute("SET enable_external_access = false")
    connection.execute("SET disabled_filesystems = 'LocalFileSystem'")
    connection.execute("SET lock_configuration = true")


def execute_query(sql: str, table: str, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    checked = prepare_sql(sql)
    import duckdb
    import pyarrow as pa

    connection = duckdb.connect(database=":memory:")
    try:
        lock_connection(connection)
        connection.register(table, pa.table({name: [row[i] for row in rows] for i, name in enumerate(columns)}))
        cursor = connection.execute(checked)
        description = cursor.description or []
        names = [column[0] for column in description]
        fetched = cursor.fetchmany(MAX_RESULT_ROWS + 1)
    except CloudiatorError:
        raise
    except Exception as exc:  # noqa: BLE001 - duckdb raises several types
        message = str(exc).split("\n", 1)[0][:500]
        lowered = message.lower()
        if any(word in lowered for word in ("permission", "disabled", "external", "filesystem", "http")):
            raise sql_not_allowed("SQL was refused by the database lockdown.") from exc
        raise CloudiatorError(400, "invalid_request_error", message, param="sql") from exc
    finally:
        connection.close()

    capped = len(fetched) > MAX_RESULT_ROWS
    raw = fetched[:MAX_RESULT_ROWS]
    preview = raw[:PREVIEW_ROWS]
    return {
        "columns": names,
        "rows": [[_cell(value) for value in row] for row in preview],
        "raw_rows": raw,
        "row_count": len(raw),
        "truncated": len(raw) > PREVIEW_ROWS or capped,
        "capped": capped,
    }


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        if value.is_integer():
            return str(int(value))
        return format(value, ".12g")
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
    return str(value)
