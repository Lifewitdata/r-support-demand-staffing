CREATE OR REPLACE VIEW data_reconciliation AS
SELECT 'chat_count' AS metric,
       (SELECT count(*) FROM conversations) AS source_value,
       (SELECT sum(chats) FROM hourly_commerce) AS hourly_value,
       (SELECT sum(chats) FROM daily_kpis) AS daily_value;
