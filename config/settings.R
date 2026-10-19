# All thresholds are portfolio assumptions, not Uber operating targets.
settings <- list(
  seed = 19062026L,
  start = as.POSIXct('2026-01-05 00:00:00', tz = 'UTC'),
  history_days = 182L,
  horizon = 168L,
  queues = c('Fare questions', 'Payment issues', 'Account support'),
  hourly_base = c(55, 35, 25),
  handling_base = c(9, 13, 17),
  occupancy = 0.85,
  shrinkage = 0.25,
  interval_level = 0.90,
  selection_origins = c(18L, 19L, 20L) * 168L,
  calibration_origins = c(21L, 22L) * 168L,
  test_origins = c(23L, 24L, 25L) * 168L,
  backlog_clearance_hours = 72L
)
