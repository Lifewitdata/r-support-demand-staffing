generate_inputs <- function(cfg) {
  set.seed(cfg$seed)
  # seq() can return integer-backed POSIXct, which fwrite exports as epoch seconds.
  timestamps <- .POSIXct(as.double(seq(cfg$start, by='hour', length.out=cfg$history_days*24L)), tz='UTC')
  grid <- CJ(hour_index=seq_along(timestamps), queue=cfg$queues, sorted=TRUE)
  grid[, timestamp := timestamps[hour_index]]
  grid[, `:=`(hour=as.integer(format(timestamp,'%H',tz='UTC')),
              dow=as.integer(format(timestamp,'%u',tz='UTC')),
              day=(hour_index-1L)%/%24L)]
  grid[, queue_id := match(queue,cfg$queues)]
  # Nonlinear daily peaks, weekly seasonality, gradual growth and isolated shocks.
  grid[, shape := 0.42 + 0.90*exp(-((hour-12)/4)^2) + 0.62*exp(-((hour-20)/3)^2)]
  grid[, weekend := ifelse(dow>=6, 1.20, 1)]
  grid[, incident := ifelse(queue=='Payment issues' & day %in% 130:132,1.75,1)]
  grid[, lambda := cfg$hourly_base[queue_id]*shape*weekend*exp(0.0014*day)*incident]
  grid[, arrivals := rnbinom(.N,mu=lambda,size=40)]
  owner <- rep(seq_len(nrow(grid)),grid$arrivals)
  tickets <- data.table(ticket_id=seq_along(owner), queue=grid$queue[owner],
                        arrived_at=grid$timestamp[owner]+runif(length(owner),0,3599))
  # A recent increase in handling work is separate from arrival demand.
  aht <- cfg$handling_base[grid$queue_id[owner]] *
    ifelse(grid$queue[owner]=='Payment issues' & grid$day[owner]>=168,1.28,1)
  tickets[, handling_minutes := round(rgamma(.N,shape=4,scale=aht/4),3)]
  # A planned calendar profile includes anticipated growth and an 8% reserve, not realised demand.
  grid[, scheduled_agents := pmax(1L,as.integer(ceiling(
    cfg$hourly_base[queue_id]*shape*weekend*exp(0.0014*day)*1.08*cfg$handling_base[queue_id]/
      (60*(1-cfg$shrinkage)*cfg$occupancy))))]
  grid[hour %in% 18:21 & dow<=5, scheduled_agents := pmax(1L,scheduled_agents-2L)]
  schedule <- grid[,.(timestamp,queue,scheduled_agents)]
  future_times <- seq(max(timestamps)+3600,by='hour',length.out=cfg$horizon)
  future <- copy(tail(schedule[order(timestamp,queue)],cfg$horizon*length(cfg$queues)))
  future[, timestamp := timestamp+cfg$horizon*3600]
  # This is a proposed paid-headcount schedule, not an optimisation output.
  dir.create('data/raw',recursive=TRUE,showWarnings=FALSE)
  saveRDS(tickets,'data/raw/tickets.rds',compress='gzip')
  saveRDS(schedule,'data/raw/hourly_schedule.rds',compress='gzip')
  fwrite(future,'data/raw/future_schedule.csv')
  fwrite(tickets[seq_len(min(.N,1000L))],'data/raw/ticket_sample.csv')
  invisible(list(tickets=tickets,schedule=schedule,future=future))
}
