-- Complete hourly calendar per observed region/language/channel segment.
-- Empty hours remain visible with zero chats so rolling windows mean real hours.
CREATE OR REPLACE VIEW hourly_commerce AS
WITH segments AS (
 SELECT DISTINCT region,language,channel FROM conversations
), bounds AS (
 SELECT date_trunc('hour',min(arrived_at_utc)) AS min_hour,
        date_trunc('hour',max(arrived_at_utc)) AS max_hour FROM conversations
), hours AS (
 SELECT unnest(generate_series(min_hour,max_hour,INTERVAL 1 HOUR)) AS hour_utc FROM bounds
), spine AS (
 SELECT h.hour_utc,s.region,s.language,s.channel FROM hours h CROSS JOIN segments s
), agg AS (
 SELECT date_trunc('hour',arrived_at_utc) AS hour_utc,region,language,channel,count(*) AS chats,
  avg(first_response_minutes) AS avg_first_response_minutes,
  quantile_cont(first_response_minutes,.90) AS p90_first_response_minutes,
  avg(handling_minutes) AS avg_handling_minutes,sum(handling_minutes) AS handling_minutes,
  avg(resolved::INT) AS resolution_rate,avg(csat) AS avg_csat,
  avg(converted::INT) AS conversion_rate,sum(revenue) AS converted_revenue,
  sum(resolved::INT) AS resolved_chats,sum(converted::INT) AS converted_chats,
  count(csat) AS csat_responses,sum(csat) AS csat_total,
  avg(concurrency) AS avg_concurrency,sum(escalated) AS escalations,
  count(*) FILTER(WHERE event_type<>'none') AS event_chats,
  avg((event_type<>'none')::INT) AS event_rate,
  avg((event_type='incident')::INT) AS incident_rate,
  avg((event_type='campaign')::INT) AS campaign_rate,
  avg((event_type='holiday')::INT) AS holiday_rate,
  avg((event_type='product_launch')::INT) AS launch_rate,
  mode(local_hour) AS local_hour
 FROM conversations GROUP BY 1,2,3,4
)
SELECT s.hour_utc,s.region,s.language,s.channel,coalesce(a.chats,0) AS chats,
 a.avg_first_response_minutes,a.p90_first_response_minutes,a.avg_handling_minutes,
 coalesce(a.handling_minutes,0) AS handling_minutes,a.resolution_rate,a.avg_csat,
 a.conversion_rate,coalesce(a.converted_revenue,0) AS converted_revenue,a.avg_concurrency,
 coalesce(a.resolved_chats,0) AS resolved_chats,coalesce(a.converted_chats,0) AS converted_chats,
 coalesce(a.csat_responses,0) AS csat_responses,coalesce(a.csat_total,0) AS csat_total,
 coalesce(a.escalations,0) AS escalations,coalesce(a.event_chats,0) AS event_chats,
 coalesce(a.event_rate,0) AS event_rate,coalesce(a.incident_rate,0) AS incident_rate,
 coalesce(a.campaign_rate,0) AS campaign_rate,coalesce(a.holiday_rate,0) AS holiday_rate,
 coalesce(a.launch_rate,0) AS launch_rate,a.local_hour
FROM spine s LEFT JOIN agg a USING(hour_utc,region,language,channel);
-- Illustrative assumptions: 85% occupancy, 25% shrinkage, $24 loaded agent-hour.
CREATE OR REPLACE VIEW staffing_coverage AS
WITH demand AS (SELECT *,handling_minutes/(60.0*.85*.75) AS required_agent_equiv,
 sum(handling_minutes) OVER(PARTITION BY hour_utc,region,language) AS pool_workload_minutes FROM hourly_commerce),
pool_schedule AS (SELECT DISTINCT hour_utc,region,language,
 CASE WHEN extract(hour FROM hour_utc)>=7 AND extract(hour FROM hour_utc)<15 THEN 'Day 07-15'
 WHEN extract(hour FROM hour_utc)>=15 AND extract(hour FROM hour_utc)<23 THEN 'Evening 15-23' ELSE 'Night 23-07' END AS shift_pattern,
 CASE WHEN extract(hour FROM hour_utc)>=7 AND extract(hour FROM hour_utc)<15 THEN 3
 WHEN extract(hour FROM hour_utc)>=15 AND extract(hour FROM hour_utc)<23 THEN 2 ELSE 1 END AS rostered_agents
 FROM hourly_commerce),
allocated AS (SELECT d.*,p.shift_pattern,p.rostered_agents,p.rostered_agents*.90 AS break_adjusted_agents,
 p.region||'-'||p.language AS skill_pool,
 CASE WHEN d.pool_workload_minutes>0 THEN p.rostered_agents*.90*d.handling_minutes/d.pool_workload_minutes ELSE 0 END AS allocated_scheduled_agents
 FROM demand d JOIN pool_schedule p USING(hour_utc,region,language))
SELECT *,ceil(required_agent_equiv) AS required_agents,
 greatest(0,required_agent_equiv-allocated_scheduled_agents) AS agent_gap,
 greatest(0,allocated_scheduled_agents-required_agent_equiv) AS overstaffed_agents,
 greatest(0,required_agent_equiv-allocated_scheduled_agents)*24.0 AS estimated_hourly_gap_cost
FROM allocated;
CREATE OR REPLACE VIEW service_commercial_risk AS
WITH b AS (SELECT *,CASE WHEN agent_gap>0 THEN 'coverage_gap' WHEN p90_first_response_minutes>10 THEN 'response_time'
 WHEN conversion_rate<.08 THEN 'conversion' WHEN avg_concurrency>=3.5 THEN 'queue_saturation' WHEN resolution_rate<.82 THEN 'resolution' END AS risk_type,
 CASE WHEN agent_gap>0 THEN 'CRITICAL' WHEN p90_first_response_minutes>15 OR resolution_rate<.70 THEN 'HIGH'
 WHEN p90_first_response_minutes>10 OR conversion_rate<.08 OR avg_concurrency>=3.5 OR resolution_rate<.82 THEN 'MEDIUM' ELSE 'LOW' END AS severity FROM staffing_coverage)
SELECT hour_utc,region,language,channel,risk_type,severity,shift_pattern,skill_pool,agent_gap,p90_first_response_minutes,conversion_rate,
 CASE risk_type WHEN 'coverage_gap' THEN 'Rebalance trained language coverage or offer voluntary overtime'
 WHEN 'response_time' THEN 'Review intraday queue load and first-response routing' WHEN 'conversion' THEN 'Review quality and commercial handoff'
 WHEN 'queue_saturation' THEN 'Reduce concurrency or add skill-matched coverage' WHEN 'resolution' THEN 'Review escalation drivers and knowledge gaps' END AS suggested_action
FROM b WHERE risk_type IS NOT NULL;
CREATE OR REPLACE VIEW operational_anomalies AS
WITH w AS (SELECT *,avg(chats) OVER(PARTITION BY region,language,channel ORDER BY hour_utc ROWS BETWEEN 24 PRECEDING AND 1 PRECEDING) AS prior_volume_avg,
 stddev_samp(chats) OVER(PARTITION BY region,language,channel ORDER BY hour_utc ROWS BETWEEN 24 PRECEDING AND 1 PRECEDING) AS prior_volume_sd,
 avg(avg_handling_minutes) OVER(PARTITION BY region,language,channel ORDER BY hour_utc ROWS BETWEEN 24 PRECEDING AND 1 PRECEDING) AS prior_aht_avg,
 stddev_samp(avg_handling_minutes) OVER(PARTITION BY region,language,channel ORDER BY hour_utc ROWS BETWEEN 24 PRECEDING AND 1 PRECEDING) AS prior_aht_sd
 FROM hourly_commerce)
SELECT *,CASE WHEN prior_volume_sd>0 AND chats>prior_volume_avg+3*prior_volume_sd THEN 'VOLUME_SPIKE'
 WHEN prior_volume_sd>0 AND chats<prior_volume_avg-3*prior_volume_sd THEN 'VOLUME_DROP'
 WHEN prior_aht_sd>0 AND avg_handling_minutes>prior_aht_avg+3*prior_aht_sd THEN 'AHT_SPIKE' END AS anomaly_type
FROM w WHERE (prior_volume_sd>0 AND abs(chats-prior_volume_avg)>3*prior_volume_sd)
 OR (prior_aht_sd>0 AND avg_handling_minutes>prior_aht_avg+3*prior_aht_sd);
CREATE OR REPLACE VIEW root_cause_decomposition AS
WITH facts AS (SELECT CAST(arrived_at_utc AS DATE) AS day,region,language,channel,
 avg(escalated::INT) AS escalation_rate,avg(resolved::INT) AS resolution_rate,
 avg(concurrency) AS avg_concurrency,mode(contact_reason) AS top_contact_reason
 FROM conversations GROUP BY 1,2,3,4),
d AS (SELECT CAST(hour_utc AS DATE) AS day,region,language,channel,sum(chats) AS chats,
 coalesce(sum(handling_minutes)/nullif(sum(chats),0),0) AS aht,sum(handling_minutes) AS workload_minutes
 FROM hourly_commerce GROUP BY 1,2,3,4),
capacity AS (SELECT CAST(hour_utc AS DATE) AS day,region,language,channel,sum(agent_gap) AS agent_gap_hours
 FROM staffing_coverage GROUP BY 1,2,3,4),
p AS (SELECT d.*,facts.escalation_rate,facts.resolution_rate,facts.avg_concurrency,facts.top_contact_reason,
 lag(chats) OVER(PARTITION BY region,language,channel ORDER BY day) AS prior_chats,
 lag(aht) OVER(PARTITION BY region,language,channel ORDER BY day) AS prior_aht
 FROM d LEFT JOIN facts USING(day,region,language,channel))
SELECT p.day,p.region,p.language,p.channel,p.chats,p.aht,p.workload_minutes,p.escalation_rate,p.resolution_rate,
 p.avg_concurrency,p.top_contact_reason,coalesce(c.agent_gap_hours,0) AS agent_gap_hours,
 p.chats-coalesce(p.prior_chats,p.chats) AS volume_change,
 round((p.aht-coalesce(p.prior_aht,p.aht))*p.chats,2) AS handling_time_effect_minutes,
 round((p.chats-coalesce(p.prior_chats,p.chats))*coalesce(p.prior_aht,p.aht),2) AS volume_effect_minutes,
 'Associational decomposition; not causal attribution' AS interpretation_note
FROM p LEFT JOIN capacity c USING(day,region,language,channel);
CREATE OR REPLACE VIEW daily_kpis AS SELECT CAST(arrived_at_utc AS DATE) AS report_date,region,language,channel,count(*) AS chats,
 avg(first_response_minutes) AS avg_first_response_minutes,quantile_cont(first_response_minutes,.90) AS p90_first_response_minutes,
 avg(handling_minutes) AS avg_handling_minutes,avg(resolved::INT) AS resolution_rate,avg(csat) AS avg_csat,avg(converted::INT) AS conversion_rate,
 sum(revenue) AS converted_revenue,sum(handling_minutes) AS handling_minutes,sum(escalated) AS escalations,
 sum(resolved::INT) AS resolved_chats,sum(converted::INT) AS converted_chats,count(csat) AS csat_responses,coalesce(sum(csat),0) AS csat_total
 FROM conversations GROUP BY 1,2,3,4;
CREATE OR REPLACE VIEW weekly_kpis AS SELECT date_trunc('week',arrived_at_utc)::DATE AS week_start,region,language,channel,count(*) AS chats,
 avg(first_response_minutes) AS avg_first_response_minutes,avg(resolved::INT) AS resolution_rate,avg(csat) AS avg_csat,
 avg(converted::INT) AS conversion_rate,sum(revenue) AS converted_revenue,sum(handling_minutes) AS handling_minutes,sum(escalated) AS escalations,
 sum(resolved::INT) AS resolved_chats,sum(converted::INT) AS converted_chats,count(csat) AS csat_responses,coalesce(sum(csat),0) AS csat_total
 FROM conversations GROUP BY 1,2,3,4;
CREATE OR REPLACE VIEW monthly_kpis AS SELECT date_trunc('month',arrived_at_utc)::DATE AS month_start,region,language,channel,count(*) AS chats,
 avg(first_response_minutes) AS avg_first_response_minutes,avg(resolved::INT) AS resolution_rate,avg(csat) AS avg_csat,
 avg(converted::INT) AS conversion_rate,sum(revenue) AS converted_revenue,sum(handling_minutes)/60.0 AS handling_hours,
 sum(handling_minutes) AS handling_minutes,sum(escalated) AS escalations,
 sum(resolved::INT) AS resolved_chats,sum(converted::INT) AS converted_chats,count(csat) AS csat_responses,coalesce(sum(csat),0) AS csat_total
 FROM conversations GROUP BY 1,2,3,4;
CREATE OR REPLACE VIEW team_kpis AS SELECT CAST(arrived_at_utc AS DATE) AS report_date,region,language,channel,team,count(*) AS chats,
 avg(first_response_minutes) AS avg_first_response_minutes,quantile_cont(first_response_minutes,.90) AS p90_first_response_minutes,
 avg(handling_minutes) AS avg_handling_minutes,avg(resolved::INT) AS resolution_rate,avg(csat) AS avg_csat,avg(converted::INT) AS conversion_rate,
 sum(revenue) AS converted_revenue,sum(handling_minutes) AS handling_minutes,sum(escalated) AS escalations,
 sum(resolved::INT) AS resolved_chats,sum(converted::INT) AS converted_chats,count(csat) AS csat_responses,coalesce(sum(csat),0) AS csat_total
 FROM conversations GROUP BY 1,2,3,4,5;