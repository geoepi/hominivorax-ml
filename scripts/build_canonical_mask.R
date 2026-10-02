#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
value_for <- function(flag) {
  position <- match(flag, args)
  if (is.na(position) || position == length(args)) stop("missing argument: ", flag)
  args[[position + 1L]]
}

inventory_path <- value_for("--inventory")
template_path <- value_for("--template")
output_path <- value_for("--output")
metadata_path <- value_for("--metadata")

if (!requireNamespace("jsonlite", quietly = TRUE) ||
    !requireNamespace("terra", quietly = TRUE) ||
    !requireNamespace("digest", quietly = TRUE)) {
  stop("jsonlite, terra, and digest are required")
}
source(file.path("R", "canonical_mask.R"))

inventory <- jsonlite::read_json(inventory_path, simplifyVector = FALSE)
comparison <- inventory$temporal_mask_comparison
if (is.null(comparison) ||
    !isTRUE(comparison$all_selected_masks_available) ||
    !isTRUE(comparison$all_selected_masks_invariant)) {
  stop("selected environmental masks are not complete and temporally invariant")
}
selected_week <- comparison$selected_week_ids[[1L]]
products <- inventory$environmental_products
paths <- vapply(products, function(product) {
  file_index <- match(selected_week, vapply(product$files, function(file) file$week_id, character(1L)))
  if (is.na(file_index)) stop("missing selected week in product: ", product$product)
  product$headers[[file_index]]$path
}, character(1L))

mask_result <- canonical_mask_from_paths(paths, template_path = template_path)
expected_hash <- comparison$canonical_intersection_sha256
actual_hash <- digest::digest(mask_result$mask_values, algo = "sha256")
if (!identical(actual_hash, expected_hash)) {
  stop("constructed canonical mask hash does not match the inventory comparison")
}
write_canonical_mask(mask_result, output_path)

result <- list(
  status = "validated",
  mask_policy = comparison$mask_policy,
  selected_week_for_construction = selected_week,
  selected_week_ids_checked = comparison$selected_week_ids,
  input_products = vapply(products, function(product) product$product, character(1L)),
  input_paths = paths,
  template_path = normalizePath(template_path, winslash = "/", mustWork = TRUE),
  canonical_mask_path = normalizePath(output_path, winslash = "/", mustWork = TRUE),
  nrow = terra::nrow(terra::rast(template_path)),
  ncol = terra::ncol(terra::rast(template_path)),
  valid_cell_count = mask_result$intersection_valid_cell_count,
  valid_cell_mask_sha256 = actual_hash,
  dropped_cell_count_by_input = setNames(
    as.list(mask_result$dropped_cell_count_by_input),
    vapply(products, function(product) product$product, character(1L))
  ),
  temporal_invariance = comparison$assessment
)
jsonlite::write_json(result, metadata_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
message("Wrote canonical environmental mask: ", output_path)
