import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pandas as pd
import pytest
from commerce_analytics import generate_data,load_input_csv,validate_chats,build_forecast,build_future_forecast,run_pipeline

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

@pytest.mark.parametrize('column,diagnostic', [('region', 'missing_region'), ('language', 'missing_language')])
def test_missing_region_or_language_rejected(column, diagnostic):
    df=generate_data(days=2,chats_per_day=10)
    df.loc[0,column]=None
    with pytest.raises(ValueError,match=diagnostic):
        validate_chats(df)

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
    assert pred.hour_utc.min()>ix[224] and pred.hour_utc.max()==ix.max()

def test_future_forecast_is_after_history():
    ix=pd.date_range('2026-01-01',periods=240,freq='h',tz='UTC')
    df=pd.DataFrame({'hour_utc':ix,'region':'AMER','language':'en','channel':'live_chat','chats':[20+i%24 for i in range(240)]})
    future=build_future_forecast(df,horizon_hours=48)
    assert len(future)==48
    assert future.hour_utc.min()==ix.max()+pd.Timedelta(1, unit="h")
    assert future.predicted_chats.ge(0).all()


def test_unsurveyed_csat_is_accepted():
    df=generate_data(days=2,chats_per_day=10)
    df.loc[0,'csat']=float('nan')
    assert validate_chats(df).status.eq('PASS').all()


@pytest.mark.parametrize('column,value,diagnostic', [
    ('csat','not numeric','numeric_metrics'),
    ('csat',float('inf'),'finite_metrics'),
    ('concurrency',0,'positive_concurrency'),
    ('concurrency',1.5,'positive_concurrency'),
    ('team','  ','required_dimensions'),
    ('chat_id','  ','unique_chat_id'),
    ('handling_minutes',-1,'nonnegative_metrics'),
    ('resolved',2,'binary_outcomes'),
    ('arrived_at_utc','invalid','valid_utc_timestamp'),
    ('local_timezone','Not/A_Zone','valid_timezone'),
])
def test_invalid_metrics_rejected(column,value,diagnostic):
    df=generate_data(days=2,chats_per_day=10)
    df[column]=df[column].astype(object)
    df.loc[0,column]=value
    with pytest.raises(ValueError,match=diagnostic):
        validate_chats(df)


def test_unconverted_revenue_rejected():
    df=generate_data(days=1,chats_per_day=10)
    df.loc[0,['converted','revenue']]=[0,10]
    with pytest.raises(ValueError,match='revenue_attribution'):
        validate_chats(df)


@pytest.mark.parametrize('days,chats',[(0,10),(1,0),(-1,10),(1,1.5)])
def test_invalid_generator_size(days,chats):
    with pytest.raises(ValueError,match='positive integers'):
        generate_data(days=days,chats_per_day=chats)


def test_empty_batch_rejected():
    with pytest.raises(ValueError,match='at least one row'):
        validate_chats(generate_data(days=1,chats_per_day=1).iloc[:0])


def test_forecast_preserves_hours_with_null_metrics():
    ix=pd.date_range('2026-01-01',periods=240,freq='h',tz='UTC')
    hourly=pd.DataFrame({'hour_utc':ix,'region':'AMER','language':'en','channel':'live_chat',
                         'chats':0,'avg_handling_minutes':float('nan')})
    predictions,scores=build_forecast(hourly)
    assert len(predictions)==15
    assert predictions.actual_chats.eq(0).all()
    assert predictions.hour_utc.max()==ix[-1]
    assert pd.isna(scores.iloc[0].wape)


def test_recursive_holdout_does_not_use_holdout_actuals():
    ix=pd.date_range('2026-01-01',periods=360,freq='h',tz='UTC')
    hourly=pd.DataFrame({'hour_utc':ix,'region':'AMER','language':'en','channel':'live_chat',
                         'chats':[10+i%24 for i in range(360)],'campaign_rate':0})
    original,_=build_forecast(hourly)
    changed=hourly.copy()
    changed.loc[changed.hour_utc>=original.hour_utc.min(),'chats']=10000
    changed['campaign_rate']=1
    updated,_=build_forecast(changed)
    pd.testing.assert_series_equal(original.predicted_chats,updated.predicted_chats)
    assert original.model.eq('random_forest').all()


def test_short_history_exports_readable_empty_forecasts():
    hourly=pd.DataFrame({'hour_utc':pd.date_range('2026-01-01',periods=4,freq='h',tz='UTC'),
                         'region':'AMER','language':'en','channel':'web','chats':[0,2,0,4]})
    predictions,scores=build_forecast(hourly)
    assert predictions.empty and scores.empty
    assert 'predicted_chats' in predictions and 'mae' in scores
    future=build_future_forecast(hourly,horizon_hours=10)
    assert len(future)==10 and future.predicted_chats.ge(0).all()


def test_pipeline_sql_and_csv_outputs(tmp_path):
    manifest=run_pipeline(days=1,chats_per_day=20,output_dir=tmp_path)
    assert manifest['rows']==20 and manifest['synthetic']
    assert len(manifest['tables'])==11
    reconciliation=pd.read_csv(tmp_path/'tableau_data_reconciliation.csv')
    assert len(reconciliation)==8 and reconciliation.status.eq('PASS').all()
    assert pd.read_csv(tmp_path/'tableau_team_kpis.csv').chats.sum()==20
    assert 'predicted_chats' in pd.read_csv(tmp_path/'forecast_holdout.csv')
    future=pd.read_csv(tmp_path/'forecast_next_7_days.csv')
    assert future.groupby(['region','language','channel']).size().eq(168).all()
    brief=(tmp_path/'weekly_brief.md').read_text(encoding='utf-8')
    assert 'Chats: 20' in brief and '\\n' not in brief
    assert 'Chats: 20' in (tmp_path/'monthly_executive_summary.md').read_text(encoding='utf-8')


def test_failed_input_preserves_previous_exports(tmp_path):
    source=tmp_path/'input.csv'
    df=generate_data(days=1,chats_per_day=2)
    df.loc[0,'language']=None
    df.to_csv(source,index=False)
    output=tmp_path/'output'
    output.mkdir()
    previous=output/'run_manifest.json'
    previous.write_text('previous valid output')
    with pytest.raises(ValueError):
        run_pipeline(input_path=source,output_dir=output)
    assert previous.read_text()=='previous valid output'
    assert not (output/'commerce_analytics.duckdb').exists()

