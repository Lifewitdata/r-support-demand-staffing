"""Transparent employee-level shift allocation heuristic."""
import argparse
import math
from pathlib import Path
import pandas as pd


SHIFT_COLUMNS = [
    "employee_id", "region", "languages", "channels", "shift_start_utc",
    "shift_end_utc", "break_start_utc", "break_end_utc", "paid_hours", "weekly_bucket",
]


def _tokens(value):
    return {x.strip().lower() for x in str(value or "").split("|") if x.strip()}


def _hours(value, name, integer=False, positive=False):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Invalid {name}") from None
    if (isinstance(value, bool) or not math.isfinite(number) or number < 0
            or (positive and number == 0) or (integer and not number.is_integer())):
        raise ValueError(f"Invalid {name}")
    return int(number) if integer else number


def _blank(value):
    return pd.isna(value) or str(value).strip() == ""


def _window(employee, start_col, end_col):
    values = [employee.get(start_col, ""), employee.get(end_col, "")]
    blank = [_blank(value) for value in values]
    if all(blank):
        return None, None
    if any(blank):
        raise ValueError(f"Both {start_col} and {end_col} are required")
    try:
        start, end = [pd.to_datetime(value, utc=True, errors="raise") for value in values]
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Invalid {start_col}/{end_col}") from None
    if pd.isna(start) or pd.isna(end) or start >= end:
        raise ValueError(f"Invalid {start_col}/{end_col} window")
    return start, end


def _buckets(hours):
    days, weeks = {}, {}
    for hour in hours:
        day = str(hour.date())
        iso = hour.isocalendar()
        week = f"{iso.year}-{iso.week:02d}"
        days[day] = days.get(day, 0) + 1
        weeks[week] = weeks.get(week, 0) + 1
    return days, weeks


def optimise_shifts(demand, employees, shift_hours=8, break_after=4, break_hours=1,
                    max_daily_hours=8, max_weekly_hours=40, min_rest_hours=11):
    required = {"hour_utc", "region", "language", "channel", "required_agents"}
    staff_required = {"employee_id", "region", "languages", "channels"}
    if required - set(demand.columns):
        raise ValueError(f"Demand missing {sorted(required - set(demand.columns))}")
    if staff_required - set(employees.columns):
        raise ValueError(f"Roster missing {sorted(staff_required - set(employees.columns))}")
    shift_hours = _hours(shift_hours, "shift_hours", integer=True, positive=True)
    break_after = _hours(break_after, "break_after", integer=True)
    break_hours = _hours(break_hours, "break_hours", integer=True)
    if break_after + break_hours > shift_hours or break_hours >= shift_hours:
        raise ValueError("Break must fit within the shift and leave productive hours")
    max_daily_hours = _hours(max_daily_hours, "max_daily_hours")
    max_weekly_hours = _hours(max_weekly_hours, "max_weekly_hours")
    min_rest_hours = _hours(min_rest_hours, "min_rest_hours")

    d = demand.copy()
    try:
        d["hour_utc"] = pd.to_datetime(d.hour_utc, utc=True, errors="raise")
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Invalid hour_utc") from None
    if d.hour_utc.isna().any() or (d.hour_utc != d.hour_utc.dt.floor("h")).any():
        raise ValueError("hour_utc must contain valid UTC hour boundaries")
    d["required_agents"] = [
        _hours(value, "required_agents", integer=True) for value in d.required_agents
    ]
    grain = d[["hour_utc", "region", "language", "channel"]].copy()
    for col in ("region", "language", "channel"):
        if d[col].map(_blank).any():
            raise ValueError(f"Demand {col} must not be blank")
        grain[col] = d[col].astype(str).str.strip().str.lower()
    if grain.duplicated().any():
        raise ValueError("Duplicate hourly demand grain")
    d = d.sort_values("hour_utc", kind="stable").reset_index(drop=True)
    staff = employees.copy()
    if staff.employee_id.map(_blank).any():
        raise ValueError("Blank employee_id")
    staff["employee_id"] = staff.employee_id.astype(str).str.strip()
    if staff.employee_id.duplicated().any():
        raise ValueError("Duplicate employee_id")
    for col, default in [("max_daily_hours", max_daily_hours), ("max_weekly_hours", max_weekly_hours)]:
        if col not in staff:
            staff[col] = default
        staff[col] = [default if _blank(value) else _hours(value, col) for value in staff[col]]
    windows = {}
    for _, employee in staff.iterrows():
        windows[employee.employee_id] = (
            _window(employee, "available_from_utc", "available_to_utc"),
            _window(employee, "leave_start_utc", "leave_end_utc"),
        )
    staff = staff.fillna("")
    coverage = {i: 0 for i in d.index}
    shifts, used = [], {}
    starts = d.hour_utc.drop_duplicates()
    while True:
        best = None
        for _, e in staff.iterrows():
            eid = e.employee_id
            state = used.get(eid, {"days": {}, "weeks": {}, "last_end": None})
            langs, channels, regions = _tokens(e.languages), _tokens(e.channels), _tokens(e.region)
            (avail_from, avail_to), (leave_from, leave_to) = windows[eid]
            for start in starts:
                end = start + pd.Timedelta(shift_hours, unit="h")
                # Chronological selection keeps a single last_end sufficient for rest checks.
                if state["last_end"] is not None and start < state["last_end"] + pd.Timedelta(min_rest_hours, unit="h"):
                    continue
                if avail_from is not None and (start < avail_from or end > avail_to):
                    continue
                if leave_from is not None and start < leave_to and end > leave_from:
                    continue
                break_start = start + pd.Timedelta(break_after, unit="h")
                break_end = break_start + pd.Timedelta(break_hours, unit="h")
                productive_hours = [
                    hour for hour in pd.date_range(start, periods=shift_hours, freq="h")
                    if not break_start <= hour < break_end
                ]
                days, weeks = _buckets(productive_hours)
                if any(state["days"].get(day, 0) + count > min(e.max_daily_hours, max_daily_hours)
                       for day, count in days.items()):
                    continue
                if any(state["weeks"].get(week, 0) + count > min(e.max_weekly_hours, max_weekly_hours)
                       for week, count in weeks.items()):
                    continue
                mask = (d.hour_utc.isin(productive_hours)
                        & d.region.astype(str).str.strip().str.lower().isin(regions)
                        & d.language.astype(str).str.strip().str.lower().isin(langs)
                        & d.channel.astype(str).str.strip().str.lower().isin(channels))
                productive = []
                for _, segment in d[mask].groupby("hour_utc", sort=False):
                    index = max(segment.index, key=lambda i: d.at[i, "required_agents"] - coverage[i])
                    if d.at[index, "required_agents"] > coverage[index]:
                        productive.append(index)
                gain = len(productive)
                if not gain:
                    continue
                candidate = {"gain": gain, "employee": eid, "start": start, "end": end,
                             "productive": productive, "row": e, "days": days, "weeks": weeks}
                if best is None or (gain, eid, start) > (best["gain"], best["employee"], best["start"]):
                    best = candidate
        if best is None:
            break
        e, eid, start, end = best["row"], best["employee"], best["start"], best["end"]
        for i in best["productive"]:
            coverage[i] += 1
        state = used.setdefault(eid, {"days": {}, "weeks": {}, "last_end": None})
        for bucket in ("days", "weeks"):
            for key, count in best[bucket].items():
                state[bucket][key] = state[bucket].get(key, 0) + count
        state["last_end"] = end
        iso = start.isocalendar()
        shifts.append({"employee_id": eid, "region": e.region, "languages": e.languages, "channels": e.channels,
                       "shift_start_utc": start, "shift_end_utc": end,
                       "break_start_utc": start + pd.Timedelta(break_after, unit="h"),
                       "break_end_utc": start + pd.Timedelta(break_after + break_hours, unit="h"),
                       "paid_hours": shift_hours - break_hours,
                       "weekly_bucket": f"{iso.year}-{iso.week:02d}"})
    d["scheduled_agents"] = [coverage[i] for i in d.index]
    d["uncovered_agents"] = (d.required_agents - d.scheduled_agents).clip(lower=0)
    d["overstaffed_agents"] = (d.scheduled_agents - d.required_agents).clip(lower=0)
    return pd.DataFrame(shifts, columns=SHIFT_COLUMNS), d


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--demand", default="outputs/tableau_staffing_coverage.csv")
    p.add_argument("--employees", default="data/raw/employee_roster.csv")
    p.add_argument("--output", default="outputs/employee_shift_schedule.csv")
    a = p.parse_args()
    shifts, coverage = optimise_shifts(pd.read_csv(a.demand), pd.read_csv(a.employees))
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    shifts.to_csv(out, index=False)
    coverage.to_csv(out.with_name("employee_shift_coverage.csv"), index=False)
    print(f"Created {len(shifts)} shifts; {int(coverage.uncovered_agents.sum())} uncovered agent-hours.")


if __name__ == "__main__":
    main()
