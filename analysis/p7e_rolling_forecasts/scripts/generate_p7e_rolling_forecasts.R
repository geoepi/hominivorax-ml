#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(ggplot2)
  library(dplyr)
  library(patchwork)
  library(jsonlite)
  library(digest)
})

repo_root <- normalizePath(file.path(getwd()), winslash = "/", mustWork = TRUE)
root <- file.path(repo_root, "analysis", "p7e_rolling_forecasts")
results <- file.path(root, "results")
figures <- file.path(root, "figures")
captions <- file.path(root, "captions")
dir.create(file.path(results, "plot_data"), recursive = TRUE, showWarnings = FALSE)
dir.create(figures, recursive = TRUE, showWarnings = FALSE)
dir.create(captions, recursive = TRUE, showWarnings = FALSE)

occ <- read.csv(file.path(results, "rolling_occurrence_forecasts.csv"), stringsAsFactors = FALSE, check.names = FALSE)
cnt <- read.csv(file.path(results, "rolling_count_forecasts.csv"), stringsAsFactors = FALSE, check.names = FALSE)
hist <- read.csv(file.path(results, "observed_occurrence_history.csv"), stringsAsFactors = FALSE, check.names = FALSE)
manifest <- fromJSON(file.path(results, "atlas_rolling_forecast_manifest.json"), simplifyVector = TRUE)

week_num <- function(x) as.integer(sub(".*-W", "", x))
occ <- occ %>% mutate(issue_num = week_num(issue_week), target_num = week_num(target_week), horizon = factor(horizon, levels = c(1, 2, 3), labels = c("h=1", "h=2", "h=3")))
cnt <- cnt %>% mutate(issue_num = week_num(issue_week), target_num = week_num(target_week), horizon = factor(horizon, levels = c(1, 2, 3), labels = c("h=1", "h=2", "h=3")))
hist <- hist %>% mutate(target_num = week_num(target_week))

blue <- c("h=1" = "#08306B", "h=2" = "#2171B5", "h=3" = "#6BAED6")
selected <- c(16, 20, 24, 28, 32, 36)
week_breaks <- seq(17, 39, by = 4)
week_labels <- function(x) paste0("W", x)
theme_p7e <- theme_minimal(base_size = 10) +
  theme(panel.grid.minor = element_blank(), legend.position = "bottom", plot.title = element_text(face = "bold", size = 11), axis.title = element_text(size = 9))

write_plot <- function(plot, stem, width = 10, height = 7) {
  svg <- file.path(figures, paste0(stem, ".svg"))
  png <- file.path(figures, paste0(stem, ".png"))
  ggsave(svg, plot, device = svglite::svglite, width = width, height = height, units = "in", bg = "white")
  ggsave(png, plot, device = "png", width = width, height = height, units = "in", dpi = 220, bg = "white")
  invisible(c(svg, png))
}

occ_panel_a <- ggplot() +
  geom_vline(xintercept = selected, color = "grey85", linewidth = 0.25) +
  geom_line(data = hist, aes(target_num, observed_positive_cells, group = 1), color = "#222222", linewidth = 0.65) +
  geom_point(data = hist, aes(target_num, observed_positive_cells), color = "#222222", size = 1.25) +
  geom_line(data = occ, aes(target_num, expected_positive_cells, group = issue_week), color = "grey45", alpha = 0.27, linewidth = 0.45) +
  geom_point(data = occ, aes(target_num, expected_positive_cells, color = horizon, shape = horizon), alpha = 0.65, size = 1.8) +
  geom_line(data = filter(occ, issue_num %in% selected), aes(target_num, expected_positive_cells, group = issue_week), color = "#D95F02", linewidth = 0.7, alpha = 0.8) +
  geom_point(data = filter(occ, issue_num %in% selected), aes(target_num, expected_positive_cells, color = horizon, shape = horizon), size = 2.2, stroke = 0.35) +
  scale_color_manual(values = blue, name = "Forecast horizon") +
  scale_shape_manual(values = c("h=1" = 16, "h=2" = 17, "h=3" = 15), name = "Forecast horizon") +
  scale_x_continuous(breaks = week_breaks, labels = week_labels, limits = c(15.5, 39.5)) +
  labs(title = "A. Expected positive-cell burden", x = "Target week (2026)", y = "Cells") + theme_p7e

occ_panel_b <- ggplot(occ, aes(issue_num, forecast_error, color = horizon, shape = horizon)) +
  geom_hline(yintercept = 0, color = "grey30", linewidth = 0.4) +
  geom_line(aes(group = horizon), color = "grey75", linewidth = 0.35) +
  geom_point(size = 2) +
  scale_color_manual(values = blue, name = "Forecast horizon") +
  scale_shape_manual(values = c("h=1" = 16, "h=2" = 17, "h=3" = 15), name = "Forecast horizon") +
  scale_x_continuous(breaks = seq(16, 36, by = 4), labels = week_labels) +
  labs(title = "B. Signed forecast error", x = "Issue week (2026)", y = "Expected − observed positive cells") + theme_p7e

occ_panel_c <- ggplot(occ, aes(horizon, forecast_error, fill = horizon)) +
  geom_hline(yintercept = 0, color = "grey30", linewidth = 0.4) +
  geom_boxplot(width = 0.55, alpha = 0.55, outlier.shape = NA) +
  geom_jitter(width = 0.08, height = 0, size = 1.4, alpha = 0.7) +
  scale_fill_manual(values = blue, guide = "none") +
  labs(title = "C. Error distribution by horizon", x = NULL, y = "Expected − observed positive cells") + theme_p7e

occ_plot <- occ_panel_a / (occ_panel_b | occ_panel_c) + plot_layout(heights = c(1.35, 1)) + plot_annotation(
  title = "Rolling-origin focal-region nowcasts: expected positive cells",
  subtitle = "All 21 prespecified origins are shown; highlighted threads are W16, W20, W24, W28, W32, and W36. Target-week points are connected within issue week."
)
write_plot(occ_plot, "figure_rolling_occurrence_forecasts", 11, 8.5)

cnt_panel_a <- ggplot() +
  geom_vline(xintercept = selected, color = "grey85", linewidth = 0.25) +
  geom_line(data = hist, aes(target_num, observed_total_count, group = 1), color = "#222222", linewidth = 0.65) +
  geom_point(data = hist, aes(target_num, observed_total_count), color = "#222222", size = 1.25) +
  geom_line(data = cnt, aes(target_num, expected_total_count, group = issue_week), color = "grey45", alpha = 0.27, linewidth = 0.45) +
  geom_point(data = cnt, aes(target_num, expected_total_count, color = horizon, shape = horizon), alpha = 0.65, size = 1.8) +
  geom_line(data = filter(cnt, issue_num %in% selected), aes(target_num, expected_total_count, group = issue_week), color = "#D95F02", linewidth = 0.7, alpha = 0.8) +
  geom_point(data = filter(cnt, issue_num %in% selected), aes(target_num, expected_total_count, color = horizon, shape = horizon), size = 2.2, stroke = 0.35) +
  scale_color_manual(values = blue, name = "Forecast horizon") +
  scale_shape_manual(values = c("h=1" = 16, "h=2" = 17, "h=3" = 15), name = "Forecast horizon") +
  scale_x_continuous(breaks = week_breaks, labels = week_labels, limits = c(15.5, 39.5)) +
  labs(title = "A. Expected-count burden", x = "Target week (2026)", y = "Total count") + theme_p7e
cnt_panel_b <- ggplot(cnt, aes(issue_num, forecast_error, color = horizon, shape = horizon)) +
  geom_hline(yintercept = 0, color = "grey30", linewidth = 0.4) + geom_line(aes(group = horizon), color = "grey75", linewidth = 0.35) + geom_point(size = 2) +
  scale_color_manual(values = blue, name = "Forecast horizon") + scale_shape_manual(values = c("h=1" = 16, "h=2" = 17, "h=3" = 15), name = "Forecast horizon") +
  scale_x_continuous(breaks = seq(16, 36, by = 4), labels = week_labels) + labs(title = "B. Signed count error", x = "Issue week (2026)", y = "Expected − observed total count") + theme_p7e
cnt_panel_c <- ggplot(cnt, aes(horizon, forecast_error, fill = horizon)) + geom_hline(yintercept = 0, color = "grey30", linewidth = 0.4) + geom_boxplot(width = 0.55, alpha = 0.55, outlier.shape = NA) + geom_jitter(width = 0.08, height = 0, size = 1.4, alpha = 0.7) + scale_fill_manual(values = blue, guide = "none") + labs(title = "C. Count-error distribution", x = NULL, y = "Expected − observed total count") + theme_p7e
cnt_plot <- cnt_panel_a / (cnt_panel_b | cnt_panel_c) + plot_layout(heights = c(1.35, 1)) + plot_annotation(title = "Candidate count-burden rolling-origin display", subtitle = "Candidate visualization only; no count-model recalibration or uncertainty band is applied.")
write_plot(cnt_plot, "figure_rolling_count_forecasts_candidate", 11, 8.5)

write.csv(occ, file.path(results, "plot_data", "rolling_occurrence_plot_data.csv"), row.names = FALSE, quote = TRUE)
write.csv(cnt, file.path(results, "plot_data", "rolling_count_plot_data.csv"), row.names = FALSE, quote = TRUE)
write.csv(hist, file.path(results, "plot_data", "observed_history_plot_data.csv"), row.names = FALSE, quote = TRUE)
write.csv(bind_rows(
  occ %>% transmute(issue_week, target_week, horizon = as.character(horizon), metric = "occurrence", observed = observed_positive_cells, expected = expected_positive_cells, error = forecast_error),
  cnt %>% transmute(issue_week, target_week, horizon = as.character(horizon), metric = "count", observed = observed_total_count, expected = expected_total_count, error = forecast_error)
), file.path(results, "plot_data", "rolling_forecast_error_plot_data.csv"), row.names = FALSE, quote = TRUE)

source_registry <- data.frame(
  figure_id = c("P7E-F1", "P7E-F1", "P7E-F1", "P7E-F2", "P7E-F2", "P7E-F2"),
  panel_id = c("A", "B", "C", "A", "B", "C"),
  source_phase = rep("P2", 6),
  source_file = rep("analysis/p7e_rolling_forecasts/results/atlas_rolling_forecast_manifest.json; compact Atlas-derived CSVs", 6),
  source_fields = c("observed_positive_cells; expected_positive_cells", "forecast_error; issue_week; horizon", "forecast_error; horizon", "observed_total_count; expected_total_count", "forecast_error; issue_week; horizon", "forecast_error; horizon"),
  transformations = c("focal-cell aggregation preserved from Atlas extraction", "signed expected minus observed", "distribution display only", "focal-cell aggregation preserved from Atlas extraction", "signed expected minus observed", "distribution display only"),
  filtering = rep("origins 2026-W16:W36; horizons h=1:3", 6),
  geographic_subset = rep("EPSG:4326 bbox [-107.5,-96.0] x [24.0,33.0]; 1,689 cells", 6),
  temporal_subset = rep("forecast targets 2026-W17:W39; observed history complete for W17:W39", 6),
  plotting_script = rep("analysis/p7e_rolling_forecasts/scripts/generate_p7e_rolling_forecasts.R", 6),
  output_file = c("figures/figure_rolling_occurrence_forecasts.svg", "figures/figure_rolling_occurrence_forecasts.svg", "figures/figure_rolling_occurrence_forecasts.svg", "figures/figure_rolling_count_forecasts_candidate.svg", "figures/figure_rolling_count_forecasts_candidate.svg", "figures/figure_rolling_count_forecasts_candidate.svg"),
  stringsAsFactors = FALSE
)
source_registry$output_hash <- vapply(source_registry$output_file, function(x) digest(file.path(root, x), algo = "sha256", file = TRUE), character(1))
write.csv(source_registry, file.path(results, "figure_source_registry.csv"), row.names = FALSE, quote = TRUE)

contract <- list(
  figure = "P7E rolling-origin forecast visualization",
  source_archive_sha256 = manifest$source_archive_sha256,
  focal_bbox = manifest$focal_bbox,
  focal_cells = manifest$focal_cells,
  origins = manifest$origins,
  horizons = manifest$horizons,
  target_week_range = manifest$target_week_range,
  uncertainty_status = "NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS",
  no_uncertainty_ribbon = TRUE,
  model_fitting = FALSE,
  occurrence_formula = "expected_positive_cells = sum(p_occurrence); observed_positive_cells = sum(observed_positive > 0)",
  count_formula = "expected_total_count = sum(expected_count); observed_total_count = sum(observed_count)",
  selected_highlight_origins = selected
)
write(toJSON(contract, auto_unbox = TRUE, pretty = TRUE), file.path(results, "rendering_contract.json"))
write(toJSON(list(
  decision = "P7E_ROLLING_FORECAST_FIGURE_SUPPORTED_WITH_LIMITATIONS",
  reason = "Occurrence figure is complete and deterministic; count display is a candidate and no canonical regional uncertainty ribbon is available.",
  primary_figure = "figure_rolling_occurrence_forecasts",
  count_candidate = "figure_rolling_count_forecasts_candidate"
), auto_unbox = TRUE, pretty = TRUE), file.path(results, "decision.json"))
write(toJSON(list(generated_at_utc = format(Sys.time(), tz = "UTC", usetz = TRUE), script = "analysis/p7e_rolling_forecasts/scripts/generate_p7e_rolling_forecasts.R", source_archive_sha256 = manifest$source_archive_sha256), auto_unbox = TRUE, pretty = TRUE), file.path(results, "run_metadata.json"))

cat("P7E_FIGURES_GENERATED\n")
