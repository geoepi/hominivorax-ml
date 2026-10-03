#!/usr/bin/env Rscript

# Build immutable Task-2A raw arrays from completed Task-1 artifacts.

args <- commandArgs(trailingOnly = TRUE)
value_for <- function(flag, default = NULL) {
  position <- match(flag, args)
  if (is.na(position)) return(default)
  if (position == length(args)) stop("missing argument: ", flag)
  args[[position + 1L]]
}

output_root <- value_for("--output-root", Sys.getenv("STGNN_OUTPUT_ROOT", "/project/disease_ecology/STGNN-output"))
environment_root <- value_for("--environment-root", Sys.getenv("STGNN_ENVIRONMENTAL_ROOT"))
template_path <- value_for("--template", Sys.getenv("STGNN_TEMPLATE_PATH"))
analysis_start <- as.Date(value_for("--analysis-start", "2024-01-01"))
analysis_end <- as.Date(value_for("--analysis-end", "2026-07-19"))
history_weeks <- as.integer(value_for("--history-weeks", "52"))

if (!nzchar(environment_root) || !nzchar(template_path)) stop("environment root and template are required")
for (package in c("arrow", "data.table", "digest", "jsonlite", "terra")) {
  if (!requireNamespace(package, quietly = TRUE)) stop(package, " is required")
}

source(file.path("R", "date_utils.R"))
source(file.path("R", "raster_inventory.R"))
source(file.path("R", "npy_io.R"))

raw_root <- file.path(output_root, "model_data", "raw")
dir.create(raw_root, recursive = TRUE, showWarnings = FALSE)
nodes_path <- file.path(output_root, "preflight", "nodes.parquet")
edges_path <- file.path(output_root, "preflight", "edges_queen.parquet")
mask_path <- file.path(output_root, "preflight", "canonical_environment_mask.tif")
livestock_nodes_path <- file.path(output_root, "preflight", "livestock_node_covariates.parquet")
diagnostic_counts_path <- file.path(output_root, "preflight", "observation_node_week_counts.parquet")

nodes <- arrow::read_parquet(nodes_path, as_data_frame = TRUE)
edges <- arrow::read_parquet(edges_path, as_data_frame = TRUE)
if (!identical(as.integer(nodes$node_id), seq.int(0L, nrow(nodes) - 1L))) stop("Task-1 node order is invalid")
if (!file.exists(mask_path)) stop("missing Task-1 canonical mask: ", mask_path)

target_dates <- seq(analysis_start, analysis_end, by = "7 days")
if (length(target_dates) != 133L) stop("unexpected target week count: ", length(target_dates))
target_week_ids <- iso_week_id(target_dates)
history_dates <- seq(analysis_start - 7L * history_weeks, analysis_end, by = "7 days")
history_week_ids <- iso_week_id(history_dates)
if (length(history_week_ids) != length(target_dates) + history_weeks) stop("history index mismatch")

environmental_features <- c(
  "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
  "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
  "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
  "era5land_surface_pressure_mean", "era5land_lai_high_mean",
  "era5land_lai_low_mean"
)
livestock_features <- c("cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density")
livestock_indicator_features <- paste0(livestock_features, "_imputed")
static_features <- c(livestock_features, livestock_indicator_features)

resolve_week_files <- function(product) {
  paths <- list.files(file.path(environment_root, product, "weekly"), full.names = TRUE,
                      pattern = "\\.(tif|tiff)$", ignore.case = TRUE)
  if (!length(paths)) stop("no weekly rasters found for ", product)
  parsed <- lapply(paths, parse_week_identifier)
  ids <- vapply(parsed, `[[`, character(1L), "week_id")
  if (anyDuplicated(ids[!is.na(ids)])) stop("duplicate environmental week for ", product)
  paths[match(history_week_ids, ids)]
}

week_paths <- setNames(lapply(environmental_features, resolve_week_files), environmental_features)
if (any(vapply(week_paths, function(x) anyNA(x), logical(1L)))) stop("missing environmental history week")

template <- terra::rast(template_path)
mask <- terra::rast(mask_path)
mask_values <- terra::values(mask, mat = FALSE)
if (sum(!is.na(mask_values)) != nrow(nodes)) stop("node count does not equal canonical support")

read_week_matrix <- function(week_index) {
  result <- matrix(NA_real_, nrow = nrow(nodes), ncol = length(environmental_features))
  for (feature_index in seq_along(environmental_features)) {
    raster <- terra::rast(week_paths[[environmental_features[[feature_index]]]][[week_index]])
    selected <- terra::values(raster, mat = FALSE)[nodes$raster_cell]
    if (any(!is.finite(selected))) stop("non-finite value in canonical support")
    result[, feature_index] <- selected
  }
  result
}

livestock <- arrow::read_parquet(livestock_nodes_path, as_data_frame = TRUE)
missing_livestock <- setdiff(c("node_id", livestock_features), names(livestock))
if (length(missing_livestock)) stop("livestock schema missing: ", paste(missing_livestock, collapse = ", "))
livestock <- livestock[match(nodes$node_id, livestock$node_id), c("node_id", livestock_features)]
if (anyNA(livestock$node_id)) stop("invalid livestock node IDs")
density_matrix <- as.matrix(livestock[, livestock_features])
storage.mode(density_matrix) <- "double"
if (any(density_matrix < 0, na.rm = TRUE)) stop("negative livestock density")
imputation_indicators <- matrix(0L, nrow = nrow(nodes), ncol = length(livestock_features),
                                 dimnames = list(NULL, livestock_indicator_features))
imputation_records <- list()
for (species_index in seq_along(livestock_features)) {
  missing_indices <- which(!is.finite(density_matrix[, species_index]))
  valid_indices <- which(is.finite(density_matrix[, species_index]))
  if (!length(valid_indices) && length(missing_indices)) stop("no valid donor for ", livestock_features[[species_index]])
  for (node_index in missing_indices) {
    squared_distance <- (nodes$x[valid_indices] - nodes$x[[node_index]])^2 +
      (nodes$y[valid_indices] - nodes$y[[node_index]])^2
    donor_position <- which.min(squared_distance)
    donor_index <- valid_indices[[donor_position]]
    distance_km <- sqrt(squared_distance[[donor_position]]) / 1000
    density_matrix[node_index, species_index] <- density_matrix[donor_index, species_index]
    imputation_indicators[node_index, species_index] <- 1L
    imputation_records[[length(imputation_records) + 1L]] <- data.frame(
      node_id = as.integer(nodes$node_id[[node_index]]),
      species = livestock_features[[species_index]],
      original_missing = TRUE,
      donor_node_id = as.integer(nodes$node_id[[donor_index]]),
      distance_to_donor_km = distance_km,
      donor_density = density_matrix[donor_index, species_index],
      stringsAsFactors = FALSE
    )
  }
}
if (any(!is.finite(density_matrix))) stop("livestock imputation left non-finite values")
imputation_provenance <- if (length(imputation_records)) {
  do.call(rbind, imputation_records)
} else {
  data.frame(node_id = integer(), species = character(), original_missing = logical(), donor_node_id = integer(),
             distance_to_donor_km = numeric(), donor_density = numeric(), stringsAsFactors = FALSE)
}
imputation_provenance_path <- file.path(raw_root, "livestock_imputation_provenance.parquet")
arrow::write_parquet(imputation_provenance, imputation_provenance_path)
imputation_summary <- lapply(seq_along(livestock_features), function(species_index) {
  species <- livestock_features[[species_index]]
  records <- imputation_provenance[imputation_provenance$species == species, , drop = FALSE]
  list(
    species = species,
    imputed_node_count = nrow(records),
    imputed_fraction_of_nodes = nrow(records) / nrow(nodes),
    maximum_distance_km = if (nrow(records)) max(records$distance_to_donor_km) else 0,
    mean_distance_km = if (nrow(records)) mean(records$distance_to_donor_km) else 0,
    over_50_km_count = if (nrow(records)) sum(records$distance_to_donor_km > 50) else 0,
    over_50_km_review_required = if (nrow(records)) any(records$distance_to_donor_km > 50) else FALSE
  )
})
jsonlite::write_json(list(
  rule = "nearest valid aligned livestock-density cell among canonical nodes, separately by species; no response or environmental inputs",
  distance_coordinate_system = terra::crs(template),
  threshold_km = 50,
  summaries = imputation_summary,
  provenance_path = normalizePath(imputation_provenance_path, winslash = "/", mustWork = TRUE)
), file.path(raw_root, "livestock_imputation.json"), auto_unbox = TRUE, pretty = TRUE, na = "null")
livestock <- data.frame(node_id = nodes$node_id, density_matrix, imputation_indicators, check.names = FALSE)
names(livestock) <- c("node_id", static_features)

counts <- matrix(0L, nrow = length(target_week_ids), ncol = nrow(nodes))
diagnostic_counts <- arrow::read_parquet(diagnostic_counts_path, as_data_frame = TRUE)
if (nrow(diagnostic_counts)) {
  week_index <- match(diagnostic_counts$iso_week, target_week_ids)
  node_index <- match(as.integer(diagnostic_counts$node_id), nodes$node_id)
  keep <- !is.na(week_index) & !is.na(node_index)
  counts[cbind(week_index[keep], node_index[keep])] <- as.integer(diagnostic_counts$detection_count[keep])
}
if (any(counts < 0L)) stop("negative detection counts")
presence <- counts > 0L

npy_write_weekwise(file.path(raw_root, "dynamic_history_features.npy"),
  function(index) as.numeric(t(read_week_matrix(index))),
  shape = c(length(history_week_ids), nrow(nodes), length(environmental_features)), descr = "<f4")
npy_write_weekwise(file.path(raw_root, "dynamic_features.npy"),
  function(index) as.numeric(t(read_week_matrix(history_weeks + index))),
  shape = c(length(target_week_ids), nrow(nodes), length(environmental_features)), descr = "<f4")
npy_write_matrix(file.path(raw_root, "static_features.npy"), as.matrix(livestock[, static_features]), descr = "<f4")
npy_write_weekwise(file.path(raw_root, "targets_count.npy"), function(index) counts[index, ],
  shape = c(length(target_week_ids), nrow(nodes)), descr = "<i4")
npy_write_weekwise(file.path(raw_root, "targets_presence.npy"), function(index) as.integer(presence[index, ]),
  shape = c(length(target_week_ids), nrow(nodes)), descr = "|u1")

weeks <- data.frame(
  week_index = seq_along(target_week_ids) - 1L,
  iso_week = target_week_ids,
  week_start = as.character(target_dates),
  week_end = as.character(target_dates + 6L),
  year = as.integer(format(target_dates, "%G")),
  iso_week_number = as.integer(format(target_dates, "%V")),
  is_final_test = seq_along(target_week_ids) > (length(target_week_ids) - 26L),
  stringsAsFactors = FALSE
)
arrow::write_parquet(weeks, file.path(raw_root, "weeks.parquet"))
arrow::write_parquet(nodes, file.path(raw_root, "nodes.parquet"))
arrow::write_parquet(edges, file.path(raw_root, "edges_queen.parquet"))
calendar <- data.frame(
  week_index = weeks$week_index,
  iso_week = weeks$iso_week,
  week_sin = sin(2 * pi * weeks$week_index / 52.1775),
  week_cos = cos(2 * pi * weeks$week_index / 52.1775)
)
arrow::write_parquet(calendar, file.path(raw_root, "calendar_features.parquet"))
arrow::write_parquet(livestock, file.path(raw_root, "static_features.parquet"))

metadata <- list(
  status = "completed", task = "2A", node_count = nrow(nodes), target_week_count = length(target_week_ids),
  history_week_count = length(history_week_ids), target_start = as.character(analysis_start),
  target_end = as.character(analysis_end), history_start = as.character(history_dates[[1L]]),
  history_end = as.character(analysis_end), dynamic_feature_names = environmental_features,
  static_feature_names = static_features, livestock_density_features = livestock_features,
  livestock_imputation_indicator_features = livestock_indicator_features,
  calendar_feature_names = c("week_sin", "week_cos"),
  calendar_period_weeks = 52.1775, response_definition = "recorded detections assigned to canonical node-week; presence is count > 0",
  coordinate_features_excluded = TRUE, response_lags_excluded = TRUE,
  livestock_transform = "log1p density columns only before fold standardization; indicators remain 0/1",
  livestock_imputation_rule = "nearest valid aligned density donor by species; no zero filling or domain change",
  livestock_imputation_provenance = normalizePath(imputation_provenance_path, winslash = "/", mustWork = TRUE),
  environmental_transform = "identity before fold standardization",
  canonical_mask = normalizePath(mask_path, winslash = "/", mustWork = TRUE),
  array_shapes = list(dynamic_history_features = c(length(history_week_ids), nrow(nodes), length(environmental_features)),
    dynamic_features = c(length(target_week_ids), nrow(nodes), length(environmental_features)),
    static_features = c(nrow(nodes), length(static_features)), targets_count = c(length(target_week_ids), nrow(nodes)),
    targets_presence = c(length(target_week_ids), nrow(nodes))), response_summary = list(
      total_node_weeks = as.double(length(target_week_ids) * nrow(nodes)), positive_node_weeks = sum(presence),
      zero_node_weeks = sum(!presence), positive_fraction = mean(presence)))
jsonlite::write_json(metadata, file.path(raw_root, "feature_manifest.json"), auto_unbox = TRUE, pretty = TRUE, na = "null")
message("Built Task-2A raw arrays under ", raw_root)
