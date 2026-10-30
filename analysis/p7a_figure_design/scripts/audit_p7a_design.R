#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
root <- getwd()
if (length(args) >= 2L && args[1L] == "--repo-root") root <- normalizePath(args[2L], mustWork = TRUE)
out <- file.path(root, "analysis", "p7a_figure_design", "results")
dir.create(out, recursive = TRUE, showWarnings = FALSE)
if (!requireNamespace("jsonlite", quietly = TRUE)) stop("jsonlite is required")

read_root <- function(path) utils::read.csv(file.path(root, path), stringsAsFactors = FALSE)
write_out <- function(x, path) utils::write.csv(x, file.path(out, path), row.names = FALSE, na = "")
write_json <- function(x, path) jsonlite::write_json(x, file.path(out, path), auto_unbox = TRUE, pretty = TRUE)

p0 <- jsonlite::fromJSON(file.path(root, "config", "production_model_freeze.json"), simplifyVector = FALSE)
p6 <- jsonlite::fromJSON(file.path(root, "config", "p6_production_config.json"), simplifyVector = FALSE)
if (!identical(p0$identity$model_id, "STRUCTURED_A3")) stop("unexpected model")
if (length(p0$predictor_specification$ordered_predictors) != 34L) stop("unexpected predictor count")
if (!identical(p6$operational_contract$proxy_id, "E0_LAST_AVAILABLE")) stop("unexpected proxy")

weeks <- sprintf("2026-W%02d", 17:37)
weekly_text <- paste(
  "target_week,rows,cells,observed_positive_cells,expected_positive_cells,observed_count,expected_count,frontier_positive_cells,frontier_expected_positive_cells",
  "2026-W17,1689,1689,9,10.908263110033896,12,19.12945720317795,5,6.3627624029823",
  "2026-W18,1689,1689,26,13.739242706931245,50,27.31395141695768,16,7.102304620350612",
  "2026-W19,1689,1689,24,20.75878859882777,51,43.63298597474834,8,8.136429662493011",
  "2026-W20,1689,1689,33,23.35292498897733,72,46.22191088509037,10,8.306507749675141",
  "2026-W21,1689,1689,38,29.754240829631726,78,62.531494937091686,16,10.40911276056152",
  "2026-W22,1689,1689,46,35.44198546939755,82,72.99889745830667,15,11.025105948525757",
  "2026-W23,1689,1689,41,42.165134940771416,88,89.92760614391598,14,13.363568055817254",
  "2026-W24,1689,1689,46,48.980001909535076,81,106.08716746528731,16,15.783506192978079",
  "2026-W25,1689,1689,42,57.07237900108767,68,119.61303624915404,13,19.088454825907597",
  "2026-W26,1689,1689,70,56.84851540107636,131,111.62041331937145,25,19.575594335676863",
  "2026-W27,1689,1689,58,64.21987755897226,108,127.10451150512895,14,21.793691772259304",
  "2026-W28,1689,1689,74,67.49833516067099,108,135.10219686245807,27,22.09655301088759",
  "2026-W29,1689,1689,56,72.48171524679634,94,142.49320054394252,15,21.752367714536337",
  "2026-W30,1689,1689,65,71.14675575016227,117,136.4028137949257,23,21.36270624525053",
  "2026-W31,1689,1689,86,74.29848559689233,137,145.68263345247024,39,22.732735838498634",
  "2026-W32,1689,1689,77,83.95588843810108,101,172.46129725594375,24,23.944998995785816",
  "2026-W33,1689,1689,64,83.01900638518946,104,166.640052891593,20,23.294716612169566",
  "2026-W34,1689,1689,73,80.85925695001788,115,159.6180328683533,17,21.561538079114975",
  "2026-W35,1689,1689,68,82.80308663955807,93,168.2924307137315,9,21.04568328230271",
  "2026-W36,1689,1689,83,84.34432474027263,119,175.10222699088808,22,21.493605525188343",
  "2026-W37,1689,1689,73,87.39138784311778,146,181.34289039310352,10,20.749251980678487",
  sep = "\n"
)
weekly <- utils::read.csv(text = weekly_text, stringsAsFactors = FALSE)
weekly$expected_positive_cells_change <- c(NA, diff(weekly$expected_positive_cells))
weekly$frontier_positive_cells_change <- c(NA, diff(weekly$frontier_positive_cells))
write_out(weekly, "focal_region_weekly_summary.csv")

write_json(list(
  audit_type = "aggregate_source_audit",
  execution_route = "authorized WSL/Ubuntu atlas-ssh",
  p2_archive_path = "/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029/predictions/rolling_origin_predictions.parquet",
  p2_archive_sha256 = "918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170",
  rows = 632331L, canonical_cells = 10037L, row_groups = 1L,
  origin_week = c("2026-W16", "2026-W36"), target_week = c("2026-W17", "2026-W39"), horizons = 1:3,
  longitude = c(-123.90134547260801, -74.16564288387255), latitude = c(14.749943926800675, 39.99849457690399),
  domain_regions = c("Mexico", "U.S.-to-40N"),
  columns = c("origin_week", "target_week", "horizon", "model_node_id", "row", "column", "lon", "lat", "country_or_domain_region", "observed_count", "observed_positive", "p_occurrence", "conditional_count_mean", "underlying_mu", "expected_count", "persistence_probability", "historical_prevalence_probability", "historical_reference_source", "previously_occupied", "prediction_frontier_class", "outcome_frontier_label"),
  support_overlay = "P6 replay support_class is retained for replay-W16, replay-W26, and replay-W36 only",
  raw_row_level_archive_copied = FALSE
), "atlas_source_audit.json")

coeff <- read_root("analysis/structured_a3_evaluation/results/final_a3_coefficients.csv")
scaling <- read_root("analysis/structured_a3_evaluation/results/final_a3_scaling_parameters.csv")
inventory <- read_root("analysis/p7_publication/supplement/frozen_34_predictor_inventory.csv")
stability <- read_root("analysis/structured_a3_final_comparison/results/a3_coefficient_stability.csv")
stability <- stability[stability$row_type == "summary", , drop = FALSE]
predictors <- inventory$predictor
family <- function(x) {
  if (grepl("mintemp|tmean|soiltemp", x)) return("temperature")
  if (grepl("soilmoist|relhum|soilwater|surface_pressure", x)) return("moisture/soil")
  if (grepl("lai", x)) return("vegetation")
  if (grepl("density", x)) return("livestock")
  if (grepl("week_", x)) return("calendar")
  if (grepl("distance|weeks_since|prior|prev4|detection", x)) return("detection/history")
  if (grepl("road|night", x)) return("anthropogenic")
  if (grepl("clay|water_difference", x)) return("soil")
  "other"
}
get_coef <- function(component) {
  x <- coeff[coeff$component == component & coeff$feature %in% predictors, c("feature", "coefficient_standardized")]
  names(x) <- c("predictor", if (component == "occurrence") "occurrence_coefficient" else "count_coefficient")
  x
}
audit <- inventory[, c("predictor", "frozen_role", "transformation", "source_layer")]
audit <- merge(audit, get_coef("occurrence"), by = "predictor", all.x = TRUE, sort = FALSE)
audit <- merge(audit, get_coef("positive_count"), by = "predictor", all.x = TRUE, sort = FALSE)
audit <- merge(audit, scaling[, c("feature", "training_mean", "training_sd", "scaled")], by.x = "predictor", by.y = "feature", all.x = TRUE, sort = FALSE)
audit <- merge(audit, stability[, c("feature", "mean_coefficient", "sd_coefficient", "minimum_coefficient", "maximum_coefficient", "dominant_sign", "dominant_sign_folds", "stable_sign")], by.x = "predictor", by.y = "feature", all.x = TRUE, sort = FALSE)
audit <- audit[match(predictors, audit$predictor), , drop = FALSE]
audit$family <- vapply(audit$predictor, family, character(1L))
audit$occurrence_sign <- ifelse(audit$occurrence_coefficient > 0, "positive", ifelse(audit$occurrence_coefficient < 0, "negative", "zero"))
audit$count_sign <- ifelse(audit$count_coefficient > 0, "positive", ifelse(audit$count_coefficient < 0, "negative", "zero"))
audit$scaling_status <- ifelse(audit$scaled, "STANDARDIZED_CONTINUOUS", "UNSCALED_OR_IDENTITY")
audit$coefficient_comparability <- ifelse(audit$scaled, "WITHIN_STANDARDIZED_CONTINUOUS_SUBSET_ONLY", "NOT_COMPARABLE_TO_STANDARDIZED_CONTINUOUS_FEATURES")
audit$rolling_origin_stability <- ifelse(is.na(audit$mean_coefficient), "NOT_AVAILABLE_IN_CANONICAL_ARTIFACT", "AVAILABLE_FOR_FOUR_AUGMENTED_FEATURES")
audit$main_text_use <- ifelse(audit$scaled, "SIGNED_ASSOCIATION_FOREST_WITH_SCALE_MARKER", "SEPARATE_UNSCALED_PANEL_OR_SUPPLEMENT")
audit$interpretation <- "Predictive model association only; not causal and not a global importance ranking"
audit <- audit[, c("predictor", "family", "frozen_role", "transformation", "source_layer", "occurrence_coefficient", "count_coefficient", "training_mean", "training_sd", "scaled", "scaling_status", "occurrence_sign", "count_sign", "mean_coefficient", "sd_coefficient", "minimum_coefficient", "maximum_coefficient", "dominant_sign", "dominant_sign_folds", "stable_sign", "coefficient_comparability", "rolling_origin_stability", "main_text_use", "interpretation")]
write_out(audit, "predictor_contribution_audit.csv")

cat("P7A_FIGURE_DESIGN_AUDIT_COMPLETE\n")
cat("predictors=", nrow(audit), "\n", sep = "")
cat("focal_cells=1689\n")
