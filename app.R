# From this folder: shiny::runApp('.')
source('R/load.R')
library(shiny)
source('R/app_logic.R')
if (!file.exists('data/processed/app_bundle.rds')) {
  stop('Prepared data are missing. Run Rscript scripts/run_pipeline.R from the project folder, then restart Shiny.')
}
project_data <- readRDS('data/processed/app_bundle.rds')
last_date <- as.Date(max(project_data$hourly$timestamp),tz='UTC')

ui <- fluidPage(
  tags$head(tags$link(rel='stylesheet',type='text/css',href='style.css')),
  div(class='hero',div(class='eyebrow','OPERATIONS ANALYTICS / R + SHINY'),
      h1('Support demand & staffing'),p('See next week’s pressure points. Compare a staffing response before committing capacity.'),
      span(class='badge-note','Synthetic data · Independent portfolio project · UTC')),
  fluidRow(column(4,selectInput('queue','Support queue',choices=c('All queues',settings$queues))),
           column(6,dateRangeInput('dates','Historical window',start=last_date-27,end=last_date,
                                   min=as.Date(settings$start),max=last_date)),
           column(2,div(class='built',paste('History ends',format(last_date,'%d %b %Y'))))),
  tabsetPanel(id='main_tab',
    tabPanel('Operations overview',
      uiOutput('overview_kpis'),
      fluidRow(column(8,plotOutput('daily_demand',height=350)),column(4,div(class='note',h3('What this view measures'),
        p('Arrivals are observed synthetic tickets. Handling minutes describe required work. Available capacity uses paid headcount, shrinkage and productive occupancy.'),
        p('Backlog is a fluid estimate of unserved workload. It is not a count of customers or a measured waiting time.')))),
      plotOutput('weekly_pattern',height=330),tableOutput('overview_table')),
    tabPanel('Forecast validation',
      div(class='note',h3('A forecast has to earn its place'),
          p('Three rolling weeks choose between a weekly seasonal baseline and a seasonal count regression. Two later weeks calibrate bands; three untouched weeks assess accuracy. Lower WAPE is better.'),
          p('The selected model stays fixed during the held-out evaluation. Empirical interval coverage is reported rather than assumed.')),
      plotOutput('forecast_plot',height=580),h3('Performance on later, held-out weeks'),tableOutput('forecast_accuracy'),
      h3('Did the uncertainty bands cover actual demand?'),tableOutput('coverage_table'),
      downloadButton('download_forecast','Download forecast CSV')),
    tabPanel('Staffing scenarios',
      fluidRow(column(3,div(class='controls',
        sliderInput('demand','Demand versus forecast (%)',min=50,max=150,value=100,step=5),
        sliderInput('handling','Handling time versus recent history (%)',min=60,max=140,value=100,step=5),
        sliderInput('shrinkage','Shrinkage (%)',min=0,max=50,value=100*settings$shrinkage,step=5),
        sliderInput('occupancy','Productive occupancy (%)',min=50,max=95,value=100*settings$occupancy,step=5),
        selectInput('basis','Demand planning basis',choices=c('Central forecast'='prediction','Upper-band stress scenario'='upper')),
        numericInput('extra_agents','Extra paid agents each hour, per queue',value=0,min=0,max=100,step=1),
        selectInput('clearance','Spread opening backlog over',choices=c('24 hours'=24,'72 hours'=72,'Seven days'=168),selected=settings$backlog_clearance_hours))),
        column(9,uiOutput('scenario_kpis'),plotOutput('staffing_plot',height=480),tableOutput('staffing_summary'),
          downloadButton('download_plan','Download this staffing scenario'))),
      div(class='note',p('Required paid agents = workload minutes ÷ [60 × (1 − shrinkage) × occupancy], rounded up each hour. Opening backlog is included.'),
          p('Uncovered agent-hours are a planning gap, not the number of hires. Skill coverage, shift patterns and labour rules still need a scheduler. No SLA is guaranteed.'))),
    tabPanel('Workload deep dive',
      div(class='note',h3('More tickets, harder cases, or less capacity?'),
        p('Compare the latest week with the previous four-week average. The decomposition splits the change in workload between volume and average handling time. It is arithmetic, not causal evidence.')),
      plotOutput('drivers_plot',height=420),tableOutput('drivers_table'),uiOutput('deep_dive_note')),
    tabPanel('Data & handoff',
      h3('Checks before using the numbers'),tableOutput('quality_table'),
      h3('Weekly decision brief'),verbatimTextOutput('brief'),downloadButton('download_brief','Download the weekly brief'),
      div(class='note',h3('How the data were made'),
        p('R generates ticket arrivals with daily and weekly patterns, growth and a temporary incident. Payment handling work rises near the end of the sample. These are simulation assumptions, not findings about Uber.'),
        p('Every table, forecast and report can be rebuilt with Rscript scripts/run_pipeline.R. No Python, SQL, credentials or paid service is required.'),
        p('The dashboard reads a completed snapshot. It is not connected to a live support platform.')))
  ),
  tags$footer('R • data.table • stats • ggplot2 • Shiny | Operational decisions with visible assumptions')
)
server <- make_server(project_data)
shinyApp(ui,server)
