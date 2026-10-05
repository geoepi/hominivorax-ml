#!/usr/bin/env Rscript

## Area-aware aggregation of the two prescribed anthropogenic rasters to the
## existing canonical V2-A node polygons. No raster is modified on disk.

suppressPackageStartupMessages({
  library(arrow)
  library(terra)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
value_for <- function(flag, default = "") {
  index <- match(flag, args)
  if (is.na(index) || index == length(args)) default else args[[index + 1L]]
}

model_output <- value_for("--model-output", Sys.getenv("STGNN_MODEL_OUTPUT_ROOT", "/project/disease_ecology/STGNN-output/revised_model_data"))
canonical_mask_path <- value_for("--canonical-mask", Sys.getenv("STGNN_CANONICAL_MASK", "/project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif"))
output_root <- value_for("--output-root", Sys.getenv("STGNN_AUGMENTATION_STATIC_ROOT", "/project/disease_ecology/STGNN-output/predictor_augmentation/static"))
road_path <- value_for("--road-raster", "/project/disease_ecology/NWScrewworm/data/raw_data/road_density/road_density_crp.tif")
night_path <- value_for("--night-raster", "/project/disease_ecology/NWScrewworm/data/raw_data/night_illumination/night_illum_crp.tif")

required <- c(model_output, canonical_mask_path, road_path, night_path)
if (any(!file.exists(required))) {
  stop("Required input is missing: ", paste(required[!file.exists(required)], collapse = ", "))
}
dir.create(output_root, recursive = TRUE, showWarnings = FALSE)

atomic <- function(path, writer) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  temporary <- tempfile(pattern = paste0(".", basename(path), "."), tmpdir = dirname(path))
  on.exit(unlink(temporary), add = TRUE)
  writer(temporary)
  if (!file.rename(temporary, path)) stop("Atomic rename failed for ", path)
}

nodes <- arrow::read_parquet(file.path(model_output, "raw", "nodes.parquet"), as_data_frame = TRUE)
if (!all(c("model_node_id", "raster_cell") %in% names(nodes))) stop("Canonical nodes lack model_node_id/raster_cell")
nodes <- nodes[order(nodes$model_node_id), , drop = FALSE]
if (nrow(nodes) != 10037L || anyDuplicated(nodes$model_node_id) || !identical(as.integer(nodes$model_node_id), 0:10036)) {
  stop("Canonical V2-A node contract failed: expected 10,037 zero-based contiguous nodes")
}
if (any(!is.finite(nodes$raster_cell)) || any(nodes$raster_cell < 1)) stop("Canonical raster cells are invalid")

canonical <- terra::rast(canonical_mask_path)
if (terra::nlyr(canonical) != 1L) stop("Canonical mask must have one layer")
mask_values <- terra::values(canonical, mat = FALSE)
valid_mask <- !is.na(mask_values) & is.finite(mask_values)
node_cells <- as.integer(nodes$raster_cell)
if (any(nodes$raster_cell != node_cells)) stop("Canonical node raster cells must be integer-valued")
if (sum(valid_mask) < nrow(nodes)) stop("Canonical mask has fewer valid cells than the 10,037-node model contract")
if (any(node_cells < 1L | node_cells > terra::ncell(canonical) | !valid_mask[node_cells])) {
  stop("One or more canonical model raster cells are absent from the supplied mask")
}

## Use the canonical raster-cell number as the polygon attribute. This keeps
## polygon ordering independent of terra's vectorization order.
cell_id_raster <- canonical
cell_values <- rep(NA_real_, terra::ncell(canonical))
cell_values[valid_mask] <- which(valid_mask)
terra::values(cell_id_raster) <- cell_values
target_polygons <- terra::as.polygons(cell_id_raster, aggregate = FALSE, values = TRUE, na.rm = TRUE)
target_cell_values <- terra::values(target_polygons, mat = FALSE)[, 1]
target_order <- match(as.integer(nodes$raster_cell), as.integer(target_cell_values))
if (anyNA(target_order)) stop("Canonical node raster cells could not be converted to polygons")
target_polygons <- target_polygons[target_order, ]

raster_metadata <- function(path, label) {
  raster <- tryCatch(terra::rast(path), error = function(e) stop(label, " raster did not open: ", conditionMessage(e)))
  if (terra::nlyr(raster) != 1L) stop(label, " raster must have exactly one layer")
  sample <- tryCatch(terra::readValues(raster, row = 1, nrows = min(10, terra::nrow(raster))), error = function(e) stop(label, " values could not be read: ", conditionMessage(e)))
  if (!length(sample)) stop(label, " raster returned no readable values")
  range <- tryCatch(terra::global(raster, c("min", "max"), na.rm = TRUE), error = function(e) stop(label, " global values could not be read: ", conditionMessage(e)))
  minimum <- as.numeric(range[1, 1]); maximum <- as.numeric(range[1, 2])
  if (!is.finite(minimum) || !is.finite(maximum)) stop(label, " has no finite source values")
  if (!terra::is.lonlat(raster) && !nzchar(terra::crs(raster))) stop(label, " has no CRS")
  list(
    raster = raster,
    rows = terra::nrow(raster), columns = terra::ncol(raster), cells = terra::ncell(raster),
    crs = terra::crs(raster), resolution_x = terra::res(raster)[1], resolution_y = terra::res(raster)[2],
    xmin = terra::ext(raster)[1], xmax = terra::ext(raster)[2], ymin = terra::ext(raster)[3], ymax = terra::ext(raster)[4],
    nodata = terra::NAflag(raster), minimum = minimum, maximum = maximum,
    finite_sample_count = sum(is.finite(sample)), source_path = normalizePath(path, winslash = "/", mustWork = TRUE), source = label
  )
}

aggregate_raster <- function(info, label) {
  raster <- info$raster
  if (terra::is.lonlat(raster)) stop(label, " is in geographic CRS; area-aware aggregation requires a projected source CRS")
  polygons <- target_polygons
  same <- tryCatch(terra::same.crs(polygons, raster), error = function(e) FALSE)
  if (!same) polygons <- terra::project(polygons, terra::crs(raster))
  extracted <- tryCatch(terra::extract(raster, polygons, exact = TRUE, ID = TRUE), error = function(e) stop(label, " exact extraction failed: ", conditionMessage(e)))
  if (!all(c("ID", "weight") %in% names(extracted))) stop(label, " exact extraction did not return area weights")
  value_columns <- setdiff(names(extracted), c("ID", "weight"))
  if (length(value_columns) != 1L) stop(label, " expected one extracted value column")
  values <- as.numeric(extracted[[value_columns]])
  weights <- as.numeric(extracted$weight)
  if (!length(values) || any(!is.finite(weights) | weights < 0)) stop(label, " returned invalid area weights")
  result <- data.frame(sum_weight = numeric(nrow(nodes)), valid_weight = numeric(nrow(nodes)), weighted_sum = numeric(nrow(nodes)))
  groups <- split(seq_len(nrow(extracted)), extracted$ID)
  for (id in names(groups)) {
    index <- groups[[id]]
    target <- as.integer(id)
    result$sum_weight[target] <- sum(weights[index], na.rm = TRUE)
    valid <- is.finite(values[index])
    result$valid_weight[target] <- sum(weights[index][valid], na.rm = TRUE)
    result$weighted_sum[target] <- sum(values[index][valid] * weights[index][valid], na.rm = TRUE)
  }
  if (any(result$sum_weight <= 0 | !is.finite(result$sum_weight))) stop(label, " has target polygons with zero source overlap")
  result$coverage_fraction <- pmin(1, pmax(0, result$valid_weight / result$sum_weight))
  result$area_weighted_mean <- result$weighted_sum / result$valid_weight
  result$valid_source_support <- result$valid_weight
  result$intersected_source_support <- result$sum_weight
  if (any(!is.finite(result$area_weighted_mean) | result$coverage_fraction <= 0)) stop(label, " has unexplained missing or zero-coverage canonical nodes")
  result
}

spot_check <- function(info, label, aggregate_result) {
  indices <- unique(as.integer(c(1L, ceiling(nrow(nodes) / 3), ceiling(2 * nrow(nodes) / 3), nrow(nodes))))
  polygons <- target_polygons[indices, ]
  raster <- info$raster
  if (!terra::same.crs(polygons, raster)) polygons <- terra::project(polygons, terra::crs(raster))
  extracted <- terra::extract(raster, polygons, exact = TRUE, ID = TRUE)
  value_column <- setdiff(names(extracted), c("ID", "weight"))[[1L]]
  check_values <- vapply(indices, function(i) {
    rows <- which(extracted$ID == match(i, indices))
    valid <- is.finite(extracted[[value_column]][rows])
    sum(extracted[[value_column]][rows][valid] * extracted$weight[rows][valid]) / sum(extracted$weight[rows][valid])
  }, numeric(1))
  differences <- abs(check_values - aggregate_result$area_weighted_mean[indices])
  data.frame(source = label, metric = c("spot_check_node_count", "spot_check_max_absolute_difference", "spot_check_pass"), value = c(as.character(length(indices)), format(max(differences), scientific = TRUE), as.character(max(differences) <= 1e-10)), stringsAsFactors = FALSE)
}

distribution_row <- function(values, feature) {
  values <- as.numeric(values)
  values <- values[is.finite(values)]
  mean_value <- mean(values); sd_value <- stats::sd(values)
  skew <- if (is.finite(sd_value) && sd_value > 0) mean(((values - mean_value) / sd_value)^3) else 0
  data.frame(feature = feature, n = length(values), minimum = min(values), p50 = stats::quantile(values, .50, names = FALSE), p95 = stats::quantile(values, .95, names = FALSE), p99 = stats::quantile(values, .99, names = FALSE), maximum = max(values), mean = mean_value, standard_deviation = sd_value, skewness = skew, nonnegative = all(values >= 0), stringsAsFactors = FALSE)
}

road_info <- raster_metadata(road_path, "road_density")
night_info <- raster_metadata(night_path, "night_illumination")
road <- aggregate_raster(road_info, "road_density")
night <- aggregate_raster(night_info, "night_illumination")
road_spot_checks <- spot_check(road_info, "road_density", road)
night_spot_checks <- spot_check(night_info, "night_illumination", night)
if (!all(c(road_spot_checks$value[3], night_spot_checks$value[3]) == "TRUE")) stop("Independent raster aggregation spot checks failed")

features <- data.frame(
  node_id = as.integer(nodes$model_node_id),
  model_node_id = as.integer(nodes$model_node_id),
  road_density = road$area_weighted_mean,
  night_illumination = night$area_weighted_mean,
  road_coverage_fraction = road$coverage_fraction,
  night_illumination_coverage_fraction = night$coverage_fraction,
  road_valid_source_support = road$valid_source_support,
  night_illumination_valid_source_support = night$valid_source_support,
  stringsAsFactors = FALSE
)
if (nrow(features) != 10037L || anyDuplicated(features$node_id) || !identical(features$node_id, 0:10036)) stop("Anthropogenic feature node contract failed")
if (any(!is.finite(features$road_density) | !is.finite(features$night_illumination))) stop("Anthropogenic means are non-finite")
if (any(features$road_density < 0 | features$night_illumination < 0)) stop("Anthropogenic values are outside the nonnegative source range")

qa <- rbind(
  data.frame(source = "road_density", metric = names(road_info)[names(road_info) != "raster"], value = unlist(road_info[names(road_info) != "raster"]), stringsAsFactors = FALSE),
  data.frame(source = "night_illumination", metric = names(night_info)[names(night_info) != "raster"], value = unlist(night_info[names(night_info) != "raster"]), stringsAsFactors = FALSE),
  road_spot_checks,
  night_spot_checks,
  data.frame(source = "aggregated_nodes", metric = c("node_count", "road_zero_coverage_nodes", "night_zero_coverage_nodes", "road_min", "road_max", "night_min", "night_max"), value = c(nrow(features), sum(features$road_coverage_fraction <= 0), sum(features$night_illumination_coverage_fraction <= 0), min(features$road_density), max(features$road_density), min(features$night_illumination), max(features$night_illumination)), stringsAsFactors = FALSE)
)
qa$value <- as.character(qa$value)
distribution <- rbind(distribution_row(features$road_density, "road_density"), distribution_row(features$night_illumination, "night_illumination"))

atomic(file.path(output_root, "road_night_node_features.parquet"), function(path) arrow::write_parquet(features, path))
atomic(file.path(output_root, "road_night_node_features.csv"), function(path) utils::write.csv(features, path, row.names = FALSE, na = ""))
atomic(file.path(output_root, "road_night_aggregation_qa.csv"), function(path) utils::write.csv(qa, path, row.names = FALSE, na = ""))
atomic(file.path(output_root, "transformation_diagnostics.csv"), function(path) utils::write.csv(distribution, path, row.names = FALSE, na = ""))
manifest <- list(status = "complete", generated_utc = format(Sys.time(), tz = "UTC", usetz = TRUE), node_count = nrow(features), canonical_mask = normalizePath(canonical_mask_path, winslash = "/", mustWork = TRUE), model_nodes = normalizePath(file.path(model_output, "raw", "nodes.parquet"), winslash = "/", mustWork = TRUE), sources = list(road_density = road_info[names(road_info) != "raster"], night_illumination = night_info[names(night_info) != "raster"]), aggregation = "terra exact area-weighted overlap in the projected source CRS; target polygons are canonical mask cells", output_features = c("road_density", "night_illumination"), coverage_fields = c("road_coverage_fraction", "night_illumination_coverage_fraction"), response_free = TRUE)
atomic(file.path(output_root, "road_night_aggregation_manifest.json"), function(path) jsonlite::write_json(manifest, path, auto_unbox = TRUE, pretty = TRUE, na = "null"))
message("Completed area-aware road/night aggregation for ", nrow(features), " canonical nodes")

