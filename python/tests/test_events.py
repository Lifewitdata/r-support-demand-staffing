import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import pandas as pd
from commerce_analytics import apply_event_calendar,build_future_forecast

def test_future_campaign_regressor_is_applied():
    ix=pd.date_range("2026-01-01",periods=240,freq="h",tz="UTC")
    history=pd.DataFrame({"hour_utc":ix,"region":"APAC","language":"hi","channel":"live_chat","chats":[10+i%8 for i in range(240)]})
    events=pd.DataFrame([{"event_id":"E1","region":"APAC","language":"hi","channel":"live_chat",
        "event_type":"campaign","start_utc":ix.max()+pd.Timedelta(2, unit="h"),
        "end_utc":ix.max()+pd.Timedelta(5, unit="h")}])
    future=build_future_forecast(history,events,168)
    assert len(future)==168
    assert future.campaign_rate.sum()==3
    assert future.hour_utc.min()==ix.max()+pd.Timedelta(1, unit="h")

def test_empty_event_calendar_does_not_change_hourly():
    hours=pd.DataFrame({"hour_utc":pd.date_range("2026-01-01",periods=2,freq="h",tz="UTC"),
                        "region":"APAC","language":"hi","channel":"live_chat","chats":[1,2]})
    empty=pd.DataFrame(columns=["event_id","region","language","channel","event_type","start_utc","end_utc"])
    result=apply_event_calendar(hours,empty)
    assert result.campaign_rate.sum()==0
