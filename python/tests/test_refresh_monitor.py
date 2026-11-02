import json
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import refresh_monitor as monitor

SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
CONVERSATIONS_DDL = """CREATE TABLE conversations (
    chat_id VARCHAR, arrived_at_utc TIMESTAMPTZ, region VARCHAR, language VARCHAR,
    channel VARCHAR, market VARCHAR, team VARCHAR, local_timezone VARCHAR,
    local_hour INTEGER, day_of_week INTEGER, event_type VARCHAR, concurrency INTEGER,
    first_response_minutes DOUBLE, handling_minutes DOUBLE, resolved INTEGER,
    csat DOUBLE, converted INTEGER, revenue DOUBLE, contact_reason VARCHAR, escalated INTEGER)"""


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "commerce_analytics.duckdb"
    con = duckdb.connect(str(path))
    con.execute("SET TimeZone='UTC'")
    con.execute(CONVERSATIONS_DDL)
    con.execute("""CREATE TABLE event_calendar (event_id VARCHAR, region VARCHAR, language VARCHAR,
        channel VARCHAR, event_type VARCHAR, start_utc TIMESTAMPTZ, end_utc TIMESTAMPTZ)""")
    con.execute("""INSERT INTO conversations VALUES
        ('c1','2026-01-01 12:00:00+00','AMER','en','live_chat','US','Payments','UTC',12,3,'none',2,5,10,1,4.5,1,20,'billing',0),
        ('c2','2026-01-01 13:00:00+00','EMEA','fr','web','FR','Core Support','UTC',13,3,'none',1,7,8,0,NULL,0,0,'refund',1)""")
    con.execute((SQL_DIR / "analytics.sql").read_text(encoding="utf-8"))
    con.execute((SQL_DIR / "reconciliation.sql").read_text(encoding="utf-8"))
    con.close()
    return path


def test_inspect_reads_the_real_views(database):
    info = monitor.inspect_database(database)
    assert info["conversations"] == 2
    assert info["reconciliation_checks"] == 8
    assert info["failed_checks"] == []
    assert info["latest_arrived_at_utc"].startswith("2026-01-01T13:00")
    assert info["latest_arrived_at_utc"].endswith("+00:00")


def test_missing_database_reports_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Analytics database not found"):
        monitor.inspect_database(tmp_path / "absent.duckdb")


def test_healthy_run_records_a_success_timestamp(database):
    state = monitor.build_state(monitor.inspect_database(database), profile="smoke", run_id="42")
    assert state["healthy"] is True
    assert state["last_successful_refresh_utc"] == state["checked_at_utc"]
    assert state["carried_previous_success"] is False


def test_failed_reconciliation_is_never_recorded_as_success(database):
    con = duckdb.connect(str(database))
    con.execute("CREATE TABLE broken AS SELECT 'revenue' AS metric, 'FAIL' AS status")
    con.close()
    info = {"conversations": 5, "latest_arrived_at_utc": "2026-01-01T00:00:00+00:00",
            "reconciliation_checks": 2, "failed_checks": ["revenue"]}
    state = monitor.build_state(info, profile="full", run_id="7",
                                previous={"last_successful_refresh_utc": "2026-01-01T02:17:00+00:00"})
    assert state["healthy"] is False
    assert state["last_successful_refresh_utc"] == "2026-01-01T02:17:00+00:00"
    assert state["carried_previous_success"] is True


@pytest.mark.parametrize("info,expected", [
    ({"conversations": 0, "latest_arrived_at_utc": None, "reconciliation_checks": 8, "failed_checks": []}, False),
    ({"conversations": 3, "latest_arrived_at_utc": "x", "reconciliation_checks": 0, "failed_checks": []}, False),
    ({"conversations": 3, "latest_arrived_at_utc": "x", "reconciliation_checks": 8, "failed_checks": ["escalations"]}, False),
    ({"conversations": 3, "latest_arrived_at_utc": "x", "reconciliation_checks": 8, "failed_checks": []}, True)])
def test_healthy_requires_every_signal(info, expected):
    assert monitor.build_state(info, profile="smoke", run_id="1")["healthy"] is expected


def test_markdown_shows_numbers_and_failures():
    state = monitor.build_state({"conversations": 420, "latest_arrived_at_utc": "2026-11-01T00:00:00+00:00",
                                 "reconciliation_checks": 8, "failed_checks": ["handling_minutes"]},
                                profile="full", run_id="9")
    text = monitor.markdown(state)
    assert "`full`" in text and "`420`" in text and "`FAIL`" in text
    assert "`handling_minutes`" in text


def test_main_writes_state_and_summary(database, tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    state_path = tmp_path / "state" / "refresh_state.json"
    assert monitor.main(["--database", str(database), "--state", str(state_path), "--profile", "smoke"]) == 0
    recorded = json.loads(state_path.read_text(encoding="utf-8"))
    assert recorded["healthy"] is True
    assert recorded["last_successful_refresh_utc"] == recorded["checked_at_utc"]
    assert "Analytics refresh" in summary.read_text(encoding="utf-8")
    assert json.loads(capsys.readouterr().out)["profile"] == "smoke"


def test_main_keeps_the_previous_success_after_a_failure(database, tmp_path, monkeypatch):
    state_path = tmp_path / "refresh_state.json"
    state_path.write_text(json.dumps({"last_successful_refresh_utc": "2026-01-01T00:00:00+00:00"}), encoding="utf-8")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert monitor.main(["--database", str(tmp_path / "gone.duckdb"), "--state", str(state_path)]) == 1
    recorded = json.loads(state_path.read_text(encoding="utf-8"))
    assert recorded["healthy"] is False
    assert recorded["last_successful_refresh_utc"] == "2026-01-01T00:00:00+00:00"


def test_main_survives_a_corrupt_state_file(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "refresh_state.json"
    state_path.write_text("{not json", encoding="utf-8")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert monitor.main(["--database", str(tmp_path / "gone.duckdb"), "--state", str(state_path)]) == 1
    assert json.loads(state_path.read_text(encoding="utf-8"))["last_successful_refresh_utc"] is None


def test_main_exits_one_when_reconciliation_fails(tmp_path, monkeypatch):
    database = tmp_path / "commerce_analytics.duckdb"
    con = duckdb.connect(str(database))
    con.execute("SET TimeZone='UTC'")
    con.execute(CONVERSATIONS_DDL)
    con.execute("""INSERT INTO conversations VALUES
        ('c1','2026-01-01 12:00:00+00','AMER','en','live_chat','US','Payments','UTC',12,3,'none',2,5,10,1,4.5,1,20,'billing',0)""")
    con.execute("CREATE TABLE data_reconciliation AS SELECT 'revenue' AS metric, 'FAIL' AS status")
    con.close()
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    state_path = tmp_path / "refresh_state.json"
    assert monitor.main(["--database", str(database), "--state", str(state_path)]) == 1
    assert json.loads(state_path.read_text(encoding="utf-8"))["failed_checks"] == ["revenue"]
