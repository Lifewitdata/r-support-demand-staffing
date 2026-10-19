flow_backlog <- function(workload,capacity,initial=0) {
  assert_valid(length(workload)==length(capacity),'Workload and capacity lengths differ.')
  assert_valid(all(is.finite(c(workload,capacity,initial))) && all(c(workload,capacity,initial)>=0),'Workload, capacity and backlog must be finite and nonnegative.')
  start <- end <- numeric(length(workload));carry <- initial
  for(i in seq_along(workload)) {
    start[i] <- carry
    carry <- max(0,carry+workload[i]-capacity[i])
    end[i] <- carry
  }
  list(start=start,end=end)
}
prepare_hourly <- function(tickets,schedule,cfg) {
  tx <- copy(tickets)
  tx[, timestamp := as.POSIXct(floor(as.numeric(arrived_at)/3600)*3600,origin='1970-01-01',tz='UTC')]
  agg <- tx[,.(arrivals=.N,workload_minutes=sum(handling_minutes)),by=.(timestamp,queue)]
  hourly <- merge(schedule,agg,by=c('timestamp','queue'),all.x=TRUE,sort=TRUE)
  hourly[is.na(arrivals),`:=`(arrivals=0L,workload_minutes=0)]
  hourly[, capacity_minutes := scheduled_agents*60*(1-cfg$shrinkage)*cfg$occupancy]
  hourly[, aht_minutes := fifelse(arrivals>0,workload_minutes/pmax(arrivals,1),NA_real_)]
  setorder(hourly,queue,timestamp)
  hourly[, c('backlog_start','backlog_end') := flow_backlog(workload_minutes,capacity_minutes),by=queue]
  hourly[, `:=`(hour_index=as.integer(difftime(timestamp,cfg$start,units='hours'))+1L,
                hour=as.integer(format(timestamp,'%H',tz='UTC')),
                dow=as.integer(format(timestamp,'%u',tz='UTC')))]
  assert_valid(sum(hourly$arrivals)==nrow(tickets),'Hourly arrivals do not reconcile to ticket count.')
  assert_valid(abs(sum(hourly$workload_minutes)-sum(tickets$handling_minutes))<1e-6,'Handling minutes do not reconcile.')
  saveRDS(hourly,'data/processed/hourly_operations.rds')
  fwrite(hourly,'outputs/hourly_operations.csv')
  hourly
}
workload_decomposition <- function(hourly) {
  end <- max(hourly$timestamp)
  current <- hourly[timestamp>end-7*86400,.(n=sum(arrivals),work=sum(workload_minutes),capacity=sum(capacity_minutes)),by=queue]
  previous <- hourly[timestamp<=end-7*86400 & timestamp>end-35*86400,.(n0=sum(arrivals)/4,work0=sum(workload_minutes)/4,capacity0=sum(capacity_minutes)/4),by=queue]
  d <- merge(current,previous,by='queue')
  assert_valid(all(d$n>0 & d$n0>0),'Workload decomposition needs arrivals in both periods.')
  d[, `:=`(aht=work/n,aht0=work0/n0)]
  d[, `:=`(demand_contribution=(n-n0)*(aht+aht0)/2,
           handling_contribution=(aht-aht0)*(n+n0)/2,
           workload_change=work-work0,capacity_change=capacity-capacity0)]
  assert_valid(all(abs(d$demand_contribution+d$handling_contribution-d$workload_change)<1e-6),'Workload decomposition does not reconcile.')
  d
}
