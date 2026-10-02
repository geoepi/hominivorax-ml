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
mask_path <- value_for("--mask")

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
  stop("environmental raster geometries are not common")
}
mask_comparison <- inventory$mask_comparison
if (is.null(mask_comparison) ||
    !isTRUE(mask_comparison$all_required_products_have_representative_masks)) {
  stop("not all required environmental products have representative masks")
}
temporal_masks <- inventory$temporal_mask_comparison
if (is.null(temporal_masks) ||
    !isTRUE(temporal_masks$all_selected_masks_available) ||
    !isTRUE(temporal_masks$all_selected_masks_invariant)) {
  stop("selected environmental masks are not complete and temporally invariant")
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

if (is.null(mask_path)) {
  stop("--mask is required for the approved environmental support intersection")
}
mask <- terra::rast(mask_path)
mask_header <- safe_raster_header(mask_path, include_values = FALSE)
crs_equal <- if ("same.crs" %in% getNamespaceExports("terra")) {
  isTRUE(terra::same.crs(mask, terra::rast(template_path)))
} else {
  identical(mask_header$crs, template_header$crs)
}
geometry_equal <- crs_equal &&
  identical(c(mask_header$nrow, mask_header$ncol), c(template_header$nrow, template_header$ncol)) &&
  isTRUE(all.equal(mask_header$resolution, template_header$resolution)) &&
  isTRUE(all.equal(mask_header$extent, template_header$extent)) &&
  isTRUE(all.equal(mask_header$origin, template_header$origin))
if (!geometry_equal) {
  stop("canonical mask geometry does not match the selected template")
}
mask_values <- terra::values(mask, mat = FALSE)
if (!all(is.na(mask_values) | mask_values == 1)) {
  stop("canonical mask must contain only 1 and nodata")
}
mask_hash <- digest::digest(as.vector(!is.na(mask_values)), algo = "sha256")
if (!identical(mask_hash, temporal_masks$canonical_intersection_sha256)) {
  stop("canonical mask does not match the approved environmental intersection")
}

result <- list(
  status = "validated",
  product = product,
  file = normalizePath(template_path, winslash = "/", mustWork = TRUE),
  iso_week = week_id,
  geometry = template_header,
  geometry_matches_inventory_reference = TRUE,
  valid_cell_count = sum(!is.na(mask_values)),
  canonical_mask_path = normalizePath(mask_path, winslash = "/", mustWork = TRUE),
  canonical_mask_sha256 = mask_hash,
  mask_policy = "cellwise intersection of valid support across all 12 required environmental predictors; no imputation"
)
jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
message("Canonical template validated: ", template_path)
