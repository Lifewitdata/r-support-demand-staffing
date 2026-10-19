features <- function(index) {
  data <- data.frame(t_day=(index-1)/24,dow=factor(((index-1)%/%24)%%7+1,levels=1:7))
  for(k in 1:3) {
    data[[paste0('sin',k)]] <- sin(2*pi*k*((index-1)%%24)/24)
    data[[paste0('cos',k)]] <- cos(2*pi*k*((index-1)%%24)/24)
  }
  data
}
forecast_one <- function(y,h,method) {
  assert_valid(length(y)>=336 && all(is.finite(y)) && all(y>=0),'Forecasting needs at least two complete weeks of valid demand.')
  assert_valid(h==168L,'Only seven-day hourly forecasts are supported.')
  if (method=='weekly_naive') return(as.numeric(tail(y,168L)))
  assert_valid(method=='seasonal_glm','Unknown forecasting method.')
  train <- features(seq_along(y));train$y <- y
  fit <- glm(y~.,data=train,family=quasipoisson(link='log'),control=glm.control(maxit=40))
  assert_valid(fit$converged,'Seasonal regression did not converge.')
  pred <- as.numeric(predict(fit,newdata=features(length(y)+seq_len(h)),type='response'))
  assert_valid(all(is.finite(pred)),'Forecast model returned invalid predictions.')
  pmax(0,pred)
}
accuracy_metrics <- function(actual,prediction) {
  assert_valid(length(actual)==length(prediction) && length(actual)>0,'Invalid accuracy inputs.')
  assert_valid(all(is.finite(c(actual,prediction))) && all(actual>=0),'Invalid accuracy values.')
  c(MAE=mean(abs(actual-prediction)),RMSE=sqrt(mean((actual-prediction)^2)),
    WAPE=if(sum(actual)>0) sum(abs(actual-prediction))/sum(actual) else NA_real_,
    bias=mean(prediction-actual))
}
rolling_predictions <- function(hourly,origins,methods,cfg) {
  rows <- list();j <- 0L
  for(q in cfg$queues) {
    series <- hourly[queue==q][order(timestamp)]
    for(origin in origins) for(method in methods) {
      assert_valid(origin+cfg$horizon<=nrow(series),'Origin extends past available observations.')
      pred <- forecast_one(series$arrivals[seq_len(origin)],cfg$horizon,method)
      idx <- origin+seq_len(cfg$horizon)
      j <- j+1L
      rows[[j]] <- data.table(queue=q,origin=origin,method=method,timestamp=series$timestamp[idx],
        actual=series$arrivals[idx],prediction=pred,train_end=series$timestamp[origin])
    }
  }
  rbindlist(rows)
}
calibration_radius <- function(actual,prediction,level) {
  # Scale residuals for count-dependent variance. Dependence prevents a formal coverage guarantee.
  scores <- abs(actual-prediction)/sqrt(pmax(prediction,1))
  assert_valid(length(scores)>=168 && all(is.finite(scores)),'Insufficient valid calibration residuals.')
  sort(scores)[min(length(scores),ceiling((length(scores)+1)*level))]
}
run_forecasts <- function(hourly,cfg) {
  selection <- rolling_predictions(hourly,cfg$selection_origins,c('weekly_naive','seasonal_glm'),cfg)
  scores <- selection[,as.list(accuracy_metrics(actual,prediction)),by=.(queue,method)]
  choices <- scores[order(queue,WAPE,method),.SD[1],by=queue][,.(queue,method)]
  calibration <- rolling_predictions(hourly,cfg$calibration_origins,c('weekly_naive','seasonal_glm'),cfg)
  calibration <- merge(calibration,choices,by=c('queue','method'))
  radii <- calibration[,.(radius=calibration_radius(actual,prediction,cfg$interval_level)),by=.(queue,method)]
  # All candidate models are evaluated for transparency; selection stays frozen.
  holdout <- rolling_predictions(hourly,cfg$test_origins,c('weekly_naive','seasonal_glm'),cfg)
  holdout_scores <- holdout[,as.list(accuracy_metrics(actual,prediction)),by=.(queue,method)]
  chosen_test <- merge(merge(holdout,choices,by=c('queue','method')),radii,by=c('queue','method'))
  chosen_test[, `:=`(lower=pmax(0,prediction-radius*sqrt(pmax(prediction,1))),upper=prediction+radius*sqrt(pmax(prediction,1)))]
  coverage <- chosen_test[,.(coverage=mean(actual>=lower & actual<=upper),mean_width=mean(upper-lower)),by=.(queue,method)]
  final <- rbindlist(lapply(cfg$queues,function(q) {
    s <- hourly[queue==q][order(timestamp)]
    method <- choices[queue==q,method]
    pred <- forecast_one(s$arrivals,cfg$horizon,method)
    radius <- radii[queue==q,radius]
    data.table(timestamp=max(s$timestamp)+seq_len(cfg$horizon)*3600,queue=q,method=method,
      prediction=pred,lower=pmax(0,pred-radius*sqrt(pmax(pred,1))),upper=pred+radius*sqrt(pmax(pred,1)))
  }))
  validate_forecast(final,cfg)
  outputs <- list(selection_scores=scores,model_choices=choices,holdout_scores=holdout_scores,
    interval_coverage=coverage,calibration=radii,holdout_predictions=chosen_test,future_forecast=final)
  for(name in names(outputs)) fwrite(outputs[[name]],file.path('outputs',paste0(name,'.csv')))
  saveRDS(outputs,'data/processed/forecast_bundle.rds')
  outputs
}
