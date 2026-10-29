#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) stop("usage: render_p1_figures.R <analysis/p1_production_validation>")
root <- normalizePath(args[[1L]], mustWork = TRUE)
results <- file.path(root, "results")
figures <- file.path(root, "figures")
dir.create(figures, recursive = TRUE, showWarnings = FALSE)
metrics <- read.csv(file.path(results, "validation_metrics.csv"), stringsAsFactors = FALSE)
boot <- read.csv(file.path(results, "bootstrap_intervals.csv"), stringsAsFactors = FALSE)
front <- read.csv(file.path(results, "frontier_metrics.csv"), stringsAsFactors = FALSE)
metrics$value <- as.numeric(metrics$value)
boot$estimate <- as.numeric(boot$estimate)
boot$lower_95 <- as.numeric(boot$lower_95)
boot$upper_95 <- as.numeric(boot$upper_95)
front$mean_predicted_probability <- as.numeric(front$mean_predicted_probability)
front$n_node_weeks <- as.numeric(front$n_node_weeks)
front$positive_node_weeks <- as.numeric(front$positive_node_weeks)

png(file.path(figures, "p1_temporal_metrics.png"), width = 1400, height = 900, res = 150)
par(mfrow = c(2, 1), mar = c(5, 5, 3, 2))
weekly <- metrics[metrics$regime == "temporal_week" & metrics$metric %in% c("pr_auc", "roc_auc"), ]
weeks <- unique(weekly$subset)
ylim <- range(weekly$value, finite = TRUE)
plot(seq_along(weeks), rep(NA_real_, length(weeks)), type = "n", xaxt = "n", ylim = ylim,
     xlab = "Post-fit week", ylab = "Discrimination", main = "Exact frozen STRUCTURED_A3: weekly discrimination")
axis(1, at = seq_along(weeks), labels = weeks, las = 2, cex.axis = 0.7)
for (metric in c("pr_auc", "roc_auc")) {
  x <- weekly[weekly$metric == metric, ]
  x <- x[match(weeks, x$subset), ]
  lines(seq_along(weeks), x$value, type = "b", pch = if (metric == "pr_auc") 16 else 17,
        col = if (metric == "pr_auc") "#0072B2" else "#D55E00")
}
legend("topright", legend = c("PR-AUC", "ROC-AUC"), pch = c(16, 17),
       col = c("#0072B2", "#D55E00"), bty = "n")
temporal_boot <- boot[boot$regime == "temporal" & boot$metric %in% c("pr_auc", "roc_auc"), ]
plot(seq_along(temporal_boot$metric), temporal_boot$estimate, pch = 19,
     ylim = range(c(temporal_boot$lower_95, temporal_boot$upper_95), finite = TRUE),
     xaxt = "n", xlab = "Metric", ylab = "Estimate with 95% block interval",
     main = "Post-fit pooled metrics: ordered two-week block bootstrap")
axis(1, at = seq_along(temporal_boot$metric), labels = temporal_boot$metric)
arrows(seq_along(temporal_boot$metric), temporal_boot$lower_95,
       seq_along(temporal_boot$metric), temporal_boot$upper_95,
       angle = 90, code = 3, length = 0.05)
dev.off()

png(file.path(figures, "p1_spatial_metrics.png"), width = 1400, height = 900, res = 150)
par(mar = c(8, 5, 3, 2))
spatial <- metrics[metrics$regime == "spatial" & metrics$metric %in% c("pr_auc", "brier_skill"), ]
regions <- unique(spatial$subset)
mat <- matrix(NA_real_, nrow = length(regions), ncol = 2, dimnames = list(regions, c("PR-AUC", "Brier skill")))
for (i in seq_len(nrow(spatial))) {
  mat[spatial$subset[i], ifelse(spatial$metric[i] == "pr_auc", 1, 2)] <- spatial$value[i]
}
barplot(t(mat), beside = TRUE, las = 2, col = c("#0072B2", "#009E73"),
        ylab = "Metric value", main = "Geographic transfer by canonical region")
legend("topright", legend = colnames(mat), fill = c("#0072B2", "#009E73"), bty = "n")
dev.off()

png(file.path(figures, "p1_frontier_metrics.png"), width = 1400, height = 900, res = 150)
par(mar = c(9, 5, 3, 2))
categories <- front$category
observed <- front$positive_node_weeks
predicted <- front$mean_predicted_probability * front$n_node_weeks
barplot(rbind(observed, predicted), beside = TRUE, names.arg = categories, las = 2,
        col = c("#CC79A7", "#56B4E9"), ylab = "Node-weeks / expected positive node-weeks",
        main = "Causal prior-history frontier strata")
legend("topright", legend = c("Observed positive node-weeks", "Expected positive node-weeks"),
       fill = c("#CC79A7", "#56B4E9"), bty = "n")
dev.off()

cat("P1_FIGURES_RENDERED\n")

