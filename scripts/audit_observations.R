#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
value_for <- function(flag, default = NULL) {
  position <- match(flag, args)
  if (is.na(position) || position == length(args)) {
    return(default)
  }
  args[[position + 1L]]
}

input_path <- value_for("--input")
output_path <- value_for("--output")
if (is.null(input_path) || is.null(output_path)) {
  stop("Usage: Rscript scripts/audit_observations.R --input <csv> --output <json>")
}

source(file.path("R", "date_utils.R"))
source(file.path("R", "observation_audit.R"))
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("jsonlite is required to write the audit manifest")
}

result <- audit_observations(input_path)
jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
message("Wrote read-only observation audit: ", output_path)
