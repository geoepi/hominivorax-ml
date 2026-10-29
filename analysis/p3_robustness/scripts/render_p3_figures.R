#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("usage: render_p3_figures.R RESULTS FIGURES")
results <- args[[1]]
figures <- args[[2]]
dir.create(figures, recursive = TRUE, showWarnings = FALSE)

frontier <- read.csv(file.path(results, "frontier_sensitivity_metrics.csv"), stringsAsFactors = FALSE)
count_strata <- read.csv(file.path(results, "count_stratum_metrics.csv"), stringsAsFactors = FALSE)
partitions <- read.csv(file.path(results, "partition_sensitivity_metrics.csv"), stringsAsFactors = FALSE)
groups <- read.csv(file.path(results, "fit_group_stability.csv"), stringsAsFactors = FALSE)

png(file.path(figures, "P3-1_frontier_definition_robustness.png"), width = 1800, height = 1100, res = 160)
par(mar = c(10, 5, 4, 1))
f <- frontier[frontier$horizon == 1 & frontier$frontier_class != "newly_detected_frontier_positive", ]
f$key <- paste(f$definition, f$frontier_class, sep = "\n")
f$auprc[!is.finite(f$auprc)] <- NA
heights <- tapply(f$auprc, f$key, mean, na.rm = TRUE)
heights[!is.finite(heights)] <- 0
barplot(heights, las = 2, col = rep(c("#4472C4", "#ED7D31", "#70AD47"), length.out = length(heights)),
        ylab = "AUPRC", main = "P3-1 Frontier-definition robustness (h=1)")
dev.off()

png(file.path(figures, "P3-2_count_error_by_magnitude.png"), width = 1800, height = 1100, res = 160)
par(mfrow = c(1, 2), mar = c(8, 5, 4, 1))
c <- count_strata[count_strata$horizon == "all", ]
c <- c[match(c("low_1_2", "moderate_3_5", "high_6_10", "extreme_11_plus"), c$count_stratum), ]
barplot(c$absolute_error_contribution, names.arg = c$count_stratum, las = 2,
        col = "#5B9BD5", ylab = "Contribution to absolute error",
        main = "P3-2 Count error contribution")
barplot(c$mean_signed_error, names.arg = c$count_stratum, las = 2,
        col = ifelse(c$mean_signed_error >= 0, "#ED7D31", "#70AD47"),
        ylab = "Mean signed error (predicted - observed)",
        main = "Signed error by observed count")
dev.off()

png(file.path(figures, "P3-3_evaluation_partition_robustness.png"), width = 1900, height = 1200, res = 160)
par(mar = c(12, 5, 4, 1))
p <- partitions[partitions$horizon == 1, ]
p$key <- paste(p$partition_scheme, p$partition_group, sep = "\n")
ord <- order(p$partition_family, p$partition_scheme, p$partition_group)
plot(seq_len(nrow(p)), p$brier[ord], xaxt = "n", pch = 19,
     col = ifelse(p$partition_family[ord] == "spatial", "#4472C4", "#70AD47"),
     xlab = "Prespecified partition/group", ylab = "Brier score",
     main = "P3-3 Evaluation-partition robustness (h=1)")
axis(1, at = seq_len(nrow(p)), labels = p$key[ord], las = 2, cex.axis = 0.65)
legend("topright", legend = c("spatial", "temporal"), col = c("#4472C4", "#70AD47"), pch = 19, bty = "n")
dev.off()

png(file.path(figures, "P3-4_fit_stability.png"), width = 1900, height = 1200, res = 160)
par(mfrow = c(1, 2), mar = c(8, 5, 4, 1))
for (component in unique(groups$component)) {
  g <- groups[groups$component == component & groups$feature_group != "intercept", ]
  origins <- unique(g$origin_week)
  group_names <- unique(g$feature_group)
  ylim <- range(g$l2_norm, finite = TRUE)
  plot(seq_along(origins), rep(NA_real_, length(origins)), ylim = ylim,
       xaxt = "n", xlab = "Rolling origin", ylab = "Coefficient group L2 norm",
       main = paste("P3-4 Fit stability:", component))
  axis(1, at = seq_along(origins), labels = origins, las = 2, cex.axis = 0.65)
  for (i in seq_along(group_names)) {
    one <- g[g$feature_group == group_names[[i]], ]
    one <- one[match(origins, one$origin_week), ]
    lines(seq_along(origins), one$l2_norm, type = "b", pch = 16, col = i)
  }
  legend("topleft", legend = group_names, col = seq_along(group_names), lty = 1, pch = 16, bty = "n", cex = 0.8)
}
dev.off()

writeLines(c("status=PASS", "figures=P3-1,P3-2,P3-3,P3-4"), file.path(figures, "figure_generation_status.txt"))
