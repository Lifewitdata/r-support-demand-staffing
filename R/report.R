metric_label <- function(x,digits=1) format(round(x,digits),big.mark=',',trim=TRUE,scientific=FALSE)
change_phrase <- function(x,unit) {
  if(abs(x)<1e-8) paste('was unchanged in',unit) else paste(if(x>0) 'increased by' else 'decreased by',metric_label(abs(x)),unit)
}
write_reports <- function(hourly,bundle,plan,quality,cfg) {
  decomposition <- workload_decomposition(hourly)
  fwrite(decomposition,'outputs/workload_deep_dive.csv')
  summary <- plan_summary(plan)
  fwrite(summary,'outputs/staffing_summary.csv')
  fwrite(plan,'outputs/staffing_plan.csv')
  selected_scores <- merge(bundle$holdout_scores,bundle$model_choices,by=c('queue','method'))
  latest <- hourly[timestamp>max(timestamp)-14*86400,.(arrivals=sum(arrivals)),by=.(date=as.Date(timestamp,tz='UTC'),queue)]
  theme <- theme_minimal(base_size=12)+theme(panel.grid.minor=element_blank(),plot.title=element_text(face='bold'))
  g1 <- ggplot(latest,aes(date,arrivals,color=queue))+geom_line(linewidth=.7)+labs(title='Recent support demand',x=NULL,y='Tickets per day',color=NULL)+theme
  ggsave('outputs/figures/recent_demand.png',g1,width=10,height=4.5,dpi=150)
  fc <- bundle$future_forecast
  history <- hourly[timestamp>max(timestamp)-7*86400]
  g2 <- ggplot()+geom_line(data=history,aes(timestamp,arrivals),color='#64748b',linewidth=.35)+
    geom_ribbon(data=fc,aes(timestamp,ymin=lower,ymax=upper),fill='#0f766e',alpha=.16)+
    geom_line(data=fc,aes(timestamp,prediction),color='#0f766e',linewidth=.5)+facet_wrap(~queue,ncol=1,scales='free_y')+
    labs(title='Next week: forecast and empirical uncertainty band',subtitle=sprintf('Band target: %.0f%%; assess held-out coverage before using it',100*cfg$interval_level),x=NULL,y='Hourly tickets')+theme
  ggsave('outputs/figures/forecast.png',g2,width=11,height=8,dpi=140)
  g3 <- ggplot(plan,aes(timestamp,staffing_gap,fill=queue))+geom_col(width=3600)+facet_wrap(~queue,ncol=1,scales='free_y')+
    scale_y_continuous(breaks=function(l) unique(floor(pretty(l))))+
    labs(title='Where the proposed schedule is short',subtitle='Central-demand scenario, including opening workload backlog',x=NULL,y='Additional concurrent agents')+theme+theme(legend.position='none')
  ggsave('outputs/figures/staffing_gap.png',g3,width=11,height=7,dpi=140)
  contribution <- melt(decomposition[,.(queue,demand_contribution,handling_contribution)],id.vars='queue',variable.name='driver',value.name='minutes')
  g4 <- ggplot(contribution,aes(queue,minutes/60,fill=driver))+geom_col(position='dodge')+
    scale_fill_manual(values=c('#0f766e','#e89b32'),labels=c('Ticket volume','Handling time'))+
    labs(title='Why workload changed',subtitle='Latest week versus the previous four-week average; descriptive decomposition',x=NULL,y='Change in workload hours',fill=NULL)+theme
  ggsave('outputs/figures/workload_drivers.png',g4,width=10,height=5,dpi=150)
  total_gap <- sum(summary$uncovered_agent_hours)
  priority <- summary[order(-uncovered_agent_hours),queue][1]
  action <- if(total_gap>0) paste('Review capacity in',priority,'first; the current scenario has uncovered workload.') else 'The proposed schedule covers the central scenario; examine the upper-demand scenario before reducing staffing.'
  queue_lines <- vapply(seq_len(nrow(summary)),function(i) {
    s <- summary[i];score <- selected_scores[queue==s$queue];coverage <- bundle$interval_coverage[queue==s$queue]
    sprintf('- **%s:** %s forecast tickets; %s uncovered paid agent-hours across %d hours. Held-out WAPE %.1f%%; empirical band coverage %.1f%%.',
      s$queue,metric_label(s$forecast_arrivals,0),metric_label(s$uncovered_agent_hours,0),s$hours_with_gap,100*score$WAPE,100*coverage$coverage)
  },character(1))
  drivers <- vapply(seq_len(nrow(decomposition)),function(i) {
    d <- decomposition[i]
    sprintf('- **%s:** workload %s. Volume contributed %+.1f hours and handling time %+.1f hours; scheduled capacity changed by %+.1f hours.',
      d$queue,change_phrase(d$workload_change/60,'hours'),d$demand_contribution/60,d$handling_contribution/60,d$capacity_change/60)
  },character(1))
  brief <- c('# Weekly support capacity brief','', '**Synthetic portfolio scenario. No Uber data or operational claims.**','',
    paste('Forecast window:',format(min(fc$timestamp),'%d %b %Y %H:%M',tz='UTC'),'to',format(max(fc$timestamp),'%d %b %Y %H:%M',tz='UTC'),'UTC.'),'',
    '## Decision',action,'',queue_lines,'','## What explains the recent workload change',drivers,'',
    'The decomposition separates arithmetic contributions from ticket volume and handling time. It does not establish why handling time changed or prove a process caused the increase. Review case complexity, escalations and workflow changes before choosing an intervention.','',
    '## How to use the staffing estimate',
    sprintf('The default scenario assumes %.0f%% shrinkage, %.0f%% productive occupancy and the last 28 days of weighted handling time. Opening workload backlog is allocated over %d hours. Change these assumptions in Shiny before making a staffing request.',100*cfg$shrinkage,100*cfg$occupancy,cfg$backlog_clearance_hours),
    'Uncovered paid agent-hours are the sum of hourly staffing gaps. They are not the number of people to hire. Shift patterns, skills, breaks and labour rules still need scheduling decisions.',
    'This is a fluid workload model. It does not predict an SLA or a customer wait-time distribution. The upper-band scenario is a stress test, not a joint guarantee that all future hours will be covered.','',
    '## Forecast checks',
    'Model choice uses three earlier rolling validation weeks. Two later weeks calibrate empirical bands. Three final weeks evaluate performance after the choice is frozen. Models refit at each weekly origin using only earlier observations. The production forecast then refits on all available history.',
    'A weekly seasonal naive forecast is retained as a benchmark. The alternative is quasi-Poisson seasonal regression with daily Fourier terms, weekday effects and a linear trend. Unplanned incidents and long-term trend changes remain risks.','',
    '## Next actions',
    '1. Review the highest-gap queue and the hour-of-day pattern with the operations lead.',
    '2. Compare added peak-hour staffing with a plausible handling-time improvement. Do not call a scenario a realised saving.',
    '3. Confirm proposed schedules and skill coverage; investigate the operational cause of any handling-time increase.',
    '4. Re-run weekly with fresh data and track forecast errors and empirical coverage before relying on the intervals.','',
    sprintf('Data checks: %d of %d passed. Historical tickets: %s. Historical queue-hours: %s.',sum(quality$passed),nrow(quality),metric_label(sum(hourly$arrivals),0),metric_label(nrow(hourly),0)))
  writeLines(brief,'outputs/weekly_brief.md')
  # A standalone HTML report needs no Python, Pandoc, Quarto or online service.
  tbl <- function(d) htmltools::tags$table(class='table',
    htmltools::tags$thead(htmltools::tags$tr(lapply(names(d),htmltools::tags$th))),
    htmltools::tags$tbody(lapply(seq_len(nrow(d)),function(i) htmltools::tags$tr(lapply(d[i],function(x)htmltools::tags$td(as.character(x)))))))
  score_view <- copy(selected_scores)[,.(Queue=queue,Model=method,MAE=round(MAE,2),WAPE_percent=round(WAPE*100,1),Bias=round(bias,2))]
  html <- htmltools::tagList(htmltools::tags$head(htmltools::tags$title('Weekly support capacity brief'),
    htmltools::tags$style('body{font:16px system-ui;color:#243247;max-width:1100px;margin:40px auto;padding:20px;background:#f8fafc}h1{font-size:38px}h2{margin-top:32px}img{width:100%;background:white;border-radius:12px;margin:16px 0}table{border-collapse:collapse;width:100%;background:white}th,td{padding:12px;text-align:left;border-bottom:1px solid #ddd}pre{white-space:pre-wrap;font:15px/1.7 system-ui}.notice{color:#0f766e}')),
    htmltools::tags$p(class='notice','INDEPENDENT PORTFOLIO PROJECT \u00b7 SYNTHETIC DATA'),
      htmltools::tags$h1('Support demand & staffing'),htmltools::tags$p(action),
      htmltools::tags$h2('Forecast performance on later weeks'),tbl(score_view),
      htmltools::tags$img(src='figures/forecast.png'),htmltools::tags$img(src='figures/staffing_gap.png'),
      htmltools::tags$img(src='figures/workload_drivers.png'),
      htmltools::tags$h2('Decision notes'),htmltools::tags$pre(paste(brief,collapse='\n')))
  # save_html keeps tags$head and declares UTF-8; as.character() silently drops the head.
  htmltools::save_html(html,'outputs/weekly_report.html',background='#f8fafc')
  invisible(summary)
}
