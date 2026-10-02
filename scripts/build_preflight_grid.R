#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
value_for <- function(flag) {
  position <- match(flag, args)
  if (is.na(position) || position == length(args)) {
    stop("missing argument: ", flag)
  }
  args[[position + 1L]]
}

template_path <- value_for("--template")
node_output <- value_for("--nodes")
edge_output <- value_for("--edges")
qa_output <- value_for("--qa-output")

if (!requireNamespace("terra", quietly = TRUE)) {
  stop("terra is required")
}
if (!requireNamespace("arrow", quietly = TRUE)) {
  stop("arrow is required")
}
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("jsonlite is required")
}

source(file.path("R", "grid_graph.R"))
template <- terra::rast(template_path)
nodes <- node_table_from_terra(template)
edges <- queen_edges(nodes, terra::nrow(template), terra::ncol(template))
qa <- queen_graph_qa(nodes, edges)

arrow::write_parquet(nodes, node_output)
arrow::write_parquet(edges, edge_output)
if (!is.null(qa_output)) {
  jsonlite::write_json(qa, qa_output, auto_unbox = TRUE, pretty = TRUE, na = "null")
}
message(jsonlite::toJSON(qa, auto_unbox = TRUE, pretty = TRUE))
