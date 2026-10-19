# Meaningful boundary and integration checks, using base R and shiny::testServer.
source('R/load.R')
library(shiny)
source('R/app_logic.R')
results <- list()
check <- function(name,expr) {
  error <- tryCatch({force(expr);NULL},error=function(e)conditionMessage(e))
  results[[length(results)+1L]] <<- data.table(test=name,passed=is.null(error),message=if(is.null(error))'OK' else error)
  cat(if(is.null(error))'PASS' else 'FAIL',name,'\n')
}
expect_error <- function(expr) {
  failed <- tryCatch({force(expr);FALSE},error=function(e)TRUE)
  stopifnot(failed)
}
d <- readRDS('data/processed/app_bundle.rds')
fc <- d$forecast$future_forecast
base <- staffing_plan(fc,d$future_schedule,d$hourly,settings)
check('Source checks all pass',stopifnot(all(d$quality$passed)))
check('Hourly ticket counts reconcile',stopifnot(sum(d$hourly$arrivals)==nrow(readRDS('data/raw/tickets.rds'))))
check('Hourly grid has zero-filled hours',stopifnot(nrow(d$hourly)==settings$history_days*24*length(settings$queues)))
check('Simple backlog flow conserves workload',{
  b <- flow_backlog(c(100,10,0),c(40,40,40));stopifnot(identical(b$end,c(60,30,0)))
})
check('Opening backlog is carried forward',stopifnot(flow_backlog(c(0,0),c(5,5),12)$end[2]==2))
check('Negative capacity is rejected',expect_error(flow_backlog(1,-1)))
check('Weekly baseline repeats only the last week',{
  y <- as.numeric(1:504);stopifnot(identical(forecast_one(y,168,'weekly_naive'),tail(y,168)))
})
check('Known accuracy example is correct',{
  m <- accuracy_metrics(c(10,20),c(12,18));stopifnot(m['MAE']==2,abs(m['WAPE']-4/30)<1e-12,m['bias']==0)
})
check('All held-out predictions follow training',stopifnot(all(d$forecast$holdout_predictions$timestamp>d$forecast$holdout_predictions$train_end)))
check('Model choice follows earlier validation scores',{
  choices <- d$forecast$selection_scores[order(queue,WAPE,method),.SD[1],by=queue][,.(queue,method)]
  stopifnot(nrow(choices)==nrow(d$forecast$model_choices), all(choices$method==d$forecast$model_choices$method[match(choices$queue,d$forecast$model_choices$queue)]))
})
check('Calibration is earlier than the held-out windows',stopifnot(max(settings$calibration_origins)+settings$horizon<=min(settings$test_origins)))
check('Missing forecast queue blocks recommendations',expect_error(staffing_plan(fc[queue!=settings$queues[1]],d$future_schedule,d$hourly,settings)))
check('Missing forecast value blocks recommendations',{
  bad <- copy(fc);bad[1,prediction:=NA_real_];expect_error(staffing_plan(bad,d$future_schedule,d$hourly,settings))
})
check('Invalid forecast interval is rejected',{
  bad <- copy(fc);bad[1,lower:=upper+1];expect_error(validate_forecast(bad,settings))
})
check('Missing scheduled hour blocks recommendations',expect_error(staffing_plan(fc,d$future_schedule[-1],d$hourly,settings)))
check('Zero occupancy cannot produce an answer',expect_error(staffing_plan(fc,d$future_schedule,d$hourly,settings,occupancy=0)))
check('Higher demand cannot reduce required capacity',{
  high <- staffing_plan(fc,d$future_schedule,d$hourly,settings,demand_multiplier=1.2)
  stopifnot(all(high$required_agents>=base$required_agents))
})
check('Longer handling cannot reduce required capacity',{
  high <- staffing_plan(fc,d$future_schedule,d$hourly,settings,aht_multiplier=1.2)
  stopifnot(all(high$required_agents>=base$required_agents))
})
check('Greater shrinkage cannot reduce required capacity',{
  high <- staffing_plan(fc,d$future_schedule,d$hourly,settings,shrinkage=.4)
  stopifnot(all(high$required_agents>=base$required_agents))
})
check('Extra staff cannot increase end backlog',{
  high <- staffing_plan(fc,d$future_schedule,d$hourly,settings,extra_agents=5)
  stopifnot(all(high$projected_backlog_end<=base$projected_backlog_end))
})
check('Upper demand scenario is no smaller than central',{
  high <- staffing_plan(fc,d$future_schedule,d$hourly,settings,basis='upper')
  stopifnot(all(high$required_agents>=base$required_agents))
})
check('Backlog allocation equals opening workload',{
  b <- base[,.(allocated=sum(backlog_allocation),opening=initial_backlog[1]),by=queue]
  stopifnot(all(abs(b$allocated-b$opening)<1e-6))
})
check('Workload decomposition reconciles exactly',{
  x <- workload_decomposition(d$hourly)
  stopifnot(all(abs(x$demand_contribution+x$handling_contribution-x$workload_change)<1e-6))
})
check('Report wording handles increases and decreases',{
  stopifnot(grepl('increased',change_phrase(2,'hours')),grepl('decreased',change_phrase(-2,'hours')))
})
check('CSV exports write ISO timestamps, not epoch seconds',{
  for(f in c('outputs/hourly_operations.csv','outputs/holdout_predictions.csv','data/raw/future_schedule.csv'))
    stopifnot(grepl('^\\d{4}-\\d{2}-\\d{2}T',fread(f,nrows=1,colClasses=list(character='timestamp'))$timestamp))
})
check('HTML report keeps its head and charset',{
  html <- paste(readLines('outputs/weekly_report.html',encoding='UTF-8'),collapse='\n')
  stopifnot(grepl('<meta charset="utf-8"',html,fixed=TRUE),grepl('<title>',html,fixed=TRUE),grepl('<style>',html,fixed=TRUE))
})
check('Shiny queue selection and scenario controls update',{
  testServer(make_server(d),{
    session$setInputs(queue='All queues',dates=c(as.Date(max(d$hourly$timestamp))-27,as.Date(max(d$hourly$timestamp))),
      demand=100,handling=100,shrinkage=25,occupancy=85,basis='prediction',extra_agents=0,clearance='24')
    stopifnot(nrow(forecast_data())==504,nrow(selected_plan())==504)
    gap <- sum(selected_plan()$staffing_gap)
    session$setInputs(demand=120)
    stopifnot(sum(selected_plan()$staffing_gap)>=gap)
    session$setInputs(queue=settings$queues[1])
    stopifnot(nrow(selected_plan())==168,nrow(forecast_data())==168)
    session$setInputs(shrinkage=0,extra_agents=0)
    stopifnot(nrow(selected_plan())==168)
    # Force table/UI renderers as well as reactives.
    stopifnot(!is.null(output$overview_kpis),!is.null(output$forecast_accuracy),
              !is.null(output$coverage_table),!is.null(output$staffing_summary),
              !is.null(output$drivers_table),!is.null(output$quality_table),!is.null(output$deep_dive_note), !is.null(output$daily_demand),!is.null(output$weekly_pattern),!is.null(output$forecast_plot),!is.null(output$staffing_plot),!is.null(output$drivers_plot))
  })
})
check("Root app loads without starting a server", {
  application <- source("app.R")$value
  stopifnot(inherits(application,"shiny.appobj"))
})
result <- rbindlist(results)
fwrite(result,'outputs/test_results.csv')
cat(sprintf('\n%d of %d checks passed.\n',sum(result$passed),nrow(result)))
if(any(!result$passed)) stop('Tests failed; see outputs/test_results.csv')
