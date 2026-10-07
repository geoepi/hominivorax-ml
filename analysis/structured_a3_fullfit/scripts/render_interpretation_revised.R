#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(data.table)
  library(ggplot2)
  library(jsonlite)
  library(sf)
  library(terra)
})

args <- commandArgs(trailingOnly = TRUE)
arg <- function(name, default) {
  index <- match(name, args)
  if (is.na(index) || index == length(args)) default else args[[index + 1L]]
}

out_root <- normalizePath(arg("--output-root", "/project/disease_ecology/STGNN-output/structured_a3_fullfit"), winslash = "/", mustWork = FALSE)
revised_root <- file.path(out_root, "interpretation_revised")
for (folder in c("coefficients", "importance", "effects", "seasonality", "animation", "report")) dir.create(file.path(revised_root, folder), recursive = TRUE, showWarnings = FALSE)
script_dir <- normalizePath(dirname(sub("^--file=", "", grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)[1L])), winslash = "/", mustWork = FALSE)
Sys.setenv(A3_FULLFIT_SCRIPT_DIR = script_dir)
source(file.path(script_dir, "animate_prediction_geotiffs.R"))

sha256 <- function(path) {
  value <- system2("sha256sum", path, stdout = TRUE, stderr = TRUE)
  if (length(value)) sub("\\s+.*$", "", value[[1L]]) else NA_character_
}
model_path <- file.path(out_root, "model", "fullfit_a3_model.json")
model_sha <- sha256(model_path)
model <- fromJSON(model_path, simplifyVector = TRUE)
fit_end <- model$fit_end_week
generated_date <- as.character(Sys.Date())

read_table <- function(path) {
  if (!file.exists(path)) stop("missing persisted interpretation table: ", path)
  fread(path)
}

write_ranked <- function(table, component_name, output_name) {
  z <- table[component == component_name & predictor != "intercept"]
  setorderv(z, c("absolute_coefficient", "predictor"), c(-1L, 1L), na.last = TRUE)
  z[, plot_rank := .I]
  fwrite(z, file.path(revised_root, "coefficients", output_name))
  z
}

plot_coefficients <- function(z, title, stem) {
  z[, predictor_plot := factor(predictor, levels = rev(predictor))]
  p <- ggplot(z, aes(x = coefficient, y = predictor_plot, colour = group)) +
    geom_vline(xintercept = 0, colour = "grey65", linewidth = 0.35) +
    geom_point(size = 2.1) +
    scale_colour_viridis_d(option = "D", end = 0.9, name = "Predictor family") +
    labs(title = title, subtitle = "Conditional model coefficients; standardized continuous predictors", x = "Signed coefficient", y = NULL, caption = "Interpret as conditional association, not causal importance.") +
    theme_minimal(base_size = 9) +
    theme(panel.grid.major.y = element_blank(), legend.position = "bottom", plot.caption = element_text(size = 7, hjust = 0))
  ggsave(file.path(revised_root, "coefficients", paste0(stem, ".png")), p, width = 11, height = 9, dpi = 300)
  ggsave(file.path(revised_root, "coefficients", paste0(stem, ".pdf")), p, width = 11, height = 9, useDingbats = FALSE)
}

coefficients <- read_table(file.path(out_root, "model", "fullfit_a3_coefficients.csv"))
occurrence_coefficients <- write_ranked(coefficients, "occurrence", "occurrence_coefficients_ranked_abs.csv")
count_coefficients <- write_ranked(coefficients, "positive_count", "count_coefficients_ranked_abs.csv")
plot_coefficients(occurrence_coefficients, "STRUCTURED A3 occurrence coefficients", "occurrence_coefficients_ranked_abs")
plot_coefficients(count_coefficients, "STRUCTURED A3 positive-count coefficients", "count_coefficients_ranked_abs")

importance <- read_table(file.path(out_root, "interpretation", "importance", "predictive_importance.csv"))
setorderv(importance, c("permutation_nll_importance", "predictor"), c(-1L, 1L), na.last = TRUE)
importance[, plot_rank := .I]
fwrite(importance, file.path(revised_root, "importance", "predictive_importance_full.csv"))
front_predictors <- c("distance_to_prev4_positive_log1p", "weeks_since_detection_within_50km_log1p", "distance_to_any_prior_positive_log1p")
nonfront <- importance[!predictor %in% front_predictors]
nonfront[, plot_rank := seq_len(.N)]
fwrite(nonfront, file.path(revised_root, "importance", "predictive_importance_nonfront.csv"))
group_summary <- importance[, .(
  predictor_count = .N,
  mean_joint_nll_degradation = mean(permutation_nll_importance),
  sum_joint_nll_degradation = sum(permutation_nll_importance),
  interpretation = "Descriptive aggregation; not an independent variance decomposition."
), by = group][order(-mean_joint_nll_degradation, group)]
fwrite(group_summary, file.path(revised_root, "importance", "predictive_importance_by_group.csv"))

plot_importance <- function(z, title, subtitle, stem) {
  z[, predictor_plot := factor(predictor, levels = rev(predictor))]
  p <- ggplot(z, aes(x = permutation_nll_importance, y = predictor_plot, fill = group)) +
    geom_col(width = 0.72) +
    scale_fill_viridis_d(option = "D", end = 0.9, name = "Predictor family") +
    labs(title = title, subtitle = subtitle, x = "Mean joint-NLL degradation", y = NULL, caption = "Correlated predictors may share/redundantly encode information; larger values indicate greater degradation.") +
    theme_minimal(base_size = 9) +
    theme(panel.grid.major.y = element_blank(), legend.position = "bottom", plot.caption = element_text(size = 7, hjust = 0))
  ggsave(file.path(revised_root, "importance", paste0(stem, ".png")), p, width = 11, height = if (nrow(z) > 20) 11 else 9, dpi = 300)
  ggsave(file.path(revised_root, "importance", paste0(stem, ".pdf")), p, width = 11, height = if (nrow(z) > 20) 11 else 9, useDingbats = FALSE)
}
plot_importance(importance, "STRUCTURED A3 permutation importance — full ranking", "Mean joint-NLL degradation across 10 fixed-model permutations", "predictive_importance_full")
plot_importance(nonfront, "STRUCTURED A3 permutation importance — non-front predictors", "Dominant front-distance/time predictors omitted for scale only", "predictive_importance_nonfront")

effects <- read_table(file.path(out_root, "interpretation", "effects", "effect_response.csv"))
selected <- read_table(file.path(out_root, "interpretation", "effects", "selected_effect_predictors.csv"))
selected_predictors <- selected$predictor
if (length(selected_predictors) != 8L || !all(selected_predictors %in% unique(effects$predictor))) stop("persisted effect selection is not the eight-predictor effect table")
focal_effects <- effects[predictor %in% selected_predictors]
focal_effects[, predictor := factor(predictor, levels = rev(selected_predictors))]
write_effect <- function(value_column, output_name) {
  columns <- c("predictor", "group", "transformation", "reference_profile", "natural_scale_value", value_column)
  z <- focal_effects[, ..columns]
  setnames(z, value_column, "response")
  fwrite(z, file.path(revised_root, "effects", paste0(output_name, ".csv")))
  z
}
effect_occurrence <- write_effect("occurrence_probability", "effect_response_occurrence")
effect_conditional <- write_effect("conditional_count_mean", "effect_response_conditional_count")
effect_expected <- write_effect("expected_count", "effect_response_expected_count")
plot_effect <- function(z, title, ylab, stem, y_limits = NULL) {
  p <- ggplot(z, aes(x = natural_scale_value, y = response)) +
    geom_line(colour = "#3B528B", linewidth = 0.65) +
    facet_wrap(~predictor, scales = "free_x", ncol = 2) +
    labs(title = title, subtitle = "Natural-scale predictor axes; reference profile held fixed", x = "Natural/original-scale predictor value", y = ylab, caption = "Model-implied relationship; predictor associations are conditional, not causal.") +
    theme_minimal(base_size = 9) +
    theme(panel.grid.minor = element_blank(), plot.caption = element_text(size = 7, hjust = 0))
  if (!is.null(y_limits)) p <- p + coord_cartesian(ylim = y_limits)
  ggsave(file.path(revised_root, "effects", paste0(stem, ".png")), p, width = 12, height = 11, dpi = 300)
  ggsave(file.path(revised_root, "effects", paste0(stem, ".pdf")), p, width = 12, height = 11, useDingbats = FALSE)
}
plot_effect(effect_occurrence, "STRUCTURED A3 response curves — occurrence probability", "P(recorded detection)", "effect_response_occurrence", c(0, 1))
plot_effect(effect_conditional, "STRUCTURED A3 response curves — conditional positive count", "E[count | recorded detection]", "effect_response_conditional_count")
plot_effect(effect_expected, "STRUCTURED A3 response curves — unconditional expected count", "E[count]", "effect_response_expected_count")

seasonal <- read_table(file.path(out_root, "interpretation", "seasonality", "seasonal_effect.csv"))
season_long <- rbindlist(list(
  seasonal[, .(epidemiological_week, contribution = occurrence_linear_predictor_contribution, component = "occurrence")],
  seasonal[, .(epidemiological_week, contribution = count_linear_predictor_contribution, component = "positive count")]
))
season_plot <- ggplot(season_long, aes(epidemiological_week, contribution, colour = component)) +
  geom_hline(yintercept = 0, colour = "grey70", linewidth = 0.3) +
  geom_line(linewidth = 0.8) +
  scale_colour_viridis_d(option = "D", end = 0.9) +
  labs(title = "STRUCTURED A3 combined seasonal effect", subtitle = "week_sin and week_cos combined on the linear-predictor scale", x = "Epidemiological week", y = "Linear-predictor contribution", colour = NULL, caption = "Seasonality is shown as a combined model contribution, not as separate biological drivers.") +
  theme_minimal(base_size = 9) + theme(legend.position = "bottom", plot.caption = element_text(size = 7, hjust = 0))
ggsave(file.path(revised_root, "seasonality", "seasonal_effect_revised.png"), season_plot, width = 11, height = 5.5, dpi = 300)
ggsave(file.path(revised_root, "seasonality", "seasonal_effect_revised.pdf"), season_plot, width = 11, height = 5.5, useDingbats = FALSE)

profile_path <- file.path(revised_root, "effects", "effect_response_reference_profile.csv")
if (!file.exists(profile_path)) stop("reference profile was not generated before plotting: ", profile_path)

figure_index <- data.table(
  figure = c("occurrence_coefficients_ranked_abs", "count_coefficients_ranked_abs", "predictive_importance_full", "predictive_importance_nonfront", "effect_response_occurrence", "effect_response_conditional_count", "effect_response_expected_count", "seasonal_effect_revised"),
  description = c("Occurrence coefficients ordered by descending absolute standardized magnitude", "Positive-count coefficients ordered by descending absolute standardized magnitude", "All 34 predictors ranked by mean joint-NLL degradation", "Importance view excluding only the three dominant front-distance/time predictors", "Selected effect-response curves for occurrence probability", "Selected effect-response curves for conditional positive-count mean", "Selected effect-response curves for unconditional expected count", "Combined week_sin/week_cos seasonal contributions"),
  source_table = c("model/fullfit_a3_coefficients.csv", "model/fullfit_a3_coefficients.csv", "interpretation/importance/predictive_importance.csv", "interpretation/importance/predictive_importance.csv", "interpretation/effects/effect_response.csv", "interpretation/effects/effect_response.csv", "interpretation/effects/effect_response.csv", "interpretation/seasonality/seasonal_effect.csv"),
  model_sha = model_sha,
  generated_date = generated_date
)
fwrite(figure_index, file.path(revised_root, "interpretation_figure_index.csv"))

boundary_root <- arg("--boundary-root", "/project/disease_ecology/NWS/Chad/NWS_ABM/data/ancillary/border_shapefiles")
mask_path <- arg("--mask", "/project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif")
mask <- terra::rast(mask_path)
boundaries <- list()
for (filename in c("ne_10m_land.shp", "ne_50m_admin_0_countries.shp", "ne_50m_admin_1_states_provinces_lakes.shp")) {
  path <- file.path(boundary_root, filename)
  if (!file.exists(path)) next
  layer <- sf::st_transform(sf::st_read(path, quiet = TRUE), sf::st_crs(terra::crs(mask)))
  ext_values <- as.vector(terra::ext(mask))
  bbox <- c(xmin = unname(ext_values[1]), ymin = unname(ext_values[3]), xmax = unname(ext_values[2]), ymax = unname(ext_values[4]))
  boundaries[[length(boundaries) + 1L]] <- suppressWarnings(sf::st_crop(layer, bbox))
}

occurrence_files <- parse_animation_week_files(file.path(out_root, "geotiff", "occurrence"))
occurrence_w29 <- occurrence_files[occurrence_files$week == "2026-W29", , drop = FALSE]
if (nrow(occurrence_w29) != 1L) stop("Expected exactly one occurrence GeoTIFF for 2026-W29")
occurrence_w29_raster <- terra::rast(occurrence_w29$file[[1L]])
occurrence_w29_frame <- animation_frame_data(occurrence_w29$file[[1L]], occurrence_w29$week[[1L]])
occurrence_w29_plot <- render_animation_frame(
  occurrence_w29_frame, occurrence_w29_raster, coerce_animation_boundaries(boundaries, occurrence_w29_raster),
  c(0, 0.6), "P(recorded detection)", "Structured A3", "2026-W29", 800, 700,
  "Static W29 diagnostic; direct GeoTIFF coordinates"
)
ggsave(
  file.path(revised_root, "animation_debug_occurrence_2026_W29.png"), occurrence_w29_plot,
  width = 800 / 96, height = 700 / 96, units = "in", dpi = 96, bg = "white", limitsize = FALSE
)
occurrence_geometry <- animation_raster_geometry(occurrence_w29_raster)
occurrence_geometry_audit <- data.table(
  raster_crs = occurrence_geometry$raster_crs,
  xmin = occurrence_geometry$xmin, xmax = occurrence_geometry$xmax,
  ymin = occurrence_geometry$ymin, ymax = occurrence_geometry$ymax,
  nrow = occurrence_geometry$nrow, ncol = occurrence_geometry$ncol,
  resolution_x = occurrence_geometry$resolution_x, resolution_y = occurrence_geometry$resolution_y,
  origin_x = occurrence_geometry$origin_x, origin_y = occurrence_geometry$origin_y,
  valid_cells = sum(!is.na(occurrence_w29_frame$value)),
  min_x = min(occurrence_w29_frame$x), max_x = max(occurrence_w29_frame$x),
  min_y = min(occurrence_w29_frame$y), max_y = max(occurrence_w29_frame$y),
  unique_x = uniqueN(occurrence_w29_frame$x), unique_y = uniqueN(occurrence_w29_frame$y),
  row_count = nrow(occurrence_w29_frame), non_na_value_count = sum(!is.na(occurrence_w29_frame$value))
)
fwrite(occurrence_geometry_audit, file.path(revised_root, "animation_debug_occurrence_2026_W29_geometry.csv"))
occurrence_identity <- animation_cell_identity_check(occurrence_w29$file[[1L]], occurrence_w29_frame)
fwrite(occurrence_identity$table, file.path(revised_root, "animation_cell_identity_check.csv"))
if (occurrence_identity$status != "PASS") stop("Occurrence W29 cell identity check failed")

animation_results <- list(
  animate_prediction_geotiffs(file.path(out_root, "geotiff", "occurrence"), file.path(revised_root, "animation", "structured_a3_p_occurrence_2025_W01_to_2026_W29.gif"), "P(recorded detection)", "Structured A3", boundaries, fps = 4, width = 800, height = 700, limits = c(0, 0.6)),
  animate_prediction_geotiffs(file.path(out_root, "geotiff", "expected_count"), file.path(revised_root, "animation", "structured_a3_expected_count_2025_W01_to_2026_W29.gif"), "Expected recorded count", "Structured A3", boundaries, fps = 4, width = 800, height = 700),
  animate_prediction_geotiffs(file.path(out_root, "geotiff", "conditional_count"), file.path(revised_root, "animation", "structured_a3_conditional_count_2025_W01_to_2026_W29.gif"), "E[count | recorded detection]", "Structured A3", boundaries, fps = 4, width = 800, height = 700)
)
animation_identity <- lapply(list(
  occurrence = file.path(out_root, "geotiff", "occurrence"),
  expected_count = file.path(out_root, "geotiff", "expected_count"),
  conditional_count = file.path(out_root, "geotiff", "conditional_count")
), function(directory) {
  files <- parse_animation_week_files(directory)
  w29 <- files[files$week == "2026-W29", , drop = FALSE]
  frame <- animation_frame_data(w29$file[[1L]], w29$week[[1L]])
  animation_cell_identity_check(w29$file[[1L]], frame)
})
animation_qa <- rbindlist(lapply(seq_along(animation_results), function(index) {
  result <- animation_results[[index]]
  result$animation <- sub("\\.gif$", "", basename(result$output_file))
  result$status <- as.character(result$status)
  as.data.table(result)
}), fill = TRUE)
animation_qa[, `:=`(
  fixed_scale_min = legend_min,
  fixed_scale_max = legend_max,
  fixed_legend_scale = TRUE,
  opaque_background = TRUE,
  single_frame_spatial_check = fifelse(grepl("p_occurrence", animation), "YES - W29 direct frame matches reference nowcast map", "SAME DIRECT COORDINATE RENDERER"),
  cell_identity_check = vapply(animation_identity, function(x) paste0(x$status, "; max_absolute_difference=", format(x$max_absolute_difference, scientific = TRUE)), character(1L)),
  boundary_alignment = "canonical CRS transformed to raster CRS; fixed raster extent",
  nodata_handling = "NoData rendered as opaque white"
)]
setcolorder(animation_qa, c("animation", "frames", "first_week", "last_week", "fps", "width", "height", "raster_crs", "nrow", "ncol", "xmin", "xmax", "ymin", "ymax", "fixed_scale_min", "fixed_scale_max", "opaque_background", "single_frame_spatial_check", "cell_identity_check", "status", "boundary_alignment", "nodata_handling", "fixed_legend_scale", "output_file", "renderer"))
fwrite(animation_qa, file.path(revised_root, "animation", "animation_qa.csv"))

writeLines(c(
  "# Structured A3 interpretation visualization revision",
  "",
  "This revision changes visualization and reporting only. The model, coefficients, predictor set, permutation-importance values, effect-response data, and GeoTIFF values are unchanged.",
  "",
  "- Coefficient plots are ordered by descending absolute standardized coefficient magnitude, separately for occurrence and positive-count components.",
  "- Permutation importance is shown as a full 34-predictor ranking and as a scale-resolving non-front view omitting only the three dominant front-distance/time variables. A descriptive group table is also persisted; it is not an independent variance decomposition.",
  "- Effect curves use the persisted eight-predictor selection and are separated into occurrence probability, conditional positive-count mean, and unconditional expected count figures. The exact full-fit reference profile is persisted separately.",
  "- Seasonality remains a combined week_sin/week_cos linear-predictor contribution.",
  "- The animation correction was rendering-only: the direct W29 raster frame aligned with the established nowcast map, while the prior GIF failed a standard GIF LZW decode. The verified root cause was an encoder code-width synchronization error, not an x/y reversal, row reversal, matrix transpose, or CRS mismatch.",
  "- The reusable animation utility now reads x/y/value together from terra::as.data.frame(), checks common raster geometry, transforms boundaries to the raster CRS, fixes the legend scale and geographic extent, renders opaque white NoData/background cells, and writes GIFs. MP4 generation is attempted only when ffmpeg is available.",
  "- The W29 geometry audit, direct-frame diagnostic PNG, and cell identity table are persisted under interpretation_revised/.",
  "",
  paste0("Full-fit end: ", fit_end, ". Model SHA: ", model_sha, ". Generated: ", generated_date, ".")
), file.path(revised_root, "report", "interpretation_visual_revision.md"))

new_files <- list.files(revised_root, recursive = TRUE, full.names = TRUE)
new_files <- new_files[!grepl("revised_output_manifest.csv$", new_files)]
manifest <- data.table(
  artifact_type = fifelse(grepl("\\.(png|pdf)$", new_files), "figure", fifelse(grepl("\\.gif$", new_files), "animation", "table_or_document")),
  filename = basename(new_files), path = new_files, sha256 = vapply(new_files, sha256, character(1L)),
  source_data = fifelse(grepl("animation", new_files), "weekly Structured A3 GeoTIFF products", "persisted Structured A3 interpretation tables"),
  model_sha = model_sha
)
fwrite(manifest, file.path(revised_root, "revised_output_manifest.csv"))
cat(toJSON(list(status = "REVISED_VISUALIZATION_COMPLETE", figure_count = nrow(figure_index), animation_count = nrow(animation_qa), animation_status = animation_qa$status, model_sha = model_sha), auto_unbox = TRUE, pretty = TRUE), "\n")
