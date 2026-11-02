CREATE OR REPLACE VIEW data_reconciliation AS
SELECT 'chat_count' AS metric,
       (SELECT count(*) FROM conversations) AS source_value,
       (SELECT sum(chats) FROM hourly_commerce) AS hourly_value,
       (SELECT sum(chats) FROM daily_kpis) AS daily_value;
CREATE OR REPLACE VIEW event_calendar_impact AS
SELECT e.event_id,e.event_type,e.region,e.language,e.channel,e.start_utc,e.end_utc,
       count(c.chat_id) AS observed_chats,
       avg(c.first_response_minutes) AS avg_first_response_minutes,
       avg(c.handling_minutes) AS avg_handling_minutes,
       avg(c.converted::INT) AS conversion_rate
FROM event_calendar e
LEFT JOIN conversations c
  ON c.arrived_at_utc>=e.start_utc AND c.arrived_at_utc<e.end_utc
 AND (e.region='*' OR e.region=c.region)
 AND (e.language='*' OR e.language=c.language)
 AND (e.channel='*' OR e.channel=c.channel)
GROUP BY e.event_id,e.event_type,e.region,e.language,e.channel,e.start_utc,e.end_utc;
