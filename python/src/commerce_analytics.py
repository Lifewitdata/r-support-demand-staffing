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
    return pd.DataFrame({'chat_id':[f'CHAT-{i:08d}' for i in range(1,n+1)],'arrived_at_utc':ts,'region':region,'language':language,'channel':channel,'market':market,'team':team,'local_timezone':tz,'local_hour':hour,'day_of_week':dow,'event_type':event,'concurrency':rng.integers(1,5,n),'first_response_minutes':np.round(response,2),'handling_minutes':np.round(handle,2),'resolved':resolved,'csat':csat,'converted':converted,'revenue':np.round(revenue,2),'contact_reason':rng.choice(['billing','account_access','product_help','delivery','cancellation'],n),'escalated':rng.binomial(1,np.clip(.07+.002*handle+.001*response,.02,.35))})
def validate_chats(df):
    required=['chat_id','arrived_at_utc','region','language','channel','market','team','local_timezone','first_response_minutes','handling_minutes','resolved','csat','converted','revenue']
    missing=[c for c in required if c not in df]
    if missing: raise ValueError('Missing columns: '+str(missing))
    if df.chat_id.isna().any() or df.chat_id.duplicated().any(): raise ValueError('chat_id must be unique and non-null')
    if df[['region','language','channel','market','team','local_timezone']].isna().any().any(): raise ValueError('Missing operational dimensions')
    if df[['arrived_at_utc','first_response_minutes','handling_minutes','resolved','converted','revenue']].isna().any().any(): raise ValueError('Missing required metric values')
    if not df.resolved.isin([0,1]).all() or not df.converted.isin([0,1]).all(): raise ValueError('Resolution and conversion must be binary')
    if not set(df.region).issubset(REGIONS): raise ValueError('Unknown region')
    if (df[['first_response_minutes','handling_minutes','revenue']]<0).any().any(): raise ValueError('Negative metric')
    if not df.csat.dropna().between(1,5).all(): raise ValueError('CSAT outside 1..5')
    return pd.DataFrame([{'check':x,'status':'PASS','failed_rows':0} for x in ['unique_chat_id','required_dimensions','region_language','nonnegative_metrics','csat_range']])
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
def run_pipeline(days=210,chats_per_day=190):
    RAW.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True); df=generate_data(days=days,chats_per_day=chats_per_day); dq=validate_chats(df)
    df.to_csv(RAW/'conversations.csv',index=False); dq.to_csv(OUT/'data_quality.csv',index=False)
    db=OUT/'commerce_analytics.duckdb'; con=duckdb.connect(str(db)); con.register('incoming',df); con.execute('CREATE OR REPLACE TABLE conversations AS SELECT * FROM incoming'); con.execute((ROOT/'sql'/'analytics.sql').read_text())
    names=['hourly_commerce','staffing_coverage','service_commercial_risk','operational_anomalies','root_cause_decomposition','daily_kpis','weekly_kpis','monthly_kpis']
    exports={}
    for name in names:
        x=con.execute('SELECT * FROM '+name).df(); x.to_csv(OUT/('tableau_'+name+'.csv'),index=False); exports[name]=len(x)
    hourly=con.execute('SELECT * FROM hourly_commerce').df(); pred,score=build_forecast(hourly); pred.to_csv(OUT/'forecast_holdout.csv',index=False); score.to_csv(OUT/'forecast_scores.csv',index=False)
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
    con.close(); manifest={'synthetic':True,'rows':len(df),'tables':exports,'database':str(db.relative_to(ROOT))}; (OUT/'run_manifest.json').write_text(json.dumps(manifest,indent=2)); return manifest
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--days',type=int,default=210); p.add_argument('--chats-per-day',type=int,default=190); a=p.parse_args(); print(json.dumps(run_pipeline(a.days,a.chats_per_day),indent=2))