import sys
from pathlib import Path
from unittest.mock import Mock

import duckdb
import pandas as pd
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import groq_assistant as groq


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(requests, "post", Mock(side_effect=AssertionError("Unmocked API call")))


def test_analytics_facts_set_utc_before_querying(monkeypatch, tmp_path):
    database = tmp_path / "commerce_analytics.duckdb"
    database.touch()
    con = Mock()
    con.execute.return_value.df.return_value = pd.DataFrame({"severity": ["CRITICAL"]})
    connect = Mock(return_value=con)
    monkeypatch.setattr(duckdb, "connect", connect)
    intent, rows = groq.fetch_analytics("List critical service alerts", database)
    assert intent == "risks" and rows == [{"severity": "CRITICAL"}]
    assert connect.call_args.kwargs["read_only"] is True
    assert [call.args[0] for call in con.execute.call_args_list][0] == "SET TimeZone='UTC'"
    con.close.assert_called_once()


@pytest.mark.parametrize("zone,suffix", [("UTC", "+00:00"), ("Asia/Kolkata", "+05:30")])
def test_duckdb_renders_timestamps_in_the_session_zone(tmp_path, zone, suffix):
    database = tmp_path / "commerce_analytics.duckdb"
    setup = duckdb.connect(str(database))
    setup.execute("CREATE TABLE moments (moment TIMESTAMPTZ)")
    setup.execute("INSERT INTO moments VALUES ('2026-01-01 13:00:00+00')")
    setup.close()
    con = duckdb.connect(str(database), read_only=True)
    try:
        con.execute(f"SET TimeZone='{zone}'")
        frame = con.execute("SELECT max(moment) AS latest FROM moments").df()
    finally:
        con.close()
    assert str(frame["latest"].iloc[0]).endswith(suffix)
