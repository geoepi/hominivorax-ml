#!/usr/bin/env Rscript

# P7C changes rendering and cartographic context only. No model fitting,
# refitting, recalibration, tuning, or new analytic method is performed.
suppressPackageStartupMessages({
  library(ggplot2); library(patchwork); library(dplyr); library(tidyr)
  library(sf); library(ggspatial); library(png); library(grid)
  library(jsonlite); library(digest)
})

args <- commandArgs(trailingOnly = TRUE)
repo <- if (length(args)) normalizePath(args[[1]], mustWork = TRUE) else normalizePath(".", mustWork = TRUE)
root <- file.path(repo, "analysis", "p7c_figure_refinement")
p7b <- file.path(repo, "analysis", "p7b_science_figures")
main <- file.path(root, "figures", "main"); supp <- file.path(root, "figures", "supplement")
tables <- file.path(root, "tables"); captions <- file.path(root, "captions")
results <- file.path(root, "results"); plot_data <- file.path(results, "plot_data")
boundary_path <- file.path(results, "boundaries", "study_states_wgs84.csv")
for (p in c(main, supp, tables, captions, results, plot_data)) dir.create(p, recursive = TRUE, showWarnings = FALSE)
if (!file.exists(boundary_path)) stop("missing P7C boundary source: ", boundary_path)

read_csv <- function(p) read.csv(p, stringsAsFactors = FALSE, check.names = FALSE)
sha256 <- function(p) digest(p, algo = "sha256", file = TRUE)
rel <- function(p) {
  p <- normalizePath(p, winslash = "/", mustWork = FALSE)
  pre <- paste0(normalizePath(repo, winslash = "/", mustWork = TRUE), "/")
  if (startsWith(p, pre)) substring(p, nchar(pre) + 1L) else p
}
write_data <- function(x, name) {
  p <- file.path(plot_data, name); write.csv(x, p, row.names = FALSE, quote = TRUE, na = ""); p
}
save_fig <- function(x, stem, width, height, dir = main) {
  svg <- file.path(dir, paste0(stem, ".svg")); pngp <- file.path(dir, paste0(stem, ".png"))
  ggsave(svg, x, device = svglite::svglite, width = width, height = height, units = "in", bg = "white")
  ggsave(pngp, x, device = "png", width = width, height = height, units = "in", dpi = 220, bg = "white")
  c(svg = svg, png = pngp)
}
theme_science <- theme_minimal(base_size = 10, base_family = "Arial") + theme(
  panel.background = element_rect(fill = "#f8fafc", colour = NA),
  panel.grid.major = element_line(colour = "#d9e2ec", linewidth = 0.25),
  panel.grid.minor = element_blank(), plot.title = element_text(face = "bold", colour = "#1f2937"),
  plot.subtitle = element_text(colour = "#52606d", size = 9), axis.title = element_text(size = 9),
  legend.position = "bottom", legend.title = element_text(size = 9), legend.text = element_text(size = 8),
  strip.text = element_text(face = "bold", colour = "#243b53"), plot.caption = element_text(size = 8, hjust = 0)
)
theme_map <- theme_science + theme(panel.grid.major = element_line(colour = "#cbd5e1", linewidth = 0.25))
support_cols <- c(SUPPORTED = "#009E73", CAUTION = "#E69F00", EXTRAPOLATIVE = "#D55E00")
horizon_cols <- c("h=1" = "#0072B2", "h=2" = "#E69F00", "h=3" = "#CC79A7")
fixed_bbox <- c(xmin = -107.5, xmax = -96, ymin = 24, ymax = 33)
bbox_rect <- data.frame(xmin = fixed_bbox[["xmin"]], xmax = fixed_bbox[["xmax"]], ymin = fixed_bbox[["ymin"]], ymax = fixed_bbox[["ymax"]])
map_weeks <- c("2026-W17", "2026-W22", "2026-W27", "2026-W32", "2026-W37")
time_weeks <- sprintf("2026-W%02d", 17:37)

tile_dims <- function(x) {
  dx <- x %>% arrange(.data$row, .data$column) %>% group_by(.data$row) %>% mutate(d = abs(.data$lon - lead(.data$lon))) %>% pull(.data$d)
  dy <- x %>% arrange(.data$column, .data$row) %>% group_by(.data$column) %>% mutate(d = abs(.data$lat - lead(.data$lat))) %>% pull(.data$d)
  dx <- dx[is.finite(dx) & dx > 0]; dy <- dy[is.finite(dy) & dy > 0]
  if (!length(dx) || !length(dy)) stop("cannot infer grid-cell dimensions")
  c(width = median(dx), height = median(dy))
}
map_aids <- function() list(
  annotation_scale(location = "bl", width_hint = 0.24, text_cex = 0.65, line_width = 0.6),
  annotation_north_arrow(location = "tl", which_north = "true",
    style = north_arrow_orienteering(text_size = 6, line_col = "#334e68", fill = c("#ffffff", "#334e68")))
)

domain <- read_csv(file.path(p7b, "results/figure_01_domain_grid.csv"))
maps <- read_csv(file.path(p7b, "results/figure_03_focal_h1_map_data.csv"))
times <- read_csv(file.path(p7b, "results/figure_03_focal_h1_time_series.csv"))
metrics <- read_csv(file.path(repo, "analysis/p2_operational_nowcast/results/horizon_metrics.csv")) %>%
  filter(.data$scope == "all", .data$region == "all", .data$horizon %in% c(1, 2, 3))
cal <- read_csv(file.path(repo, "analysis/p2_operational_nowcast/results/calibration_bins.csv")) %>%
  filter(.data$metric_family == "occurrence", .data$scope == "all", .data$horizon %in% c(1, 2, 3))
paired <- read_csv(file.path(repo, "analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv"))
boot <- read_csv(file.path(repo, "analysis/p5a_environmental_proxy/results/bootstrap_intervals.csv"))
env <- read_csv(file.path(repo, "analysis/p5a_environmental_proxy/results/environmental_proxy_error_by_family.csv"))
support <- read_csv(file.path(repo, "analysis/p5a_environmental_proxy/results/support_metrics.csv"))
support_perf <- read_csv(file.path(repo, "analysis/p4_uncertainty_extrapolation/results/performance_by_support.csv"))
frontier <- read_csv(file.path(repo, "analysis/p7_publication/supplement/frontier_sensitivity_metrics.csv"))
coef <- read_csv(file.path(repo, "analysis/p7a_figure_design/results/predictor_contribution_audit.csv"))
stability <- read_csv(file.path(repo, "analysis/structured_a3_final_comparison/results/a3_coefficient_stability.csv"))

domain$region <- ifelse(domain$country_or_domain_region == "Mexico", "Mexico", "U.S.-to-40N")
maps <- maps %>% filter(.data$horizon == 1, .data$target_week %in% map_weeks)
maps$target_week <- factor(as.character(maps$target_week), levels = map_weeks)
times <- times %>% filter(.data$target_week %in% time_weeks)
times$target_week <- factor(as.character(times$target_week), levels = time_weeks)
# Preserve a bounded, source-traceable focal extract for review and regeneration.
focal_extract_cols <- c("origin_week", "target_week", "horizon", "model_node_id", "row", "column",
                        "lon", "lat", "observed_count", "observed_positive", "p_occurrence",
                        "conditional_count_mean", "expected_count", "previously_occupied",
                        "prediction_frontier_class", "outcome_frontier_label")
focal_extract <- maps[, intersect(focal_extract_cols, names(maps)), drop = FALSE]
focal_extract_path <- file.path(results, "mexico_texas_focal_h1_2026w17_w37.csv")
write.csv(focal_extract, focal_extract_path, row.names = FALSE, quote = TRUE, na = "")
jsonlite::write_json(list(
  source_archive = rel(file.path(p7b, "results/figure_03_focal_h1_map_data.csv")),
  source_sha256 = sha256(file.path(p7b, "results/figure_03_focal_h1_map_data.csv")),
  filter = list(horizon = 1L, target_weeks = map_weeks, bbox = as.numeric(fixed_bbox)),
  fields = names(focal_extract), row_count = nrow(focal_extract),
  canonical_cell_count = length(unique(focal_extract$model_node_id)),
  extraction_script = "analysis/p7c_figure_refinement/scripts/generate_p7c_figures.R",
  output = rel(focal_extract_path), output_sha256 = sha256(focal_extract_path),
  scientific_status = "bounded derived extract; no model fitting or scientific transformation"
), file.path(results, "focal_extract_manifest.json"), auto_unbox = TRUE, pretty = TRUE)
dd <- tile_dims(domain); md <- tile_dims(maps)

boundary_raw <- st_as_sf(read_csv(boundary_path), wkt = "geometry_wkt", crs = 4326, remove = FALSE)
boundary_crs <- st_crs(boundary_raw)
boundary <- st_transform(st_make_valid(boundary_raw), 4326)
boundary_domain <- suppressWarnings(st_crop(boundary, c(xmin = min(domain$lon) - 1, xmax = max(domain$lon) + 1,
                                                         ymin = min(domain$lat) - 1, ymax = max(domain$lat) + 1)))
boundary_focal <- suppressWarnings(st_crop(boundary, fixed_bbox))
coord_domain <- coord_sf(xlim = c(min(domain$lon) - .5, max(domain$lon) + .5),
  ylim = c(min(domain$lat) - .5, max(domain$lat) + .5), expand = FALSE,
  crs = st_crs(4326), default_crs = st_crs(4326))
coord_focal <- coord_sf(xlim = fixed_bbox[c("xmin", "xmax")], ylim = fixed_bbox[c("ymin", "ymax")],
  expand = FALSE, crs = st_crs(4326), default_crs = st_crs(4326))

# Figure 1: domain/focal cells, model schematic, and E0 timeline.
p1a <- ggplot(domain, aes(.data$lon, .data$lat, fill = .data$region)) +
  geom_tile(width = dd[["width"]], height = dd[["height"]], alpha = .72) +
  geom_sf(data = boundary_domain, inherit.aes = FALSE, fill = NA, colour = "#52606d", linewidth = .12) +
  geom_rect(data = bbox_rect, aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax),
            inherit.aes = FALSE, fill = NA, colour = "#111827", linewidth = .7, linetype = 2) + coord_domain +
  scale_fill_manual(values = c(Mexico = "#56B4E9", `U.S.-to-40N` = "#E69F00")) +
  labs(title = "Canonical spatial domain", x = "Longitude", y = "Latitude", fill = "Domain") + map_aids() + theme_map
p1b <- ggplot(filter(domain, lon >= fixed_bbox[["xmin"]], lon <= fixed_bbox[["xmax"]], lat >= fixed_bbox[["ymin"]], lat <= fixed_bbox[["ymax"]]), aes(lon, lat)) +
  geom_tile(width = dd[["width"]], height = dd[["height"]], fill = "#56B4E9", alpha = .72) +
  geom_sf(data = boundary_focal, inherit.aes = FALSE, fill = NA, colour = "#52606d", linewidth = .15) +
  coord_focal + labs(title = "Fixed Mexico-Texas focal region", x = "Longitude", y = "Latitude") + map_aids() + theme_map
boxes <- data.frame(xmin = c(.04, .36, .69), xmax = c(.30, .62, .96), ymin = .58, ymax = .80,
                    label = c("34 predictors", "Occurrence\ncomponent", "Conditional positive-count\ncomponent"))
arrows <- data.frame(x = c(.30, .62), xend = c(.36, .69), y = .69, yend = .69)
p1c <- ggplot() + geom_rect(data = boxes, aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax), fill = "#e6f2ff", colour = "#2166ac") +
  geom_text(data = boxes, aes(x = (xmin + xmax) / 2, y = (ymin + ymax) / 2, label = label), size = 3) +
  geom_segment(data = arrows, aes(x = x, xend = xend, y = y, yend = yend), arrow = arrow(length = unit(.16, "cm")), linewidth = .6, colour = "#52606d") +
  annotate("text", x = .5, y = .34, label = "full expected count = occurrence probability x conditional positive count", size = 3) +
  annotate("text", x = .5, y = .14, label = "outputs: h=1, h=2, h=3", size = 3.5, fontface = "bold") +
  xlim(0, 1) + ylim(0, 1) + labs(title = "Frozen STRUCTURED_A3 hurdle structure") + theme_void()
proxy <- data.frame(x = 1:5, label = c("issue\nT", "latest\nL(T)", "h=1", "h=2", "h=3"), group = c("issue", "available", "target", "target", "target"))
p1d <- ggplot(proxy, aes(x, 0, colour = group)) + geom_segment(data = data.frame(x = 1, xend = 5, y = 0, yend = 0), aes(x = x, xend = xend, y = y, yend = yend), colour = "#52606d", arrow = arrow(length = unit(.18, "cm")), linewidth = .7) +
  geom_point(size = 3) + geom_text(aes(label = label), vjust = -1.1, size = 3.1) +
  scale_colour_manual(values = c(issue = "#222222", available = "#0072B2", target = "#009E73"), guide = "none") +
  xlim(.7, 5.3) + ylim(-.2, .3) + labs(title = "E0_LAST_AVAILABLE operational input", subtitle = "latest legitimate environmental state held across h=1 to h=3") +
  theme_void() + theme(plot.title = element_text(face = "bold", hjust = .5), plot.subtitle = element_text(hjust = .5, size = 8, colour = "#52606d"))
d1 <- write_data(domain, "figure_01_domain_framework_data.csv")
f1 <- save_fig((p1a | p1b) / (p1c | p1d) + plot_annotation(tag_levels = "A"), "figure_01_domain_framework", 13, 9)

# Figure 2: canonical P2 performance by horizon.
m2 <- metrics %>% mutate(horizon_label = paste0("h=", .data$horizon))
p2a <- ggplot(m2, aes(horizon_label, brier, colour = horizon_label)) + geom_line(aes(group = 1), colour = "#52606d", linewidth = .5) + geom_point(size = 3) + scale_colour_manual(values = horizon_cols) + labs(title = "Brier score", x = NULL, y = "Brier score (lower is better)") + theme_science + theme(legend.position = "none")
p2b <- ggplot(m2, aes(horizon_label, auprc, colour = horizon_label)) + geom_line(aes(group = 1), colour = "#52606d", linewidth = .5) + geom_point(size = 3) + scale_colour_manual(values = horizon_cols) + labs(title = "AUPRC", x = NULL, y = "AUPRC (higher is better)") + theme_science + theme(legend.position = "none")
cal2 <- m2 %>% select(horizon, calibration_intercept, calibration_slope) %>% pivot_longer(c(calibration_intercept, calibration_slope), names_to = "metric", values_to = "value") %>% mutate(horizon_label = paste0("h=", horizon), metric = recode(metric, calibration_intercept = "Calibration intercept", calibration_slope = "Calibration slope"), reference = ifelse(metric == "Calibration intercept", 0, 1))
p2c <- ggplot(cal2, aes(horizon_label, value, colour = metric, group = metric)) + geom_hline(data = distinct(cal2, metric, reference), aes(yintercept = reference), linetype = 2, colour = "#9aa5b1") + geom_line(linewidth = .6) + geom_point(size = 2.8) + labs(title = "Calibration summaries", x = NULL, y = "Estimate; dashed = ideal reference", colour = NULL) + theme_science
p2d <- ggplot(m2, aes(horizon_label, auroc, colour = horizon_label)) + geom_line(aes(group = 1), colour = "#52606d", linewidth = .5) + geom_point(size = 3) + scale_colour_manual(values = horizon_cols) + labs(title = "AUROC context", x = NULL, y = "AUROC") + theme_science + theme(legend.position = "none")
d2 <- write_data(m2, "figure_02_performance_data.csv")
f2 <- save_fig((p2a | p2b) / (p2c | p2d) + plot_annotation(tag_levels = "A"), "figure_02_predictive_performance", 11, 8)

# Figure 3: focal cell maps with shared scales, boundaries, north arrows, and scale bars.
prob_limits <- range(maps$p_occurrence, na.rm = TRUE); count_limits <- range(maps$expected_count, na.rm = TRUE)
map_theme <- theme_map + theme(strip.text = element_text(size = 8), legend.key.width = unit(1.5, "cm"))
p3a <- ggplot(maps, aes(lon, lat, fill = p_occurrence)) + geom_tile(width = md[["width"]], height = md[["height"]]) +
  geom_sf(data = boundary_focal, inherit.aes = FALSE, fill = NA, colour = "#334e68", linewidth = .12) +
  geom_point(data = filter(maps, observed_positive > 0), aes(lon, lat), inherit.aes = FALSE, shape = 21, fill = "white", colour = "#111827", size = 1.05, stroke = .35) +
  facet_wrap(~target_week, nrow = 1) + scale_fill_viridis_c(option = "D", begin = .04, end = .96, limits = prob_limits, oob = scales::squish, name = "Occurrence\nprobability") +
  coord_focal + map_aids() + labs(title = "h=1 occurrence probability; observed positives overlaid", x = "Longitude", y = "Latitude") + map_theme
p3b <- ggplot(maps, aes(lon, lat, fill = expected_count)) + geom_tile(width = md[["width"]], height = md[["height"]]) +
  geom_sf(data = boundary_focal, inherit.aes = FALSE, fill = NA, colour = "#334e68", linewidth = .12) +
  geom_point(data = filter(maps, observed_count > 0), aes(lon, lat), inherit.aes = FALSE, shape = 21, fill = "white", colour = "#111827", size = 1.05, stroke = .35) +
  facet_wrap(~target_week, nrow = 1) + scale_fill_viridis_c(option = "C", begin = .04, end = .96, limits = count_limits, oob = scales::squish, name = "Full hurdle\nexpected count") +
  coord_focal + map_aids() + labs(title = "Candidate full hurdle expected-count maps; observed counts overlaid", x = "Longitude", y = "Latitude") + map_theme
p3c <- ggplot(times, aes(target_week)) +
  geom_line(aes(y = observed_positive_cells, colour = "Observed positive cells", group = 1), linewidth = .8) + geom_point(aes(y = observed_positive_cells, colour = "Observed positive cells"), size = 1.5) +
  geom_line(aes(y = expected_positive_cells, colour = "Expected number of positive cells", group = 1), linewidth = .8) + geom_point(aes(y = expected_positive_cells, colour = "Expected number of positive cells"), size = 1.5) +
  scale_colour_manual(values = c("Observed positive cells" = "#222222", "Expected number of positive cells" = "#0072B2")) + labs(title = "Focal occurrence burden, h=1", x = "Target week", y = "Cells", colour = NULL) + theme_science + theme(axis.text.x = element_text(angle = 45, hjust = 1))
p3d <- ggplot(times, aes(target_week)) +
  geom_line(aes(y = observed_count, colour = "Observed total count", group = 1), linewidth = .8) + geom_point(aes(y = observed_count, colour = "Observed total count"), size = 1.5) +
  geom_line(aes(y = expected_count, colour = "Predicted total expected count", group = 1), linewidth = .8) + geom_point(aes(y = expected_count, colour = "Predicted total expected count"), size = 1.5) +
  scale_colour_manual(values = c("Observed total count" = "#222222", "Predicted total expected count" = "#D55E00")) + labs(title = "Candidate focal count burden, h=1", x = "Target week", y = "Count", colour = NULL) + theme_science + theme(axis.text.x = element_text(angle = 45, hjust = 1))
d3m <- write_data(maps, "figure_03_focal_h1_map_data.csv"); d3t <- write_data(times, "figure_03_focal_h1_time_series.csv")
f3occ <- save_fig(p3a / p3c + plot_annotation(tag_levels = "A"), "figure_03_mexico_texas_occurrence", 15, 9)
f3cnt <- save_fig(p3b / p3d + plot_annotation(tag_levels = "A"), "figure_03_mexico_texas_expected_count_candidate", 15, 9)

# Figure 4: canonical P5A proxy-minus-realized differences.
e0_metrics <- c("brier", "auprc", "conditional_mae", "full_expected_mae")
f4_data <- paired %>% filter(proxy_id == "E0_LAST_AVAILABLE", metric %in% e0_metrics) %>% left_join(
  boot %>% filter(proxy_id == "E0_LAST_AVAILABLE", metric %in% e0_metrics) %>% select(horizon, metric, lower, upper), by = c("horizon", "metric"))
diff_panel <- function(metric, title) {
  d <- f4_data %>% filter(.data$metric == metric)
  ggplot(d, aes(factor(horizon), difference_proxy_minus_realized)) + geom_hline(yintercept = 0, linetype = 2, colour = "#52606d") + geom_errorbar(aes(ymin = lower, ymax = upper), width = .12, colour = "#0072B2", linewidth = .6) + geom_point(size = 2.8, colour = "#0072B2") + labs(title = title, x = "Horizon", y = "E0 - REALIZED_ENV") + theme_science
}
f4a <- diff_panel("brier", "Brier"); f4b <- diff_panel("auprc", "AUPRC"); f4c <- diff_panel("conditional_mae", "Conditional positive-count MAE"); f4d <- diff_panel("full_expected_mae", "Full expected-count MAE")
d4 <- write_data(f4_data, "figure_04_e0_proxy_degradation_data.csv")
f4 <- save_fig((f4a | f4b) / (f4c | f4d) + plot_annotation(tag_levels = "A"), "figure_04_issue_time_proxy_validation", 12, 8)

# Figure 5: family-block signed associations; no global importance ranking.
coef_long <- bind_rows(
  coef %>% transmute(predictor, family, scale_category = scaling_status, component = "Occurrence", coefficient = occurrence_coefficient),
  coef %>% transmute(predictor, family, scale_category = scaling_status, component = "Conditional positive-count", coefficient = count_coefficient)
) %>% filter(is.finite(coefficient)) %>% arrange(family, predictor)
coef_long$predictor <- factor(coef_long$predictor, levels = rev(unique(coef_long$predictor)))
scale_levels <- unique(coef_long$scale_category)
scale_cols <- setNames(c("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9", "#666666")[seq_along(scale_levels)], scale_levels)
scale_shapes <- setNames(c(16, 17, 15, 18, 8, 3)[seq_along(scale_levels)], scale_levels)
coef_plot <- function(component, title) {
  ggplot(filter(coef_long, .data$component == component), aes(coefficient, predictor, colour = scale_category, shape = scale_category)) +
    geom_vline(xintercept = 0, colour = "#52606d") + geom_segment(aes(x = 0, xend = coefficient, y = predictor, yend = predictor), linewidth = .55) + geom_point(size = 1.9) +
    facet_grid(family ~ ., scales = "free_y", space = "free_y") + scale_colour_manual(values = scale_cols) + scale_shape_manual(values = scale_shapes) +
    labs(title = title, x = "Fitted coefficient; scaling class shown", y = NULL, colour = "Scale class", shape = "Scale class") + theme_science + theme(strip.text.y = element_text(angle = 0))
}
p5a <- coef_plot("Occurrence", "Occurrence-component signed associations")
p5b <- coef_plot("Conditional positive-count", "Conditional positive-count signed associations")
stability_s <- stability %>% filter(row_type == "summary") %>% mutate(component_label = recode(component, occurrence = "Occurrence", positive_count = "Conditional positive-count"), feature = factor(feature, levels = rev(unique(feature))))
p5c <- ggplot(stability_s, aes(feature, mean_coefficient, colour = component_label)) + geom_hline(yintercept = 0, colour = "#52606d") + geom_errorbar(aes(ymin = mean_coefficient - sd_coefficient, ymax = mean_coefficient + sd_coefficient), width = .15, position = position_dodge(width = .35)) + geom_point(position = position_dodge(width = .35), size = 2) + coord_flip() + scale_colour_manual(values = c(Occurrence = "#0072B2", `Conditional positive-count` = "#D55E00")) + labs(title = "Canonical rolling-origin stability subset", subtitle = "Four predictors with available canonical summaries", x = NULL, y = "Mean coefficient ± SD", colour = NULL) + theme_science
d5 <- write_data(coef_long, "figure_05_signed_coefficient_associations_data.csv"); d5s <- write_data(stability_s, "figure_05_coefficient_stability_subset_data.csv")
f5 <- save_fig((p5a | p5b) / p5c + plot_annotation(tag_levels = "A"), "figure_05_predictor_associations", 15, 14)

# Figure 6: support proportions, canonical P4 context, performance, and definitions.
sp <- support %>% filter(proxy_id == "E0_LAST_AVAILABLE") %>% mutate(horizon_label = paste0("h=", horizon), support_class = factor(support_class, levels = names(support_cols)))
p6a <- ggplot(sp, aes(horizon_label, proportion, fill = support_class)) + geom_col(width = .68) + geom_text(aes(label = ifelse(proportion > .04, scales::percent(proportion, accuracy = .1), "")), position = position_stack(vjust = .5), colour = "white", size = 2.8) + scale_y_continuous(labels = scales::percent, expand = expansion(mult = c(0, .03))) + scale_fill_manual(values = support_cols, drop = FALSE) + labs(title = "P4 support proportions under E0", x = NULL, y = "Rows", fill = "Predictor-space support") + theme_science
p4_support <- file.path(p7b, "figures/main/figure_06_support_canonical_p4.png")
p6b <- ggplot() + annotation_custom(rasterGrob(readPNG(p4_support), interpolate = TRUE), xmin = -Inf, xmax = Inf, ymin = -Inf, ymax = Inf) + xlim(0, 1) + ylim(0, 1) + labs(title = "Canonical P4 support display") + theme_void() + theme(plot.title = element_text(face = "bold", hjust = .5, colour = "#1f2937"))
sp_perf <- support_perf %>% mutate(support_class = factor(support_class, levels = names(support_cols)), horizon_label = paste0("h=", horizon))
p6c <- ggplot(sp_perf, aes(horizon_label, brier, colour = support_class, group = support_class)) + geom_line(linewidth = .6) + geom_point(size = 2) + scale_colour_manual(values = support_cols) + labs(title = "Occurrence Brier by support class", x = NULL, y = "Brier score", colour = "Support class") + theme_science
support_def <- data.frame(support_class = factor(names(support_cols), levels = names(support_cols)), definition = c("Predictor conditions well represented in training data", "Less well supported predictor conditions", "Predictor conditions substantially outside training support"))
support_def$label <- paste0(as.character(support_def$support_class), "\n", vapply(support_def$definition, function(x) paste(strwrap(x, width = 22), collapse = "\n"), character(1)))
p6d <- ggplot(support_def, aes(support_class, 1, fill = support_class)) + geom_tile(width = .96, height = .82) + geom_text(aes(label = label), size = 2.5, lineheight = .95) + scale_fill_manual(values = support_cols) + scale_y_continuous(NULL, breaks = NULL) + labs(title = "Support classes describe predictor-space representation") + theme_void() + theme(legend.position = "none", plot.title = element_text(face = "bold", hjust = .5, size = 10))
d6 <- write_data(sp, "figure_06_support_proportions_data.csv")
f6 <- save_fig((p6a | p6b) / (p6c | p6d) + plot_annotation(tag_levels = "A"), "figure_06_support_extrapolation", 13, 9)
file.copy(p4_support, file.path(main, "figure_06_support_canonical_p4.png"), overwrite = TRUE)

# Supplementary figures; S3 remains an exact canonical P3 raster reuse.
cal$horizon_label <- paste0("h=", cal$horizon)
s1 <- ggplot(cal, aes(mean_predicted, observed_probability, colour = horizon_label, group = horizon_label)) + geom_abline(slope = 1, intercept = 0, linetype = 2, colour = "#52606d") + geom_errorbar(aes(ymin = pmax(0, observed_probability - observed_se), ymax = pmin(1, observed_probability + observed_se)), width = 0, alpha = .45) + geom_line(linewidth = .65) + geom_point(size = 1.8) + scale_colour_manual(values = horizon_cols) + facet_wrap(~horizon_label) + labs(title = "Reliability curves by horizon", x = "Mean predicted probability", y = "Observed probability", colour = NULL) + theme_science
dS1 <- write_data(cal, "supplement_S1_reliability_data.csv"); s1_out <- save_fig(s1, "S1_reliability_curves", 10, 5, supp)
fr <- frontier %>% mutate(horizon_label = paste0("h=", horizon))
s2 <- ggplot(fr, aes(frontier_class, brier, colour = definition, group = definition)) + geom_line(linewidth = .55, na.rm = TRUE) + geom_point(size = 1.8, na.rm = TRUE) + facet_wrap(~horizon_label) + labs(title = "Frontier-definition sensitivity", x = "Frontier class", y = "Brier score", colour = "Definition") + theme_science + theme(axis.text.x = element_text(angle = 30, hjust = 1))
dS2 <- write_data(fr, "supplement_S2_frontier_sensitivity_data.csv"); s2_out <- save_fig(s2, "S2_frontier_sensitivity", 11, 5, supp)
s3_path <- file.path(supp, "S3_count_diagnostics_reference.png")
count_ref <- file.path(repo, "analysis/p3_robustness/figures/P3-2_count_error_by_magnitude.png")
if (!file.exists(count_ref)) stop("canonical P3 count diagnostic is missing")
file.copy(count_ref, s3_path, overwrite = TRUE)
transition <- read_csv(file.path(repo, "analysis/p5a_environmental_proxy/results/support_transitions.csv")) %>% filter(proxy_id == "E0_LAST_AVAILABLE")
env0 <- env %>% filter(proxy_id == "E0_LAST_AVAILABLE") %>% group_by(horizon, family) %>% summarise(mae = mean(mae), .groups = "drop") %>% mutate(horizon_label = paste0("h=", horizon))
pS4a <- ggplot(env0, aes(family, mae, fill = horizon_label)) + geom_col(position = "dodge") + scale_fill_manual(values = horizon_cols) + labs(title = "A. Environmental proxy MAE by family", x = NULL, y = "Mean MAE", fill = NULL) + theme_science + theme(axis.text.x = element_text(angle = 30, hjust = 1))
transition$from_support_class <- factor(transition$from_support_class, levels = names(support_cols)); transition$to_support_class <- factor(transition$to_support_class, levels = names(support_cols))
pS4b <- ggplot(transition, aes(from_support_class, to_support_class, fill = n)) + geom_tile() + geom_text(aes(label = n), size = 2.8) + scale_fill_viridis_c(option = "D") + labs(title = "B. E0 support-class transitions", x = "REALIZED_ENV class", y = "E0 class", fill = "Rows") + theme_science
dS4a <- write_data(env0, "supplement_S4_environmental_error_family_data.csv"); dS4b <- write_data(transition, "supplement_S4_support_transition_data.csv")
s4_out <- save_fig(pS4a | pS4b + plot_annotation(tag_levels = "A"), "S4_proxy_error_support_transitions", 12, 5, supp)

# P7B/P7 core tables copied exactly without scientific edits.
table_map <- c(table_1_model_data = "table_1_model_data.csv", table_2_occurrence = "table_2_occurrence.csv", table_3_count = "table_3_count.csv", table_4_proxy = "table_4_proxy.csv")
for (nm in names(table_map)) {
  src <- file.path(p7b, "tables", table_map[[nm]])
  if (!file.exists(src)) stop("missing P7B source table: ", src)
  file.copy(src, file.path(tables, paste0(nm, ".csv")), overwrite = TRUE)
}

# Technical captions only; no manuscript narrative is generated.
caption_text <- list(
  figure_01 = "A. The canonical domain is rendered as cell tiles with the fixed Mexico-Texas focal bounding box and cartographic boundaries. B. The focal inset uses the same fixed extent. C. STRUCTURED_A3 combines occurrence probability with conditional positive-count prediction to form the full expected count. D. E0_LAST_AVAILABLE uses the latest legitimately available environmental state at issue time and holds that state across h=1 to h=3; future environmental conditions are not observed in advance. The boundary layer is orientation context and does not alter model results.",
  figure_02 = "Canonical P2 rolling-origin metrics by horizon. Lower Brier is better; AUPRC is prevalence-sensitive; calibration intercepts are referenced to zero and slopes to one; AUROC is secondary discrimination context. These are retrospective predictive summaries, not causal effects.",
  figure_03_occurrence = "Focal-region h=1 outputs for the prespecified target weeks 2026-W17, W22, W27, W32, and W37. Cell tiles use identical geographic and probability scales; boundaries, north arrows, and scale bars provide orientation; white outlined cells mark observed positives. The time series compares observed positive cells with the expected number of positive cells, defined as the sum of cell-level occurrence probabilities. It is not a regional risk index.",
  figure_03_count = "Candidate full hurdle expected-count maps and focal count time series for the same prespecified weeks and h=1 interval. Cell tiles use one count scale across weeks. The predicted total expected count is the sum of cell-level full hurdle expected counts. This is a visual candidate for review and does not change the count model.",
  figure_04 = "Paired E0_LAST_AVAILABLE minus REALIZED_ENV differences from P5A. REALIZED_ENV uses target-week realized environmental inputs, whereas E0 uses only the latest issue-time environmental state. Intervals are the canonical dependence-aware target-week bootstrap intervals. The zero reference highlights near-zero change; near-zero predictive differences do not imply that future environmental conditions are constant.",
  figure_05 = "Signed fitted coefficient associations for the occurrence and conditional positive-count components, grouped by predictor family and marked by scaling class. Coefficients represent fitted predictive associations conditional on the model structure. Magnitudes are most defensibly compared within comparable scaling classes; correlated predictors can redistribute coefficient magnitudes. The display is not a global feature-importance ranking and does not imply causal effects. The stability panel is limited to four predictors with canonical rolling-origin summaries.",
  figure_06 = "P4 support classes are shown without threshold changes. SUPPORTED indicates predictor conditions well represented in the training data; CAUTION indicates less well supported predictor conditions; EXTRAPOLATIVE indicates predictor conditions substantially outside training support. These are predictor-space support states. They are not confidence intervals, not direct measures of correctness, and not causal categories. Extrapolative predictions remain visible. The canonical P4 support display is reused because complete cell-level support records are not available for a new focal re-render.",
  S1 = "Canonical P2 occurrence reliability curves by horizon. Points show mean predicted probability and observed probability within fixed probability bins; bars show the canonical approximate binomial standard-error display. The sparse high-probability tail should not be overinterpreted.",
  S2 = "Canonical P3 frontier-definition sensitivity summaries. Definitions and outcomes are unchanged from P3; this figure is descriptive and does not select a new frontier definition.",
  S3 = "Canonical P3 count-error diagnostic reused without re-estimation. Count-stratum behavior is descriptive and does not imply unbiased abundance estimation.",
  S4 = "Canonical P5A environmental proxy error summarized by predictor family and E0 support-class transitions. These are diagnostic summaries; support thresholds are unchanged."
)
for (nm in names(caption_text)) writeLines(caption_text[[nm]], file.path(captions, paste0(nm, ".caption.md")))

# Palette and support-class explanation note.
writeLines(c(
  "# P7C palette and legend note", "",
  "Continuous surfaces use viridis option D for occurrence probability and option C for full hurdle expected count, with shared limits across the five map weeks.",
  "Support classes use the following colorblind-conscious semantic mapping:",
  "- SUPPORTED: #009E73, green; predictor conditions well represented in training data",
  "- CAUTION: #E69F00, orange; less well supported predictor conditions",
  "- EXTRAPOLATIVE: #D55E00, vermilion; predictor conditions substantially outside training support",
  "", "Support classes are not confidence intervals, direct correctness measures, or causal categories.",
  "Map surfaces use ggplot2::geom_tile; boundaries use sf::geom_sf; scale bars and north arrows use ggspatial."
), file.path(root, "palette_legend_note.md"))

# Boundary/rendering audit records.
boundary_audit <- list(
  source_path_atlas = "/project/disease_ecology/NWScrewworm/data/processed_data/spatial_domain/study_states.gpkg",
  local_copy = rel(boundary_path), layer_names = "study_states (WGS84 WKT-CSV derivative)", layer_used = "study_states", feature_count = nrow(boundary_raw),
  source_crs_input = "unknown (Atlas GeoPackage input; WGS84 WKT-CSV derivative)",
  source_crs_wkt = "Atlas audit: WGS84-based Albers Equal Area WKT; derivative is explicit EPSG:4326 WKT", plot_crs = "EPSG:4326",
  transformation = "st_make_valid followed by st_transform to EPSG:4326",
  local_sha256 = sha256(boundary_path), use = "cartographic orientation only; scientific results unchanged"
)
write_json(boundary_audit, file.path(results, "boundary_audit.json"), auto_unbox = TRUE, pretty = TRUE)
render_contract <- list(
  focal_bbox = fixed_bbox, focal_cells = 1689L, map_weeks = map_weeks,
  time_interval = c("2026-W17", "2026-W37"), horizon = 1L, focal_surface_geometry = "ggplot2::geom_tile",
  boundary_layer = "study_states", north_arrow = "ggspatial::annotation_north_arrow",
  scale_bar = "ggspatial::annotation_scale", no_point_surface_rendering = TRUE
)
write_json(render_contract, file.path(results, "rendering_contract.json"), auto_unbox = TRUE, pretty = TRUE)

# One registry row per refined panel/output.
registry <- data.frame(
  figure_id = character(), panel_id = character(), source_phase = character(), source_file = character(),
  source_fields = character(), transformations = character(), filtering = character(), focal_subset = character(),
  boundary_source = character(), scale_limits = character(), palette = character(), plotting_script = character(),
  output_file = character(), output_hash = character(), variant_status = character(), underlying_data_file = character(),
  underlying_data_hash = character(), stringsAsFactors = FALSE
)
add_reg <- function(id, panel, phase, source, fields, trans, filt, focal, bsrc, limits, pal, output, status, data = NA_character_) {
  op <- file.path(repo, output); dp <- if (!is.na(data)) file.path(repo, data) else NA_character_
  registry <<- rbind(registry, data.frame(
    figure_id = id, panel_id = panel, source_phase = phase, source_file = source, source_fields = fields,
    transformations = trans, filtering = filt, focal_subset = focal, boundary_source = bsrc,
    scale_limits = limits, palette = pal, plotting_script = "analysis/p7c_figure_refinement/scripts/generate_p7c_figures.R",
    output_file = output, output_hash = if (file.exists(op)) sha256(op) else NA_character_, variant_status = status,
    underlying_data_file = if (!is.na(data)) data else NA_character_, underlying_data_hash = if (!is.na(data) && file.exists(dp)) sha256(dp) else NA_character_,
    stringsAsFactors = FALSE
  ))
}
bsrc <- "Atlas study_states.gpkg; tracked WGS84 WKT-CSV derivative; EPSG:4326"
add_reg("Figure 1", "A", "P2/P7", "analysis/p7b_science_figures/results/figure_01_domain_grid.csv", "lon,lat,region", "geom_tile plus geom_sf", "full domain", "full canonical domain", bsrc, "fixed domain extent", "domain categorical", rel(f1[["svg"]]), "revised", rel(d1))
add_reg("Figure 1", "B", "P2/P7A", "analysis/p7b_science_figures/results/figure_01_domain_grid.csv; analysis/p7a_figure_design/results/mexico_texas_focal_region.json", "lon,lat,bbox", "fixed focal geom_tile plus geom_sf", "bbox exact", "EPSG:4326 -107.5:-96,24:33", bsrc, "fixed focal extent", "domain categorical", rel(f1[["svg"]]), "revised", rel(d1))
add_reg("Figure 1", "C-D", "P0/P5A/P6", "config/production_model_freeze.json; analysis/p5a_environmental_proxy/results/proxy_contract.json; config/p6_production_config.json", "model ID, hurdle, proxy", "schematic formatting", "none", "not applicable", "none", "not applicable", "semantic schematic", rel(f1[["svg"]]), "revised", rel(d1))
add_reg("Figure 2", "A-D", "P2", "analysis/p2_operational_nowcast/results/horizon_metrics.csv", "brier,auprc,calibration_intercept,calibration_slope,auroc", "canonical regeneration", "scope=all,region=all,h=1:3", "not applicable", "none", "shared horizon", "horizon palette", rel(f2[["svg"]]), "revised", rel(d2))
add_reg("Figure 3", "A,C", "P2", "analysis/p7b_science_figures/results/figure_03_focal_h1_map_data.csv; figure_03_focal_h1_time_series.csv", "lon,lat,p_occurrence,observed_positive", "geom_tile and focal aggregation", "horizon=1", "EPSG:4326 fixed bbox; 1,689 cells", bsrc, "shared probability limits", "viridis D", rel(f3occ[["svg"]]), "revised", rel(d3m))
add_reg("Figure 3 candidate", "B,D", "P2", "analysis/p7b_science_figures/results/figure_03_focal_h1_map_data.csv; figure_03_focal_h1_time_series.csv", "lon,lat,expected_count,observed_count", "geom_tile and focal aggregation", "horizon=1", "EPSG:4326 fixed bbox; 1,689 cells", bsrc, "shared expected-count limits", "viridis C", rel(f3cnt[["svg"]]), "candidate alternative", rel(d3m))
add_reg("Figure 4", "A-D", "P5A", "analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv; bootstrap_intervals.csv", "difference_proxy_minus_realized,lower,upper", "paired differences with zero reference", "proxy=E0; four metrics", "full evaluation", "none", "canonical intervals", "blue/neutral", rel(f4[["svg"]]), "revised", rel(d4))
add_reg("Figure 5", "A-C", "P0/P7A", "analysis/p7a_figure_design/results/predictor_contribution_audit.csv; analysis/structured_a3_final_comparison/results/a3_coefficient_stability.csv", "predictor,family,component,coefficient,scale_category,mean,sd", "family-block signed associations; no global ranking", "intercept excluded", "all predictors; four-feature subset", "none", "shared zero reference", "scale-class palette/shapes", rel(f5[["svg"]]), "revised", rel(d5))
add_reg("Figure 6", "A,C,D", "P4/P5A", "analysis/p5a_environmental_proxy/results/support_metrics.csv; analysis/p4_uncertainty_extrapolation/results/performance_by_support.csv", "support_class,proportion,brier", "semantic palette and definition tiles", "E0,h=1:3", "full evaluation", "none", "support proportions/performance", "support semantic", rel(f6[["svg"]]), "revised", rel(d6))
add_reg("Figure 6", "B", "P4", "analysis/p7b_science_figures/figures/main/figure_06_support_canonical_p4.png", "canonical P4 support display", "raster reuse", "none", "canonical P4 display", "not re-rendered", "canonical", "canonical P4", rel(file.path(main, "figure_06_support_canonical_p4.png")), "unchanged from P7B")
add_reg("S1", "A", "P2", "analysis/p2_operational_nowcast/results/calibration_bins.csv", "mean_predicted,observed_probability,observed_se", "reliability display", "occurrence,all,h=1:3", "full evaluation", "none", "0:1", "horizon palette", rel(s1_out[["svg"]]), "revised", rel(dS1))
add_reg("S2", "A", "P3", "analysis/p7_publication/supplement/frontier_sensitivity_metrics.csv", "definition,frontier_class,horizon,brier", "sensitivity display", "canonical rows", "full evaluation", "none", "canonical", "horizon palette", rel(s2_out[["svg"]]), "revised", rel(dS2))
add_reg("S3", "A", "P3", "analysis/p3_robustness/figures/P3-2_count_error_by_magnitude.png", "canonical P3 figure", "raster reuse", "none", "full evaluation", "none", "canonical", "canonical P3", rel(s3_path), "unchanged from P7B")
add_reg("S4", "A-B", "P5A", "analysis/p5a_environmental_proxy/results/environmental_proxy_error_by_family.csv; support_transitions.csv", "family,mae,from_support_class,to_support_class,n", "family summaries and transition matrix", "E0", "full evaluation", "none", "canonical", "horizon/support palette", rel(s4_out[["svg"]]), "revised", rel(dS4a))
registry$output_hash <- vapply(registry$output_file, function(x) sha256(file.path(repo, x)), character(1))
registry$underlying_data_hash <- vapply(seq_len(nrow(registry)), function(i) {
  x <- registry$underlying_data_file[[i]]
  if (is.na(x) || !nzchar(x)) return(NA_character_)
  sha256(file.path(repo, x))
}, character(1))
write.csv(registry, file.path(results, "figure_source_registry.csv"), row.names = FALSE, quote = TRUE, na = "")
write.csv(registry[, c("figure_id", "panel_id", "output_file", "output_hash", "variant_status", "underlying_data_file", "underlying_data_hash")], file.path(results, "figure_output_hashes.csv"), row.names = FALSE, quote = TRUE, na = "")

decision <- list(
  p7c_decision = "P7C_FIGURE_REFINEMENT_SUPPORTED_WITH_LIMITATIONS", no_model_fitting = TRUE,
  fixed_focal_bbox = fixed_bbox, focal_cells = 1689L, map_weeks = map_weeks, time_interval = c("2026-W17", "2026-W37"),
  limitations = c("support map panel reused from canonical P4 because complete cell-level support records are unavailable for a new re-render", "provided boundary layer has unknown user-input CRS but WGS84-based Albers WKT; transformed to EPSG:4326 for orientation", "Figure 5 remains a mixed-scaling signed-association display", "expected-count Figure 3 remains a candidate alternative")
)
write_json(decision, file.path(results, "decision.json"), auto_unbox = TRUE, pretty = TRUE)
metadata <- list(phase = "P7C", script = "analysis/p7c_figure_refinement/scripts/generate_p7c_figures.R", r_version = R.version.string, model_fitting = FALSE, forbidden_methods_used = FALSE, plotting_framework = c("ggplot2", "sf", "ggspatial"), source_registry = "analysis/p7c_figure_refinement/results/figure_source_registry.csv", boundary_audit = "analysis/p7c_figure_refinement/results/boundary_audit.json", rendering_contract = "analysis/p7c_figure_refinement/results/rendering_contract.json")
write_json(metadata, file.path(results, "run_metadata.json"), auto_unbox = TRUE, pretty = TRUE)
cat("P7C_FIGURES_GENERATED\n")
