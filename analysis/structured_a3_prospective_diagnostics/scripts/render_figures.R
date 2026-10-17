#!/usr/bin/env Rscript

# Render the eight publication figures from compact diagnostic tables.

suppressPackageStartupMessages({
  library(ggplot2)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) {
  stop("usage: render_figures.R OUTPUT_ROOT")
}
root <- normalizePath(args[[1]], mustWork = TRUE)
results <- file.path(root, "results")
figures <- file.path(root, "figures")
dir.create(figures, recursive = TRUE, showWarnings = FALSE)

save_plot <- function(plot, stem, width = 8, height = 5) {
  ggsave(file.path(figures, paste0(stem, ".png")), plot, width = width, height = height, units = "in", dpi = 300, bg = "white")
  ggsave(file.path(figures, paste0(stem, ".pdf")), plot, width = width, height = height, units = "in", device = cairo_pdf, bg = "white")
}

long_metrics <- function(data, columns, key = "week") {
  do.call(rbind, lapply(columns, function(column) {
    data.frame(
      key = data[[key]],
      metric = column,
      value = data[[column]],
      stringsAsFactors = FALSE
    )
  }))
}

comparison <- read.csv(file.path(results, "prospective_vs_terminal_metrics.csv"), stringsAsFactors = FALSE)
full <- comparison[comparison$region == "full_domain" & comparison$metric %in% c("brier_skill", "pr_auc", "roc_auc", "joint_hurdle_nll"), ]
comparison_long <- rbind(
  data.frame(metric = full$metric, source = "Terminal", value = full$terminal_value),
  data.frame(metric = full$metric, source = "Prospective", value = full$prospective_value)
)
p <- ggplot(comparison_long, aes(source, value, fill = source)) +
  geom_col(width = 0.65) +
  facet_wrap(~metric, scales = "free_y") +
  scale_fill_manual(values = c(Terminal = "grey55", Prospective = "#2171b5")) +
  labs(x = NULL, y = "Metric value", title = "Prospective versus prior terminal metrics") +
  theme_minimal(base_size = 10) + theme(legend.position = "none", axis.text.x = element_text(angle = 20, hjust = 1))
save_plot(p, "01_prospective_vs_terminal_metrics", 8.5, 6)

weekly <- read.csv(file.path(results, "weekly_metrics.csv"), stringsAsFactors = FALSE)
weekly_long <- long_metrics(weekly, c("prevalence", "brier_skill", "pr_auc", "joint_hurdle_nll"))
p <- ggplot(weekly_long, aes(key, value, group = 1)) +
  geom_line(color = "#2171b5") + geom_point(color = "#2171b5") +
  facet_wrap(~metric, scales = "free_y", ncol = 2) +
  labs(x = "Prospective week", y = "Metric value", title = "Weekly prospective performance") +
  theme_minimal(base_size = 10) + theme(axis.text.x = element_text(angle = 45, hjust = 1))
save_plot(p, "02_weekly_performance_trajectory", 8.5, 6)

calibration <- read.csv(file.path(results, "calibration_summary.csv"), stringsAsFactors = FALSE)
cal <- calibration[calibration$row_type == "bin" & calibration$binning == "equal_frequency", ]
p <- ggplot(cal, aes(mean_predicted, observed_fraction)) +
  geom_abline(slope = 1, intercept = 0, linetype = "dashed", color = "grey45") +
  geom_line(color = "#cb181d") + geom_point(color = "#cb181d") +
  facet_wrap(~region, scales = "free") +
  labs(x = "Mean predicted probability", y = "Observed fraction", title = "Equal-frequency reliability curves") +
  theme_minimal(base_size = 10)
save_plot(p, "03_reliability_calibration", 10, 3.7)

geography <- read.csv(file.path(results, "geographic_strata_metrics.csv"), stringsAsFactors = FALSE)
latitude <- geography[geography$stratum_type == "latitude", ]
latitude_long <- long_metrics(latitude, c("brier", "pr_auc", "joint_hurdle_nll"), key = "stratum")
latitude_long <- latitude_long[is.finite(latitude_long$value), ]
latitude_long$metric <- factor(latitude_long$metric, levels = c("brier", "pr_auc", "joint_hurdle_nll"))
p <- ggplot(latitude_long, aes(key, value, group = 1)) +
  geom_line(color = "#238b45") + geom_point(color = "#238b45") +
  facet_wrap(~metric, scales = "free_y") +
  labs(x = "Latitude band", y = "Metric value", title = "Latitude-band prospective performance") +
  theme_minimal(base_size = 10) + theme(axis.text.x = element_text(angle = 45, hjust = 1))
save_plot(p, "04_latitude_band_performance", 10, 3.7)

rank <- read.csv(file.path(results, "us_risk_ranking.csv"), stringsAsFactors = FALSE)
rank <- rank[rank$row_type == "overall_top_k", ]
rank_long <- rbind(
  data.frame(top_k = rank$top_k, metric = "Recall / capture", value = 100 * rank$recall),
  data.frame(top_k = rank$top_k, metric = "Precision", value = 100 * rank$precision)
)
rank_long <- rank_long[is.finite(rank_long$value), ]
rank_long$label <- factor(paste0(100 * rank_long$top_k, "%"), levels = paste0(100 * rank$top_k, "%"))
p <- ggplot(rank_long, aes(label, value, group = metric, color = metric)) +
  geom_line() + geom_point() + scale_y_continuous(limits = c(0, 100)) +
  scale_color_manual(values = c("Recall / capture" = "#2171b5", Precision = "#cb181d")) +
  labs(x = "Top-k fraction of U.S. nodes", y = "Percent", title = "U.S. risk-rank capture and precision") +
  theme_minimal(base_size = 10)
save_plot(p, "05_us_risk_rank_capture", 7, 4.5)

front <- read.csv(file.path(results, "front_distance_metrics.csv"), stringsAsFactors = FALSE)
front <- front[is.finite(front$joint_hurdle_nll), ]
p <- ggplot(front, aes(stratum, joint_hurdle_nll, group = 1)) +
  geom_line(color = "#6a51a3") + geom_point(color = "#6a51a3") +
  facet_wrap(~front_feature, scales = "free_x", nrow = 1) +
  labs(x = "Front/history stratum", y = "Joint hurdle NLL", title = "Performance by front distance and recency") +
  theme_minimal(base_size = 10) + theme(axis.text.x = element_text(angle = 60, hjust = 1))
save_plot(p, "06_front_distance_performance", 11, 4.2)

residual_map <- read.csv(file.path(results, "spatial_residual_map_data.csv"), stringsAsFactors = FALSE)
limit <- quantile(abs(residual_map$pooled_combined_expected_count_residual), 0.99, na.rm = TRUE)
p <- ggplot(residual_map, aes(lon, lat, color = pooled_combined_expected_count_residual)) +
  geom_point(size = 0.7) + scale_color_gradient2(low = "#2166ac", mid = "white", high = "#b2182b", limits = c(-limit, limit), oob = scales::squish) +
  coord_equal() + labs(x = "Longitude", y = "Latitude", color = "Observed − expected", title = "Pooled combined expected-count residual") +
  theme_minimal(base_size = 10)
save_plot(p, "07_spatial_residual_map", 7.2, 5.2)

weekly_long <- rbind(
  data.frame(week = weekly$week, metric = "Observed", value = weekly$observed_detections),
  data.frame(week = weekly$week, metric = "Expected", value = weekly$predicted_detections)
)
p <- ggplot(weekly_long, aes(week, value, group = metric, color = metric)) +
  geom_line() + geom_point() + scale_color_manual(values = c(Observed = "#252525", Expected = "#2171b5")) +
  labs(x = "Week", y = "Detections", title = "Observed and expected detections by week") +
  theme_minimal(base_size = 10) + theme(axis.text.x = element_text(angle = 45, hjust = 1))
save_plot(p, "08_observed_vs_predicted_by_week", 8, 4.5)

cat("Rendered eight diagnostic figure pairs to", figures, "\n")
