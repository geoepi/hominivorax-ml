#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) stop("usage: render_a4_figures.R OUTPUT_ROOT")
root <- normalizePath(args[[1]], mustWork = TRUE)
dir.create(file.path(root, "figures"), showWarnings = FALSE, recursive = TRUE)

suppressPackageStartupMessages({
  library(ggplot2)
  library(readr)
  library(dplyr)
  library(tidyr)
  library(scales)
})

cmp <- read_csv(file.path(root, "results", "a4_candidate_comparison.csv"), show_col_types = FALSE)
fold <- read_csv(file.path(root, "results", "a4_fold_metrics.csv"), show_col_types = FALSE)
spatial <- read_csv(file.path(root, "results", "a4_spatial_residual_summary.csv"), show_col_types = FALSE)
ranking <- read_csv(file.path(root, "results", "a4_us_ranking.csv"), show_col_types = FALSE)
extrap <- read_csv(file.path(root, "results", "a4_extrapolative_regime_metrics.csv"), show_col_types = FALSE)
spatial_map <- read_csv(file.path(root, "results", "a4_spatial_residual_map_data.csv"), show_col_types = FALSE)

theme_set(theme_minimal(base_size = 11) + theme(plot.title = element_text(face = "bold"), legend.position = "bottom"))
candidate_levels <- c("A3", "A4-S", "A4-C", "A4-SC")
cmp$candidate <- factor(cmp$candidate, levels = candidate_levels)
cmp_eval <- cmp %>% filter(selection_eligible)

save_plot <- function(plot, stem, width = 7.2, height = 4.6) {
  ggsave(file.path(root, "figures", paste0(stem, ".png")), plot, width = width, height = height, dpi = 300, bg = "white")
  ggsave(file.path(root, "figures", paste0(stem, ".pdf")), plot, width = width, height = height, device = cairo_pdf, bg = "white")
}

save_plot(
  ggplot(cmp_eval, aes(candidate, mean_fold_pr_auc, fill = candidate)) +
    geom_col(width = 0.7, show.legend = FALSE) +
    geom_text(aes(label = sprintf("%.3f", mean_fold_pr_auc)), vjust = -0.35, size = 3.4) +
    labs(title = "A4 candidate comparison: mean blocked-fold PR-AUC", x = NULL, y = "Mean PR-AUC") +
    scale_y_continuous(limits = c(0, max(cmp_eval$mean_fold_pr_auc) * 1.15), expand = c(0, 0)),
  "candidate_pr_auc"
)

save_plot(
  ggplot(cmp_eval, aes(candidate, mean_brier_skill, fill = candidate)) +
    geom_col(width = 0.7, show.legend = FALSE) +
    geom_text(aes(label = sprintf("%.3f", mean_brier_skill)), vjust = -0.35, size = 3.4) +
    labs(title = "A4 candidate comparison: mean blocked-fold Brier skill", x = NULL, y = "Mean Brier skill") +
    scale_y_continuous(limits = c(0, max(cmp_eval$mean_brier_skill) * 1.15), expand = c(0, 0)),
  "candidate_brier_skill"
)

save_plot(
  ggplot(cmp_eval, aes(candidate, mean_joint_nll, fill = candidate)) +
    geom_col(width = 0.7, show.legend = FALSE) +
    geom_text(aes(label = sprintf("%.3f", mean_joint_nll)), vjust = -0.35, size = 3.4) +
    labs(title = "A4 candidate comparison: mean joint hurdle NLL", x = NULL, y = "Mean joint NLL (lower is better)") +
    scale_y_continuous(limits = c(0, max(cmp_eval$mean_joint_nll) * 1.15), expand = c(0, 0)),
  "candidate_joint_nll"
)

count_totals <- fold %>%
  group_by(candidate) %>%
  summarise(observed = sum(observed_total), predicted = sum(predicted_expected_total), .groups = "drop") %>%
  pivot_longer(c(observed, predicted), names_to = "quantity", values_to = "detections") %>%
  mutate(candidate = factor(candidate, levels = candidate_levels))
save_plot(
  ggplot(count_totals, aes(candidate, detections, fill = quantity)) +
    geom_col(position = position_dodge(width = 0.75), width = 0.68) +
    labs(title = "Blocked-fold observed versus expected detections", x = NULL, y = "Total detections", fill = NULL) +
    scale_fill_manual(values = c(observed = "#2C7FB8", predicted = "#F03B20"), labels = c(observed = "Observed", predicted = "Predicted expected")),
  "candidate_count_observed_vs_predicted"
)

save_plot(
  ggplot(spatial %>% filter(residual != "combined_expected_count"), aes(candidate, moran_i, fill = residual)) +
    geom_col(position = position_dodge(width = 0.75), width = 0.68) +
    geom_hline(yintercept = 0, linewidth = 0.3) +
    labs(title = "Out-of-fold residual spatial dependence", x = NULL, y = "Moran's I", fill = NULL) +
    scale_fill_manual(values = c(occurrence = "#1B9E77", positive_count = "#D95F02"), labels = c(occurrence = "Occurrence", positive_count = "Positive count")),
  "candidate_residual_moran_i"
)

save_plot(
  ggplot(spatial_map %>% filter(candidate != "A4-O"), aes(lon, lat, colour = occurrence_residual)) +
    geom_point(size = 0.08, alpha = 0.6) +
    facet_wrap(~candidate, ncol = 2) +
    scale_colour_gradient2(low = "#2166AC", mid = "white", high = "#B2182B", midpoint = 0) +
    coord_fixed() +
    labs(title = "Out-of-fold occurrence residual maps", x = "Longitude", y = "Latitude", colour = "Residual"),
  "residual_spatial_map",
  width = 8.0,
  height = 6.0
)

us_positive <- ranking %>% filter(row_type == "overall_positive_summary", !is.na(us_positive_node_weeks)) %>% summarise(n = sum(us_positive_node_weeks)) %>% pull(n)
us_plot <- ggplot() + theme_void() +
  labs(title = "U.S. positive risk ranking", subtitle = "Not assessable in pre-W30 blocked folds: zero U.S. positive node-weeks") +
  annotate("text", x = 0.5, y = 0.5, label = "No U.S. positive node-weeks\nin the A4 development folds", size = 5, colour = "#555555") +
  xlim(0, 1) + ylim(0, 1)
save_plot(us_plot, "us_top_k_capture", width = 7.2, height = 4.6)

extrap_plot_data <- extrap %>%
  filter(feature == "combined_history") %>%
  group_by(candidate, regime) %>%
  summarise(joint_nll = mean(joint_hurdle_nll), .groups = "drop") %>%
  mutate(candidate = factor(candidate, levels = candidate_levels), regime = factor(regime, levels = c("in_distribution", "moderate", "strong")))
save_plot(
  ggplot(extrap_plot_data, aes(regime, joint_nll, colour = candidate, group = candidate)) +
    geom_line(linewidth = 0.8) + geom_point(size = 2) +
    labs(title = "History-feature extrapolation performance", x = NULL, y = "Mean joint NLL", colour = NULL),
  "extrapolative_regime_performance"
)

save_plot(
  ggplot(cmp_eval, aes(effective_complexity, mean_fold_pr_auc, label = candidate, colour = candidate)) +
    geom_point(size = 3) + geom_text(nudge_y = 0.008, show.legend = FALSE) +
    scale_x_continuous(trans = "log1p", breaks = c(70, 71, 20144, 20145)) +
    labs(title = "Complexity versus mean PR-AUC", x = "Effective complexity (log scale)", y = "Mean PR-AUC", colour = NULL),
  "complexity_vs_performance"
)

write_csv(tibble(
  figure = c("candidate_pr_auc", "candidate_brier_skill", "candidate_joint_nll", "candidate_count_observed_vs_predicted", "candidate_residual_moran_i", "residual_spatial_map", "us_top_k_capture", "extrapolative_regime_performance", "complexity_vs_performance"),
  status = c(rep("rendered", 9)),
  note = c(rep("Static blocked-development diagnostic; no prospective W30-W39 values used.", 9))
), file.path(root, "figures", "figure_manifest.csv"))
