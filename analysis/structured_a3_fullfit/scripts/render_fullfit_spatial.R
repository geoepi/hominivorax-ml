#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(data.table)
  library(ggplot2)
  library(jsonlite)
  library(sf)
  library(terra)
  library(arrow)
})

args <- commandArgs(trailingOnly = TRUE)
arg <- function(name, default) { i <- match(name, args); if (is.na(i) || i == length(args)) default else args[[i + 1L]] }
out <- normalizePath(arg("--output-root", "/project/disease_ecology/STGNN-output/structured_a3_fullfit"), winslash = "/", mustWork = FALSE)
mask_path <- arg("--mask", "/project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif")
boundary_root <- arg("--boundary-root", "/project/disease_ecology/NWS/Chad/NWS_ABM/data/ancillary/border_shapefiles")
for (folder in c("geotiff/occurrence", "geotiff/conditional_count", "geotiff/expected_count", "raster_summaries", "nowcast_pdf", "manifests", "interpretation/coefficients", "interpretation/importance", "interpretation/effects", "interpretation/seasonality", "tables")) dir.create(file.path(out, folder), recursive = TRUE, showWarnings = FALSE)
pred_path <- file.path(out, "predictions", "weekly_predictions.parquet")
horizon_path <- file.path(out, "manifests", "fullfit_data_horizon.json")
if (any(!file.exists(c(pred_path, horizon_path, mask_path)))) stop("missing full-fit spatial input")

sha <- function(path) { x <- system2("sha256sum", path, stdout = TRUE, stderr = TRUE); if (length(x)) sub("\\s+.*$", "", x[[1L]]) else NA_character_ }
git_sha <- tryCatch(system2("git", c("rev-parse", "HEAD"), stdout = TRUE, stderr = FALSE)[[1L]], error = function(e) "unknown")
horizon <- read_json(horizon_path, simplifyVector = TRUE)
pred <- as.data.table(arrow::read_parquet(pred_path)); pred[, week := as.character(week)]; setorder(pred, week, model_node_id)
weeks <- sort(unique(pred$week))
obs_path <- file.path(out, "predictions", "observed_detections.csv")
obs <- if (file.exists(obs_path)) fread(obs_path) else data.table()
if (nrow(obs)) obs[, week := as.character(week)]
node_cols <- c("model_node_id", "canonical_node_id", "raster_cell", "row", "column", "x", "y", "lon", "lat", "country_or_domain_region")
req <- c("week", node_cols, "p_occurrence", "conditional_count_mean", "expected_count", "observed_count")
if (!all(req %in% names(pred)) || nrow(pred) != length(weeks) * 10037L) stop("prediction archive contract failed")
if (pred[, .N, by = .(week, model_node_id)][, any(N != 1L)]) stop("duplicate prediction week/node rows")

mask <- rast(mask_path); mask_values <- values(mask, mat = FALSE); nodes <- unique(pred[, ..node_cols]); setorder(nodes, model_node_id)
if (nrow(nodes) != 10037L || anyDuplicated(nodes$raster_cell)) stop("node map count/uniqueness failed")
if (anyNA(mask_values[as.integer(nodes$raster_cell)])) stop("modeled cell outside canonical mask")
if (!all(rowFromCell(mask, nodes$raster_cell) == nodes$row) || !all(colFromCell(mask, nodes$raster_cell) == nodes$column)) stop("node-to-cell row/column mapping failed")
if (is.na(crs(mask)) || !nzchar(crs(mask))) stop("canonical mask CRS missing")
if (any(!is.finite(pred$p_occurrence)) || any(pred$p_occurrence < 0 | pred$p_occurrence > 1)) stop("probability range failed")
if (any(!is.finite(pred$conditional_count_mean)) || any(pred$conditional_count_mean < 0) || any(!is.finite(pred$expected_count)) || any(pred$expected_count < 0)) stop("count range failed")

nodata <- -9999
write_raster <- function(values_to_write, path, variable) {
  r <- mask; v <- rep(NA_real_, ncell(mask)); v[as.integer(nodes$raster_cell)] <- values_to_write; values(r) <- v; names(r) <- variable
  tmp <- paste0(path, ".tmp-", Sys.getpid(), ".tif")
  terra::writeRaster(r, tmp, overwrite = TRUE, datatype = "FLT4S", NAflag = nodata, gdal = c("COMPRESS=DEFLATE", "PREDICTOR=2", "TILED=YES"), wopt = list(names = variable))
  if (file.exists(path)) unlink(path); if (!file.rename(tmp, path)) stop("atomic raster rename failed")
}
write_full_raster <- function(r, path, variable) {
  names(r) <- variable
  tmp <- paste0(path, ".tmp-", Sys.getpid(), ".tif")
  terra::writeRaster(r, tmp, overwrite = TRUE, datatype = "FLT4S", NAflag = nodata, gdal = c("COMPRESS=DEFLATE", "PREDICTOR=2", "TILED=YES"), wopt = list(names = variable))
  if (file.exists(path)) unlink(path); if (!file.rename(tmp, path)) stop("atomic summary raster rename failed")
}
qa_raster <- function(path, week, variable) {
  r <- rast(path); vals <- values(r, mat = FALSE); keep <- !is.na(vals); if (!any(keep)) stop("raster has no valid cells")
  mn <- min(vals[keep]); mx <- max(vals[keep]); if (grepl("p_occurrence|weeks_p_ge", variable) && (mn < 0 || (grepl("p_occurrence", variable) && mx > 1))) stop("probability QA failed"); if (!grepl("p_occurrence|weeks_p_ge", variable) && mn < 0) stop("count QA failed")
  data.table(week = week, variable = variable, filename = basename(path), relative_path = sub(paste0("^", out, "/"), "", normalizePath(path, winslash = "/")), sha256 = sha(path), crs = crs(r), resolution = paste(res(r), collapse = " x "), extent = paste(as.vector(ext(r)), collapse = ","), origin = paste(origin(r), collapse = ","), cell_count = ncell(r), valid_cells = sum(keep), nodata_count = sum(!keep), min = mn, max = mx, mean = mean(vals[keep]), model_sha = sha(file.path(out, "model", "fullfit_a3_model.json")), fit_end_week = horizon$full_fit_end_week, prediction_week = week)
}

qa_rows <- list(); index_rows <- list(); raster_paths <- list()
for (wk in weeks) {
  rows <- pred[week == wk]; if (nrow(rows) != 10037L) stop("incomplete prediction week: ", wk)
  paths <- list(p_occurrence = file.path(out, "geotiff/occurrence", paste0("a3_p_occurrence_", gsub("-", "_", wk), ".tif")), conditional_count_mean = file.path(out, "geotiff/conditional_count", paste0("a3_conditional_count_", gsub("-", "_", wk), ".tif")), expected_count = file.path(out, "geotiff/expected_count", paste0("a3_expected_count_", gsub("-", "_", wk), ".tif")))
  values_by_name <- list(p_occurrence = rows$p_occurrence, conditional_count_mean = rows$conditional_count_mean, expected_count = rows$expected_count)
  for (variable in names(paths)) { if (!file.exists(paths[[variable]])) write_raster(values_by_name[[variable]], paths[[variable]], variable); q <- qa_raster(paths[[variable]], wk, variable); qa_rows[[length(qa_rows) + 1L]] <- q; index_rows[[length(index_rows) + 1L]] <- q[, .(week, variable, filename, relative_path, sha256, crs, resolution, valid_cells, min, max, mean, model_sha, fit_end_week)] }
  raster_paths[[wk]] <- paths
}

summary_specs <- list(mean_p_occurrence = list(source = "p_occurrence", fun = mean), max_p_occurrence = list(source = "p_occurrence", fun = max), mean_expected_count = list(source = "expected_count", fun = mean), max_expected_count = list(source = "expected_count", fun = max), weeks_p_ge_025 = list(source = "p_occurrence", fun = function(x, na.rm = TRUE) sum(x >= 0.25, na.rm = na.rm)), weeks_p_ge_050 = list(source = "p_occurrence", fun = function(x, na.rm = TRUE) sum(x >= 0.50, na.rm = na.rm)))
summary_paths <- list()
for (name in names(summary_specs)) {
  spec <- summary_specs[[name]]; stack <- rast(vapply(weeks, function(w) raster_paths[[w]][[spec$source]], character(1L))); destination <- file.path(out, "raster_summaries", paste0("a3_", name, ".tif"))
  if (!file.exists(destination)) { r <- app(stack, spec$fun, na.rm = !grepl("weeks_", name)); rv <- values(r, mat = FALSE); rv[is.nan(rv)] <- NA; values(r) <- rv; write_full_raster(r, destination, name) }
  q <- qa_raster(destination, "study_period", name); qa_rows[[length(qa_rows) + 1L]] <- q; index_rows[[length(index_rows) + 1L]] <- q[, .(week, variable, filename, relative_path, sha256, crs, resolution, valid_cells, min, max, mean, model_sha, fit_end_week)]; summary_paths[[name]] <- destination
}
qa_table <- rbindlist(qa_rows, fill = TRUE); index_table <- rbindlist(index_rows, fill = TRUE); fwrite(qa_table, file.path(out, "manifests/geotiff_qa.csv")); fwrite(index_table, file.path(out, "manifests/geotiff_index.csv"))

spot <- pred[model_node_id %in% c(0L, 5000L, 10036L) & week %in% c(weeks[1L], tail(weeks, 1L))]
spot_rows <- lapply(seq_len(nrow(spot)), function(i) { z <- spot[i]; value <- values(rast(raster_paths[[z$week]][["p_occurrence"]]), mat = FALSE)[as.integer(z$raster_cell)]; data.table(week = z$week, model_node_id = z$model_node_id, raster_cell = z$raster_cell, source_value = z$p_occurrence, raster_value = value, absolute_difference = abs(z$p_occurrence - value), passed = abs(z$p_occurrence - value) <= 1e-5) })
spot_table <- rbindlist(spot_rows); fwrite(spot_table, file.path(out, "manifests/geotiff_spot_checks.csv")); if (!all(spot_table$passed)) stop("GeoTIFF spot checks failed")

area_values <- values(cellSize(mask, unit = "km"), mat = FALSE)[as.integer(nodes$raster_cell)]; node_area <- nodes[, .(model_node_id, geography = country_or_domain_region, cell_area_km2 = as.numeric(area_values))]
weekly_table_path <- file.path(out, "tables/weekly_prediction_summary.csv")
if (file.exists(weekly_table_path)) { w <- fread(weekly_table_path); w[, valid_cell_area_km2 := sum(node_area$cell_area_km2), by = week]; w[, area_p_ge_025_km2 := cells_p_ge_025 * valid_cell_area_km2 / valid_cells]; w[, area_p_ge_050_km2 := cells_p_ge_050 * valid_cell_area_km2 / valid_cells]; fwrite(w, weekly_table_path) }
geo_table_path <- file.path(out, "tables/weekly_geographic_summary.csv")
if (file.exists(geo_table_path)) { g <- fread(geo_table_path); if ("valid_cell_area_km2" %in% names(g)) g[, valid_cell_area_km2 := NULL]; if ("area_p_ge_025_km2" %in% names(g)) g[, area_p_ge_025_km2 := NULL]; if ("area_p_ge_050_km2" %in% names(g)) g[, area_p_ge_050_km2 := NULL]; ga <- node_area[, .(valid_cell_area_km2 = sum(cell_area_km2)), by = geography]; g <- merge(g, ga, by = "geography", all.x = TRUE); g[, area_p_ge_025_km2 := cells_p_ge_025 * valid_cell_area_km2 / valid_cells]; g[, area_p_ge_050_km2 := cells_p_ge_050 * valid_cell_area_km2 / valid_cells]; fwrite(g, geo_table_path) }

target_crs <- st_crs(crs(mask)); ext_values <- as.vector(ext(mask)); read_boundary <- function(filename) {
  path <- file.path(boundary_root, filename)
  if (!file.exists(path)) return(NULL)
  tryCatch({
    layer <- st_read(path, quiet = TRUE)
    layer <- layer[!is.na(st_geometry(layer)) & !st_is_empty(layer), ]
    layer <- st_transform(layer, target_crs)
    bbox <- st_bbox(c(xmin = ext_values[1], xmax = ext_values[2], ymin = ext_values[3], ymax = ext_values[4]), crs = target_crs)
    suppressWarnings(st_crop(layer, bbox))
  }, error = function(e) {
    message("boundary layer skipped: ", filename, " (", conditionMessage(e), ")")
    NULL
  })
}
land <- read_boundary("ne_10m_land.shp"); countries <- read_boundary("ne_50m_admin_0_countries.shp"); states <- read_boundary("ne_50m_admin_1_states_provinces_lakes.shp")
obs_sf <- NULL; if (nrow(obs)) obs_sf <- st_transform(st_as_sf(obs, coords = c("lon", "lat"), crs = 4326, remove = FALSE), target_crs)
boundary_layers <- function() { x <- list(); if (!is.null(land) && nrow(land)) x <- c(x, list(geom_sf(data = land, fill = NA, colour = "grey75", linewidth = .15, inherit.aes = FALSE))); if (!is.null(countries) && nrow(countries)) x <- c(x, list(geom_sf(data = countries, fill = NA, colour = "grey35", linewidth = .22, inherit.aes = FALSE))); if (!is.null(states) && nrow(states)) x <- c(x, list(geom_sf(data = states, fill = NA, colour = "grey62", linewidth = .12, inherit.aes = FALSE))); x }
map_theme <- theme_minimal(base_size = 9) + theme(panel.grid = element_blank(), panel.background = element_rect(fill = "white", colour = NA), axis.title = element_blank(), axis.text = element_blank(), axis.ticks = element_blank(), legend.title = element_text(size = 8), legend.text = element_text(size = 7), plot.caption = element_text(size = 5, hjust = 0))
coord_map <- coord_sf(crs = target_crs, xlim = ext_values[1:2], ylim = ext_values[3:4], expand = FALSE, datum = NA)
footer <- function(w) paste0("Structured A3 | repository SHA ", git_sha, " | full-fit end ", horizon$full_fit_end_week, " | prediction ", w, " | generated ", Sys.Date(), " | Descriptive full-fit output; not an independent validation product.")
map_frame <- function(w, variable) { r <- rast(raster_paths[[w]][[variable]]); x <- as.data.table(as.data.frame(r, xy = TRUE, na.rm = TRUE)); setnames(x, 3L, "value"); x[, week := w]; x }
observed_layer <- function(w) { if (is.null(obs_sf) || !nrow(obs_sf)) return(NULL); z <- obs_sf[obs_sf$week == w, ]; if (!nrow(z)) return(NULL); geom_sf(data = z, shape = 1, colour = "#C62828", fill = NA, size = .7, stroke = .35, inherit.aes = FALSE) }
plot_map <- function(w, variable, limit, observed = TRUE) { f <- map_frame(w, variable); label <- if (variable == "p_occurrence") "P(recorded detection)" else if (variable == "expected_count") "Expected recorded count" else "E[Y | Y > 0]"; p <- ggplot(f, aes(x = x, y = y, fill = value)) + geom_raster() + boundary_layers() + scale_fill_viridis_c(option = "C", limits = c(0, limit), oob = scales::squish, name = label) + coord_map + labs(title = paste(variable, w), caption = footer(w)) + map_theme; if (observed) p <- p + observed_layer(w); p }
row_plot <- function(ws, variable, limit) { f <- rbindlist(lapply(ws, map_frame, variable = variable)); label <- if (variable == "p_occurrence") "P(recorded detection)" else "Expected recorded count"; p <- ggplot(f, aes(x = x, y = y, fill = value)) + geom_raster() + boundary_layers() + scale_fill_viridis_c(option = "C", limits = c(0, limit), oob = scales::squish, name = label) + facet_wrap(~week, nrow = 1) + coord_map + labs(title = paste("STRUCTURED A3", label), caption = footer(paste(ws, collapse = ", "))) + map_theme; for (w in ws) p <- p + observed_layer(w); p }

pmax <- max(pred$p_occurrence); emax <- max(pred$expected_count); snapshots <- unique(c(weeks[1L], weeks[max(1L, ceiling(length(weeks) / 2))], weeks[which(weeks >= "2026-W17")[1L]], weeks[max(1L, length(weeks) - 2L)], tail(weeks, 1L))); snapshots <- snapshots[!is.na(snapshots)]
pdf(file.path(out, "interpretation/spatial_snapshots.pdf"), width = 12, height = 8); grid::grid.newpage(); grid::pushViewport(grid::viewport(layout = grid::grid.layout(2, 1))); print(row_plot(snapshots, "p_occurrence", pmax), vp = grid::viewport(layout.pos.row = 1L)); print(row_plot(snapshots, "expected_count", emax), vp = grid::viewport(layout.pos.row = 2L)); grid::popViewport(); dev.off()
png(file.path(out, "interpretation/spatial_snapshots.png"), width = 3600, height = 2400, res = 300); grid::grid.newpage(); grid::pushViewport(grid::viewport(layout = grid::grid.layout(2, 1))); print(row_plot(snapshots, "p_occurrence", pmax), vp = grid::viewport(layout.pos.row = 1L)); print(row_plot(snapshots, "expected_count", emax), vp = grid::viewport(layout.pos.row = 2L)); grid::popViewport(); dev.off()

nowcast_weeks <- tail(weeks, min(6L, length(weeks)))
for (w in nowcast_weeks) { path <- file.path(out, "nowcast_pdf", paste0("structured_a3_nowcast_", gsub("-", "_", w), ".pdf")); pdf(path, width = 11, height = 8.5); grid::grid.newpage(); grid::pushViewport(grid::viewport(layout = grid::grid.layout(2, 1))); print(plot_map(w, "p_occurrence", pmax), vp = grid::viewport(layout.pos.row = 1L)); print(plot_map(w, "expected_count", emax), vp = grid::viewport(layout.pos.row = 2L)); grid::popViewport(); dev.off() }
summary_pdf <- file.path(out, "nowcast_pdf", paste0("structured_a3_nowcast_summary_through_", gsub("-", "_", tail(weeks, 1L)), ".pdf")); pdf(summary_pdf, width = 12, height = 8); grid::grid.newpage(); grid::pushViewport(grid::viewport(layout = grid::grid.layout(2, 1))); print(row_plot(nowcast_weeks, "p_occurrence", pmax), vp = grid::viewport(layout.pos.row = 1L)); print(row_plot(nowcast_weeks, "expected_count", emax), vp = grid::viewport(layout.pos.row = 2L)); grid::popViewport(); dev.off()
writeLines(c(paste0("nowcast_start_week: ", nowcast_weeks[1L]), paste0("nowcast_end_week: ", tail(nowcast_weeks, 1L)), paste0("number_of_weeks: ", length(nowcast_weeks)), "layout_source: existing Task 3E exact-cell continuous map workflow (docs/V2A_MAP_FIGURES.md and scripts/task3e_raster_outputs.R)", "classification: descriptive full-fit output; not an independent validation product."), file.path(out, "manifests/nowcast_period_provenance.txt"))

coef_plot <- function(path, title) { z <- fread(path); z[, predictor := reorder(predictor, coefficient)]; ggplot(z, aes(predictor, coefficient, colour = group)) + geom_hline(yintercept = 0, colour = "grey70") + geom_point(size = 2) + coord_flip() + labs(title = title, subtitle = "Conditional model coefficients; standardized continuous predictors", x = NULL, y = "Coefficient") + theme_minimal(base_size = 9) }
for (spec in list(list(file = "occurrence_coefficients_ranked.csv", title = "STRUCTURED A3 occurrence coefficients"), list(file = "count_coefficients_ranked.csv", title = "STRUCTURED A3 positive-count coefficients"))) { p <- coef_plot(file.path(out, "interpretation/coefficients", spec$file), spec$title); stem <- sub("\\.csv$", "", spec$file); ggsave(file.path(out, "interpretation/coefficients", paste0(stem, ".png")), p, width = 10, height = 8, dpi = 300); ggsave(file.path(out, "interpretation/coefficients", paste0(stem, ".pdf")), p, width = 10, height = 8) }
imp <- fread(file.path(out, "interpretation/importance/predictive_importance.csv")); imp[, predictor := reorder(predictor, permutation_nll_importance)]; p <- ggplot(imp, aes(predictor, permutation_nll_importance, fill = group)) + geom_col() + coord_flip() + labs(title = "STRUCTURED A3 fixed-model permutation importance", subtitle = "Larger values indicate greater joint-NLL degradation; correlated predictors may be redundant", x = NULL, y = "Joint NLL degradation") + theme_minimal(base_size = 9); ggsave(file.path(out, "interpretation/importance/predictive_importance.png"), p, width = 10, height = 8, dpi = 300); ggsave(file.path(out, "interpretation/importance/predictive_importance.pdf"), p, width = 10, height = 8)
effects <- fread(file.path(out, "interpretation/effects/effect_response.csv")); effect_long <- rbindlist(list(effects[, .(predictor, natural_scale_value, response = occurrence_probability, response_type = "occurrence probability")], effects[, .(predictor, natural_scale_value, response = conditional_count_mean, response_type = "conditional positive-count mean")], effects[, .(predictor, natural_scale_value, response = expected_count, response_type = "unconditional expected count")])); p <- ggplot(effect_long, aes(natural_scale_value, response, colour = response_type)) + geom_line(linewidth = .6) + facet_wrap(~predictor, scales = "free_x", ncol = 2) + labs(title = "STRUCTURED A3 model-implied response curves", subtitle = "Natural-scale predictor axes; reference profile held fixed", x = "Natural/original-scale predictor value", y = NULL, colour = NULL) + theme_minimal(base_size = 8); ggsave(file.path(out, "interpretation/effects/effect_response.png"), p, width = 12, height = 12, dpi = 300); ggsave(file.path(out, "interpretation/effects/effect_response.pdf"), p, width = 12, height = 12)
seasonal <- fread(file.path(out, "interpretation/seasonality/seasonal_effect.csv")); season_long <- rbindlist(list(seasonal[, .(epidemiological_week, contribution = occurrence_linear_predictor_contribution, component = "occurrence")], seasonal[, .(epidemiological_week, contribution = count_linear_predictor_contribution, component = "positive count")])); p <- ggplot(season_long, aes(epidemiological_week, contribution, colour = component)) + geom_line(linewidth = .8) + labs(title = "Combined seasonal effect", subtitle = "Week-sine and week-cosine combined on the linear-predictor scale", x = "Epidemiological week", y = "Contribution", colour = NULL) + theme_minimal(base_size = 9); ggsave(file.path(out, "interpretation/seasonality/seasonal_effect.png"), p, width = 10, height = 5, dpi = 300); ggsave(file.path(out, "interpretation/seasonality/seasonal_effect.pdf"), p, width = 10, height = 5)
weekly <- fread(file.path(out, "tables/weekly_prediction_summary.csv")); p <- ggplot(weekly, aes(week, mean_p_occurrence, group = 1)) + geom_line() + geom_point(size = .7) + theme_minimal(base_size = 9) + theme(axis.text.x = element_text(angle = 90, hjust = 1, vjust = .5)) + labs(title = "Weekly descriptive full-fit predictions", x = NULL, y = "Mean occurrence probability"); ggsave(file.path(out, "tables/weekly_prediction_summary.png"), p, width = 12, height = 5, dpi = 300); ggsave(file.path(out, "tables/weekly_prediction_summary.pdf"), p, width = 12, height = 5)

task_path <- file.path(out, "manifests/fullfit_product_task_manifest.csv")
if (file.exists(task_path)) { task <- fread(task_path); task[, status := ifelse(file.exists(file.path(out, output)), "COMPLETED", "FAILED")]; task[, checksum := vapply(output, function(x) { p <- file.path(out, x); if (file.exists(p)) sha(p) else NA_character_ }, character(1L))]; fwrite(task, task_path) }
writeLines(c(paste0("repository_sha: ", git_sha), paste0("fit_end_week: ", horizon$full_fit_end_week), paste0("node_count: ", nrow(nodes)), paste0("weekly_prediction_count: ", length(weeks)), paste0("weekly_geotiff_count: ", length(weeks) * 3L), paste0("summary_geotiff_count: ", length(summary_specs)), paste0("crs: ", crs(mask)), paste0("resolution: ", paste(res(mask), collapse = " x ")), paste0("spot_checks_passed: ", all(spot_table$passed)), paste0("nowcast_start_week: ", nowcast_weeks[1L]), paste0("nowcast_end_week: ", tail(nowcast_weeks, 1L)), "layout_source: Task 3E exact-cell continuous map workflow"), file.path(out, "manifests/spatial_render_summary.txt"))
cat(toJSON(list(status = "render_complete", weeks = length(weeks), weekly_geotiffs = length(weeks) * 3L, summary_geotiffs = length(summary_specs), nowcast_weeks = nowcast_weeks, grid_alignment = TRUE, probability_range_valid = TRUE, count_range_valid = TRUE, spot_checks_passed = all(spot_table$passed)), auto_unbox = TRUE, pretty = TRUE), "\n")
