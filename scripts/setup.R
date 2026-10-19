# Run once from the project root: Rscript scripts/setup.R
packages <- c('data.table', 'ggplot2', 'shiny')
missing <- packages[!vapply(packages, requireNamespace, logical(1), quietly=TRUE)]
if (length(missing)) install.packages(missing, repos='https://cloud.r-project.org')
cat('Packages ready. Run Rscript scripts/run_pipeline.R next.\n')
