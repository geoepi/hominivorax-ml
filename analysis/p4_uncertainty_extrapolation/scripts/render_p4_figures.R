#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("usage: render_p4_figures.R RESULTS FIGURES")
results <- args[[1]]
figures <- args[[2]]
dir.create(figures, recursive = TRUE, showWarnings = FALSE)

support <- read.csv(file.path(results, "representative_support_map.csv"), stringsAsFactors = FALSE)
novelty <- read.csv(file.path(results, "performance_by_novelty.csv"), stringsAsFactors = FALSE)
coverage <- read.csv(file.path(results, "count_interval_coverage.csv"), stringsAsFactors = FALSE)
frontier <- read.csv(file.path(results, "frontier_support_metrics.csv"), stringsAsFactors = FALSE)
uncertainty <- read.csv(file.path(results, "representative_uncertainty_map.csv"), stringsAsFactors = FALSE)
support_cols <- c(SUPPORTED = "#2C7FB8", CAUTION = "#FDAE61", EXTRAPOLATIVE = "#D7191C")

png(file.path(figures, "P4-1_environmental_novelty_map.png"), width = 1800, height = 1300, res = 160)
plot(support$lon, support$lat, pch = 16, cex = 0.25, col = support_cols[support$support_class],
     xlab = "Longitude", ylab = "Latitude", main = "P4-1 Environmental support classification")
legend("bottomleft", legend = names(support_cols), col = support_cols, pch = 16, bty = "n")
dev.off()

png(file.path(figures, "P4-2_novelty_vs_occurrence_performance.png"), width = 1800, height = 1100, res = 160)
par(mar = c(10, 5, 4, 1))
bins <- unique(novelty$novelty_bin)
plot(seq_along(bins), rep(NA_real_, length(bins)), xaxt = "n", ylim = range(novelty$brier, finite = TRUE),
     xlab = "Fixed training-distance novelty bin", ylab = "Brier score", main = "P4-2 Novelty versus occurrence performance")
axis(1, at = seq_along(bins), labels = bins, las = 2, cex.axis = 0.7)
for (h in sort(unique(novelty$horizon))) {
  one <- novelty[novelty$horizon == h, ]
  one <- one[match(bins, one$novelty_bin), ]
  lines(seq_along(bins), one$brier, type = "b", pch = 16, col = h)
}
legend("topleft", legend = paste0("h=", sort(unique(novelty$horizon))), col = sort(unique(novelty$horizon)), lty = 1, pch = 16, bty = "n")
dev.off()

png(file.path(figures, "P4-3_model_uncertainty_map.png"), width = 1800, height = 1300, res = 160)
plot(uncertainty$lon, uncertainty$lat, pch = 16, cex = 0.3, col = heat.colors(100)[cut(uncertainty$p_boot_sd, breaks = 100, include.lowest = TRUE)],
     xlab = "Longitude", ylab = "Latitude", main = "P4-3 Bootstrap occurrence-probability uncertainty")
dev.off()

png(file.path(figures, "P4-4_count_interval_coverage.png"), width = 1500, height = 1100, res = 160)
pooled <- coverage[coverage$scope == "all", ]
plot(c(0, 1), c(0, 1), type = "n", xlab = "Nominal coverage", ylab = "Empirical coverage", main = "P4-4 Count predictive interval coverage")
abline(0, 1, lty = 2)
for (h in sort(unique(pooled$horizon))) {
  one <- pooled[pooled$horizon == h, ]
  lines(one$nominal_level, one$full_interval_coverage, type = "b", pch = 16, col = h)
}
legend("topleft", legend = paste0("h=", sort(unique(pooled$horizon))), col = sort(unique(pooled$horizon)), lty = 1, pch = 16, bty = "n")
dev.off()

png(file.path(figures, "P4-5_frontier_support.png"), width = 1800, height = 1100, res = 160)
one <- frontier[frontier$horizon == 1, ]
keys <- paste(one$frontier_group, one$support_tier, sep = " / ")
barplot(one$brier, names.arg = keys, las = 2, col = c("#4472C4", "#ED7D31", "#70AD47", "#A5A5A5"),
        ylab = "Brier score", main = "P4-5 Frontier × support (h=1)")
dev.off()

png(file.path(figures, "P4-6_production_support_classification.png"), width = 1800, height = 1300, res = 160)
plot(support$lon, support$lat, pch = 16, cex = 0.25, col = support_cols[support$support_class],
     xlab = "Longitude", ylab = "Latitude", main = "P4-6 Production support classification")
legend("bottomleft", legend = names(support_cols), col = support_cols, pch = 16, bty = "n")
dev.off()

writeLines(c("status=PASS", "figures=P4-1,P4-2,P4-3,P4-4,P4-5,P4-6"), file.path(figures, "figure_generation_status.txt"))
