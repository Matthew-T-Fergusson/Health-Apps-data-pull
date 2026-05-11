CREATE OR REPLACE VIEW health.weight_trend_daily AS
WITH w AS (
  SELECT
    metric_date,
    weight_kg,
    weight_kg * 2.20462262185 AS weight_lb
  FROM health.body_composition_daily
  WHERE source='garmin' AND weight_kg IS NOT NULL
)
SELECT
  metric_date,
  ROUND(weight_kg::numeric, 3) AS weight_kg,
  ROUND(weight_lb::numeric, 2) AS weight_lb,
  ROUND(AVG(weight_lb) OVER (
    ORDER BY metric_date
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  )::numeric, 2) AS weight_lb_ma7,
  ROUND((weight_lb - LAG(weight_lb, 7) OVER (ORDER BY metric_date))::numeric, 2) AS delta_lb_vs_7d,
  ROUND((weight_lb - LAG(weight_lb, 14) OVER (ORDER BY metric_date))::numeric, 2) AS delta_lb_vs_14d
FROM w
ORDER BY metric_date;
