#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args)) normalizePath(args[[1]], mustWork = TRUE) else normalizePath(file.path("analysis", "p7g_manuscript_evidence"), mustWork = TRUE)
results <- file.path(root, "results")
figures <- file.path(root, "figures")
dir.create(figures, recursive = TRUE, showWarnings = FALSE)

write_plot <- function(stem, draw, width = 7.2, height = 5.0) {
  pdf(file.path(figures, paste0(stem, ".pdf")), width = width, height = height, useDingbats = FALSE)
  draw()
  dev.off()
  png(file.path(figures, paste0(stem, ".png")), width = round(width * 160), height = round(height * 160), res = 160)
  draw()
  dev.off()
}

spatial <- read.csv(file.path(results, "spatial_shell_dependence.csv"), stringsAsFactors = FALSE)
early <- read.csv(file.path(results, "early_warning_topk.csv"), stringsAsFactors = FALSE)
support <- read.csv(file.path(results, "support_horizon_calibration_metrics.csv"), stringsAsFactors = FALSE)
support_ci <- read.csv(file.path(results, "support_horizon_bootstrap_ci.csv"), stringsAsFactors = FALSE)
dep <- read.csv(file.path(results, "predictor_dependence_pairs.csv"), stringsAsFactors = FALSE)

cols <- c("#1B9E77", "#D95F02", "#7570B3")

write_plot("p7g_spatial_dependence", function() {
  par(mfrow = c(2, 2), mar = c(4, 4, 2, 1))
  for (h in 1:3) {
    x <- spatial[spatial$horizon == h & spatial$variable %in% c("raw_occurrence", "residual_occurrence"), ]
    x <- x[order(x$shell_order, x$variable), ]
    yraw <- x$moran_i[x$variable == "raw_occurrence"]
    yres <- x$moran_i[x$variable == "residual_occurrence"]
    plot(1:4, yraw, type = "o", pch = 16, col = cols[1], ylim = range(c(yraw, yres), finite = TRUE), xlab = "Queen-graph shell", ylab = "Moran's I", main = paste0("Occurrence dependence, h=", h), xaxt = "n")
    axis(1, at = 1:4, labels = 1:4)
    lines(1:4, yres, type = "o", pch = 17, col = cols[2])
    legend("topright", legend = c("raw occurrence", "occurrence residual"), col = cols[1:2], pch = c(16, 17), lty = 1, bty = "n", cex = 0.75)
  }
  plot.new(); text(0.5, 0.5, "P7G-A\nCanonical residual definitions\nNo new spatial validation", cex = 1.0)
})

write_plot("p7g_early_warning_capture", function() {
  x <- early[early$score == "p_occurrence" & early$status == "estimable", ]
  par(mfrow = c(1, 2), mar = c(4, 4, 2, 1))
  for (pool in c("FULL_DOMAIN", "FRONTIER_RELATIVE")) {
    y <- x[x$pool == pool, ]
    fractions <- sort(unique(y$top_fraction))
    yr <- range(y$capture_fraction, finite = TRUE)
    plot(fractions * 100, y$capture_fraction[y$horizon == 1][match(fractions, y$top_fraction[y$horizon == 1])], type = "o", pch = 16, col = cols[1], ylim = c(0, 1), xlab = "Top-ranked fraction (%)", ylab = "First-detection capture fraction", main = pool, xaxt = "n")
    axis(1, at = fractions * 100, labels = paste0(fractions * 100, "%"))
    for (h in 2:3) {
      z <- y[y$horizon == h, ]
      lines(z$top_fraction * 100, z$capture_fraction, type = "o", pch = 15 + h, col = cols[h])
    }
    legend("bottomright", legend = paste0("h=", 1:3), col = cols, pch = c(16, 17, 18), lty = 1, bty = "n", cex = 0.8)
  }
})

write_plot("p7g_support_calibration", function() {
  par(mfrow = c(1, 2), mar = c(4, 4, 2, 1))
  xpos <- seq_along(unique(support$support_class))
  classes <- c("SUPPORTED", "CAUTION", "EXTRAPOLATIVE")
  for (h in 1:3) {
    y <- support[support$horizon == h, ]
    y <- y[match(classes, y$support_class), ]
    b <- support_ci[support_ci$horizon == h, ]
    b <- b[match(classes, b$support_class), ]
    if (h == 1) {
      plot(xpos, y$brier, pch = 16, col = cols, ylim = range(c(b$brier_lower, b$brier_upper), finite = TRUE), xaxt = "n", xlab = "P4 support class", ylab = "Brier score", main = "Support-stratified calibration")
      axis(1, at = xpos, labels = classes, las = 2, cex.axis = 0.75)
    } else {
      points(xpos, y$brier, pch = 15 + h, col = cols)
    }
    arrows(xpos, b$brier_lower, xpos, b$brier_upper, angle = 90, code = 3, length = 0.04, col = "grey35")
  }
  legend("topleft", legend = paste0("h=", 1:3), pch = c(16, 17, 18), bty = "n", cex = 0.8)
  mat <- matrix(NA_real_, nrow = 3, ncol = 3, dimnames = list(classes, paste0("h=", 1:3)))
  for (h in 1:3) mat[, h] <- support$brier[support$horizon == h][match(classes, support$support_class[support$horizon == h])]
  image(1:3, 1:3, mat, axes = FALSE, col = hcl.colors(20, "YlOrRd", rev = TRUE), xlab = "Horizon", ylab = "P4 support class", main = "Brier score matrix")
  axis(1, at = 1:3, labels = paste0("h=", 1:3)); axis(2, at = 1:3, labels = classes, las = 2)
})

write_plot("p7g_predictor_dependence", function() {
  predictors <- sort(unique(c(dep$predictor_a, dep$predictor_b)))
  m <- diag(1, length(predictors)); dimnames(m) <- list(predictors, predictors)
  for (i in seq_len(nrow(dep))) {
    a <- match(dep$predictor_a[i], predictors); b <- match(dep$predictor_b[i], predictors)
    m[a, b] <- dep$pearson[i]; m[b, a] <- dep$pearson[i]
  }
  par(mar = c(10, 10, 2, 2))
  image(seq_along(predictors), seq_along(predictors), abs(m), axes = FALSE, col = hcl.colors(24, "Blue-Red 2", rev = TRUE), zlim = c(0, 1), xlab = "Predictor", ylab = "Predictor", main = "Absolute Pearson dependence\nP7G-C training reference")
  axis(1, at = seq_along(predictors), labels = predictors, las = 2, cex.axis = 0.55)
  axis(2, at = seq_along(predictors), labels = predictors, las = 2, cex.axis = 0.55)
})

writeLines(c(
  "P7G figures are compact diagnostic displays generated from canonical P7G result tables.",
  "They are not manuscript prose and do not introduce new model fitting or importance methods."
), file.path(figures, "README.md"))
