#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
value_for <- function(flag) {
  position <- match(flag, args)
  if (is.na(position) || position == length(args)) {
    stop("missing argument: ", flag)
  }
  args[[position + 1L]]
}

observation_path <- value_for("--observations")
template_path <- value_for("--template")
nodes_path <- value_for("--nodes")
output_json <- value_for("--output-json")
output_parquet <- value_for("--output-parquet")
mask_path <- value_for("--mask")

if (!requireNamespace("arrow", quietly = TRUE)) {
  stop("arrow is required")
}
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("jsonlite is required")
}

source(file.path("R", "date_utils.R"))
source(file.path("R", "observation_grid_diagnostic.R"))
nodes <- arrow::read_parquet(nodes_path, as_data_frame = TRUE)
result <- observation_to_grid_diagnostic(
  observation_path = observation_path,
  template_path = template_path,
  nodes = nodes,
  mask_path = mask_path
)
aggregation <- result$aggregation
result$aggregation <- NULL
arrow::write_parquet(aggregation, output_parquet)
jsonlite::write_json(result, output_json, auto_unbox = TRUE, pretty = TRUE, na = "null")
message("Wrote observation-to-grid summary: ", output_json)
message("Wrote node-week diagnostic counts: ", output_parquet)
