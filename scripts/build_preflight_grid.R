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
mask_path <- value_for("--mask")

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
if (is.null(mask_path)) {
  stop("--mask is required for the approved canonical environmental support mask")
}
mask <- terra::rast(mask_path)
mask_crs_equal <- if ("same.crs" %in% getNamespaceExports("terra")) {
  isTRUE(terra::same.crs(mask, template))
} else {
  identical(terra::crs(mask), terra::crs(template))
}
if (!identical(terra::nrow(mask), terra::nrow(template)) ||
    !identical(terra::ncol(mask), terra::ncol(template)) ||
    !isTRUE(all.equal(as.vector(terra::ext(mask)), as.vector(terra::ext(template)))) ||
    !isTRUE(all.equal(as.numeric(terra::res(mask)), as.numeric(terra::res(template)))) ||
    !mask_crs_equal) {
  stop("canonical mask geometry does not match the selected template")
}
mask_values <- terra::values(mask, mat = FALSE)
template_values <- terra::values(template, mat = FALSE)
if (!all(is.na(mask_values) | mask_values == 1)) {
  stop("canonical mask must contain only 1 and nodata")
}
template_values[is.na(mask_values)] <- NA_real_
template_for_nodes <- template
terra::values(template_for_nodes) <- template_values
nodes <- node_table_from_terra(template_for_nodes)
edges <- queen_edges(nodes, terra::nrow(template), terra::ncol(template))
qa <- queen_graph_qa(nodes, edges)

arrow::write_parquet(nodes, node_output)
arrow::write_parquet(edges, edge_output)
if (!is.null(qa_output)) {
  jsonlite::write_json(qa, qa_output, auto_unbox = TRUE, pretty = TRUE, na = "null")
}
message(jsonlite::toJSON(qa, auto_unbox = TRUE, pretty = TRUE))
