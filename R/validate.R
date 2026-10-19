assert_valid <- function(condition,message) {
  if (!isTRUE(condition)) stop(message,call.=FALSE)
}
validate_config <- function(cfg) {
  assert_valid(cfg$horizon==168L,'This model uses a seven-day hourly horizon; horizon must be 168.')
  assert_valid(cfg$history_days*24L>=max(cfg$test_origins)+cfg$horizon,'History does not cover the held-out windows.')
  assert_valid(max(cfg$selection_origins)+cfg$horizon<=min(cfg$calibration_origins),'Selection and calibration windows overlap.')
  assert_valid(max(cfg$calibration_origins)+cfg$horizon<=min(cfg$test_origins),'Calibration and test windows overlap.')
  assert_valid(length(cfg$queues)==length(cfg$hourly_base) && length(cfg$queues)==length(cfg$handling_base),'Queue configuration lengths differ.')
  assert_valid(is.finite(cfg$occupancy) && cfg$occupancy>0 && cfg$occupancy<=1,'Occupancy must be in (0,1].')
  assert_valid(is.finite(cfg$shrinkage) && cfg$shrinkage>=0 && cfg$shrinkage<1,'Shrinkage must be in [0,1).')
  assert_valid(cfg$interval_level>0 && cfg$interval_level<1,'Interval level must be between zero and one.')
  invisible(TRUE)
}
validate_inputs <- function(tickets,schedule,future,cfg) {
  validate_config(cfg)
  checks <- list(
    unique_ticket_ids=uniqueN(tickets$ticket_id)==nrow(tickets),
    nonmissing_ticket_ids=!anyNA(tickets$ticket_id),
    valid_ticket_queues=all(tickets$queue %in% cfg$queues),
    complete_ticket_fields=!anyNA(tickets),
    positive_finite_handling=all(is.finite(tickets$handling_minutes) & tickets$handling_minutes>0),
    tickets_inside_history=all(tickets$arrived_at>=cfg$start & tickets$arrived_at<cfg$start+cfg$history_days*86400),
    unique_schedule_key=uniqueN(schedule,by=c('timestamp','queue'))==nrow(schedule),
    schedule_full_size=nrow(schedule)==cfg$history_days*24L*length(cfg$queues),
    complete_schedule_fields=!anyNA(schedule),
    valid_schedule_queues=setequal(schedule$queue,cfg$queues),
    nonnegative_integer_headcount=all(is.finite(schedule$scheduled_agents) & schedule$scheduled_agents>=0 & schedule$scheduled_agents==floor(schedule$scheduled_agents)),
    unique_future_key=uniqueN(future,by=c('timestamp','queue'))==nrow(future),
    future_full_size=nrow(future)==cfg$horizon*length(cfg$queues),
    complete_future_fields=!anyNA(future),
    valid_future_queues=setequal(future$queue,cfg$queues),
    future_headcount=all(is.finite(future$scheduled_agents) & future$scheduled_agents>=0 & future$scheduled_agents==floor(future$scheduled_agents))
  )
  expected <- seq(cfg$start,by='hour',length.out=cfg$history_days*24L)
  expected_future <- max(expected)+seq_len(cfg$horizon)*3600
  checks$schedule_hour_grid <- all(vapply(cfg$queues,function(q) identical(as.numeric(sort(schedule[queue==q,timestamp])),as.numeric(expected)),logical(1)))
  checks$future_hour_grid <- all(vapply(cfg$queues,function(q) identical(as.numeric(sort(future[queue==q,timestamp])),as.numeric(expected_future)),logical(1)))
  out <- data.table(check=names(checks),passed=unlist(checks))
  fwrite(out,'outputs/data_quality.csv')
  if (any(!out$passed)) stop('Data validation failed: ',paste(out[passed==FALSE,check],collapse=', '))
  out
}
validate_forecast <- function(fc,cfg) {
  required <- c('timestamp','queue','prediction','lower','upper')
  assert_valid(all(required %in% names(fc)),'Forecast columns are missing.')
  assert_valid(nrow(fc)==cfg$horizon*length(cfg$queues),'Not enough forecast rows for a staffing decision.')
  assert_valid(uniqueN(fc,by=c('timestamp','queue'))==nrow(fc),'Duplicate forecast hours.')
  assert_valid(setequal(fc$queue,cfg$queues),'A required queue is missing.')
  assert_valid(!anyNA(fc[,..required]),'Missing forecast values: cannot produce a staffing recommendation.')
  assert_valid(all(is.finite(fc$prediction)&is.finite(fc$lower)&is.finite(fc$upper)),'Nonfinite forecast values.')
  assert_valid(all(fc$lower>=0 & fc$lower<=fc$prediction & fc$prediction<=fc$upper),'Invalid forecast bounds.')
  expected <- cfg$start+cfg$history_days*86400+(seq_len(cfg$horizon)-1)*3600
  assert_valid(all(vapply(cfg$queues,function(q) identical(as.numeric(sort(fc[queue==q,timestamp])),as.numeric(expected)),logical(1))),'Forecast hours are missing or shifted.')
  invisible(TRUE)
}
