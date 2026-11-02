import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import pandas as pd
import pytest
from workforce_optimizer import SHIFT_COLUMNS, optimise_shifts


def _demand(hours, required=1):
    return pd.DataFrame({"hour_utc": pd.to_datetime(hours, utc=True), "region": "APAC",
                         "language": "hi", "channel": "live_chat", "required_agents": required})


def _roster(**overrides):
    employee = {"employee_id": "A1", "region": "APAC", "languages": "en|hi",
                "channels": "live_chat|email"}
    employee.update(overrides)
    return pd.DataFrame([employee])


def _short_shifts(demand, roster, **options):
    params = {"shift_hours": 2, "break_after": 0, "break_hours": 0}
    params.update(options)
    return optimise_shifts(demand, roster, **params)

def test_employee_skill_shift_and_break_are_applied():
    hours=pd.date_range("2026-11-02T00:00:00Z",periods=8,freq="h")
    demand=pd.DataFrame({"hour_utc":hours,"region":"APAC","language":"hi","channel":"live_chat","required_agents":1})
    roster=pd.DataFrame([{"employee_id":"A1","region":"APAC","languages":"en|hi","channels":"live_chat","max_daily_hours":8,"max_weekly_hours":40}])
    shifts,coverage=optimise_shifts(demand,roster)
    assert len(shifts)==1
    assert shifts.iloc[0].paid_hours==7
    assert coverage.scheduled_agents.sum()==7
    assert coverage.uncovered_agents.sum()==1

def test_employee_without_language_skill_is_not_assigned():
    hours=pd.date_range("2026-11-02T00:00:00Z",periods=8,freq="h")
    demand=pd.DataFrame({"hour_utc":hours,"region":"APAC","language":"hi","channel":"live_chat","required_agents":1})
    roster=pd.DataFrame([{"employee_id":"A1","region":"APAC","languages":"en|fr","channels":"live_chat"}])
    shifts,coverage=optimise_shifts(demand,roster)
    assert shifts.empty
    assert coverage.uncovered_agents.sum()==8

def test_leave_blocks_overlapping_shift():
    hours=pd.date_range("2026-11-02T00:00:00Z",periods=8,freq="h")
    demand=pd.DataFrame({"hour_utc":hours,"region":"APAC","language":"hi","channel":"live_chat","required_agents":1})
    roster=pd.DataFrame([{"employee_id":"A1","region":"APAC","languages":"hi","channels":"live_chat",
                          "leave_start_utc":"2026-11-02T00:00:00Z","leave_end_utc":"2026-11-02T08:00:00Z"}])
    shifts,coverage=optimise_shifts(demand,roster)
    assert shifts.empty


def test_simultaneous_segments_conserve_employee_hours_and_choose_shortfall():
    hours = pd.date_range("2026-11-02", periods=2, freq="h", tz="UTC")
    demand = pd.concat([
        _demand(hours, 1),
        _demand(hours, 3).assign(language="en", channel="email"),
    ], ignore_index=True)
    shifts, coverage = _short_shifts(demand, _roster())
    assert len(shifts) == 1
    assert coverage.groupby("hour_utc").scheduled_agents.sum().eq(1).all()
    assert coverage.loc[coverage.channel == "email", "scheduled_agents"].eq(1).all()
    assert coverage.loc[coverage.channel == "live_chat", "scheduled_agents"].eq(0).all()
    assert coverage.scheduled_agents.sum() == shifts.paid_hours.sum()
    assert coverage.overstaffed_agents.sum() == 0


def test_candidates_score_actual_unit_gains_not_total_shortfall():
    demand = _demand(["2026-11-02T00:00Z", "2026-11-02T03:00Z", "2026-11-02T04:00Z"], [100, 1, 1])
    shifts, coverage = _short_shifts(demand, _roster(max_daily_hours=2))
    assert shifts.iloc[0].shift_start_utc == pd.Timestamp("2026-11-02T03:00Z")
    assert coverage.scheduled_agents.tolist() == [0, 1, 1]


def test_no_overcoverage_with_multiple_employees_and_zero_demand():
    demand = _demand(pd.date_range("2026-11-02", periods=2, freq="h", tz="UTC"), [1, 0])
    roster = pd.concat([_roster(employee_id=eid) for eid in ("A1", "A2", "A3")])
    shifts, coverage = _short_shifts(demand, roster)
    assert len(shifts) == 1
    assert coverage.scheduled_agents.tolist() == [1, 0]
    assert coverage.overstaffed_agents.sum() == 0


def test_multi_hour_break_excludes_entire_interval():
    demand = _demand(pd.date_range("2026-11-02", periods=8, freq="h", tz="UTC"))
    shifts, coverage = optimise_shifts(demand, _roster(), break_after=3, break_hours=2)
    assert len(shifts) == 1
    assert shifts.iloc[0].paid_hours == 6
    assert coverage.scheduled_agents.tolist() == [1, 1, 1, 0, 0, 1, 1, 1]
    assert shifts.iloc[0].break_end_utc - shifts.iloc[0].break_start_utc == pd.Timedelta(2, unit="h")


def test_zero_break_has_all_hours_productive():
    demand = _demand(pd.date_range("2026-11-02", periods=8, freq="h", tz="UTC"))
    shifts, coverage = optimise_shifts(demand, _roster(), break_hours=0)
    assert shifts.iloc[0].paid_hours == 8
    assert coverage.scheduled_agents.eq(1).all()


@pytest.mark.parametrize("cap_source", ["global", "employee"])
def test_midnight_daily_caps_charge_each_productive_day(cap_source):
    demand = _demand(pd.date_range("2026-11-02T22:00Z", periods=8, freq="h"))
    options = {"shift_hours": 4, "min_rest_hours": 0}
    roster = _roster()
    if cap_source == "global":
        options["max_daily_hours"] = 2
    else:
        roster["max_daily_hours"] = 2
    shifts, coverage = _short_shifts(demand, roster, **options)
    assert len(shifts) == 1
    assert shifts.iloc[0].shift_start_utc == pd.Timestamp("2026-11-02T22:00Z")
    assert shifts.iloc[0].paid_hours == 4
    assert coverage.groupby(coverage.hour_utc.dt.date).scheduled_agents.sum().tolist() == [2, 2]


@pytest.mark.parametrize("start", ["2026-11-08T22:00Z", "2027-01-03T22:00Z"])
@pytest.mark.parametrize("cap_source", ["global", "employee"])
def test_midnight_iso_week_caps_charge_each_productive_week(start, cap_source):
    demand = _demand(pd.date_range(start, periods=8, freq="h"))
    options = {"shift_hours": 4, "min_rest_hours": 0}
    roster = _roster()
    if cap_source == "global":
        options["max_weekly_hours"] = 2
    else:
        roster["max_weekly_hours"] = 2
    shifts, coverage = _short_shifts(demand, roster, **options)
    assert len(shifts) == 1
    assert shifts.iloc[0].shift_start_utc == pd.Timestamp(start)
    assert coverage.scheduled_agents.sum() == 4
    iso = coverage.hour_utc.dt.isocalendar()
    assert coverage.groupby([iso.year, iso.week]).scheduled_agents.sum().tolist() == [2, 2]


def test_caps_charge_productive_hours_even_without_matching_demand():
    demand = _demand(["2026-11-02T00:00Z"])
    shifts, coverage = _short_shifts(demand, _roster(max_daily_hours=1))
    assert shifts.empty
    assert coverage.scheduled_agents.sum() == 0


def test_break_hours_do_not_consume_daily_or_weekly_caps():
    demand = _demand(pd.date_range("2026-11-08T22:00Z", periods=4, freq="h"))
    shifts, coverage = optimise_shifts(demand, _roster(), shift_hours=4, break_after=1,
                                       break_hours=2, max_daily_hours=1, max_weekly_hours=1)
    assert len(shifts) == 1
    assert coverage.scheduled_agents.tolist() == [1, 0, 0, 1]


def test_availability_requires_entire_shift_inside_window():
    demand = _demand(pd.date_range("2026-11-02", periods=6, freq="h", tz="UTC"))
    shifts, coverage = _short_shifts(demand, _roster(
        available_from_utc="2026-11-02T01:00Z", available_to_utc="2026-11-02T03:00Z"))
    assert len(shifts) == 1
    assert shifts.iloc[0].shift_start_utc == pd.Timestamp("2026-11-02T01:00Z")
    assert coverage.scheduled_agents.tolist() == [0, 1, 1, 0, 0, 0]


@pytest.mark.parametrize("rest, expected", [(2, 2), (3, 1)])
def test_rest_between_shifts_includes_exact_boundary(rest, expected):
    demand = _demand(["2026-11-02T00:00Z", "2026-11-02T01:00Z", "2026-11-02T04:00Z"])
    shifts, coverage = _short_shifts(demand, _roster(), min_rest_hours=rest)
    assert len(shifts) == expected
    assert shifts.iloc[0].shift_start_utc == pd.Timestamp("2026-11-02T00:00Z")
    if expected == 2:
        assert shifts.iloc[1].shift_start_utc - shifts.iloc[0].shift_end_utc == pd.Timedelta(rest, unit="h")
    assert coverage.scheduled_agents.sum() == expected + 1


@pytest.mark.parametrize("blank", ["", "  ", None, float("nan")])
def test_blank_optional_caps_use_defaults(blank):
    demand = _demand(pd.date_range("2026-11-02", periods=2, freq="h", tz="UTC"))
    shifts, coverage = _short_shifts(demand, _roster(max_daily_hours=blank, max_weekly_hours=blank))
    assert len(shifts) == 1
    assert coverage.scheduled_agents.sum() == 2


@pytest.mark.parametrize("ids", [["A1", "A1"], ["A1", " A1 "], [""], ["  "], [None]])
def test_duplicate_or_blank_employee_ids_rejected(ids):
    roster = pd.concat([_roster(employee_id=eid) for eid in ids])
    with pytest.raises(ValueError, match="employee_id"):
        optimise_shifts(_demand(["2026-11-02T00:00Z"]), roster)


@pytest.mark.parametrize("required", [-1, 0.5, float("nan"), float("inf"), -float("inf"), "bad", "", None, True])
def test_invalid_required_agents_rejected(required):
    with pytest.raises(ValueError, match="required_agents"):
        optimise_shifts(_demand(["2026-11-02T00:00Z"], required), _roster())


def test_duplicate_hourly_demand_rejected_after_utc_and_segment_normalization():
    demand = _demand(["2026-11-02T00:00Z", "2026-11-02T01:00+01:00"])
    demand.loc[1, "region"] = " apac "
    with pytest.raises(ValueError, match="Duplicate hourly demand"):
        optimise_shifts(demand, _roster())


@pytest.mark.parametrize("hour", ["bad", "", None, "2026-11-02T00:30Z"])
def test_invalid_demand_hour_rejected(hour):
    demand = _demand(["2026-11-02T00:00Z"])
    demand["hour_utc"] = hour
    with pytest.raises(ValueError, match="hour_utc"):
        optimise_shifts(demand, _roster())


@pytest.mark.parametrize("columns", [
    ("available_from_utc", "available_to_utc"), ("leave_start_utc", "leave_end_utc"),
])
@pytest.mark.parametrize("start, end", [
    ("bad", "2026-11-02T08:00Z"), ("2026-11-02T00:00Z", "bad"),
    ("2026-11-02T00:00Z", ""), ("", "2026-11-02T08:00Z"),
    ("2026-11-02T08:00Z", "2026-11-02T00:00Z"),
    ("2026-11-02T00:00Z", "2026-11-02T00:00Z"),
    ("NaT", "2026-11-02T08:00Z"),
])
def test_invalid_employee_windows_rejected(columns, start, end):
    with pytest.raises(ValueError):
        optimise_shifts(_demand(["2026-11-02T00:00Z"]), _roster(**dict(zip(columns, (start, end)))))


@pytest.mark.parametrize("cap", ["max_daily_hours", "max_weekly_hours"])
@pytest.mark.parametrize("value", [-1, float("inf"), "bad", True])
def test_invalid_employee_caps_rejected(cap, value):
    with pytest.raises(ValueError, match=cap):
        optimise_shifts(_demand(["2026-11-02T00:00Z"]), _roster(**{cap: value}))


@pytest.mark.parametrize("options", [
    {"shift_hours": 0}, {"shift_hours": -1}, {"shift_hours": 1.5}, {"shift_hours": float("inf")},
    {"break_after": -1}, {"break_after": 1.5}, {"break_after": 9},
    {"break_hours": -1}, {"break_hours": 1.5}, {"break_hours": float("nan")},
    {"break_after": 0, "break_hours": 8}, {"break_after": 7, "break_hours": 2},
    {"max_daily_hours": -1}, {"max_daily_hours": float("nan")},
    {"max_weekly_hours": float("inf")}, {"max_weekly_hours": ""},
    {"min_rest_hours": -1}, {"min_rest_hours": float("nan")}, {"min_rest_hours": "bad"},
])
def test_invalid_shift_break_rest_and_global_caps_rejected(options):
    with pytest.raises(ValueError):
        optimise_shifts(_demand(["2026-11-02T00:00Z"]), _roster(), **options)


@pytest.mark.parametrize("empty_kind", ["demand", "roster", "zero", "skills"])
def test_empty_shifts_have_stable_csv_headers(empty_kind):
    demand = _demand(["2026-11-02T00:00Z"])
    roster = _roster()
    if empty_kind == "demand":
        demand = demand.iloc[:0]
    elif empty_kind == "roster":
        roster = roster.iloc[:0]
    elif empty_kind == "zero":
        demand["required_agents"] = 0
    else:
        roster["languages"] = "fr"
    shifts, coverage = optimise_shifts(demand, roster)
    assert shifts.empty
    assert list(shifts.columns) == SHIFT_COLUMNS
    assert shifts.to_csv(index=False).splitlines()[0] == ",".join(SHIFT_COLUMNS)
    assert {"scheduled_agents", "uncovered_agents", "overstaffed_agents"} <= set(coverage.columns)
