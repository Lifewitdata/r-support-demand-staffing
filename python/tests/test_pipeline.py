import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pandas as pd
import pytest
from commerce_analytics import generate_data,load_input_csv,validate_chats,build_forecast,build_future_forecast

def test_generator_reproducible():
    pd.testing.assert_frame_equal(generate_data(seed=7,days=3,chats_per_day=20),generate_data(seed=7,days=3,chats_per_day=20))

def test_data_contract_and_local_time():
    df=generate_data(seed=9,days=3,chats_per_day=20)
    report=validate_chats(df)
    assert report.status.eq('PASS').all()
    assert df.chat_id.is_unique
    assert set(df.region)=={'AMER','EMEA','APAC'}
    row=df.iloc[0]
    expected=pd.Timestamp(row.arrived_at_utc).tz_convert(row.local_timezone).hour
    assert row.local_hour==expected

def test_missing_language_rejected():
    df=generate_data(days=2,chats_per_day=10); df.loc[0,'language']=None
    with pytest.raises(ValueError,match='required_dimensions|region_language'): validate_chats(df)

def test_invalid_region_language_pair_rejected():
    df=generate_data(days=2,chats_per_day=10); df.loc[0,'region']='APAC'; df.loc[0,'language']='fr'
    with pytest.raises(ValueError,match='region_language'): validate_chats(df)

def test_duplicate_id_rejected():
    df=generate_data(days=2,chats_per_day=10); df.loc[1,'chat_id']=df.loc[0,'chat_id']
    with pytest.raises(ValueError,match='unique_chat_id'): validate_chats(df)

def test_csv_input_contract_and_timezone(tmp_path):
    df=generate_data(seed=3,days=2,chats_per_day=10)
    source=tmp_path/'chats.csv'; df.drop(columns=['local_hour']).to_csv(source,index=False)
    loaded=load_input_csv(source)
    assert loaded.local_hour.between(0,23).all()
    assert validate_chats(loaded).status.eq('PASS').all()

def test_chronological_holdout_forecast():
    ix=pd.date_range('2026-01-01',periods=240,freq='h',tz='UTC')
    df=pd.DataFrame({'hour_utc':ix,'region':'AMER','language':'en','channel':'live_chat','chats':[20+i%24 for i in range(240)]})
    pred,score=build_forecast(df)
    assert not pred.empty and len(score)==1 and score.iloc[0].mae>=0
    assert pred.hour_utc.max()<ix.max()

def test_future_forecast_is_after_history():
    ix=pd.date_range('2026-01-01',periods=240,freq='h',tz='UTC')
    df=pd.DataFrame({'hour_utc':ix,'region':'AMER','language':'en','channel':'live_chat','chats':[20+i%24 for i in range(240)]})
    future=build_future_forecast(df,horizon_hours=48)
    assert len(future)==48
    assert future.hour_utc.min()==ix.max()+pd.Timedelta(hours=1)
    assert future.predicted_chats.ge(0).all()
