#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) stop("usage: render_p2_figures.R <results-dir> <figures-dir>")
results_dir <- normalizePath(args[[1]], mustWork = TRUE)
figures_dir <- args[[2]]
dir.create(figures_dir, recursive = TRUE, showWarnings = FALSE)

horizon <- read.csv(file.path(results_dir, "horizon_metrics.csv"), stringsAsFactors = FALSE)
bins <- read.csv(file.path(results_dir, "calibration_bins.csv"), stringsAsFactors = FALSE)
frontier <- read.csv(file.path(results_dir, "frontier_metrics.csv"), stringsAsFactors = FALSE)
reference <- read.csv(file.path(results_dir, "reference_metrics.csv"), stringsAsFactors = FALSE)

save_plot <- function(path, expr) {
  png(path, width = 1400, height = 900, res = 150)
  on.exit(dev.off(), add = TRUE)
  par(mar = c(5, 5, 3, 2) + 0.1, family = "sans")
  force(expr)
}

# P2-1: the operational rolling-origin geometry.
save_plot(file.path(figures_dir, "P2-1_rolling_origin_design.png"), {
  plot(c(0, 12), c(0, 4), type = "n", axes = FALSE, xlab = "Weekly position", ylab = "", main = "P2 operational rolling-origin design")
  axis(1, at = c(0, 4, 8, 12), labels = c("T-2", "T", "T+2", "T+4"))
  axis(2, at = c(1, 2, 3), labels = c("Training through T", "h=1..3 target window", "Next weekly origin"), las = 1)
  box()
  segments(0, 1, 5, 1, lwd = 8, col = "#2C7FB8")
  segments(5, 2, 8, 2, lwd = 8, col = "#F28E2B")
  segments(1, 3, 6, 3, lwd = 8, col = "#2C7FB8")
  segments(6, 2.7, 9, 2.7, lwd = 8, col = "#F28E2B")
  points(c(5, 6), c(1, 3), pch = 16, cex = 1.5)
  text(c(5, 6), c(1.35, 3.35), c("origin T", "origin T+1"), pos = 4)
  text(6.5, 2.3, "primary horizon stops at T+3", col = "#B2182B")
})

# P2-2: occurrence reliability by horizon.
occ <- bins[bins$metric_family == "occurrence" & bins$scope == "all" & bins$n > 0, ]
save_plot(file.path(figures_dir, "P2-2_occurrence_reliability_by_horizon.png"), {
  plot(c(0, 1), c(0, 1), type = "n", xlab = "Mean predicted occurrence probability", ylab = "Observed occurrence frequency", main = "Occurrence reliability by horizon")
  abline(0, 1, lty = 2, col = "grey40")
  cols <- c("#1B9E77", "#D95F02", "#7570B3")
  for (i in seq_along(c(1, 2, 3))) {
    sub <- occ[occ$horizon == i, ]
    if (nrow(sub)) {
      points(sub$mean_predicted, sub$observed_probability, pch = 16, col = cols[[i]])
      arrows(sub$mean_predicted, pmax(0, sub$observed_probability - 1.96 * sub$observed_se), sub$mean_predicted, pmin(1, sub$observed_probability + 1.96 * sub$observed_se), angle = 90, code = 3, length = 0.03, col = cols[[i]])
      lines(sub$mean_predicted, sub$observed_probability, col = cols[[i]])
    }
  }
  legend("topleft", legend = paste0("h=", 1:3), col = cols, lty = 1, pch = 16, bty = "n")
})

# P2-3: bounded horizon performance summary.
primary <- horizon[horizon$scope == "all" & horizon$horizon %in% c(1, 2, 3), ]
save_plot(file.path(figures_dir, "P2-3_performance_vs_horizon.png"), {
  par(mfrow = c(1, 2))
  plot(primary$horizon, primary$brier, type = "b", pch = 16, xaxt = "n", xlab = "Horizon", ylab = "Brier score", main = "Occurrence error")
  axis(1, at = 1:3, labels = paste0("h=", 1:3))
  plot(primary$horizon, primary$calibration_slope, type = "b", pch = 16, xaxt = "n", xlab = "Horizon", ylab = "Calibration slope", main = "Diagnostic calibration slope")
  axis(1, at = 1:3, labels = paste0("h=", 1:3))
  abline(h = 1, lty = 2, col = "grey40")
})

# P2-4: frontier calibration contrast.
front_plot <- frontier[frontier$frontier_class %in% c("previously_occupied", "previously_unoccupied") & frontier$horizon %in% c(1, 2, 3), ]
save_plot(file.path(figures_dir, "P2-4_frontier_calibration.png"), {
  if (nrow(front_plot)) {
    classes <- unique(front_plot$frontier_class)
    cols <- c("#2166AC", "#B2182B")
    ylim <- range(front_plot$brier[is.finite(front_plot$brier)], na.rm = TRUE)
    plot(NA, xlim = c(1, 3), ylim = if (all(is.finite(ylim))) ylim else c(0, 1), xaxt = "n", xlab = "Horizon", ylab = "Brier score", main = "Frontier-stratified occurrence calibration")
    axis(1, at = 1:3, labels = paste0("h=", 1:3))
    for (i in seq_along(classes)) {
      sub <- front_plot[front_plot$frontier_class == classes[[i]], ]
      points(sub$horizon, sub$brier, type = "b", pch = 16, col = cols[[i]])
    }
    legend("topleft", legend = classes, col = cols[seq_along(classes)], lty = 1, pch = 16, bty = "n")
  }
})

# P2-5: count calibration for the two hurdle quantities.
count_bins <- bins[bins$metric_family %in% c("conditional_count", "full_expected_count") & bins$horizon == "all" & bins$n > 0, ]
save_plot(file.path(figures_dir, "P2-5_count_calibration.png"), {
  par(mfrow = c(1, 2))
  for (family in c("conditional_count", "full_expected_count")) {
    sub <- count_bins[count_bins$metric_family == family & is.finite(count_bins$mean_observed), ]
    if (nrow(sub)) {
      plot(sub$mean_predicted, sub$mean_observed, log = "xy", pch = 16, xlab = "Mean predicted", ylab = "Mean observed", main = family)
      abline(0, 1, lty = 2, col = "grey40")
    } else {
      plot.new(); title(main = paste(family, "not estimable"))
    }
  }
})

# P2-6: A3 versus the two minimal references.
save_plot(file.path(figures_dir, "P2-6_a3_vs_minimal_references.png"), {
  refs <- unique(reference$reference)
  mat <- t(sapply(refs, function(ref) reference$brier[reference$reference == ref]))
  matplot(1:3, rbind(reference$a3_brier[reference$reference == refs[[1]]], mat), type = "b", pch = 16, lty = 1, xaxt = "n", xlab = "Horizon", ylab = "Brier score", main = "A3 versus minimal references", col = c("black", "#1B9E77", "#D95F02"))
  axis(1, at = 1:3, labels = paste0("h=", 1:3))
  legend("topleft", legend = c("A3", refs), col = c("black", "#1B9E77", "#D95F02"), lty = 1, pch = 16, bty = "n")
})

writeLines(c("status=PASS", "figures=P2-1..P2-6", "uncertainty=reported in bootstrap_intervals.csv"), file.path(figures_dir, "figure_generation_status.txt"))
