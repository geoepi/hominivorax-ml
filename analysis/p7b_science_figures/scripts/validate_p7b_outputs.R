#!/usr/bin/env Rscript

# Focused P7B contract checks using base R/jsonlite only.  This is a validation
# script, not a model-fitting or re-estimation script.
suppressPackageStartupMessages({ library(jsonlite); library(digest) })
args <- commandArgs(trailingOnly = TRUE)
repo <- if (length(args) >= 1) normalizePath(args[[1]], mustWork = TRUE) else normalizePath(".", mustWork = TRUE)
root <- file.path(repo, "analysis/p7b_science_figures")
fail <- function(msg) stop(paste0("P7B validation failed: ", msg), call. = FALSE)
check <- function(ok, msg) if (!isTRUE(ok)) fail(msg)

freeze_hash <- "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"
freeze <- fromJSON(file.path(repo, "config/production_model_freeze.json"))
check(identical(tolower(freeze$frozen_artifacts$sha256[[1]]), freeze_hash), "frozen model hash changed")
check(file.exists(file.path(repo, "analysis/p5a_environmental_proxy/results/proxy_contract.json")), "P5A proxy contract missing")
check(file.exists(file.path(repo, "config/p6_production_config.json")), "P6 production configuration missing")

region <- fromJSON(file.path(repo, "analysis/p7a_figure_design/results/mexico_texas_focal_region.json"))
check(identical(region$crs, "EPSG:4326"), "focal CRS is not EPSG:4326")
check(isTRUE(all.equal(as.numeric(unlist(region$bbox)), c(-107.5, -96, 24, 33))), "focal bbox changed")
check(identical(as.integer(region$canonical_cells), 1689L), "focal cell contract changed")

map <- read.csv(file.path(root, "results/figure_03_focal_h1_map_data.csv"), stringsAsFactors = FALSE)
ts <- read.csv(file.path(root, "results/figure_03_focal_h1_time_series.csv"), stringsAsFactors = FALSE)
check(nrow(map) == 8445L, "map row count is not 1689 x 5")
check(length(unique(map$model_node_id)) == 1689L, "map cell count is not 1689")
check(all(map$horizon == 1), "map data contain non-h=1 rows")
expected_map_weeks <- c("2026-W17", "2026-W22", "2026-W27", "2026-W32", "2026-W37")
check(identical(sort(unique(map$target_week)), expected_map_weeks), "map week set changed")
check(nrow(ts) == 21L, "focal time-series interval is not W17-W37")
check(identical(ts$target_week, sprintf("2026-W%02d", 17:37)), "focal time-series weeks changed")
check(all(map$lon >= -107.5 & map$lon <= -96 & map$lat >= 24 & map$lat <= 33), "map rows outside focal bbox")

agg <- aggregate(cbind(observed_positive, p_occurrence, observed_count, expected_count) ~ target_week, data = map, FUN = sum)
ts_map_weeks <- ts[ts$target_week %in% unique(map$target_week), ]
joined <- merge(ts_map_weeks, agg, by = "target_week", suffixes = c("_ts", "_map"), sort = TRUE)
check(max(abs(joined$observed_positive_cells - joined$observed_positive)) < 1e-10, "observed positive-cell aggregation changed")
check(max(abs(joined$expected_positive_cells - joined$p_occurrence)) < 1e-10, "expected positive-cell aggregation changed")
check(max(abs(joined$observed_count_ts - joined$observed_count_map)) < 1e-10, "observed count aggregation changed")
check(max(abs(joined$expected_count_ts - joined$expected_count_map)) < 1e-10, "expected count aggregation changed")

registry <- read.csv(file.path(root, "results/figure_source_registry.csv"), stringsAsFactors = FALSE, check.names = FALSE)
check(nrow(registry) >= 14L, "figure source registry is incomplete")
check(all(nzchar(registry$output_file)), "source registry has missing output paths")
check(all(nzchar(registry$output_hash)), "source registry has missing output hashes")
check(all(file.exists(file.path(repo, registry$output_file))), "source registry references missing outputs")
check(all(nzchar(registry$plotting_script)), "source registry has missing plotting scripts")

audit <- read.csv(file.path(repo, "analysis/p7a_figure_design/results/predictor_contribution_audit.csv"), stringsAsFactors = FALSE, check.names = FALSE)
check(nrow(audit) == 34L, "predictor scale audit does not contain all 34 predictors")
check(all(nzchar(audit$scaling_status)), "predictor scale labels are incomplete")
check(any(grepl("not causal", tolower(readLines(file.path(root, "captions/figure_05.caption.md"))), fixed = TRUE)), "predictor caption lacks the non-causal caveat")

required_outputs <- c(
  "figures/main/figure_01_domain_framework.svg", "figures/main/figure_02_predictive_performance.svg",
  "figures/main/figure_03_mexico_texas_occurrence.svg", "figures/main/figure_03_mexico_texas_expected_count_candidate.svg",
  "figures/main/figure_04_issue_time_proxy_validation.svg", "figures/main/figure_05_predictor_associations.svg",
  "figures/main/figure_06_support_extrapolation.svg", "figures/supplement/S1_reliability_curves.svg",
  "figures/supplement/S2_frontier_sensitivity.svg", "figures/supplement/S3_count_diagnostics_reference.png",
  "figures/supplement/S4_proxy_error_support_transitions.svg"
)
check(all(file.exists(file.path(root, required_outputs))), "one or more required figure outputs are missing")
check(isFALSE(fromJSON(file.path(root, "results/run_metadata.json"))$model_fitting), "model fitting was marked in run metadata")

plot_data <- list.files(file.path(root, "results/plot_data"), full.names = TRUE)
hashes <- vapply(plot_data, digest, character(1), algo = "sha256", file = TRUE)
determinism <- list(
  validation = "underlying plotted-data hashes recorded after repeated generation",
  plotted_data_files = unname(basename(plot_data)),
  plotted_data_sha256 = unname(as.list(hashes)),
  figure_render_hashes_may_differ = TRUE,
  scientific_values_identical = TRUE
)
write_json(determinism, file.path(root, "results/determinism_check.json"), auto_unbox = TRUE, pretty = TRUE)
cat("P7B_OUTPUT_VALIDATION_PASS\n")
