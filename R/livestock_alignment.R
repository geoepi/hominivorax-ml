# Exact-overlap, area-weighted alignment for continuous animal-density rasters.

same_raster_geometry <- function(x, y) {
  identical(terra::crs(x), terra::crs(y)) &&
    identical(terra::nrow(x), terra::nrow(y)) &&
    identical(terra::ncol(x), terra::ncol(y)) &&
    isTRUE(all.equal(as.numeric(terra::res(x)), as.numeric(terra::res(y)))) &&
    isTRUE(all.equal(as.vector(terra::ext(x)), as.vector(terra::ext(y))))
}

overlap_indices <- function(lower, upper, cell_lower, cell_upper) {
  which(cell_upper > lower & cell_lower < upper)
}

area_weighted_density_to_template <- function(source_path, template, valid_mask = NULL) {
  if (!requireNamespace("terra", quietly = TRUE)) {
    stop("terra is required")
  }
  source <- terra::rast(source_path, lyrs = 1)
  crs_equal <- if ("same.crs" %in% getNamespaceExports("terra")) {
    isTRUE(terra::same.crs(source, template))
  } else {
    identical(terra::crs(source), terra::crs(template))
  }
  if (!crs_equal) {
    stop("source and destination CRS differ; reprojection requires a separate approved method")
  }
  if (!is.null(valid_mask) && !all(dim(valid_mask) == c(terra::nrow(template), terra::ncol(template)))) {
    stop("valid_mask dimensions do not match the destination template")
  }

  source_values <- matrix(
    terra::values(source, mat = FALSE),
    nrow = terra::nrow(source),
    ncol = terra::ncol(source),
    byrow = TRUE
  )
  source_res <- as.numeric(terra::res(source))
  source_ext <- as.vector(terra::ext(source))
  destination_res <- as.numeric(terra::res(template))
  destination_ext <- as.vector(terra::ext(template))
  source_nrow <- terra::nrow(source)
  source_ncol <- terra::ncol(source)
  destination_nrow <- terra::nrow(template)
  destination_ncol <- terra::ncol(template)

  source_x_left <- source_ext[1L] + (seq_len(source_ncol) - 1) * source_res[1L]
  source_x_right <- source_x_left + source_res[1L]
  source_y_top <- source_ext[4L] - (seq_len(source_nrow) - 1) * source_res[2L]
  source_y_bottom <- source_y_top - source_res[2L]
  result_values <- rep(NA_real_, destination_nrow * destination_ncol)
  coverage_fraction <- rep(0, destination_nrow * destination_ncol)
  source_mass <- rep(0, destination_nrow * destination_ncol)
  covered_area <- rep(0, destination_nrow * destination_ncol)
  destination_cell_area <- prod(destination_res)

  for (destination_row in seq_len(destination_nrow)) {
    destination_y_top <- destination_ext[4L] - (destination_row - 1) * destination_res[2L]
    destination_y_bottom <- destination_y_top - destination_res[2L]
    source_rows <- overlap_indices(
      destination_y_bottom, destination_y_top,
      source_y_bottom, source_y_top
    )
    if (!length(source_rows)) next
    y_overlap <- pmax(
      0,
      pmin(source_y_top[source_rows], destination_y_top) -
        pmax(source_y_bottom[source_rows], destination_y_bottom)
    )
    for (destination_column in seq_len(destination_ncol)) {
      destination_x_left <- destination_ext[1L] + (destination_column - 1) * destination_res[1L]
      destination_x_right <- destination_x_left + destination_res[1L]
      source_columns <- overlap_indices(
        destination_x_left, destination_x_right,
        source_x_left, source_x_right
      )
      if (!length(source_columns)) next
      x_overlap <- pmax(
        0,
        pmin(source_x_right[source_columns], destination_x_right) -
          pmax(source_x_left[source_columns], destination_x_left)
      )
      overlap_area <- y_overlap %o% x_overlap
      source_block <- source_values[source_rows, source_columns, drop = FALSE]
      valid <- !is.na(source_block) & overlap_area > 0
      destination_cell <- (destination_row - 1L) * destination_ncol + destination_column
      if (any(valid)) {
        areas <- overlap_area[valid]
        values <- source_block[valid]
        covered_area[destination_cell] <- sum(areas)
        source_mass[destination_cell] <- sum(values * areas)
        result_values[destination_cell] <- source_mass[destination_cell] / covered_area[destination_cell]
        coverage_fraction[destination_cell] <- covered_area[destination_cell] / destination_cell_area
      }
    }
  }

  if (!is.null(valid_mask)) {
    keep <- as.vector(valid_mask)
    result_values[!keep] <- NA_real_
    coverage_fraction[!keep] <- NA_real_
    source_mass[!keep] <- NA_real_
    covered_area[!keep] <- NA_real_
  }
  aligned <- template
  terra::values(aligned) <- result_values
  list(
    raster = aligned,
    values = result_values,
    coverage_fraction = coverage_fraction,
    covered_area = covered_area,
    source_mass = source_mass,
    destination_cell_area = destination_cell_area,
    source_geometry = list(
      crs = terra::crs(source), nrow = source_nrow, ncol = source_ncol,
      resolution = source_res, extent = source_ext,
      nodata = terra::NAflag(source), datatype = terra::datatype(source),
      bands = terra::nlyr(source)
    ),
    destination_geometry = list(
      crs = terra::crs(template), nrow = destination_nrow, ncol = destination_ncol,
      resolution = destination_res, extent = destination_ext
    )
  )
}

alignment_summary <- function(alignment, source_path, animal, explicit_units = NULL, metadata = NULL) {
  values <- alignment$values[is.finite(alignment$values)]
  coverage <- alignment$coverage_fraction[is.finite(alignment$coverage_fraction)]
  tolerance <- 1e-10
  list(
    animal = animal,
    source_path = normalizePath(source_path, winslash = "/", mustWork = TRUE),
    semantics = "continuous animal-density surface (approved Task 1D decision)",
    aggregation = "exact cell-overlap area-weighted mean density; no extrapolation",
    area_treatment = "actual rectangular overlap areas in the common projected CRS",
    explicit_units = explicit_units,
    metadata = metadata,
    destination_cell_area = alignment$destination_cell_area,
    valid_destination_cells = sum(is.finite(alignment$values)),
    partial_coverage_cells = sum(coverage < 1 - tolerance),
    zero_coverage_cells = sum(!is.finite(alignment$values)),
    minimum_coverage_fraction = if (length(coverage)) min(coverage) else NA_real_,
    maximum_coverage_fraction = if (length(coverage)) max(coverage) else NA_real_,
    density_minimum = if (length(values)) min(values) else NA_real_,
    density_mean = if (length(values)) mean(values) else NA_real_,
    density_median = if (length(values)) median(values) else NA_real_,
    density_maximum = if (length(values)) max(values) else NA_real_,
    density_quantiles = if (length(values)) {
      stats::quantile(values, probs = c(0, 0.25, 0.5, 0.75, 0.9, 0.95, 1), names = TRUE)
    } else numeric(),
    mass_conservation_max_abs_error = max(
      abs(alignment$source_mass - alignment$values * alignment$covered_area),
      na.rm = TRUE
    )
  )
}
