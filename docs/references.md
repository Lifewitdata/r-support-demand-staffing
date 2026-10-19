# Method and implementation references

- Forecasting: Principles and Practice, rolling-origin cross-validation: https://otexts.com/fpp3/tscv.html
- R statistics package documentation for glm: https://stat.ethz.ch/R-manual/R-devel/library/stats/html/glm.html
- Shiny server testing: https://shiny.posit.co/r/articles/improve/server-function-testing/

The forecasting model uses base R stats rather than fable. This keeps the runtime smaller while preserving an explicit, inspectable statistical model and chronological evaluation. ggplot2 supplies the charts; Shiny supplies the interactive app.
