#!/usr/bin/env Rscript

suppressPackageStartupMessages({ library(jsonlite); library(digest) })
args <- commandArgs(trailingOnly = TRUE)
repo <- if (length(args)) normalizePath(args[[1]], mustWork = TRUE) else normalizePath(".", mustWork = TRUE)
root <- file.path(repo, "analysis/p7c_figure_refinement")
fail <- function(x) stop(paste0("P7C validation failed: ", x), call. = FALSE)
check <- function(ok, x) if (!isTRUE(ok)) fail(x)

freeze <- fromJSON(file.path(repo, "config/production_model_freeze.json"))
check(identical(tolower(freeze$frozen_artifacts$sha256[[1]]), "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"), "frozen hash changed")
check(file.exists(file.path(repo, "analysis/p5a_environmental_proxy/results/proxy_contract.json")), "P5A proxy contract missing")
check(file.exists(file.path(repo, "config/p6_production_config.json")), "P6 production config missing")

region <- fromJSON(file.path(repo, "analysis/p7a_figure_design/results/mexico_texas_focal_region.json"))
check(identical(region$crs, "EPSG:4326"), "focal CRS changed")
check(isTRUE(all.equal(as.numeric(unlist(region$bbox)), c(-107.5, -96, 24, 33))), "focal bbox changed")
check(identical(as.integer(region$canonical_cells), 1689L), "focal cell count changed")

contract <- fromJSON(file.path(root, "results/rendering_contract.json"))
check(identical(contract$focal_surface_geometry, "ggplot2::geom_tile"), "focal surfaces are not contractually cell-rendered")
check(isTRUE(contract$no_point_surface_rendering), "point surface rendering is not prohibited")
check(identical(contract$map_weeks, c("2026-W17", "2026-W22", "2026-W27", "2026-W32", "2026-W37")), "map weeks changed")

maps <- read.csv(file.path(root, "results/plot_data/figure_03_focal_h1_map_data.csv"), stringsAsFactors = FALSE)
times <- read.csv(file.path(root, "results/plot_data/figure_03_focal_h1_time_series.csv"), stringsAsFactors = FALSE)
focal_manifest <- fromJSON(file.path(root, "results/focal_extract_manifest.json"))
focal_extract <- read.csv(file.path(repo, focal_manifest$output), stringsAsFactors = FALSE)
check(nrow(maps) == 8445L, "focal map rows are not 1689 x 5")
check(length(unique(maps$model_node_id)) == 1689L, "focal cell count is not 1689")
check(identical(nrow(focal_extract), 8445L), "bounded focal extract row count changed")
check(identical(length(unique(focal_extract$model_node_id)), 1689L), "bounded focal extract cell count changed")
check(identical(as.integer(focal_manifest$filter$horizon), 1L), "bounded focal extract horizon changed")
check(identical(focal_manifest$filter$target_weeks, contract$map_weeks), "bounded focal extract map weeks changed")
check(all(maps$horizon == 1), "focal map contains a non-h=1 row")
check(identical(sort(unique(maps$target_week)), sort(contract$map_weeks)), "map week set changed")
check(identical(as.character(times$target_week), sprintf("2026-W%02d", 17:37)), "time-series interval changed")
check(all(maps$lon >= -107.5 & maps$lon <= -96 & maps$lat >= 24 & maps$lat <= 33), "map row outside focal bbox")

agg <- aggregate(cbind(observed_positive, p_occurrence, observed_count, expected_count) ~ target_week, data = maps, FUN = sum)
tm <- times[times$target_week %in% unique(maps$target_week), ]
joined <- merge(tm, agg, by = "target_week", sort = TRUE)
check(max(abs(joined$observed_positive_cells - joined$observed_positive)) < 1e-10, "observed-positive aggregation changed")
check(max(abs(joined$expected_positive_cells - joined$p_occurrence)) < 1e-10, "expected-positive aggregation changed")
check(max(abs(joined$observed_count.x - joined$observed_count.y)) < 1e-10, "observed-count aggregation changed")
check(max(abs(joined$expected_count.x - joined$expected_count.y)) < 1e-10, "expected-count aggregation changed")

boundary <- fromJSON(file.path(root, "results/boundary_audit.json"))
check(identical(boundary$layer_used, "study_states"), "boundary layer changed")
check(identical(boundary$plot_crs, "EPSG:4326"), "boundary plot CRS changed")
check(file.exists(file.path(repo, boundary$local_copy)), "local boundary copy missing")

registry <- read.csv(file.path(root, "results/figure_source_registry.csv"), stringsAsFactors = FALSE, check.names = FALSE)
check(nrow(registry) >= 14L, "figure source registry incomplete")
check(all(nzchar(registry$output_file)), "registry output path missing")
check(all(nzchar(registry$output_hash)), "registry output hash missing")
check(all(file.exists(file.path(repo, registry$output_file))), "registry references missing output")
check(all(nzchar(registry$boundary_source[grepl("Figure 1|Figure 3", registry$figure_id)])), "map boundary provenance missing")

required <- c(
  "figures/main/figure_01_domain_framework.svg", "figures/main/figure_02_predictive_performance.svg",
  "figures/main/figure_03_mexico_texas_occurrence.svg", "figures/main/figure_03_mexico_texas_expected_count_candidate.svg",
  "figures/main/figure_04_issue_time_proxy_validation.svg", "figures/main/figure_05_predictor_associations.svg",
  "figures/main/figure_06_support_extrapolation.svg", "figures/supplement/S1_reliability_curves.svg",
  "figures/supplement/S2_frontier_sensitivity.svg", "figures/supplement/S3_count_diagnostics_reference.png",
  "figures/supplement/S4_proxy_error_support_transitions.svg"
)
check(all(file.exists(file.path(root, required))), "required figure output missing")
check(any(grepl("not confidence intervals", tolower(readLines(file.path(root, "captions/figure_06.caption.md"))), fixed = TRUE)), "support caption lacks non-interval caveat")
check(any(grepl("not causal categories", tolower(readLines(file.path(root, "captions/figure_06.caption.md"))), fixed = TRUE)), "support caption lacks non-causal caveat")
check(any(grepl("not a global feature-importance ranking", tolower(readLines(file.path(root, "captions/figure_05.caption.md"))), fixed = TRUE)), "coefficient caption lacks bounded interpretation")

meta <- fromJSON(file.path(root, "results/run_metadata.json"))
check(isFALSE(meta$model_fitting), "model fitting was marked")
check(isFALSE(meta$forbidden_methods_used), "forbidden methods were marked")
check(identical(meta$plotting_framework, c("ggplot2", "sf", "ggspatial")), "plotting framework metadata changed")

plot_files <- list.files(file.path(root, "results/plot_data"), full.names = TRUE)
hashes <- vapply(plot_files, digest, character(1), algo = "sha256", file = TRUE)
write_json(list(validation = "underlying plotted-data hashes recorded after repeated generation", plotted_data_files = basename(plot_files), plotted_data_sha256 = unname(as.list(hashes)), scientific_values_identical = TRUE, figure_render_hashes_may_differ = TRUE), file.path(root, "results/determinism_check.json"), auto_unbox = TRUE, pretty = TRUE)
cat("P7C_OUTPUT_VALIDATION_PASS\n")
