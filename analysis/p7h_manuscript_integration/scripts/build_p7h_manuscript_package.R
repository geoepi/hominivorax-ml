#!/usr/bin/env Rscript

# P7H manuscript-evidence integration. This script runs the canonical P7
# publication build, then adds only source-traceable P7G evidence. It never
# fits, refits, tunes, recalibrates, or regenerates predictions.
options(stringsAsFactors = FALSE, scipen = 999)

args <- commandArgs(trailingOnly = TRUE)
arg_value <- function(flag, default = NULL) {
  i <- match(flag, args)
  if (is.na(i) || i == length(args)) return(default)
  args[[i + 1L]]
}
repo_root <- normalizePath(arg_value("--repo-root", getwd()), mustWork = TRUE)
verify_only <- "--verify-only" %in% args
skip_base <- "--skip-base" %in% args

stopf <- function(...) stop(sprintf(...), call. = FALSE)
abs_path <- function(x) file.path(repo_root, x)
rel_path <- function(path) {
  path <- normalizePath(path, winslash = "/", mustWork = FALSE)
  root <- normalizePath(repo_root, winslash = "/", mustWork = TRUE)
  prefix <- paste0(root, "/")
  if (startsWith(tolower(path), tolower(prefix))) return(substring(path, nchar(prefix) + 1L))
  path
}
sha256_file <- function(path) {
  if (!file.exists(path)) stopf("Missing file for hashing: %s", rel_path(path))
  tolower(digest::digest(file = path, algo = "sha256"))
}
read_json <- function(path) {
  if (!file.exists(abs_path(path))) stopf("Missing JSON source: %s", path)
  jsonlite::fromJSON(abs_path(path), simplifyVector = FALSE)
}
read_csv <- function(path, check.names = FALSE) {
  if (!file.exists(abs_path(path))) stopf("Missing CSV source: %s", path)
  utils::read.csv(abs_path(path), check.names = check.names,
                  stringsAsFactors = FALSE, na.strings = c("", "NA"))
}
atomic_lines <- function(lines, path) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  tmp <- paste0(path, ".tmp")
  if (file.exists(tmp)) unlink(tmp)
  con <- file(tmp, open = "wb")
  writeBin(charToRaw(paste0(enc2utf8(paste(lines, collapse = "\n")), "\n")), con)
  close(con)
  if (file.exists(path)) unlink(path)
  if (!file.rename(tmp, path)) stopf("Atomic rename failed: %s", rel_path(path))
}
atomic_csv <- function(data, path) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  tmp <- paste0(path, ".tmp")
  if (file.exists(tmp)) unlink(tmp)
  utils::write.table(data, tmp, sep = ",", row.names = FALSE, quote = TRUE,
                    na = "", eol = "\n", qmethod = "double", fileEncoding = "UTF-8")
  # Windows text-mode connections can translate LF to CRLF. Normalize the
  # temporary bytes before the atomic rename so tracked CSVs pass repository
  # hygiene checks consistently across hosts.
  raw <- readBin(tmp, what = "raw", n = file.info(tmp)$size)
  raw <- raw[raw != as.raw(13)]
  tmp_lf <- paste0(tmp, ".lf")
  if (file.exists(tmp_lf)) unlink(tmp_lf)
  writeBin(raw, tmp_lf)
  unlink(tmp)
  if (!file.rename(tmp_lf, tmp)) stopf("Could not normalize CSV line endings: %s", rel_path(path))
  if (file.exists(path)) unlink(path)
  if (!file.rename(tmp, path)) stopf("Atomic CSV rename failed: %s", rel_path(path))
}
atomic_json <- function(object, path) {
  atomic_lines(strsplit(as.character(jsonlite::toJSON(object, pretty = TRUE,
                                                        auto_unbox = TRUE,
                                                        null = "null", na = "null",
                                                        digits = 17)), "\n", fixed = TRUE)[[1L]], path)
}
copy_checked <- function(source, destination) {
  if (!file.exists(abs_path(source))) stopf("Missing copy source: %s", source)
  dir.create(dirname(abs_path(destination)), recursive = TRUE, showWarnings = FALSE)
  if (!file.copy(abs_path(source), abs_path(destination), overwrite = TRUE)) {
    stopf("Could not copy %s to %s", source, destination)
  }
  if (grepl("\\.svg$", destination, ignore.case = TRUE)) {
    raw <- readBin(abs_path(destination), what = "raw", n = file.info(abs_path(destination))$size)
    raw <- raw[raw != as.raw(13)]
    writeBin(raw, abs_path(destination))
  }
}
fmt4 <- function(x) sprintf("%.4f", as.numeric(x))
fmt_pct <- function(x) sprintf("%.1f%%", 100 * as.numeric(x))
raw_num <- function(x) sprintf("%.17g", as.numeric(x))

if (!requireNamespace("jsonlite", quietly = TRUE)) stopf("jsonlite is required")
if (!requireNamespace("digest", quietly = TRUE)) stopf("digest is required")

for (d in c("analysis/p7h_manuscript_integration/results",
            "analysis/p7h_manuscript_integration/figures",
            "analysis/p7_publication/supplement",
            "analysis/p7f_final_figures/figures/archive")) {
  dir.create(abs_path(d), recursive = TRUE, showWarnings = FALSE)
}

# The canonical P7 builder is the first stage of every non-verification run.
if (!verify_only && !skip_base) {
  rscript <- file.path(R.home("bin"), "Rscript")
  if (!file.exists(rscript)) rscript <- file.path(R.home("bin"), "Rscript.exe")
  status <- system2(rscript, c(abs_path("analysis/p7_publication/scripts/build_publication_artifacts.R"),
                               "--repo-root", repo_root))
  if (!identical(status, 0L)) stopf("Canonical P7 publication build failed with status %s", status)
}

# Immutable starting-state checks.
model_hash <- sha256_file(abs_path("analysis/structured_a3_evaluation/results/final_a3_model.json"))
if (!identical(model_hash, "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e")) {
  stopf("Frozen model hash mismatch: %s", model_hash)
}
p6_config <- read_json("config/p6_production_config.json")
if (!identical(p6_config$scientific_model$model_id, "STRUCTURED_A3") ||
    !identical(p6_config$operational_contract$proxy_id, "E0_LAST_AVAILABLE")) {
  stopf("P6 production configuration does not match the qualified specification")
}
p7g_decision <- read_json("analysis/p7g_manuscript_evidence/results/decision.json")
if (!identical(p7g_decision$decision, "P7G_MANUSCRIPT_EVIDENCE_COMPLETE_WITH_LIMITATIONS") ||
    !identical(isTRUE(p7g_decision$no_model_fitting), TRUE)) {
  stopf("P7G decision/no-model-fitting contract failed")
}
p7g_manifest <- read_json("analysis/p7g_manuscript_evidence/results/p7g_reproducibility_manifest.json")
if (!identical(p7g_manifest$frozen_model_sha256, model_hash) ||
    !identical(p7g_manifest$p2_archive_sha256,
               "918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170") ||
    !identical(p7g_manifest$p4_support_sha256,
               "c35bf794fcc882e3ea71bc1a279b90e4f32aeff412a9399f2fb25e383141d058")) {
  stopf("P7G source-hash contract failed")
}

# Verify every tracked P7G artifact in the canonical P7G manifest before use.
for (artifact in p7g_manifest$artifacts) {
  path <- artifact$path
  if (!file.exists(abs_path(path))) stopf("P7G manifest artifact is missing: %s", path)
  observed <- sha256_file(abs_path(path))
  if (!identical(observed, artifact$sha256)) {
    stopf("P7G artifact hash mismatch for %s: %s != %s", path, observed, artifact$sha256)
  }
}

p7g <- "analysis/p7g_manuscript_evidence/results/"
spatial <- read_csv(paste0(p7g, "spatial_shell_dependence.csv"))
temporal <- read_csv(paste0(p7g, "temporal_dependence.csv"))
early <- read_csv(paste0(p7g, "early_warning_topk.csv"))
dep_pairs <- read_csv(paste0(p7g, "predictor_dependence_pairs.csv"))
dep_summary <- read_csv(paste0(p7g, "predictor_dependence_summary.csv"))
assoc <- read_csv(paste0(p7g, "predictor_standardized_associations.csv"))
support_prop <- read_csv(paste0(p7g, "support_class_proportions.csv"))
support_metrics <- read_csv(paste0(p7g, "support_horizon_calibration_metrics.csv"))
support_ci <- read_csv(paste0(p7g, "support_horizon_bootstrap_ci.csv"))

required <- list(
  spatial = c("scope", "horizon", "shell_order", "variable", "moran_i"),
  temporal = c("horizon", "lag_weeks", "variable", "scope", "correlation"),
  early = c("horizon", "pool", "score", "top_fraction", "event_n", "captured_n", "capture_fraction"),
  dep_pairs = c("predictor_a", "predictor_b", "pearson", "spearman"),
  dep_summary = c("threshold_abs_correlation", "pair_count"),
  assoc = c("predictor", "component", "category", "scaled_in_fitted_model", "coefficient",
            "coefficient_contrast", "odds_or_mean_parameter_ratio"),
  support_prop = c("support_class", "n", "proportion"),
  support_metrics = c("horizon", "support_class", "n", "positives", "brier", "auprc"),
  support_ci = c("horizon", "support_class", "bootstrap_replicates", "brier_lower", "brier_upper",
                 "auprc_lower", "auprc_upper"))
for (nm in names(required)) {
  x <- get(nm)
  missing <- setdiff(required[[nm]], names(x))
  if (length(missing)) stopf("P7G schema failure for %s: %s", nm, paste(missing, collapse = ", "))
}

# Exact numerical traceability table used by the integrated prose and reviewer audit.
trace <- data.frame(metric_id = character(), source_artifact = character(), filter = character(),
                    value = character(), units = character(), interpretation = character(),
                    stringsAsFactors = FALSE)
add_trace <- function(id, source, filter, value, units, interpretation) {
  trace <<- rbind(trace, data.frame(metric_id = id, source_artifact = source,
                                    filter = filter, value = raw_num(value), units = units,
                                    interpretation = interpretation,
                                    stringsAsFactors = FALSE))
}
for (h in 1:3) {
  for (variable in c("raw_occurrence", "residual_occurrence")) {
    for (shell in c(1, 4)) {
      row <- spatial[spatial$scope == "pooled_node_mean" & as.integer(spatial$horizon) == h &
                       spatial$variable == variable & as.integer(spatial$shell_order) == shell, , drop = FALSE]
      if (nrow(row) != 1L) stopf("Missing spatial trace row")
      add_trace(paste("spatial", variable, paste0("h", h), paste0("shell", shell), sep = "_"),
                paste0(p7g, "spatial_shell_dependence.csv"),
                paste0("scope=pooled_node_mean,horizon=", h, ",variable=", variable,
                       ",shell_order=", shell), row$moran_i, "association",
                "Pooled node-mean spatial shell diagnostic")
    }
  }
  for (variable in c("raw_occurrence", "residual_occurrence")) {
    for (lag in c(1, 3)) {
      row <- temporal[temporal$scope == "pooled" & as.integer(temporal$horizon) == h &
                        temporal$variable == variable & as.integer(temporal$lag_weeks) == lag, , drop = FALSE]
      if (nrow(row) != 1L) stopf("Missing temporal trace row")
      add_trace(paste("temporal", variable, paste0("h", h), paste0("lag", lag), sep = "_"),
                paste0(p7g, "temporal_dependence.csv"),
                paste0("scope=pooled,horizon=", h, ",variable=", variable,
                       ",lag_weeks=", lag), row$correlation, "correlation",
                "Pooled same-cell temporal diagnostic")
    }
    for (pool in c("FRONTIER_RELATIVE", "FULL_DOMAIN")) {
      row <- early[early$pool == pool & early$score == "p_occurrence" &
                     as.integer(early$horizon) == h & as.numeric(early$top_fraction) %in% c(0.05, 0.1, 0.2), , drop = FALSE]
      if (nrow(row) != 3L) stopf("Missing early-warning trace rows")
      for (frac in c(0.05, 0.1, 0.2)) {
        r <- row[as.numeric(row$top_fraction) == frac, , drop = FALSE]
        add_trace(paste("early_warning", pool, paste0("h", h), paste0("top", frac * 100), sep = "_"),
                  paste0(p7g, "early_warning_topk.csv"),
                  paste0("pool=", pool, ",score=p_occurrence,horizon=", h,
                         ",top_fraction=", frac), r$capture_fraction, "fraction",
                  "First-recorded detections captured by the fixed ranked fraction")
      }
    }
  }
}
for (row in seq_len(nrow(dep_summary))) {
  add_trace(paste0("predictor_pairs_abs_corr_", dep_summary$threshold_abs_correlation[[row]]),
            paste0(p7g, "predictor_dependence_summary.csv"),
            paste0("threshold_abs_correlation=", dep_summary$threshold_abs_correlation[[row]]),
            dep_summary$pair_count[[row]], "pairs", "Frozen-reference predictor dependence count")
}
for (h in 1:3) for (sc in c("SUPPORTED", "CAUTION", "EXTRAPOLATIVE")) {
  row <- support_metrics[as.integer(support_metrics$horizon) == h & support_metrics$support_class == sc, , drop = FALSE]
  ci <- support_ci[as.integer(support_ci$horizon) == h & support_ci$support_class == sc, , drop = FALSE]
  if (nrow(row) != 1L || nrow(ci) != 1L) stopf("Missing support trace row")
  add_trace(paste("support_brier", sc, paste0("h", h), sep = "_"),
            paste0(p7g, "support_horizon_calibration_metrics.csv"),
            paste0("horizon=", h, ",support_class=", sc), row$brier, "Brier score",
            "Support-stratified empirical occurrence performance")
  add_trace(paste("support_brier_lower", sc, paste0("h", h), sep = "_"),
            paste0(p7g, "support_horizon_bootstrap_ci.csv"),
            paste0("horizon=", h, ",support_class=", sc), ci$brier_lower, "Brier score",
            "Target-week block-bootstrap lower bound")
  add_trace(paste("support_brier_upper", sc, paste0("h", h), sep = "_"),
            paste0(p7g, "support_horizon_bootstrap_ci.csv"),
            paste0("horizon=", h, ",support_class=", sc), ci$brier_upper, "Brier score",
            "Target-week block-bootstrap upper bound")
}
atomic_csv(trace, abs_path("analysis/p7h_manuscript_integration/results/p7h_numerical_traceability.csv"))

# Source-registered standardized association data and figure.
assoc$scale_category <- as.character(assoc$category)
assoc$predictor <- as.character(assoc$predictor)
atomic_csv(assoc, abs_path("analysis/p7h_manuscript_integration/results/predictor_standardized_associations.csv"))
atomic_csv(dep_pairs, abs_path("analysis/p7h_manuscript_integration/results/predictor_dependence_pairs.csv"))
atomic_csv(support_metrics, abs_path("analysis/p7h_manuscript_integration/results/support_horizon_calibration_metrics.csv"))
atomic_csv(support_ci, abs_path("analysis/p7h_manuscript_integration/results/support_horizon_bootstrap_ci.csv"))

p0 <- read_json("config/production_model_freeze.json")
predictor_order <- vapply(p0$predictor_specification$ordered_predictors, function(x) x$name, character(1L))
assoc$predictor <- factor(assoc$predictor, levels = rev(predictor_order))
assoc_col <- c(continuous_standardized = "#0072B2", binary_availability_indicator = "#D55E00",
               calendar = "#009E73", imputation_indicator = "#CC79A7")
assoc_col <- assoc_col[as.character(assoc$scale_category)]
plot_associations <- function() {
  old <- par(no.readonly = TRUE); on.exit(par(old), add = TRUE)
  par(mfrow = c(1, 2), mar = c(4.4, 12, 3.3, 2), oma = c(4.5, 0, 2, 0),
      family = "sans")
  xval <- suppressWarnings(as.numeric(assoc$coefficient_contrast))
  lim <- max(abs(xval), na.rm = TRUE) * 1.12
  if (!is.finite(lim) || lim == 0) lim <- 1
  for (component in c("occurrence", "positive_count")) {
    d <- assoc[assoc$component == component, , drop = FALSE]
    d <- d[order(match(as.character(d$predictor), rev(predictor_order))), , drop = FALSE]
    y <- seq_len(nrow(d))
    x <- suppressWarnings(as.numeric(d$coefficient_contrast))
    plot(x, y, pch = 19, col = assoc_col[as.character(d$scale_category)],
         xlim = c(-lim, lim), ylim = c(0.5, nrow(d) + 0.5), yaxt = "n",
         xlab = "Fitted-scale contrast", ylab = "",
         main = if (component == "occurrence") "Occurrence component" else "Positive-count component")
    axis(2, at = y, labels = as.character(d$predictor), las = 2, cex.axis = 0.58)
    abline(v = 0, lty = 2, col = "grey45")
    grid(nx = NA, ny = NULL, col = "grey90")
    if (component == "positive_count") {
      legend("topright", inset = c(0.02, 0.02),
             legend = c("continuous standardized", "binary / indicator", "calendar", "imputation indicator"),
             col = c("#0072B2", "#D55E02", "#009E73", "#CC79A7"), pch = 19, bty = "n", cex = 0.64)
    }
  }
  mtext("P7G standardized association contrasts; conditional predictive associations, not causal effects",
        outer = TRUE, cex = 0.9)
}
assoc_svg <- abs_path("analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.svg")
assoc_pdf <- abs_path("analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.pdf")
assoc_png <- abs_path("analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.png")
grDevices::svg(assoc_svg, width = 11, height = 12.5, pointsize = 10, onefile = FALSE, bg = "white")
plot_associations(); grDevices::dev.off()
grDevices::pdf(assoc_pdf, width = 11, height = 12.5, onefile = FALSE, pointsize = 10)
plot_associations(); grDevices::dev.off()
grDevices::png(assoc_png, width = 2200, height = 2500, res = 220, type = "cairo", bg = "white")
plot_associations(); grDevices::dev.off()

# Archive the superseded P7F Figure 6 and install the source-traceable
# standardized-association replacement under the same active figure number.
for (ext in c("svg", "png")) {
  old <- paste0("analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.", ext)
  original <- paste0("analysis/p7c_figure_refinement/figures/main/figure_05_predictor_associations.", ext)
  archived <- paste0("analysis/p7h_manuscript_integration/figures/archive/figure_06_predictor_associations_p7f_superseded.", ext)
  # P7C is the recorded source of the original P7F F6 asset. Copying it on
  # every build prevents a second build from archiving the P7H replacement.
  copy_checked(original, archived)
  copy_checked(paste0("analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.", ext), old)
}

# Add selected P7G diagnostics to the publication supplement; the P7G source
# artifacts themselves remain untouched.
supp_figs <- c("p7g_spatial_dependence.png", "p7g_spatial_dependence.pdf",
               "p7g_early_warning_capture.png", "p7g_early_warning_capture.pdf",
               "p7g_predictor_dependence.png", "p7g_predictor_dependence.pdf",
               "p7g_support_calibration.png", "p7g_support_calibration.pdf")
for (f in supp_figs) copy_checked(paste0("analysis/p7g_manuscript_evidence/figures/", f),
                                  paste0("analysis/p7_publication/supplement/P7G_", f))
supp_csvs <- c("spatial_shell_dependence.csv", "temporal_dependence.csv", "early_warning_topk.csv",
               "predictor_dependence_summary.csv", "predictor_dependence_pairs.csv",
               "predictor_standardized_associations.csv", "support_horizon_calibration_metrics.csv",
               "support_horizon_bootstrap_ci.csv", "support_horizon_reliability.csv")
for (f in supp_csvs) copy_checked(paste0(p7g, f), paste0("analysis/p7_publication/supplement/P7G_", f))

# Add bounded P7H claims to the P7 registry while retaining the original eight
# P7 claim families and their exact values.
claim_path <- abs_path("analysis/p7_publication/results/claim_registry.csv")
claims <- utils::read.csv(claim_path, check.names = FALSE, stringsAsFactors = FALSE)
if (!identical(as.character(claims$claim_id), LETTERS[1:8])) stopf("Unexpected P7 claim registry before P7H")
row_for <- function(h, var, shell) spatial[spatial$scope == "pooled_node_mean" & as.integer(spatial$horizon) == h &
                                               spatial$variable == var & as.integer(spatial$shell_order) == shell, , drop = FALSE]
ew <- function(pool, h, frac) early[early$pool == pool & early$score == "p_occurrence" &
                                     as.integer(early$horizon) == h & as.numeric(early$top_fraction) == frac, , drop = FALSE]
sp1 <- row_for(1, "raw_occurrence", 1); sr1 <- row_for(1, "residual_occurrence", 1)
sp4 <- row_for(1, "raw_occurrence", 4); sr4 <- row_for(1, "residual_occurrence", 4)
ew1 <- ew("FRONTIER_RELATIVE", 1, 0.05); ew2 <- ew("FRONTIER_RELATIVE", 2, 0.05); ew3 <- ew("FRONTIER_RELATIVE", 3, 0.05)
sm <- dep_summary
srows <- support_metrics[support_metrics$support_class %in% c("SUPPORTED", "EXTRAPOLATIVE") & as.integer(support_metrics$horizon) %in% 1:3, , drop = FALSE]
new_claims <- data.frame(
  claim_id = c("I", "J", "K", "L"),
  concise_claim = c(
    "Residual spatial and temporal dependence is lower than raw outcome dependence but remains positive.",
    "Fixed p_occurrence ranks capture many first-recorded detections in frontier-relative top fractions, with horizon-specific capture.",
    "The frozen predictors contain substantial pairwise dependence, so standardized coefficient contrasts are conditional associations rather than independent importance scores.",
    "Empirical occurrence performance differs by P4 support class, with extrapolative rows having higher Brier scores than supported rows across h=1--3."),
  source_phase = c("P7G-A", "P7G-B", "P7G-C", "P7G-D"),
  source_artifact = c(paste0(p7g, "spatial_shell_dependence.csv; ", p7g, "temporal_dependence.csv"),
                      paste0(p7g, "early_warning_topk.csv"),
                      paste0(p7g, "predictor_dependence_summary.csv; ", p7g, "predictor_standardized_associations.csv"),
                      paste0(p7g, "support_horizon_calibration_metrics.csv; ", p7g, "support_horizon_bootstrap_ci.csv")),
  source_metric_or_row = c("h=1 pooled shell 1/4; pooled lag 1/3", "FRONTIER_RELATIVE p_occurrence top 5% h=1..3",
                           "abs Pearson thresholds 0.70 and 0.90; association table", "support class Brier h=1..3"),
  exact_value = c(
    paste0("raw shell1=", raw_num(sp1$moran_i), "; residual shell1=", raw_num(sr1$moran_i),
           "; raw shell4=", raw_num(sp4$moran_i), "; residual shell4=", raw_num(sr4$moran_i)),
    paste0("frontier-relative top5 capture h1=", raw_num(ew1$capture_fraction),
           "; h2=", raw_num(ew2$capture_fraction), "; h3=", raw_num(ew3$capture_fraction)),
    paste0("pairs abs Pearson >=0.70=", raw_num(sm$pair_count[sm$threshold_abs_correlation == 0.7]),
           "; >=0.90=", raw_num(sm$pair_count[sm$threshold_abs_correlation == 0.9]),
           "; standardized rows=", nrow(assoc)),
    paste0("Brier supported h1--h3=", paste(raw_num(srows$brier[srows$support_class == "SUPPORTED"]), collapse = ","),
           "; extrapolative h1--h3=", paste(raw_num(srows$brier[srows$support_class == "EXTRAPOLATIVE"]), collapse = ","))),
  uncertainty_interval = c("P7G point diagnostics; no independent spatial holdout.",
                           "P7G fixed-rank event capture; sparse first-detection strata.",
                           "P7G point associations; coefficient-bootstrap artifact not retained.",
                           "P7G 199-replicate target-week block-bootstrap intervals are in source."),
  allowed_interpretation = c("Residual process dependence remains after fitted-mean subtraction.",
                             "Retrospective event-ranking evidence within the specified pools.",
                             "Conditional association display with scale and correlation caveats.",
                             "Support class is associated with empirical performance differences."),
  prohibited_overinterpretation = c("Not a refitted spatial holdout or proof of model failure.",
                                   "Not a causal early-warning effect or prospective forecast claim.",
                                   "Not causal inference, global feature importance, or variable selection.",
                                   "Not a direct probability of correctness or a retuned support threshold."),
  destination = c("Results; Supplement", "Results; Supplement", "Methods; Supplement; Figure 6", "Results; Supplement"),
  stringsAsFactors = FALSE)
claims <- rbind(claims, new_claims)
atomic_csv(claims, claim_path)

claim_audit <- data.frame(
  claim_id = c(LETTERS[1:8], "I", "J", "K", "L"),
  status = c(rep("RETAINED", 8), "ADDED_P7G", "ADDED_P7G", "ADDED_P7G_WITH_LIMITATION", "ADDED_P7G"),
  source_phase = claims$source_phase,
  source_artifact = claims$source_artifact,
  allowed_interpretation = claims$allowed_interpretation,
  prohibited_overinterpretation = claims$prohibited_overinterpretation,
  stringsAsFactors = FALSE)
atomic_csv(claim_audit, abs_path("analysis/p7h_manuscript_integration/results/p7h_claim_audit.csv"))

# Integrate manuscript-facing evidence, preserving the technical and bounded style.
phase_decision <- c(
  "P1: `P1_TRANSFER_VALIDATION_SUPPORTED_WITH_LIMITATIONS`",
  "P2: `P2_OPERATIONAL_NOWCAST_SUPPORTED_WITH_LIMITATIONS`",
  "P3: `P3_ROBUSTNESS_SUPPORTED_WITH_LIMITATIONS`",
  "P4: `P4_UNCERTAINTY_SUPPORT_SUPPORTED_WITH_LIMITATIONS`",
  "P5: `P5_OPERATIONAL_CONTRACT_NOT_SUPPORTED`",
  "P5A: `P5A_ENVIRONMENTAL_PROXY_SUPPORTED`",
  "P6: `P6_PRODUCTION_HARDENING_SUPPORTED_WITH_LIMITATIONS`",
  "P7G: `P7G_MANUSCRIPT_EVIDENCE_COMPLETE_WITH_LIMITATIONS`")

methods <- c(
  "# Methods Summary", "",
  "The analysis uses weekly node-level observations on the frozen 25 x 25 km canonical grid. `STRUCTURED_A3` is a penalized spatiotemporal hurdle model with a Bernoulli/logistic occurrence component and a zero-truncated negative-binomial conditional positive-count component. The frozen schema has 34 predictors and is defined by the P0 production-freeze manifest.", "",
  "Qualification used retrospective rolling-origin evaluation at h=1, h=2, and h=3, with canonical P1 transfer regimes, P2 calibration and count metrics, bounded P3 sensitivity, P4 uncertainty and support classification, P5 operational-contract testing, P5A issue-time environmental proxy comparison, and P6 hardening/restart/provenance validation.", "",
  "P7G manuscript diagnostics reused the immutable P2 prediction archive and P4 support classifications. Spatial dependence used the canonical queen graph and exact shortest-path shells 1--4; residual occurrence was `observed_positive - p_occurrence`, residual positive count was defined against the conditional count mean, and full-hurdle residuals used the observed count minus expected count. Temporal dependence used same-cell exact ISO-week lags 1--3 within horizon. These are descriptive dependence diagnostics and are not a refitted spatial holdout.", "",
  "First-recorded detections were defined from prediction-time previously-unoccupied rows and ranked by fixed midranks within the prespecified full-domain and frontier-relative pools. Predictor dependence used Pearson and Spearman correlations among the 34 frozen predictors in the P4 training reference, with warning thresholds of absolute correlation 0.70 and 0.90. Standardized association contrasts used the P7G fitted-scale contrast definitions and are reported as conditional predictive associations; no new importance method or coefficient-bootstrap interval was introduced.", "",
  "Support-stratified calibration used the unchanged P4 support classes and fixed ten-bin summaries with 199 target-week block-bootstrap replicates. The operational environmental state remains `E0_LAST_AVAILABLE`, held across h=1--3. Production output includes occurrence risk, conditional positive count, full hurdle expected count, uncertainty/support fields, warnings, and provenance.")
atomic_lines(methods, abs_path("analysis/p7_publication/results/methods_summary.md"))

results <- c(
  "# Results Draft", "",
  "## Model and retrospective nowcast performance", "",
  "P2 all-domain Brier scores were 0.0281, 0.0284, and 0.0288 for h=1--3; AUPRC values were 0.4452, 0.4414, and 0.4402. These are retrospective rolling-origin results with explicit horizon labels, not unrestricted prospective forecasts.", "",
  "## Dependence and first-recorded detection diagnostics", "",
  paste0("P7G dependence diagnostics showed positive raw occurrence association across spatial shells and temporal lags. At h=1, pooled shell-1 association was ", fmt4(sp1$moran_i), " for raw occurrence and ", fmt4(sr1$moran_i), " for the occurrence residual; at shell 4 the corresponding values were ", fmt4(sp4$moran_i), " and ", fmt4(sr4$moran_i), ". Pooled temporal lag-1 occurrence association at h=1 was ", fmt4(temporal$correlation[temporal$scope == "pooled" & temporal$horizon == 1 & temporal$lag_weeks == 1 & temporal$variable == "raw_occurrence"]), " for raw occurrence and ", fmt4(temporal$correlation[temporal$scope == "pooled" & temporal$horizon == 1 & temporal$lag_weeks == 1 & temporal$variable == "residual_occurrence"]), " for the residual. Residual association was lower but remained positive; this is a diagnostic, not a spatial holdout."), "",
  paste0("Among ", raw_num(ew1$event_n), " first-recorded frontier-relative events at h=1, the top 5% of p_occurrence-ranked cells captured ", fmt_pct(ew1$capture_fraction), " of events; corresponding capture was ", fmt_pct(ew2$capture_fraction), " at h=2 and ", fmt_pct(ew3$capture_fraction), " at h=3. These are retrospective ranking diagnostics within fixed pools and do not establish causal early-warning performance."), "",
  "## Predictor dependence and conditional associations", "",
  paste0("The 34 frozen predictors included ", dep_summary$pair_count[dep_summary$threshold_abs_correlation == 0.7], " pairs with absolute Pearson correlation at least 0.70 and ", dep_summary$pair_count[dep_summary$threshold_abs_correlation == 0.9], " pairs at least 0.90 in the P4 training reference. The standardized association display therefore uses fitted-scale contrasts with scale-category labels; it is not a global importance ranking. A retained P4 coefficient-bootstrap stability artifact was unavailable, so no coefficient intervals were fabricated."), "",
  "## Environmental proxy validation", "",
  "P5A E0 Brier differences relative to REALIZED_ENV were -0.0000, -0.0000, and -0.0000 for h=1--3 in the paired comparison. E0 was selected by the prespecified simplicity-first rule and uses only the latest legitimate issue-time environmental state; it is not a realized future environment or a numerical weather forecast.", "",
  "## Support-stratified calibration", "",
  paste0("Empirical occurrence performance varied by support class. Brier scores for SUPPORTED rows were ", paste(fmt4(support_metrics$brier[support_metrics$support_class == "SUPPORTED"]), collapse = ", "), " across h=1--3, compared with ", paste(fmt4(support_metrics$brier[support_metrics$support_class == "EXTRAPOLATIVE"]), collapse = ", "), " for EXTRAPOLATIVE rows. These estimates are conditional support-stratified diagnostics; support classes are not direct correctness probabilities and thresholds were not retuned."), "",
  "## Frontier, counts, support, and production", "",
  "Frontier strata remain sparse and weaker, count predictions retain measurable bias, and P4 support flags identify heterogeneous predictor-space support. P6 demonstrated deterministic replay, restartability, duplicate-run protection, and corruption detection without changing the scientific model.")
atomic_lines(results, abs_path("analysis/p7_publication/results/results_draft.md"))

synthesis <- c(
  "# Controlled Results Synthesis", "",
  "This document is generated from canonical P1--P7G machine-readable artifacts. It is a controlled source for manuscript wording, not a new scientific analysis.", "",
  "## Qualified model and horizon", "",
  "The frozen model is `STRUCTURED_A3` with 34 predictors on the 25 x 25 km canonical grid (10037 cells). The qualified operational configuration uses `E0_LAST_AVAILABLE` across the 1--3 week nowcast horizon.", "Source: `config/production_model_freeze.json`; `config/p6_production_config.json`.", "",
  "## Canonical decisions", "", phase_decision, "",
  "## P7G evidence", "",
  paste0("P7G residual dependence diagnostics show reduced but nonzero spatial and temporal association after fitted-mean subtraction. At h=1, occurrence shell-1 values were raw=", fmt4(sp1$moran_i), " and residual=", fmt4(sr1$moran_i), "; pooled lag-1 values were raw=", fmt4(temporal$correlation[temporal$scope == "pooled" & temporal$horizon == 1 & temporal$lag_weeks == 1 & temporal$variable == "raw_occurrence"]), " and residual=", fmt4(temporal$correlation[temporal$scope == "pooled" & temporal$horizon == 1 & temporal$lag_weeks == 1 & temporal$variable == "residual_occurrence"]), ". Source: P7G spatial and temporal dependence tables."),
  paste0("P7G first-recorded detection ranking captured ", fmt_pct(ew1$capture_fraction), ", ", fmt_pct(ew2$capture_fraction), " and ", fmt_pct(ew3$capture_fraction), " of frontier-relative events in the top 5% at h=1--3, respectively. Source: P7G early-warning table."),
  paste0("P7G predictor-dependence counts were ", dep_summary$pair_count[dep_summary$threshold_abs_correlation == 0.7], " at absolute Pearson correlation >=0.70 and ", dep_summary$pair_count[dep_summary$threshold_abs_correlation == 0.9], " at >=0.90. Standardized associations are conditional, scale-labeled point estimates; coefficient-bootstrap stability intervals were not available."),
  paste0("P7G support-stratified Brier scores were ", paste(fmt4(support_metrics$brier[support_metrics$support_class == "SUPPORTED"]), collapse = ", "), " for SUPPORTED rows and ", paste(fmt4(support_metrics$brier[support_metrics$support_class == "EXTRAPOLATIVE"]), collapse = ", "), " for EXTRAPOLATIVE rows across h=1--3. Source: P7G support calibration tables."), "",
  "## Existing qualified results", "",
  "P2 occurrence, P5A proxy, frontier, count, support, and P6 production claims remain unchanged and are sourced from the existing P7 table/claim artifacts. These are retrospective or contract-validation results with the limitations recorded in P1--P7G.")
atomic_lines(synthesis, abs_path("analysis/p7_publication/results/results_synthesis.md"))

limitations <- c(
  "# Limitations Draft", "",
  "The qualification and manuscript-evidence program does not remove the following limitations:", "",
  "1. Frontier/newly unoccupied positives are sparse and performance is weaker in those strata.",
  "2. U.S./regional outcome support is sparse, so geographic transport claims are limited to supported evidence.",
  "3. Conditional positive-count and full-hurdle expected-count predictions retain measurable count-process bias; they are not unbiased abundance estimates.",
  "4. A substantial proportion of rows are CAUTION or EXTRAPOLATIVE under the unchanged P4 support specification.",
  "5. Prospective operation relies on `E0_LAST_AVAILABLE`, an issue-time environmental proxy rather than a future environmental forecast.",
  "6. Bounded regrouping and sensitivity analyses do not create a refitted spatial holdout.",
  "7. The framework is predictive and observational; predictor associations are not causal environmental effects.",
  "8. Source-product publication, revision, and vintage limitations remain part of the operational contract and replay interpretation.",
  "9. P7G residual dependence remains positive after fitted-mean subtraction; this diagnostic does not provide a refitted spatial holdout or remove observation-process dependence.",
  "10. First-recorded detection strata are event-defined and retrospective; ranking capture should not be interpreted as prospective early-warning validation.",
  "11. The frozen predictors contain substantial pairwise dependence, and no retained P4 coefficient-bootstrap stability artifact was available for coefficient intervals.")
atomic_lines(limitations, abs_path("analysis/p7_publication/results/limitations_draft.md"))

discussion <- c(
  "# Discussion Outline", "", "## Predictive utility", "",
  "Discuss the value of a spatially explicit weekly occurrence/count framework for short-horizon nowcasting, with metrics interpreted within the retrospective rolling-origin design.", "",
  "## Dependence and observation process", "",
  "Treat positive residual spatial and temporal association as a diagnostic of remaining structured dependence. Distinguish prediction of recorded detections from a direct observation of latent occurrence or spread.", "",
  "## Ecological interpretation", "",
  "Separate predictive associations from ecological mechanism. Standardized fitted-scale contrasts are not causal environmental effects; correlated predictors can redistribute conditional coefficient association.", "",
  "## Operational use", "",
  "Describe E0_LAST_AVAILABLE as an issue-time environmental-context assumption and emphasize that every prediction retains support and uncertainty flags.", "",
  "## Limits of transport", "",
  "Discuss sparse frontier and regional support, extrapolative support, count bias, the absence of a refitted spatial holdout, support-stratified performance differences, retrospective event-ranking diagnostics, and source-vintage limits.", "",
  "## Relationship to complementary frameworks", "",
  "Position the framework as complementary to other modeling approaches without direct comparative superiority claims.")
atomic_lines(discussion, abs_path("analysis/p7_publication/results/discussion_outline.md"))

reviewer <- c(
  "# Publication Reviewer Checklist", "",
  "- [ ] Every primary value traces to a machine-readable P1--P7G artifact.",
  "- [ ] Every primary figure has source metadata and plotted-data provenance.",
  "- [ ] All required limitations appear in the manuscript components.",
  "- [ ] No future-data leakage is implied by retrospective results or first-recorded detection ranking.",
  "- [ ] E0_LAST_AVAILABLE is described as an issue-time proxy, not a true future environmental forecast.",
  "- [ ] No causal language is used for predictive associations or dependence diagnostics.",
  "- [ ] Frontier, regional/U.S., count, support/extrapolation, and residual-dependence caveats are explicit.",
  "- [ ] Standardized association scale classes and predictor dependence are identified; no global importance ranking is claimed.",
  "- [ ] Missing P4 coefficient-bootstrap stability intervals are not represented as if available.",
  "- [ ] Scientific model, operational-contract, and production-software versions are distinguished.",
  "- [ ] No claim of full U.S. validation, unbiased abundance prediction, superiority, or unrestricted production readiness appears.",
  "- [ ] Protected raw data and secrets are absent from the release candidate.")
atomic_lines(reviewer, abs_path("analysis/p7_publication/results/publication_reviewer_checklist.md"))

# Expand the P7 limitation table with the P7G evidence boundary.
table5_path <- abs_path("analysis/p7_publication/tables/table_5_limitation_summary.csv")
table5 <- utils::read.csv(table5_path, stringsAsFactors = FALSE, check.names = FALSE)
if (!"source_artifact" %in% names(table5)) stopf("P7 limitation table schema changed")
table5 <- rbind(table5, data.frame(
  limitation = c("Residual spatial/temporal dependence", "Observation-process/event-ranking boundary",
                 "Predictor dependence and coefficient uncertainty"),
  evidence = c("P7G raw-versus-residual spatial shells and temporal lags retain positive residual association.",
               "P7G first-recorded detections are retrospective event-defined ranking diagnostics.",
               "P7G reports 19 pairs at absolute Pearson correlation >=0.70 and no retained P4 coefficient-bootstrap artifact."),
  phase_identified = c("P7G-A", "P7G-B", "P7G-C"),
  operational_treatment = c("Report residual diagnostics; do not call them a spatial holdout.",
                            "Use bounded ranking language and preserve sparse-stratum caveat.",
                            "Use scale-labeled conditional association display; no causal or global importance claim."),
  manuscript_interpretation = c("Fitted means do not remove all structured dependence.",
                                "Predictions concern recorded outcomes under the evaluated observation process.",
                                "Coefficient displays are conditional associations with no bootstrap stability interval."),
  source_artifact = c(paste0(p7g, "spatial_shell_dependence.csv; ", p7g, "temporal_dependence.csv"),
                      paste0(p7g, "early_warning_topk.csv"),
                      paste0(p7g, "predictor_dependence_summary.csv; ", p7g, "predictor_standardized_associations.csv")),
  stringsAsFactors = FALSE))
atomic_csv(table5, table5_path)

# Replace the P7F active predictor figure only, preserving its number and
# retaining the original asset under the P7H archive.
p7f_registry_path <- abs_path("analysis/p7f_final_figures/results/figure_source_registry.csv")
p7f_registry <- utils::read.csv(p7f_registry_path, stringsAsFactors = FALSE, check.names = FALSE)
f6 <- which(p7f_registry$figure_id == "F6")
if (length(f6) != 1L) stopf("P7F F6 registry row missing")
p7f_registry$source_phase[f6] <- "P7H integrated from P7G"
p7f_registry$source_file[f6] <- paste0("analysis/p7g_manuscript_evidence/results/predictor_standardized_associations.csv; ",
                                       "analysis/p7h_manuscript_integration/scripts/build_p7h_manuscript_package.R")
p7f_registry$source_hash[f6] <- sha256_file(abs_path("analysis/p7g_manuscript_evidence/results/predictor_standardized_associations.csv"))
p7f_registry$output_hash[f6] <- paste(sha256_file(abs_path("analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.svg")),
                                      sha256_file(abs_path("analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.png")), sep = ";")
atomic_csv(p7f_registry, p7f_registry_path)
p7f_caption <- abs_path("analysis/p7f_final_figures/captions/final_captions.md")
cap <- readLines(p7f_caption, warn = FALSE, encoding = "UTF-8")
cap[grepl("^## Figure 6\\.", cap)] <- "## Figure 6. Predictor associations (P7H standardized display)"
f6_start <- which(grepl("^## Figure 6\\.", cap))
f6_next <- which(seq_along(cap) > f6_start & grepl("^## ", cap))
f6_end <- if (length(f6_next)) min(f6_next) - 1L else length(cap)
replacement <- c("## Figure 6. Predictor associations (P7H standardized display)",
                 "P7G fitted-scale association contrasts for the occurrence and conditional positive-count components, with predictor scale categories shown. Contrasts are conditional predictive associations; correlated predictors can redistribute coefficient magnitude. The display is not a causal effect plot or a global feature-importance ranking, and no coefficient-bootstrap intervals are available in the retained canonical artifacts.")
cap <- c(cap[seq_len(f6_start - 1L)], replacement, cap[(f6_end + 1L):length(cap)])
atomic_lines(cap, p7f_caption)

replacement_decision <- list(
  replacement = TRUE,
  active_figure = "analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.{svg,png}",
  source = "analysis/p7g_manuscript_evidence/results/predictor_standardized_associations.csv",
  superseded_archive = "analysis/p7h_manuscript_integration/figures/archive/figure_06_predictor_associations_p7f_superseded.{svg,png}",
  rationale = "P7G standardized fitted-scale contrasts support a clearer scale-labeled conditional-association display than the mixed raw-coefficient figure.",
  prohibited_interpretations = c("causal effect", "global feature importance", "independent importance ranking"),
  no_model_fitting = TRUE)
atomic_json(replacement_decision, abs_path("analysis/p7h_manuscript_integration/results/p7h_predictor_figure_replacement.json"))

# Update the P7 report to identify the P7H integrated evidence boundary.
p7_report <- c(
  "# P7 Publication Artifact Generation and Release Candidate Assembly Report", "",
  "P7H integrated the canonical P7G manuscript-evidence outputs into this P7 package without changing the frozen model or prior scientific decisions.", "",
  "## Qualified specification", "",
  "The package describes `STRUCTURED_A3` with the `E0_LAST_AVAILABLE` issue-time environmental proxy, horizons 1--3, unchanged P4 support classes, and the P6 production schema. The frozen model SHA-256 is `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`.", "",
  "## P7G evidence integration", "",
  "P7G dependence, first-recorded detection, predictor-dependence/standardized-association, and support-stratified calibration artifacts are included as source-registered supplementary evidence. Figure 6 is the scale-labeled standardized-association display; the superseded P7F figure is retained under the P7H archive. P7G remains descriptive and does not create a refitted spatial holdout or a causal importance analysis.", "",
  "## Limitations", "",
  "Frontier and regional/U.S. sparsity, count-process bias, support/extrapolation burden, residual dependence, observation-process boundaries, E0 proxy dependence, the spatial-holdout boundary, retrospective evaluation, and missing P4 coefficient-bootstrap stability remain explicit.", "",
  "## Decision", "", "`P7_PUBLICATION_PACKAGE_SUPPORTED_WITH_LIMITATIONS`")
atomic_lines(p7_report, abs_path("analysis/p7_publication/p7_publication_report.md"))

# Source registry covers every P7G source used and the active P7H-generated outputs.
source_paths <- c(
  "analysis/p7g_manuscript_evidence/results/p7g_reproducibility_manifest.json",
  "analysis/p7g_manuscript_evidence/results/decision.json",
  "analysis/p7g_manuscript_evidence/results/spatial_shell_dependence.csv",
  "analysis/p7g_manuscript_evidence/results/temporal_dependence.csv",
  "analysis/p7g_manuscript_evidence/results/early_warning_topk.csv",
  "analysis/p7g_manuscript_evidence/results/predictor_dependence_summary.csv",
  "analysis/p7g_manuscript_evidence/results/predictor_dependence_pairs.csv",
  "analysis/p7g_manuscript_evidence/results/predictor_standardized_associations.csv",
  "analysis/p7g_manuscript_evidence/results/support_horizon_calibration_metrics.csv",
  "analysis/p7g_manuscript_evidence/results/support_horizon_bootstrap_ci.csv",
  "analysis/p7h_manuscript_integration/results/p7h_numerical_traceability.csv",
  "analysis/p7h_manuscript_integration/results/predictor_standardized_associations.csv",
  "analysis/p7h_manuscript_integration/results/p7h_claim_audit.csv",
  "analysis/p7h_manuscript_integration/results/p7h_predictor_figure_replacement.json")
source_registry <- data.frame(
  artifact = source_paths,
  sha256 = vapply(source_paths, function(x) sha256_file(abs_path(x)), character(1L)),
  role = c("P7G manifest", "P7G decision", "spatial dependence", "temporal dependence",
           "first-recorded detection ranking", "dependence threshold summary", "dependence pairs",
           "standardized associations", "support metrics", "support bootstrap intervals",
           "P7H traceability", "P7H figure data", "P7H claim audit", "P7H replacement decision"),
  stringsAsFactors = FALSE)
atomic_csv(source_registry, abs_path("analysis/p7h_manuscript_integration/results/p7h_source_registry.csv"))

# Registry for the post-P7 publication additions, including the active Figure 6
# replacement and the source-derived P7G supplement. This keeps the package
# auditable without changing the meaning of the P7 primary figure/table manifests.
added_paths <- c(
  "analysis/p7h_manuscript_integration/p7h_prespecification.md",
  "analysis/p7h_manuscript_integration/p7h_manuscript_integration_report.md",
  "analysis/p7h_manuscript_integration/results/p7h_decision.json",
  "analysis/p7h_manuscript_integration/results/p7h_numerical_traceability.csv",
  "analysis/p7h_manuscript_integration/results/p7h_claim_audit.csv",
  "analysis/p7h_manuscript_integration/results/p7h_predictor_figure_replacement.json",
  "analysis/p7h_manuscript_integration/results/p7h_source_registry.csv",
  "analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.svg",
  "analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.png",
  "analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.svg",
  "analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.png",
  "analysis/p7f_final_figures/figures/archive/figure_06_predictor_associations_p7f_superseded.svg",
  "analysis/p7f_final_figures/figures/archive/figure_06_predictor_associations_p7f_superseded.png")
supp_added <- list.files(abs_path("analysis/p7_publication/supplement"),
                         pattern = "^P7G_", full.names = FALSE)
added_paths <- c(added_paths, file.path("analysis/p7_publication/supplement", supp_added))
added_paths <- added_paths[file.exists(vapply(added_paths, abs_path, character(1L)))]
artifact_registry <- data.frame(
  artifact_type = c(rep("P7H integration", length(added_paths) - length(supp_added)),
                    rep("P7G supplementary", length(supp_added))),
  path = added_paths,
  source_artifact = ifelse(grepl("P7G_", added_paths),
                           sub("analysis/p7_publication/supplement/P7G_", "analysis/p7g_manuscript_evidence/", added_paths),
                           "P7H integration source registry/decision"),
  sha256 = vapply(added_paths, function(x) sha256_file(abs_path(x)), character(1L)),
  generation_script = "analysis/p7h_manuscript_integration/scripts/build_p7h_manuscript_package.R",
  stringsAsFactors = FALSE)
atomic_csv(artifact_registry, abs_path("analysis/p7h_manuscript_integration/results/p7h_publication_artifact_registry.csv"))

# P7H manifest: all generated integration outputs are hashed after writing.
generated <- c(
  "analysis/p7h_manuscript_integration/p7h_prespecification.md",
  "analysis/p7h_manuscript_integration/results/p7h_numerical_traceability.csv",
  "analysis/p7h_manuscript_integration/results/predictor_standardized_associations.csv",
  "analysis/p7h_manuscript_integration/results/predictor_dependence_pairs.csv",
  "analysis/p7h_manuscript_integration/results/support_horizon_calibration_metrics.csv",
  "analysis/p7h_manuscript_integration/results/support_horizon_bootstrap_ci.csv",
  "analysis/p7h_manuscript_integration/results/p7h_claim_audit.csv",
  "analysis/p7h_manuscript_integration/results/p7h_predictor_figure_replacement.json",
  "analysis/p7h_manuscript_integration/results/p7h_source_registry.csv",
  "analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.svg",
  "analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.png",
  "analysis/p7_publication/results/claim_registry.csv",
  "analysis/p7_publication/results/methods_summary.md",
  "analysis/p7_publication/results/results_draft.md",
  "analysis/p7_publication/results/results_synthesis.md",
  "analysis/p7_publication/results/limitations_draft.md",
  "analysis/p7_publication/results/discussion_outline.md",
  "analysis/p7_publication/results/publication_reviewer_checklist.md",
  "analysis/p7_publication/tables/table_5_limitation_summary.csv",
  "analysis/p7_publication/p7_publication_report.md",
  "analysis/p7f_final_figures/results/figure_source_registry.csv",
  "analysis/p7f_final_figures/captions/final_captions.md")
generated <- generated[file.exists(vapply(generated, abs_path, character(1L)))]
output_hashes <- setNames(vapply(generated, function(x) sha256_file(abs_path(x)), character(1L)), generated)
git_sha <- tryCatch(trimws(system2("git", c("-c", "safe.directory=*", "-C", repo_root, "rev-parse", "HEAD"), stdout = TRUE)),
                    error = function(e) "UNKNOWN")
p7h_manifest <- list(
  schema_version = "P7H_MANUSCRIPT_INTEGRATION_1.0",
  canonical_main_sha_at_build = git_sha,
  frozen_model = list(model_id = "STRUCTURED_A3", sha256 = model_hash),
  p7g_manifest = "analysis/p7g_manuscript_evidence/results/p7g_reproducibility_manifest.json",
  p7g_manifest_sha256 = sha256_file(abs_path("analysis/p7g_manuscript_evidence/results/p7g_reproducibility_manifest.json")),
  p7g_decision = p7g_decision$decision,
  p7g_atlas_job_id = p7g_manifest$atlas_job_id,
  no_model_fitting = TRUE,
  output_hashes_excluding_manifest = as.list(output_hashes),
  generation_timestamp_utc = format(Sys.time(), tz = "UTC", usetz = TRUE))
atomic_json(p7h_manifest, abs_path("analysis/p7h_manuscript_integration/results/p7h_provenance_manifest.json"))

# Add the P7H manifest link to the P7 manifest after the base build. The P7
# manifest remains a package-level record; P7H is the post-integration audit.
p7_manifest_path <- abs_path("analysis/p7_publication/results/reproducibility_manifest.json")
if (file.exists(p7_manifest_path)) {
  p7_manifest <- jsonlite::fromJSON(p7_manifest_path, simplifyVector = FALSE)
  p7_manifest$p7h_integration <- list(
    manifest = "analysis/p7h_manuscript_integration/results/p7h_provenance_manifest.json",
    manifest_sha256 = sha256_file(abs_path("analysis/p7h_manuscript_integration/results/p7h_provenance_manifest.json")),
    p7g_manifest = "analysis/p7g_manuscript_evidence/results/p7g_reproducibility_manifest.json",
    p7g_decision = p7g_decision$decision,
    no_model_fitting = TRUE)
  p7_manifest$generation_timestamp_utc <- format(Sys.time(), tz = "UTC", usetz = TRUE)
  atomic_json(p7_manifest, p7_manifest_path)
}

decision <- list(
  decision = "P7H_MANUSCRIPT_PACKAGE_READY_WITH_LIMITATIONS",
  prespecification_committed_before_integration = "8c878d9",
  p7g_source_hashes_verified = TRUE,
  primary_claims_traceable = TRUE,
  publication_components_updated = TRUE,
  predictor_figure_replaced_with_standardized_association_display = TRUE,
  no_model_fitting = TRUE,
  limitations = c(
    "P7G support-stratified and first-recorded detection strata are descriptive and may be sparse.",
    "Residual dependence remains positive and is not a refitted spatial holdout.",
    "Predictors are correlated and the retained P4 coefficient-bootstrap stability artifact is unavailable.",
    "P2 remains retrospective realized-environment evaluation; E0 is the qualified issue-time proxy.",
    "The validated Atlas environment lacks testthat; this is a tooling limitation, not a scientific result."),
  no_release_tag = TRUE)
atomic_json(decision, abs_path("analysis/p7h_manuscript_integration/results/p7h_decision.json"))

report <- c(
  "# P7H Manuscript Evidence Integration Report", "",
  "## Objective", "",
  "P7H integrates canonical P7G evidence into the P7 publication package without changing the frozen scientific model, operational proxy, support specification, or prior qualification decisions.", "",
  "## Source verification", "",
  paste0("The frozen `STRUCTURED_A3` artifact hash is `", model_hash, "`. The P7G reproducibility manifest and all 33 listed P7G artifacts were hash-verified; P7G decision is `", p7g_decision$decision, "` and `no_model_fitting` is true."), "",
  "## Integrated evidence", "",
  "P7G spatial/temporal dependence, first-recorded detection ranking, predictor dependence and standardized association, and support-stratified calibration outputs were added to the controlled traceability registry, claim registry, synthesis, Methods, Results, Limitations, Discussion outline, reviewer checklist, and publication supplement.", "",
  "## Predictor association figure", "",
  "The active P7F Figure 6 was replaced under the same figure number with a scale-labeled fitted-scale association display. The superseded P7F asset is archived under `analysis/p7h_manuscript_integration/figures/archive/`. The replacement is conditional and noncausal; no global feature-importance ranking or coefficient interval is claimed.", "",
  "## Limitations retained", "",
  "Residual dependence, observation-process and event-ranking boundaries, sparse frontier/regional support, count-process bias, extrapolative support, E0 proxy dependence, retrospective P2 evaluation, absence of a refitted spatial holdout, predictor dependence, and missing P4 coefficient-bootstrap stability remain explicit.", "",
  "## Reproducibility", "",
  "This integration is generated by `analysis/p7h_manuscript_integration/scripts/build_p7h_manuscript_package.R`, which invokes the canonical P7 builder first, verifies P7G source hashes, writes source-registered outputs, and fails on missing or mismatched inputs. The P7H manifest records deterministic source/data/SVG/PNG hashes and no-model-fitting status. PDF rendering metadata are not used for deterministic equality; the underlying plotted data and non-PDF outputs are the reproducibility gate.", "",
  "## Decision", "", "`P7H_MANUSCRIPT_PACKAGE_READY_WITH_LIMITATIONS`")
atomic_lines(report, abs_path("analysis/p7h_manuscript_integration/p7h_manuscript_integration_report.md"))

# Refresh the artifact registry now that the decision and report have been
# written; this avoids a first-build/second-build difference in its contents.
added_paths <- c(
  "analysis/p7h_manuscript_integration/p7h_prespecification.md",
  "analysis/p7h_manuscript_integration/p7h_manuscript_integration_report.md",
  "analysis/p7h_manuscript_integration/results/p7h_decision.json",
  "analysis/p7h_manuscript_integration/results/p7h_numerical_traceability.csv",
  "analysis/p7h_manuscript_integration/results/p7h_claim_audit.csv",
  "analysis/p7h_manuscript_integration/results/p7h_predictor_figure_replacement.json",
  "analysis/p7h_manuscript_integration/results/p7h_source_registry.csv",
  "analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.svg",
  "analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.png",
  "analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.svg",
  "analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.png",
  "analysis/p7f_final_figures/figures/archive/figure_06_predictor_associations_p7f_superseded.svg",
  "analysis/p7f_final_figures/figures/archive/figure_06_predictor_associations_p7f_superseded.png")
supp_added <- list.files(abs_path("analysis/p7_publication/supplement"), pattern = "^P7G_", full.names = FALSE)
added_paths <- c(added_paths, file.path("analysis/p7_publication/supplement", supp_added))
added_paths <- added_paths[file.exists(vapply(added_paths, abs_path, character(1L)))]
artifact_registry <- data.frame(
  artifact_type = c(rep("P7H integration", length(added_paths) - length(supp_added)),
                    rep("P7G supplementary", length(supp_added))),
  path = added_paths,
  source_artifact = ifelse(grepl("P7G_", added_paths),
                           sub("analysis/p7_publication/supplement/P7G_", "analysis/p7g_manuscript_evidence/", added_paths),
                           "P7H integration source registry/decision"),
  sha256 = vapply(added_paths, function(x) sha256_file(abs_path(x)), character(1L)),
  generation_script = "analysis/p7h_manuscript_integration/scripts/build_p7h_manuscript_package.R",
  stringsAsFactors = FALSE)
atomic_csv(artifact_registry, abs_path("analysis/p7h_manuscript_integration/results/p7h_publication_artifact_registry.csv"))

# Finalize the P7H manifest only after decision, report, and the artifact
# registry exist. The manifest itself is excluded to avoid a self-hash cycle.
generated <- c(
  "analysis/p7h_manuscript_integration/p7h_prespecification.md",
  "analysis/p7h_manuscript_integration/p7h_manuscript_integration_report.md",
  "analysis/p7h_manuscript_integration/scripts/build_p7h_manuscript_package.R",
  "analysis/p7h_manuscript_integration/scripts/validate_p7h_outputs.R",
  "analysis/p7h_manuscript_integration/results/p7h_decision.json",
  "analysis/p7h_manuscript_integration/results/p7h_numerical_traceability.csv",
  "analysis/p7h_manuscript_integration/results/predictor_standardized_associations.csv",
  "analysis/p7h_manuscript_integration/results/predictor_dependence_pairs.csv",
  "analysis/p7h_manuscript_integration/results/support_horizon_calibration_metrics.csv",
  "analysis/p7h_manuscript_integration/results/support_horizon_bootstrap_ci.csv",
  "analysis/p7h_manuscript_integration/results/p7h_claim_audit.csv",
  "analysis/p7h_manuscript_integration/results/p7h_predictor_figure_replacement.json",
  "analysis/p7h_manuscript_integration/results/p7h_source_registry.csv",
  "analysis/p7h_manuscript_integration/results/p7h_publication_artifact_registry.csv",
  "analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.svg",
  "analysis/p7h_manuscript_integration/figures/figure_06_predictor_associations_standardized.png",
  "analysis/p7_publication/results/claim_registry.csv",
  "analysis/p7_publication/results/methods_summary.md",
  "analysis/p7_publication/results/results_draft.md",
  "analysis/p7_publication/results/results_synthesis.md",
  "analysis/p7_publication/results/limitations_draft.md",
  "analysis/p7_publication/results/discussion_outline.md",
  "analysis/p7_publication/results/publication_reviewer_checklist.md",
  "analysis/p7_publication/tables/table_5_limitation_summary.csv",
  "analysis/p7_publication/p7_publication_report.md",
  "analysis/p7f_final_figures/results/figure_source_registry.csv",
  "analysis/p7f_final_figures/captions/final_captions.md")
generated <- generated[file.exists(vapply(generated, abs_path, character(1L)))]
output_hashes <- setNames(vapply(generated, function(x) sha256_file(abs_path(x)), character(1L)), generated)
p7h_manifest$output_hashes_excluding_manifest <- as.list(output_hashes)
atomic_json(p7h_manifest, abs_path("analysis/p7h_manuscript_integration/results/p7h_provenance_manifest.json"))
if (file.exists(p7_manifest_path)) {
  p7_manifest <- jsonlite::fromJSON(p7_manifest_path, simplifyVector = FALSE)
  p7_manifest$p7h_integration$manifest_sha256 <- sha256_file(abs_path("analysis/p7h_manuscript_integration/results/p7h_provenance_manifest.json"))
  p7_manifest$generation_timestamp_utc <- format(Sys.time(), tz = "UTC", usetz = TRUE)
  atomic_json(p7_manifest, p7_manifest_path)
}
package_manifest_path <- abs_path("analysis/p7_publication/release_candidate/package_manifest.json")
if (file.exists(package_manifest_path)) {
  package_manifest <- jsonlite::fromJSON(package_manifest_path, simplifyVector = FALSE)
  package_manifest$included <- unique(c(package_manifest$included,
                                        "analysis/p7h_manuscript_integration",
                                        "analysis/p7g_manuscript_evidence/results",
                                        "analysis/p7g_manuscript_evidence/figures"))
  package_manifest$manifest <- "analysis/p7h_manuscript_integration/results/p7h_provenance_manifest.json"
  atomic_json(package_manifest, package_manifest_path)
}

if (verify_only) {
  required_outputs <- c(
    "analysis/p7h_manuscript_integration/p7h_prespecification.md",
    "analysis/p7h_manuscript_integration/p7h_manuscript_integration_report.md",
    "analysis/p7h_manuscript_integration/results/p7h_decision.json",
    "analysis/p7h_manuscript_integration/results/p7h_source_registry.csv",
    "analysis/p7h_manuscript_integration/results/p7h_numerical_traceability.csv",
    "analysis/p7_publication/results/claim_registry.csv",
    "analysis/p7_publication/results/results_synthesis.md",
    "analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.svg",
    "analysis/p7f_final_figures/figures/main/figure_06_predictor_associations.png")
  missing <- required_outputs[!file.exists(vapply(required_outputs, abs_path, character(1L)))]
  if (length(missing)) stopf("P7H outputs missing: %s", paste(missing, collapse = ", "))
  cat("P7H_MANUSCRIPT_PACKAGE_VERIFIED\n")
  quit(save = "no", status = 0L)
}

cat("P7H_MANUSCRIPT_PACKAGE_BUILT\n")
cat(sprintf("canonical_main_sha=%s\n", git_sha))
cat(sprintf("p7g_artifacts_verified=%d\n", length(p7g_manifest$artifacts)))
cat(sprintf("trace_rows=%d\n", nrow(trace)))
cat("no_model_fitting=true\n")
