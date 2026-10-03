#!/usr/bin/env Rscript

# Task 2D: revised analysis domain and observation-regime audit.
# This script is descriptive only. It does not fit a model and never computes
# predictive metrics.

script_argument <- commandArgs()[grep("^--file=", commandArgs())]
script_path <- if (length(script_argument)) sub("^--file=", "", script_argument[[1L]]) else "scripts/run_revised_domain_audit.R"
repository_root <- normalizePath(file.path(dirname(script_path), ".."), winslash = "/", mustWork = TRUE)
setwd(repository_root)

source("R/date_utils.R")
source("R/grid_graph.R")
source("R/revised_domain_audit.R")

task2d_require(c("arrow", "data.table", "digest", "jsonlite", "sf", "terra", "ggplot2", "scales"))
arguments <- task2d_resolve_paths(task2d_parse_args(commandArgs(trailingOnly = TRUE)))

if (arguments$analysis_end < arguments$analysis_start) stop("analysis end precedes analysis start")
task2d_require_files(c(
  arguments$observation_path, arguments$boundary_path, arguments$canonical_mask,
  arguments$nodes_path, arguments$edges_path, arguments$weeks_path,
  arguments$static_path, arguments$dynamic_path, arguments$history_path,
  arguments$counts_path, arguments$presence_path
))

output_root <- arguments$output_root
revised_root <- file.path(output_root, "revised_domain")
directories <- file.path(revised_root, c("raw", "graph", "diagnostics", "tables", "figures", "manifests"))
invisible(lapply(directories, dir.create, recursive = TRUE, showWarnings = FALSE))
dir.create(file.path(output_root, "manifests"), recursive = TRUE, showWarnings = FALSE)

message("Reading frozen Task-2A canonical artifacts")
nodes <- arrow::read_parquet(arguments$nodes_path, as_data_frame = TRUE)
edges <- arrow::read_parquet(arguments$edges_path, as_data_frame = TRUE)
if (!all(c("node_id", "raster_cell", "row", "column") %in% names(nodes))) stop("canonical node table has an unsupported schema")
if (!all(c("source_node", "target_node") %in% names(edges))) stop("canonical edge table has an unsupported schema")
if (!identical(as.integer(nodes$node_id), seq.int(0L, nrow(nodes) - 1L))) stop("canonical node IDs are not zero-based contiguous")
if (any(edges$source_node < 0L | edges$target_node < 0L | edges$source_node >= nrow(nodes) | edges$target_node >= nrow(nodes))) stop("canonical graph contains an out-of-range edge")

weeks <- arrow::read_parquet(arguments$weeks_path, as_data_frame = TRUE)
if (!all(c("iso_week", "week_start", "week_end") %in% names(weeks))) stop("weeks table lacks the required ISO-week fields")
weeks$week_index <- if ("week_index" %in% names(weeks)) as.integer(weeks$week_index) else seq_len(nrow(weeks)) - 1L
weeks$week_start <- as.Date(weeks$week_start)
weeks$week_end <- as.Date(weeks$week_end)
if (any(weeks$week_start < arguments$analysis_start | weeks$week_end > arguments$analysis_end)) stop("source weeks extend outside requested audit interval")

counts_original <- task2d_npy_read_all(arguments$counts_path)
presence_original <- task2d_npy_read_all(arguments$presence_path)
if (!is.matrix(counts_original) || !identical(dim(counts_original), c(nrow(weeks), nrow(nodes)))) stop("targets_count.npy shape does not match canonical weeks/nodes")
if (!is.matrix(presence_original) || !identical(dim(presence_original), dim(counts_original))) stop("targets_presence.npy shape does not match targets_count.npy")
if (any(!is.finite(counts_original)) || any(counts_original < 0)) stop("counts contain non-finite or negative values")
if (!isTRUE(all.equal(presence_original > 0, counts_original > 0))) stop("presence is not exactly count > 0")

static_header <- task2d_npy_header(arguments$static_path)
static_original <- task2d_npy_read_all(arguments$static_path)
if (!is.matrix(static_original) || nrow(static_original) != nrow(nodes)) stop("static_features.npy shape does not match canonical nodes")
if (ncol(static_original) < 10L) stop("static feature tensor must contain five densities and five indicators")
if (any(!is.finite(static_original))) stop("static features contain non-finite values")
if (any(static_original[, seq_len(5L)] < 0)) stop("livestock density features contain negative values")
if (!all(static_original[, 6:10] %in% c(0, 1))) stop("livestock imputation indicators are not binary")

if (file.exists(arguments$feature_manifest_path)) {
  feature_manifest <- jsonlite::fromJSON(arguments$feature_manifest_path, simplifyVector = FALSE)
} else {
  feature_manifest <- list()
}

message("Constructing fixed-boundary geographic mask")
boundary_layers <- sf::st_layers(arguments$boundary_path)
boundary_layer <- arguments$boundary_layer
if (!nzchar(boundary_layer)) boundary_layer <- if ("study_states" %in% boundary_layers$name) "study_states" else boundary_layers$name[[1L]]
boundary <- sf::st_read(arguments$boundary_path, layer = boundary_layer, quiet = TRUE)
boundary <- sf::st_make_valid(boundary)
boundary_wgs84 <- sf::st_transform(boundary, 4326)
boundary_code_info <- task2d_country_codes(boundary_wgs84)
boundary_wgs84$country_code <- boundary_code_info$values

canonical_mask <- terra::rast(arguments$canonical_mask)
mask_values <- terra::values(canonical_mask, mat = FALSE)
if (max(nodes$raster_cell, na.rm = TRUE) > length(mask_values)) stop("canonical node raster cells exceed canonical mask")
if (!all(c("x", "y") %in% names(nodes))) {
  xy <- terra::xyFromCell(canonical_mask, nodes$raster_cell)
  nodes$x <- xy[, 1L]
  nodes$y <- xy[, 2L]
}
if (!all(c("lon", "lat") %in% names(nodes))) {
  xy <- as.matrix(nodes[, c("x", "y")])
  node_points <- terra::vect(data.frame(x = xy[, 1L], y = xy[, 2L]), geom = c("x", "y"), crs = terra::crs(canonical_mask))
  lonlat <- terra::crds(terra::project(node_points, "EPSG:4326"))
  nodes$lon <- lonlat[, 1L]
  nodes$lat <- lonlat[, 2L]
}

node_country <- task2d_classify_points(nodes$lon, nodes$lat, boundary_wgs84, boundary_wgs84$country_code)
node_region <- task2d_region(node_country, nodes$lat)
retain <- node_country %in% c("MX") | (node_country %in% c("US", "USA") & nodes$lat < 40)
if (!any(retain)) stop("fixed geographic rule retained zero canonical nodes; inspect boundary CRS/country field")
if (!any(node_country == "MX")) stop("fixed geographic rule found no Mexico canonical cells")
if (anyNA(node_country[retain])) stop("retained geographic-domain cells are not covered by the boundary data")
if (anyNA(mask_values[nodes$raster_cell[retain]])) stop("geographic-domain cells are not contained in canonical environmental support")

canonical_nodes <- nodes
canonical_nodes$canonical_node_id <- as.integer(canonical_nodes$node_id)
canonical_graph_nodes <- canonical_nodes
canonical_graph_nodes$node_id <- canonical_graph_nodes$canonical_node_id
original_graph_qa <- task2d_graph_qa(canonical_graph_nodes, edges)

retained_canonical_ids <- canonical_nodes$canonical_node_id[retain]
revised_nodes <- canonical_nodes[retain, c("canonical_node_id", "raster_cell", "row", "column", "x", "y", "lon", "lat"), drop = FALSE]
revised_nodes$model_node_id <- seq_len(nrow(revised_nodes)) - 1L
revised_nodes$country_or_domain_region <- ifelse(node_country[retain] == "MX", "Mexico", "U.S.-to-40N")
revised_nodes <- revised_nodes[, c("model_node_id", "canonical_node_id", "raster_cell", "row", "column", "x", "y", "lon", "lat", "country_or_domain_region")]
if (!identical(revised_nodes$model_node_id, seq_len(nrow(revised_nodes)) - 1L) || anyDuplicated(revised_nodes$canonical_node_id)) stop("revised node mapping is not contiguous and unique")
revised_graph_nodes <- revised_nodes
revised_graph_nodes$node_id <- revised_graph_nodes$model_node_id

edge_keep <- edges$source_node %in% retained_canonical_ids & edges$target_node %in% retained_canonical_ids
revised_edges <- edges[edge_keep, c("source_node", "target_node"), drop = FALSE]
source_map <- revised_nodes$model_node_id
names(source_map) <- as.character(revised_nodes$canonical_node_id)
revised_edges$source_canonical_node_id <- as.integer(revised_edges$source_node)
revised_edges$target_canonical_node_id <- as.integer(revised_edges$target_node)
revised_edges$source_node <- as.integer(unname(source_map[as.character(revised_edges$source_node)]))
revised_edges$target_node <- as.integer(unname(source_map[as.character(revised_edges$target_node)]))
revised_edges <- revised_edges[order(revised_edges$source_node, revised_edges$target_node), , drop = FALSE]
revised_graph_qa <- task2d_graph_qa(revised_graph_nodes, revised_edges[, c("source_node", "target_node")])

task2d_write_table(revised_nodes, file.path(revised_root, "raw", "nodes"))
task2d_write_table(revised_edges, file.path(revised_root, "graph", "edges_queen"))
task2d_write_json(list(original = original_graph_qa, revised = revised_graph_qa), file.path(revised_root, "graph", "graph_summary.json"))

revised_indices <- which(retain)
counts_revised <- counts_original[, revised_indices, drop = FALSE]
presence_revised <- counts_revised > 0
region_by_canonical_node <- node_region
region_by_revised_node <- revised_nodes$country_or_domain_region

message("Reading and classifying observations")
observations <- data.table::fread(arguments$observation_path, showProgress = FALSE)
if (!all(c("date", "lon", "lat") %in% names(observations))) stop("observation CSV must contain date, lon, and lat")
observations$date <- parse_strict_date(observations$date)
observations$lon <- suppressWarnings(as.numeric(observations$lon))
observations$lat <- suppressWarnings(as.numeric(observations$lat))
observations <- observations[!is.na(observations$date) & is.finite(observations$lon) & is.finite(observations$lat), , drop = FALSE]
observations <- observations[observations$date >= arguments$analysis_start & observations$date <= arguments$analysis_end, , drop = FALSE]
observations$iso_week <- iso_week_id(observations$date)
observations <- observations[observations$iso_week %in% weeks$iso_week, , drop = FALSE]
observations$country_code <- task2d_classify_points(observations$lon, observations$lat, boundary_wgs84, boundary_wgs84$country_code)
observations$broad_region <- task2d_region(observations$country_code, observations$lat)

projected_points <- terra::project(terra::vect(observations, geom = c("lon", "lat"), crs = "EPSG:4326"), terra::crs(canonical_mask))
observation_cells <- terra::cellFromXY(canonical_mask, terra::crds(projected_points))
cell_to_canonical <- canonical_nodes$canonical_node_id
names(cell_to_canonical) <- as.character(canonical_nodes$raster_cell)
observations$canonical_node_id <- as.integer(unname(cell_to_canonical[as.character(observation_cells)]))
observations$revised_model_node_id <- as.integer(unname(source_map[as.character(observations$canonical_node_id)]))
observations$within_revised_domain <- !is.na(observations$revised_model_node_id)
observations$date <- as.Date(observations$date)

weekly <- task2d_weekly_summary(weeks, counts_original, counts_revised, canonical_nodes, revised_nodes, observations, node_region)
for (region in unique(observations$broad_region)) {
  rows <- observations$broad_region == region
  if (!any(rows)) next
  values <- table(factor(observations$iso_week[rows], levels = weeks$iso_week))
  column <- paste0("records_", region)
  if (!column %in% names(weekly)) weekly[[column]] <- 0L
  weekly[[column]] <- as.integer(values)
}
for (region in c("Mexico", "U.S.-to-40N", "excluded-Central-America-south-of-Mexico")) {
  column <- paste0("records_", region)
  if (!column %in% names(weekly)) weekly[[column]] <- integer(nrow(weekly))
}
region_columns <- grep("^records_", names(weekly), value = TRUE)
for (column in region_columns) {
  detections <- weekly[[column]]
  gaps <- rep(NA_integer_, length(detections))
  last_detection <- NA_integer_
  for (i in seq_along(detections)) {
    if (detections[[i]] > 0 && !is.na(last_detection)) gaps[[i]] <- i - last_detection
    if (detections[[i]] > 0) last_detection <- i
  }
  weekly[[sub("^records_", "weeks_since_previous_", column)]] <- gaps
}

revised_observations <- observations[observations$within_revised_domain, , drop = FALSE]
weekly$revised_latitude_q25 <- NA_real_
weekly$revised_latitude_q75 <- NA_real_
weekly$revised_northmost_detection_latitude <- NA_real_
weekly$revised_southmost_detection_latitude <- NA_real_
if (nrow(revised_observations)) {
  grouped <- split(seq_len(nrow(revised_observations)), revised_observations$iso_week)
  for (week_id in names(grouped)) {
    index <- match(week_id, weekly$iso_week)
    values <- revised_observations$lat[grouped[[week_id]]]
    weekly$revised_latitude_q25[[index]] <- as.numeric(stats::quantile(values, 0.25, names = FALSE))
    weekly$revised_latitude_q75[[index]] <- as.numeric(stats::quantile(values, 0.75, names = FALSE))
    weekly$revised_northmost_detection_latitude[[index]] <- max(values)
    weekly$revised_southmost_detection_latitude[[index]] <- min(values)
  }
}
weekly$week_number <- as.integer(format(weekly$week_start, "%V"))
weekly$month <- as.integer(format(weekly$week_start, "%m"))
weekly$quarter <- ((weekly$month - 1L) %/% 3L) + 1L
weekly$calendar_season <- ifelse(weekly$month %in% c(12L, 1L, 2L), "winter", ifelse(weekly$month %in% 3L:5L, "spring", ifelse(weekly$month %in% 6L:8L, "summer", "fall")))

candidate_starts <- c("2025-W01", "2025-W05", "2025-W09", "2025-W13")
candidates <- task2d_candidate_metrics(candidate_starts, weeks, counts_revised, revised_nodes, region_by_revised_node)

scenario_definitions <- list(
  list(name = "A_original_domain_2024-W01", start = "2024-W01", node_ids = seq_len(nrow(canonical_nodes))),
  list(name = "B_revised_domain_2024-W01", start = "2024-W01", node_ids = revised_indices),
  list(name = "C_revised_domain_2025-W01", start = "2025-W01", node_ids = revised_indices),
  list(name = "D_revised_domain_2025-W05", start = "2025-W05", node_ids = revised_indices),
  list(name = "E_revised_domain_2025-W09", start = "2025-W09", node_ids = revised_indices),
  list(name = "F_revised_domain_2025-W13", start = "2025-W13", node_ids = revised_indices)
)
scenarios <- task2d_scenario_metrics(scenario_definitions, weeks, counts_original, canonical_nodes)
scenarios$domain_label <- sub("_[0-9]{4}-W[0-9]{2}$", "", scenarios$scenario)

message("Building regional, latitude-band, and seasonal summaries")
region_levels <- c("Mexico", "U.S.-to-40N", "excluded-Central-America-south-of-Mexico")
regional_summary <- do.call(rbind, lapply(region_levels, function(region) {
  node_selection <- region_by_canonical_node == region
  raw_selection <- observations$broad_region == region
  node_counts <- counts_original[, node_selection, drop = FALSE]
  detection_weeks <- rowSums(node_counts) > 0
  data.frame(
    region = region,
    nodes = sum(node_selection),
    possible_node_weeks_2025_plus = sum(weeks$iso_week >= "2025-W01") * sum(node_selection),
    positive_node_weeks_2024_W01_2026_W29 = sum(node_counts > 0),
    detections_2024_W01_2026_W29 = if (any(raw_selection)) sum(raw_selection) else 0L,
    occupied_nodes_2024_W01_2026_W29 = sum(colSums(node_counts > 0) > 0),
    weeks_with_any_node_detection = sum(detection_weeks),
    fraction_weeks_with_any_node_detection = mean(detection_weeks),
    stringsAsFactors = FALSE
  )
}))

climate_zone <- rep("other_or_unclassified", nrow(observations))
climate_zone[observations$country_code == "MX" & observations$lat < 20] <- "southern-Mexico"
climate_zone[observations$country_code == "MX" & observations$lat >= 20] <- "central-northern-Mexico"
climate_zone[observations$country_code %in% c("US", "USA") & observations$lat < 35] <- "southern-U.S."
observations$climate_zone <- climate_zone
climate_zone_levels <- c("southern-Mexico", "central-northern-Mexico", "southern-U.S.", "other_or_unclassified")
climate_zone_summary <- do.call(rbind, lapply(climate_zone_levels, function(zone) {
  selected <- observations$climate_zone == zone
  revised_cells <- observations$revised_model_node_id[selected]
  revised_cells <- revised_cells[!is.na(revised_cells)]
  data.frame(
    climate_zone = zone,
    detections = sum(selected), positive_cells = length(unique(revised_cells)),
    weeks_with_detections = length(unique(observations$iso_week[selected])),
    winter_detections = sum(selected & weekly$calendar_season[match(observations$iso_week, weekly$iso_week)] == "winter"),
    spring_detections = sum(selected & weekly$calendar_season[match(observations$iso_week, weekly$iso_week)] == "spring"),
    summer_detections = sum(selected & weekly$calendar_season[match(observations$iso_week, weekly$iso_week)] == "summer"),
    fall_detections = sum(selected & weekly$calendar_season[match(observations$iso_week, weekly$iso_week)] == "fall"),
    stringsAsFactors = FALSE
  )
}))

us_nodes <- region_by_revised_node == "U.S.-to-40N"
us_response <- counts_revised[weeks$iso_week >= "2025-W01", us_nodes, drop = FALSE]
us_observations <- observations$broad_region == "U.S.-to-40N"
us_week_ids <- weeks$iso_week[rowSums(us_response) > 0]
us_summary <- data.frame(
  us_nodes = sum(us_nodes), us_possible_node_weeks = nrow(us_response) * sum(us_nodes),
  us_positive_node_weeks = if (any(us_nodes)) sum(us_response > 0) else 0L,
  us_detections = sum(us_observations),
  us_occupied_nodes = if (any(us_nodes)) sum(colSums(us_response > 0) > 0) else 0L,
  us_weeks_with_any_detection = length(us_week_ids),
  us_first_detection_week = if (length(us_week_ids)) min(us_week_ids) else NA_character_,
  us_latest_detection_week = if (length(us_week_ids)) max(us_week_ids) else NA_character_,
  stringsAsFactors = FALSE
)

removed_nodes <- !retain
removed_observations <- observations$canonical_node_id %in% canonical_nodes$canonical_node_id[removed_nodes]
removed_observation_dates <- observations$date[removed_observations]
removed_weekly <- table(factor(observations$iso_week[removed_observations], levels = weeks$iso_week))
excluded_summary <- data.frame(
  removed_nodes = sum(removed_nodes), removed_detections = sum(removed_observations),
  removed_positive_node_weeks = sum(counts_original[, removed_nodes, drop = FALSE] > 0),
  removed_observation_date_min = if (length(removed_observation_dates)) min(removed_observation_dates) else as.Date(NA),
  removed_observation_date_max = if (length(removed_observation_dates)) max(removed_observation_dates) else as.Date(NA),
  removed_weeks_with_detection = sum(removed_weekly > 0), removed_fraction_weeks_with_detection = mean(removed_weekly > 0),
  stringsAsFactors = FALSE
)

latitude_breaks <- c(-Inf, 15, 20, 25, 30, 35, 40)
latitude_labels <- c("<15N", "15-20N", "20-25N", "25-30N", "30-35N", "35-40N")
node_bands <- cut(revised_nodes$lat, breaks = latitude_breaks, labels = latitude_labels, right = FALSE)
latitude_band_weekly <- do.call(rbind, lapply(seq_len(nrow(weeks)), function(i) {
  do.call(rbind, lapply(latitude_labels, function(band) {
    selected <- node_bands == band
    data.frame(
      week_index = weeks$week_index[[i]], iso_week = weeks$iso_week[[i]], week_start = weeks$week_start[[i]], latitude_band = band,
      positive_cells = if (any(selected)) sum(counts_revised[i, selected] > 0) else 0L,
      detections = if (any(selected)) sum(counts_revised[i, selected]) else 0L, stringsAsFactors = FALSE
    )
  }))
}))

seasonal_period <- weekly$iso_week >= "2025-W01"
seasonal_summary <- do.call(rbind, lapply(c("winter", "spring", "summer", "fall"), function(season) {
  selected_weeks <- seasonal_period & weekly$calendar_season == season
  selected_observations <- revised_observations$iso_week %in% weekly$iso_week[selected_weeks]
  y <- counts_revised[selected_weeks, , drop = FALSE]
  data.frame(
    season = season, weeks = sum(selected_weeks), detections = sum(selected_observations), positive_node_weeks = sum(y > 0),
    occupied_nodes = if (ncol(y)) sum(colSums(y > 0) > 0) else 0L,
    weeks_with_any_detection = if (nrow(y)) sum(rowSums(y) > 0) else 0L,
    fraction_weeks_with_any_detection = if (nrow(y)) mean(rowSums(y) > 0) else NA_real_, stringsAsFactors = FALSE
  )
}))
iso_week_coverage <- weekly[seasonal_period, c("iso_week", "week_number", "revised_detection_total", "positive_revised_cells")]
month_coverage <- aggregate(cbind(revised_detection_total, positive_revised_cells) ~ month, data = weekly[seasonal_period, ], FUN = sum)
quarter_coverage <- aggregate(cbind(revised_detection_total, positive_revised_cells) ~ quarter, data = weekly[seasonal_period, ], FUN = sum)

regional_weekly <- do.call(rbind, lapply(region_levels, function(region) {
  column <- paste0("records_", region)
  data.frame(week_start = weekly$week_start, iso_week = weekly$iso_week, region = region, detections = weekly[[column]], stringsAsFactors = FALSE)
}))
progression_summary <- weekly[, c("week_index", "iso_week", "week_start", "revised_northmost_detection_latitude", "latitude_median", "revised_latitude_q25", "revised_latitude_q75", "positive_revised_cells")]

message("Auditing candidate start and validation feasibility")
candidate_screen <- do.call(rbind, lapply(candidate_starts, function(start) {
  index <- match(start, weekly$iso_week)
  first_thirteen <- weekly$revised_detection_total[index:min(index + 12L, nrow(weekly))]
  active <- first_thirteen > 0
  gaps <- integer()
  last <- NA_integer_
  for (j in seq_along(active)) {
    if (active[[j]] && !is.na(last)) gaps <- c(gaps, j - last)
    if (active[[j]]) last <- j
  }
  candidate_record <- candidates[candidates$candidate_start == start, , drop = FALSE]
  data.frame(
    candidate_start = start,
    first_13_week_reporting_fraction = mean(active),
    first_13_week_max_gap = if (length(gaps)) max(gaps) else Inf,
    response_weeks = candidate_record$response_weeks,
    descriptive_start_eligible = candidate_record$response_weeks >= 52L && mean(active) >= 0.75 && (if (length(gaps)) max(gaps) else Inf) <= 4L,
    stringsAsFactors = FALSE
  )
}))
eligible <- candidate_screen$candidate_start[candidate_screen$descriptive_start_eligible]
recommended_start <- if (length(eligible)) eligible[[1L]] else candidate_starts[[1L]]
recommendation_basis <- if (length(eligible)) "earliest candidate retaining at least 52 response weeks, >=75% reporting coverage in its first 13 weeks, and no early reporting gap >4 weeks; no predictive metric used" else "2025-W01 retained as the preferred full-cycle default; early coverage screen did not pass for any candidate"

validation_feasibility <- do.call(rbind, lapply(candidate_starts, function(start) {
  n <- candidates$response_weeks[candidates$candidate_start == start]
  data.frame(
    candidate_start = start, response_weeks = n,
    feasible_3_folds_8_week_validation_plus_13_week_test = n >= (3L * 8L + 13L),
    feasible_4_folds_8_week_validation_plus_13_week_test = n >= (4L * 8L + 13L),
    feasible_3_folds_13_week_validation_plus_13_week_test = n >= (3L * 13L + 13L),
    feasible_4_folds_13_week_validation_plus_13_week_test = n >= (4L * 13L + 13L),
    weeks_after_4x13_validation_plus_13_week_test = n - (4L * 13L + 13L), stringsAsFactors = FALSE
  )
}))

if (file.exists(arguments$spatial_assignments_path)) {
  spatial_assignments <- arrow::read_parquet(arguments$spatial_assignments_path, as_data_frame = TRUE)
  spatial_id_col <- if ("node_id" %in% names(spatial_assignments)) "node_id" else names(spatial_assignments)[[1L]]
  spatial_fold_candidates <- grep("fold", names(spatial_assignments), value = TRUE)
  spatial_fold_col <- if ("spatial_fold" %in% names(spatial_assignments)) "spatial_fold" else spatial_fold_candidates[[1L]]
  assigned_folds <- spatial_assignments[[spatial_fold_col]][match(revised_nodes$canonical_node_id, spatial_assignments[[spatial_id_col]])]
  spatial_block_candidates <- grep("block", names(spatial_assignments), value = TRUE)
  spatial_block_ids <- if (length(spatial_block_candidates)) spatial_assignments[[spatial_block_candidates[[1L]]]][match(revised_nodes$canonical_node_id, spatial_assignments[[spatial_id_col]])] else NULL
  block_source <- "existing Task-2A spatial assignments subset to revised nodes"
  block_key <- NULL
} else {
  block_key <- paste(floor((revised_nodes$row - 1L) / 5L), floor((revised_nodes$column - 1L) / 5L), sep = ":")
  block_levels <- sort(unique(block_key))
  assigned_folds <- (match(block_key, block_levels) - 1L) %% 5L
  spatial_block_ids <- block_key
  block_source <- "audit-only 5x5 full-raster blocks; existing persisted assignments were unavailable"
}
if (anyNA(assigned_folds)) stop("revised nodes are missing spatial-block assignments")
spatial_fold_summary <- data.frame(spatial_fold = sort(unique(assigned_folds)), nodes = as.integer(table(factor(assigned_folds, levels = sort(unique(assigned_folds))))), stringsAsFactors = FALSE)
spatial_audit <- list(
  source = block_source,
  number_spatial_blocks = if (is.null(spatial_block_ids)) NA_integer_ else length(unique(spatial_block_ids)),
  nodes_per_block_min = if (is.null(spatial_block_ids)) NA_integer_ else min(table(spatial_block_ids)),
  nodes_per_block_max = if (is.null(spatial_block_ids)) NA_integer_ else max(table(spatial_block_ids)),
  candidate_five_fold_balance = spatial_fold_summary,
  revised_graph_components = revised_graph_qa$connected_components,
  revised_isolated_nodes = revised_graph_qa$isolated_nodes
)

message("Writing revised raw tensors and audit tables")
raw_output <- file.path(revised_root, "raw")
dynamic_subset <- task2d_npy_subset(arguments$dynamic_path, file.path(raw_output, "dynamic_features.npy"), revised_indices)
history_subset <- task2d_npy_subset(arguments$history_path, file.path(raw_output, "dynamic_history_features.npy"), revised_indices)
counts_subset <- task2d_npy_subset(arguments$counts_path, file.path(raw_output, "targets_count.npy"), revised_indices)
presence_subset <- task2d_npy_subset(arguments$presence_path, file.path(raw_output, "targets_presence.npy"), revised_indices)
if (!identical(as.integer(dynamic_subset$output_shape), c(nrow(weeks), nrow(revised_nodes), 12L))) stop("revised dynamic feature tensor shape is not [weeks, nodes, 12]")
if (length(history_subset$output_shape) != 3L || history_subset$output_shape[[2L]] != nrow(revised_nodes) || history_subset$output_shape[[3L]] != 12L || history_subset$output_shape[[1L]] < nrow(weeks)) stop("revised environmental history tensor shape is invalid")
if (!identical(as.integer(counts_subset$output_shape), c(nrow(weeks), nrow(revised_nodes)))) stop("revised target tensor shape is invalid")
if (!identical(as.integer(presence_subset$output_shape), c(nrow(weeks), nrow(revised_nodes)))) stop("revised presence tensor shape is invalid")
static_revised <- static_original[revised_indices, , drop = FALSE]
static_output <- task2d_npy_open_write(file.path(raw_output, "static_features.npy"), static_header$descr, dim(static_revised))
task2d_npy_write_vector(static_output, as.numeric(t(static_revised)), static_header$descr)
close(static_output)
if (!dynamic_subset$finite || !history_subset$finite) stop("environmental tensors contain non-finite values")

arrow::write_parquet(weeks, file.path(raw_output, "weeks.parquet"))
arrow::write_parquet(revised_nodes, file.path(raw_output, "nodes.parquet"))
arrow::write_parquet(revised_edges, file.path(raw_output, "edges_queen.parquet"))
if (file.exists(arguments$calendar_path)) {
  calendar <- arrow::read_parquet(arguments$calendar_path, as_data_frame = TRUE)
  if (!all(c("week_sin", "week_cos") %in% names(calendar))) stop("calendar feature table lacks week_sin/week_cos")
  expected_sin <- sin(2 * pi * weeks$week_index / 52.1775)
  expected_cos <- cos(2 * pi * weeks$week_index / 52.1775)
  if (!isTRUE(all.equal(as.numeric(calendar$week_sin), expected_sin, tolerance = 2e-5)) || !isTRUE(all.equal(as.numeric(calendar$week_cos), expected_cos, tolerance = 2e-5))) stop("calendar features do not match the approved continuous annual phase")
  arrow::write_parquet(calendar, file.path(raw_output, "calendar_features.parquet"))
}
history_start <- weeks$week_start[[1L]] - 7L * (history_subset$output_shape[[1L]] - nrow(weeks))
history_dates <- seq(history_start, by = "7 days", length.out = history_subset$output_shape[[1L]])
history_weeks <- data.frame(history_index = seq_along(history_dates) - 1L, iso_week = iso_week_id(history_dates), week_start = history_dates, week_end = history_dates + 6L, stringsAsFactors = FALSE)
arrow::write_parquet(history_weeks, file.path(raw_output, "history_weeks.parquet"))
response_masks <- data.frame(week_index = weeks$week_index, iso_week = weeks$iso_week, response_end = "2026-W29", stringsAsFactors = FALSE)
for (start in candidate_starts) response_masks[[paste0("response_", gsub("-", "_", start))]] <- weeks$iso_week >= start
task2d_write_table(response_masks, file.path(revised_root, "diagnostics", "response_masks"))

static_feature_names <- if (!is.null(feature_manifest$static_feature_names)) unlist(feature_manifest$static_feature_names) else c("cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density", "cattle_density_imputed", "goat_density_imputed", "sheep_density_imputed", "horse_density_imputed", "pig_density_imputed")
static_table <- data.frame(model_node_id = revised_nodes$model_node_id, canonical_node_id = revised_nodes$canonical_node_id, static_revised, check.names = FALSE)
names(static_table)[seq.int(3L, 2L + ncol(static_revised))] <- static_feature_names[seq_len(ncol(static_revised))]
arrow::write_parquet(static_table, file.path(raw_output, "static_features.parquet"))
task2d_write_json(list(node_count = nrow(static_revised), finite = all(is.finite(static_revised)), density_nonnegative = all(static_revised[, seq_len(5L)] >= 0), imputation_indicator_counts = colSums(static_revised[, 6:10, drop = FALSE])), file.path(revised_root, "diagnostics", "livestock_qa.json"))

task2d_write_table(weekly, file.path(revised_root, "tables", "weekly_observation_regime"))
task2d_write_table(candidates, file.path(revised_root, "tables", "candidate_start_comparison"))
task2d_write_table(scenarios, file.path(revised_root, "tables", "original_vs_revised_domain"))
task2d_write_table(latitude_band_weekly, file.path(revised_root, "tables", "latitude_band_weekly"))
task2d_write_table(regional_summary, file.path(revised_root, "tables", "mexico_us_excluded_summary"))
task2d_write_table(regional_weekly, file.path(revised_root, "tables", "mexico_us_weekly"))
task2d_write_table(climate_zone_summary, file.path(revised_root, "tables", "climate_zone_coverage"))
task2d_write_table(progression_summary, file.path(revised_root, "tables", "northward_progression"))
task2d_write_table(seasonal_summary, file.path(revised_root, "tables", "seasonal_coverage"))
task2d_write_table(iso_week_coverage, file.path(revised_root, "tables", "seasonal_iso_week_coverage"))
task2d_write_table(month_coverage, file.path(revised_root, "tables", "seasonal_month_coverage"))
task2d_write_table(quarter_coverage, file.path(revised_root, "tables", "seasonal_quarter_coverage"))
task2d_write_table(candidate_screen, file.path(revised_root, "tables", "candidate_start_screen"))
task2d_write_table(validation_feasibility, file.path(revised_root, "tables", "validation_feasibility"))
task2d_write_table(spatial_fold_summary, file.path(revised_root, "tables", "spatial_fold_balance"))
task2d_write_table(us_summary, file.path(revised_root, "tables", "us_coverage"))
task2d_write_table(excluded_summary, file.path(revised_root, "tables", "excluded_central_america_summary"))
graph_summary_table <- data.frame(
  domain = c("original", "revised"),
  node_count = c(original_graph_qa$node_count, revised_graph_qa$node_count),
  directed_edge_count = c(original_graph_qa$directed_edge_count, revised_graph_qa$directed_edge_count),
  undirected_edge_count = c(original_graph_qa$undirected_edge_count, revised_graph_qa$undirected_edge_count),
  mean_degree = c(original_graph_qa$mean_degree, revised_graph_qa$mean_degree),
  connected_components = c(original_graph_qa$connected_components, revised_graph_qa$connected_components),
  isolated_nodes = c(original_graph_qa$isolated_nodes, revised_graph_qa$isolated_nodes),
  stringsAsFactors = FALSE
)
task2d_write_table(graph_summary_table, file.path(revised_root, "tables", "revised_graph_summary"))

task2d_save_figures(file.path(revised_root, "figures"), weekly, candidates, observations, boundary_wgs84, canonical_nodes, revised_nodes, latitude_band_weekly, regional_weekly)

source_checksums <- list(
  observations = list(path = normalizePath(arguments$observation_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$observation_path)),
  boundary = list(path = normalizePath(arguments$boundary_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$boundary_path)),
  canonical_mask = list(path = normalizePath(arguments$canonical_mask, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$canonical_mask)),
  nodes = list(path = normalizePath(arguments$nodes_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$nodes_path)),
  edges = list(path = normalizePath(arguments$edges_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$edges_path)),
  weeks = list(path = normalizePath(arguments$weeks_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$weeks_path)),
  dynamic_features = list(path = normalizePath(arguments$dynamic_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$dynamic_path)),
  dynamic_history_features = list(path = normalizePath(arguments$history_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$history_path)),
  static_features = list(path = normalizePath(arguments$static_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$static_path)),
  targets_count = list(path = normalizePath(arguments$counts_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$counts_path)),
  targets_presence = list(path = normalizePath(arguments$presence_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(arguments$presence_path))
)

manifest <- list(
  task = "2D", git_sha = arguments$git_sha,
  branch = Sys.getenv("STGNN_GIT_BRANCH", "feature/revised-domain-audit"),
  status = "completed_audit_only",
  original_domain_description = "canonical environmental-support intersection from Task 1/Task 2A",
  revised_domain_definition = "retain canonical cell centers within Mexico, or within the existing canonical U.S. footprint south of 40 degrees north; then retain only cells already present in the canonical environmental-support intersection",
  geographic_boundary_rule = list(boundary_path = normalizePath(arguments$boundary_path, winslash = "/", mustWork = TRUE), boundary_layer = boundary_layer, country_field = boundary_code_info$field, northern_limit_degrees_north = 40, outcome_independent = TRUE),
  original_node_count = nrow(canonical_nodes), revised_node_count = nrow(revised_nodes),
  original_graph_statistics = original_graph_qa, revised_graph_statistics = revised_graph_qa,
  original_positive_node_weeks = sum(counts_original > 0), revised_positive_node_weeks_2024_W01_2026_W29 = sum(counts_revised > 0),
  original_positive_fraction = mean(counts_original > 0), revised_positive_fraction_2024_W01_2026_W29 = mean(counts_revised > 0),
  occupied_revised_nodes_2024_W01_2026_W29 = sum(colSums(counts_revised > 0) > 0),
  observation_audit_dates = list(start = as.character(arguments$analysis_start), end = as.character(arguments$analysis_end), complete_endpoint = "2026-W29"),
  candidate_response_starts = candidate_starts,
  candidate_start_metrics_path = normalizePath(file.path(revised_root, "tables", "candidate_start_comparison.parquet"), winslash = "/", mustWork = TRUE),
  recommended_response_start = recommended_start,
  recommended_response_end = "2026-W29",
  recommendation_basis = recommendation_basis,
  environmental_history_availability = list(source_start = as.character(history_start), history_week_count = nrow(history_weeks), response_history_start = "2024-W01", optional_antecedent_context = c("lag1", "previous-4-week-mean", "previous-13-week-mean"), recurrent_warmup_required = FALSE),
  seasonality = list(features = c("week_sin", "week_cos"), annual_period_weeks = 52.1775, higher_order_harmonics_added = FALSE),
  observation_semantics = "count is the number of recorded detections in a node-week; presence is 1[count > 0]; zero means no recorded detection, not confirmed insect absence",
  graph_construction = "induced subgraph of the original canonical queen graph; no artificial reconnection",
  livestock_contract = list(density_features = c("cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density"), imputation_indicators = paste0(c("cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density"), "_imputed"), finite = TRUE, nonnegative_densities = TRUE),
  validation_feasibility_path = normalizePath(file.path(revised_root, "tables", "validation_feasibility.parquet"), winslash = "/", mustWork = TRUE),
  spatial_validation_audit = spatial_audit, source_artifact_checksums = source_checksums,
  output_artifact_paths = list(revised_root = normalizePath(revised_root, winslash = "/", mustWork = TRUE), nodes = normalizePath(file.path(revised_root, "raw", "nodes.parquet"), winslash = "/", mustWork = TRUE), edges = normalizePath(file.path(revised_root, "graph", "edges_queen.parquet"), winslash = "/", mustWork = TRUE), weekly_summary = normalizePath(file.path(revised_root, "tables", "weekly_observation_regime.parquet"), winslash = "/", mustWork = TRUE), climate_zone_summary = normalizePath(file.path(revised_root, "tables", "climate_zone_coverage.parquet"), winslash = "/", mustWork = TRUE), figures = normalizePath(file.path(revised_root, "figures"), winslash = "/", mustWork = TRUE)),
  predictive_models_fitted = FALSE, final_test_metrics_calculated = FALSE
)
manifest_path <- file.path(output_root, "manifests", "revised_domain_manifest.json")
task2d_write_json(manifest, manifest_path)
file.copy(manifest_path, file.path(revised_root, "manifests", "revised_domain_manifest.json"), overwrite = TRUE)

feature_contract <- list(
  dynamic_feature_names = if (!is.null(feature_manifest$dynamic_feature_names)) unlist(feature_manifest$dynamic_feature_names) else c("era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min", "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean", "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean", "era5land_surface_pressure_mean", "era5land_lai_high_mean", "era5land_lai_low_mean"),
  static_feature_names = if (!is.null(feature_manifest$static_feature_names)) unlist(feature_manifest$static_feature_names) else c("cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density", "cattle_density_imputed", "goat_density_imputed", "sheep_density_imputed", "horse_density_imputed", "pig_density_imputed"),
  calendar_features = c("week_sin", "week_cos"), recurrent_warmup = "not required by default"
)
task2d_write_json(feature_contract, file.path(revised_root, "raw", "feature_manifest.json"))

message("Task 2D audit complete: ", normalizePath(manifest_path, winslash = "/", mustWork = TRUE))
