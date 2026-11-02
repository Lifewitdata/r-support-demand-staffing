import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pandas as pd
import pytest
from commerce_analytics import generate_data,validate_chats,build_forecast

def test_generator_reproducible():
    pd.testing.assert_frame_equal(generate_data(seed=7,days=3,chats_per_day=20),generate_data(seed=7,days=3,chats_per_day=20))
def test_data_contract():
    df=generate_data(seed=9,days=3,chats_per_day=20); assert len(validate_chats(df))==5; assert df.chat_id.is_unique; assert set(df.region)=={'AMER','EMEA','APAC'}
def test_missing_language_rejected():
    df=generate_data(days=2,chats_per_day=10); df.loc[0,'language']=None
    with pytest.raises(ValueError,match='Missing operational dimensions'): validate_chats(df)
def test_duplicate_id_rejected():
    df=generate_data(days=2,chats_per_day=10); df.loc[1,'chat_id']=df.loc[0,'chat_id']
    with pytest.raises(ValueError,match='unique'): validate_chats(df)
def test_chronological_holdout_forecast():
    ix=pd.date_range('2026-01-01',periods=240,freq='h',tz='UTC')
    df=pd.DataFrame({'hour_utc':ix,'region':'AMER','language':'en','channel':'live_chat','chats':[20+i%24 for i in range(240)]})
    pred,score=build_forecast(df); assert not pred.empty and len(score)==1 and score.iloc[0].mae>=0
