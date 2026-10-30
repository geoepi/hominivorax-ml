#!/usr/bin/env Rscript

# P7B science-facing figure generation. Canonical aggregation and formatting
# only; no model fitting, refitting, tuning, or new importance method.
suppressPackageStartupMessages({
  library(ggplot2); library(patchwork); library(dplyr); library(tidyr)
  library(png); library(grid); library(jsonlite); library(digest)
})

args <- commandArgs(trailingOnly = TRUE)
repo <- if (length(args) >= 1) normalizePath(args[[1]], mustWork = TRUE) else normalizePath(".", mustWork = TRUE)
root <- file.path(repo, "analysis", "p7b_science_figures")
fig_main <- file.path(root, "figures", "main")
fig_supp <- file.path(root, "figures", "supplement")
tables_dir <- file.path(root, "tables")
captions_dir <- file.path(root, "captions")
results_dir <- file.path(root, "results")
plot_data_dir <- file.path(results_dir, "plot_data")
for (x in c(fig_main, fig_supp, tables_dir, captions_dir, results_dir, plot_data_dir)) dir.create(x, recursive = TRUE, showWarnings = FALSE)

read_csv <- function(path) read.csv(path, stringsAsFactors = FALSE, check.names = FALSE)
write_data <- function(x, name) {
  path <- file.path(plot_data_dir, name)
  write.csv(x, path, row.names = FALSE, quote = TRUE, na = "")
  path
}
sha256 <- function(path) digest(path, algo = "sha256", file = TRUE)
rel <- function(path) {
  p <- normalizePath(path, winslash = "/", mustWork = FALSE)
  prefix <- paste0(normalizePath(repo, winslash = "/", mustWork = TRUE), "/")
  if (startsWith(p, prefix)) substring(p, nchar(prefix) + 1L) else p
}
save_figure <- function(plot, stem, width = 10, height = 6, directory = fig_main) {
  svg <- file.path(directory, paste0(stem, ".svg")); png_path <- file.path(directory, paste0(stem, ".png"))
  ggsave(svg, plot = plot, device = svglite::svglite, width = width, height = height, units = "in", bg = "white")
  ggsave(png_path, plot = plot, device = "png", width = width, height = height, units = "in", dpi = 220, bg = "white")
  c(svg = svg, png = png_path)
}
theme_set(theme_minimal(base_size = 10, base_family = "Arial"))
horizon_cols <- c("h=1" = "#1b9e77", "h=2" = "#d95f02", "h=3" = "#7570b3")
support_cols <- c("SUPPORTED" = "#2b8cbe", "CAUTION" = "#fdae61", "EXTRAPOLATIVE" = "#d73027")

domain <- read_csv(file.path(results_dir, "figure_01_domain_grid.csv"))
map_data <- read_csv(file.path(results_dir, "figure_03_focal_h1_map_data.csv"))
time_data <- read_csv(file.path(results_dir, "figure_03_focal_h1_time_series.csv"))
metrics <- read_csv(file.path(repo, "analysis/p2_operational_nowcast/results/horizon_metrics.csv"))
metrics <- metrics[metrics$scope == "all" & metrics$region == "all" & metrics$horizon %in% c(1, 2, 3), ]
cal_bins <- read_csv(file.path(repo, "analysis/p2_operational_nowcast/results/calibration_bins.csv"))
cal_bins <- cal_bins[cal_bins$metric_family == "occurrence" & cal_bins$scope == "all" & cal_bins$horizon %in% c(1, 2, 3), ]
paired <- read_csv(file.path(repo, "analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv"))
bootstrap <- read_csv(file.path(repo, "analysis/p5a_environmental_proxy/results/bootstrap_intervals.csv"))
env_family <- read_csv(file.path(repo, "analysis/p5a_environmental_proxy/results/environmental_proxy_error_by_family.csv"))
support <- read_csv(file.path(repo, "analysis/p5a_environmental_proxy/results/support_metrics.csv"))
support_perf <- read_csv(file.path(repo, "analysis/p4_uncertainty_extrapolation/results/performance_by_support.csv"))
frontier_sensitivity <- read_csv(file.path(repo, "analysis/p7_publication/supplement/frontier_sensitivity_metrics.csv"))
coeff_audit <- read_csv(file.path(repo, "analysis/p7a_figure_design/results/predictor_contribution_audit.csv"))
stability <- read_csv(file.path(repo, "analysis/structured_a3_final_comparison/results/a3_coefficient_stability.csv"))

# Figure 1: domain, focal crop, model structure, and E0 issue-time proxy.
bbox <- data.frame(xmin = -107.5, xmax = -96, ymin = 24, ymax = 33)
domain <- domain %>% mutate(region = ifelse(country_or_domain_region == "Mexico", "Mexico", "U.S.-to-40N"))
p1a <- ggplot(domain, aes(lon, lat, color = region)) + geom_point(shape = 15, size = 0.32, alpha = 0.65) +
  geom_rect(data = bbox, aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax), inherit.aes = FALSE, fill = NA, color = "black", linewidth = 0.8, linetype = 2) +
  coord_equal(expand = FALSE) + scale_color_manual(values = c("Mexico" = "#377eb8", "U.S.-to-40N" = "#e41a1c")) +
  labs(title = "Canonical modeling domain", x = "Longitude", y = "Latitude", color = "Domain") + theme(legend.position = "bottom")
p1b <- ggplot(domain %>% filter(lon >= -107.5, lon <= -96, lat >= 24, lat <= 33), aes(lon, lat)) +
  geom_point(shape = 15, size = 0.5, color = "#2c7fb8", alpha = 0.7) + coord_equal(xlim = c(-107.5, -96), ylim = c(24, 33), expand = FALSE) +
  labs(title = "Mexico-Texas focal region", x = "Longitude", y = "Latitude")
box_df <- data.frame(xmin = c(0.05, 0.39, 0.70), xmax = c(0.30, 0.61, 0.95), ymin = c(0.57, 0.57, 0.57), ymax = c(0.79, 0.79, 0.79), label = c("34 predictors", "Occurrence\ncomponent", "Conditional positive-count\ncomponent"))
arrow_df <- data.frame(x = c(0.30, 0.61), xend = c(0.39, 0.70), y = c(0.68, 0.68), yend = c(0.68, 0.68))
p1c <- ggplot() + geom_rect(data = box_df, aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax), fill = "#e6f2ff", color = "#2166ac") +
  geom_text(data = box_df, aes(x = (xmin + xmax) / 2, y = (ymin + ymax) / 2, label = label), size = 3) +
  geom_segment(data = arrow_df, aes(x = x, xend = xend, y = y, yend = yend), arrow = arrow(length = unit(0.16, "cm")), linewidth = 0.5) +
  annotate("text", x = 0.5, y = 0.35, label = "hurdle expected count = occurrence probability × conditional positive count", size = 3) +
  annotate("text", x = 0.5, y = 0.14, label = "outputs: h=1, h=2, h=3", size = 3.4, fontface = "bold") + xlim(0, 1) + ylim(0, 1) + labs(title = "Frozen STRUCTURED_A3 hurdle structure") + theme_void()
proxy_df <- data.frame(x = c(1, 2, 3, 4, 5), label = c("issue\nT", "latest\nL(T)", "h=1", "h=2", "h=3"), group = c("issue", "available", "target", "target", "target"))
p1d <- ggplot(proxy_df, aes(x, 0, color = group)) + geom_segment(data = data.frame(x = 1, xend = 5, y = 0, yend = 0), aes(x = x, xend = xend, y = y, yend = yend), color = "#555555", arrow = arrow(length = unit(0.18, "cm")), linewidth = 0.7) + geom_point(size = 3) + geom_text(aes(label = label), vjust = -1.1, size = 3.1) + scale_color_manual(values = c("issue" = "#222222", "available" = "#2166ac", "target" = "#4daf4a"), guide = "none") + xlim(0.7, 5.3) + ylim(-0.2, 0.3) + labs(title = "E0_LAST_AVAILABLE operational input", subtitle = "latest legitimate environmental state held across h=1 to h=3") + theme_void()
fig1_data <- domain
fig1_data$panel <- "domain"
d1 <- write_data(fig1_data, "figure_01_domain_framework_data.csv")
f1 <- save_figure((p1a | p1b) / (p1c | p1d) + plot_annotation(tag_levels = "A"), "figure_01_domain_framework", 12, 8)

# Figure 2: canonical P2 performance by horizon.
m2 <- metrics %>% mutate(horizon_label = paste0("h=", horizon))
p2a <- ggplot(m2, aes(horizon_label, brier, color = horizon_label)) + geom_point(size = 3) + geom_line(aes(group = 1), color = "#555555") + scale_color_manual(values = horizon_cols) + labs(title = "Brier score", x = NULL, y = "Brier score (lower is better)") + theme(legend.position = "none")
p2b <- ggplot(m2, aes(horizon_label, auprc, color = horizon_label)) + geom_point(size = 3) + geom_line(aes(group = 1), color = "#555555") + scale_color_manual(values = horizon_cols) + labs(title = "AUPRC", x = NULL, y = "AUPRC (higher is better)") + theme(legend.position = "none")
cal2 <- m2 %>% select(horizon, calibration_intercept, calibration_slope) %>% pivot_longer(c(calibration_intercept, calibration_slope), names_to = "metric", values_to = "value") %>% mutate(horizon_label = paste0("h=", horizon), metric = recode(metric, calibration_intercept = "Calibration intercept", calibration_slope = "Calibration slope"))
p2c <- ggplot(cal2, aes(horizon_label, value, color = metric, group = metric)) + geom_point(size = 2.8) + geom_line() + labs(title = "Calibration summaries", x = NULL, y = "Estimate", color = NULL) + theme(legend.position = "bottom")
p2d <- ggplot(m2, aes(horizon_label, auroc, color = horizon_label)) + geom_point(size = 3) + geom_line(aes(group = 1), color = "#555555") + scale_color_manual(values = horizon_cols) + labs(title = "AUROC context", x = NULL, y = "AUROC") + theme(legend.position = "none")
d2 <- write_data(m2, "figure_02_performance_data.csv")
f2 <- save_figure((p2a | p2b) / (p2c | p2d) + plot_annotation(tag_levels = "A"), "figure_02_predictive_performance", 10, 8)

# Figure 3: bounded focal extraction; maps share extent and legend scales.
map_data <- map_data %>% mutate(target_week = factor(target_week, levels = unique(target_week)))
prob_limits <- range(map_data$p_occurrence, na.rm = TRUE); count_limits <- range(map_data$expected_count, na.rm = TRUE)
map_base <- list(coord_equal(xlim = c(-107.5, -96), ylim = c(24, 33), expand = FALSE), theme_void(), theme(strip.text = element_text(size = 8), legend.position = "bottom"))
p3a <- ggplot(map_data, aes(lon, lat, color = p_occurrence)) + geom_point(shape = 15, size = 0.52) + geom_point(data = map_data %>% filter(observed_positive > 0), shape = 21, fill = "white", color = "black", size = 1.05, stroke = 0.35) + facet_wrap(~target_week, nrow = 1) + scale_color_viridis_c(limits = prob_limits, name = "Occurrence\nprobability") + map_base + labs(title = "h=1 occurrence probability; observed positives overlaid")
p3b <- ggplot(map_data, aes(lon, lat, color = expected_count)) + geom_point(shape = 15, size = 0.52) + geom_point(data = map_data %>% filter(observed_count > 0), shape = 21, fill = "white", color = "black", size = 1.05, stroke = 0.35) + facet_wrap(~target_week, nrow = 1) + scale_color_viridis_c(limits = count_limits, name = "Expected\ncount") + map_base + labs(title = "Candidate full hurdle expected-count maps; observed counts overlaid")
ts_long <- time_data %>% transmute(target_week, observed_positive_cells, expected_positive_cells, observed_count, expected_count)
p3c <- ggplot(ts_long, aes(target_week, observed_positive_cells)) + geom_line(aes(y = observed_positive_cells, color = "Observed positive cells", group = 1), linewidth = 0.8) + geom_point(aes(y = observed_positive_cells, color = "Observed positive cells"), size = 1.5) + geom_line(aes(y = expected_positive_cells, color = "Expected number of positive cells", group = 1), linewidth = 0.8) + geom_point(aes(y = expected_positive_cells, color = "Expected number of positive cells"), size = 1.5) + scale_color_manual(values = c("Observed positive cells" = "#222222", "Expected number of positive cells" = "#2166ac")) + labs(title = "Focal occurrence burden, h=1", x = "Target week", y = "Cells", color = NULL) + theme(axis.text.x = element_text(angle = 45, hjust = 1), legend.position = "bottom")
p3d <- ggplot(ts_long, aes(target_week, observed_count)) + geom_line(aes(y = observed_count, color = "Observed total count", group = 1), linewidth = 0.8) + geom_point(aes(y = observed_count, color = "Observed total count"), size = 1.5) + geom_line(aes(y = expected_count, color = "Predicted total expected count", group = 1), linewidth = 0.8) + geom_point(aes(y = expected_count, color = "Predicted total expected count"), size = 1.5) + scale_color_manual(values = c("Observed total count" = "#222222", "Predicted total expected count" = "#b2182b")) + labs(title = "Candidate focal count burden, h=1", x = "Target week", y = "Count", color = NULL) + theme(axis.text.x = element_text(angle = 45, hjust = 1), legend.position = "bottom")
d3m <- write_data(map_data, "figure_03_focal_h1_map_data.csv"); d3t <- write_data(time_data, "figure_03_focal_h1_time_series.csv")
f3occ <- save_figure(p3a / p3c + plot_annotation(tag_levels = "A"), "figure_03_mexico_texas_occurrence", 14, 9)
f3cnt <- save_figure(p3b / p3d + plot_annotation(tag_levels = "A"), "figure_03_mexico_texas_expected_count_candidate", 14, 9)

# Figure 4: E0 proxy-minus-realized differences with canonical intervals.
e0_metrics <- c("brier", "auprc", "conditional_mae", "full_expected_mae")
f4_data <- paired %>% filter(proxy_id == "E0_LAST_AVAILABLE", metric %in% e0_metrics) %>%
  left_join(bootstrap %>% filter(proxy_id == "E0_LAST_AVAILABLE", metric %in% e0_metrics) %>% select(horizon, metric, lower, upper), by = c("horizon", "metric"))
diff_panel <- function(metric, title) {
  d <- f4_data %>% filter(.data$metric == metric)
  ggplot(d, aes(factor(horizon), difference_proxy_minus_realized)) + geom_hline(yintercept = 0, linetype = 2, color = "#555555") + geom_errorbar(aes(ymin = lower, ymax = upper), width = 0.12, color = "#2166ac") + geom_point(size = 2.7, color = "#2166ac") + labs(title = title, x = "Horizon", y = "E0 - REALIZED_ENV")
}
f4a <- diff_panel("brier", "Brier")
f4b <- diff_panel("auprc", "AUPRC")
f4c <- diff_panel("conditional_mae", "Conditional positive-count MAE")
f4d <- diff_panel("full_expected_mae", "Full expected-count MAE")
d4 <- write_data(f4_data, "figure_04_e0_proxy_degradation_data.csv")
f4 <- save_figure((f4a | f4b) / (f4c | f4d) + plot_annotation(tag_levels = "A"), "figure_04_issue_time_proxy_validation", 11, 8)

# Figure 5: signed coefficient associations; no global importance ranking.
coef_long <- bind_rows(
  coeff_audit %>% transmute(predictor, family, scale_category = scaling_status, component = "Occurrence", coefficient = occurrence_coefficient),
  coeff_audit %>% transmute(predictor, family, scale_category = scaling_status, component = "Conditional positive-count", coefficient = count_coefficient)
) %>% filter(is.finite(coefficient)) %>% arrange(component, family, predictor)
coef_long$predictor <- factor(coef_long$predictor, levels = rev(unique(coef_long$predictor)))
p5a <- ggplot(coef_long %>% filter(component == "Occurrence"), aes(coefficient, predictor, color = scale_category)) + geom_vline(xintercept = 0, color = "#555555") + geom_segment(aes(x = 0, xend = coefficient, y = predictor, yend = predictor), linewidth = 0.6) + geom_point(size = 1.8) + facet_grid(family ~ ., scales = "free_y", space = "free_y") + labs(title = "Occurrence-component signed associations", x = "Fitted coefficient; scale categories shown", y = NULL, color = "Scale category") + theme(legend.position = "bottom", strip.text.y = element_text(angle = 0))
p5b <- ggplot(coef_long %>% filter(component == "Conditional positive-count"), aes(coefficient, predictor, color = scale_category)) + geom_vline(xintercept = 0, color = "#555555") + geom_segment(aes(x = 0, xend = coefficient, y = predictor, yend = predictor), linewidth = 0.6) + geom_point(size = 1.8) + facet_grid(family ~ ., scales = "free_y", space = "free_y") + labs(title = "Conditional positive-count signed associations", x = "Fitted coefficient; scale categories shown", y = NULL, color = "Scale category") + theme(legend.position = "bottom", strip.text.y = element_text(angle = 0))
stability_s <- stability %>% filter(row_type == "summary") %>% mutate(component_label = recode(component, occurrence = "Occurrence", positive_count = "Conditional positive-count"), feature = factor(feature, levels = rev(unique(feature))))
p5c <- ggplot(stability_s, aes(feature, mean_coefficient, color = component_label)) + geom_hline(yintercept = 0, color = "#555555") + geom_errorbar(aes(ymin = mean_coefficient - sd_coefficient, ymax = mean_coefficient + sd_coefficient), width = 0.15, position = position_dodge(width = 0.35)) + geom_point(position = position_dodge(width = 0.35), size = 2) + coord_flip() + labs(title = "Canonical rolling-origin stability subset", x = NULL, y = "Mean coefficient +/- SD", color = NULL) + theme(legend.position = "bottom")
d5 <- write_data(coef_long, "figure_05_signed_coefficient_associations_data.csv"); d5s <- write_data(stability_s, "figure_05_coefficient_stability_subset_data.csv")
f5 <- save_figure((p5a / p5b) | p5c + plot_layout(widths = c(1.55, 0.9)) + plot_annotation(tag_levels = "A"), "figure_05_predictor_associations", 15, 12)

# Figure 6: support proportions, canonical support map reuse, and performance.
support0 <- support %>% filter(proxy_id == "E0_LAST_AVAILABLE") %>% mutate(horizon_label = paste0("h=", horizon))
p6a <- ggplot(support0, aes(horizon_label, proportion, fill = support_class)) + geom_col() + scale_y_continuous(labels = scales::percent_format()) + scale_fill_manual(values = support_cols) + labs(title = "E0 support-class proportions", x = NULL, y = "Evaluated rows", fill = NULL) + theme(legend.position = "bottom")
support_perf0 <- support_perf %>% filter(horizon %in% c(1, 2, 3)) %>% mutate(horizon_label = paste0("h=", horizon))
p6c <- ggplot(support_perf0, aes(horizon_label, brier, color = support_class)) + geom_point(size = 2.4) + geom_line(aes(group = support_class)) + scale_color_manual(values = support_cols) + labs(title = "Brier score by support class", x = NULL, y = "Brier score", color = NULL) + theme(legend.position = "bottom")
support_png <- file.path(repo, "analysis/p4_uncertainty_extrapolation/figures/P4-6_production_support_classification.png")
p6b <- if (file.exists(support_png)) wrap_elements(full = rasterGrob(readPNG(support_png), interpolate = TRUE)) else wrap_elements(full = textGrob("Canonical support map unavailable", gp = gpar(fontsize = 10)))
d6 <- write_data(support0, "figure_06_support_proportions_data.csv")
f6 <- save_figure(p6a | p6b | p6c + plot_layout(widths = c(1, 1.25, 1)) + plot_annotation(tag_levels = "A"), "figure_06_support_extrapolation", 14, 5.5)
if (file.exists(support_png)) file.copy(support_png, file.path(fig_main, "figure_06_support_canonical_p4.png"), overwrite = TRUE)

# Supplementary candidates.
cal_bins$horizon_label <- paste0("h=", cal_bins$horizon)
cal_bins <- cal_bins[is.finite(cal_bins$mean_predicted) & is.finite(cal_bins$observed_probability), ]
pS1 <- ggplot(cal_bins, aes(mean_predicted, observed_probability)) + geom_abline(slope = 1, intercept = 0, linetype = 2, color = "#555555") + geom_errorbar(aes(ymin = observed_probability - 1.96 * observed_se, ymax = observed_probability + 1.96 * observed_se), width = 0, alpha = 0.4) + geom_point(size = 1.3, color = "#2166ac") + facet_wrap(~horizon_label, nrow = 1) + coord_equal(xlim = c(0, 1), ylim = c(0, 1)) + labs(title = "S1. Occurrence reliability by horizon", x = "Mean predicted probability", y = "Observed probability")
dS1 <- write_data(cal_bins, "supplement_S1_reliability_data.csv"); s1 <- save_figure(pS1, "S1_reliability_curves", 11, 4.5, fig_supp)

fs <- frontier_sensitivity %>% filter(horizon %in% c(1, 2, 3))
if ("frontier_class" %in% names(fs)) fs <- fs %>% filter(frontier_class %in% c("previously_unoccupied", "frontier", "unoccupied"))
pS2 <- ggplot(fs, aes(factor(horizon), brier, color = definition, group = definition)) + geom_point(position = position_dodge(width = 0.25)) + labs(title = "S2. Frontier-definition sensitivity", x = "Horizon", y = "Brier score", color = "Definition") + theme(legend.position = "bottom")
dS2 <- write_data(fs, "supplement_S2_frontier_sensitivity_data.csv"); s2 <- save_figure(pS2, "S2_frontier_sensitivity", 10, 5, fig_supp)

count_reference <- file.path(repo, "analysis/p3_robustness/figures/P3-2_count_error_by_magnitude.png")
s3_path <- file.path(fig_supp, "S3_count_diagnostics_reference.png"); if (file.exists(count_reference)) file.copy(count_reference, s3_path, overwrite = TRUE)
transition <- read_csv(file.path(repo, "analysis/p5a_environmental_proxy/results/support_transitions.csv")) %>% filter(proxy_id == "E0_LAST_AVAILABLE")
env0 <- env_family %>% filter(proxy_id == "E0_LAST_AVAILABLE") %>% group_by(horizon, family) %>% summarise(mae = mean(mae), .groups = "drop") %>% mutate(horizon_label = paste0("h=", horizon))
pS4a <- ggplot(env0, aes(family, mae, fill = horizon_label)) + geom_col(position = "dodge") + labs(title = "A. Environmental proxy MAE by family", x = NULL, y = "Mean MAE", fill = NULL) + theme(axis.text.x = element_text(angle = 30, hjust = 1), legend.position = "bottom")
transition <- transition %>% mutate(from_support_class = factor(from_support_class, levels = c("SUPPORTED", "CAUTION", "EXTRAPOLATIVE")), to_support_class = factor(to_support_class, levels = c("SUPPORTED", "CAUTION", "EXTRAPOLATIVE")))
pS4b <- ggplot(transition, aes(from_support_class, to_support_class, fill = n)) + geom_tile() + geom_text(aes(label = n), size = 2.8) + scale_fill_viridis_c() + labs(title = "B. E0 support-class transitions", x = "REALIZED_ENV class", y = "E0 class", fill = "Rows")
dS4a <- write_data(env0, "supplement_S4_environmental_error_family_data.csv"); dS4b <- write_data(transition, "supplement_S4_support_transition_data.csv"); s4 <- save_figure(pS4a | pS4b + plot_annotation(tag_levels = "A"), "S4_proxy_error_support_transitions", 11, 5, fig_supp)

# Copy exact canonical P7 core tables without scientific edits.
table_map <- c(table_1_model_data = "table_1_data_model_specification.csv", table_2_occurrence = "table_2_occurrence_performance.csv", table_3_count = "table_3_count_performance.csv", table_4_proxy = "table_4_proxy_comparison.csv")
for (nm in names(table_map)) file.copy(file.path(repo, "analysis/p7_publication/tables", table_map[[nm]]), file.path(tables_dir, paste0(nm, ".csv")), overwrite = TRUE)

# Technical captions only: definitions, source phases, and primary caveats.
captions <- c(
  figure_01 = "A. Canonical 25 × 25 km modeling domain with the fixed Mexico–Texas focal bounding box. B. Focal-region cell grid. C. STRUCTURED_A3 hurdle components: occurrence probability and conditional positive-count prediction combine into the full expected count. D. E0_LAST_AVAILABLE uses the latest legitimately available environmental state at issue time and holds that state across h=1–3; future environmental conditions are not observed in advance.",
  figure_02 = "Canonical P2 rolling-origin metrics by horizon. Lower Brier is better; AUPRC is prevalence-sensitive; calibration intercepts are centered on zero and slopes on one. Values are retrospective evaluation summaries and are not causal effects.",
  figure_03_occurrence = "Focal-region h=1 outputs for the prespecified target weeks 2026-W17, W22, W27, W32, and W37. Maps use identical geographic and probability scales; white outlined cells mark observed positives. The time series compares observed positive cells with the expected number of positive cells, defined as the sum of cell-level occurrence probabilities. It is not a regional risk index.",
  figure_03_count = "Candidate full hurdle expected-count maps and focal count time series for the same prespecified weeks and h=1 interval. Map colors use one scale across weeks. The predicted total expected count is the sum of cell-level full hurdle expected counts; this candidate is shown for scientific review and does not change the count model.",
  figure_04 = "Paired E0_LAST_AVAILABLE minus REALIZED_ENV differences from P5A. REALIZED_ENV uses target-week realized environmental inputs, whereas E0 uses only the latest issue-time environmental state. Intervals are the canonical dependence-aware target-week bootstrap intervals. Near-zero predictive differences do not imply that future environmental conditions are constant.",
  figure_05 = "Signed fitted coefficient associations for the occurrence and conditional positive-count components. Scale categories identify standardized continuous, binary, calendar, and other predictor encodings. Coefficients are conditional predictive associations; magnitudes are not globally comparable across mixed scaling classes and are not causal effects or feature-importance scores. The stability panel is limited to four predictors with canonical rolling-origin summaries.",
  figure_06 = "P4 support classes are shown without threshold changes. The canonical support display is reused from P4. SUPPORTED, CAUTION, and EXTRAPOLATIVE identify predictor-space support states; extrapolative predictions remain visible and are not treated as validated everywhere.",
  S1 = "Canonical P2 occurrence reliability curves by horizon. Points show mean predicted probability and observed probability within fixed probability bins; bars show the canonical approximate binomial standard-error display. The sparse high-probability tail should not be overinterpreted.",
  S2 = "Canonical P3 frontier-definition sensitivity summaries. Definitions and outcomes are unchanged from P3; this figure is descriptive and does not select a new frontier definition.",
  S3 = "Canonical P3 count-error diagnostic reused without re-estimation. Count-stratum behavior is descriptive and does not imply unbiased abundance estimation.",
  S4 = "Canonical P5A environmental proxy error summarized by predictor family and E0 support-class transitions. These are diagnostic summaries; support thresholds are unchanged."
)
for (nm in names(captions)) writeLines(captions[[nm]], file.path(captions_dir, paste0(nm, ".caption.md")))

# Source registry: one row per review panel/output.  Output hashes are computed
# after all deterministic figure and plotted-data files are written.
registry <- data.frame(
  figure_id = character(), panel_id = character(), source_phase = character(), source_file = character(), source_fields = character(), transformations = character(), filtering = character(), geographic_subset = character(), temporal_subset = character(), plotting_script = character(), output_file = character(), output_hash = character(), underlying_data_file = character(), underlying_data_hash = character(), stringsAsFactors = FALSE
)
add_reg <- function(figure_id, panel_id, phase, source_file, fields, trans, filt, geo, time, output, data_file = NA_character_) {
  out_path <- file.path(repo, output); data_path <- if (!is.na(data_file)) file.path(repo, data_file) else NA_character_
  registry <<- rbind(registry, data.frame(figure_id = figure_id, panel_id = panel_id, source_phase = phase, source_file = source_file, source_fields = fields, transformations = trans, filtering = filt, geographic_subset = geo, temporal_subset = time, plotting_script = "analysis/p7b_science_figures/scripts/generate_p7b_figures.R", output_file = output, output_hash = if (file.exists(out_path)) sha256(out_path) else NA_character_, underlying_data_file = if (!is.na(data_file)) data_file else NA_character_, underlying_data_hash = if (!is.na(data_file) && file.exists(data_path)) sha256(data_path) else NA_character_, stringsAsFactors = FALSE))
}
add_reg("Figure 1", "A", "P2/P7", "analysis/p7b_science_figures/results/figure_01_domain_grid.csv", "model_node_id,lon,lat,country_or_domain_region", "plot cell centers and fixed bbox", "none", "full domain", "domain reference", rel(f1[["svg"]]), rel(d1))
add_reg("Figure 1", "B", "P2/P7A", "analysis/p7b_science_figures/results/figure_01_domain_grid.csv; analysis/p7a_figure_design/results/mexico_texas_focal_region.json", "lon,lat,bbox", "fixed focal crop", "bbox exact", "EPSG:4326 -107.5:-96,24:33", "domain reference", rel(f1[["svg"]]), rel(d1))
add_reg("Figure 1", "C", "P0/P7", "config/production_model_freeze.json", "model ID, predictor count, hurdle components", "schematic only", "none", "full domain", "all horizons", rel(f1[["svg"]]), rel(d1))
add_reg("Figure 1", "D", "P5A/P6", "config/p6_production_config.json; analysis/p5a_environmental_proxy/results/proxy_contract.json", "proxy ID, horizon", "technical timeline", "none", "operational contract", "h=1:3", rel(f1[["svg"]]), rel(d1))
add_reg("Figure 2", "A-D", "P2", "analysis/p2_operational_nowcast/results/horizon_metrics.csv", "brier,auprc,calibration_intercept,calibration_slope,auroc", "select scope=all, region=all", "h=1:3", "full evaluation", "h=1:3", rel(f2[["svg"]]), rel(d2))
add_reg("Figure 3", "A,C", "P2", "Atlas P2 archive; analysis/p7b_science_figures/results/figure_03_focal_h1_map_data.csv", "lon,lat,p_occurrence,observed_positive,target_week", "bounded focal aggregation", "horizon=1", "EPSG:4326 fixed bbox", "W17,W22,W27,W32,W37; time W17:W37", rel(f3occ[["svg"]]), rel(d3m))
add_reg("Figure 3 candidate", "B,D", "P2", "Atlas P2 archive; analysis/p7b_science_figures/results/figure_03_focal_h1_map_data.csv", "lon,lat,expected_count,observed_count,target_week", "bounded focal aggregation", "horizon=1", "EPSG:4326 fixed bbox", "W17,W22,W27,W32,W37; time W17:W37", rel(f3cnt[["svg"]]), rel(d3m))
add_reg("Figure 4", "A-D", "P5A", "analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv; bootstrap_intervals.csv", "difference_proxy_minus_realized,lower,upper", "select E0 and four metrics", "proxy=E0", "full evaluation", "h=1:3", rel(f4[["svg"]]), rel(d4))
add_reg("Figure 5", "A-C", "P0/P7A", "analysis/p7a_figure_design/results/predictor_contribution_audit.csv; analysis/structured_a3_final_comparison/results/a3_coefficient_stability.csv", "predictor,component,coefficient,scale_category,mean,sd", "signed association display; no global ranking", "exclude intercept", "all predictors; four-feature stability subset", "frozen model; canonical folds", rel(f5[["svg"]]), rel(d5))
add_reg("Figure 6", "A,C", "P4/P5A", "analysis/p5a_environmental_proxy/results/support_metrics.csv; analysis/p4_uncertainty_extrapolation/results/performance_by_support.csv", "support_class,proportion,brier", "E0 proportions and P4 performance", "E0; h=1:3", "full evaluation", "h=1:3", rel(f6[["svg"]]), rel(d6))
add_reg("Figure 6", "B", "P4", "analysis/p4_uncertainty_extrapolation/figures/P4-6_production_support_classification.png", "canonical support display", "reuse existing raster", "none", "canonical P4 display", "canonical P4 display", rel(file.path(fig_main, "figure_06_support_canonical_p4.png")), NA_character_)
add_reg("S1", "A", "P2", "analysis/p2_operational_nowcast/results/calibration_bins.csv", "mean_predicted,observed_probability,observed_se", "fixed-bin reliability display", "occurrence,all,h=1:3", "full evaluation", "h=1:3", rel(s1[["svg"]]), rel(dS1))
add_reg("S2", "A", "P3", "analysis/p7_publication/supplement/frontier_sensitivity_metrics.csv", "definition,frontier_class,horizon,brier", "descriptive sensitivity plot", "canonical rows", "full evaluation", "h=1:3", rel(s2[["svg"]]), rel(dS2))
add_reg("S3", "A", "P3", "analysis/p3_robustness/figures/P3-2_count_error_by_magnitude.png", "canonical P3 figure", "reuse existing raster", "none", "full evaluation", "canonical P3", rel(s3_path), NA_character_)
add_reg("S4", "A-B", "P5A", "analysis/p5a_environmental_proxy/results/environmental_proxy_error_by_family.csv; support_transitions.csv", "family,mae,from_support_class,to_support_class,n", "family means and E0 transition matrix", "E0", "full evaluation", "h=1:3", rel(s4[["svg"]]), rel(dS4a))
registry$output_hash <- vapply(registry$output_file, function(x) {
  p <- file.path(repo, x)
  if (file.exists(p)) sha256(p) else NA_character_
}, character(1))
registry$underlying_data_hash <- vapply(seq_len(nrow(registry)), function(i) {
  x <- registry$underlying_data_file[[i]]
  if (is.na(x) || !nzchar(x)) return(NA_character_)
  p <- file.path(repo, x)
  if (file.exists(p)) sha256(p) else NA_character_
}, character(1))
write.csv(registry, file.path(results_dir, "figure_source_registry.csv"), row.names = FALSE, quote = TRUE, na = "")
write.csv(registry %>% select(figure_id, panel_id, output_file, output_hash, underlying_data_file, underlying_data_hash), file.path(results_dir, "figure_output_hashes.csv"), row.names = FALSE, quote = TRUE, na = "")

decision <- list(p7b_decision = "P7B_SCIENCE_FIGURES_SUPPORTED_WITH_LIMITATIONS", focal_bbox = bbox, focal_cells = 1689, focal_interval = c("2026-W17", "2026-W37"), map_weeks = c("2026-W17", "2026-W22", "2026-W27", "2026-W32", "2026-W37"), no_model_fitting = TRUE, limitations = c("focal support time series not complete in canonical P2/P6 joins", "state-level boundaries not retained in P2 archive; country/domain orientation used", "coefficient display is association-only under mixed scaling", "expected-count map/time-series representation remains a scientific-review candidate"))
write_json(decision, file.path(results_dir, "decision.json"), auto_unbox = TRUE, pretty = TRUE)
run_meta <- list(phase = "P7B", script = "analysis/p7b_science_figures/scripts/generate_p7b_figures.R", r_version = R.version.string, model_fitting = FALSE, source_registry = "analysis/p7b_science_figures/results/figure_source_registry.csv")
write_json(run_meta, file.path(results_dir, "run_metadata.json"), auto_unbox = TRUE, pretty = TRUE)
cat("P7B_FIGURES_GENERATED\n")
