"""The Neon client (PLAN.md §11).

The numbers in this file are the ones the plan argues for, so they are asserted
rather than trusted: pool 0/2, pre-ping on, 300s recycle, 3s connect, 5s
statement timeout, pooled endpoint.

Two behaviours matter more than the numbers:

* a socket that died during an idle suspend is replaced, not handed to the auth
  path — that is the common Neon failure, and a pre-ping is what catches it;
* a Neon outage costs no latency. Without the breaker every cache miss would
  wait out the connect timeout, and "Neon is never on the critical path" would
  quietly become "Neon adds three seconds to everything".
"""

from __future__ import annotations

import asyncio
import dataclasses

import asyncpg
import pytest

from app import db as db_module
from app.db import (
    BREAKER_FAILURES,
    STATE_DEGRADED,
    STATE_NOT_CONFIGURED,
    STATE_OK,
    STATE_UNKNOWN,
    DatabaseRejected,
    DatabaseUnavailable,
    Neon,
    normalize_dsn,
    pooled_endpoint,
)

DSN = "postgresql://user:pw@ep-x-pooler.eu-west-2.aws.neon.tech/neondb?sslmode=require"


class FakeTransaction:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        self.connection.transactions += 1
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False


class FakeConnection:
    def __init__(self, *, ping_error: BaseException | None = None) -> None:
        self.ping_error = ping_error
        self.statements: list[str] = []
        self.transactions = 0
        self.terminated = False

    async def fetchval(self, sql, *args, timeout=None):
        if self.ping_error is not None:
            raise self.ping_error
        self.statements.append(sql)
        return 1

    async def execute(self, sql, *args, timeout=None):
        self.statements.append(sql)

    async def fetchrow(self, sql, *args, timeout=None):
        self.statements.append(sql)
        return {"id": "row"}

    def transaction(self):
        return FakeTransaction(self)

    def terminate(self) -> None:
        self.terminated = True


class FakePool:
    def __init__(self, connections: list[FakeConnection]) -> None:
        self.connections = connections
        self.acquired: list[FakeConnection] = []
        self.released: list[FakeConnection] = []
        self.closed = False

    async def acquire(self, timeout=None):
        connection = self.connections[min(len(self.acquired), len(self.connections) - 1)]
        self.acquired.append(connection)
        return connection

    async def release(self, connection) -> None:
        self.released.append(connection)

    async def close(self) -> None:
        self.closed = True


def make_neon(connections: list[FakeConnection], **overrides) -> tuple[Neon, FakePool]:
    from app.config import get_settings

    settings = dataclasses.replace(get_settings(), database_url=DSN, **overrides)
    neon = Neon(settings)
    pool = FakePool(connections)
    neon._pool = pool
    return neon, pool


async def one(connection: FakeConnection):
    return "ok"


# ---- DSN handling --------------------------------------------------------


def test_the_dsn_keeps_sslmode_and_drops_what_asyncpg_would_forward():
    """asyncpg turns unknown query parameters into server settings, and Postgres
    then rejects them as unknown GUCs. Neon hands out `channel_binding`."""
    cleaned = normalize_dsn(f"{DSN}&channel_binding=require&options=-csearch_path%3Dx")

    assert "sslmode=require" in cleaned
    assert "channel_binding" not in cleaned
    assert cleaned.startswith("postgresql://user:pw@ep-x-pooler.eu-west-2.aws.neon.tech/neondb")


def test_a_dsn_without_a_query_is_untouched():
    plain = "postgresql://user:pw@host/neondb"

    assert normalize_dsn(plain) == plain


def test_the_pooled_endpoint_is_recognised():
    assert pooled_endpoint(DSN) is True
    assert pooled_endpoint("postgresql://u:p@ep-x.eu-west-2.aws.neon.tech/neondb") is False
    assert pooled_endpoint(None) is False


# ---- pool settings -------------------------------------------------------


async def test_the_pool_is_built_with_the_documented_numbers(monkeypatch):
    captured: dict = {}

    async def fake_create_pool(dsn, **kwargs):
        captured["dsn"] = dsn
        captured.update(kwargs)
        return FakePool([FakeConnection()])

    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)
    neon, _ = make_neon([FakeConnection()])
    neon._pool = None

    await neon._ensure_pool()

    assert captured["min_size"] == 0
    assert captured["max_size"] == 2
    assert captured["max_inactive_connection_lifetime"] == 300.0
    assert captured["timeout"] == 3.0
    assert captured["command_timeout"] == 5.0
    # The pooled endpoint is PgBouncer in transaction mode, where asyncpg's
    # implicit prepared statements break.
    assert captured["statement_cache_size"] == 0
    assert "channel_binding" not in captured["dsn"]


async def test_every_statement_runs_under_a_server_side_timeout():
    connection = FakeConnection()
    neon, _ = make_neon([connection])

    await neon.run(one)

    assert connection.transactions == 1
    assert "SET LOCAL statement_timeout = 5000" in connection.statements


async def test_a_background_flush_gets_its_own_longer_budget():
    connection = FakeConnection()
    neon, _ = make_neon([connection])

    await neon.run(one, statement_timeout_seconds=15.0)

    assert "SET LOCAL statement_timeout = 15000" in connection.statements


# ---- pre-ping ------------------------------------------------------------


async def test_a_socket_that_died_while_idle_is_replaced():
    dead = FakeConnection(ping_error=asyncpg.PostgresConnectionError("connection lost"))
    alive = FakeConnection()
    neon, pool = make_neon([dead, alive])

    assert await neon.run(one) == "ok"
    assert dead.terminated is True
    assert alive.terminated is False
    # Both connections were handed back, so the pool can discard the dead one.
    assert pool.released == [dead, alive]
    assert neon.state() == STATE_OK


async def test_a_closed_connection_is_an_outage_not_a_500():
    """asyncpg reports "connection is closed" as an InterfaceError, which does not
    inherit from PostgresError. Uncaught, an idle suspend becomes a 500."""

    async def closed(connection):
        raise asyncpg.InterfaceError("connection is closed")

    neon, _ = make_neon([FakeConnection()])

    with pytest.raises(DatabaseUnavailable):
        await neon.run(closed)

    assert neon.state() == STATE_DEGRADED


async def test_a_dead_socket_reported_as_an_interface_error_is_replaced():
    dead = FakeConnection(ping_error=asyncpg.InterfaceError("connection is closed"))
    neon, _ = make_neon([dead, FakeConnection()])

    assert await neon.run(one) == "ok"
    assert dead.terminated is True


async def test_two_dead_sockets_are_a_database_outage():
    connections = [
        FakeConnection(ping_error=asyncpg.PostgresConnectionError("lost")),
        FakeConnection(ping_error=asyncpg.PostgresConnectionError("lost")),
    ]
    neon, _ = make_neon(connections)

    with pytest.raises(DatabaseUnavailable):
        await neon.run(one)

    assert neon.state() == STATE_DEGRADED
    assert all(connection.terminated for connection in connections)


# ---- breaker -------------------------------------------------------------


async def test_the_breaker_opens_and_stops_costing_latency():
    async def boom(connection):
        raise asyncpg.PostgresConnectionError("neon is gone")

    neon, pool = make_neon([FakeConnection()])

    for _ in range(BREAKER_FAILURES):
        with pytest.raises(DatabaseUnavailable):
            await neon.run(boom)
    acquisitions = len(pool.acquired)

    with pytest.raises(DatabaseUnavailable, match="breaker is open"):
        await neon.run(boom)

    # Nothing was acquired, so nothing waited on the connect timeout.
    assert len(pool.acquired) == acquisitions


async def test_the_breaker_lets_one_request_through_after_the_cooldown():
    neon, _ = make_neon([FakeConnection()])
    neon._failures = BREAKER_FAILURES
    neon._breaker_open_until = asyncio.get_running_loop().time() - 0.1

    assert await neon.run(one) == "ok"
    assert neon.state() == STATE_OK


async def test_recovery_clears_the_degraded_state():
    async def boom(connection):
        raise OSError("connection refused")

    connection = FakeConnection()
    neon, _ = make_neon([connection])

    with pytest.raises(DatabaseUnavailable):
        await neon.run(boom)
    assert neon.state() == STATE_DEGRADED

    await neon.run(one)
    assert neon.state() == STATE_OK


# ---- refused statements --------------------------------------------------


async def test_a_row_neon_refuses_does_not_count_as_an_outage():
    """A foreign key violation means the row is wrong, not that Neon is down."""

    async def refuse(connection):
        raise asyncpg.ForeignKeyViolationError("key_id is not in api_keys")

    neon, _ = make_neon([FakeConnection()])

    with pytest.raises(DatabaseRejected):
        await neon.run(refuse)

    assert neon.state() == STATE_OK


# ---- configuration -------------------------------------------------------


async def test_an_unconfigured_client_never_pretends_to_work():
    from app.config import get_settings

    settings = dataclasses.replace(get_settings(), database_url=None)
    neon = Neon(settings)

    assert neon.configured is False
    assert neon.state() == STATE_NOT_CONFIGURED
    with pytest.raises(DatabaseUnavailable):
        await neon.run(one)


def test_a_configured_client_starts_out_unknown_rather_than_healthy():
    """`/v1/health` must not claim Neon is fine before anything has asked it."""
    neon, _ = make_neon([FakeConnection()])

    assert neon.state() == STATE_UNKNOWN


async def test_closing_releases_the_pool():
    neon, pool = make_neon([FakeConnection()])

    await neon.close()

    assert pool.closed is True
    assert neon._pool is None


def test_the_usage_insert_matches_the_documented_column_order():
    """The outbox builds positional rows; a reordered INSERT silently swaps them."""
    columns = db_module.INSERT_USAGE_EVENT.split("(", 1)[1].split(")", 1)[0]
    names = [name.strip() for name in columns.split(",")]

    assert names == [
        "key_id",
        "tenant_id",
        "ts",
        "request_id",
        "route",
        "model",
        "tool",
        "status",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "bytes_out",
        "job_id",
        "error_code",
    ]
    assert db_module.INSERT_USAGE_EVENT.count("$") == len(names)
