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
inventory_path <- value_for("--inventory")
output_path <- value_for("--output")
product <- value_for("--product")
week_id <- value_for("--week")

if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("jsonlite is required")
}
if (!requireNamespace("terra", quietly = TRUE)) {
  stop("terra is required")
}

source(file.path("R", "raster_inventory.R"))
inventory <- jsonlite::read_json(inventory_path, simplifyVector = FALSE)
reference <- inventory$geometry_comparison$reference
if (is.null(reference)) {
  stop("inventory has no reference raster")
}
if (!isTRUE(inventory$geometry_comparison$common_geometry)) {
  stop("environmental raster geometries are not common; no mask/geometry reconciliation is authorized")
}
mask_comparison <- inventory$mask_comparison
if (is.null(mask_comparison) ||
    !isTRUE(mask_comparison$all_required_products_have_representative_masks)) {
  stop("not all required environmental products have representative masks")
}
if (!isTRUE(mask_comparison$all_required_representative_masks_equal)) {
  stop("representative environmental masks differ; escalate the Level-2 mask decision")
}
products <- inventory$environmental_products
selected_product <- Filter(
  function(entry) identical(entry$product, product),
  products
)
if (length(selected_product) != 1L) {
  stop("selected product is not uniquely present in inventory: ", product)
}
selected_product <- selected_product[[1L]]
template_normalized <- normalizePath(template_path, winslash = "/", mustWork = TRUE)
inventory_paths <- vapply(
  selected_product$headers,
  function(header) header$path,
  character(1L)
)
if (!template_normalized %in% inventory_paths) {
  stop("selected template file is not in the selected product inventory")
}
selected_file <- Filter(
  function(file) identical(file$filename, basename(template_path)),
  selected_product$files
)
if (length(selected_file) != 1L ||
    !identical(selected_file[[1L]]$week_id, week_id)) {
  stop("selected template filename and requested ISO week do not match inventory")
}
reference_path <- reference$path[[1L]]
template_header <- safe_raster_header(template_path, include_values = TRUE)
reference_header <- safe_raster_header(reference_path, include_values = FALSE)
template_signature <- raster_geometry_signature(template_header)
reference_signature <- raster_geometry_signature(reference_header)
if (!identical(template_signature, reference_signature)) {
  stop("canonical template geometry does not exactly match inventory reference")
}

result <- list(
  status = "validated",
  product = product,
  file = normalizePath(template_path, winslash = "/", mustWork = TRUE),
  iso_week = week_id,
  geometry = template_header,
  geometry_matches_inventory_reference = TRUE,
  valid_cell_count = sum(!is.na(terra::values(terra::rast(template_path), mat = FALSE))),
  mask_policy = "all valid cells in the template; no mask reconciliation performed"
)
jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
message("Canonical template validated: ", template_path)
