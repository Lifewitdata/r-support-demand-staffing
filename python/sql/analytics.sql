CREATE OR REPLACE VIEW hourly_commerce AS
SELECT date_trunc('hour',arrived_at_utc) AS hour_utc,region,language,channel,count(*) AS chats,
 avg(first_response_minutes) AS avg_first_response_minutes,quantile_cont(first_response_minutes,.90) AS p90_first_response_minutes,
 avg(handling_minutes) AS avg_handling_minutes,sum(handling_minutes) AS handling_minutes,avg(resolved::INT) AS resolution_rate,
 avg(csat) AS avg_csat,avg(converted::INT) AS conversion_rate,sum(revenue) AS converted_revenue,avg(concurrency) AS avg_concurrency,
 sum(escalated) AS escalations,count(*) FILTER(WHERE event_type<>'none') AS event_chats
FROM conversations GROUP BY 1,2,3,4;
-- Planning assumptions: 85% occupancy, 25% shrinkage, $24 loaded agent-hour; illustrative only.
CREATE OR REPLACE VIEW staffing_coverage AS
WITH d AS (SELECT *,ceil(chats*avg_handling_minutes/(60.0*.85*.75)) AS required_agents FROM hourly_commerce),
s AS (SELECT *,greatest(0,floor(1+2*sin((extract(hour FROM hour_utc)-8)*pi()/12))) AS scheduled_agents FROM d)
SELECT *,greatest(0,required_agents-scheduled_agents) AS agent_gap,greatest(0,scheduled_agents-required_agents) AS overstaffed_agents,
 greatest(0,required_agents-scheduled_agents)*24.0 AS estimated_hourly_gap_cost FROM s;
CREATE OR REPLACE VIEW service_commercial_risk AS
WITH b AS (SELECT *,CASE WHEN required_agents>scheduled_agents THEN 'coverage_gap' WHEN p90_first_response_minutes>10 THEN 'response_time'
 WHEN conversion_rate<.08 THEN 'conversion' WHEN avg_concurrency>=3.5 THEN 'queue_saturation' WHEN resolution_rate<.82 THEN 'resolution' END AS risk_type,
 CASE WHEN required_agents>scheduled_agents THEN 'CRITICAL' WHEN p90_first_response_minutes>15 OR resolution_rate<.70 THEN 'HIGH'
 WHEN p90_first_response_minutes>10 OR conversion_rate<.08 OR avg_concurrency>=3.5 THEN 'MEDIUM' ELSE 'LOW' END AS severity FROM staffing_coverage)
SELECT hour_utc,region,language,channel,risk_type,severity,agent_gap,p90_first_response_minutes,conversion_rate,
 CASE risk_type WHEN 'coverage_gap' THEN 'Rebalance trained coverage or offer voluntary overtime'
 WHEN 'response_time' THEN 'Review intraday queue load and first-response routing' WHEN 'conversion' THEN 'Review quality and commercial handoff'
 WHEN 'queue_saturation' THEN 'Reduce concurrency or add skill-matched coverage' WHEN 'resolution' THEN 'Review escalation drivers and knowledge gaps' END AS suggested_action
FROM b WHERE risk_type IS NOT NULL;
CREATE OR REPLACE VIEW root_cause_decomposition AS
WITH d AS (SELECT CAST(arrived_at_utc AS DATE) AS day,region,language,channel,count(*) AS chats,avg(handling_minutes) AS aht,
 sum(handling_minutes) AS workload_minutes,avg(escalated::INT) AS escalation_rate,avg(resolved::INT) AS resolution_rate,avg(concurrency) AS avg_concurrency
 FROM conversations GROUP BY 1,2,3,4),
p AS (SELECT *,lag(chats) OVER(PARTITION BY region,language,channel ORDER BY day) AS prior_chats,lag(aht) OVER(PARTITION BY region,language,channel ORDER BY day) AS prior_aht FROM d)
SELECT day,region,language,channel,chats,aht,workload_minutes,escalation_rate,resolution_rate,avg_concurrency,
 chats-coalesce(prior_chats,chats) AS volume_change,round((aht-coalesce(prior_aht,aht))*chats,2) AS handling_time_effect_minutes,
 round((chats-coalesce(prior_chats,chats))*coalesce(prior_aht,aht),2) AS volume_effect_minutes,
 'Associational decomposition; not causal attribution' AS interpretation_note FROM p;
CREATE OR REPLACE VIEW daily_kpis AS SELECT CAST(arrived_at_utc AS DATE) AS report_date,region,language,channel,count(*) AS chats,
 avg(first_response_minutes) AS avg_first_response_minutes,quantile_cont(first_response_minutes,.90) AS p90_first_response_minutes,
 avg(handling_minutes) AS avg_handling_minutes,avg(resolved::INT) AS resolution_rate,avg(csat) AS avg_csat,avg(converted::INT) AS conversion_rate,
 sum(revenue) AS converted_revenue,sum(escalated) AS escalations FROM conversations GROUP BY 1,2,3,4;
CREATE OR REPLACE VIEW weekly_kpis AS SELECT date_trunc('week',arrived_at_utc)::DATE AS week_start,region,language,channel,count(*) AS chats,
 avg(first_response_minutes) AS avg_first_response_minutes,avg(resolved::INT) AS resolution_rate,avg(csat) AS avg_csat,
 avg(converted::INT) AS conversion_rate,sum(revenue) AS converted_revenue FROM conversations GROUP BY 1,2,3,4;
CREATE OR REPLACE VIEW monthly_kpis AS SELECT date_trunc('month',arrived_at_utc)::DATE AS month_start,region,language,channel,count(*) AS chats,
 avg(first_response_minutes) AS avg_first_response_minutes,avg(resolved::INT) AS resolution_rate,avg(csat) AS avg_csat,
 avg(converted::INT) AS conversion_rate,sum(revenue) AS converted_revenue,sum(handling_minutes)/60.0 AS handling_hours
FROM conversations GROUP BY 1,2,3,4;