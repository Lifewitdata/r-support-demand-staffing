staffing_plan <- function(fc,future,hourly,cfg,demand_multiplier=1,aht_multiplier=1,
                          shrinkage=cfg$shrinkage,occupancy=cfg$occupancy,
                          basis='prediction',extra_agents=0L,clearance_hours=cfg$backlog_clearance_hours) {
  validate_forecast(fc,cfg)
  assert_valid(basis %in% c('prediction','upper'),'Select the central forecast or upper planning scenario.')
  assert_valid(all(is.finite(c(demand_multiplier,aht_multiplier,shrinkage,occupancy,extra_agents,clearance_hours))), 'Scenario inputs must be finite.')
  assert_valid(demand_multiplier>=0 && aht_multiplier>0,'Demand must be nonnegative and handling time positive.')
  assert_valid(shrinkage>=0 && shrinkage<1 && occupancy>0 && occupancy<=1,'Invalid shrinkage or occupancy.')
  assert_valid(extra_agents>=0 && extra_agents==floor(extra_agents) && clearance_hours>0,'Invalid staffing or backlog-clearance input.')
  assert_valid(uniqueN(future,by=c('timestamp','queue'))==nrow(future),'Duplicate scheduled hours.')
  plan <- merge(fc,future,by=c('timestamp','queue'),all.x=TRUE)
  assert_valid(nrow(plan)==nrow(fc) && !anyNA(plan$scheduled_agents),'Scheduled headcount missing: cannot make a staffing recommendation.')
  assert_valid(all(is.finite(plan$scheduled_agents)&plan$scheduled_agents>=0&plan$scheduled_agents==floor(plan$scheduled_agents)),'Scheduled headcount must be finite, nonnegative integers.')
  aht <- hourly[timestamp>max(timestamp)-28*86400,.(aht_minutes=sum(workload_minutes)/sum(arrivals)),by=queue]
  backlog <- hourly[order(timestamp),.(initial_backlog=tail(backlog_end,1)),by=queue]
  plan <- merge(merge(plan,aht,by='queue'),backlog,by='queue')
  assert_valid(!anyNA(plan$aht_minutes) && all(is.finite(plan$aht_minutes)) && all(plan$aht_minutes>0),'Historical handling-time inputs are missing or invalid.')
  plan[, `:=`(planned_arrivals=get(basis)*demand_multiplier,aht_minutes=aht_minutes*aht_multiplier,
              scheduled_agents=scheduled_agents+extra_agents)]
  setorder(plan,queue,timestamp)
  plan[, horizon_hour:=seq_len(.N),by=queue]
  # Allocate opening workload evenly over the requested clearance period.
  plan[, backlog_allocation:=initial_backlog*pmax(0,pmin(horizon_hour,clearance_hours)-pmin(horizon_hour-1,clearance_hours))/clearance_hours]
  plan[, demand_workload_minutes:=planned_arrivals*aht_minutes]
  plan[, required_workload_minutes:=demand_workload_minutes+backlog_allocation]
  unit_capacity <- 60*(1-shrinkage)*occupancy
  plan[, `:=`(required_agents=ceiling(required_workload_minutes/unit_capacity),
              capacity_minutes=scheduled_agents*unit_capacity)]
  plan[, staffing_gap:=pmax(0,required_agents-scheduled_agents)]
  plan[, c('projected_backlog_start','projected_backlog_end'):=flow_backlog(demand_workload_minutes,capacity_minutes,initial=initial_backlog[1]),by=queue]
  plan[, `:=`(planning_basis=basis,demand_multiplier=demand_multiplier,aht_multiplier=aht_multiplier,
              shrinkage_assumption=shrinkage,occupancy_assumption=occupancy)]
  plan
}
plan_summary <- function(plan) {
  plan[,.(forecast_arrivals=sum(planned_arrivals),required_paid_agent_hours=sum(required_agents),
    scheduled_paid_agent_hours=sum(scheduled_agents),uncovered_agent_hours=sum(staffing_gap),
    hours_with_gap=sum(staffing_gap>0),peak_gap=max(staffing_gap),
    opening_backlog_hours=initial_backlog[1]/60,ending_backlog_hours=tail(projected_backlog_end,1)/60),by=queue]
}
