#!/usr/bin/env Rscript

suppressPackageStartupMessages({library(jsonlite); library(digest)})
args <- commandArgs(trailingOnly = TRUE)
repo <- if (length(args)) normalizePath(args[[1]], mustWork = TRUE) else normalizePath(".", mustWork = TRUE)
root <- file.path(repo, "analysis", "p7d_cartography_forecast")
results <- file.path(root, "results")
failures <- character()
check <- function(ok, message) if (!isTRUE(ok)) failures <<- c(failures, message)
read_csv <- function(path) read.csv(path, stringsAsFactors = FALSE, check.names = FALSE)
sha256 <- function(path) digest(path, algo = "sha256", file = TRUE)
need <- function(path) { check(file.exists(path), paste("missing:", path)); path }

freeze <- fromJSON(need(file.path(repo, "config", "production_model_freeze.json")))
check(identical(as.character(freeze$identity$model_id), "STRUCTURED_A3"), "model ID is not STRUCTURED_A3")
proxy <- fromJSON(need(file.path(repo, "analysis", "p5a_environmental_proxy", "results", "proxy_contract.json")))
check("E0_LAST_AVAILABLE" %in% as.character(proxy$proxy_ids), "P5A proxy is not E0_LAST_AVAILABLE")
p6 <- fromJSON(need(file.path(repo, "config", "p6_production_config.json")))
check(identical(as.character(p6$scientific_model$model_id), "STRUCTURED_A3"), "P6 model ID mismatch")
check(identical(as.character(p6$scientific_model$artifact_sha256), "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"), "P6 model hash mismatch")

contract <- fromJSON(need(file.path(results, "rendering_contract.json")))
check(identical(as.character(contract$crs), "EPSG:4326"), "rendering CRS mismatch")
check(identical(as.numeric(contract$focal_bbox), c(-107.5, -96.0, 24.0, 33.0)), "focal bbox changed")
check(identical(as.integer(contract$focal_cells), 1689L), "focal cell contract changed")
check(identical(as.integer(contract$map_horizon), 1L), "map horizon is not h=1")
check(identical(as.character(contract$uncertainty_ribbon), "NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS"), "uncertainty status changed")
check(identical(as.character(contract$forecast_issue_week), "2026-W36"), "forecast issue week changed")
check(identical(as.character(contract$forecast_targets), c("2026-W37", "2026-W38", "2026-W39")), "forecast target weeks changed")

domain <- read_csv(need(file.path(results, "plot_data", "figure_01_domain_framework_data.csv")))
maps <- read_csv(need(file.path(results, "plot_data", "figure_03_focal_h1_map_data.csv")))
times <- read_csv(need(file.path(results, "plot_data", "figure_03_focal_h1_time_series.csv")))
support <- read_csv(need(file.path(results, "plot_data", "figure_06_cell_level_support_map_data.csv")))
traj <- read_csv(need(file.path(results, "atlas_extract", "mexico_texas_issue_W36_forecast_trajectory.csv")))
agg <- read_csv(need(file.path(results, "plot_data", "forecast_trajectory_aggregates.csv")))
check(nrow(domain) == 10037L, paste("domain row count:", nrow(domain)))
focal <- domain[domain$lon >= -107.5 & domain$lon <= -96.0 & domain$lat >= 24.0 & domain$lat <= 33.0, , drop = FALSE]
check(nrow(focal) == 1689L, paste("focal cell count:", nrow(focal)))
check(all(c("Mexico", "U.S.-to-40N") %in% unique(as.character(focal$region))), "focal Figure 1 does not contain both domain colors")
check(identical(sort(unique(as.character(maps$target_week))), sort(c("2026-W17", "2026-W22", "2026-W27", "2026-W32", "2026-W37"))), "Figure 3 weeks changed")
check(all(maps$horizon == 1), "Figure 3 contains non-h=1 rows")
check(nrow(maps) == 8445L, paste("Figure 3 row count:", nrow(maps)))
check(all(maps$lon >= -107.5 & maps$lon <= -96.0 & maps$lat >= 24.0 & maps$lat <= 33.0), "Figure 3 extends beyond focal bbox")
check(nrow(support) == 10037L && length(unique(support$model_node_id)) == 10037L, "support map is not the complete canonical cell set")
check(identical(sort(unique(as.character(support$support_class))), sort(c("CAUTION", "EXTRAPOLATIVE", "SUPPORTED"))), "support classes changed")
check(all(c("geom_tile", "geom_sf") %in% as.character(contract$figure_6_layers)), "Figure 6 tile/boundary contract missing")
support_audit <- fromJSON(need(file.path(results, "support_source_audit.json")))
check(isFALSE(as.logical(support_audit$prior_point_map_reused)), "prior point-rendered support map was reused")

history <- traj[traj$trajectory_role == "observed_history" & traj$horizon == 1 & traj$target_week %in% sprintf("2026-W%02d", 17:36), , drop = FALSE]
future <- traj[traj$trajectory_role == "issue_W36_forecast" & traj$origin_week == "2026-W36" & traj$target_week %in% c("2026-W37", "2026-W38", "2026-W39") & traj$horizon %in% 1:3, , drop = FALSE]
check(nrow(history) == 33780L, paste("history extract rows:", nrow(history)))
check(nrow(future) == 5067L, paste("future extract rows:", nrow(future)))
check(identical(sort(unique(as.character(future$target_week))), c("2026-W37", "2026-W38", "2026-W39")), "future target alignment changed")
check(identical(sort(unique(as.integer(future$horizon))), c(1L, 2L, 3L)), "future horizon alignment changed")
check(all(future$origin_week == "2026-W36"), "future rows contain a different forecast origin")
check(all(future$observation_status == "subsequently_observed_only"), "future outcomes are not explicitly isolated from issue-time forecast fields")

hist_expected <- aggregate(cbind(p_occurrence, expected_count) ~ target_week, history, sum)
hist_observed <- aggregate(cbind(observed_positive, observed_count) ~ target_week, history, sum)
names(hist_expected)[2:3] <- c("expected_positive_cells", "expected_count")
names(hist_observed)[2:3] <- c("observed_positive_cells", "observed_count")
expected <- merge(hist_expected, hist_observed, by = "target_week")
expected <- expected[, c("target_week", "observed_positive_cells", "expected_positive_cells", "observed_count", "expected_count")]
hist_agg <- agg[agg$segment == "historical_h1", c("target_week", "observed_positive_cells", "expected_positive_cells", "observed_count", "expected_count"), drop = FALSE]
check(nrow(hist_agg) == 20L, "historical trajectory aggregate does not have 20 weeks")
check(isTRUE(all.equal(hist_agg[order(hist_agg$target_week), ], expected[order(expected$target_week), ], check.attributes = FALSE, tolerance = 1e-10)), "historical trajectory aggregate formula mismatch")

future_calc <- aggregate(cbind(p_occurrence, expected_count) ~ target_week + horizon, future, sum)
names(future_calc)[3:4] <- c("expected_positive_cells", "expected_count")
future_agg <- agg[agg$segment == "issue_W36_forecast", c("target_week", "horizon", "expected_positive_cells", "expected_count"), drop = FALSE]
check(isTRUE(all.equal(future_agg[order(future_agg$target_week, future_agg$horizon), ], future_calc[order(future_calc$target_week, future_calc$horizon), ], check.attributes = FALSE, tolerance = 1e-10)), "forecast trajectory aggregate formula mismatch")

unc <- fromJSON(need(file.path(results, "uncertainty_audit.json")))
check(identical(as.character(unc$status), "NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS"), "uncertainty audit status mismatch")
check(isFALSE(as.logical(unc$ribbon_drawn)), "uncertainty ribbon was drawn")
meta <- fromJSON(need(file.path(results, "run_metadata.json")))
check(isFALSE(as.logical(meta$model_fitting)), "run metadata permits model fitting")
check(isFALSE(as.logical(meta$scientific_model_modified)), "run metadata permits scientific modification")

registry <- read_csv(need(file.path(results, "figure_source_registry.csv")))
check(nrow(registry) >= 9L, "source registry is incomplete")
check(all(file.exists(file.path(repo, registry$output_file))), "source registry contains a missing output")
check(all(vapply(seq_len(nrow(registry)), function(i) sha256(file.path(repo, registry$output_file[[i]])) == registry$output_hash[[i]], logical(1))), "source registry output hash mismatch")
check(all(grepl("generate_p7d_figures.R|P7C canonical renderer", registry$plotting_script)), "registry plotting provenance is incomplete")
script_text <- paste(readLines(file.path(root, "scripts", "generate_p7d_figures.R"), warn = FALSE), collapse = "\n")
check(grepl("geom_tile", script_text) && grepl("geom_sf", script_text), "tile/boundary rendering is not encoded in generator")
check(!grepl("p4_support <-|rasterGrob", script_text), "generator contains an unauthorized raster support reuse")
check(grepl("NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS", script_text), "uncertainty limitation is not encoded in generator")

if (length(failures)) {
  cat("P7D_VALIDATION_FAILED\n", paste0("- ", failures, collapse = "\n"), "\n", sep = "")
  quit(status = 1)
}
cat("P7D_VALIDATION_PASSED\n")

