# Run scripts from the repository root. The Shiny entrypoint is also at the root.
required <- c('data.table', 'ggplot2', 'htmltools')
missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) stop('Missing R packages: ', paste(missing, collapse=', '), '. Run source("scripts/setup.R") first.')
suppressPackageStartupMessages(library(data.table))
suppressPackageStartupMessages(library(ggplot2))
source('config/settings.R')
for (file in c('generate.R','validate.R','prepare.R','forecast.R','staffing.R','report.R')) source(file.path('R',file))
