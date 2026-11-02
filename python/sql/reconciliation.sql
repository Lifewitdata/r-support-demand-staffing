CREATE OR REPLACE VIEW data_reconciliation AS
WITH totals AS (
 SELECT 'source' AS grain,count(*) AS chat_count,sum(revenue) AS converted_revenue,
 sum(handling_minutes) AS handling_minutes,sum(escalated) AS escalations,
 sum(resolved::INT) AS resolved_chats,sum(converted::INT) AS converted_chats,
 count(csat) AS csat_responses,coalesce(sum(csat),0) AS csat_total FROM conversations
 UNION ALL
 SELECT 'hourly',sum(chats),sum(converted_revenue),sum(handling_minutes),sum(escalations),
 sum(resolved_chats),sum(converted_chats),sum(csat_responses),sum(csat_total) FROM hourly_commerce
 UNION ALL
 SELECT 'daily',sum(chats),sum(converted_revenue),sum(handling_minutes),sum(escalations),
 sum(resolved_chats),sum(converted_chats),sum(csat_responses),sum(csat_total) FROM daily_kpis
 UNION ALL
 SELECT 'weekly',sum(chats),sum(converted_revenue),sum(handling_minutes),sum(escalations),
 sum(resolved_chats),sum(converted_chats),sum(csat_responses),sum(csat_total) FROM weekly_kpis
 UNION ALL
 SELECT 'monthly',sum(chats),sum(converted_revenue),sum(handling_minutes),sum(escalations),
 sum(resolved_chats),sum(converted_chats),sum(csat_responses),sum(csat_total) FROM monthly_kpis
 UNION ALL
 SELECT 'team',sum(chats),sum(converted_revenue),sum(handling_minutes),sum(escalations),
 sum(resolved_chats),sum(converted_chats),sum(csat_responses),sum(csat_total) FROM team_kpis
), metrics AS (
 UNPIVOT totals ON chat_count,converted_revenue,handling_minutes,escalations,
 resolved_chats,converted_chats,csat_responses,csat_total INTO NAME metric VALUE total
), comparison AS (
 SELECT metric,max(total) FILTER(WHERE grain='source') AS source_value,
 max(total) FILTER(WHERE grain='hourly') AS hourly_value,
 max(total) FILTER(WHERE grain='daily') AS daily_value,
 max(total) FILTER(WHERE grain='weekly') AS weekly_value,
 max(total) FILTER(WHERE grain='monthly') AS monthly_value,
 max(total) FILTER(WHERE grain='team') AS team_value FROM metrics GROUP BY metric
)
SELECT *,CASE WHEN abs(source_value-hourly_value)<=0.000001
 AND abs(source_value-daily_value)<=0.000001 AND abs(source_value-weekly_value)<=0.000001
 AND abs(source_value-monthly_value)<=0.000001 AND abs(source_value-team_value)<=0.000001
 THEN 'PASS' ELSE 'FAIL' END AS status FROM comparison;

-- Overlapping events count their own overlaps; event totals are not additive.
CREATE OR REPLACE VIEW event_calendar_impact AS
SELECT e.event_id,e.event_type,e.region,e.language,e.channel,e.start_utc,e.end_utc,
       count(c.chat_id) AS observed_chats,
       avg(c.first_response_minutes) AS avg_first_response_minutes,
       avg(c.handling_minutes) AS avg_handling_minutes,
       avg(c.converted::INT) AS conversion_rate,
       coalesce(sum(c.revenue),0) AS converted_revenue
FROM event_calendar e
LEFT JOIN conversations c
  ON c.arrived_at_utc>=e.start_utc AND c.arrived_at_utc<e.end_utc
 AND (e.region IN ('*','ALL','all') OR e.region=c.region)
 AND (e.language IN ('*','ALL','all') OR e.language=c.language)
 AND (e.channel IN ('*','ALL','all') OR e.channel=c.channel)
GROUP BY e.event_id,e.event_type,e.region,e.language,e.channel,e.start_utc,e.end_utc;
