#!/usr/bin/env Rscript

# Graphics-only renderer for the completed STRUCTURED_A3 W44 candidate.
# Reads persisted products and writes only to a separate versioned figure root.

suppressPackageStartupMessages({
  library(data.table)
  library(ggplot2)
  library(jsonlite)
  library(sf)
  library(terra)
  library(arrow)
})

args <- commandArgs(trailingOnly = TRUE)
arg <- function(name, default) {
  i <- match(name, args)
  if (is.na(i) || i == length(args)) default else args[[i + 1L]]
}

mode <- match.arg(arg("--mode", "full"), c("pilot", "full"))
candidate_root <- normalizePath(
  arg("--candidate-root", "/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44"),
  winslash = "/", mustWork = TRUE
)
input_root <- file.path(candidate_root, "fullfit_products")
default_output <- file.path(candidate_root, "figures_cartographic_revision_v1")
output_root <- normalizePath(arg("--output-root", default_output), winslash = "/", mustWork = FALSE)
boundary_root <- arg("--boundary-root", "/project/disease_ecology/NWS/Chad/NWS_ABM/data/ancillary/border_shapefiles")
if (startsWith(output_root, paste0(input_root, "/")) || identical(output_root, input_root)) {
  stop("Output root must be separate from the candidate full-fit source directory")
}
if (mode == "full" && !identical(output_root, default_output)) {
  stop("Full mode writes only to the requested versioned figure directory")
}
if (dir.exists(output_root) && length(list.files(output_root, all.files = TRUE, no.. = TRUE))) {
  stop("Refusing to overwrite a non-empty cartographic output directory: ", output_root)
}

script_file <- sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE)[[1L]])
script_dir <- dirname(normalizePath(script_file, winslash = "/", mustWork = TRUE))
source(file.path(script_dir, "cartographic_style.R"), local = TRUE)
palette_check <- a3_cartographic_palette_check()
if (!palette_check$monotonic_light_to_dark) stop("Shared cartographic palette is not monotonic light-to-dark")

sha256_file <- function(path) {
  output <- system2("sha256sum", path, stdout = TRUE, stderr = TRUE)
  if (!length(output) || nchar(strsplit(output[[1L]], "[[:space:]]+")[[1L]][[1L]]) != 64L) {
    stop("Could not calculate SHA-256 for ", path, ": ", paste(output, collapse = " "))
  }
  sub("\\s+.*$", "", output[[1L]])
}

artifact_manifest_path <- file.path(input_root, "structured_a3_fullfit_output_manifest.csv")
if (!file.exists(artifact_manifest_path)) stop("Candidate full-fit artifact manifest is missing")
artifact_manifest_sha <- sha256_file(artifact_manifest_path)
artifact_manifest <- fread(artifact_manifest_path)
manifest_columns <- c("artifact_type", "path", "relative_path", "sha256", "model_sha", "fit_end_week")
if (!all(manifest_columns %in% names(artifact_manifest))) stop("Candidate artifact manifest schema is incomplete")
artifact_manifest[, relative_path := as.character(relative_path)]
artifact_manifest[, path := as.character(path)]
artifact_manifest[, sha256 := as.character(sha256)]
model_shas <- unique(na.omit(as.character(artifact_manifest$model_sha)))
expected_model_sha <- "b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b"
if (length(model_shas) != 1L || !identical(model_shas[[1L]], expected_model_sha)) {
  stop("Candidate model SHA does not match the authorized W44 artifact")
}

artifact_entry <- function(relative) {
  index <- which(artifact_manifest[["relative_path"]] == relative)
  rows <- artifact_manifest[index]
  if (nrow(rows) != 1L) stop("Expected one exact source-manifest entry for ", relative, "; found ", nrow(rows))
  if (!file.exists(rows$path[[1L]])) stop("Candidate source artifact is missing: ", rows$path[[1L]])
  actual_sha <- sha256_file(rows$path[[1L]])
  if (!identical(actual_sha, rows$sha256[[1L]])) stop("Candidate source checksum differs from its artifact manifest: ", relative)
  rows[1L]
}

source_rels <- c(
  "predictions/weekly_predictions.parquet",
  "predictions/observed_detections.csv",
  "interpretation/coefficients/occurrence_coefficients_ranked.csv",
  "interpretation/coefficients/count_coefficients_ranked.csv",
  "interpretation/importance/predictive_importance.csv",
  "interpretation/effects/effect_response.csv",
  "interpretation/seasonality/seasonal_effect.csv"
)
source_entries <- rbindlist(lapply(source_rels, artifact_entry), fill = TRUE)
source_paths <- setNames(source_entries$path, source_entries$relative_path)
source_hashes_before <- setNames(source_entries$sha256, source_entries$relative_path)

# Protect every source artifact named by the candidate manifest from accidental writes.
protected <- copy(artifact_manifest)
if (any(!file.exists(protected$path))) stop("At least one candidate manifest artifact is missing")
protected_hashes_before <- vapply(protected$path, sha256_file, character(1L))
if (any(protected_hashes_before != protected$sha256)) {
  stop("At least one persisted candidate artifact does not match the original output manifest")
}

prediction_path <- source_paths[["predictions/weekly_predictions.parquet"]]
pred <- as.data.table(arrow::read_parquet(prediction_path))
required_prediction_columns <- c(
  "week", "model_node_id", "raster_cell", "x", "y", "lon", "lat",
  "p_occurrence", "expected_count", "observed_count"
)
if (!all(required_prediction_columns %in% names(pred))) stop("Weekly prediction archive schema is incomplete")
weeks <- sort(unique(as.character(pred[["week"]])))
if (nrow(pred) != length(weeks) * 10037L || length(weeks) != 96L) stop("Weekly prediction archive row/week contract failed")
if (pred[, .N, by = .(week, model_node_id)][, any(N != 1L)]) stop("Prediction archive contains duplicate week/node rows")
focus_weeks <- sprintf("2026-W%02d", 39:44)
if (!all(focus_weeks %in% weeks)) stop("Candidate prediction archive does not contain all W39-W44 maps")
focus_rows <- as.character(pred[["week"]]) %in% focus_weeks
occurrence_values <- as.numeric(pred[["p_occurrence"]])
expected_values <- as.numeric(pred[["expected_count"]])
observed_values <- as.numeric(pred[["observed_count"]])
if (any(!is.finite(occurrence_values)) || any(occurrence_values < 0 | occurrence_values > 1)) stop("Occurrence probability range check failed")
if (any(!is.finite(expected_values)) || any(expected_values < 0)) stop("Expected-count range check failed")
if (any(!is.finite(observed_values)) || any(observed_values < 0)) stop("Observed-count range check failed")
expected_limit <- max(expected_values)
expected_reference <- median(expected_values[expected_values > 0])
occurrence_focus_limit <- as.numeric(stats::quantile(occurrence_values[focus_rows], 0.995, names = FALSE, na.rm = TRUE))
observation_limit <- max(observed_values[as.character(pred[["week"]]) %in% focus_weeks])
if (!is.finite(expected_limit) || expected_limit <= 0 || !is.finite(expected_reference) || expected_reference <= 0) {
  stop("Expected-count display limits could not be established from persisted predictions")
}

week_number <- function(week) as.integer(sub("^.*-W", "", week))
week_year <- function(week) as.integer(substr(week, 1L, 4L))
snapshot_weeks <- unique(c(
  weeks[[1L]],
  weeks[max(1L, ceiling(length(weeks) / 2))],
  weeks[which(weeks >= "2026-W17")[[1L]]],
  weeks[max(1L, length(weeks) - 2L)],
  tail(weeks, 1L)
))
snapshot_weeks <- snapshot_weeks[!is.na(snapshot_weeks)]
if (length(snapshot_weeks) != 5L) stop("The original five-week spatial snapshot selection did not resolve as expected")

required_raster_rels <- unlist(lapply(unique(c(focus_weeks, snapshot_weeks)), function(week) {
  stamp <- gsub("-", "_", week)
  c(
    paste0("geotiff/occurrence/a3_p_occurrence_", stamp, ".tif"),
    paste0("geotiff/expected_count/a3_expected_count_", stamp, ".tif")
  )
}), use.names = FALSE)
raster_entries <- rbindlist(lapply(required_raster_rels, artifact_entry), fill = TRUE)
source_entries <- unique(rbindlist(list(source_entries, raster_entries), fill = TRUE), by = "relative_path")
source_paths <- setNames(source_entries$path, source_entries$relative_path)
source_hashes_before <- setNames(source_entries$sha256, source_entries$relative_path)

observation_path <- source_paths[["predictions/observed_detections.csv"]]
observations <- fread(observation_path)
required_observation_columns <- c("week", "lon", "lat", "observed_count")
if (!all(required_observation_columns %in% names(observations))) stop("Observed-cell source table schema is incomplete")
observations[, week := as.character(week)]
observations <- observations[week %chin% focus_weeks]
if (!nrow(observations)) stop("No occupied model cells are available for W39-W44 observation maps")

template_rel <- paste0("geotiff/occurrence/a3_p_occurrence_", gsub("-", "_", focus_weeks[[1L]]), ".tif")
template_path <- source_paths[[template_rel]]
template <- terra::rast(template_path)
if (terra::nlyr(template) != 1L || is.na(terra::crs(template)) || !nzchar(terra::crs(template))) {
  stop("Candidate prediction raster geometry or CRS is invalid")
}
target_crs <- sf::st_crs(terra::crs(template))
raster_extent <- as.vector(terra::ext(template))
full_xlim <- unname(raster_extent[1:2])
full_ylim <- unname(raster_extent[3:4])

# The detail frame is a rendering crop only; source rasters are never changed.
detail_lon <- c(-108, -93)
detail_lat <- c(22, 37)
detail_edge <- seq(0, 1, length.out = 101L)
detail_ring <- rbind(
  cbind(detail_lon[1L] + diff(detail_lon) * detail_edge, detail_lat[1L]),
  cbind(detail_lon[2L], detail_lat[1L] + diff(detail_lat) * detail_edge),
  cbind(detail_lon[2L] - diff(detail_lon) * detail_edge, detail_lat[2L]),
  cbind(detail_lon[1L], detail_lat[2L] - diff(detail_lat) * detail_edge)
)
detail_polygon <- sf::st_sfc(sf::st_polygon(list(rbind(detail_ring, detail_ring[1L, ]))), crs = 4326)
detail_projected <- sf::st_transform(detail_polygon, target_crs)
detail_bbox <- sf::st_bbox(detail_projected)
detail_xlim <- unname(c(detail_bbox[["xmin"]], detail_bbox[["xmax"]]))
detail_ylim <- unname(c(detail_bbox[["ymin"]], detail_bbox[["ymax"]]))

read_boundary <- function(filename) {
  path <- file.path(boundary_root, filename)
  if (!file.exists(path)) stop("Required geographic boundary source is missing: ", path)
  layer <- sf::st_read(path, quiet = TRUE)
  layer <- layer[!is.na(sf::st_geometry(layer)) & !sf::st_is_empty(layer), ]
  sf::st_transform(layer, target_crs)
}
boundaries <- list(
  land = read_boundary("ne_10m_land.shp"),
  countries = read_boundary("ne_50m_admin_0_countries.shp"),
  states = read_boundary("ne_50m_admin_1_states_provinces_lakes.shp")
)
boundary_layers <- function() list(
  ggplot2::geom_sf(data = boundaries$land, fill = NA, colour = "grey78", linewidth = 0.15, inherit.aes = FALSE),
  ggplot2::geom_sf(data = boundaries$countries, fill = NA, colour = "grey34", linewidth = 0.25, inherit.aes = FALSE),
  ggplot2::geom_sf(data = boundaries$states, fill = NA, colour = "grey58", linewidth = 0.14, inherit.aes = FALSE)
)

map_theme <- ggplot2::theme_minimal(base_size = 10) + ggplot2::theme(
  plot.background = ggplot2::element_rect(fill = "white", colour = NA),
  panel.background = ggplot2::element_rect(fill = "white", colour = NA),
  legend.background = ggplot2::element_rect(fill = "white", colour = NA),
  legend.key = ggplot2::element_rect(fill = "white", colour = NA),
  panel.grid.major = ggplot2::element_line(colour = "grey91", linewidth = 0.18),
  panel.grid.minor = ggplot2::element_blank(),
  axis.title = ggplot2::element_blank(),
  axis.text = ggplot2::element_text(colour = "grey38", size = 7),
  axis.ticks = ggplot2::element_line(colour = "grey70", linewidth = 0.2),
  strip.text = ggplot2::element_text(face = "bold", size = 9),
  plot.title = ggplot2::element_text(face = "bold", size = 13, hjust = 0.5),
  plot.subtitle = ggplot2::element_text(size = 9, hjust = 0.5),
  plot.caption = ggplot2::element_text(size = 7, hjust = 0, colour = "grey35"),
  legend.title = ggplot2::element_text(size = 8),
  legend.text = ggplot2::element_text(size = 7),
  plot.margin = ggplot2::margin(8, 8, 8, 8)
)

coord_for_view <- function(view) {
  if (view == "full_domain") {
    ggplot2::coord_sf(crs = target_crs, xlim = full_xlim, ylim = full_ylim, expand = FALSE, datum = sf::st_crs(4326))
  } else {
    ggplot2::coord_sf(crs = target_crs, xlim = detail_xlim, ylim = detail_ylim, expand = FALSE, datum = sf::st_crs(4326))
  }
}

extent_description <- function(view) {
  if (view == "full_domain") {
    paste0("Full canonical raster extent in raster CRS: x=[", format(full_xlim[1L]), ",", format(full_xlim[2L]), "]; y=[", format(full_ylim[1L]), ",", format(full_ylim[2L]), "]")
  } else if (view == "mexico_texas_detail") {
    paste0("Northern Mexico-Texas rendering crop: lon=[", detail_lon[1L], ",", detail_lon[2L], "]; lat=[", detail_lat[1L], ",", detail_lat[2L], "]")
  } else {
    "Not a geographic figure"
  }
}

raster_cache <- new.env(parent = emptyenv())
frame_for <- function(week, variable) {
  rel <- if (variable == "p_occurrence") {
    paste0("geotiff/occurrence/a3_p_occurrence_", gsub("-", "_", week), ".tif")
  } else {
    paste0("geotiff/expected_count/a3_expected_count_", gsub("-", "_", week), ".tif")
  }
  key <- paste(week, variable, sep = "|")
  if (!exists(key, envir = raster_cache, inherits = FALSE)) {
    path <- source_paths[[rel]]
    raster <- terra::rast(path)
    frame <- terra::as.data.frame(raster, xy = TRUE, cells = TRUE, na.rm = FALSE)
    value_name <- setdiff(names(frame), c("x", "y", "cell"))
    if (length(value_name) != 1L) stop("Unexpected single-band candidate raster structure: ", rel)
    data.table::setnames(frame, value_name, "value")
    frame[, week := week]
    assign(key, list(path = path, frame = as.data.table(frame), raster = raster), envir = raster_cache)
  }
  get(key, envir = raster_cache, inherits = FALSE)$frame
}

prediction_limits <- list(
  occurrence_primary = c(0, 1),
  occurrence_focus = c(0, occurrence_focus_limit),
  expected_linear = c(0, expected_limit),
  expected_log1p = c(0, expected_limit)
)
expected_log_trans <- a3_scaled_log1p_trans(expected_reference)
expected_log_breaks <- sort(unique(c(
  0,
  stats::quantile(expected_values[expected_values > 0], c(0.5, 0.9, 0.99), names = FALSE),
  expected_limit
)))
occurrence_focus_breaks <- sort(unique(c(
  0,
  stats::quantile(occurrence_values[focus_rows], c(0.25, 0.5, 0.75, 0.95), names = FALSE),
  occurrence_focus_limit
)))

prediction_style <- function(variable, style) {
  if (variable == "p_occurrence" && style == "primary") {
    return(list(
      limits = prediction_limits$occurrence_primary,
      label = "P(recorded detection)",
      trans = NULL,
      breaks = seq(0, 1, by = 0.2),
      norm = "linear; fixed 0-1 probability scale",
      palette = "Sequential blue-grey; zero is #F4F4F4"
    ))
  }
  if (variable == "p_occurrence" && style == "focus") {
    return(list(
      limits = prediction_limits$occurrence_focus,
      label = "P(recorded detection; supplementary focus scale)",
      trans = NULL,
      breaks = occurrence_focus_breaks,
      norm = "linear; fixed W39-W44 99.5th percentile upper limit; values above limit saturated",
      palette = "Sequential blue-grey; zero is #F4F4F4"
    ))
  }
  if (variable == "expected_count" && style == "linear") {
    return(list(
      limits = prediction_limits$expected_linear,
      label = "Expected recorded count",
      trans = NULL,
      breaks = pretty(c(0, expected_limit), n = 6L),
      norm = "linear; fixed full-period maximum",
      palette = "Sequential blue-grey; zero is #F4F4F4"
    ))
  }
  list(
    limits = prediction_limits$expected_log1p,
    label = "Expected recorded count (supplementary log1p display; original units)",
    trans = expected_log_trans,
    breaks = expected_log_breaks,
    norm = paste0("log1p(count / ", format(expected_reference, digits = 8L, scientific = TRUE), "); original-unit legend ticks"),
    palette = "Sequential blue-grey; zero is #F4F4F4"
  )
}

prediction_caption <- function(style) {
  note <- "Valid zero = #F4F4F4; NoData = #BDBDBD. Prediction-only map; no observation layer. Descriptive full-fit output, not independent validation."
  if (style == "focus") paste(note, "Supplementary scale saturates values above its fixed 99.5th-percentile limit.") else note
}

prediction_plot <- function(selected_weeks, variable, style, view) {
  frames <- rbindlist(lapply(selected_weeks, frame_for, variable = variable), use.names = TRUE)
  frames[, week := factor(week, levels = selected_weeks)]
  spec <- prediction_style(variable, style)
  title_label <- if (variable == "p_occurrence") "Occurrence probability" else "Expected count"
  if (length(selected_weeks) == 1L) {
    title <- paste("STRUCTURED A3", title_label, "-", selected_weeks[[1L]])
    subtitle <- if (style == "focus") "Supplementary distribution-focused scale" else if (style == "log1p") "Supplementary monotonic nonlinear display; legend ticks remain in count units" else NULL
  } else {
    title <- paste("STRUCTURED A3", title_label, "- six-week comparison")
    subtitle <- if (style == "focus") "Supplementary distribution-focused scale; identical limits in every panel" else if (style == "log1p") "Supplementary monotonic nonlinear display; legend ticks remain in count units" else "Common numerical scale in all panels"
  }
  plot <- ggplot2::ggplot(frames, ggplot2::aes(x = x, y = y, fill = value)) +
    ggplot2::geom_raster(na.rm = FALSE) +
    boundary_layers() +
    a3_cartographic_fill_scale(
      limits = spec$limits,
      label = spec$label,
      breaks = spec$breaks,
      labels = scales::label_number(accuracy = 0.001, trim = TRUE),
      trans = spec$trans
    ) +
    coord_for_view(view) +
    ggplot2::labs(title = title, subtitle = subtitle, caption = prediction_caption(style)) +
    map_theme
  if (length(selected_weeks) > 1L) {
    plot <- plot + ggplot2::facet_wrap(~week, ncol = 3L, nrow = 2L, drop = FALSE)
  }
  plot
}

observation_sf <- sf::st_as_sf(observations, coords = c("lon", "lat"), crs = 4326, remove = FALSE)
observation_sf <- sf::st_transform(observation_sf, target_crs)
observation_sf$map_feature <- "Occupied 25 km model-cell centroid"

observation_location_plot <- function(week, view) {
  points <- observation_sf[observation_sf$week == week, , drop = FALSE]
  if (!nrow(points)) stop("No occupied model cells are available for ", week)
  ggplot2::ggplot() +
    boundary_layers() +
    ggplot2::geom_sf(
      data = points,
      ggplot2::aes(colour = map_feature),
      size = 0.8,
      alpha = 0.7,
      shape = 16,
      inherit.aes = FALSE
    ) +
    ggplot2::scale_colour_manual(values = c("Occupied 25 km model-cell centroid" = "#B2182B"), name = NULL) +
    coord_for_view(view) +
    ggplot2::labs(
      title = paste("STRUCTURED A3 observed detections -", week),
      subtitle = "One point per occupied model cell; point location is the existing cell centroid",
      caption = "Observation locations shown separately from all predictions. Source: persisted candidate observed_detections.csv; each row already represents an occupied 25 km model cell."
    ) +
    map_theme +
    ggplot2::theme(legend.position = "bottom")
}

observation_count_frame <- function(week) {
  raster <- terra::rast(template_path)
  frame <- terra::as.data.frame(raster, xy = TRUE, cells = TRUE, na.rm = FALSE)
  value_name <- setdiff(names(frame), c("x", "y", "cell"))
  if (length(value_name) != 1L) stop("Unexpected model-cell grid geometry for observed counts")
  data.table::setnames(frame, value_name, "value")
  values <- rep(NA_real_, terra::ncell(raster))
  week_key <- as.character(week)
  rows <- pred[as.character(pred[["week"]]) == week_key]
  if (nrow(rows) != 10037L) stop("Observation-count source does not contain one full model week: ", week)
  values[as.integer(rows[["raster_cell"]])] <- as.numeric(rows[["observed_count"]])
  frame$value <- values[as.integer(frame$cell)]
  as.data.table(frame)
}

observation_count_plot <- function(week, view) {
  frame <- observation_count_frame(week)
  ggplot2::ggplot(frame, ggplot2::aes(x = x, y = y, fill = value)) +
    ggplot2::geom_raster(na.rm = FALSE) +
    boundary_layers() +
    a3_cartographic_fill_scale(
      limits = c(0, observation_limit),
      label = "Observed detections per 25 km model cell",
      breaks = pretty(c(0, observation_limit), n = 6L),
      labels = scales::label_number(accuracy = 1L, trim = TRUE)
    ) +
    coord_for_view(view) +
    ggplot2::labs(
      title = paste("STRUCTURED A3 observed cell counts -", week),
      subtitle = "Observed counts on the existing 25 km model grid; not predicted intensity",
      caption = "Valid zero-count cells = #F4F4F4; cells outside the modeled domain (NoData) = #BDBDBD. Fixed count scale across W39-W44."
    ) +
    map_theme
}

input_sources_for_weeks <- function(selected_weeks, variable = NULL) {
  if (is.null(variable)) return("predictions/observed_detections.csv")
  relatives <- unlist(lapply(selected_weeks, function(week) {
    stamp <- gsub("-", "_", week)
    if (variable == "p_occurrence") paste0("geotiff/occurrence/a3_p_occurrence_", stamp, ".tif")
    else paste0("geotiff/expected_count/a3_expected_count_", stamp, ".tif")
  }), use.names = FALSE)
  paste(relatives, collapse = ";")
}

manifest_rows <- list()
render_figure <- function(
    plot,
    figure_id,
    description,
    relative_stem,
    source_relative_paths,
    view,
    selected_weeks,
    palette,
    limits,
    normalization,
    width,
    height,
    formats = c("png", "pdf"),
    observation_layer = "none") {
  source_rels <- strsplit(source_relative_paths, ";", fixed = TRUE)[[1L]]
  source_rows <- artifact_manifest[relative_path %chin% source_rels]
  if (nrow(source_rows) != length(unique(source_rels))) stop("Figure source path does not resolve to the authorized artifact manifest")
  source_rows <- source_rows[match(source_rels, relative_path)]
  source_sha <- vapply(source_rows$path, sha256_file, character(1L))
  if (any(source_sha != source_rows$sha256)) stop("Figure source checksum changed before rendering: ", figure_id)
  geographic_extent <- extent_description(view)
  message("Rendering ", figure_id)
  for (format in formats) {
    destination <- file.path(output_root, paste0(relative_stem, ".", format))
    dir.create(dirname(destination), recursive = TRUE, showWarnings = FALSE)
    if (file.exists(destination)) stop("Refusing to overwrite an existing figure: ", destination)
    save_args <- list(
      filename = destination,
      plot = plot,
      width = width,
      height = height,
      units = "in",
      device = format,
      bg = "white",
      limitsize = FALSE
    )
    if (format == "png") save_args$dpi <- 300
    do.call(ggplot2::ggsave, save_args)
    manifest_rows[[length(manifest_rows) + 1L]] <<- data.table(
      figure_id = figure_id,
      description = description,
      source_artifact_paths = paste(source_rows$path, collapse = ";"),
      source_artifact_sha256 = paste(source_rows$sha256, collapse = ";"),
      weeks = paste(selected_weeks, collapse = ";"),
      view = view,
      geographic_extent = geographic_extent,
      palette = palette,
      limit_min = limits[[1L]],
      limit_max = limits[[2L]],
      normalization = normalization,
      observation_layer = observation_layer,
      rendering_configuration = paste0("ggplot2; ", width, " x ", height, " in; ", if (format == "png") "300 dpi; " else "vector PDF; ", "opaque white background"),
      output_path = destination,
      output_relative_path = sub(paste0("^", output_root, "/"), "", destination),
      output_format = format,
      output_sha256 = sha256_file(destination),
      output_size_bytes = as.numeric(file.info(destination)$size)
    )
  }
}

write_prediction_product <- function(week, variable, style, view, prefix = "predictions") {
  spec <- prediction_style(variable, style)
  variable_slug <- if (variable == "p_occurrence") "p_occurrence" else "expected_count"
  weeks_for_map <- if (length(week) > 1L) week else week
  view_slug <- if (view == "full_domain") "full_domain" else "mexico_texas_detail"
  style_slug <- switch(style, primary = "primary_0_1", focus = "supplementary_focus", linear = "linear", log1p = "supplementary_log1p")
  if (prefix == "snapshots") {
    stem <- file.path(prefix, paste0(variable_slug, "_", style_slug, "_progression_snapshots"))
    id <- paste(variable_slug, style_slug, "progression_snapshots", sep = "_")
    description <- paste("Original five-week progression snapshots;", spec$norm, "and no observation overlay")
    width <- 14
    height <- 9
  } else if (length(weeks_for_map) > 1L) {
    stem <- file.path(prefix, "six_week", paste0(variable_slug, "_", style_slug, "_", view_slug))
    id <- paste(variable_slug, style_slug, "six_week", view_slug, sep = "_")
    description <- paste("Six-week", variable_slug, "comparison;", spec$norm, "and no observation overlay")
    width <- 14
    height <- 9
  } else {
    stem <- file.path(prefix, "weekly", paste0(gsub("-", "_", week), "_", variable_slug, "_", style_slug, "_", view_slug))
    id <- paste(gsub("-", "_", week), variable_slug, style_slug, view_slug, sep = "_")
    description <- paste(week, variable_slug, "prediction-only map;", spec$norm)
    width <- if (view == "full_domain") 10 else 9
    height <- if (view == "full_domain") 8 else 8
  }
  source_rels <- input_sources_for_weeks(weeks_for_map, variable)
  render_figure(
    plot = prediction_plot(weeks_for_map, variable, style, view),
    figure_id = id,
    description = description,
    relative_stem = stem,
    source_relative_paths = source_rels,
    view = view,
    selected_weeks = weeks_for_map,
    palette = spec$palette,
    limits = spec$limits,
    normalization = spec$norm,
    width = width,
    height = height,
    observation_layer = "none"
  )
}

write_observation_product <- function(week, view, aggregated = FALSE) {
  view_slug <- if (view == "full_domain") "full_domain" else "mexico_texas_detail"
  week_slug <- gsub("-", "_", week)
  if (aggregated) {
    id <- paste(week_slug, "observed_cell_counts", view_slug, sep = "_")
    stem <- file.path("observations", "cell_counts", paste0(id))
    description <- paste(week, "observed detection counts on existing 25 km model cells; not predicted intensity")
    source_rels <- "predictions/weekly_predictions.parquet"
    palette <- "Sequential blue-grey; zero is #F4F4F4"
    normalization <- "linear; fixed W39-W44 maximum observed cell count"
    limits <- c(0, observation_limit)
    plot <- observation_count_plot(week, view)
    layer <- "observed cell counts only"
  } else {
    id <- paste(week_slug, "occupied_cell_locations", view_slug, sep = "_")
    stem <- file.path("observations", "locations", id)
    description <- paste(week, "occupied 25 km model-cell centroid locations; the source table is already cell-aggregated")
    source_rels <- "predictions/observed_detections.csv"
    palette <- "Categorical red occupied-cell markers on white background"
    normalization <- "one point per observed model cell; no continuous scale"
    limits <- c(NA_real_, NA_real_)
    plot <- observation_location_plot(week, view)
    layer <- "occupied model-cell centroids only"
  }
  render_figure(
    plot = plot,
    figure_id = id,
    description = description,
    relative_stem = stem,
    source_relative_paths = source_rels,
    view = view,
    selected_weeks = week,
    palette = palette,
    limits = if (all(is.na(limits))) c(0, 0) else limits,
    normalization = normalization,
    width = if (view == "full_domain") 10 else 9,
    height = 8,
    observation_layer = layer
  )
}

interpretation_theme <- ggplot2::theme_minimal(base_size = 9) + ggplot2::theme(
  plot.background = ggplot2::element_rect(fill = "white", colour = NA),
  panel.background = ggplot2::element_rect(fill = "white", colour = NA),
  legend.background = ggplot2::element_rect(fill = "white", colour = NA)
)

render_interpretation_figures <- function() {
  coefficient_specs <- list(
    list(file = "occurrence_coefficients_ranked.csv", title = "STRUCTURED A3 occurrence coefficients"),
    list(file = "count_coefficients_ranked.csv", title = "STRUCTURED A3 positive-count coefficients")
  )
  for (spec in coefficient_specs) {
    relative <- paste0("interpretation/coefficients/", spec$file)
    table <- fread(source_paths[[relative]])
    if (!all(c("predictor", "coefficient", "group") %in% names(table))) stop("Coefficient interpretation table schema failed")
    table[, predictor := reorder(predictor, coefficient)]
    plot <- ggplot2::ggplot(table, ggplot2::aes(predictor, coefficient, colour = group)) +
      ggplot2::geom_hline(yintercept = 0, colour = "grey70") +
      ggplot2::geom_point(size = 2) + ggplot2::coord_flip() +
      ggplot2::labs(title = spec$title, subtitle = "Conditional model coefficients; standardized continuous predictors", x = NULL, y = "Coefficient") + interpretation_theme
    stem <- paste0("interpretation/coefficients/", sub("\\.csv$", "", spec$file))
    render_figure(plot, sub("\\.csv$", "", spec$file), spec$title, stem, relative, "not_applicable", character(), "Existing interpretation palette", c(NA_real_, NA_real_), "Existing statistical values; white PNG/PDF export only", 10, 8)
  }

  relative <- "interpretation/importance/predictive_importance.csv"
  importance <- fread(source_paths[[relative]])
  if (!all(c("predictor", "permutation_nll_importance", "group") %in% names(importance))) stop("Permutation-importance table schema failed")
  importance[, predictor := reorder(predictor, permutation_nll_importance)]
  plot <- ggplot2::ggplot(importance, ggplot2::aes(predictor, permutation_nll_importance, fill = group)) +
    ggplot2::geom_col() + ggplot2::coord_flip() +
    ggplot2::labs(title = "STRUCTURED A3 fixed-model permutation importance", subtitle = "Larger values indicate greater joint-NLL degradation; correlated predictors may be redundant", x = NULL, y = "Joint NLL degradation") + interpretation_theme
  render_figure(plot, "predictive_importance", "Fixed-model permutation importance", "interpretation/importance/predictive_importance", relative, "not_applicable", character(), "Existing grouped categorical palette", c(NA_real_, NA_real_), "Existing statistical values; white PNG/PDF export only", 10, 8)

  relative <- "interpretation/effects/effect_response.csv"
  effects <- fread(source_paths[[relative]])
  effect_columns <- c("predictor", "natural_scale_value", "occurrence_probability", "conditional_count_mean", "expected_count")
  if (!all(effect_columns %in% names(effects))) stop("Effect-response table schema failed")
  effect_long <- rbindlist(list(
    effects[, .(predictor, natural_scale_value, response = occurrence_probability, response_type = "occurrence probability")],
    effects[, .(predictor, natural_scale_value, response = conditional_count_mean, response_type = "conditional positive-count mean")],
    effects[, .(predictor, natural_scale_value, response = expected_count, response_type = "unconditional expected count")]
  ))
  plot <- ggplot2::ggplot(effect_long, ggplot2::aes(natural_scale_value, response, colour = response_type)) +
    ggplot2::geom_line(linewidth = 0.6) + ggplot2::facet_wrap(~predictor, scales = "free_x", ncol = 2) +
    ggplot2::labs(title = "STRUCTURED A3 model-implied response curves", subtitle = "Natural-scale predictor axes; reference profile held fixed", x = "Natural/original-scale predictor value", y = NULL, colour = NULL) + interpretation_theme
  render_figure(plot, "effect_response", "Model-implied effect-response curves", "interpretation/effects/effect_response", relative, "not_applicable", character(), "Existing response-type categorical palette", c(NA_real_, NA_real_), "Existing statistical values; white PNG/PDF export only", 12, 12)

  relative <- "interpretation/seasonality/seasonal_effect.csv"
  seasonal <- fread(source_paths[[relative]])
  season_columns <- c("epidemiological_week", "occurrence_linear_predictor_contribution", "count_linear_predictor_contribution")
  if (!all(season_columns %in% names(seasonal))) stop("Seasonal interpretation table schema failed")
  season_long <- rbindlist(list(
    seasonal[, .(epidemiological_week, contribution = occurrence_linear_predictor_contribution, component = "occurrence")],
    seasonal[, .(epidemiological_week, contribution = count_linear_predictor_contribution, component = "positive count")]
  ))
  plot <- ggplot2::ggplot(season_long, ggplot2::aes(epidemiological_week, contribution, colour = component)) +
    ggplot2::geom_line(linewidth = 0.8) +
    ggplot2::labs(title = "Combined seasonal effect", subtitle = "Week-sine and week-cosine combined on the linear-predictor scale", x = "Epidemiological week", y = "Contribution", colour = NULL) + interpretation_theme
  render_figure(plot, "seasonal_effect", "Combined seasonal effect", "interpretation/seasonality/seasonal_effect", relative, "not_applicable", character(), "Existing seasonal categorical palette", c(NA_real_, NA_real_), "Existing statistical values; white PNG/PDF export only", 10, 5)
}

write_pilot <- function() {
  render_figure(
    prediction_plot("2026-W44", "p_occurrence", "primary", "full_domain"),
    "pilot_p_occurrence_W44_full_domain", "Pilot weekly occurrence map", "pilot/p_occurrence_W44_full_domain",
    input_sources_for_weeks("2026-W44", "p_occurrence"), "full_domain", "2026-W44",
    "Sequential blue-grey; zero is #F4F4F4", c(0, 1), "linear; fixed 0-1", 10, 8, "png"
  )
  render_figure(
    prediction_plot("2026-W44", "expected_count", "linear", "full_domain"),
    "pilot_expected_count_W44_full_domain", "Pilot weekly expected-count map", "pilot/expected_count_W44_full_domain",
    input_sources_for_weeks("2026-W44", "expected_count"), "full_domain", "2026-W44",
    "Sequential blue-grey; zero is #F4F4F4", c(0, expected_limit), "linear; fixed full-period maximum", 10, 8, "png"
  )
  render_figure(
    observation_location_plot("2026-W44", "mexico_texas_detail"),
    "pilot_observation_locations_W44_mexico_texas", "Pilot separate occupied-cell location map", "pilot/observation_locations_W44_mexico_texas",
    "predictions/observed_detections.csv", "mexico_texas_detail", "2026-W44",
    "Categorical red occupied-cell markers on white background", c(0, 0), "one point per occupied model cell", 9, 8, "png",
    observation_layer = "occupied model-cell centroids only"
  )
  render_figure(
    prediction_plot(focus_weeks, "p_occurrence", "primary", "full_domain"),
    "pilot_p_occurrence_six_week_full_domain", "Pilot six-week occurrence comparison", "pilot/p_occurrence_six_week_full_domain",
    input_sources_for_weeks(focus_weeks, "p_occurrence"), "full_domain", focus_weeks,
    "Sequential blue-grey; zero is #F4F4F4", c(0, 1), "linear; fixed 0-1", 14, 9, "png"
  )
  render_figure(
    prediction_plot("2026-W44", "expected_count", "log1p", "mexico_texas_detail"),
    "pilot_expected_count_log1p_W44_mexico_texas", "Pilot detailed supplementary expected-count map", "pilot/expected_count_log1p_W44_mexico_texas",
    input_sources_for_weeks("2026-W44", "expected_count"), "mexico_texas_detail", "2026-W44",
    "Sequential blue-grey; zero is #F4F4F4", c(0, expected_limit), "scaled log1p; original-unit legend ticks", 9, 8, "png"
  )
}

if (mode == "pilot") {
  dir.create(output_root, recursive = TRUE, showWarnings = FALSE)
  write_pilot()
  cat(toJSON(list(
    status = "pilot_render_complete",
    output_root = output_root,
    pilot_png_count = length(manifest_rows),
    expected_count_limit = expected_limit,
    expected_count_log1p_reference = expected_reference,
    occurrence_focus_limit = occurrence_focus_limit,
    source_artifact_manifest_sha256 = artifact_manifest_sha
  ), auto_unbox = TRUE, pretty = TRUE), "\n")
  quit(save = "no", status = 0L)
}

dir.create(output_root, recursive = TRUE, showWarnings = FALSE)
for (variable in c("p_occurrence", "expected_count")) {
  styles <- if (variable == "p_occurrence") c("primary", "focus") else c("linear", "log1p")
  for (style in styles) {
    for (week in focus_weeks) {
      for (view in c("full_domain", "mexico_texas_detail")) {
        write_prediction_product(week, variable, style, view)
      }
    }
    for (view in c("full_domain", "mexico_texas_detail")) {
      write_prediction_product(focus_weeks, variable, style, view)
    }
    if (variable == "p_occurrence" || style %in% c("linear", "log1p")) {
      write_prediction_product(snapshot_weeks, variable, style, "full_domain", prefix = "snapshots")
    }
  }
}

for (week in focus_weeks) {
  for (view in c("full_domain", "mexico_texas_detail")) {
    write_observation_product(week, view, aggregated = FALSE)
    write_observation_product(week, view, aggregated = TRUE)
  }
}
render_interpretation_figures()

if (!length(manifest_rows)) stop("No cartographic figures were generated")
figure_manifest <- rbindlist(manifest_rows, use.names = TRUE, fill = TRUE)
if (any(figure_manifest$observation_layer == "occupied model-cell centroids only" & grepl("prediction", figure_manifest$figure_id))) {
  stop("An observation layer was assigned to a prediction-only figure")
}
if (any(figure_manifest$limit_min[grepl("p_occurrence_primary", figure_manifest$figure_id)] != 0) ||
    any(figure_manifest$limit_max[grepl("p_occurrence_primary", figure_manifest$figure_id)] != 1)) {
  stop("Primary occurrence maps do not share the fixed 0-1 scale")
}

validate_figure_file <- function(row) {
  path <- row$output_path
  if (!file.exists(path) || file.info(path)$size <= 1000) stop("Figure output is missing or unexpectedly small: ", path)
  first <- readBin(path, what = "raw", n = 8L)
  if (row$output_format == "png") {
    signature <- as.raw(c(137, 80, 78, 71, 13, 10, 26, 10))
    if (!identical(first, signature)) stop("PNG signature check failed: ", path)
  } else {
    if (rawToChar(first[1:4]) != "%PDF") stop("PDF signature check failed: ", path)
    connection <- file(path, open = "rb")
    seek(connection, where = max(0, file.info(path)$size - 128), origin = "start")
    tail_bytes <- readBin(connection, what = "raw", n = 128L)
    tail_text <- rawToChar(tail_bytes[tail_bytes %in% as.raw(c(9, 10, 13, 32:126))])
    close(connection)
    if (!grepl("%%EOF", tail_text, fixed = TRUE)) stop("PDF end marker check failed: ", path)
  }
  if (!identical(sha256_file(path), row$output_sha256)) stop("Output checksum changed after manifest recording: ", path)
  TRUE
}
if (!all(vapply(seq_len(nrow(figure_manifest)), function(i) validate_figure_file(figure_manifest[i]), logical(1L)))) {
  stop("At least one figure file failed its signature/checksum validation")
}

png_paths <- figure_manifest[output_format == "png", output_path]
if (!requireNamespace("png", quietly = TRUE)) stop("The png R package is required for opaque-background validation")
for (path in png_paths) {
  image <- png::readPNG(path)
  dimensions <- dim(image)
  if (length(dimensions) == 3L && dimensions[[3L]] == 4L && any(image[, , 4L] < 1 - 1e-7)) {
    stop("PNG contains transparent pixels: ", path)
  }
  channels <- if (length(dimensions) == 2L) 1L else dimensions[[3L]]
  corner <- if (channels == 1L) rep(image[1L, 1L], 3L) else image[1L, 1L, 1:3]
  if (max(abs(corner - 1)) > 1e-6) stop("PNG top-left corner is not opaque white: ", path)
  rm(image)
}

protected_hashes_after <- vapply(protected$path, sha256_file, character(1L))
names(protected_hashes_after) <- protected$relative_path
names(protected_hashes_before) <- protected$relative_path
if (!identical(unname(protected_hashes_after), unname(protected_hashes_before))) {
  stop("At least one pre-existing candidate output changed during cartographic rendering")
}
manifest_sources_after <- vapply(source_paths, sha256_file, character(1L))
if (any(manifest_sources_after != source_hashes_before[names(manifest_sources_after)])) {
  stop("A source artifact changed during cartographic rendering")
}
if (!identical(sha256_file(artifact_manifest_path), artifact_manifest_sha)) stop("The pre-existing candidate output manifest changed")

figure_manifest_path <- file.path(output_root, "figure_manifest.csv")
fwrite(figure_manifest, figure_manifest_path)
figure_manifest_json <- file.path(output_root, "figure_manifest.json")
summary <- list(
  status = "W44_CARTOGRAPHIC_REVISION_RENDERED",
  generated_utc = format(Sys.time(), tz = "UTC", usetz = TRUE),
  candidate_status = "CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED",
  candidate_model_sha256 = expected_model_sha,
  source_output_manifest_path = artifact_manifest_path,
  source_output_manifest_sha256 = artifact_manifest_sha,
  source_artifact_count = nrow(source_entries),
  protected_candidate_artifact_count = nrow(protected),
  protected_candidate_artifacts_unchanged = TRUE,
  output_root = output_root,
  figure_count = uniqueN(figure_manifest$figure_id),
  output_file_count = nrow(figure_manifest),
  output_formats = sort(unique(figure_manifest$output_format)),
  output_files_opaque_white = TRUE,
  output_checksums_recorded = TRUE,
  prediction_maps_have_observation_layer = FALSE,
  observation_map_representation = "Existing observed_detections.csv is already aggregated to occupied 25 km model-cell centroids; no raw observation source was reprocessed.",
  prediction_weeks = focus_weeks,
  original_snapshot_selection = snapshot_weeks,
  palette = as.list(A3_CARTOGRAPHIC_PALETTE),
  nodata_colour = A3_CARTOGRAPHIC_NODATA,
  occurrence_primary_limits = list(0, 1),
  occurrence_supplementary_995_percentile_limit = occurrence_focus_limit,
  expected_count_fixed_linear_limit = expected_limit,
  expected_count_log1p_reference_median = expected_reference,
  expected_count_log1p_ticks_are_original_units = TRUE,
  northern_mexico_texas_extent_longitude = as.list(detail_lon),
  northern_mexico_texas_extent_latitude = as.list(detail_lat),
  figure_manifest_csv_sha256 = sha256_file(figure_manifest_path)
)
jsonlite::write_json(summary, figure_manifest_json, auto_unbox = TRUE, pretty = TRUE, digits = NA)

cat(toJSON(summary, auto_unbox = TRUE, pretty = TRUE, digits = NA), "\n")
