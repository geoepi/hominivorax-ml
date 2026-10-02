#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
value_for <- function(flag, default = NULL) {
  position <- match(flag, args)
  if (is.na(position) || position == length(args)) {
    return(default)
  }
  args[[position + 1L]]
}

weekly_root <- value_for("--weekly-root")
livestock_root <- value_for("--livestock-root")
output_path <- value_for("--output")
candidate_end <- value_for("--candidate-end")
if (is.null(weekly_root) || is.null(livestock_root) || is.null(output_path)) {
  stop(
    "Usage: Rscript scripts/inventory_rasters.R ",
    "--weekly-root <production-root> ",
    "--livestock-root <livestock-root> ",
    "--output <json> [--candidate-end YYYY-MM-DD]"
  )
}

source(file.path("R", "date_utils.R"))
source(file.path("R", "raster_inventory.R"))
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("jsonlite is required")
}

environmental_inventory <- lapply(
  expected_environmental_products(),
  inventory_environmental_product,
  weekly_root = weekly_root
)
livestock_inventory <- lapply(
  expected_livestock_files(),
  function(filename) inventory_livestock_layer(file.path(livestock_root, filename))
)
geometry <- compare_inventory_geometry(environmental_inventory)
representative_masks <- vapply(
  environmental_inventory,
  function(product) {
    summary <- product$representative_value_summary
    if (is.null(summary)) NA_character_ else summary$valid_cell_mask_sha256
  },
  character(1L)
)
mask_values <- representative_masks[!is.na(representative_masks)]
mask_comparison <- list(
  representative_mask_sha256_by_product = representative_masks,
  all_required_products_have_representative_masks =
    length(mask_values) == length(environmental_inventory),
  all_required_representative_masks_equal =
    length(mask_values) == length(environmental_inventory) &&
    length(unique(mask_values)) == 1L,
  assessment =
    "Representative weekly masks compared; all-week mask equality requires review if products differ."
)
week_sets <- lapply(environmental_inventory, function(product) {
  product$files$week_id[!is.na(product$files$week_id)]
})
common_week_ids <- if (length(week_sets)) Reduce(intersect, week_sets) else character()
candidate <- if (is.null(candidate_end)) {
  NULL
} else {
  as.Date(candidate_end)
}
common_endpoint <- if (length(common_week_ids)) {
  max(common_week_ids)
} else {
  NA_character_
}

result <- list(
  generated_at_utc = format(Sys.time(), tz = "UTC", usetz = TRUE),
  weekly_root = normalizePath(weekly_root, winslash = "/", mustWork = FALSE),
  livestock_root = normalizePath(livestock_root, winslash = "/", mustWork = FALSE),
  environmental_products = environmental_inventory,
  livestock_layers = livestock_inventory,
  geometry_comparison = geometry,
  mask_comparison = mask_comparison,
  common_week_ids = common_week_ids,
  common_environmental_earliest_week = if (length(common_week_ids)) {
    min(common_week_ids)
  } else {
    NA_character_
  },
  common_environmental_latest_week = common_endpoint,
  candidate_analysis_end = if (is.null(candidate)) NA_character_ else as.character(candidate),
  candidate_endpoint_supported_by_common_environment = if (is.null(candidate)) {
    NA
  } else {
    iso_week_id(as.Date(candidate)) %in% common_week_ids
  }
)

jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
message("Wrote weekly and livestock inventory: ", output_path)
