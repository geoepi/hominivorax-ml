# Canonical environmental support-mask helpers.

canonical_mask_from_paths <- function(paths, template_path = NULL) {
  if (!length(paths)) {
    stop("at least one environmental raster path is required")
  }
  if (!requireNamespace("terra", quietly = TRUE)) {
    stop("terra is required")
  }
  rasters <- lapply(paths, terra::rast)
  reference <- if (is.null(template_path)) rasters[[1L]] else terra::rast(template_path)
  reference_signature <- paste(
    terra::crs(reference), terra::nrow(reference), terra::ncol(reference),
    paste(format(terra::res(reference), digits = 17), collapse = ","),
    paste(format(as.vector(terra::ext(reference)), digits = 17), collapse = ","),
    sep = "|"
  )
  same_geometry <- vapply(rasters, function(raster) {
    signature <- paste(
      terra::crs(raster), terra::nrow(raster), terra::ncol(raster),
      paste(format(terra::res(raster), digits = 17), collapse = ","),
      paste(format(as.vector(terra::ext(raster)), digits = 17), collapse = ","),
      sep = "|"
    )
    identical(signature, reference_signature)
  }, logical(1L))
  if (!all(same_geometry)) {
    stop("all environmental rasters must have common geometry before mask intersection")
  }
  valid_masks <- lapply(rasters, function(raster) {
    !is.na(terra::values(raster, mat = FALSE))
  })
  intersection <- Reduce(`&`, valid_masks)
  list(
    mask = matrix(intersection, nrow = terra::nrow(reference), ncol = terra::ncol(reference), byrow = TRUE),
    mask_values = as.vector(intersection),
    template = reference,
    input_paths = normalizePath(paths, winslash = "/", mustWork = TRUE),
    input_valid_cell_counts = vapply(valid_masks, sum, integer(1L)),
    intersection_valid_cell_count = sum(intersection),
    dropped_cell_count_by_input = vapply(valid_masks, function(mask) sum(mask & !intersection), integer(1L))
  )
}

write_canonical_mask <- function(mask_result, output_path) {
  if (!requireNamespace("terra", quietly = TRUE)) {
    stop("terra is required")
  }
  mask_raster <- mask_result$template
  terra::values(mask_raster) <- ifelse(mask_result$mask_values, 1, NA_real_)
  terra::writeRaster(mask_raster, output_path, overwrite = TRUE, datatype = "INT1U", NAflag = 255)
  invisible(output_path)
}
