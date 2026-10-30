#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(ggplot2)
  library(dplyr)
  library(patchwork)
  library(jsonlite)
  library(digest)
})

repo_root <- normalizePath(getwd(), winslash = "/", mustWork = TRUE)
root <- file.path(repo_root, "analysis", "p7f_final_figures")
main_dir <- file.path(root, "figures", "main")
supp_dir <- file.path(root, "figures", "supplement")
archive_dir <- file.path(root, "figures", "archive")
results_dir <- file.path(root, "results")
plot_data_dir <- file.path(results_dir, "plot_data")
dir.create(main_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(supp_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(archive_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(plot_data_dir, recursive = TRUE, showWarnings = FALSE)

hash_file <- function(path) digest(path, algo = "sha256", file = TRUE)
source_path <- function(relative) file.path(repo_root, relative)

copy_assets <- function(source_relative, destination_dir, destination_stem) {
  source_stem <- source_path(source_relative)
  copied <- character()
  for (ext in c("png", "svg")) {
    src <- paste0(source_stem, ".", ext)
    if (file.exists(src)) {
      dest <- file.path(destination_dir, paste0(destination_stem, ".", ext))
      if (!file.copy(src, dest, overwrite = TRUE)) stop("could not copy ", src)
      copied <- c(copied, dest)
    }
  }
  if (!length(copied)) stop("no source figure assets found for ", source_relative)
  copied
}

copy_count_candidate <- function(source_relative, destination_dir, destination_stem) {
  copied <- copy_assets(source_relative, destination_dir, destination_stem)
  svg_path <- file.path(destination_dir, paste0(destination_stem, ".svg"))
  if (file.exists(svg_path)) {
    svg_lines <- readLines(svg_path, warn = FALSE, encoding = "UTF-8")
    needs_label_fix <- grepl("Expected b", svg_lines, fixed = TRUE) &
      grepl("observed total count", svg_lines, fixed = TRUE)
    svg_lines[needs_label_fix] <- sub(
      "Expected b.* observed total count",
      "Expected - observed total count",
      svg_lines[needs_label_fix],
      perl = TRUE
    )
    writeLines(svg_lines, svg_path, useBytes = TRUE)
    if (requireNamespace("magick", quietly = TRUE)) {
      magick::image_read(svg_path) |>
        magick::image_write(path = file.path(destination_dir, paste0(destination_stem, ".png")),
                            format = "png")
    }
  }
  copied
}

copy_assets("analysis/p7d_cartography_forecast/figures/main_candidates/figure_01_domain_framework_corrected", main_dir, "figure_01_domain_framework")
copy_assets("analysis/p7c_figure_refinement/figures/main/figure_02_predictive_performance", main_dir, "figure_02_predictive_performance")
copy_assets("analysis/p7d_cartography_forecast/figures/main_candidates/figure_03_mexico_texas_occurrence_corrected", main_dir, "figure_03_mexico_texas_occurrence")
copy_assets("analysis/p7c_figure_refinement/figures/main/figure_04_issue_time_proxy_validation", main_dir, "figure_05_issue_time_proxy_validation")
copy_assets("analysis/p7c_figure_refinement/figures/main/figure_05_predictor_associations", main_dir, "figure_06_predictor_associations")

copy_assets("analysis/p7c_figure_refinement/figures/supplement/S1_reliability_curves", supp_dir, "S1_reliability_curves")
copy_assets("analysis/p7c_figure_refinement/figures/supplement/S2_frontier_sensitivity", supp_dir, "S2_frontier_sensitivity")
copy_assets("analysis/p7c_figure_refinement/figures/supplement/S3_count_diagnostics_reference", supp_dir, "S3_count_diagnostics")
copy_assets("analysis/p7c_figure_refinement/figures/supplement/S4_proxy_error_support_transitions", supp_dir, "S4_proxy_error_support_transitions")
copy_assets("analysis/p7d_cartography_forecast/figures/main_candidates/figure_06_support_extrapolation_corrected", supp_dir, "S5_support_extrapolation")
copy_count_candidate("analysis/p7e_rolling_forecasts/figures/figure_rolling_count_forecasts_candidate", supp_dir, "S6_rolling_count_nowcasts")

copy_assets("analysis/p7d_cartography_forecast/figures/main_candidates/figure_03_mexico_texas_expected_count_corrected_candidate", archive_dir, "figure_03_expected_count_archive")
copy_assets("analysis/p7d_cartography_forecast/figures/main_candidates/forecast_trajectory_issue_W36_candidate", archive_dir, "forecast_trajectory_issue_W36_archive")

# The only regenerated figure is the P7E rolling occurrence display. It uses
# the existing compact P7E plotted data and applies the P7F style contract.
occ <- read.csv(source_path("analysis/p7e_rolling_forecasts/results/rolling_occurrence_forecasts.csv"), stringsAsFactors = FALSE, check.names = FALSE)
hist <- read.csv(source_path("analysis/p7e_rolling_forecasts/results/observed_occurrence_history.csv"), stringsAsFactors = FALSE, check.names = FALSE)
week_num <- function(x) as.integer(sub(".*-W", "", x))
occ <- occ %>% mutate(issue_num = week_num(issue_week), target_num = week_num(target_week), horizon_label = factor(horizon, levels = c(1, 2, 3), labels = c("h=1", "h=2", "h=3")))
hist <- hist %>% mutate(target_num = week_num(target_week))
selected <- c(16, 20, 24, 28, 32, 36)
week_breaks <- seq(16, 36, by = 4)
week_labels <- function(x) paste0("W", x)
shape_values <- c("h=1" = 16, "h=2" = 17, "h=3" = 15)
theme_p7f <- theme_minimal(base_size = 11, base_family = "sans") +
  theme(panel.grid.minor = element_blank(), legend.position = "bottom", legend.title = element_text(size = 9), legend.text = element_text(size = 9), plot.title = element_text(face = "bold", size = 12), plot.subtitle = element_text(size = 10), axis.title = element_text(size = 10), axis.text = element_text(size = 9))

panel_a <- ggplot() +
  geom_vline(xintercept = selected, color = "grey90", linewidth = 0.25) +
  geom_line(data = hist, aes(target_num, observed_positive_cells, group = 1), color = "#222222", linewidth = 0.8) +
  geom_point(data = hist, aes(target_num, observed_positive_cells), color = "#222222", size = 1.7) +
  geom_line(data = occ, aes(target_num, expected_positive_cells, group = issue_week), color = "#C7CDD3", linewidth = 0.55, alpha = 0.8) +
  geom_point(data = occ, aes(target_num, expected_positive_cells, shape = horizon_label), color = "#AEB7C0", size = 1.9, alpha = 0.95) +
  geom_line(data = filter(occ, issue_num %in% selected), aes(target_num, expected_positive_cells, group = issue_week), color = "#D55E00", linewidth = 0.9, alpha = 0.92) +
  geom_point(data = filter(occ, issue_num %in% selected), aes(target_num, expected_positive_cells, shape = horizon_label), color = "#D55E00", size = 2.4, alpha = 0.95) +
  annotate("text", x = 39.25, y = max(hist$observed_positive_cells) * 0.78, label = "Observed positive cells", color = "#222222", hjust = 1, vjust = 0, size = 3.4) +
  annotate("text", x = 39.25, y = max(occ$expected_positive_cells) * 1.02, label = "Rolling 1-3 week nowcasts", color = "#D55E00", hjust = 1, vjust = 0, size = 3.4) +
  scale_shape_manual(values = shape_values, name = "Horizon point shape") +
  scale_x_continuous(breaks = week_breaks, labels = week_labels, limits = c(15.5, 39.8)) +
  labs(title = "A. Observed and forecast positive-cell burden", x = "Target week (2026)", y = "Cells") + theme_p7f

panel_b <- ggplot(occ, aes(issue_num, forecast_error, shape = horizon_label)) +
  geom_hline(yintercept = 0, color = "#444444", linewidth = 0.45) +
  geom_line(aes(group = horizon_label), color = "#D4D9DE", linewidth = 0.35, alpha = 0.75) +
  geom_point(color = "#1F4E79", size = 2.3) +
  scale_shape_manual(values = shape_values, name = "Horizon point shape") +
  scale_x_continuous(breaks = week_breaks, labels = week_labels) +
  labs(title = "B. Signed forecast error", x = "Issue week (2026)", y = "Forecast error (expected - observed positive cells)") + theme_p7f

panel_c <- ggplot(occ, aes(horizon_label, forecast_error)) +
  geom_hline(yintercept = 0, color = "#444444", linewidth = 0.45) +
  geom_boxplot(width = 0.55, fill = "#C6DBEF", color = "#1F4E79", outlier.shape = NA, alpha = 0.8) +
  geom_jitter(width = 0.08, height = 0, color = "#444444", size = 1.5, alpha = 0.8) +
  labs(title = "C. Error distribution by horizon", x = NULL, y = "Forecast error (expected - observed positive cells)") + theme_p7f

rolling_plot <- panel_a / (panel_b | panel_c) + plot_layout(heights = c(1.35, 1)) + plot_annotation(title = "Rolling-origin focal-region nowcasts", subtitle = "All 21 prespecified origins are retained; highlighted origins are W16, W20, W24, W28, W32, and W36.")
rolling_svg <- file.path(main_dir, "figure_04_rolling_occurrence_forecasts.svg")
rolling_png <- file.path(main_dir, "figure_04_rolling_occurrence_forecasts.png")
ggsave(rolling_svg, rolling_plot, device = svglite::svglite, width = 11, height = 8.5, units = "in", bg = "white")
ggsave(rolling_png, rolling_plot, device = "png", width = 11, height = 8.5, units = "in", dpi = 220, bg = "white")

write.csv(occ, file.path(plot_data_dir, "rolling_occurrence_plot_data.csv"), row.names = FALSE, quote = TRUE)
write.csv(hist, file.path(plot_data_dir, "observed_history_plot_data.csv"), row.names = FALSE, quote = TRUE)

style <- list(
  font_family = "sans",
  base_font_size_pt = 11,
  title_size_pt = 12,
  panel_label_convention = "A., B., C., ...",
  panel_label_position = "upper-left within panel title",
  axis_title_size_pt = 10,
  axis_text_size_pt = 9,
  legend_text_size_pt = 9,
  main_dimensions_in = list(full_width = c(11, 8.5), single_column = c(7.2, 5.2)),
  supplement_dimensions_in = c(8.5, 7.0),
  raster_preview_dpi = 220,
  vector_formats = c("SVG", "PDF"),
  map_palette = "sequential light-low to dark-high; inherited from P7D corrected assets",
  observed_series = "#222222",
  rolling_neutral = "#AEB7C0 / #C7CDD3",
  rolling_highlight = "#D55E00",
  support_classes = list(SUPPORTED = "#009E73", CAUTION = "#E69F00", EXTRAPOLATIVE = "#D55E00"),
  horizon_symbols = list(h1 = 16, h2 = 17, h3 = 15),
  uncertainty_ribbon = "NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS"
)
write(toJSON(style, auto_unbox = TRUE, pretty = TRUE), file.path(results_dir, "figure_style_spec.json"))

disposition <- data.frame(
  figure_id = c("F1", "F2", "F3", "F4", "F5", "F6", "S1", "S2", "S3", "S4", "S5", "S6", "A1", "A2"),
  title = c("Domain and model framework", "Predictive performance across horizons", "Mexico-Texas spatial-temporal occurrence dynamics", "Rolling-origin 1-3 week nowcast trajectories", "Issue-time environmental proxy validation", "Predictor associations", "Reliability curves", "Frontier sensitivity", "Count diagnostics", "Proxy error and support transitions", "Support and extrapolation", "Rolling count nowcasts", "Expected-count spatial candidate", "Single-W36 forecast trajectory"),
  current_source = c("P7D corrected", "P7C refined", "P7D corrected", "P7E regenerated", "P7C refined", "P7C refined", "P7C", "P7C", "P7C", "P7C", "P7D corrected", "P7E", "P7D corrected", "P7D"),
  scientific_question = c("Where does the model operate and what is the production contract?", "How stable are occurrence metrics over h=1-3?", "How does occurrence burden evolve in the focal corridor?", "How do repeated issue-time forecast threads behave?", "What is the performance cost of E0?", "What conditional associations are represented by fitted coefficients?", "Are probabilities calibrated?", "How sensitive are frontier results?", "How does the count component behave?", "What are proxy errors and support transitions?", "Where is predictor-space support limited?", "How does count burden behave across horizons?", "Does expected count add distinct spatial information?", "How does one W36 issue trajectory compare with later observations?"),
  disposition = c("MAIN", "MAIN", "MAIN", "MAIN", "MAIN", "MAIN", "SUPPLEMENT", "SUPPLEMENT", "SUPPLEMENT", "SUPPLEMENT", "SUPPLEMENT", "SUPPLEMENT", "ARCHIVE", "ARCHIVE"),
  reason = c("Opening framework figure with corrected boundaries and shared domain colors.", "Canonical horizon-performance summary.", "Occurrence is the clearer spatial and regional-burden representation.", "Supersedes the single-origin trajectory and shows repeated issuances.", "Direct operational-proxy validation.", "Retained with mixed-scale caveat and noncausal framing.", "Supports calibration interpretation without duplicating main metrics.", "Preserves bounded robustness evidence.", "Diagnostic count limitation belongs outside main narrative.", "Supports proxy and support caveats.", "Important limitation, but redundant with the core operational figures in main text.", "Diagnostic count view; occurrence remains the primary operational showcase.", "Retained for provenance but not active package.", "Superseded by the repeated-origin P7E display."),
  remaining_limitation = c("Cartographic boundary derivative is orientation only.", "Retrospective rolling-origin metrics.", "Focal-region descriptive aggregation; not causal spread inference.", "No qualified regional uncertainty ribbon.", "Depends on E0 issue-time proxy.", "Coefficients are not globally comparable across mixed scaling classes.", "Sparse strata remain possible.", "Sparse frontier positives.", "Known count-process bias.", "No new uncertainty model.", "Substantial extrapolative support burden.", "Count bias and no regional uncertainty ribbon.", "Candidate representation only.", "Not a repeated-origin operational summary."),
  stringsAsFactors = FALSE
)
write.csv(disposition, file.path(results_dir, "figure_disposition.csv"), row.names = FALSE, quote = TRUE)

source_registry <- data.frame(
  figure_id = disposition$figure_id,
  title = disposition$title,
  disposition = disposition$disposition,
  source_phase = disposition$current_source,
  source_file = c(
    "analysis/p7d_cartography_forecast/figures/main_candidates/figure_01_domain_framework_corrected.(png|svg)",
    "analysis/p7c_figure_refinement/figures/main/figure_02_predictive_performance.(png|svg)",
    "analysis/p7d_cartography_forecast/figures/main_candidates/figure_03_mexico_texas_occurrence_corrected.(png|svg)",
    "analysis/p7e_rolling_forecasts/results/rolling_occurrence_forecasts.csv; observed_occurrence_history.csv",
    "analysis/p7c_figure_refinement/figures/main/figure_04_issue_time_proxy_validation.(png|svg)",
    "analysis/p7c_figure_refinement/figures/main/figure_05_predictor_associations.(png|svg)",
    "analysis/p7c_figure_refinement/figures/supplement/S1_reliability_curves.(png|svg)",
    "analysis/p7c_figure_refinement/figures/supplement/S2_frontier_sensitivity.(png|svg)",
    "analysis/p7c_figure_refinement/figures/supplement/S3_count_diagnostics_reference.png",
    "analysis/p7c_figure_refinement/figures/supplement/S4_proxy_error_support_transitions.(png|svg)",
    "analysis/p7d_cartography_forecast/figures/main_candidates/figure_06_support_extrapolation_corrected.(png|svg)",
    "analysis/p7e_rolling_forecasts/figures/figure_rolling_count_forecasts_candidate.(png|svg)",
    "analysis/p7d_cartography_forecast/figures/main_candidates/figure_03_mexico_texas_expected_count_corrected_candidate.(png|svg)",
    "analysis/p7d_cartography_forecast/figures/main_candidates/forecast_trajectory_issue_W36_candidate.(png|svg)"
  ),
  output_file = c(
    "figures/main/figure_01_domain_framework.(png|svg)", "figures/main/figure_02_predictive_performance.(png|svg)", "figures/main/figure_03_mexico_texas_occurrence.(png|svg)", "figures/main/figure_04_rolling_occurrence_forecasts.(png|svg)", "figures/main/figure_05_issue_time_proxy_validation.(png|svg)", "figures/main/figure_06_predictor_associations.(png|svg)", "figures/supplement/S1_reliability_curves.(png|svg)", "figures/supplement/S2_frontier_sensitivity.(png|svg)", "figures/supplement/S3_count_diagnostics.png", "figures/supplement/S4_proxy_error_support_transitions.(png|svg)", "figures/supplement/S5_support_extrapolation.(png|svg)", "figures/supplement/S6_rolling_count_nowcasts.(png|svg)", "figures/archive/figure_03_expected_count_archive.(png|svg)", "figures/archive/forecast_trajectory_issue_W36_archive.(png|svg)"
  ),
  source_hash = NA_character_, output_hash = NA_character_,
  stringsAsFactors = FALSE
)
source_registry$source_hash[4] <- paste(hash_file(source_path("analysis/p7e_rolling_forecasts/results/rolling_occurrence_forecasts.csv")), hash_file(source_path("analysis/p7e_rolling_forecasts/results/observed_occurrence_history.csv")), sep = ";")
source_registry$source_hash[-4] <- paste0("see canonical source registry; source assets preserved unchanged")
expand_output_paths <- function(pattern) {
  if (grepl("(png|svg)", pattern, fixed = TRUE)) {
    stem <- sub(".(png|svg)", "", pattern, fixed = TRUE)
    return(file.path(root, paste0(stem, c(".png", ".svg"))))
  }
  file.path(root, pattern)
}
for (i in seq_len(nrow(source_registry))) {
  output_paths <- expand_output_paths(source_registry$output_file[i])
  source_registry$output_hash[i] <- paste(vapply(output_paths, hash_file, character(1)), collapse = ";")
}
write.csv(source_registry, file.path(results_dir, "figure_source_registry.csv"), row.names = FALSE, quote = TRUE)

qa <- data.frame(
  figure_id = c("F1", "F2", "F3", "F4", "F5", "F6", "S1", "S2", "S3", "S4", "S5", "S6"),
  scientific_question_obvious = TRUE,
  primary_message_clear = c(TRUE, TRUE, TRUE, TRUE, TRUE, FALSE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE),
  axes_interpretable = TRUE,
  legend_understandable = TRUE,
  observed_predicted_distinction_clear = c(TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE),
  major_caveat_visible_or_captioned = TRUE,
  redundant_with_another_figure = c(FALSE, FALSE, FALSE, FALSE, FALSE, TRUE, FALSE, FALSE, FALSE, FALSE, TRUE, FALSE),
  recommendation = c("MAIN", "MAIN", "MAIN", "MAIN", "MAIN", "MAIN_WITH_CAVEAT", "SUPPLEMENT", "SUPPLEMENT", "SUPPLEMENT", "SUPPLEMENT", "SUPPLEMENT", "SUPPLEMENT"),
  note = c("Corrected boundaries and shared domain colors.", "Compact horizon metric summary.", "Fixed weeks, shared scale, observed detections.", "Repeated issuance threads; no uncertainty ribbon.", "E0-minus-REALIZED direction is explicit.", "Mixed scaling prevents global importance interpretation.", "Canonical reliability display.", "Sparse frontier strata remain a caveat.", "Count-process diagnostic.", "Proxy/support diagnostic.", "Support figure is important but overlaps operational caveats.", "Candidate count-burden display."),
  stringsAsFactors = FALSE
)
write.csv(qa, file.path(results_dir, "science_qa.csv"), row.names = FALSE, quote = TRUE)

write(toJSON(list(
  decision = "P7F_FINAL_FIGURE_SET_SUPPORTED_WITH_LIMITATIONS",
  predictor_association_status = "INADEQUATE_REQUIRES_SEPARATE_PREDICTOR_INFLUENCE_ANALYSIS",
  main_figure_count = sum(disposition$disposition == "MAIN"),
  no_model_fitting = TRUE,
  uncertainty_ribbon = "NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS"
), auto_unbox = TRUE, pretty = TRUE), file.path(results_dir, "decision.json"))
write(toJSON(list(source_main_sha = "5c826708c03dbd9117da0ddf0e1fa842000767d2", frozen_model = "STRUCTURED_A3", frozen_artifact_sha256 = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e", proxy = "E0_LAST_AVAILABLE", generator = "analysis/p7f_final_figures/scripts/generate_p7f_figures.R", no_model_fitting = TRUE), auto_unbox = TRUE, pretty = TRUE), file.path(results_dir, "run_metadata.json"))
cat("P7F_FIGURES_GENERATED\n")
