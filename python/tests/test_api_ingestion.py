import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import api_ingestion as api


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.delenv("SUPPORT_API_TOKEN", raising=False)
    monkeypatch.setattr(requests, "Session", Mock(side_effect=AssertionError("Unmocked API call")))


def response(payload, status=200):
    value = Mock(status_code=status)
    value.json.return_value = payload
    return value


def session(monkeypatch, pages):
    value = Mock()
    value.headers = {}
    value.get.side_effect = pages
    monkeypatch.setattr(requests, "Session", Mock(return_value=value))
    return value


def test_pagination_urljoin_and_query_preservation(monkeypatch):
    client = session(monkeypatch, [
        response({"data": [{"id": 1}], "next": "?cursor=a%2Fb&limit=7"}),
        response({"data": [{"id": 2}], "next": "../pages?cursor=end&limit=8"}),
        response({"data": [{"id": 3}], "next": None})])
    result = api.fetch_records("https://support.example/api/chats?filter=open&limit=4", "fake-token")
    assert result.id.tolist() == [1, 2, 3]
    calls = client.get.call_args_list
    assert calls[0].args[0] == "https://support.example/api/chats?filter=open&limit=4"
    assert calls[0].kwargs["params"] is None
    assert calls[1].args[0] == "https://support.example/api/chats?cursor=a%2Fb&limit=7"
    assert calls[2].args[0] == "https://support.example/pages?cursor=end&limit=8"
    assert all(c.kwargs["allow_redirects"] is False for c in calls)
    assert all(c.kwargs["params"] is None for c in calls[1:])
    assert client.headers["Authorization"] == "Bearer fake-token"
    client.close.assert_called_once()


def test_initial_limit_and_nested_payload(monkeypatch):
    client = session(monkeypatch, [response({"result": {"rows": [{"id": 1}]}, "links": {"next": None}})])
    result = api.fetch_records("https://support.example/chats?state=open", "fake", "result.rows", "links.next", page_size=12)
    assert result.id.tolist() == [1]
    assert client.get.call_args.kwargs["params"] == {"limit": 12}
    assert client.get.call_args.args[0].endswith("?state=open")


@pytest.mark.parametrize("url", ["http://support.example/chats", "https://user:pass@support.example/chats",
    "https://user@support.example/chats", "https://support.example@evil.example/chats", "//support.example/chats",
    "https://support.example/chats#fragment", "https://support.example:bad/chats", "", None,
    " https://support.example/chats", "https://support.example/\nchats", "https://support.example\\@evil.example"])
def test_invalid_base_url_never_sends_credentials(url):
    with pytest.raises(ValueError):
        api.fetch_records(url, "fake")
    requests.Session.assert_not_called()


@pytest.mark.parametrize("next_url", ["https://evil.example/chats", "http://support.example/chats",
    "//evil.example/chats", "https://support.example:444/chats", "https://support.example:0/chats", "https://u:p@support.example/chats",
    "https://u@support.example/chats", "https://support.example@evil.example/chats", "https://support.example/chats#fragment",
    "\nhttps://evil.example/chats", "https://support.example\\@evil.example/chats", 7, True, [], {}])
def test_untrusted_pagination_rejected_before_second_request(monkeypatch, next_url):
    client = session(monkeypatch, [response({"data": [{"id": 1}], "next": next_url})])
    with pytest.raises(ValueError):
        api.fetch_records("https://support.example/chats", "fake")
    client.get.assert_called_once()
    client.close.assert_called_once()


def test_equivalent_default_https_port_allowed(monkeypatch):
    client = session(monkeypatch, [response({"data": [{"id": 1}], "next": "https://SUPPORT.example:443/chats?page=2"}), response([{"id": 2}])])
    assert len(api.fetch_records("https://support.example/chats", "fake")) == 2
    assert client.get.call_count == 2


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirects_fail_without_following(monkeypatch, status):
    client = session(monkeypatch, [response({"data": [{"id": 1}]}, status)])
    with pytest.raises(ValueError, match="redirects"):
        api.fetch_records("https://support.example/chats", "fake")
    assert client.get.call_args.kwargs["allow_redirects"] is False
    client.get.assert_called_once()
    client.close.assert_called_once()


@pytest.mark.parametrize("kwargs", [{"page_size": 0}, {"page_size": True}, {"page_size": 1.5},
    {"max_pages": 0}, {"max_pages": True}, {"max_pages": "2"}, {"timeout": 0}, {"timeout": -1},
    {"timeout": float("nan")}, {"timeout": float("inf")}, {"timeout": True},
    {"records_path": ""}, {"records_path": "data..rows"}, {"next_path": None}])
def test_invalid_controls_before_request(kwargs):
    with pytest.raises(ValueError):
        api.fetch_records("https://support.example/chats", "fake", **kwargs)
    requests.Session.assert_not_called()


@pytest.mark.parametrize("payload", [None, "text", 2, {"other": []}, {"data": {}},
    {"data": [1]}, {"data": [None]}, [{"id": 1}, "bad"]])
def test_payload_must_be_list_of_dict_rows(monkeypatch, payload):
    client = session(monkeypatch, [response(payload)])
    with pytest.raises(ValueError):
        api.fetch_records("https://support.example/chats", "fake")
    client.close.assert_called_once()


def test_no_partial_extract_on_max_pages(monkeypatch):
    client = session(monkeypatch, [response({"data": [{"id": 1}], "next": "?page=2"})])
    with pytest.raises(RuntimeError, match="refusing partial extract"):
        api.fetch_records("https://support.example/chats", "fake", max_pages=1)
    client.close.assert_called_once()


def test_no_partial_extract_on_bad_later_payload(monkeypatch):
    client = session(monkeypatch, [response({"data": [{"id": 1}], "next": "?page=2"}), response({"data": ["bad"]})])
    with pytest.raises(ValueError):
        api.fetch_records("https://support.example/chats", "fake")
    client.close.assert_called_once()


def test_zero_records_rejected(monkeypatch):
    client = session(monkeypatch, [response([])])
    with pytest.raises(ValueError, match="zero records"):
        api.fetch_records("https://support.example/chats", "fake")
    client.close.assert_called_once()


@pytest.mark.parametrize("failure", ["network", "http", "json"])
def test_session_closed_on_errors(monkeypatch, failure):
    page = response({})
    if failure == "http":
        page.raise_for_status.side_effect = requests.HTTPError("mock error")
    if failure == "json":
        page.json.side_effect = ValueError("bad JSON")
    client = session(monkeypatch, [requests.Timeout("mock timeout") if failure == "network" else page])
    with pytest.raises((requests.RequestException, ValueError)):
        api.fetch_records("https://support.example/chats", "fake")
    client.close.assert_called_once()


def test_mapping_exports_only_explicit_fields():
    raw = pd.DataFrame({"id": ["c1"], "email": ["private@example.com"], "body": ["private"], "region_code": ["AMER"]})
    result = api.map_fields(raw, {"region": "region_code", "chat_id": "id"})
    assert result.columns.tolist() == ["region", "chat_id"]
    assert "private" not in result.to_csv(index=False)
    assert raw.columns.tolist() == ["id", "email", "body", "region_code"]


@pytest.mark.parametrize("mapping", [None, [], {}, {"chat_id": "missing"}, {"chat_id": "id", "other": "id"},
    {"chat_id": None}, {"chat_id": []}, {"chat_id": " "}, {"": "id"}, {1: "id"}])
def test_invalid_mapping(mapping):
    with pytest.raises(ValueError):
        api.map_fields(pd.DataFrame({"id": [1]}), mapping)


def test_duplicate_source_columns_rejected():
    with pytest.raises(ValueError, match="unique"):
        api.map_fields(pd.DataFrame([[1, 2]], columns=["id", "id"]), {"chat_id": "id"})


def configure_main(monkeypatch, tmp_path):
    mapping, output = tmp_path / "mapping.json", tmp_path / "approved.csv"
    mapping.write_text(json.dumps({"chat_id": "id", "arrived_at_utc": "timestamp", "local_timezone": "timezone"}))
    output.write_text("previous valid extract\n")
    monkeypatch.setenv("SUPPORT_API_URL", "https://support.example/chats")
    monkeypatch.setenv("SUPPORT_API_TOKEN", "test-only-placeholder")
    monkeypatch.setattr(sys, "argv", ["api_ingestion.py", "--mapping", str(mapping), "--output", str(output)])
    monkeypatch.setattr(api, "fetch_records", Mock(return_value=pd.DataFrame({
        "id": ["c1"], "timestamp": ["2026-01-01T12:00:00Z"], "timezone": ["UTC"], "email": ["private@example.com"]})))
    return output


def test_main_normalizes_validates_then_atomically_replaces(monkeypatch, tmp_path):
    output = configure_main(monkeypatch, tmp_path)
    events = []
    def normalize(frame):
        events.append("normalize")
        assert "email" not in frame.columns
        result = frame.copy()
        result["arrived_at_utc"] = pd.to_datetime(result["arrived_at_utc"], utc=True)
        result["local_hour"] = 12
        return result
    def validate(frame):
        events.append("validate")
        assert frame.local_hour.tolist() == [12]
        assert output.read_text() == "previous valid extract\n"
    monkeypatch.setitem(sys.modules, "commerce_analytics", SimpleNamespace(_with_local_hour=normalize, validate_chats=validate))
    api.main()
    assert events == ["normalize", "validate"]
    result = pd.read_csv(output)
    assert result.chat_id.tolist() == ["c1"]
    assert result.local_hour.tolist() == [12]
    assert "private@example.com" not in output.read_text()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("stage", ["normalize", "validate", "write", "replace"])
def test_main_failure_preserves_last_extract_and_cleans_temp(monkeypatch, tmp_path, stage):
    output = configure_main(monkeypatch, tmp_path)
    normalize = Mock(side_effect=ValueError("normalization failed")) if stage == "normalize" else lambda frame: frame
    validate = Mock(side_effect=ValueError("validation failed")) if stage == "validate" else Mock()
    monkeypatch.setitem(sys.modules, "commerce_analytics", SimpleNamespace(_with_local_hour=normalize, validate_chats=validate))
    if stage == "write":
        monkeypatch.setattr(pd.DataFrame, "to_csv", Mock(side_effect=OSError("write failed")))
    if stage == "replace":
        monkeypatch.setattr(Path, "replace", Mock(side_effect=OSError("replace failed")))
    with pytest.raises((ValueError, OSError)):
        api.main()
    assert output.read_text() == "previous valid extract\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_main_with_real_canonical_validation(monkeypatch, tmp_path):
    from commerce_analytics import generate_data
    raw = generate_data(days=1, chats_per_day=2)
    mapping = {column: column for column in raw.columns if column not in {"local_hour", "day_of_week"}}
    raw["private_email"] = "private@example.com"
    mapping_path, output = tmp_path / "mapping.json", tmp_path / "approved.csv"
    mapping_path.write_text(json.dumps(mapping))
    output.write_text("previous valid extract\n")
    monkeypatch.setenv("SUPPORT_API_URL", "https://support.example/chats")
    monkeypatch.setenv("SUPPORT_API_TOKEN", "test-only-placeholder")
    monkeypatch.setattr(sys, "argv", ["api_ingestion.py", "--mapping", str(mapping_path), "--output", str(output)])
    monkeypatch.setattr(api, "fetch_records", Mock(return_value=raw))
    api.main()
    exported = pd.read_csv(output)
    assert len(exported) == 2 and "local_hour" in exported
    assert "private_email" not in exported
    valid_output = output.read_bytes()
    invalid = raw.copy()
    invalid.loc[0, "first_response_minutes"] = -1
    monkeypatch.setattr(api, "fetch_records", Mock(return_value=invalid))
    with pytest.raises(ValueError, match="validation failed"):
        api.main()
    assert output.read_bytes() == valid_output


def test_invalid_nested_next_payload_rejected(monkeypatch):
    client = session(monkeypatch, [response({"data": [{"id": 1}], "links": "invalid"})])
    with pytest.raises(ValueError, match="pagination payload"):
        api.fetch_records("https://support.example/chats", "fake", next_path="links.next")
    client.close.assert_called_once()


def test_main_missing_credentials():
    # Parse succeeds, but no requests or file reads occur without configured credentials.
    old = sys.argv
    try:
        sys.argv = ["api_ingestion.py", "--mapping", "unused.json"]
        with pytest.raises(SystemExit, match="SUPPORT_API"):
            api.main()
    finally:
        sys.argv = old
    requests.Session.assert_not_called()
