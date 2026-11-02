import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from commerce_analytics import ROOT, generate_data


@pytest.fixture
def database():
    frame = generate_data(days=1, chats_per_day=4)
    frame['region'] = 'AMER'
    frame['language'] = 'en'
    frame['channel'] = 'live_chat'
    frame['team'] = ['Payments', 'Payments', 'Retention', 'Core Support']
    frame['arrived_at_utc'] = pd.to_datetime(['2026-01-31T00:00Z', '2026-01-31T00:30Z',
                                            '2026-02-02T00:00Z', '2026-02-02T01:00Z'], utc=True)
    frame['handling_minutes'] = [10., 20., 30., 40.]
    frame['converted'] = [0, 1, 1, 0]
    frame['revenue'] = [0., 50., 100., 0.]
    frame['resolved'] = [1, 0, 1, 1]
    frame['csat'] = [5., None, 3., None]
    frame['escalated'] = [0, 1, 0, 1]
    events = pd.DataFrame([
        {'event_id': 'all', 'region': '*', 'language': '*', 'channel': '*',
         'event_type': 'campaign', 'start_utc': '2026-01-31T00:00Z', 'end_utc': '2026-02-02T00:00Z'},
        {'event_id': 'alias', 'region': 'ALL', 'language': 'all', 'channel': '*',
         'event_type': 'holiday', 'start_utc': '2026-01-31T00:00Z', 'end_utc': '2026-02-02T00:00Z'},
        {'event_id': 'empty', 'region': 'APAC', 'language': 'hi', 'channel': '*',
         'event_type': 'incident', 'start_utc': '2026-01-31T00:00Z', 'end_utc': '2026-02-02T00:00Z'}])
    for column in ['start_utc', 'end_utc']:
        events[column] = pd.to_datetime(events[column], utc=True)
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    con.register('input', frame)
    con.execute('CREATE TABLE conversations AS SELECT * FROM input')
    con.register('events', events)
    con.execute('CREATE TABLE event_calendar AS SELECT * FROM events')
    con.execute((ROOT / 'sql' / 'analytics.sql').read_text(encoding='utf-8'))
    con.execute((ROOT / 'sql' / 'reconciliation.sql').read_text(encoding='utf-8'))
    yield con, frame
    con.close()


@pytest.mark.parametrize('view', ['hourly_commerce', 'staffing_coverage', 'service_commercial_risk',
                                  'operational_anomalies', 'root_cause_decomposition', 'daily_kpis',
                                  'weekly_kpis', 'monthly_kpis', 'team_kpis',
                                  'data_reconciliation', 'event_calendar_impact'])
def test_every_sql_view_executes(database, view):
    con, _ = database
    assert con.execute(f'SELECT * FROM {view}').df() is not None


def test_hourly_spine_and_null_handling(database):
    con, _ = database
    hourly = con.execute('SELECT * FROM hourly_commerce ORDER BY hour_utc').df()
    assert len(hourly) == 50
    assert hourly.chats.sum() == 4
    empty = hourly.loc[hourly.chats == 0]
    assert len(empty) == 47
    assert empty.handling_minutes.eq(0).all()
    assert empty.avg_csat.isna().all()
    coverage = con.execute('SELECT * FROM staffing_coverage WHERE chats=0').df()
    assert coverage.required_agent_equiv.eq(0).all()
    assert coverage.required_agents.eq(0).all()
    assert coverage.agent_gap.eq(0).all()


def test_all_additive_metrics_reconcile(database):
    con, frame = database
    reconciliation = con.execute('SELECT * FROM data_reconciliation').df().set_index('metric')
    expected = {'chat_count': len(frame), 'converted_revenue': frame.revenue.sum(),
                'handling_minutes': frame.handling_minutes.sum(), 'escalations': frame.escalated.sum(),
                'resolved_chats': frame.resolved.sum(), 'converted_chats': frame.converted.sum(),
                'csat_responses': frame.csat.count(), 'csat_total': frame.csat.sum()}
    assert set(reconciliation.index) == set(expected)
    for metric, value in expected.items():
        for column in ['source_value', 'hourly_value', 'daily_value', 'weekly_value', 'monthly_value', 'team_value']:
            assert reconciliation.loc[metric, column] == pytest.approx(value)
    assert reconciliation.status.eq('PASS').all()


def test_reconciliation_detects_wrong_aggregate(database):
    con, _ = database
    con.execute('CREATE OR REPLACE VIEW weekly_kpis AS SELECT * REPLACE(chats+1 AS chats) FROM monthly_kpis')
    reconciliation = con.execute("SELECT status FROM data_reconciliation WHERE metric='chat_count'").fetchone()
    assert reconciliation == ('FAIL',)


def test_periods_and_nullable_csat(database):
    con, _ = database
    months = con.execute('SELECT month_start,sum(chats) FROM monthly_kpis GROUP BY 1 ORDER BY 1').fetchall()
    assert [row[0].isoformat() for row in months] == ['2026-01-01', '2026-02-01']
    assert [row[1] for row in months] == [2, 2]
    weekly = con.execute('SELECT week_start FROM weekly_kpis ORDER BY 1').fetchall()
    assert [row[0].isoformat() for row in weekly] == ['2026-01-26', '2026-02-02']
    assert con.execute('SELECT avg_csat,csat_responses FROM daily_kpis ORDER BY report_date').fetchall() == [(5., 1), (3., 1)]


def test_root_cause_uses_previous_calendar_day(database):
    con, _ = database
    rows = con.execute('SELECT * FROM root_cause_decomposition ORDER BY day').df()
    assert len(rows) == 3
    assert rows.iloc[1].chats == 0
    workload_change = rows.workload_minutes.diff().fillna(0)
    pd.testing.assert_series_equal(rows.handling_time_effect_minutes + rows.volume_effect_minutes,
                                   workload_change, check_names=False)


def test_event_bounds_wildcards_and_overlap(database):
    con, _ = database
    events = con.execute('SELECT * FROM event_calendar_impact').df().set_index('event_id')
    assert events.loc['all', 'observed_chats'] == 2
    assert events.loc['alias', 'observed_chats'] == 2
    assert events.loc['empty', 'observed_chats'] == 0
    assert events.loc['empty', 'converted_revenue'] == 0
    assert pd.isna(events.loc['empty', 'conversion_rate'])
    assert events.loc['all', 'converted_revenue'] == 50


def test_team_breakdowns_do_not_duplicate_fact_rows(database):
    con, _ = database
    teams = con.execute('SELECT team,sum(chats),sum(converted_revenue) FROM team_kpis GROUP BY team').fetchall()
    assert {team: (chats, revenue) for team, chats, revenue in teams} == {
        'Payments': (2, 50.), 'Retention': (1, 100.), 'Core Support': (1, 0.)}


def test_pool_allocation_does_not_duplicate_agents(database):
    con, frame = database
    other = frame.copy()
    other['chat_id'] = 'other-' + other.chat_id
    other['channel'] = 'web'
    con.register('other', other)
    con.execute('INSERT INTO conversations SELECT * FROM other')
    rows = con.execute('SELECT sum(allocated_scheduled_agents),max(break_adjusted_agents),sum(required_agent_equiv) FROM staffing_coverage WHERE hour_utc=(SELECT min(hour_utc) FROM staffing_coverage)').fetchone()
    assert float(rows[0]) == pytest.approx(float(rows[1]))
    assert float(rows[2]) == pytest.approx(60 / (60 * .85 * .75))


def test_volume_anomaly_executes_on_real_hourly_history(database):
    con, frame = database
    batches = []
    for hour in range(25):
        count = 20 if hour == 24 else 1 + hour % 2
        for index in range(count):
            row = frame.iloc[[0]].copy()
            row['chat_id'] = f'{hour}-{index}'
            row['arrived_at_utc'] = pd.Timestamp('2026-01-01', tz='UTC') + pd.Timedelta(hour, unit="h")
            batches.append(row)
    source = pd.concat(batches, ignore_index=True)
    con.register('replacement', source)
    con.execute('CREATE OR REPLACE TABLE conversations AS SELECT * FROM replacement')
    anomalies = con.execute('SELECT * FROM operational_anomalies ORDER BY hour_utc').df()
    assert anomalies.iloc[-1].anomaly_type == 'VOLUME_SPIKE'
    assert anomalies.iloc[-1].chats == 20
