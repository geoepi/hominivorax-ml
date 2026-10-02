#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
value_for <- function(flag) {
  position <- match(flag, args)
  if (is.na(position) || position == length(args)) {
    stop("missing argument: ", flag)
  }
  args[[position + 1L]]
}

weekly_root <- value_for("--weekly-root")
livestock_root <- value_for("--livestock-root")
output_path <- value_for("--output")

if (!requireNamespace("terra", quietly = TRUE)) {
  stop("terra is required")
}
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("jsonlite is required")
}

expected_products <- c(
  "era5_mintemp",
  "era5_soilmoist",
  "era5_lai_low",
  "agera5_relhum_min",
  "era5land_tmean",
  "era5land_soiltemp_l1_mean",
  "era5land_soiltemp_l2_mean",
  "era5land_soilwater_l1_mean",
  "era5land_soilwater_l2_mean",
  "era5land_surface_pressure_mean",
  "era5land_lai_high_mean",
  "era5land_lai_low_mean"
)
expected_livestock <- c(
  "goat_density20.tif",
  "cattle_density20.tif",
  "sheep_density20.tif",
  "horse_density.tif",
  "pig_density20.tiff"
)

safe_raster_metadata <- function(path) {
  raster <- terra::rast(path, lyrs = 1)
  values <- tryCatch(terra::values(raster, mat = FALSE), error = function(error) NULL)
  finite_values <- if (is.null(values)) numeric() else values[!is.na(values)]
  list(
    path = normalizePath(path, winslash = "/", mustWork = TRUE),
    file_size_bytes = unname(file.info(path)$size),
    crs = terra::crs(raster),
    nrow = terra::nrow(raster),
    ncol = terra::ncol(raster),
    resolution = as.numeric(terra::res(raster)),
    extent = as.numeric(terra::ext(raster)),
    origin = as.numeric(terra::origin(raster)),
    nodata = terra::NAflag(raster),
    data_type = terra::datatype(raster),
    valid_cell_count = if (is.null(values)) NA_integer_ else sum(!is.na(values)),
    minimum = if (!length(finite_values)) NA_real_ else min(finite_values),
    maximum = if (!length(finite_values)) NA_real_ else max(finite_values),
    filename = basename(path)
  )
}

weekly_inventory <- lapply(expected_products, function(product) {
  product_weekly_root <- file.path(weekly_root, product, "weekly")
  product_files <- list.files(product_weekly_root, pattern = "\\.(tif|tiff)$",
    recursive = TRUE, full.names = TRUE, ignore.case = TRUE)
  list(
    product = product,
    weekly_directory = normalizePath(product_weekly_root,
      winslash = "/", mustWork = FALSE),
    file_count = length(product_files),
    files = lapply(product_files, safe_raster_metadata)
  )
})

livestock_inventory <- lapply(expected_livestock, function(filename) {
  path <- file.path(livestock_root, filename)
  if (!file.exists(path)) {
    return(list(path = normalizePath(path, winslash = "/", mustWork = FALSE), missing = TRUE))
  }
  safe_raster_metadata(path)
})

jsonlite::write_json(
  list(
    generated_at_utc = format(Sys.time(), tz = "UTC", usetz = TRUE),
    weekly_inventory = weekly_inventory,
    livestock_inventory = livestock_inventory
  ),
  output_path,
  auto_unbox = TRUE,
  pretty = TRUE,
  na = "null"
)
