#!/usr/bin/env Rscript

# Task 2E: refresh the revised-domain production dataset from the updated
# observation source.  This script performs source verification, spatial
# reassignment, response-target rebuilding, and split/contract generation.  It
# does not fit models or calculate predictive metrics.

script_argument <- commandArgs()[grep("^--file=", commandArgs())]
script_path <- if (length(script_argument)) sub("^--file=", "", script_argument[[1L]]) else "scripts/run_task2e_refresh.R"
repository_root <- normalizePath(file.path(dirname(script_path), ".."), winslash = "/", mustWork = TRUE)
setwd(repository_root)

source("R/date_utils.R")
source("R/revised_domain_audit.R")

task2d_require(c("arrow", "data.table", "digest", "jsonlite", "sf", "terra", "ggplot2", "scales"))

value_for <- function(args, flag, default = NULL, required = FALSE) {
  position <- match(flag, args)
  if (is.na(position)) {
    if (required) stop("missing argument: ", flag)
    return(default)
  }
  if (position == length(args)) stop("missing argument value: ", flag)
  args[[position + 1L]]
}

cli <- commandArgs(trailingOnly = TRUE)
source_root <- value_for(cli, "--source-output-root", Sys.getenv("STGNN_OUTPUT_ROOT", "/project/disease_ecology/STGNN-output"))
model_output <- value_for(cli, "--model-output", Sys.getenv("STGNN_MODEL_OUTPUT_ROOT", "/project/disease_ecology/STGNN-output/revised_model_data"))
observation_path <- value_for(cli, "--observation-path", "/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv")
boundary_path <- value_for(cli, "--boundary-path", Sys.getenv("STGNN_BOUNDARY_PATH", ""), required = TRUE)
boundary_layer <- value_for(cli, "--boundary-layer", Sys.getenv("STGNN_BOUNDARY_LAYER", "study_states"))
analysis_start <- as.Date(value_for(cli, "--analysis-start", "2024-01-01"))
analysis_end <- as.Date(value_for(cli, "--analysis-end", "2026-07-19"))
response_start <- value_for(cli, "--response-start", "2025-W01")
response_end <- value_for(cli, "--response-end", "2026-W29")
task2d_commit <- value_for(cli, "--task2d-commit", "e18777f1d98c539c92acc9ba1e7e4deb84b54319")
git_sha <- value_for(cli, "--git-sha", Sys.getenv("STGNN_GIT_SHA", "unknown"))

if (analysis_end < analysis_start) stop("analysis end precedes analysis start")
dir.create(model_output, recursive = TRUE, showWarnings = FALSE)
invisible(lapply(file.path(model_output, c("raw", "splits", "scaling", "predictions", "diagnostics", "manifests")), dir.create, recursive = TRUE, showWarnings = FALSE))

old_raw <- file.path(source_root, "model_data", "raw")
old_split <- file.path(source_root, "model_data", "splits")
old_revised <- file.path(source_root, "revised_domain")
nodes_path <- file.path(old_raw, "nodes.parquet")
edges_path <- file.path(old_raw, "edges_queen.parquet")
weeks_path <- file.path(old_raw, "weeks.parquet")
calendar_path <- file.path(old_raw, "calendar_features.parquet")
dynamic_path <- file.path(old_raw, "dynamic_features.npy")
history_path <- file.path(old_raw, "dynamic_history_features.npy")
static_path <- file.path(old_raw, "static_features.npy")
feature_manifest_path <- file.path(old_raw, "feature_manifest.json")
canonical_mask_path <- file.path(source_root, "preflight", "canonical_environment_mask.tif")
spatial_assignments_path <- file.path(old_split, "spatial_node_assignments.parquet")
required <- c(observation_path, boundary_path, nodes_path, edges_path, weeks_path, calendar_path, dynamic_path, history_path, static_path, canonical_mask_path, feature_manifest_path, spatial_assignments_path)
task2d_require_files(required)

write_npy_matrix <- function(values, path, descr = "<i4") {
  values <- as.matrix(values)
  handle <- task2d_npy_open_write(path, descr, dim(values))
  on.exit(close(handle), add = TRUE)
  task2d_npy_write_vector(handle, as.numeric(t(values)), descr)
  invisible(path)
}

message("Reading frozen canonical artifacts")
nodes <- arrow::read_parquet(nodes_path, as_data_frame = TRUE)
edges <- arrow::read_parquet(edges_path, as_data_frame = TRUE)
weeks <- arrow::read_parquet(weeks_path, as_data_frame = TRUE)
calendar <- arrow::read_parquet(calendar_path, as_data_frame = TRUE)
weeks$week_index <- if ("week_index" %in% names(weeks)) as.integer(weeks$week_index) else seq_len(nrow(weeks)) - 1L
weeks$week_start <- as.Date(weeks$week_start)
weeks$week_end <- as.Date(weeks$week_end)
if (!identical(as.integer(nodes$node_id), seq.int(0L, nrow(nodes) - 1L))) stop("canonical nodes are not zero-based contiguous")
if (!all(c("source_node", "target_node") %in% names(edges))) stop("canonical edges lack source_node/target_node")
if (any(edges$source_node < 0L | edges$target_node < 0L | edges$source_node >= nrow(nodes) | edges$target_node >= nrow(nodes))) stop("canonical edges are out of bounds")
if (nrow(weeks) != 133L || !identical(weeks$iso_week, iso_week_id(weeks$week_start))) stop("canonical weeks are not the expected 133 ISO weeks")
if (!all(c("week_sin", "week_cos") %in% names(calendar))) stop("calendar features lack week_sin/week_cos")

feature_manifest <- jsonlite::fromJSON(feature_manifest_path, simplifyVector = FALSE)
dynamic_feature_names <- unlist(feature_manifest$dynamic_feature_names)
static_feature_names <- unlist(feature_manifest$static_feature_names)
calendar_feature_names <- c("week_sin", "week_cos")
if (length(dynamic_feature_names) != 12L || length(static_feature_names) != 10L) stop("unexpected frozen feature contract")

static_header <- task2d_npy_header(static_path)
static_original <- task2d_npy_read_all(static_path)
if (!identical(dim(static_original), c(nrow(nodes), 10L))) stop("static feature shape is not [16756, 10]")
if (!all(is.finite(static_original)) || any(static_original[, seq_len(5L)] < 0) || !all(static_original[, 6:10] %in% c(0, 1))) stop("static livestock contract invalid")

message("Constructing and verifying the fixed revised domain")
boundary <- sf::st_make_valid(sf::st_read(boundary_path, layer = boundary_layer, quiet = TRUE))
boundary_wgs84 <- sf::st_transform(boundary, 4326)
boundary_code_info <- task2d_country_codes(boundary_wgs84)
boundary_wgs84$country_code <- boundary_code_info$values
state_candidates <- c("name_1", "NAME_1", "state", "STATE", "stusps", "STUSPS", "name", "NAME", "GID_1")
state_matches <- state_candidates[state_candidates %in% names(boundary_wgs84)]
state_field <- if (length(state_matches)) state_matches[[1L]] else NA_character_
boundary_wgs84$state_name <- if (!is.na(state_field)) as.character(boundary_wgs84[[state_field]]) else NA_character_

canonical_mask <- terra::rast(canonical_mask_path)
mask_values <- terra::values(canonical_mask, mat = FALSE)
if (!all(c("x", "y") %in% names(nodes))) {
  xy <- terra::xyFromCell(canonical_mask, nodes$raster_cell)
  nodes$x <- xy[, 1L]; nodes$y <- xy[, 2L]
}
if (!all(c("lon", "lat") %in% names(nodes))) {
  node_points <- terra::vect(data.frame(x = nodes$x, y = nodes$y), geom = c("x", "y"), crs = terra::crs(canonical_mask))
  lonlat <- terra::crds(terra::project(node_points, "EPSG:4326"))
  nodes$lon <- lonlat[, 1L]; nodes$lat <- lonlat[, 2L]
}
node_country <- task2d_classify_points(nodes$lon, nodes$lat, boundary_wgs84, boundary_wgs84$country_code)
node_region <- task2d_region(node_country, nodes$lat)
retain <- node_country %in% c("MX") | (node_country %in% c("US", "USA") & nodes$lat < 40)
if (sum(retain) != 10037L) stop("fixed boundary rule retained ", sum(retain), " nodes; expected 10037")
if (anyNA(mask_values[nodes$raster_cell[retain]])) stop("retained revised nodes are outside environmental support")
revised_indices <- which(retain)
revised_nodes <- nodes[retain, c("node_id", "raster_cell", "row", "column", "x", "y", "lon", "lat"), drop = FALSE]
names(revised_nodes)[names(revised_nodes) == "node_id"] <- "canonical_node_id"
revised_nodes$model_node_id <- seq_len(nrow(revised_nodes)) - 1L
revised_nodes$country_or_domain_region <- ifelse(node_country[retain] == "MX", "Mexico", "U.S.-to-40N")
revised_nodes <- revised_nodes[, c("model_node_id", "canonical_node_id", "raster_cell", "row", "column", "x", "y", "lon", "lat", "country_or_domain_region")]

edge_keep <- edges$source_node %in% revised_nodes$canonical_node_id & edges$target_node %in% revised_nodes$canonical_node_id
source_map <- revised_nodes$model_node_id; names(source_map) <- as.character(revised_nodes$canonical_node_id)
revised_edges <- edges[edge_keep, c("source_node", "target_node"), drop = FALSE]
revised_edges$source_node <- as.integer(unname(source_map[as.character(revised_edges$source_node)]))
revised_edges$target_node <- as.integer(unname(source_map[as.character(revised_edges$target_node)]))
revised_edges <- revised_edges[order(revised_edges$source_node, revised_edges$target_node), , drop = FALSE]
revised_graph_qa <- task2d_graph_qa(transform(revised_nodes, node_id = model_node_id), revised_edges)
if (!identical(revised_graph_qa$node_count, 10037L) || !identical(revised_graph_qa$directed_edge_count, 77614L) || !identical(revised_graph_qa$connected_components, 4L) || !identical(revised_graph_qa$isolated_nodes, 3L)) stop("revised graph statistics do not match Task 2D")

old_revised_nodes <- arrow::read_parquet(file.path(old_revised, "raw", "nodes.parquet"), as_data_frame = TRUE)
old_revised_edges <- arrow::read_parquet(file.path(old_revised, "graph", "edges_queen.parquet"), as_data_frame = TRUE)
if (!identical(as.integer(old_revised_nodes$canonical_node_id), as.integer(revised_nodes$canonical_node_id)) || !identical(as.integer(old_revised_nodes$model_node_id), as.integer(revised_nodes$model_node_id))) stop("Task 2D revised node ordering changed")
if (!isTRUE(all.equal(old_revised_edges[, c("source_node", "target_node")], revised_edges[, c("source_node", "target_node")], check.attributes = FALSE))) stop("Task 2D induced graph changed")

message("Reading and spatially classifying the updated observation source")
raw_observations <- data.table::fread(observation_path, showProgress = FALSE)
raw_observations$source_row_id <- seq_len(nrow(raw_observations))
old_row_count <- 136670L
new_row_count <- nrow(raw_observations)
raw_observations$date <- suppressWarnings(parse_strict_date(as.character(raw_observations$date)))
raw_observations$lon <- suppressWarnings(as.numeric(raw_observations$lon))
raw_observations$lat <- suppressWarnings(as.numeric(raw_observations$lat))
valid_coordinate <- is.finite(raw_observations$lon) & is.finite(raw_observations$lat) & raw_observations$lon >= -180 & raw_observations$lon <= 180 & raw_observations$lat >= -90 & raw_observations$lat <= 90
valid_date <- !is.na(raw_observations$date)
raw_observations$country_code <- NA_character_
raw_observations$state <- NA_character_
valid_rows <- which(valid_coordinate)
if (length(valid_rows)) {
  points <- sf::st_as_sf(raw_observations[valid_rows, ], coords = c("lon", "lat"), crs = 4326, remove = FALSE)
  hits <- sf::st_intersects(points, boundary_wgs84, sparse = TRUE)
  raw_observations$country_code[valid_rows] <- vapply(hits, function(index) if (length(index)) boundary_wgs84$country_code[[index[[1L]]]] else NA_character_, character(1L))
  raw_observations$state[valid_rows] <- vapply(hits, function(index) if (length(index)) boundary_wgs84$state_name[[index[[1L]]]] else NA_character_, character(1L))
  projected <- terra::project(terra::vect(raw_observations[valid_rows, ], geom = c("lon", "lat"), crs = "EPSG:4326"), terra::crs(canonical_mask))
  cells <- terra::cellFromXY(canonical_mask, terra::crds(projected))
  cell_to_canonical <- nodes$node_id; names(cell_to_canonical) <- as.character(nodes$raster_cell)
  raw_observations$canonical_node_id[valid_rows] <- as.integer(unname(cell_to_canonical[as.character(cells)]))
}
raw_observations$iso_week <- ifelse(valid_date, iso_week_id(raw_observations$date), NA_character_)
raw_observations$broad_region <- task2d_region(raw_observations$country_code, raw_observations$lat)
raw_observations$source_group <- ifelse(raw_observations$country_code == "MX", "Mexico", ifelse(raw_observations$country_code %in% c("US", "USA"), "United States", ifelse(is.na(raw_observations$country_code), "unmatched", "excluded region")))
raw_observations$geographic_domain <- raw_observations$country_code == "MX" | (raw_observations$country_code %in% c("US", "USA") & raw_observations$lat < 40)
raw_observations$model_node_id <- as.integer(unname(source_map[as.character(raw_observations$canonical_node_id)]))
raw_observations$environmental_support <- !is.na(raw_observations$canonical_node_id)
raw_observations$revised_domain_membership <- raw_observations$geographic_domain & !is.na(raw_observations$model_node_id)
raw_observations$revised_domain_exclusion_reason <- ifelse(raw_observations$revised_domain_membership, "inside_revised_domain", ifelse(raw_observations$geographic_domain & !raw_observations$environmental_support, "geographic_domain_outside_environmental_support", ifelse(!raw_observations$geographic_domain, "outside_revised_geographic_rule", "invalid_or_unmatched")))

classification_columns <- c("source_row_id", "date", "host", "lon", "lat", "country_code", "state", "broad_region", "source_group", "iso_week", "canonical_node_id", "model_node_id", "geographic_domain", "environmental_support", "revised_domain_membership", "revised_domain_exclusion_reason")
source_classification <- as.data.frame(raw_observations[, ..classification_columns])
task2d_write_table(source_classification, file.path(model_output, "diagnostics", "updated_observation_classification"))
us_details <- source_classification[source_classification$source_group == "United States", c("source_row_id", "date", "host", "lon", "lat", "state", "iso_week", "canonical_node_id", "model_node_id", "revised_domain_membership", "revised_domain_exclusion_reason"), drop = FALSE]
task2d_write_table(us_details, file.path(model_output, "diagnostics", "us_observation_assignments"))

new_us <- raw_observations$source_group == "United States"
new_mexico <- raw_observations$source_group == "Mexico"
valid_lat <- raw_observations$lat[valid_coordinate]
us_dates <- raw_observations$date[new_us & valid_date]
source_change <- data.frame(
  old_sha256 = "099f5fcc61dbd3686bd9bfd0dbfb0a4e37a36f2cba8b443580d2c456544f8a41",
  new_sha256 = task2d_sha256(observation_path), old_row_count = old_row_count, new_row_count = new_row_count,
  row_count_change = new_row_count - old_row_count, valid_coordinate_count = sum(valid_coordinate), valid_date_count = sum(valid_date),
  new_us_observation_count = sum(new_us), new_mexico_observation_count = sum(new_mexico),
  assumed_new_observation_count = max(0L, new_row_count - old_row_count),
  assumed_new_2024 = sum(new_us & format(raw_observations$date, "%Y") == "2024", na.rm = TRUE),
  assumed_new_2025 = sum(new_us & format(raw_observations$date, "%Y") == "2025", na.rm = TRUE),
  assumed_new_2026 = sum(new_us & format(raw_observations$date, "%Y") == "2026", na.rm = TRUE),
  minimum_latitude = min(valid_lat, na.rm = TRUE), maximum_latitude = max(valid_lat, na.rm = TRUE),
  earliest_us_observation_date = if (length(us_dates)) min(us_dates) else as.Date(NA),
  latest_us_observation_date = if (length(us_dates)) max(us_dates) else as.Date(NA),
  old_source_available_for_row_level_diff = FALSE,
  stringsAsFactors = FALSE
)
task2d_write_table(source_change, file.path(model_output, "diagnostics", "observation_source_change"))

us_state_summary <- if (nrow(us_details)) as.data.frame(table(state = us_details$state, useNA = "ifany"), stringsAsFactors = FALSE) else data.frame(state = character(), Freq = integer())
names(us_state_summary)[names(us_state_summary) == "Freq"] <- "observations"
us_month_summary <- if (nrow(us_details)) as.data.frame(table(month = format(us_details$date, "%Y-%m"), useNA = "ifany"), stringsAsFactors = FALSE) else data.frame(month = character(), Freq = integer())
names(us_month_summary)[names(us_month_summary) == "Freq"] <- "observations"
us_week_summary <- if (nrow(us_details)) as.data.frame(table(iso_week = us_details$iso_week, useNA = "ifany"), stringsAsFactors = FALSE) else data.frame(iso_week = character(), Freq = integer())
names(us_week_summary)[names(us_week_summary) == "Freq"] <- "observations"
task2d_write_table(us_state_summary, file.path(model_output, "diagnostics", "us_observations_by_state"))
task2d_write_table(us_month_summary, file.path(model_output, "diagnostics", "us_observations_by_month"))
task2d_write_table(us_week_summary, file.path(model_output, "diagnostics", "us_observations_by_iso_week"))

analysis_selection <- valid_date & raw_observations$date >= analysis_start & raw_observations$date <= analysis_end & raw_observations$iso_week %in% weeks$iso_week
analysis_observations <- as.data.frame(raw_observations[analysis_selection, ])
target_weeks <- which(weeks$iso_week >= response_start & weeks$iso_week <= response_end)
if (length(target_weeks) != 81L) stop("approved response period is not 81 weeks")

make_counts <- function(node_column, n_nodes) {
  selected <- analysis_observations[[node_column]]
  keep <- !is.na(selected) & analysis_observations$iso_week %in% weeks$iso_week
  week_index <- match(analysis_observations$iso_week[keep], weeks$iso_week)
  node_index <- as.integer(selected[keep]) + 1L
  index <- week_index + nrow(weeks) * (node_index - 1L)
  matrix(tabulate(index, nbins = nrow(weeks) * n_nodes), nrow = nrow(weeks), ncol = n_nodes)
}

canonical_counts <- make_counts("canonical_node_id", nrow(nodes))
revised_counts <- canonical_counts[, revised_indices, drop = FALSE]
revised_presence <- revised_counts > 0
if (nrow(revised_counts) != 133L || ncol(revised_counts) != 10037L) stop("refreshed canonical/revised targets have unexpected dimensions")
if (!isTRUE(all.equal(revised_presence, revised_counts > 0))) stop("presence does not equal count > 0")

region_by_revised_node <- revised_nodes$country_or_domain_region
weekly <- task2d_weekly_summary(weeks, canonical_counts, revised_counts, nodes, revised_nodes, analysis_observations, node_region)
for (region in c("Mexico", "U.S.-to-40N")) {
  selected <- analysis_observations$source_group == ifelse(region == "Mexico", "Mexico", "United States")
  values <- table(factor(analysis_observations$iso_week[selected], levels = weeks$iso_week))
  weekly[[paste0("records_", region)]] <- as.integer(values)
}
for (region in c("Mexico", "U.S.-to-40N")) {
  col <- paste0("records_", region)
  gaps <- rep(NA_integer_, nrow(weekly)); last <- NA_integer_
  for (i in seq_len(nrow(weekly))) { if (weekly[[col]][[i]] > 0 && !is.na(last)) gaps[[i]] <- i - last; if (weekly[[col]][[i]] > 0) last <- i }
  weekly[[sub("^records_", "weeks_since_previous_", col)]] <- gaps
}
revised_observations <- analysis_observations[analysis_observations$revised_domain_membership, , drop = FALSE]
weekly$revised_latitude_q25 <- NA_real_; weekly$revised_latitude_q75 <- NA_real_; weekly$revised_northmost_detection_latitude <- NA_real_; weekly$revised_southmost_detection_latitude <- NA_real_
if (nrow(revised_observations)) {
  groups <- split(seq_len(nrow(revised_observations)), revised_observations$iso_week)
  for (week_id in names(groups)) {
    i <- match(week_id, weekly$iso_week); values <- revised_observations$lat[groups[[week_id]]]
    weekly$revised_latitude_q25[[i]] <- as.numeric(stats::quantile(values, .25, names = FALSE)); weekly$revised_latitude_q75[[i]] <- as.numeric(stats::quantile(values, .75, names = FALSE))
    weekly$revised_northmost_detection_latitude[[i]] <- max(values); weekly$revised_southmost_detection_latitude[[i]] <- min(values)
  }
}

candidate_starts <- c("2025-W01", "2025-W05", "2025-W09", "2025-W13")
candidates <- task2d_candidate_metrics(candidate_starts, weeks, revised_counts, revised_nodes, region_by_revised_node)
candidate_screen <- do.call(rbind, lapply(candidate_starts, function(start) {
  i <- match(start, weekly$iso_week); first <- weekly$revised_detection_total[i:min(i + 12L, nrow(weekly))]; active <- first > 0
  gaps <- integer(); last <- NA_integer_
  for (j in seq_along(active)) { if (active[[j]] && !is.na(last)) gaps <- c(gaps, j - last); if (active[[j]]) last <- j }
  record <- candidates[candidates$candidate_start == start, , drop = FALSE]
  data.frame(candidate_start = start, first_13_week_reporting_fraction = mean(active), first_13_week_max_gap = if (length(gaps)) max(gaps) else Inf, response_weeks = record$response_weeks, descriptive_start_eligible = record$response_weeks >= 52L && mean(active) >= .75 && (if (length(gaps)) max(gaps) else Inf) <= 4L, stringsAsFactors = FALSE)
}))
eligible <- candidate_screen$candidate_start[candidate_screen$descriptive_start_eligible]
recommended_start <- if (length(eligible)) eligible[[1L]] else response_start
if (!identical(recommended_start, response_start)) stop("refreshed descriptive audit no longer supports 2025-W01; escalate before fitting")

regional_summary <- do.call(rbind, lapply(c("Mexico", "U.S.-to-40N"), function(region) {
  node_selection <- region_by_revised_node == region
  source_selection <- analysis_observations$source_group == ifelse(region == "Mexico", "Mexico", "United States")
  y <- revised_counts[, node_selection, drop = FALSE]
  data.frame(region = region, nodes = sum(node_selection), possible_node_weeks_2025_plus = 81L * sum(node_selection), positive_node_weeks_2025_plus = sum(y[target_weeks, , drop = FALSE] > 0), detections_2025_plus = sum(source_selection & analysis_observations$iso_week >= response_start), occupied_nodes_2025_plus = sum(colSums(y[target_weeks, , drop = FALSE] > 0) > 0), stringsAsFactors = FALSE)
}))
regional_weekly <- rbind(data.frame(week_start = weekly$week_start, iso_week = weekly$iso_week, region = "Mexico", detections = weekly$records_Mexico, stringsAsFactors = FALSE), data.frame(week_start = weekly$week_start, iso_week = weekly$iso_week, region = "U.S.-to-40N", detections = weekly[["records_U.S.-to-40N"]], stringsAsFactors = FALSE))
latitude_breaks <- c(-Inf, 20, 25, 30, 35, 40); latitude_labels <- c("<20N", "20-25N", "25-30N", "30-35N", "35-40N")
node_bands <- cut(revised_nodes$lat, breaks = latitude_breaks, labels = latitude_labels, right = FALSE)
latitude_band_weekly <- do.call(rbind, lapply(seq_len(nrow(weeks)), function(i) do.call(rbind, lapply(latitude_labels, function(band) { selected <- node_bands == band; data.frame(week_index = weeks$week_index[[i]], iso_week = weeks$iso_week[[i]], week_start = weeks$week_start[[i]], latitude_band = band, positive_cells = if (any(selected)) sum(revised_counts[i, selected] > 0) else 0L, detections = if (any(selected)) sum(revised_counts[i, selected]) else 0L, stringsAsFactors = FALSE) }))))
seasonal_summary <- do.call(rbind, lapply(c("winter", "spring", "summer", "fall"), function(season) { selected <- weeks$iso_week >= response_start & weekly$calendar_season == season; y <- revised_counts[selected, , drop = FALSE]; data.frame(season = season, weeks = sum(selected), detections = sum(y), positive_node_weeks = sum(y > 0), occupied_nodes = sum(colSums(y > 0) > 0), weeks_with_any_detection = sum(rowSums(y) > 0), fraction_weeks_with_any_detection = mean(rowSums(y) > 0), stringsAsFactors = FALSE) }))

message("Writing refreshed response arrays and contract artifacts")
raw_output <- file.path(model_output, "raw")
dynamic_result <- task2d_npy_subset(dynamic_path, file.path(raw_output, "dynamic_features.npy"), revised_indices, target_weeks)
history_result <- task2d_npy_subset(history_path, file.path(raw_output, "dynamic_history_features.npy"), revised_indices)
if (!identical(as.integer(dynamic_result$output_shape), c(81L, 10037L, 12L))) stop("dynamic response array has unexpected shape")
static_revised <- static_original[revised_indices, , drop = FALSE]
write_npy_matrix(static_revised, file.path(raw_output, "static_features.npy"), static_header$descr)
if (!identical(as.integer(dim(static_revised)), c(10037L, 10L))) stop("static response array has unexpected shape")
write_npy_matrix(revised_counts[target_weeks, , drop = FALSE], file.path(raw_output, "targets_count.npy"), "<i4")
presence_response <- revised_presence[target_weeks, , drop = FALSE]
write_npy_matrix(matrix(as.integer(presence_response), nrow = nrow(presence_response), ncol = ncol(presence_response)), file.path(raw_output, "targets_presence.npy"), "<i4")
arrow::write_parquet(weeks[target_weeks, , drop = FALSE], file.path(raw_output, "weeks.parquet"))
arrow::write_parquet(revised_nodes, file.path(raw_output, "nodes.parquet"))
arrow::write_parquet(revised_edges, file.path(raw_output, "edges_queen.parquet"))
arrow::write_parquet(calendar[target_weeks, , drop = FALSE], file.path(raw_output, "calendar_features.parquet"))
history_shape <- history_result$output_shape
history_start <- weeks$week_start[[1L]] - 7L * (history_shape[[1L]] - nrow(weeks))
history_dates <- seq(history_start, by = "7 days", length.out = history_shape[[1L]])
history_weeks <- data.frame(history_index = seq_along(history_dates) - 1L, iso_week = iso_week_id(history_dates), week_start = history_dates, week_end = history_dates + 6L, stringsAsFactors = FALSE)
arrow::write_parquet(history_weeks, file.path(raw_output, "history_weeks.parquet"))
static_table <- data.frame(model_node_id = revised_nodes$model_node_id, canonical_node_id = revised_nodes$canonical_node_id, static_original[revised_indices, , drop = FALSE], check.names = FALSE)
names(static_table)[seq.int(3L, 2L + ncol(static_original))] <- static_feature_names
arrow::write_parquet(static_table, file.path(raw_output, "static_features.parquet"))

spatial <- arrow::read_parquet(spatial_assignments_path, as_data_frame = TRUE)
spatial_id_col <- if ("node_id" %in% names(spatial)) "node_id" else names(spatial)[[1L]]
fold_col <- if ("spatial_fold" %in% names(spatial)) "spatial_fold" else grep("fold", names(spatial), value = TRUE)[[1L]]
block_col <- if ("spatial_block_id" %in% names(spatial)) "spatial_block_id" else grep("block", names(spatial), value = TRUE)[[1L]]
spatial_revised <- data.frame(canonical_node_id = revised_nodes$canonical_node_id, model_node_id = revised_nodes$model_node_id, spatial_fold = as.integer(spatial[[fold_col]][match(revised_nodes$canonical_node_id, spatial[[spatial_id_col]])]), spatial_block_id = as.character(spatial[[block_col]][match(revised_nodes$canonical_node_id, spatial[[spatial_id_col]])]), stringsAsFactors = FALSE)
if (anyNA(spatial_revised$spatial_fold)) stop("revised nodes lack spatial-fold assignments")
arrow::write_parquet(spatial_revised, file.path(model_output, "splits", "spatial_node_assignments.parquet"))

response_labels <- weeks$iso_week[target_weeks]
make_range <- function(start, end) which(response_labels >= start & response_labels <= end) - 1L
folds <- list(
  list(fold = 1L, train_indices = make_range("2025-W01", "2025-W26"), validation_indices = make_range("2025-W27", "2025-W39"), train_weeks = c("2025-W01", "2025-W26"), validation_weeks = c("2025-W27", "2025-W39")),
  list(fold = 2L, train_indices = make_range("2025-W01", "2025-W39"), validation_indices = make_range("2025-W40", "2025-W52"), train_weeks = c("2025-W01", "2025-W39"), validation_weeks = c("2025-W40", "2025-W52")),
  list(fold = 3L, train_indices = make_range("2025-W01", "2025-W52"), validation_indices = make_range("2026-W01", "2026-W08"), train_weeks = c("2025-W01", "2025-W52"), validation_weeks = c("2026-W01", "2026-W08")),
  list(fold = 4L, train_indices = make_range("2025-W01", "2026-W08"), validation_indices = make_range("2026-W09", "2026-W16"), train_weeks = c("2025-W01", "2026-W08"), validation_weeks = c("2026-W09", "2026-W16"))
)
if (!all(vapply(folds, function(x) length(x$train_indices) > 0 && length(x$validation_indices) > 0, logical(1L)))) stop("invalid temporal fold")
split_manifest <- list(response_start = response_start, response_end = response_end, response_week_count = length(response_labels), development_weeks = c("2025-W01", "2026-W16"), development_indices = 0:67, final_test = list(weeks = c("2026-W17", "2026-W29"), indices = 68:80, week_count = 13L), temporal_folds = folds, evaluation_mode = "development", terminal_holdout_predictive_metrics_calculated = FALSE)
task2d_write_json(split_manifest, file.path(model_output, "splits", "temporal_splits.json"))
task2d_write_json(list(response_start = response_start, response_end = response_end, response_week_count = length(response_labels), terminal_holdout = c("2026-W17", "2026-W29"), terminal_holdout_indices = 68:80, predictive_metrics_calculated = FALSE), file.path(model_output, "splits", "response_period.json"))

feature_contract <- list(task = "2E", dynamic_feature_names = dynamic_feature_names, static_feature_names = static_feature_names, calendar_feature_names = calendar_feature_names, predictor_order = c(dynamic_feature_names, static_feature_names, calendar_feature_names), predictor_count = 24L, calendar_period_weeks = 52.1775, dynamic_features_shape = c(81L, 10037L, 12L), static_features_shape = c(10037L, 10L), targets_count_shape = c(81L, 10037L), targets_presence_shape = c(81L, 10037L), response_definition = "count is recorded detections assigned to a revised-domain node-week; presence is count > 0", zero_semantics = "no recorded detection, not confirmed biological absence", coordinate_features_excluded = TRUE, response_lags_excluded = TRUE, environmental_lags_excluded = TRUE, spatial_features_excluded = TRUE, livestock_transform = "log1p density columns only before fold standardization; indicators remain 0/1", calendar_transform = "natural sine/cosine scale", source = "updated observation source")
task2d_write_json(feature_contract, file.path(raw_output, "feature_manifest.json"))

task2d_write_table(weekly, file.path(model_output, "diagnostics", "weekly_observation_regime"))
task2d_write_table(candidates, file.path(model_output, "diagnostics", "candidate_start_comparison"))
task2d_write_table(candidate_screen, file.path(model_output, "diagnostics", "candidate_start_screen"))
task2d_write_table(regional_summary, file.path(model_output, "diagnostics", "mexico_us_summary"))
task2d_write_table(regional_weekly, file.path(model_output, "diagnostics", "mexico_us_weekly"))
task2d_write_table(seasonal_summary, file.path(model_output, "diagnostics", "seasonal_summary"))
task2d_write_table(latitude_band_weekly, file.path(model_output, "diagnostics", "latitude_band_weekly"))
task2d_write_table(data.frame(domain = c("original", "revised"), node_count = c(nrow(nodes), nrow(revised_nodes)), directed_edge_count = c(nrow(edges), nrow(revised_edges)), connected_components = c(task2d_graph_qa(nodes, edges)$connected_components, revised_graph_qa$connected_components), isolated_nodes = c(task2d_graph_qa(nodes, edges)$isolated_nodes, revised_graph_qa$isolated_nodes), stringsAsFactors = FALSE), file.path(model_output, "diagnostics", "graph_summary"))
task2d_write_json(list(total_target_records = sum(revised_counts[target_weeks, ]), positive_node_weeks = sum(revised_counts[target_weeks, ] > 0), positive_fraction = mean(revised_counts[target_weeks, ] > 0), mexico_positive_node_weeks = sum(revised_counts[target_weeks, , drop = FALSE][, region_by_revised_node == "Mexico", drop = FALSE] > 0), us_positive_node_weeks = sum(revised_counts[target_weeks, , drop = FALSE][, region_by_revised_node == "U.S.-to-40N", drop = FALSE] > 0), geographic_domain_outside_environmental_support = sum(raw_observations$geographic_domain & !raw_observations$environmental_support, na.rm = TRUE), outside_revised_study_domain = sum(!raw_observations$revised_domain_membership, na.rm = TRUE), invalid_or_unassignable = sum(!valid_coordinate | !valid_date | is.na(raw_observations$canonical_node_id)), graph_checksum = task2d_sha256(file.path(model_output, "raw", "edges_queen.parquet"))), file.path(model_output, "diagnostics", "target_assignment_qa.json"))

task2d_save_figures(file.path(model_output, "diagnostics", "figures"), weekly, candidates, analysis_observations, boundary_wgs84, nodes, revised_nodes, latitude_band_weekly, regional_weekly)

source_info <- list(path = normalizePath(observation_path, winslash = "/", mustWork = TRUE), sha256 = task2d_sha256(observation_path), row_count = new_row_count, file_mtime = as.character(file.info(observation_path)$mtime), valid_coordinate_count = sum(valid_coordinate), valid_date_count = sum(valid_date), minimum_date = as.character(min(raw_observations$date, na.rm = TRUE)), maximum_date = as.character(max(raw_observations$date, na.rm = TRUE)), old_sha256 = source_change$old_sha256, old_row_count = old_row_count, source_revision_newer_than_task2d = TRUE)
manifest <- list(task = "2E", status = "production_dataset_built_audit_complete", branch = Sys.getenv("STGNN_GIT_BRANCH", "feature/revised-domain-baselines"), git_sha = git_sha, task2d_domain_commit = task2d_commit, observation_source = source_info, source_change_audit = task2d_jsonable(source_change), boundary = list(path = normalizePath(boundary_path, winslash = "/", mustWork = TRUE), layer = boundary_layer, country_field = boundary_code_info$field, state_field = state_field, rule = "Mexico plus existing U.S. study footprint south of 40 degrees north"), revised_domain = list(node_count = nrow(revised_nodes), canonical_node_order_verified = TRUE, graph_checksum = task2d_sha256(file.path(model_output, "raw", "edges_queen.parquet")), graph_statistics = revised_graph_qa), response = list(start = response_start, end = response_end, week_count = length(response_labels), positive_node_weeks = sum(revised_counts[target_weeks, ] > 0), positive_fraction = mean(revised_counts[target_weeks, ] > 0), mexico_positive_node_weeks = sum(revised_counts[target_weeks, , drop = FALSE][, region_by_revised_node == "Mexico", drop = FALSE] > 0), us_positive_node_weeks = sum(revised_counts[target_weeks, , drop = FALSE][, region_by_revised_node == "U.S.-to-40N", drop = FALSE] > 0)), feature_order = c(dynamic_feature_names, static_feature_names, calendar_feature_names), array_shapes = list(dynamic_features = c(81L, 10037L, 12L), static_features = c(10037L, 10L), targets_count = c(81L, 10037L), targets_presence = c(81L, 10037L)), fold_definitions = folds, terminal_holdout = split_manifest$final_test, observation_semantics = "recorded detections / no recorded detection", predictive_models_fitted = FALSE, terminal_holdout_metrics_calculated = FALSE, baseline_results_pending = TRUE, task2d_quantities_refreshed = TRUE, task2d_historical_manifest_preserved = TRUE)
task2d_write_json(manifest, file.path(model_output, "manifests", "revised_production_manifest.json"))
message("Task 2E dataset refresh complete: ", normalizePath(model_output, winslash = "/", mustWork = TRUE))
