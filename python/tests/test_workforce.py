import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import pandas as pd
from workforce_optimizer import optimise_shifts

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
