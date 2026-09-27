"""SQL over a caller-supplied table. No model, no filesystem."""

from __future__ import annotations

import asyncio
import io
from typing import Any

from app.errors import CloudiatorError
from app.sql_sandbox import HEAVY_INPUT_ROWS, execute_query, parse_table, prepare_sql

NAME = "sql_on_table"
CAPABILITY = "tools.data"
TIMEOUT_SECONDS = 30
GPU = False


async def run(arguments: dict[str, Any], *, artifacts, scheduler=None) -> dict[str, Any]:
    sql = arguments.get("sql")
    prepare_sql(sql if isinstance(sql, str) else "")
    table, columns, rows = parse_table(arguments)
    if len(rows) > HEAVY_INPUT_ROWS:
        if scheduler is None:
            raise CloudiatorError(
                429,
                "metal_busy",
                "A large query needs the CPU slot, and none is available.",
                error_type="rate_limit_error",
            )
        async with scheduler.cpu_heavy_slot():
            result = await asyncio.to_thread(execute_query, sql, table, columns, rows)
    else:
        result = await asyncio.to_thread(execute_query, sql, table, columns, rows)
    payload = {
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": result["row_count"],
        "truncated": result["truncated"],
    }
    if result["truncated"]:
        payload["url"] = _parquet_url(artifacts, result["columns"], result["raw_rows"])
        payload["capped"] = result["capped"]
    return payload


def _parquet_url(artifacts, columns: list[str], rows: list[tuple]) -> str:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({name: [row[index] for row in rows] for index, name in enumerate(columns)})
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    artifact_id = artifacts.save(buffer.getvalue(), ".parquet")
    return artifacts.sign(artifact_id)
