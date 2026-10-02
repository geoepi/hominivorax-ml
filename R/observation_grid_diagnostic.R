# Read-only observation-to-canonical-grid diagnostic.

observation_to_grid_diagnostic <- function(
  observation_path,
  template_path,
  nodes,
  analysis_start = as.Date("2024-01-01"),
  mask_path = NULL
) {
  required_nodes <- c("node_id", "raster_cell", "row", "column")
  if (!all(required_nodes %in% names(nodes))) {
    stop("nodes must contain: ", paste(required_nodes, collapse = ", "))
  }
  if (!requireNamespace("data.table", quietly = TRUE)) {
    stop("data.table is required")
  }
  if (!requireNamespace("terra", quietly = TRUE)) {
    stop("terra is required")
  }

  observations <- data.table::fread(observation_path, showProgress = FALSE)
  required_observations <- c("lon", "lat", "date")
  if (!all(required_observations %in% names(observations))) {
    stop("observation data are missing required columns")
  }
  template <- terra::rast(template_path)
  if (is.na(terra::crs(template)) || !nzchar(terra::crs(template))) {
    stop("canonical template has no CRS")
  }

  parsed_date <- parse_strict_date(observations[["date"]])
  lon <- suppressWarnings(as.numeric(observations[["lon"]]))
  lat <- suppressWarnings(as.numeric(observations[["lat"]]))
  valid_date <- !is.na(parsed_date)
  valid_coordinate <- is.finite(lon) & is.finite(lat) &
    lon >= -180 & lon <= 180 & lat >= -90 & lat <= 90
  post_2024 <- valid_date & parsed_date >= analysis_start
  period <- latest_complete_iso_week(parsed_date, analysis_start)
  in_candidate_period <- post_2024
  if (!is.na(period$candidate_analysis_end)) {
    in_candidate_period <- in_candidate_period &
      parsed_date <= period$candidate_analysis_end
  } else {
    in_candidate_period[] <- FALSE
  }

  classification_positions <- which(post_2024)
  coordinate_positions <- classification_positions[
    valid_coordinate[classification_positions]
  ]
  classification <- rep(NA_character_, length(classification_positions))
  classification[!valid_coordinate[classification_positions]] <- "invalid_coordinate"

  template_values <- if (is.null(mask_path)) {
    terra::values(template, mat = FALSE)
  } else {
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
      stop("canonical mask geometry does not match the observation template")
    }
    terra::values(mask, mat = FALSE)
  }
  valid_template_cells <- !is.na(template_values)
  cells <- rep(NA_integer_, length(coordinate_positions))
  node_ids <- rep(NA_integer_, length(coordinate_positions))
  if (length(coordinate_positions)) {
    points <- terra::vect(
      data.frame(lon = lon[coordinate_positions], lat = lat[coordinate_positions]),
      geom = c("lon", "lat"),
      crs = "EPSG:4326"
    )
    projected_points <- terra::project(points, terra::crs(template))
    projected_xy <- terra::crds(projected_points)
    cells <- terra::cellFromXY(template, projected_xy)
    inside_extent <- !is.na(cells) & cells >= 1L &
      cells <= length(valid_template_cells)
    valid_cell <- rep(FALSE, length(cells))
    valid_cell[inside_extent] <- valid_template_cells[cells[inside_extent]]
    classification[valid_coordinate[classification_positions]] <- ifelse(
      inside_extent,
      ifelse(valid_cell, "assigned_valid_cell", "masked_nodata_cell"),
      "outside_extent"
    )
    lookup <- nodes$node_id
    names(lookup) <- as.character(nodes$raster_cell)
    node_ids <- unname(lookup[as.character(cells)])
    node_ids[!valid_cell] <- NA_integer_
  }

  assigned_coordinate <- classification[
    valid_coordinate[classification_positions]
  ] == "assigned_valid_cell"
  in_candidate_coordinate <- in_candidate_period[coordinate_positions]
  assigned_positions <- coordinate_positions[
    assigned_coordinate & in_candidate_coordinate
  ]
  assigned_node_ids <- node_ids[assigned_coordinate & in_candidate_coordinate]
  aggregation <- if (length(assigned_positions)) {
    data.table::data.table(
      node_id = as.integer(assigned_node_ids),
      iso_week = iso_week_id(parsed_date[assigned_positions])
    )[, .(detection_count = .N), by = .(node_id, iso_week)]
  } else {
    data.table::data.table(
      node_id = integer(),
      iso_week = character(),
      detection_count = integer()
    )
  }

  target_week_ids <- if (period$target_week_count > 0L) {
    iso_week_id(seq(analysis_start, period$candidate_analysis_end, by = "7 days"))
  } else {
    character()
  }
  weekly <- if (length(target_week_ids)) {
    weekly_counts <- if (nrow(aggregation)) {
      aggregation[, .(
        total_recorded_detections = sum(detection_count),
        detection_positive_nodes = data.table::uniqueN(node_id)
      ), by = iso_week]
    } else {
      data.table::data.table(
        iso_week = character(),
        total_recorded_detections = integer(),
        detection_positive_nodes = integer()
      )
    }
    weekly_result <- merge(
      data.table::data.table(iso_week = target_week_ids),
      weekly_counts,
      by = "iso_week",
      all.x = TRUE,
      sort = FALSE
    )
    weekly_result[is.na(total_recorded_detections),
      total_recorded_detections := 0L]
    weekly_result[is.na(detection_positive_nodes),
      detection_positive_nodes := 0L]
    weekly_result
  } else {
    data.table::data.table(
      iso_week = character(),
      total_recorded_detections = integer(),
      detection_positive_nodes = integer()
    )
  }

  positive_counts <- aggregation$detection_count
  possible_node_weeks <- as.double(nrow(nodes)) * period$target_week_count
  positive_node_weeks <- nrow(aggregation)
  zero_node_weeks <- max(0, possible_node_weeks - positive_node_weeks)
  list(
    source_path = normalizePath(observation_path, winslash = "/", mustWork = TRUE),
    template_path = normalizePath(template_path, winslash = "/", mustWork = TRUE),
    total_post_2024_observations = sum(post_2024),
    observations_in_candidate_period = sum(in_candidate_period),
    invalid_coordinate_observations = sum(post_2024 & !valid_coordinate),
    successfully_assigned_observations = sum(
      classification == "assigned_valid_cell",
      na.rm = TRUE
    ),
    outside_extent_observations = sum(
      classification == "outside_extent",
      na.rm = TRUE
    ),
    masked_cell_observations = sum(
      classification == "masked_nodata_cell",
      na.rm = TRUE
    ),
    classification_counts = as.list(table(classification, useNA = "no")),
    number_model_nodes = nrow(nodes),
    number_target_weeks = period$target_week_count,
    total_possible_node_weeks = possible_node_weeks,
    positive_node_weeks = positive_node_weeks,
    zero_node_weeks = zero_node_weeks,
    zero_fraction = if (possible_node_weeks > 0) {
      zero_node_weeks / possible_node_weeks
    } else {
      NA_real_
    },
    occupied_nodes = data.table::uniqueN(aggregation$node_id),
    positive_count_mean = if (length(positive_counts)) mean(positive_counts) else NA_real_,
    positive_count_median = if (length(positive_counts)) median(positive_counts) else NA_real_,
    positive_count_variance = if (length(positive_counts) > 1L) {
      stats::var(positive_counts)
    } else if (length(positive_counts) == 1L) {
      0
    } else {
      NA_real_
    },
    positive_count_maximum = if (length(positive_counts)) max(positive_counts) else NA_real_,
    positive_count_quantiles = if (length(positive_counts)) {
      stats::quantile(
        positive_counts,
        probs = c(0, 0.25, 0.5, 0.75, 0.9, 0.95, 1),
        names = TRUE
      )
    } else {
      numeric()
    },
    fraction_positive_node_weeks_count_one = if (length(positive_counts)) {
      mean(positive_counts == 1L)
    } else {
      NA_real_
    },
    weekly = weekly,
    candidate_period = period,
    aggregation = aggregation
  )
}
