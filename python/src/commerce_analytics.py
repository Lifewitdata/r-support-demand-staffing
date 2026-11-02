from pathlib import Path
import argparse, json
import numpy as np, pandas as pd, duckdb
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
ROOT=Path(__file__).resolve().parents[1]; RAW=ROOT/'data'/'raw'; OUT=ROOT/'outputs'
REGIONS={'AMER':['en','es','pt'],'EMEA':['en','fr','de'],'APAC':['en','hi','ja']}
def generate_data(seed=19062026, days=210, chats_per_day=190):
    rng=np.random.default_rng(seed); n=days*chats_per_day
    ts=pd.Timestamp('2026-01-05',tz='UTC')+pd.to_timedelta(rng.integers(0,days*1440,n),unit='m')
    region=rng.choice(list(REGIONS),n,p=[.42,.33,.25]); language=np.array([rng.choice(REGIONS[x]) for x in region])
    channel=rng.choice(['live_chat','in_app','web'],n,p=[.48,.32,.20]); market=np.array([rng.choice({'AMER':['US','CA','BR'],'EMEA':['UK','FR','DE'],'APAC':['IN','JP','AU']}[x]) for x in region])
    team=rng.choice(['Core Support','Payments','Retention'],n,p=[.45,.35,.20]); hour=pd.DatetimeIndex(ts).hour; dow=pd.DatetimeIndex(ts).dayofweek
    event=rng.choice(['none','campaign','holiday','product_launch','incident'],n,p=[.83,.07,.045,.035,.02])
    base=np.select([team=='Payments',team=='Retention'],[13.5,11.5],default=9.0)
    handle=np.clip(rng.lognormal(np.log(base),.34)*np.where(event=='incident',1.25,1),2,65)
    pressure=np.where((hour>=14)&(hour<=20),1.22,1)*np.where(dow>=5,.88,1)*pd.Series(event).map({'none':1,'campaign':1.32,'holiday':1.18,'product_launch':1.42,'incident':1.55}).to_numpy()
    response=np.clip(rng.gamma(2.1,2.2,n)*pressure,.15,75); resolved=rng.binomial(1,np.clip(.91-.003*handle-.002*response,.35,.96))
    csat=np.clip(np.rint(rng.normal(np.where(resolved==1,4.35-.012*response,2.8),.7)),1,5)
    converted=rng.binomial(1,np.clip(.12+.07*(team=='Retention')-.002*response+.0005*(csat-3),.01,.32)); revenue=np.where(converted,rng.lognormal(np.log(68),.55),0)
    tz=np.select([region=='AMER',region=='EMEA'],['America/New_York','Europe/London'],default='Asia/Kolkata')
    local_hour=np.empty(n,dtype=int)
    for zone in np.unique(tz):
        mask=tz==zone; local_hour[mask]=pd.DatetimeIndex(ts[mask]).tz_convert(zone).hour
    return pd.DataFrame({'chat_id':[f'CHAT-{i:08d}' for i in range(1,n+1)],'arrived_at_utc':ts,'region':region,'language':language,'channel':channel,'market':market,'team':team,'local_timezone':tz,'local_hour':local_hour,'day_of_week':dow,'event_type':event,'concurrency':rng.integers(1,5,n),'first_response_minutes':np.round(response,2),'handling_minutes':np.round(handle,2),'resolved':resolved,'csat':csat,'converted':converted,'revenue':np.round(revenue,2),'contact_reason':rng.choice(['billing','account_access','product_help','delivery','cancellation'],n),'escalated':rng.binomial(1,np.clip(.07+.002*handle+.001*response,.02,.35))})
def _with_local_hour(df):
    out=df.copy()
    out['arrived_at_utc']=pd.to_datetime(out['arrived_at_utc'],utc=True,errors='coerce')
    local_hour=np.full(len(out),-1,dtype=int)
    for zone in out['local_timezone'].dropna().unique():
        mask=out['local_timezone'].eq(zone).to_numpy()
        try:
            local_hour[mask]=pd.DatetimeIndex(out.loc[mask,'arrived_at_utc']).tz_convert(zone).hour
        except Exception as exc:
            raise ValueError(f'Invalid IANA timezone {zone!r}: {exc}') from exc
    out['local_hour']=local_hour
    return out

def load_input_csv(path):
    """Load an approved chat-level CSV and normalize timestamps/local hours."""
    df=pd.read_csv(path)
    if 'arrived_at_utc' not in df:
        raise ValueError('Input CSV must include arrived_at_utc')
    if 'local_timezone' not in df:
        raise ValueError('Input CSV must include local_timezone')
    return _with_local_hour(df)

def validate_chats(df):
    required=['chat_id','arrived_at_utc','region','language','channel','market','team','local_timezone',
              'event_type','concurrency','first_response_minutes','handling_minutes','resolved','csat',
              'converted','revenue','contact_reason','escalated']
    missing=[c for c in required if c not in df]
    if missing:
        raise ValueError('Missing columns: '+str(missing))
    checks=[]
    def record(name,failed,detail):
        checks.append({'check':name,'status':'PASS' if failed==0 else 'FAIL',
                       'failed_rows':int(failed),'details':detail})
    record('unique_chat_id',df.chat_id.isna().sum()+df.chat_id.duplicated().sum(),'chat_id must be unique and non-null')
    dims=['region','language','channel','market','team','local_timezone','event_type','contact_reason']
    record('required_dimensions',df[dims].isna().any(axis=1).sum(),'Required dimensions must be populated')
    valid_language=df.apply(lambda r: r['language'] in REGIONS.get(r['region'],[]),axis=1)
    record('region_language',(~valid_language).sum(),'Language must be supported by the selected region')
    timestamps=pd.to_datetime(df.arrived_at_utc,utc=True,errors='coerce')
    record('valid_utc_timestamp',timestamps.isna().sum(),'arrived_at_utc must be parseable as UTC')
    numeric=['concurrency','first_response_minutes','handling_minutes','resolved','csat','converted','revenue','escalated']
    numeric_values=df[numeric].apply(pd.to_numeric,errors='coerce')
    record('numeric_metrics',numeric_values.isna().sum().sum(),'Operational and commercial measures must be numeric')
    finite=np.isfinite(numeric_values.fillna(0).to_numpy(dtype=float)).all(axis=1)
    record('finite_metrics',(~finite).sum(),'Metrics must be finite numbers')
    nonnegative=['concurrency','first_response_minutes','handling_minutes','revenue']
    record('nonnegative_metrics',(numeric_values[nonnegative]<0).any(axis=1).sum(),'Durations, concurrency and revenue cannot be negative')
    record('binary_outcomes',(~numeric_values[['resolved','converted','escalated']].isin([0,1])).any(axis=1).sum(),'resolved, converted and escalated must be 0 or 1')
    csat_bad=numeric_values.csat.notna() & ~numeric_values.csat.between(1,5)
    record('csat_range',csat_bad.sum(),'CSAT must be null or between 1 and 5')
    allowed_events={'none','campaign','holiday','product_launch','incident'}
    record('event_type',(~df.event_type.isin(allowed_events)).sum(),'event_type must use the documented categories')
    record('known_region',(~df.region.isin(REGIONS)).sum(),'Unknown region code')
    invalid_timezone=0
    for zone in df.local_timezone.dropna().unique():
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(str(zone))
        except Exception:
            invalid_timezone+=int(df.local_timezone.eq(zone).sum())
    record('valid_timezone',invalid_timezone,'local_timezone must be a valid IANA timezone')
    failed=sum(x['failed_rows'] for x in checks if x['status']=='FAIL')
    report=pd.DataFrame(checks)
    if failed:
        failed_names=', '.join(x['check'] for x in checks if x['status']=='FAIL')
        raise ValueError(f'Chat data validation failed: {failed_names}')
    return report

def load_event_calendar(path):
    events=pd.read_csv(path)
    required=['event_id','region','language','channel','event_type','start_utc','end_utc']
    missing=set(required)-set(events.columns)
    if missing: raise ValueError(f'Event calendar missing columns: {sorted(missing)}')
    events['start_utc']=pd.to_datetime(events.start_utc,utc=True,errors='coerce')
    events['end_utc']=pd.to_datetime(events.end_utc,utc=True,errors='coerce')
    if events[['start_utc','end_utc']].isna().any().any(): raise ValueError('Event start/end must be valid UTC timestamps')
    if (events.end_utc<=events.start_utc).any(): raise ValueError('Event end_utc must be after start_utc')
    allowed={'campaign','holiday','product_launch','incident'}
    if not events.event_type.isin(allowed).all(): raise ValueError('Unsupported event_type in event calendar')
    return events

def apply_event_calendar(hourly, events):
    out=hourly.copy()
    for col in ['event_rate','campaign_rate','holiday_rate','launch_rate','incident_rate']:
        if col not in out: out[col]=0.0
    if events is None or events.empty: return out
    out['hour_utc']=pd.to_datetime(out.hour_utc,utc=True)
    for _,event in events.iterrows():
        mask=(out.hour_utc>=event.start_utc)&(out.hour_utc<event.end_utc)
        for dim in ['region','language','channel']:
            if str(event[dim]) not in ('*','ALL','all'): mask &= out[dim].astype(str).eq(str(event[dim]))
        if not mask.any(): continue
        out.loc[mask,'event_rate']=1.0
        col={'campaign':'campaign_rate','holiday':'holiday_rate','product_launch':'launch_rate','incident':'incident_rate'}[event.event_type]
        out.loc[mask,col]=1.0
    return out

def build_forecast(hourly):
    preds=[]; scores=[]
    for keys,g in hourly.groupby(['region','language','channel']):
        for col in ['event_rate','campaign_rate','holiday_rate','launch_rate','incident_rate']:
            if col not in g: g[col]=0.0
        g=g.sort_values('hour_utc').copy(); full=pd.date_range(g.hour_utc.min(),g.hour_utc.max(),freq='h'); g=g.set_index('hour_utc').reindex(full).rename_axis('hour_utc').reset_index(); g['region']=keys[0]; g['language']=keys[1]; g['channel']=keys[2]; g['chats']=g.chats.fillna(0); g['event_rate']=g.event_rate.fillna(0); g['campaign_rate']=g.campaign_rate.fillna(0); g['holiday_rate']=g.holiday_rate.fillna(0); g['launch_rate']=g.launch_rate.fillna(0); g['incident_rate']=g.incident_rate.fillna(0); g['hour']=g.hour_utc.dt.hour; g['dow']=g.hour_utc.dt.dayofweek
        g['lag24']=g.chats.shift(24); g['lag168']=g.chats.shift(168); g['roll24']=g.chats.shift(1).rolling(24,min_periods=6).mean(); g=g.dropna().reset_index(drop=True)
        if len(g)<72: continue
        cut=max(24,int(len(g)*.8)); tr=g.iloc[:cut]; te=g.iloc[cut:]; features=['hour','dow','lag24','lag168','roll24','event_rate','campaign_rate','holiday_rate','launch_rate','incident_rate']
        if len(tr)>=100:
            model=RandomForestRegressor(n_estimators=100,max_depth=9,min_samples_leaf=3,random_state=42,n_jobs=-1); model.fit(tr[features],tr.chats); p=np.maximum(0,model.predict(te[features])); name='random_forest'
        else: p=np.maximum(0,te.lag168.fillna(te.lag24).to_numpy()); name='seasonal_naive'
        y=te.chats.to_numpy(); scores.append({'region':keys[0],'language':keys[1],'channel':keys[2],'model':name,'holdout_hours':len(te),'mae':mean_absolute_error(y,p),'rmse':mean_squared_error(y,p)**.5,'wape':np.abs(y-p).sum()/max(y.sum(),1)})
        preds.append(pd.DataFrame({'hour_utc':te.hour_utc,'region':keys[0],'language':keys[1],'channel':keys[2],'actual_chats':y,'predicted_chats':np.round(p,2),'model':name}))
    return (pd.concat(preds,ignore_index=True) if preds else pd.DataFrame(),pd.DataFrame(scores))
def build_future_forecast(hourly, events=None, horizon_hours=168):
    if horizon_hours<1: raise ValueError('horizon_hours must be positive')
    event_cols=['event_rate','campaign_rate','holiday_rate','launch_rate','incident_rate']
    features=['hour','dow','lag24','lag168','roll24']+event_cols
    results=[]
    for keys,g in hourly.groupby(['region','language','channel']):
        g=g.sort_values('hour_utc').copy()
        for col in event_cols:
            if col not in g: g[col]=0.0
        full=pd.date_range(pd.to_datetime(g.hour_utc,utc=True).min(),pd.to_datetime(g.hour_utc,utc=True).max(),freq='h')
        g=g.set_index('hour_utc').reindex(full).rename_axis('hour_utc').reset_index()
        g['chats']=g.chats.fillna(0)
        for col in event_cols: g[col]=g[col].fillna(0)
        g['hour']=g.hour_utc.dt.hour; g['dow']=g.hour_utc.dt.dayofweek
        g['lag24']=g.chats.shift(24); g['lag168']=g.chats.shift(168)
        g['roll24']=g.chats.shift(1).rolling(24,min_periods=6).mean()
        train=g.dropna(subset=['lag24','lag168','roll24'])
        model=None; model_name='seasonal_naive'
        if len(train)>=100:
            model=RandomForestRegressor(n_estimators=100,max_depth=9,min_samples_leaf=3,random_state=42,n_jobs=-1)
            model.fit(train[features],train.chats); model_name='random_forest'
        history=list(g.chats.astype(float)); last=g.hour_utc.max()
        future=pd.DataFrame({'hour_utc':pd.date_range(last+pd.Timedelta(hours=1),periods=horizon_hours,freq='h'),
                             'region':keys[0],'language':keys[1],'channel':keys[2]})
        for col in event_cols: future[col]=0.0
        future=apply_event_calendar(future,events)
        for _,row in future.iterrows():
            lag24=history[-24] if len(history)>=24 else float(np.mean(history))
            lag168=history[-168] if len(history)>=168 else lag24
            roll24=float(np.mean(history[-24:]))
            x=pd.DataFrame([{'hour':row.hour_utc.hour,'dow':row.hour_utc.dayofweek,'lag24':lag24,
                             'lag168':lag168,'roll24':roll24,
                             'event_rate':row.event_rate,'campaign_rate':row.campaign_rate,
                             'holiday_rate':row.holiday_rate,'launch_rate':row.launch_rate,
                             'incident_rate':row.incident_rate}])
            value=max(0.0,float(model.predict(x[features])[0])) if model is not None else max(0.0,float(lag168))
            history.append(value)
            results.append({'hour_utc':row.hour_utc,'region':keys[0],'language':keys[1],
                            'channel':keys[2],'predicted_chats':round(value,2),'model':model_name,
                            'campaign_rate':row.campaign_rate,'holiday_rate':row.holiday_rate,
                            'launch_rate':row.launch_rate,'incident_rate':row.incident_rate})
    return pd.DataFrame(results)

def run_pipeline(days=210,chats_per_day=190,input_path=None,events_path=None):
    RAW.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
    df=load_input_csv(input_path) if input_path else generate_data(days=days,chats_per_day=chats_per_day)
    df=_with_local_hour(df); dq=validate_chats(df)
    df.to_csv(RAW/'conversations.csv',index=False); dq.to_csv(OUT/'data_quality.csv',index=False)
    db=OUT/'commerce_analytics.duckdb'; con=duckdb.connect(str(db)); con.register('incoming',df); con.execute('CREATE OR REPLACE TABLE conversations AS SELECT * FROM incoming'); con.execute((ROOT/'sql'/'analytics.sql').read_text())
    events=load_event_calendar(events_path) if events_path else pd.DataFrame({'event_id':pd.Series(dtype='str'),'region':pd.Series(dtype='str'),'language':pd.Series(dtype='str'),'channel':pd.Series(dtype='str'),'event_type':pd.Series(dtype='str'),'start_utc':pd.Series(dtype='datetime64[ns, UTC]'),'end_utc':pd.Series(dtype='datetime64[ns, UTC]')})
    con.register('event_input',events); con.execute('CREATE OR REPLACE TABLE event_calendar AS SELECT * FROM event_input')
    con.execute((ROOT/'sql'/'reconciliation.sql').read_text())
    names=['hourly_commerce','staffing_coverage','service_commercial_risk','operational_anomalies','root_cause_decomposition','daily_kpis','weekly_kpis','monthly_kpis','data_reconciliation','event_calendar_impact']
    exports={}
    for name in names:
        x=con.execute('SELECT * FROM '+name).df(); x.to_csv(OUT/('tableau_'+name+'.csv'),index=False); exports[name]=len(x)
    hourly=con.execute('SELECT * FROM hourly_commerce').df(); hourly=apply_event_calendar(hourly,events); pred,score=build_forecast(hourly); pred.to_csv(OUT/'forecast_holdout.csv',index=False); score.to_csv(OUT/'forecast_scores.csv',index=False); future=build_future_forecast(hourly,events,168); future.to_csv(OUT/'forecast_next_7_days.csv',index=False)
    daily=con.execute('SELECT * FROM daily_kpis').df(); weekly=con.execute('SELECT * FROM weekly_kpis').df(); monthly=con.execute('SELECT * FROM monthly_kpis').df(); risks=con.execute('SELECT * FROM service_commercial_risk').df()
    daily.to_csv(OUT/'daily_tracker.csv',index=False)
    if not weekly.empty:
        w=weekly.sort_values('week_start').iloc[-1]
        brief=['# Weekly operations brief','',f"Week starting: {w['week_start']}",f"Chats: {int(w['chats']):,}",f"Conversion: {w['conversion_rate']:.1%}",f"Mean first response: {w['avg_first_response_minutes']:.1f} min",f"Converted revenue: ${w['converted_revenue']:,.0f}",'','## Priority risk alerts']
        for _,r in risks.head(5).iterrows(): brief.append(f"- {r['severity']} {r['region']}/{r['language']}/{r['channel']}: {r['risk_type']} — {r['suggested_action']}")
        (OUT/'weekly_brief.md').write_text('\\n'.join(brief))
    if not monthly.empty:
        m=monthly.sort_values('month_start').iloc[-1]
        summary=['# Monthly executive summary','',f"Month: {m['month_start']}",f"Chats: {int(m['chats']):,}",f"Resolution: {m['resolution_rate']:.1%}",f"Conversion: {m['conversion_rate']:.1%}",f"CSAT: {m['avg_csat']:.2f}",f"Converted revenue: ${m['converted_revenue']:,.0f}",'','## Decision focus','Review the three largest region-language-channel coverage gaps and assign a named operations owner before changing staffing.','Revenue is attributed converted revenue, not estimated revenue loss.']
        (OUT/'monthly_executive_summary.md').write_text('\\n'.join(summary))
    con.close(); manifest={'synthetic':input_path is None,'source_file':str(input_path) if input_path else None,'rows':len(df),'tables':exports,'database':str(db.relative_to(ROOT))}; (OUT/'run_manifest.json').write_text(json.dumps(manifest,indent=2)); return manifest
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--days',type=int,default=210); p.add_argument('--chats-per-day',type=int,default=190); p.add_argument('--input',help='Path to an approved chat-level CSV; if omitted, synthetic data is generated'); p.add_argument('--events',help='Optional event calendar CSV with UTC start/end'); a=p.parse_args(); print(json.dumps(run_pipeline(a.days,a.chats_per_day,a.input,a.events),indent=2))