# Use an explicit scalar name to avoid data.table column-name ambiguity.
queue_view <- function(x,selected) if (identical(selected,'All queues')) copy(x) else x[queue==selected]
card <- function(label,value,detail='') div(class='metric-card',div(class='metric-label',label),div(class='metric-value',value),div(class='metric-detail',detail))
make_server <- function(d) {
  function(input,output,session) {
    history_data <- reactive({
      req(input$queue,input$dates)
      x <- queue_view(d$hourly,input$queue)
      x[as.Date(timestamp,tz='UTC')>=as.Date(input$dates[1]) & as.Date(timestamp,tz='UTC')<=as.Date(input$dates[2])]
    })
    forecast_data <- reactive({req(input$queue);queue_view(d$forecast$future_forecast,input$queue)})
    scenario_data <- reactive({
      req(input$demand,input$handling,input$occupancy,input$basis,input$clearance,!is.null(input$shrinkage),!is.null(input$extra_agents))
      tryCatch(staffing_plan(d$forecast$future_forecast,d$future_schedule,d$hourly,d$settings,
        demand_multiplier=input$demand/100,aht_multiplier=input$handling/100,
        shrinkage=input$shrinkage/100,occupancy=input$occupancy/100,basis=input$basis,
        extra_agents=input$extra_agents,clearance_hours=as.numeric(input$clearance)),
        error=function(e){validate(need(FALSE,conditionMessage(e)))})
    })
    selected_plan <- reactive({req(input$queue);queue_view(scenario_data(),input$queue)})
    drivers <- reactive({req(input$queue);queue_view(workload_decomposition(d$hourly),input$queue)})
    clean_theme <- function() theme_minimal(base_size=12)+theme(panel.grid.minor=element_blank(),plot.title=element_text(face='bold'))
    output$overview_kpis <- renderUI({
      x <- history_data();validate(need(nrow(x)>0,'No data in this range.'))
      fluidRow(column(3,card('Tickets',metric_label(sum(x$arrivals),0),'Selected historical window')),
        column(3,card('Handling time',paste0(metric_label(sum(x$workload_minutes)/sum(x$arrivals)),' min'),'Weighted average per ticket')),
        column(3,card('Workload / capacity',paste0(metric_label(100*sum(x$workload_minutes)/sum(x$capacity_minutes)),'%'),'Above 100% means more work than capacity')),
        column(3,card('Closing workload backlog',paste0(metric_label(sum(x[order(timestamp),tail(backlog_end,1),by=queue]$V1)/60),' h'),'Modelled unserved handling work')))
    })
    output$daily_demand <- renderPlot({
      x <- history_data()[,.(tickets=sum(arrivals)),by=.(date=as.Date(timestamp,tz='UTC'),queue)]
      ggplot(x,aes(date,tickets,color=queue))+geom_line(linewidth=.8)+labs(title='Daily ticket demand',x=NULL,y='Tickets',color=NULL)+clean_theme()
    })
    output$weekly_pattern <- renderPlot({
      x <- history_data()[,.(arrivals=mean(arrivals)),by=.(hour,dow)]
      ggplot(x,aes(hour,factor(dow,levels=7:1,labels=c('Sun','Sat','Fri','Thu','Wed','Tue','Mon')),fill=arrivals))+
        geom_tile()+scale_fill_gradient(low='#ecfdf5',high='#0f766e')+
        labs(title='When each queue is busiest',subtitle='Average arrivals per queue-hour in the selected view',x='Hour of day (UTC)',y=NULL,fill='Tickets')+clean_theme()
    })
    output$overview_table <- renderTable({
      x <- history_data()[,.(Tickets=sum(arrivals),Handling_minutes=round(sum(workload_minutes)/sum(arrivals),1),
         Workload_hours=round(sum(workload_minutes)/60,1),Capacity_hours=round(sum(capacity_minutes)/60,1)),by=queue]
      as.data.frame(x)
    },striped=TRUE)
    output$forecast_plot <- renderPlot({
      f <- forecast_data();h <- queue_view(d$hourly,input$queue);h <- h[timestamp>max(timestamp)-7*86400]
      ggplot()+geom_line(data=h,aes(timestamp,arrivals),color='#94a3b8',linewidth=.4)+
        geom_ribbon(data=f,aes(timestamp,ymin=lower,ymax=upper),fill='#0f766e',alpha=.16)+
        geom_line(data=f,aes(timestamp,prediction),color='#0f766e',linewidth=.6)+
        facet_wrap(~queue,ncol=1,scales='free_y')+labs(title='One week of history and one week ahead',
          subtitle=paste0(round(100*d$settings$interval_level),'% target empirical bands; not a simultaneous guarantee'),x=NULL,y='Hourly tickets')+clean_theme()
    })
    output$forecast_accuracy <- renderTable({
      x <- merge(queue_view(d$forecast$holdout_scores,input$queue),d$forecast$model_choices,by='queue',suffixes=c('','_selected'))
      as.data.frame(x[,.(queue,Model=method,Selected=method==method_selected,MAE=round(MAE,2),WAPE_percent=round(WAPE*100,1),Bias=round(bias,2))])
    },striped=TRUE)
    output$coverage_table <- renderTable({
      x <- queue_view(d$forecast$interval_coverage,input$queue)
      as.data.frame(x[,.(queue,Model=method,Coverage_percent=round(coverage*100,1),Target_percent=d$settings$interval_level*100,Mean_band_width=round(mean_width,1))])
    },striped=TRUE)
    output$scenario_kpis <- renderUI({
      x <- plan_summary(selected_plan())
      fluidRow(column(4,card('Uncovered agent-hours',metric_label(sum(x$uncovered_agent_hours),0),'Sum of positive hourly gaps')),
        column(4,card('Peak concurrent gap',metric_label(max(x$peak_gap),0),'Largest gap within a single queue')),
        column(4,card('Ending workload backlog',paste0(metric_label(sum(x$ending_backlog_hours),0),' h'),'Unserved handling work in this scenario')))
    })
    output$staffing_plot <- renderPlot({
      x <- melt(selected_plan()[,.(timestamp,queue,scheduled_agents,required_agents)],id.vars=c('timestamp','queue'),variable.name='staffing',value.name='agents')
      ggplot(x,aes(timestamp,agents,color=staffing))+geom_step(linewidth=.6)+facet_wrap(~queue,ncol=1,scales='free_y')+
        scale_color_manual(values=c('#64748b','#0f766e'),labels=c('Scheduled','Required'))+
        labs(title='Scheduled and required paid headcount',x=NULL,y='Concurrent agents',color=NULL)+clean_theme()
    })
    output$staffing_summary <- renderTable(as.data.frame(plan_summary(selected_plan())[,lapply(.SD,function(v)if(is.numeric(v))round(v,1) else v)]),striped=TRUE)
    output$drivers_plot <- renderPlot({
      x <- melt(drivers()[,.(queue,demand_contribution,handling_contribution)],id.vars='queue',variable.name='driver',value.name='minutes')
      ggplot(x,aes(queue,minutes/60,fill=driver))+geom_col(position='dodge')+
        scale_fill_manual(values=c('#0f766e','#e89b32'),labels=c('Ticket volume','Handling time'))+
        labs(title='Change in weekly workload',x=NULL,y='Workload hours',fill=NULL)+clean_theme()
    })
    output$drivers_table <- renderTable(as.data.frame(drivers()[,.(queue,Workload_change_hours=round(workload_change/60,1),Volume_contribution_hours=round(demand_contribution/60,1),Handling_contribution_hours=round(handling_contribution/60,1),Capacity_change_hours=round(capacity_change/60,1))]),striped=TRUE)
    output$deep_dive_note <- renderUI({
      x <- drivers();j <- which.max(abs(x$workload_change));v <- x[j]
      p(paste(v$queue,'has the largest absolute workload change in this view. Review',
        if(abs(v$handling_contribution)>abs(v$demand_contribution)) 'case complexity and handling steps' else 'arrival patterns and demand drivers',
        'first. This is a follow-up hypothesis, not a causal conclusion.'))
    })
    output$quality_table <- renderTable(as.data.frame(d$quality),striped=TRUE)
    output$brief <- renderText(paste(readLines('outputs/weekly_brief.md'),collapse='\n'))
    output$download_forecast <- downloadHandler(filename=function()'support_forecast.csv',content=function(file)fwrite(forecast_data(),file))
    output$download_plan <- downloadHandler(filename=function()'staffing_scenario.csv',content=function(file)fwrite(selected_plan(),file))
    output$download_brief <- downloadHandler(filename=function()'weekly_brief.md',content=function(file)file.copy('outputs/weekly_brief.md',file,overwrite=TRUE))
  }
}
