from pathlib import Path
import argparse
import json
import logging
from datetime import datetime, timezone

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
OUT = ROOT / 'outputs'
ONE_HOUR = pd.Timedelta(1, unit='h')
REGIONS = {'AMER': ['en', 'es', 'pt'], 'EMEA': ['en', 'fr', 'de'], 'APAC': ['en', 'hi', 'ja']}
CHAT_COLUMNS = ['chat_id', 'arrived_at_utc', 'region', 'language', 'channel', 'market', 'team',
                'local_timezone', 'event_type', 'concurrency', 'first_response_minutes',
                'handling_minutes', 'resolved', 'csat', 'converted', 'revenue', 'contact_reason', 'escalated']
METRICS = ['concurrency', 'first_response_minutes', 'handling_minutes', 'resolved', 'csat',
           'converted', 'revenue', 'escalated']
EVENT_COLUMNS = ['event_rate', 'campaign_rate', 'holiday_rate', 'launch_rate', 'incident_rate']
SEGMENTS = ['region', 'language', 'channel']
FORECAST_COLUMNS = ['hour_utc', *SEGMENTS, 'predicted_chats', 'model', *EVENT_COLUMNS,
                    'future_event_assumption']
PREDICTION_COLUMNS = ['hour_utc', *SEGMENTS, 'actual_chats', 'predicted_chats', 'model']
SCORE_COLUMNS = [*SEGMENTS, 'model', 'holdout_hours', 'mae', 'rmse', 'wape']


def generate_data(seed=19062026, days=210, chats_per_day=190):
    if any(not isinstance(value, (int, np.integer)) or isinstance(value, bool) or value < 1
           for value in (days, chats_per_day)):
        raise ValueError('days and chats_per_day must be positive integers')
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
    out = df.copy()
    for name in ['arrived_at_utc', 'local_timezone']:
        if name not in out:
            raise ValueError(f'Input must include {name}')
    out['arrived_at_utc'] = pd.to_datetime(out['arrived_at_utc'], utc=True, errors='coerce')
    local_hour = np.full(len(out), -1, dtype=int)
    for zone in out['local_timezone'].dropna().unique():
        mask = out['local_timezone'].eq(zone).to_numpy()
        try:
            hours = pd.DatetimeIndex(out.loc[mask, 'arrived_at_utc']).tz_convert(zone).hour
            local_hour[mask] = np.where(pd.isna(hours), -1, hours).astype(int)
        except Exception as exc:
            raise ValueError(f'Invalid IANA timezone {zone!r}: {exc}') from exc
    out['local_hour'] = local_hour
    return out


def load_input_csv(path):
    return _with_local_hour(pd.read_csv(path, dtype={'chat_id': str}))


def validate_chats(df):
    missing = [c for c in CHAT_COLUMNS if c not in df]
    if missing:
        raise ValueError('Missing columns: ' + str(missing))
    if df.empty:
        raise ValueError('Chat data must contain at least one row')
    checks = []

    def record(name, failed, detail):
        checks.append({'check': name, 'status': 'PASS' if failed == 0 else 'FAIL',
                       'failed_rows': int(failed), 'details': detail})

    blank_ids = df.chat_id.isna() | df.chat_id.astype(str).str.strip().eq('')
    record('unique_chat_id', blank_ids.sum() + df.chat_id.duplicated().sum(), 'chat_id must be unique and non-blank')
    dims = ['region', 'language', 'channel', 'market', 'team', 'local_timezone', 'event_type', 'contact_reason']
    blank_dims = df[dims].isna() | df[dims].astype(str).apply(lambda col: col.str.strip().eq(''))
    record('required_dimensions', blank_dims.any(axis=1).sum(), 'Required dimensions must be populated')
    valid_language = df.apply(lambda r: r['language'] in REGIONS.get(r['region'], []), axis=1)
    record('region_language', (~valid_language).sum(), 'Language must be supported by the selected region')
    timestamps = pd.to_datetime(df.arrived_at_utc, utc=True, errors='coerce')
    record('valid_utc_timestamp', timestamps.isna().sum(), 'arrived_at_utc must be parseable as UTC')
    values = df[METRICS].apply(pd.to_numeric, errors='coerce')
    numeric_bad = values[[c for c in METRICS if c != 'csat']].isna().any(axis=1)
    numeric_bad |= df.csat.notna() & values.csat.isna()
    record('numeric_metrics', numeric_bad.sum(), 'Required metrics must be numeric; unsurveyed CSAT may be null')
    finite = np.isfinite(values.fillna(0).to_numpy(dtype=float)).all(axis=1)
    record('finite_metrics', (~finite).sum(), 'Metrics must be finite numbers')
    nonnegative = ['first_response_minutes', 'handling_minutes', 'revenue']
    record('nonnegative_metrics', (values[nonnegative] < 0).any(axis=1).sum(), 'Durations and revenue cannot be negative')
    concurrency_bad = (values.concurrency < 1) | (values.concurrency % 1 != 0)
    record('positive_concurrency', concurrency_bad.sum(), 'Concurrency must be a positive integer')
    record('binary_outcomes', (~values[['resolved', 'converted', 'escalated']].isin([0, 1])).any(axis=1).sum(), 'Outcomes must be 0 or 1')
    record('csat_range', (values.csat.notna() & ~values.csat.between(1, 5)).sum(), 'CSAT must be null or between 1 and 5')
    record('revenue_attribution', ((values.converted == 0) & (values.revenue != 0)).sum(), 'Revenue must be zero for unconverted chats')
    record('event_type', (~df.event_type.isin({'none', 'campaign', 'holiday', 'product_launch', 'incident'})).sum(), 'Unsupported event_type')
    record('known_region', (~df.region.isin(REGIONS)).sum(), 'Unknown region code')
    invalid_timezone = 0
    from zoneinfo import ZoneInfo
    for zone in df.local_timezone.dropna().unique():
        try:
            ZoneInfo(str(zone))
        except (ValueError, KeyError):
            invalid_timezone += int(df.local_timezone.eq(zone).sum())
    record('valid_timezone', invalid_timezone, 'local_timezone must be a valid IANA timezone')
    report = pd.DataFrame(checks)
    failed = report.loc[report.status == 'FAIL', 'check']
    if not failed.empty:
        raise ValueError('Chat data validation failed: ' + ', '.join(failed))
    return report


def load_event_calendar(path):
    events = pd.read_csv(path, dtype=str)
    required = ['event_id', *SEGMENTS, 'event_type', 'start_utc', 'end_utc']
    missing = set(required) - set(events.columns)
    if missing:
        raise ValueError(f'Event calendar missing columns: {sorted(missing)}')
    events = events[required].copy()
    if events.empty:
        events['start_utc'] = pd.to_datetime(events.start_utc, utc=True)
        events['end_utc'] = pd.to_datetime(events.end_utc, utc=True)
        return events
    if events.isna().any().any() or events.apply(lambda c: c.str.strip().eq('')).any().any():
        raise ValueError('Event calendar fields must be populated')
    if events.event_id.duplicated().any():
        raise ValueError('Event IDs must be unique')
    for dim in SEGMENTS:
        events[dim] = events[dim].replace({'ALL': '*', 'all': '*'})
    if not events.region.isin([*REGIONS, '*']).all():
        raise ValueError('Unsupported event region')
    for row in events.itertuples():
        languages = REGIONS.get(row.region, set(sum(REGIONS.values(), [])))
        if row.language != '*' and row.language not in languages:
            raise ValueError('Unsupported event region/language combination')
    events['start_utc'] = pd.to_datetime(events.start_utc, utc=True, errors='coerce')
    events['end_utc'] = pd.to_datetime(events.end_utc, utc=True, errors='coerce')
    if events[['start_utc', 'end_utc']].isna().any().any():
        raise ValueError('Event start/end must be valid UTC timestamps')
    if (events.end_utc <= events.start_utc).any():
        raise ValueError('Event end_utc must be after start_utc')
    if not events.event_type.isin({'campaign', 'holiday', 'product_launch', 'incident'}).all():
        raise ValueError('Unsupported event_type in event calendar')
    return events


def apply_event_calendar(hourly, events):
    out = hourly.copy()
    for col in EVENT_COLUMNS:
        if col not in out:
            out[col] = 0.0
    if events is None or events.empty:
        return out
    out['hour_utc'] = pd.to_datetime(out.hour_utc, utc=True)
    for event in events.itertuples():
        mask = (out.hour_utc < event.end_utc) & (out.hour_utc + ONE_HOUR > event.start_utc)
        for dim in SEGMENTS:
            if str(getattr(event, dim)) not in ('*', 'ALL', 'all'):
                mask &= out[dim].astype(str).eq(str(getattr(event, dim)))
        out.loc[mask, 'event_rate'] = 1.0
        col = {'campaign': 'campaign_rate', 'holiday': 'holiday_rate',
               'product_launch': 'launch_rate', 'incident': 'incident_rate'}[event.event_type]
        out.loc[mask, col] = 1.0
    return out


def _forecast_history(group, keys, events):
    group = group[['hour_utc', 'chats']].copy()
    group['hour_utc'] = pd.to_datetime(group.hour_utc, utc=True)
    full = pd.date_range(group.hour_utc.min(), group.hour_utc.max(), freq='h')
    group = group.set_index('hour_utc').reindex(full).rename_axis('hour_utc').reset_index()
    group['chats'] = group.chats.fillna(0)
    for dim, key in zip(SEGMENTS, keys):
        group[dim] = key
    # Realized chat-level event rates are unavailable at prediction time.
    for col in EVENT_COLUMNS:
        group[col] = 0.0
    group = apply_event_calendar(group, events)
    group['hour'] = group.hour_utc.dt.hour
    group['dow'] = group.hour_utc.dt.dayofweek
    group['lag24'] = group.chats.shift(24)
    group['lag168'] = group.chats.shift(168)
    group['roll24'] = group.chats.shift(1).rolling(24, min_periods=6).mean()
    return group


def build_forecast(hourly, events=None):
    predictions = []
    scores = []
    for keys, group in hourly.groupby(SEGMENTS):
        history = _forecast_history(group, keys, events)
        usable = len(history) - 168
        if usable < 72:
            continue
        cut = 168 + max(24, int(usable * .8))
        train = history.iloc[:cut]
        test = history.iloc[cut:]
        future = build_future_forecast(train, events=events, horizon_hours=len(test))
        actual = test.chats.to_numpy()
        predicted = future.predicted_chats.to_numpy()
        score = dict(zip(SEGMENTS, keys))
        score.update(model=future.model.iloc[0], holdout_hours=len(test),
                     mae=mean_absolute_error(actual, predicted),
                     rmse=mean_squared_error(actual, predicted) ** .5,
                     wape=np.abs(actual - predicted).sum() / actual.sum() if actual.sum() else np.nan)
        scores.append(score)
        future['actual_chats'] = actual
        predictions.append(future[PREDICTION_COLUMNS])
    return (pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame(columns=PREDICTION_COLUMNS),
            pd.DataFrame(scores, columns=SCORE_COLUMNS))


def build_future_forecast(hourly, events=None, horizon_hours=168):
    if not isinstance(horizon_hours, (int, np.integer)) or isinstance(horizon_hours, bool) or horizon_hours < 1:
        raise ValueError('horizon_hours must be a positive integer')
    features = ['hour', 'dow', 'lag24', 'lag168', 'roll24', *EVENT_COLUMNS]
    results = []
    for keys, group in hourly.groupby(SEGMENTS):
        group = _forecast_history(group, keys, events)
        train = group.dropna(subset=['lag24', 'lag168', 'roll24'])
        model = None
        model_name = 'seasonal_naive'
        if len(train) >= 100:
            model = RandomForestRegressor(n_estimators=100, max_depth=9, min_samples_leaf=3,
                                          random_state=42, n_jobs=1)
            model.fit(train[features], train.chats)
            model_name = 'random_forest'
        history = list(group.chats.astype(float))
        future = pd.DataFrame({'hour_utc': pd.date_range(group.hour_utc.max() + ONE_HOUR,
                                                       periods=horizon_hours, freq='h')})
        for dim, key in zip(SEGMENTS, keys):
            future[dim] = key
        future = apply_event_calendar(future, events)
        for row in future.itertuples():
            lag24 = history[-24] if len(history) >= 24 else float(np.mean(history))
            lag168 = history[-168] if len(history) >= 168 else lag24
            inputs = {'hour': row.hour_utc.hour, 'dow': row.hour_utc.dayofweek,
                      'lag24': lag24, 'lag168': lag168, 'roll24': float(np.mean(history[-24:]))}
            inputs.update({col: getattr(row, col) for col in EVENT_COLUMNS})
            value = max(0.0, float(model.predict(pd.DataFrame([inputs])[features])[0])) if model is not None else max(0.0, lag168)
            history.append(value)
            result = {'hour_utc': row.hour_utc, **dict(zip(SEGMENTS, keys)), 'predicted_chats': round(value, 2),
                      'model': model_name, **{col: getattr(row, col) for col in EVENT_COLUMNS},
                      'future_event_assumption': 'supplied event calendar' if events is not None and not events.empty else 'no future event calendar supplied'}
            results.append(result)
    return pd.DataFrame(results, columns=FORECAST_COLUMNS)


def run_pipeline(days=210, chats_per_day=190, input_path=None, events_path=None, output_dir=None):
    df = load_input_csv(input_path) if input_path else _with_local_hour(generate_data(days=days, chats_per_day=chats_per_day))
    quality = validate_chats(df)
    df = df[[*CHAT_COLUMNS, 'local_hour']].copy()
    df[METRICS] = df[METRICS].apply(pd.to_numeric, errors='raise')
    events = load_event_calendar(events_path) if events_path else pd.DataFrame({
        'event_id': pd.Series(dtype=str), 'region': pd.Series(dtype=str), 'language': pd.Series(dtype=str),
        'channel': pd.Series(dtype=str), 'event_type': pd.Series(dtype=str),
        'start_utc': pd.Series(dtype='datetime64[ns, UTC]'), 'end_utc': pd.Series(dtype='datetime64[ns, UTC]')})
    output = Path(output_dir) if output_dir is not None else OUT
    raw = output / 'data' / 'raw' if output_dir is not None else RAW
    output.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    database = output / 'commerce_analytics.duckdb'
    exports = {}
    with duckdb.connect(str(database)) as con:
        con.execute("SET TimeZone='UTC'")
        con.execute('BEGIN TRANSACTION')
        con.register('incoming', df)
        con.execute('CREATE OR REPLACE TABLE conversations AS SELECT * FROM incoming')
        con.register('event_input', events)
        con.execute('CREATE OR REPLACE TABLE event_calendar AS SELECT * FROM event_input')
        con.execute((ROOT / 'sql' / 'analytics.sql').read_text(encoding='utf-8'))
        con.execute((ROOT / 'sql' / 'reconciliation.sql').read_text(encoding='utf-8'))
        reconciliation = con.execute('SELECT * FROM data_reconciliation').df()
        if not reconciliation.status.eq('PASS').all():
            raise ValueError('SQL data reconciliation failed')
        con.execute('COMMIT')
        names = ['hourly_commerce', 'staffing_coverage', 'service_commercial_risk', 'operational_anomalies',
                 'root_cause_decomposition', 'daily_kpis', 'weekly_kpis', 'monthly_kpis', 'team_kpis',
                 'data_reconciliation', 'event_calendar_impact']
        for name in names:
            frame = con.execute('SELECT * FROM ' + name).df()
            frame.to_csv(output / ('tableau_' + name + '.csv'), index=False)
            exports[name] = len(frame)
        hourly = con.execute('SELECT * FROM hourly_commerce').df()
        predictions, scores = build_forecast(hourly, events)
        predictions.to_csv(output / 'forecast_holdout.csv', index=False)
        scores.to_csv(output / 'forecast_scores.csv', index=False)
        build_future_forecast(hourly, events=events).to_csv(output / 'forecast_next_7_days.csv', index=False)
        con.execute('SELECT * FROM daily_kpis').df().to_csv(output / 'daily_tracker.csv', index=False)
        weekly = con.execute("SELECT date_trunc('week',arrived_at_utc)::DATE AS week_start,count(*) AS chats,avg(converted::INT) AS conversion_rate,avg(first_response_minutes) AS avg_first_response_minutes,sum(revenue) AS converted_revenue FROM conversations GROUP BY 1 ORDER BY 1 DESC LIMIT 1").df().iloc[0]
        monthly = con.execute("SELECT date_trunc('month',arrived_at_utc)::DATE AS month_start,count(*) AS chats,avg(resolved::INT) AS resolution_rate,avg(converted::INT) AS conversion_rate,avg(csat) AS avg_csat,sum(revenue) AS converted_revenue FROM conversations GROUP BY 1 ORDER BY 1 DESC LIMIT 1").df().iloc[0]
        risks = con.execute("SELECT * FROM service_commercial_risk ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'MEDIUM' THEN 3 ELSE 4 END, hour_utc DESC LIMIT 5").df()
    df.to_csv(raw / 'conversations.csv', index=False)
    quality.to_csv(output / 'data_quality.csv', index=False)
    brief = ['# Weekly operations brief', '', f"Week starting (UTC): {weekly['week_start']}",
             'Scope: all regions, languages and channels', f"Chats: {int(weekly['chats']):,}",
             f"Conversion: {weekly['conversion_rate']:.1%}",
             f"Mean first response: {weekly['avg_first_response_minutes']:.1f} min",
             f"Converted revenue: ${weekly['converted_revenue']:,.0f}", '', '## Priority risk alerts']
    for row in risks.itertuples():
        brief.append(f'- {row.severity} {row.region}/{row.language}/{row.channel}: {row.risk_type} — {row.suggested_action}')
    (output / 'weekly_brief.md').write_text('\n'.join(brief) + '\n', encoding='utf-8')
    summary = ['# Monthly executive summary', '', f"Month (UTC): {monthly['month_start']}",
               'Scope: all regions, languages and channels', f"Chats: {int(monthly['chats']):,}",
               f"Resolution: {monthly['resolution_rate']:.1%}", f"Conversion: {monthly['conversion_rate']:.1%}",
               f"CSAT: {monthly['avg_csat']:.2f}", f"Converted revenue: ${monthly['converted_revenue']:,.0f}",
               '', '## Decision focus', 'Review the largest skill-pool coverage gaps before changing staffing.',
               'Revenue is attributed converted revenue, not estimated revenue loss.']
    (output / 'monthly_executive_summary.md').write_text('\n'.join(summary) + '\n', encoding='utf-8')
    manifest = {'synthetic': input_path is None, 'source_file': str(input_path) if input_path else None,
                'rows': len(df), 'tables': exports, 'database': str(database.resolve()),
                'generated_at_utc': datetime.now(timezone.utc).isoformat(),
                'forecast_evaluation': 'recursive chronological holdout; supplied calendar assumed known in advance'}
    (output / 'run_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    logging.getLogger(__name__).info('Validated and exported %s conversations to %s', len(df), output)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=210)
    parser.add_argument('--chats-per-day', type=int, default=190)
    parser.add_argument('--input', help='Approved chat-level CSV; omitted means synthetic data')
    parser.add_argument('--events', help='Optional approved event calendar with UTC start/end')
    parser.add_argument('--output-dir', help='Output directory; defaults to python/outputs')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run_pipeline(args.days, args.chats_per_day, args.input, args.events, args.output_dir), indent=2))
