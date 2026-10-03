# Task-2D revised-domain construction and observation-regime audit helpers.
#
# This file deliberately contains no model-fitting code.  It reads the frozen
# Task-2A artifacts, applies an outcome-independent geographic mask, subsets
# the canonical graph/features/tensors, and writes descriptive audit outputs.

task2d_require <- function(packages) {
  missing <- packages[!vapply(packages, requireNamespace, logical(1L), quietly = TRUE)]
  if (length(missing)) stop("missing R packages: ", paste(missing, collapse = ", "))
}

task2d_sha256 <- function(path) {
  if (!file.exists(path)) return(NA_character_)
  unname(digest::digest(file = path, algo = "sha256"))
}

task2d_iso_week_start <- function(week_id) {
  parts <- strsplit(week_id, "-W", fixed = TRUE)
  as.Date(sprintf("%s-01-04", vapply(parts, `[[`, character(1L), 1L))) -
    as.integer(format(as.Date(sprintf("%s-01-04", vapply(parts, `[[`, character(1L), 1L))), "%u")) +
    1L + 7L * (as.integer(vapply(parts, `[[`, character(1L), 2L)) - 1L)
}

task2d_parse_args <- function(args) {
  value_for <- function(flag, default = NULL, required = FALSE) {
    position <- match(flag, args)
    if (is.na(position)) {
      if (required) stop("missing argument: ", flag)
      return(default)
    }
    if (position == length(args)) stop("missing argument value: ", flag)
    args[[position + 1L]]
  }
  boundary_default <- Sys.getenv("STGNN_BOUNDARY_PATH", "")
  list(
    output_root = value_for("--output-root", Sys.getenv("STGNN_OUTPUT_ROOT", "/project/disease_ecology/STGNN-output")),
    observation_path = value_for("--observation-path", Sys.getenv("STGNN_OBSERVATION_PATH", "/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv")),
    boundary_path = value_for("--boundary-path", boundary_default, required = TRUE),
    boundary_layer = value_for("--boundary-layer", Sys.getenv("STGNN_BOUNDARY_LAYER", "")),
    canonical_mask = value_for("--canonical-mask", NULL),
    nodes_path = value_for("--nodes", NULL),
    edges_path = value_for("--edges", NULL),
    analysis_start = as.Date(value_for("--analysis-start", "2024-01-01")),
    analysis_end = as.Date(value_for("--analysis-end", "2026-07-19")),
    git_sha = value_for("--git-sha", Sys.getenv("STGNN_GIT_SHA", "unknown"))
  )
}

task2d_resolve_paths <- function(args) {
  root <- normalizePath(args$output_root, winslash = "/", mustWork = FALSE)
  args$output_root <- root
  args$canonical_mask <- args$canonical_mask %||% file.path(root, "preflight", "canonical_environment_mask.tif")
  args$nodes_path <- args$nodes_path %||% file.path(root, "model_data", "raw", "nodes.parquet")
  args$edges_path <- args$edges_path %||% file.path(root, "model_data", "raw", "edges_queen.parquet")
  args$weeks_path <- file.path(root, "model_data", "raw", "weeks.parquet")
  args$calendar_path <- file.path(root, "model_data", "raw", "calendar_features.parquet")
  args$static_path <- file.path(root, "model_data", "raw", "static_features.npy")
  args$dynamic_path <- file.path(root, "model_data", "raw", "dynamic_features.npy")
  args$history_path <- file.path(root, "model_data", "raw", "dynamic_history_features.npy")
  args$counts_path <- file.path(root, "model_data", "raw", "targets_count.npy")
  args$presence_path <- file.path(root, "model_data", "raw", "targets_presence.npy")
  args$feature_manifest_path <- file.path(root, "model_data", "raw", "feature_manifest.json")
  args$dataset_manifest_path <- file.path(root, "model_data", "manifests", "dataset_manifest.json")
  args$spatial_assignments_path <- file.path(root, "model_data", "splits", "spatial_node_assignments.parquet")
  args$livestock_path <- file.path(root, "preflight", "livestock_node_covariates.parquet")
  args$diagnostic_counts_path <- file.path(root, "preflight", "observation_node_week_counts.parquet")
  args
}

`%||%` <- function(x, y) if (is.null(x) || !nzchar(x)) y else x

task2d_require_files <- function(paths) {
  missing <- paths[!file.exists(paths)]
  if (length(missing)) stop("required Task-2D artifact(s) are missing:\n", paste(missing, collapse = "\n"))
}

task2d_npy_header <- function(path) {
  connection <- file(path, open = "rb")
  on.exit(close(connection), add = TRUE)
  magic <- rawToChar(readBin(connection, what = "raw", n = 6L))
  if (!identical(magic, "\x93NUMPY")) stop("not a NumPy .npy file: ", path)
  version <- readBin(connection, what = "raw", n = 2L)
  if (!identical(as.integer(version), c(1L, 0L))) stop("only NumPy .npy v1.0 is supported: ", path)
  header_length <- readBin(connection, what = "integer", n = 1L, size = 2L, endian = "little", signed = FALSE)
  header <- rawToChar(readBin(connection, what = "raw", n = header_length))
  descriptor <- sub(".*'descr'[^']*'([^']+)'.*", "\\1", header)
  shape_text <- sub(".*'shape'[^(]*\\(([^)]*)\\).*", "\\1", header)
  shape <- as.integer(trimws(strsplit(shape_text, ",", fixed = TRUE)[[1L]]))
  shape <- shape[is.finite(shape)]
  if (!length(shape) || !nzchar(descriptor)) stop("could not parse NumPy header: ", path)
  list(descr = descriptor, shape = shape, data_start = 10L + header_length, header = header)
}

task2d_npy_header_text <- function(descr, shape) {
  shape_text <- if (length(shape) == 1L) {
    sprintf("(%d,)", as.integer(shape))
  } else {
    paste0("(", paste(as.integer(shape), collapse = ", "), ")")
  }
  dictionary <- sprintf("{'descr': '%s', 'fortran_order': False, 'shape': %s, }", descr, shape_text)
  prefix_length <- 6L + 2L + 2L
  padding <- (16L - ((prefix_length + nchar(dictionary) + 1L) %% 16L)) %% 16L
  paste0(dictionary, strrep(" ", padding), "\n")
}

task2d_npy_open_write <- function(path, descr, shape) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  connection <- file(path, open = "wb")
  writeBin(charToRaw("\x93NUMPY"), connection)
  writeBin(as.raw(c(1L, 0L)), connection)
  header <- charToRaw(task2d_npy_header_text(descr, shape))
  writeBin(as.raw(c(bitwAnd(length(header), 255L), bitwAnd(length(header) %/% 256L, 255L))), connection)
  writeBin(header, connection)
  connection
}

task2d_npy_read_vector <- function(connection, n, descr) {
  if (descr == "<f4") return(readBin(connection, what = "numeric", n = n, size = 4L, endian = "little"))
  if (descr == "<i4") return(readBin(connection, what = "integer", n = n, size = 4L, endian = "little"))
  if (descr == "|u1") return(as.integer(readBin(connection, what = "raw", n = n)))
  stop("unsupported NumPy dtype: ", descr)
}

task2d_npy_write_vector <- function(connection, values, descr) {
  if (descr == "<f4") return(writeBin(as.numeric(values), connection, size = 4L, endian = "little"))
  if (descr == "<i4") return(writeBin(as.integer(values), connection, size = 4L, endian = "little"))
  if (descr == "|u1") return(writeBin(as.raw(as.integer(values)), connection, size = 1L))
  stop("unsupported NumPy dtype: ", descr)
}

task2d_npy_read_all <- function(path) {
  header <- task2d_npy_header(path)
  connection <- file(path, open = "rb")
  on.exit(close(connection), add = TRUE)
  seek(connection, where = header$data_start, origin = "start")
  values <- task2d_npy_read_vector(connection, prod(header$shape), header$descr)
  if (length(header$shape) == 1L) return(values)
  if (length(header$shape) == 2L) return(matrix(values, nrow = header$shape[[1L]], ncol = header$shape[[2L]], byrow = TRUE))
  array(values, dim = header$shape)
}

task2d_npy_subset <- function(source_path, output_path, node_indices, time_indices = NULL) {
  header <- task2d_npy_header(source_path)
  if (length(header$shape) < 2L || length(header$shape) > 3L) {
    stop("Task-2D supports only 2D or 3D arrays: ", source_path)
  }
  source_time <- header$shape[[1L]]
  source_nodes <- header$shape[[2L]]
  node_indices <- as.integer(node_indices)
  if (anyNA(node_indices) || any(node_indices < 1L) || any(node_indices > source_nodes)) {
    stop("node indices out of bounds for ", source_path)
  }
  time_indices <- time_indices %||% seq_len(source_time)
  time_indices <- as.integer(time_indices)
  if (anyNA(time_indices) || any(time_indices < 1L) || any(time_indices > source_time)) {
    stop("time indices out of bounds for ", source_path)
  }
  output_shape <- header$shape
  output_shape[[1L]] <- length(time_indices)
  output_shape[[2L]] <- length(node_indices)
  input_per_time <- prod(header$shape[-1L])
  output <- task2d_npy_open_write(output_path, header$descr, output_shape)
  on.exit(close(output), add = TRUE)
  input <- file(source_path, open = "rb")
  on.exit(close(input), add = TRUE)
  bytes <- switch(header$descr, "<f4" = 4L, "<i4" = 4L, "|u1" = 1L, stop("unsupported NumPy dtype"))
  finite <- TRUE
  for (time_index in time_indices) {
    seek(input, where = header$data_start + (time_index - 1L) * input_per_time * bytes, origin = "start")
    values <- task2d_npy_read_vector(input, input_per_time, header$descr)
    if (header$descr == "<f4") finite <- finite && all(is.finite(values))
    if (length(header$shape) == 2L) {
      selected <- values[node_indices]
    } else {
      matrix_values <- matrix(values, nrow = source_nodes, ncol = header$shape[[3L]], byrow = TRUE)
      selected <- as.numeric(t(matrix_values[node_indices, , drop = FALSE]))
    }
    task2d_npy_write_vector(output, selected, header$descr)
  }
  list(source_shape = header$shape, output_shape = output_shape, finite = finite, descr = header$descr)
}

task2d_write_table <- function(x, path_stem) {
  dir.create(dirname(path_stem), recursive = TRUE, showWarnings = FALSE)
  arrow::write_parquet(x, paste0(path_stem, ".parquet"))
  data.table::fwrite(x, paste0(path_stem, ".csv"))
  invisible(path_stem)
}

task2d_boundary_field <- function(boundary) {
  candidates <- c("iso_a2", "ISO_A2", "iso_a2_eh", "adm0_a3", "sov_a3", "country", "country_code", "admin")
  selected <- candidates[candidates %in% names(boundary)]
  if (!length(selected)) stop("boundary data need an ISO-2 or country-code field; available fields: ", paste(names(boundary), collapse = ", "))
  selected[[1L]]
}

task2d_country_codes <- function(boundary) {
  field <- task2d_boundary_field(boundary)
  values <- toupper(trimws(as.character(boundary[[field]])))
  # Natural-Earth administrative products use ISO-2 in iso_a2.  For a
  # country-name field, normalize only the two countries used by the rule.
  values[values %in% c("UNITED STATES", "UNITED STATES OF AMERICA", "USA")] <- "US"
  values[values %in% c("MEXICO")] <- "MX"
  list(field = field, values = values)
}

task2d_classify_points <- function(lon, lat, boundary_wgs84, boundary_codes) {
  valid <- is.finite(lon) & is.finite(lat) & lon >= -180 & lon <= 180 & lat >= -90 & lat <= 90
  result <- rep(NA_character_, length(lon))
  if (!any(valid)) return(result)
  points <- sf::st_as_sf(data.frame(lon = lon[valid], lat = lat[valid]), coords = c("lon", "lat"), crs = 4326, remove = FALSE)
  hits <- sf::st_intersects(points, boundary_wgs84, sparse = TRUE)
  result[which(valid)] <- vapply(hits, function(index) {
    if (!length(index)) NA_character_ else boundary_codes[[index[[1L]]]]
  }, character(1L))
  result
}

task2d_region <- function(country, lat) {
  central_america <- c("BZ", "GT", "SV", "HN", "NI", "CR", "PA")
  out <- rep("unclassified_or_outside_boundary", length(country))
  out[country == "MX"] <- "Mexico"
  out[country %in% c("US", "USA") & lat < 40] <- "U.S.-to-40N"
  out[country %in% c("US", "USA") & lat >= 40] <- "excluded-U.S.-north-of-40N"
  out[country %in% central_america & lat < 40] <- "excluded-Central-America-south-of-Mexico"
  out
}

task2d_graph_qa <- function(nodes, edges) {
  ids <- as.integer(nodes$node_id)
  edges <- edges[edges$source_node %in% ids & edges$target_node %in% ids, , drop = FALSE]
  degree <- tabulate(match(edges$source_node, ids), nbins = length(ids))
  adjacency <- vector("list", length(ids))
  if (nrow(edges)) {
    for (i in seq_len(nrow(edges))) {
      source <- match(edges$source_node[[i]], ids)
      target <- match(edges$target_node[[i]], ids)
      adjacency[[source]] <- c(adjacency[[source]], target)
      adjacency[[target]] <- c(adjacency[[target]], source)
    }
  }
  remaining <- seq_along(ids)
  component_sizes <- integer()
  while (length(remaining)) {
    queue <- remaining[[1L]]
    visited <- integer()
    while (length(queue)) {
      current <- queue[[1L]]
      queue <- queue[-1L]
      if (current %in% visited) next
      visited <- c(visited, current)
      queue <- c(queue, adjacency[[current]])
    }
    component_sizes <- c(component_sizes, length(unique(visited)))
    remaining <- setdiff(remaining, visited)
  }
  keys <- paste(edges$source_node, edges$target_node, sep = ":")
  reverse <- paste(edges$target_node, edges$source_node, sep = ":")
  list(
    node_count = length(ids),
    directed_edge_count = nrow(edges),
    undirected_edge_count = sum(edges$source_node < edges$target_node),
    mean_degree = if (length(degree)) mean(degree) else NA_real_,
    degree_min = if (length(degree)) min(degree) else NA_integer_,
    degree_max = if (length(degree)) max(degree) else NA_integer_,
    isolated_nodes = sum(degree == 0L),
    connected_components = length(component_sizes),
    component_sizes = sort(component_sizes, decreasing = TRUE),
    symmetric = setequal(keys, reverse),
    self_loops = sum(edges$source_node == edges$target_node),
    invalid_edge_count = sum(!(edges$source_node %in% ids & edges$target_node %in% ids))
  )
}

task2d_jsonable <- function(x) {
  if (inherits(x, "Date")) return(as.character(x))
  if (is.factor(x)) return(as.character(x))
  if (is.atomic(x)) return(x)
  if (is.data.frame(x)) return(lapply(x, task2d_jsonable))
  if (is.list(x)) return(lapply(x, task2d_jsonable))
  x
}

task2d_write_json <- function(x, path) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  jsonlite::write_json(task2d_jsonable(x), path, auto_unbox = TRUE, pretty = TRUE, na = "null", dataframe = "columns")
  stopifnot(jsonlite::validate(paste(readLines(path, warn = FALSE), collapse = "\n")))
}

task2d_weekly_summary <- function(weeks, counts_original, counts_revised, nodes_original, nodes_revised, observations, region_by_node) {
  n_weeks <- nrow(weeks)
  result <- data.frame(
    week_index = weeks$week_index,
    iso_week = weeks$iso_week,
    week_start = as.Date(weeks$week_start),
    week_end = as.Date(weeks$week_end),
    total_observation_records = 0L,
    positive_canonical_cells = rowSums(counts_original > 0),
    positive_revised_cells = rowSums(counts_revised > 0),
    unique_spatial_locations = 0L,
    unique_revised_domain_cells = rowSums(counts_revised > 0),
    latitude_min = NA_real_, latitude_max = NA_real_, latitude_median = NA_real_,
    longitude_min = NA_real_, longitude_max = NA_real_,
    northmost_detection_latitude = NA_real_, southmost_detection_latitude = NA_real_,
    canonical_detection_total = rowSums(counts_original),
    revised_detection_total = rowSums(counts_revised),
    revised_positive_node_weeks = rowSums(counts_revised > 0),
    stringsAsFactors = FALSE
  )
  if (nrow(observations)) {
    split_rows <- split(seq_len(nrow(observations)), observations$iso_week)
    for (week_id in names(split_rows)) {
      index <- match(week_id, result$iso_week)
      if (is.na(index)) next
      rows <- split_rows[[week_id]]
      result$total_observation_records[[index]] <- length(rows)
      locations <- unique(paste(sprintf("%.6f", observations$lon[rows]), sprintf("%.6f", observations$lat[rows]), sep = ":"))
      result$unique_spatial_locations[[index]] <- length(locations)
      lat <- observations$lat[rows]
      lon <- observations$lon[rows]
      result$latitude_min[[index]] <- min(lat)
      result$latitude_max[[index]] <- max(lat)
      result$latitude_median[[index]] <- stats::median(lat)
      result$longitude_min[[index]] <- min(lon)
      result$longitude_max[[index]] <- max(lon)
      result$northmost_detection_latitude[[index]] <- max(lat)
      result$southmost_detection_latitude[[index]] <- min(lat)
    }
  }
  for (region in unique(region_by_node)) {
    selected <- which(region_by_node == region)
    if (!length(selected)) next
    result[[paste0("positive_cells_", region)]] <- rowSums(counts_original[, selected, drop = FALSE] > 0)
  }
  result$week_number <- as.integer(format(result$week_start, "%V"))
  result$month <- as.integer(format(result$week_start, "%m"))
  result$quarter <- ((result$month - 1L) %/% 3L) + 1L
  result$calendar_season <- ifelse(result$month %in% c(12L, 1L, 2L), "winter",
    ifelse(result$month %in% 3L:5L, "spring", ifelse(result$month %in% 6L:8L, "summer", "fall")))
  result
}

task2d_candidate_metrics <- function(candidate_starts, weeks, counts_revised, nodes_revised, region_by_revised_node) {
  rows <- lapply(candidate_starts, function(start) {
    keep <- weeks$iso_week >= start
    selected <- counts_revised[keep, , drop = FALSE]
    weekly <- rowSums(selected)
    occupied <- colSums(selected > 0)
    mexico <- region_by_revised_node == "Mexico"
    united_states <- region_by_revised_node == "U.S.-to-40N"
    cv <- if (mean(weekly) > 0) stats::sd(weekly) / mean(weekly) else NA_real_
    data.frame(
      candidate_start = start,
      response_weeks = nrow(selected),
      node_count = ncol(selected),
      possible_node_weeks = nrow(selected) * ncol(selected),
      positive_node_weeks = sum(selected > 0),
      zero_node_weeks = sum(selected == 0),
      positive_fraction = mean(selected > 0),
      positive_node_weeks_per_1000 = 1000 * mean(selected > 0),
      weekly_mean_detections = mean(weekly),
      weekly_median_detections = stats::median(weekly),
      weekly_detection_cv = cv,
      fraction_weeks_ge_1 = mean(weekly >= 1),
      fraction_weeks_ge_5 = mean(weekly >= 5),
      fraction_weeks_ge_10 = mean(weekly >= 10),
      occupied_nodes = sum(occupied > 0),
      fraction_domain_nodes_ever_positive = mean(occupied > 0),
      mexico_positive_node_weeks = if (any(mexico)) sum(selected[, mexico, drop = FALSE] > 0) else 0L,
      us_positive_node_weeks = if (any(united_states)) sum(selected[, united_states, drop = FALSE] > 0) else 0L,
      revised_latitude_min = min(nodes_revised$lat),
      revised_latitude_max = max(nodes_revised$lat),
      revised_latitude_median = stats::median(nodes_revised$lat),
      stringsAsFactors = FALSE
    )
  })
  do.call(rbind, rows)
}

task2d_scenario_metrics <- function(scenarios, weeks, counts, nodes) {
  do.call(rbind, lapply(scenarios, function(scenario) {
    selected_weeks <- weeks$iso_week >= scenario$start
    selected_nodes <- scenario$node_ids
    y <- counts[selected_weeks, selected_nodes, drop = FALSE]
    weekly <- rowSums(y)
    occupied <- colSums(y > 0)
    data.frame(
      scenario = scenario$name,
      node_count = ncol(y), response_weeks = nrow(y),
      possible_node_weeks = nrow(y) * ncol(y), positive_node_weeks = sum(y > 0),
      zero_node_weeks = sum(y == 0), positive_fraction = mean(y > 0),
      positive_node_weeks_per_1000 = 1000 * mean(y > 0), occupied_nodes = sum(occupied > 0),
      fraction_weeks_ge_1 = mean(weekly >= 1), fraction_weeks_ge_5 = mean(weekly >= 5),
      fraction_weeks_ge_10 = mean(weekly >= 10), weekly_mean_detections = mean(weekly),
      weekly_median_detections = stats::median(weekly),
      weekly_detection_cv = if (mean(weekly) > 0) stats::sd(weekly) / mean(weekly) else NA_real_,
      latitude_min = min(nodes$lat[selected_nodes]), latitude_max = max(nodes$lat[selected_nodes]),
      latitude_median = stats::median(nodes$lat[selected_nodes]),
      stringsAsFactors = FALSE
    )
  }))
}

task2d_reporting_summary <- function(weeks, weekly, region_column) {
  detections <- weekly[[region_column]]
  active <- detections > 0
  previous <- rep(NA_integer_, length(active))
  last <- NA_integer_
  for (i in seq_along(active)) {
    previous[[i]] <- if (active[[i]] && !is.na(last)) i - last else NA_integer_
    if (active[[i]]) last <- i
  }
  data.frame(
    region = sub("^records_", "", region_column),
    total_detections = sum(detections),
    weeks_with_detection = sum(active),
    fraction_weeks_ge_1 = mean(detections >= 1),
    fraction_weeks_ge_5 = mean(detections >= 5),
    fraction_weeks_ge_10 = mean(detections >= 10),
    maximum_weeks_since_previous_detection = if (all(is.na(previous))) NA_integer_ else max(previous, na.rm = TRUE),
    median_weekly_detections = stats::median(detections),
    stringsAsFactors = FALSE
  )
}

task2d_save_figures <- function(output_dir, weekly, candidates, observations, boundary, nodes_original, nodes_revised, latitude_band_weekly, region_weekly) {
  task2d_require("ggplot2")
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
  p1 <- ggplot2::ggplot(weekly, ggplot2::aes(week_start, total_observation_records)) + ggplot2::geom_line() +
    ggplot2::labs(x = NULL, y = "Recorded detections", title = "Weekly recorded detections") + ggplot2::theme_minimal()
  p2 <- ggplot2::ggplot(weekly, ggplot2::aes(week_start, positive_revised_cells)) + ggplot2::geom_line() +
    ggplot2::labs(x = NULL, y = "Positive revised-domain cells", title = "Weekly positive canonical cells") + ggplot2::theme_minimal()
  p3 <- ggplot2::ggplot(weekly, ggplot2::aes(week_start)) +
    ggplot2::geom_line(ggplot2::aes(y = northmost_detection_latitude, colour = "maximum"), na.rm = TRUE) +
    ggplot2::geom_line(ggplot2::aes(y = latitude_median, colour = "median"), na.rm = TRUE) +
    ggplot2::scale_colour_manual(values = c(maximum = "#b2182b", median = "#2166ac")) +
    ggplot2::labs(x = NULL, y = "Latitude (degrees N)", colour = NULL, title = "Detection latitude through time") + ggplot2::theme_minimal()
  ggplot2::ggsave(file.path(output_dir, "01_weekly_total_detections.png"), p1, width = 10, height = 5, dpi = 160)
  ggplot2::ggsave(file.path(output_dir, "02_weekly_positive_cells.png"), p2, width = 10, height = 5, dpi = 160)
  ggplot2::ggsave(file.path(output_dir, "03_weekly_detection_latitude.png"), p3, width = 10, height = 5, dpi = 160)

  boundary_plot <- boundary
  boundary_plot$boundary_group <- ifelse(toupper(as.character(boundary_plot$country_code)) %in% c("MX", "US"), "retained-country-source", "other-boundary-source")
  nodes_original$domain_status <- "original canonical support"
  nodes_revised$domain_status <- "revised retained support"
  p4 <- ggplot2::ggplot() + ggplot2::geom_sf(data = boundary_plot, ggplot2::aes(fill = boundary_group), colour = NA, alpha = 0.22) +
    ggplot2::geom_point(data = nodes_original, ggplot2::aes(lon, lat), size = 0.08, colour = "grey45", alpha = 0.35) +
    ggplot2::geom_point(data = nodes_revised, ggplot2::aes(lon, lat), size = 0.10, colour = "#2166ac", alpha = 0.45) +
    ggplot2::coord_sf(xlim = range(nodes_original$lon), ylim = range(nodes_original$lat), expand = FALSE) +
    ggplot2::labs(title = "Original versus revised canonical domain", x = "Longitude", y = "Latitude", fill = NULL) + ggplot2::theme_minimal()
  p5 <- ggplot2::ggplot() + ggplot2::geom_sf(data = boundary_plot, fill = "grey92", colour = "grey75", linewidth = 0.1) +
    ggplot2::geom_point(data = observations, ggplot2::aes(lon, lat, colour = as.Date(date)), size = 0.15, alpha = 0.25) +
    ggplot2::coord_sf(xlim = range(nodes_original$lon), ylim = range(nodes_original$lat), expand = FALSE) +
    ggplot2::scale_colour_viridis_c() + ggplot2::labs(title = "Recorded detections coloured by date", x = "Longitude", y = "Latitude", colour = "Date") + ggplot2::theme_minimal()
  ggplot2::ggsave(file.path(output_dir, "04_original_vs_revised_domain.png"), p4, width = 10, height = 7, dpi = 160)
  ggplot2::ggsave(file.path(output_dir, "05_detections_coloured_by_time.png"), p5, width = 10, height = 7, dpi = 160)

  p6 <- ggplot2::ggplot(candidates, ggplot2::aes(candidate_start, positive_fraction)) + ggplot2::geom_col(fill = "#2166ac") +
    ggplot2::scale_y_continuous(labels = scales::percent_format(accuracy = 0.01)) + ggplot2::labs(x = "Candidate response start", y = "Positive node-week fraction", title = "Information density by candidate response start") + ggplot2::theme_minimal()
  ggplot2::ggsave(file.path(output_dir, "06_candidate_start_prevalence.png"), p6, width = 8, height = 5, dpi = 160)

  p7 <- ggplot2::ggplot(region_weekly, ggplot2::aes(week_start, detections, colour = region)) + ggplot2::geom_line() +
    ggplot2::labs(x = NULL, y = "Recorded detections", colour = NULL, title = "Weekly Mexico versus U.S. detections") + ggplot2::theme_minimal()
  ggplot2::ggsave(file.path(output_dir, "07_mexico_us_weekly_detections.png"), p7, width = 10, height = 5, dpi = 160)

  p8 <- ggplot2::ggplot(latitude_band_weekly, ggplot2::aes(week_start, positive_cells, fill = latitude_band)) + ggplot2::geom_area(position = "stack") +
    ggplot2::labs(x = NULL, y = "Positive cells", fill = "Latitude band", title = "Positive cells by latitude band") + ggplot2::theme_minimal()
  ggplot2::ggsave(file.path(output_dir, "08_latitude_band_positive_cells.png"), p8, width = 10, height = 5, dpi = 160)
}
