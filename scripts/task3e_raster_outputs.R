#!/usr/bin/env Rscript

# Task 3E: rasterize persisted, frozen STGNN-Hurdle-V2A predictions and
# produce exact-cell ggplot2 maps.  This script never fits a model.

suppressPackageStartupMessages({
  library(data.table)
  library(ggplot2)
  library(jsonlite)
  library(sf)
  library(terra)
})

MODEL_ID <- "STGNN-Hurdle-V2A"
WEEKS <- sprintf("2026-W%02d", 17:29)
FOCAL_WEEKS <- c("2026-W17", "2026-W23", "2026-W29")
PSEUDO_WEEKS <- c("2026-W23", "2026-W26")
NODE_COUNT <- 10037L
NODATA_VALUE <- -9999

output_root <- Sys.getenv(
  "STGNN_OUTPUT_ROOT",
  "/project/disease_ecology/STGNN-output/v2_rasters"
)
input_root <- file.path(output_root, "inputs")
mask_path <- "/project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif"
land_path <- "/project/disease_ecology/NWS/Chad/NWS_ABM/data/ancillary/border_shapefiles/ne_10m_land.shp"
country_path <- "/project/disease_ecology/NWS/Chad/NWS_ABM/data/ancillary/border_shapefiles/ne_50m_admin_0_countries.shp"
state_path <- "/project/disease_ecology/NWS/Chad/NWS_ABM/data/ancillary/border_shapefiles/ne_50m_admin_1_states_provinces_lakes.shp"

dir.create(output_root, recursive = TRUE, showWarnings = FALSE)
for (folder in c("probability", "expected_count", "conditional_count", "pseudo_nowcast", "figures", "manifests", "qa")) {
  dir.create(file.path(output_root, folder), recursive = TRUE, showWarnings = FALSE)
}

stop_if_missing <- function(paths) {
  missing <- paths[!file.exists(paths)]
  if (length(missing)) stop("missing required file(s): ", paste(missing, collapse = ", "))
}

stop_if_missing(c(
  file.path(input_root, "task3e_predictions.csv"),
  file.path(input_root, "task3e_observations.csv"),
  file.path(input_root, "task3e_input_manifest.json"),
  mask_path
))

git_sha <- tryCatch(
  system2("git", c("rev-parse", "HEAD"), stdout = TRUE, stderr = FALSE)[[1L]],
  error = function(e) NA_character_
)
if (is.na(git_sha) || !nzchar(git_sha)) stop("could not determine repository HEAD")

sha256_file <- function(path) {
  line <- system2("sha256sum", path, stdout = TRUE, stderr = TRUE)
  if (!length(line)) return(NA_character_)
  sub("\\s+.*$", "", line[[1L]])
}

input_manifest <- jsonlite::read_json(
  file.path(input_root, "task3e_input_manifest.json"),
  simplifyVector = TRUE
)
model_manifest_sha <- input_manifest$source_artifacts$frozen_model_manifest$sha256
created_utc <- format(Sys.time(), tz = "UTC", usetz = TRUE)

predictions <- data.table::fread(file.path(input_root, "task3e_predictions.csv"))
observations <- data.table::fread(file.path(input_root, "task3e_observations.csv"))
predictions[, week := as.character(week)]
observations[, week := as.character(week)]

required_prediction_columns <- c(
  "week", "model_node_id", "canonical_node_id", "raster_cell", "row", "column",
  "x", "y", "lon", "lat", "country_or_domain_region",
  "predicted_probability", "predicted_conditional_mean", "predicted_unconditional_mean"
)
if (!all(required_prediction_columns %in% names(predictions))) {
  stop("prediction input columns are incomplete")
}
if (!setequal(unique(predictions$week), WEEKS)) stop("prediction week set is incorrect")
if (nrow(predictions) != length(WEEKS) * NODE_COUNT) stop("prediction row count is incorrect")
if (predictions[, .N, by = .(week, model_node_id)][, any(N != 1L)]) {
  stop("prediction input is not one row per week-node")
}

mask <- terra::rast(mask_path)
mask_values <- terra::values(mask, mat = FALSE)
node_map <- unique(predictions[, .(model_node_id, canonical_node_id, raster_cell, row, column, x, y, lon, lat, country_or_domain_region)])
if (nrow(node_map) != NODE_COUNT) stop("node mapping row count is incorrect")
if (anyDuplicated(node_map$raster_cell)) stop("node mapping contains duplicate raster cells")
valid_cells <- as.integer(node_map$raster_cell)
if (any(is.na(mask_values[valid_cells]))) stop("revised-domain nodes fall outside environmental support")
if (!all(terra::rowFromCell(mask, node_map$raster_cell) == node_map$row)) stop("row mapping mismatch")
if (!all(terra::colFromCell(mask, node_map$raster_cell) == node_map$column)) stop("column mapping mismatch")
if (nrow(mask) <= 0L || ncol(mask) <= 0L) stop("canonical mask dimensions are invalid")

if (any(!is.finite(predictions$predicted_probability)) ||
    any(predictions$predicted_probability < 0 | predictions$predicted_probability > 1)) {
  stop("probability range failed")
}
if (any(!is.finite(predictions$predicted_unconditional_mean)) ||
    any(predictions$predicted_unconditional_mean < 0)) {
  stop("expected-count range failed")
}
if (any(!is.finite(predictions$predicted_conditional_mean)) ||
    any(predictions$predicted_conditional_mean < 0)) {
  stop("conditional-count range failed")
}

make_raster <- function(week, value_column, output_path, variable_name) {
  week_value <- as.character(week)
  rows <- predictions[which(as.character(predictions[["week"]]) == week_value)]
  if (nrow(rows) != NODE_COUNT) stop("incomplete prediction rows for ", week)
  result <- mask
  result_values <- rep(NA_real_, terra::ncell(mask))
  result_values[as.integer(rows$raster_cell)] <- as.numeric(rows[[value_column]])
  terra::values(result) <- result_values
  terra::writeRaster(
    result,
    output_path,
    overwrite = TRUE,
    datatype = "FLT4S",
    NAflag = NODATA_VALUE,
    gdal = c("COMPRESS=DEFLATE", "PREDICTOR=2", "TILED=YES"),
    wopt = list(names = variable_name)
  )
  output_path
}

raster_records <- list()
record_raster <- function(path, variable, week, prediction_type) {
  raster_records[[length(raster_records) + 1L]] <<- data.frame(
    model_id = MODEL_ID,
    variable = variable,
    week = week,
    prediction_type = prediction_type,
    source_prediction_artifact = input_manifest$prediction_selection$artifact,
    git_sha = git_sha,
    model_manifest_sha = model_manifest_sha,
    creation_timestamp = created_utc,
    crs = terra::crs(mask),
    resolution_x = terra::res(mask)[[1L]],
    resolution_y = terra::res(mask)[[2L]],
    extent = paste(as.vector(terra::ext(mask)), collapse = ","),
    nrow = terra::nrow(mask),
    ncol = terra::ncol(mask),
    nodata_value = NODATA_VALUE,
    datatype = "FLT4S",
    path = normalizePath(path, winslash = "/", mustWork = TRUE),
    stringsAsFactors = FALSE
  )
}

for (week in WEEKS) {
  path <- file.path(output_root, "probability", paste0("stgnn_v2a_probability_", week, ".tif"))
  make_raster(week, "predicted_probability", path, "predicted_probability")
  record_raster(path, "predicted_probability", week, "frozen_validation_prediction")

  path <- file.path(output_root, "expected_count", paste0("stgnn_v2a_expected_count_", week, ".tif"))
  make_raster(week, "predicted_unconditional_mean", path, "predicted_expected_count")
  record_raster(path, "predicted_expected_count", week, "frozen_validation_prediction")

  path <- file.path(output_root, "conditional_count", paste0("stgnn_v2a_conditional_positive_count_", week, ".tif"))
  make_raster(week, "predicted_conditional_mean", path, "predicted_conditional_positive_count")
  record_raster(path, "predicted_conditional_positive_count", week, "frozen_validation_prediction")
}

for (week in PSEUDO_WEEKS) {
  path <- file.path(output_root, "pseudo_nowcast", paste0("stgnn_v2a_preoutcome_probability_", week, ".tif"))
  make_raster(week, "predicted_probability", path, "preoutcome_probability")
  record_raster(path, "preoutcome_probability", week, "preoutcome_pseudo_nowcast_prediction")

  path <- file.path(output_root, "pseudo_nowcast", paste0("stgnn_v2a_preoutcome_expected_count_", week, ".tif"))
  make_raster(week, "predicted_unconditional_mean", path, "preoutcome_expected_count")
  record_raster(path, "preoutcome_expected_count", week, "preoutcome_pseudo_nowcast_prediction")
}

raster_metadata <- data.table::rbindlist(raster_records, fill = TRUE)
data.table::fwrite(raster_metadata, file.path(output_root, "manifests", "task3e_raster_metadata.csv"))
jsonlite::write_json(
  split(raster_metadata, seq_len(nrow(raster_metadata))),
  file.path(output_root, "manifests", "task3e_raster_metadata.json"),
  pretty = TRUE,
  auto_unbox = TRUE,
  na = "null"
)

read_map_data <- function(path, week, variable) {
  raster <- terra::rast(path)
  frame <- as.data.frame(raster, xy = TRUE, na.rm = TRUE)
  names(frame)[[3L]] <- "value"
  frame$week <- week
  frame$variable <- variable
  frame
}

probability_max <- max(predictions$predicted_probability, na.rm = TRUE)
expected_max <- max(predictions$predicted_unconditional_mean, na.rm = TRUE)
conditional_max <- max(predictions$predicted_conditional_mean, na.rm = TRUE)

target_crs <- sf::st_crs(terra::crs(mask))
mask_extent <- as.vector(terra::ext(mask))
crop_to_mask <- function(path, target_crs) {
  if (!file.exists(path)) return(NULL)
  layer <- sf::st_read(path, quiet = TRUE)
  layer <- sf::st_transform(layer, target_crs)
  bbox <- sf::st_bbox(c(
    xmin = mask_extent[[1L]], xmax = mask_extent[[2L]],
    ymin = mask_extent[[3L]], ymax = mask_extent[[4L]]
  ), crs = target_crs)
  suppressWarnings(sf::st_crop(layer, bbox))
}
land <- crop_to_mask(land_path, target_crs)
countries <- crop_to_mask(country_path, target_crs)
states <- crop_to_mask(state_path, target_crs)

observed_sf <- NULL
if (nrow(observations)) {
  observed_sf <- sf::st_as_sf(observations, coords = c("lon", "lat"), crs = 4326, remove = FALSE)
  observed_sf <- sf::st_transform(observed_sf, target_crs)
}

boundary_layers <- function() {
  layers <- list()
  if (!is.null(land) && nrow(land)) layers$land <- geom_sf(data = land, fill = NA, colour = "grey75", linewidth = 0.15, inherit.aes = FALSE)
  if (!is.null(countries) && nrow(countries)) layers$country <- geom_sf(data = countries, fill = NA, colour = "grey35", linewidth = 0.22, inherit.aes = FALSE)
  if (!is.null(states) && nrow(states)) layers$states <- geom_sf(data = states, fill = NA, colour = "grey62", linewidth = 0.12, inherit.aes = FALSE)
  layers
}

map_theme <- theme_minimal(base_size = 9) + theme(
  panel.grid = element_blank(),
  panel.background = element_rect(fill = "white", colour = NA),
  plot.background = element_rect(fill = "white", colour = NA),
  axis.title = element_blank(),
  axis.text = element_blank(),
  axis.ticks = element_blank(),
  strip.background = element_rect(fill = "grey94", colour = NA),
  strip.text = element_text(face = "bold"),
  legend.title = element_text(size = 8),
  legend.text = element_text(size = 7)
)

coord_map <- coord_sf(
  crs = target_crs,
  xlim = mask_extent[1:2],
  ylim = mask_extent[3:4],
  expand = FALSE,
  datum = NA
)

observed_layer <- function(week, include_observed) {
  if (!include_observed || is.null(observed_sf)) return(NULL)
  current <- observed_sf[observed_sf$week == week, ]
  if (!nrow(current)) return(NULL)
  geom_sf(data = current, shape = 1, colour = "#C62828", fill = NA, size = 0.7, stroke = 0.35, inherit.aes = FALSE)
}

make_row_plot <- function(weeks, variable, label, fill_label, limits, folder, include_observed = FALSE, title = NULL) {
  frames <- lapply(weeks, function(week) {
    path <- if (variable == "probability") {
      file.path(output_root, "probability", paste0("stgnn_v2a_probability_", week, ".tif"))
    } else if (variable == "expected_count") {
      file.path(output_root, "expected_count", paste0("stgnn_v2a_expected_count_", week, ".tif"))
    } else {
      file.path(output_root, "conditional_count", paste0("stgnn_v2a_conditional_positive_count_", week, ".tif"))
    }
    read_map_data(path, week, variable)
  })
  frame <- data.table::rbindlist(frames)
  p <- ggplot(frame, aes(x = x, y = y, fill = value)) +
    geom_raster() +
    boundary_layers() +
    scale_fill_viridis_c(
      option = "C",
      limits = c(0, limits),
      oob = scales::squish,
      name = fill_label,
      guide = guide_colourbar(barheight = unit(34, "mm"), barwidth = unit(5, "mm"))
    ) +
    facet_wrap(~week, nrow = 1) +
    coord_map +
    labs(title = title, subtitle = label) +
    map_theme
  if (include_observed) {
    for (week in weeks) p <- p + observed_layer(week, TRUE)
  }
  p
}

draw_stack <- function(plots, png_path, pdf_path, width = 12, height = 8) {
  png(png_path, width = width * 300, height = height * 300, res = 300)
  grid::grid.newpage()
  grid::pushViewport(grid::viewport(layout = grid::grid.layout(length(plots), 1)))
  for (index in seq_along(plots)) {
    print(plots[[index]], vp = grid::viewport(layout.pos.row = index))
  }
  grid::popViewport()
  dev.off()

  pdf(pdf_path, width = width, height = height, useDingbats = FALSE)
  grid::grid.newpage()
  grid::pushViewport(grid::viewport(layout = grid::grid.layout(length(plots), 1)))
  for (index in seq_along(plots)) {
    print(plots[[index]], vp = grid::viewport(layout.pos.row = index))
  }
  grid::popViewport()
  dev.off()
}

figure_paths <- character()
figure1_png <- file.path(output_root, "figures", "v2a_figure1_current_estimates.png")
figure1_pdf <- file.path(output_root, "figures", "v2a_figure1_current_estimates.pdf")
draw_stack(
  list(
    make_row_plot(FOCAL_WEEKS, "probability", "Predicted probability of recorded detection", "Predicted probability", probability_max, "probability", title = "STGNN-Hurdle-V2A current estimates"),
    make_row_plot(FOCAL_WEEKS, "expected_count", "Predicted expected detection count", "Expected count", expected_max, "expected_count")
  ),
  figure1_png,
  figure1_pdf
)
figure_paths <- c(figure_paths, figure1_png, figure1_pdf)

make_pseudo_plot <- function(week, variable, title, include_observed = FALSE) {
  if (variable == "probability") {
    path <- file.path(output_root, "pseudo_nowcast", paste0("stgnn_v2a_preoutcome_probability_", week, ".tif"))
    limit <- probability_max
    fill_label <- "Predicted probability"
  } else {
    path <- file.path(output_root, "pseudo_nowcast", paste0("stgnn_v2a_preoutcome_expected_count_", week, ".tif"))
    limit <- expected_max
    fill_label <- "Expected count"
  }
  frame <- read_map_data(path, week, variable)
  p <- ggplot(frame, aes(x = x, y = y, fill = value)) +
    geom_raster() +
    boundary_layers() +
    scale_fill_viridis_c(option = "C", limits = c(0, limit), oob = scales::squish, name = fill_label) +
    coord_map +
    labs(title = title) +
    map_theme
  overlay <- observed_layer(week, include_observed)
  if (!is.null(overlay)) p <- p + overlay
  p
}

figure2_png <- file.path(output_root, "figures", "v2a_figure2_pseudo_nowcast_2026-W23.png")
figure2_pdf <- file.path(output_root, "figures", "v2a_figure2_pseudo_nowcast_2026-W23.pdf")
draw_stack(
  list(
    make_pseudo_plot("2026-W23", "probability", "2026-W23 pre-outcome pseudo-nowcast probability"),
    make_pseudo_plot("2026-W23", "expected_count", "2026-W23 pre-outcome pseudo-nowcast expected count"),
    make_pseudo_plot("2026-W23", "probability", "2026-W23 scored view - observed detections overlaid after scoring", TRUE)
  ),
  figure2_png,
  figure2_pdf,
  width = 10,
  height = 11
)
figure_paths <- c(figure_paths, figure2_png, figure2_pdf)

validate_raster <- function(path, sample_rows) {
  raster <- terra::rast(path)
  same_geometry <-
    isTRUE(terra::nrow(mask) == terra::nrow(raster)) &&
    isTRUE(terra::ncol(mask) == terra::ncol(raster)) &&
    isTRUE(all.equal(as.numeric(terra::res(mask)), as.numeric(terra::res(raster)), tolerance = 1e-12)) &&
    isTRUE(all.equal(as.vector(terra::ext(mask)), as.vector(terra::ext(raster)), tolerance = 1e-9)) &&
    isTRUE(terra::crs(mask) == terra::crs(raster))
  values_raster <- terra::values(raster, mat = FALSE)
  inside_finite <- all(is.finite(values_raster[valid_cells]))
  outside_na <- all(is.na(values_raster[-valid_cells]))
  sampled_indices <- unique(round(seq(1L, nrow(sample_rows), length.out = min(25L, nrow(sample_rows)))))
  sampled <- sample_rows[sampled_indices, ]
  sampled_values <- values_raster[as.integer(sampled$raster_cell)]
  source_values <- sampled[[if (grepl("probability", basename(path))) "predicted_probability" else if (grepl("expected", basename(path))) "predicted_unconditional_mean" else "predicted_conditional_mean"]]
  agreement <- isTRUE(all.equal(as.numeric(sampled_values), as.numeric(source_values), tolerance = 1e-5))
  c(
    same_geometry = same_geometry,
    valid_cells_finite = inside_finite,
    masked_cells_na = outside_na,
    sampled_values_agree = agreement
  )
}

tif_paths <- c(
  list.files(file.path(output_root, "probability"), pattern = "\\.tif$", full.names = TRUE),
  list.files(file.path(output_root, "expected_count"), pattern = "\\.tif$", full.names = TRUE),
  list.files(file.path(output_root, "conditional_count"), pattern = "\\.tif$", full.names = TRUE),
  list.files(file.path(output_root, "pseudo_nowcast"), pattern = "\\.tif$", full.names = TRUE)
)
qa_rows <- lapply(tif_paths, function(path) {
  week <- sub(".*(2026-W[0-9]{2}).*", "\\1", basename(path))
  week_value <- as.character(week)
  sample_rows <- predictions[which(as.character(predictions[["week"]]) == week_value)]
  result <- validate_raster(path, sample_rows)
  data.frame(path = path, t(result), stringsAsFactors = FALSE)
})
qa <- data.table::rbindlist(qa_rows, fill = TRUE)
qa$all_checks_pass <- apply(qa[, c("same_geometry", "valid_cells_finite", "masked_cells_na", "sampled_values_agree")], 1, all)

qa_summary <- list(
  model_id = MODEL_ID,
  git_sha = git_sha,
  canonical_mask = mask_path,
  canonical_environment_supported_cell_count = sum(!is.na(mask_values)),
  canonical_revised_domain_cell_count = length(valid_cells),
  canonical_dimensions = list(nrow = terra::nrow(mask), ncol = terra::ncol(mask), ncell = terra::ncell(mask)),
  canonical_crs = terra::crs(mask),
  canonical_resolution = as.numeric(terra::res(mask)),
  canonical_extent = as.vector(terra::ext(mask)),
  canonical_nodata = NODATA_VALUE,
  node_count = NODE_COUNT,
  valid_cell_count = length(valid_cells),
  node_mapping_matches_mask = TRUE,
  prediction_ranges = list(
    probability = c(min = min(predictions$predicted_probability), max = max(predictions$predicted_probability)),
    expected_count = c(min = min(predictions$predicted_unconditional_mean), max = max(predictions$predicted_unconditional_mean)),
    conditional_count = c(min = min(predictions$predicted_conditional_mean), max = max(predictions$predicted_conditional_mean))
  ),
  pseudo_nowcast_rasters_exclude_outcomes = TRUE,
  figure_generation_completed = all(file.exists(figure_paths)),
  raster_checks = qa,
  all_checks_pass = all(qa$all_checks_pass) && all(file.exists(figure_paths))
)
data.table::fwrite(qa, file.path(output_root, "qa", "task3e_raster_qa.csv"))
jsonlite::write_json(qa_summary, file.path(output_root, "qa", "task3e_raster_qa.json"), pretty = TRUE, auto_unbox = TRUE, na = "null")
if (!isTRUE(qa_summary$all_checks_pass)) stop("Task 3E raster QA failed")

all_checksum_paths <- c(tif_paths, figure_paths)
checksums <- data.frame(
  relative_path = vapply(all_checksum_paths, function(path) sub(paste0("^", output_root, "/?"), "", normalizePath(path, winslash = "/")), character(1L)),
  size_bytes = file.info(all_checksum_paths)$size,
  sha256 = vapply(all_checksum_paths, sha256_file, character(1L)),
  stringsAsFactors = FALSE
)
data.table::fwrite(checksums, file.path(output_root, "manifests", "task3e_checksums.csv"))

manifest <- list(
  git_sha = git_sha,
  branch = system2("git", c("branch", "--show-current"), stdout = TRUE)[[1L]],
  model_id = MODEL_ID,
  model_manifest_sha = model_manifest_sha,
  weeks_rendered = WEEKS,
  focal_figure_weeks = FOCAL_WEEKS,
  pseudo_nowcast_weeks = PSEUDO_WEEKS,
  variables_rendered = c("predicted_probability", "predicted_expected_count", "predicted_conditional_positive_count"),
  prediction_source = input_manifest$prediction_selection,
  canonical_grid_reference = mask_path,
  canonical_dimensions = list(nrow = terra::nrow(mask), ncol = terra::ncol(mask), ncell = terra::ncell(mask)),
  canonical_crs = terra::crs(mask),
  canonical_resolution = as.numeric(terra::res(mask)),
  canonical_extent = as.vector(terra::ext(mask)),
  nodata_value = NODATA_VALUE,
  datatype = "FLT4S",
  count_display_scale = "raw values; no transformed color scale",
  tif_paths = normalizePath(all_checksum_paths[seq_along(tif_paths)], winslash = "/", mustWork = TRUE),
  figure_paths = normalizePath(figure_paths, winslash = "/", mustWork = TRUE),
  metadata_path = normalizePath(file.path(output_root, "manifests", "task3e_raster_metadata.csv"), winslash = "/", mustWork = TRUE),
  checksum_path = normalizePath(file.path(output_root, "manifests", "task3e_checksums.csv"), winslash = "/", mustWork = TRUE),
  qa_path = normalizePath(file.path(output_root, "qa", "task3e_raster_qa.json"), winslash = "/", mustWork = TRUE),
  creation_timestamp = created_utc,
  qa_passed = TRUE,
  pseudo_nowcast_prediction_only_rasters = TRUE
)
jsonlite::write_json(manifest, file.path(output_root, "manifests", "task3e_raster_manifest.json"), pretty = TRUE, auto_unbox = TRUE, na = "null")
writeLines(sha256_file(file.path(output_root, "manifests", "task3e_raster_manifest.json")), file.path(output_root, "manifests", "task3e_raster_manifest.json.sha256"))

message("Task 3E raster and figure production completed: ", output_root)
