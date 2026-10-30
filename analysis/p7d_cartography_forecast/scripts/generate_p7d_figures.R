#!/usr/bin/env Rscript

# P7D corrects cartographic rendering and adds a bounded operational forecast
# visualization. No model fitting, refitting, recalibration, threshold change,
# feature-importance analysis, or new uncertainty analysis is performed.
suppressPackageStartupMessages({
  library(ggplot2); library(patchwork); library(dplyr); library(tidyr)
  library(sf); library(ggspatial); library(jsonlite); library(digest)
  library(svglite)
})

args <- commandArgs(trailingOnly = TRUE)
repo <- if (length(args)) normalizePath(args[[1]], mustWork = TRUE) else normalizePath(".", mustWork = TRUE)
root <- file.path(repo, "analysis", "p7d_cartography_forecast")
main <- file.path(root, "figures", "main_candidates")
supp <- file.path(root, "figures", "supplement_candidates")
captions <- file.path(root, "captions")
results <- file.path(root, "results")
plot_data_dir <- file.path(results, "plot_data")
for (p in c(main, supp, captions, results, plot_data_dir)) dir.create(p, recursive = TRUE, showWarnings = FALSE)

read_csv <- function(path) read.csv(path, stringsAsFactors = FALSE, check.names = FALSE)
sha256 <- function(path) digest(path, algo = "sha256", file = TRUE)
rel <- function(path) {
  p <- normalizePath(path, winslash = "/", mustWork = FALSE)
  pre <- paste0(normalizePath(repo, winslash = "/", mustWork = TRUE), "/")
  if (startsWith(p, pre)) substring(p, nchar(pre) + 1L) else p
}
write_data <- function(x, name) {
  path <- file.path(plot_data_dir, name)
  write.csv(x, path, row.names = FALSE, quote = TRUE, na = "")
  path
}
save_fig <- function(plot, stem, width, height, directory = main) {
  svg_path <- file.path(directory, paste0(stem, ".svg"))
  png_path <- file.path(directory, paste0(stem, ".png"))
  ggsave(svg_path, plot, device = svglite::svglite, width = width, height = height, units = "in", bg = "white")
  ggsave(png_path, plot, device = "png", width = width, height = height, units = "in", dpi = 220, bg = "white")
  c(svg = svg_path, png = png_path)
}
tile_dims <- function(x) {
  if (all(c("row", "column") %in% names(x))) {
    dx <- x %>% arrange(row, column) %>% group_by(row) %>% mutate(d = abs(lon - lead(lon))) %>% pull(d)
    dy <- x %>% arrange(column, row) %>% group_by(column) %>% mutate(d = abs(lat - lead(lat))) %>% pull(d)
  } else {
    dx <- x %>% arrange(lon) %>% distinct(lon) %>% mutate(d = abs(lon - lead(lon))) %>% pull(d)
    dy <- x %>% arrange(lat) %>% distinct(lat) %>% mutate(d = abs(lat - lead(lat))) %>% pull(d)
  }
  dx <- dx[is.finite(dx) & dx > 0]; dy <- dy[is.finite(dy) & dy > 0]
  if (!length(dx) || !length(dy)) stop("cannot infer canonical grid-cell dimensions")
  # Center spacing is slightly irregular after the canonical projection-to-
  # longitude/latitude representation; a small expansion closes visual seams
  # without changing cell membership or scientific values.
  c(width = median(dx) * 1.05, height = median(dy) * 1.05)
}
map_aids <- function() list(
  annotation_scale(location = "bl", width_hint = 0.22, text_cex = 0.62, line_width = 0.55),
  annotation_north_arrow(location = "tl", which_north = "true",
    style = north_arrow_orienteering(text_size = 6, line_col = "#334e68", fill = c("#ffffff", "#334e68")))
)
theme_science <- theme_minimal(base_size = 10, base_family = "Arial") + theme(
  panel.background = element_rect(fill = "#f8fafc", colour = NA),
  panel.grid.major = element_line(colour = "#d9e2ec", linewidth = 0.25),
  panel.grid.minor = element_blank(), plot.title = element_text(face = "bold", colour = "#1f2937"),
  plot.subtitle = element_text(colour = "#52606d", size = 9), axis.title = element_text(size = 9),
  legend.position = "bottom", legend.title = element_text(size = 9), legend.text = element_text(size = 8),
  strip.text = element_text(face = "bold", colour = "#243b53", size = 10), plot.caption = element_text(size = 8, hjust = 0)
)
theme_map <- theme_science + theme(panel.grid.major = element_line(colour = "#cbd5e1", linewidth = 0.25))
fixed_bbox <- c(xmin = -107.5, xmax = -96.0, ymin = 24.0, ymax = 33.0)
map_weeks <- c("2026-W17", "2026-W22", "2026-W27", "2026-W32", "2026-W37")
time_weeks <- sprintf("2026-W%02d", 17:37)
domain_colors <- c(Mexico = "#56B4E9", `U.S.-to-40N` = "#E69F00")
support_colors <- c(SUPPORTED = "#009E73", CAUTION = "#E69F00", EXTRAPOLATIVE = "#D55E00")

p7b <- file.path(repo, "analysis", "p7b_science_figures")
p7c <- file.path(repo, "analysis", "p7c_figure_refinement")
domain <- read_csv(file.path(p7c, "results", "plot_data", "figure_01_domain_framework_data.csv"))
maps <- read_csv(file.path(p7c, "results", "plot_data", "figure_03_focal_h1_map_data.csv"))
times <- read_csv(file.path(p7c, "results", "plot_data", "figure_03_focal_h1_time_series.csv"))
maps <- maps %>% filter(horizon == 1, target_week %in% map_weeks)
maps$target_week <- factor(maps$target_week, levels = map_weeks)
times <- times %>% filter(target_week %in% time_weeks)
times$target_week <- factor(times$target_week, levels = time_weeks)
boundary_path <- file.path(p7c, "results", "boundaries", "study_states_wgs84.csv")
boundary_raw <- st_as_sf(read_csv(boundary_path), wkt = "geometry_wkt", crs = 4326, remove = FALSE)
boundary <- st_transform(st_make_valid(boundary_raw), 4326)
boundary_domain <- suppressWarnings(st_crop(boundary, c(xmin = min(domain$lon) - 1, xmax = max(domain$lon) + 1,
  ymin = min(domain$lat) - 1, ymax = max(domain$lat) + 1)))
boundary_focal <- suppressWarnings(st_crop(boundary, fixed_bbox))
coord_domain <- coord_sf(xlim = c(min(domain$lon) - .5, max(domain$lon) + .5),
  ylim = c(min(domain$lat) - .5, max(domain$lat) + .5), expand = FALSE, crs = st_crs(4326), default_crs = st_crs(4326))
coord_focal <- coord_sf(xlim = fixed_bbox[c("xmin", "xmax")], ylim = fixed_bbox[c("ymin", "ymax")],
  expand = FALSE, crs = st_crs(4326), default_crs = st_crs(4326))
dd <- tile_dims(domain); md <- tile_dims(maps)

# Figure 1: shared domain colors in full and focal panels, boundaries after tiles.
domain$region <- factor(domain$region, levels = names(domain_colors))
focal_domain <- domain %>% filter(lon >= fixed_bbox[["xmin"]], lon <= fixed_bbox[["xmax"]],
  lat >= fixed_bbox[["ymin"]], lat <= fixed_bbox[["ymax"]])
p1a <- ggplot(domain, aes(lon, lat, fill = region)) +
  geom_tile(width = dd[["width"]], height = dd[["height"]], alpha = .76) +
  geom_sf(data = boundary_domain, inherit.aes = FALSE, fill = NA, colour = "#334e68", linewidth = .12) +
  geom_rect(data = data.frame(xmin = fixed_bbox[["xmin"]], xmax = fixed_bbox[["xmax"]], ymin = fixed_bbox[["ymin"]], ymax = fixed_bbox[["ymax"]]),
    aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax), inherit.aes = FALSE, fill = NA, colour = "#111827", linewidth = .7, linetype = 2) +
  coord_domain + scale_fill_manual(values = domain_colors, drop = FALSE) +
  labs(title = "Canonical spatial domain", x = "Longitude", y = "Latitude", fill = "Domain") + map_aids() + theme_map
p1b <- ggplot(focal_domain, aes(lon, lat, fill = region)) +
  geom_tile(width = dd[["width"]], height = dd[["height"]], alpha = .76) +
  geom_sf(data = boundary_focal, inherit.aes = FALSE, fill = NA, colour = "#334e68", linewidth = .15) +
  coord_focal + scale_fill_manual(values = domain_colors, drop = FALSE) +
  labs(title = "Fixed Mexico-Texas focal region", x = "Longitude", y = "Latitude", fill = "Domain") + map_aids() + theme_map
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
p1d <- ggplot(proxy, aes(x, 0, colour = group)) +
  geom_segment(data = data.frame(x = 1, xend = 5, y = 0, yend = 0), aes(x = x, xend = xend, y = y, yend = yend), inherit.aes = FALSE, colour = "#52606d", arrow = arrow(length = unit(.18, "cm")), linewidth = .7) +
  geom_point(size = 3) + geom_text(aes(label = label), vjust = -1.1, size = 3.1) +
  scale_colour_manual(values = c(issue = "#222222", available = "#0072B2", target = "#009E73"), guide = "none") +
  xlim(.7, 5.3) + ylim(-.2, .3) + labs(title = "E0_LAST_AVAILABLE operational input", subtitle = "latest legitimate environmental state held across h=1 to h=3") +
  theme_void() + theme(plot.title = element_text(face = "bold", hjust = .5), plot.subtitle = element_text(hjust = .5, size = 8, colour = "#52606d"))
f1 <- save_fig((p1a | p1b) / (p1c | p1d) + plot_annotation(tag_levels = "A"), "figure_01_domain_framework_corrected", 13, 9)
write_data(domain, "figure_01_domain_framework_data.csv")

# Figure 3: fixed-week surfaces with shared light-low/dark-high scales and
# boundaries above tiles. Expected-count maps are retained as an explicit candidate.
prob_limits <- range(maps$p_occurrence, na.rm = TRUE)
count_limits <- range(maps$expected_count, na.rm = TRUE)
prob_palette <- c("#fff7ec", "#fee8c8", "#fdbb84", "#e34a33", "#7f0000")
count_palette <- c("#f7fbff", "#deebf7", "#9ecae1", "#3182bd", "#08306b")
map_theme <- theme_map + theme(strip.text = element_text(size = 10), legend.key.width = unit(1.6, "cm"))
p3occ_map <- ggplot(maps, aes(lon, lat, fill = p_occurrence)) +
  geom_tile(width = md[["width"]], height = md[["height"]]) +
  geom_sf(data = boundary_focal, inherit.aes = FALSE, fill = NA, colour = "#263238", linewidth = .13) +
  geom_point(data = filter(maps, observed_positive > 0), aes(lon, lat), inherit.aes = FALSE, shape = 21, fill = "white", colour = "#111827", size = .95, stroke = .3) +
  facet_wrap(~target_week, nrow = 1, labeller = label_value) +
  scale_fill_gradientn(colours = prob_palette, limits = prob_limits, oob = scales::squish, name = "Occurrence\nprobability") +
  coord_focal + labs(title = "h=1 occurrence probability; observed positives overlaid", x = "Longitude", y = "Latitude") + map_theme
p3occ_time <- ggplot(times, aes(target_week)) +
  geom_line(aes(y = observed_positive_cells, colour = "Observed positive cells", group = 1), linewidth = .8) +
  geom_point(aes(y = observed_positive_cells, colour = "Observed positive cells"), size = 1.5) +
  geom_line(aes(y = expected_positive_cells, colour = "Expected number of positive cells", group = 1), linewidth = .8) +
  geom_point(aes(y = expected_positive_cells, colour = "Expected number of positive cells"), size = 1.5) +
  scale_colour_manual(values = c("Observed positive cells" = "#222222", "Expected number of positive cells" = "#0072B2")) +
  labs(title = "Focal occurrence burden, h=1", x = "Target week", y = "Cells", colour = NULL) + theme_science + theme(axis.text.x = element_text(angle = 45, hjust = 1))
p3occ <- save_fig(p3occ_map / p3occ_time + plot_annotation(tag_levels = "A"), "figure_03_mexico_texas_occurrence_corrected", 15, 9)
write_data(maps, "figure_03_focal_h1_map_data.csv")
write_data(times, "figure_03_focal_h1_time_series.csv")

p3count_map <- ggplot(maps, aes(lon, lat, fill = expected_count)) +
  geom_tile(width = md[["width"]], height = md[["height"]]) +
  geom_sf(data = boundary_focal, inherit.aes = FALSE, fill = NA, colour = "#263238", linewidth = .13) +
  geom_point(data = filter(maps, observed_count > 0), aes(lon, lat), inherit.aes = FALSE, shape = 21, fill = "white", colour = "#111827", size = .95, stroke = .3) +
  facet_wrap(~target_week, nrow = 1, labeller = label_value) +
  scale_fill_gradientn(colours = count_palette, limits = count_limits, oob = scales::squish, name = "Full hurdle\nexpected count") +
  coord_focal + labs(title = "Candidate full hurdle expected-count maps; observed counts overlaid", x = "Longitude", y = "Latitude") + map_theme
p3count_time <- ggplot(times, aes(target_week)) +
  geom_line(aes(y = observed_count, colour = "Observed total count", group = 1), linewidth = .8) + geom_point(aes(y = observed_count, colour = "Observed total count"), size = 1.5) +
  geom_line(aes(y = expected_count, colour = "Predicted total expected count", group = 1), linewidth = .8) + geom_point(aes(y = expected_count, colour = "Predicted total expected count"), size = 1.5) +
  scale_colour_manual(values = c("Observed total count" = "#222222", "Predicted total expected count" = "#D55E00")) +
  labs(title = "Candidate focal count burden, h=1", x = "Target week", y = "Count", colour = NULL) + theme_science + theme(axis.text.x = element_text(angle = 45, hjust = 1))
p3count <- save_fig(p3count_map / p3count_time + plot_annotation(tag_levels = "A"), "figure_03_mexico_texas_expected_count_corrected_candidate", 15, 9)

# Figure 6: rebuild the spatial support display from canonical cell-level
# P4 classifications as tiles; do not reuse the previous point-rendered map.
support_map <- read_csv(file.path(repo, "analysis", "p4_uncertainty_extrapolation", "results", "representative_support_map.csv")) %>%
  left_join(domain %>% select(model_node_id, row, column), by = "model_node_id")
support_map$support_class <- factor(support_map$support_class, levels = names(support_colors))
support_dims <- tile_dims(support_map)
support_coord <- coord_sf(xlim = c(min(support_map$lon) - .5, max(support_map$lon) + .5),
  ylim = c(min(support_map$lat) - .5, max(support_map$lat) + .5), expand = FALSE, crs = st_crs(4326), default_crs = st_crs(4326))
p6map <- ggplot(support_map, aes(lon, lat, fill = support_class)) +
  geom_tile(width = support_dims[["width"]], height = support_dims[["height"]]) +
  geom_sf(data = boundary_domain, inherit.aes = FALSE, fill = NA, colour = "#263238", linewidth = .12) +
  support_coord + scale_fill_manual(values = support_colors, drop = FALSE) +
  labs(title = "Canonical P4 predictor-space support", x = "Longitude", y = "Latitude", fill = "Support class") + map_aids() + theme_map
support <- read_csv(file.path(repo, "analysis", "p5a_environmental_proxy", "results", "support_metrics.csv")) %>%
  filter(proxy_id == "E0_LAST_AVAILABLE") %>% mutate(horizon_label = paste0("h=", horizon), support_class = factor(support_class, levels = names(support_colors)))
support_perf <- read_csv(file.path(repo, "analysis", "p4_uncertainty_extrapolation", "results", "performance_by_support.csv")) %>%
  mutate(horizon_label = paste0("h=", horizon), support_class = factor(support_class, levels = names(support_colors)))
p6prop <- ggplot(support, aes(horizon_label, proportion, fill = support_class)) + geom_col(width = .68) +
  geom_text(aes(label = ifelse(proportion > .04, scales::percent(proportion, accuracy = .1), "")), position = position_stack(vjust = .5), colour = "white", size = 2.8) +
  scale_y_continuous(labels = scales::percent, expand = expansion(mult = c(0, .03))) + scale_fill_manual(values = support_colors, drop = FALSE) +
  labs(title = "Support proportions under E0", x = NULL, y = "Rows", fill = "Support class") + theme_science
p6perf <- ggplot(support_perf, aes(horizon_label, brier, colour = support_class, group = support_class)) + geom_line(linewidth = .6) + geom_point(size = 2) +
  scale_colour_manual(values = support_colors, drop = FALSE) + labs(title = "Occurrence Brier by support class", x = NULL, y = "Brier score", colour = "Support class") + theme_science
p6defs <- ggplot(data.frame(x = 1:3, support_class = factor(names(support_colors), levels = names(support_colors))), aes(x, 1, fill = support_class)) +
  geom_tile(width = .9, height = .8) + geom_text(aes(label = as.character(support_class)), colour = "white", size = 3) +
  scale_fill_manual(values = support_colors, drop = FALSE) + scale_x_continuous(NULL, breaks = NULL) + scale_y_continuous(NULL, breaks = NULL) +
  labs(title = "Classes describe predictor-space representation") + theme_void() + theme(plot.title = element_text(face = "bold", hjust = .5, size = 10))
p6 <- save_fig((p6map | p6prop) / (p6perf | p6defs) + plot_annotation(tag_levels = "A"), "figure_06_support_extrapolation_corrected", 14, 10)
write_data(support_map, "figure_06_cell_level_support_map_data.csv")
write_data(support, "figure_06_support_proportions_data.csv")
write_data(support_perf, "figure_06_support_performance_data.csv")

# Operational trajectory candidate. History is retrospective h=1; future rows
# use only W36-origin predictions. Future observed outcomes are retained only
# as separately labelled subsequent observations for visual audit.
trajectory <- read_csv(file.path(results, "atlas_extract", "mexico_texas_issue_W36_forecast_trajectory.csv"))
trajectory$target_week <- as.character(trajectory$target_week)
hist <- trajectory %>% filter(trajectory_role == "observed_history", horizon == 1, target_week %in% time_weeks) %>%
  group_by(target_week) %>% summarise(observed_positive_cells = sum(observed_positive > 0), expected_positive_cells = sum(p_occurrence),
    observed_count = sum(observed_count), expected_count = sum(expected_count), .groups = "drop") %>% mutate(segment = "historical_h1")
future <- trajectory %>% filter(trajectory_role == "issue_W36_forecast", origin_week == "2026-W36", target_week %in% c("2026-W37", "2026-W38", "2026-W39"), horizon %in% 1:3) %>%
  group_by(target_week, horizon) %>% summarise(expected_positive_cells = sum(p_occurrence), expected_count = sum(expected_count), .groups = "drop") %>%
  mutate(segment = "issue_W36_forecast", observed_positive_cells = NA_real_, observed_count = NA_real_)
future_observed <- trajectory %>% filter(trajectory_role == "issue_W36_forecast", origin_week == "2026-W36", target_week %in% c("2026-W37", "2026-W38", "2026-W39"), horizon %in% 1:3) %>%
  group_by(target_week, horizon) %>% summarise(observed_positive_cells = sum(observed_positive > 0), observed_count = sum(observed_count), .groups = "drop") %>% mutate(segment = "subsequently_observed")
forecast_plot <- bind_rows(hist %>% mutate(horizon = 1L), future, future_observed) %>% mutate(target_week = factor(target_week, levels = c(time_weeks, "2026-W38", "2026-W39")))
forecast_plot <- forecast_plot %>% mutate(target_week = factor(as.character(target_week), levels = c(sprintf("2026-W%02d", 17:39))))
write_data(forecast_plot, "forecast_trajectory_aggregates.csv")
forecast_line <- bind_rows(hist %>% filter(target_week == "2026-W36") %>% transmute(target_week = as.character(target_week), expected_positive_cells, expected_count),
  future %>% transmute(target_week, expected_positive_cells, expected_count)) %>% mutate(target_week = factor(target_week, levels = sprintf("2026-W%02d", 17:39)))
forecast_history <- hist %>% mutate(target_week = factor(target_week, levels = sprintf("2026-W%02d", 17:39)))
future_obs <- future_observed %>% mutate(target_week = factor(target_week, levels = sprintf("2026-W%02d", 17:39)))
trajectory_layers <- function() list(
  geom_vline(xintercept = 20.5, linetype = 2, colour = "#52606d"),
  annotate("text", x = 20.5, y = Inf, label = "issue week W36", vjust = 1.3, hjust = 1.05, size = 3, colour = "#52606d")
)
tf_a <- ggplot() +
  geom_line(data = forecast_history, aes(target_week, observed_positive_cells, colour = "Observed positive cells", group = 1), linewidth = .75) + geom_point(data = forecast_history, aes(target_week, observed_positive_cells, colour = "Observed positive cells"), size = 1.5) +
  geom_line(data = forecast_history, aes(target_week, expected_positive_cells, colour = "Retrospective expected positive cells", group = 1), linewidth = .75) + geom_point(data = forecast_history, aes(target_week, expected_positive_cells, colour = "Retrospective expected positive cells"), size = 1.5) +
  geom_line(data = forecast_line, aes(target_week, expected_positive_cells, colour = "Issue-time forecast", group = 1), linewidth = .85, linetype = "dashed") + geom_point(data = future %>% mutate(target_week = factor(target_week, levels = sprintf("2026-W%02d", 17:39))), aes(target_week, expected_positive_cells, colour = "Issue-time forecast"), size = 1.8) +
  geom_point(data = future_obs, aes(target_week, observed_positive_cells, colour = "Subsequently observed"), size = 1.7, shape = 4, stroke = .8) + trajectory_layers() +
  scale_colour_manual(values = c("Observed positive cells" = "#222222", "Retrospective expected positive cells" = "#0072B2", "Issue-time forecast" = "#D55E00", "Subsequently observed" = "#7f8c8d")) +
  labs(title = "Focal occurrence trajectory candidate", subtitle = "W36 issue-time forecast extends to W37-W39; forecast values are not future observations", x = "Target week", y = "Expected number of positive cells", colour = NULL) + theme_science + theme(axis.text.x = element_text(angle = 45, hjust = 1))
tf_b <- ggplot() +
  geom_line(data = forecast_history, aes(target_week, observed_count, colour = "Observed total count", group = 1), linewidth = .75) + geom_point(data = forecast_history, aes(target_week, observed_count, colour = "Observed total count"), size = 1.5) +
  geom_line(data = forecast_history, aes(target_week, expected_count, colour = "Retrospective expected count", group = 1), linewidth = .75) + geom_point(data = forecast_history, aes(target_week, expected_count, colour = "Retrospective expected count"), size = 1.5) +
  geom_line(data = forecast_line, aes(target_week, expected_count, colour = "Issue-time forecast", group = 1), linewidth = .85, linetype = "dashed") + geom_point(data = future %>% mutate(target_week = factor(target_week, levels = sprintf("2026-W%02d", 17:39))), aes(target_week, expected_count, colour = "Issue-time forecast"), size = 1.8) +
  geom_point(data = future_obs, aes(target_week, observed_count, colour = "Subsequently observed"), size = 1.7, shape = 4, stroke = .8) + trajectory_layers() +
  scale_colour_manual(values = c("Observed total count" = "#222222", "Retrospective expected count" = "#0072B2", "Issue-time forecast" = "#D55E00", "Subsequently observed" = "#7f8c8d")) +
  labs(title = "Focal count trajectory candidate", subtitle = "Forecast path uses sum of cell-level full hurdle expected counts", x = "Target week", y = "Total count", colour = NULL) + theme_science + theme(axis.text.x = element_text(angle = 45, hjust = 1))
ft <- save_fig(tf_a / tf_b + plot_annotation(tag_levels = "A"), "forecast_trajectory_issue_W36_candidate", 13, 9)

# Small supplementary candidate set is reused from the already-qualified P7C
# outputs without scientific regeneration or visual-data substitution.
supp_reuse <- c(
  "S1_reliability_curves.svg", "S1_reliability_curves.png",
  "S2_frontier_sensitivity.svg", "S2_frontier_sensitivity.png",
  "S3_count_diagnostics_reference.png",
  "S4_proxy_error_support_transitions.svg", "S4_proxy_error_support_transitions.png"
)
for (f in supp_reuse) {
  src <- file.path(p7c, "figures", "supplement", f)
  if (!file.exists(src)) stop("missing reusable P7C supplementary figure: ", src)
  file.copy(src, file.path(supp, f), overwrite = TRUE)
}

# Explicit uncertainty audit: no qualified joint region-level predictive draws
# or equivalent regional interval artifact is present, so no ribbon is drawn.
uncertainty_audit <- list(
  status = "NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS",
  issue_week = "2026-W36", target_weeks = c("2026-W37", "2026-W38", "2026-W39"),
  reason = "Available uncertainty artifacts are cell-level; summing interval limits or assuming cell independence is not authorized.",
  ribbon_drawn = FALSE, qualified_region_level_source = NA_character_, model_fitting = FALSE
)
write_json(uncertainty_audit, file.path(results, "uncertainty_audit.json"), auto_unbox = TRUE, pretty = TRUE)

# Preserve Atlas extraction provenance locally without changing its recorded values.
atlas_manifest <- fromJSON(file.path(results, "atlas_extract", "forecast_trajectory_manifest.json"), simplifyVector = FALSE)
write_json(atlas_manifest, file.path(results, "forecast_trajectory_manifest.json"), auto_unbox = TRUE, pretty = TRUE)

source_registry <- data.frame(
  figure_id = c("Figure 1", "Figure 3", "Figure 3 candidate", "Figure 6", "Forecast candidate"),
  panel_id = c("A-D", "A-C", "A-B", "A-D", "A-B"),
  source_phase = c("P2/P5A/P6/P7", "P2/P7C", "P2/P7C", "P4/P5A", "P2/P5/P5A"),
  source_file = c(
    "analysis/p7c_figure_refinement/results/plot_data/figure_01_domain_framework_data.csv; analysis/p7c_figure_refinement/results/boundaries/study_states_wgs84.csv",
    "analysis/p7c_figure_refinement/results/plot_data/figure_03_focal_h1_map_data.csv; analysis/p7c_figure_refinement/results/plot_data/figure_03_focal_h1_time_series.csv",
    "analysis/p7c_figure_refinement/results/plot_data/figure_03_focal_h1_map_data.csv; analysis/p7c_figure_refinement/results/plot_data/figure_03_focal_h1_time_series.csv",
    "analysis/p4_uncertainty_extrapolation/results/representative_support_map.csv; analysis/p5a_environmental_proxy/results/support_metrics.csv; analysis/p4_uncertainty_extrapolation/results/performance_by_support.csv",
    "analysis/p7d_cartography_forecast/results/atlas_extract/mexico_texas_issue_W36_forecast_trajectory.csv"),
  source_fields = c("lon,lat,region,geometry_wkt", "lon,lat,target_week,p_occurrence,observed_positive,expected_count,observed_count", "lon,lat,target_week,expected_count,observed_count", "lon,lat,support_class,novelty_knn_distance,proportion,brier", "origin_week,target_week,horizon,observed_count,observed_positive,p_occurrence,expected_count,trajectory_role,observation_status"),
  transformations = c("fixed named domain palette; geom_tile then geom_sf", "fixed h=1 weeks; focal filter; shared sequential scale; geom_tile then geom_sf", "same fixed weeks and filters; expected-count candidate", "canonical support classes; geom_tile; no P4 threshold change", "bounded aggregation: sum(p_occurrence) and sum(expected_count); future observations not used in forecast values"),
  filtering = c("full domain and fixed focal bbox", "horizon=1; five prespecified weeks", "horizon=1; five prespecified weeks", "all canonical support cells; E0 h=1:3 summaries", "history W17-W36 h=1; issue W36 forecast W37-W39 h=1:3"),
  geometry = c("EPSG:4326; boundary orientation only", "EPSG:4326; focal bbox -107.5:-96,24:33; 1,689 cells", "EPSG:4326; focal bbox -107.5:-96,24:33; 1,689 cells", "EPSG:4326; full 10,037-cell support map", "focal bbox; 1,689 cells"),
  plotting_script = "analysis/p7d_cartography_forecast/scripts/generate_p7d_figures.R",
  output_file = c(rel(f1[["svg"]]), rel(p3occ[["svg"]]), rel(p3count[["svg"]]), rel(p6[["svg"]]), rel(ft[["svg"]])),
  underlying_data_file = c("analysis/p7d_cartography_forecast/results/plot_data/figure_01_domain_framework_data.csv", "analysis/p7d_cartography_forecast/results/plot_data/figure_03_focal_h1_map_data.csv; analysis/p7d_cartography_forecast/results/plot_data/figure_03_focal_h1_time_series.csv", "analysis/p7d_cartography_forecast/results/plot_data/figure_03_focal_h1_map_data.csv; analysis/p7d_cartography_forecast/results/plot_data/figure_03_focal_h1_time_series.csv", "analysis/p7d_cartography_forecast/results/plot_data/figure_06_cell_level_support_map_data.csv", "analysis/p7d_cartography_forecast/results/plot_data/forecast_trajectory_aggregates.csv"),
  stringsAsFactors = FALSE
)
supp_registry <- data.frame(
  figure_id = c("S1", "S2", "S3", "S4"), panel_id = c("A", "A", "A", "A-B"),
  source_phase = c("P2/P7C", "P3/P7C", "P3/P7C", "P5A/P7C"),
  source_file = c(
    "analysis/p7c_figure_refinement/figures/supplement/S1_reliability_curves.svg",
    "analysis/p7c_figure_refinement/figures/supplement/S2_frontier_sensitivity.svg",
    "analysis/p7c_figure_refinement/figures/supplement/S3_count_diagnostics_reference.png",
    "analysis/p7c_figure_refinement/figures/supplement/S4_proxy_error_support_transitions.svg"),
  source_fields = c("canonical P2 reliability bins", "canonical P3 frontier sensitivity", "canonical P3 count diagnostic", "canonical P5A proxy error and support transitions"),
  transformations = "reused without scientific or plotting-data changes",
  filtering = "canonical P7C output",
  geometry = "not applicable",
  plotting_script = "P7C canonical renderer; P7D copy only",
  output_file = c("analysis/p7d_cartography_forecast/figures/supplement_candidates/S1_reliability_curves.svg", "analysis/p7d_cartography_forecast/figures/supplement_candidates/S2_frontier_sensitivity.svg", "analysis/p7d_cartography_forecast/figures/supplement_candidates/S3_count_diagnostics_reference.png", "analysis/p7d_cartography_forecast/figures/supplement_candidates/S4_proxy_error_support_transitions.svg"),
  underlying_data_file = c("analysis/p7c_figure_refinement/results/plot_data/supplement_S1_reliability_data.csv", "analysis/p7c_figure_refinement/results/plot_data/supplement_S2_frontier_sensitivity_data.csv", "analysis/p3_robustness/figures/P3-2_count_error_by_magnitude.png", "analysis/p7c_figure_refinement/results/plot_data/supplement_S4_environmental_error_family_data.csv; analysis/p7c_figure_refinement/results/plot_data/supplement_S4_support_transition_data.csv"),
  stringsAsFactors = FALSE
)
source_registry <- bind_rows(source_registry, supp_registry)
source_registry$output_hash <- vapply(source_registry$output_file, function(x) sha256(file.path(repo, x)), character(1))
source_registry$source_hashes <- vapply(source_registry$underlying_data_file, function(x) {
  paths <- strsplit(x, "; ", fixed = TRUE)[[1]]
  paste(vapply(paths, function(y) sha256(file.path(repo, y)), character(1)), collapse = ";")
}, character(1))
write.csv(source_registry, file.path(results, "figure_source_registry.csv"), row.names = FALSE, quote = TRUE, na = "")

support_audit <- list(source = rel(file.path(repo, "analysis/p4_uncertainty_extrapolation/results/representative_support_map.csv")), source_sha256 = sha256(file.path(repo, "analysis/p4_uncertainty_extrapolation/results/representative_support_map.csv")), rows = nrow(support_map), unique_cells = length(unique(support_map$model_node_id)), classes = sort(unique(as.character(support_map$support_class))), rendering = "geom_tile followed by geom_sf", prior_point_map_reused = FALSE)
write_json(support_audit, file.path(results, "support_source_audit.json"), auto_unbox = TRUE, pretty = TRUE)
rendering_contract <- list(crs = "EPSG:4326", focal_bbox = fixed_bbox, focal_cells = 1689L, map_weeks = map_weeks, map_horizon = 1L,
  figure_1_shared_domain_colors = unname(domain_colors), figure_3_occurrence_palette = "light-low-to-dark-high sequential", figure_3_expected_count_palette = "light-low-to-dark-high sequential",
  figure_3_layers = c("geom_tile", "geom_sf", "observed_positive_points"), figure_6_surface_geometry = "geom_tile", figure_6_layers = c("geom_tile", "geom_sf"), north_arrow = TRUE, scale_bar = TRUE,
  forecast_issue_week = "2026-W36", forecast_targets = c("2026-W37", "2026-W38", "2026-W39"), uncertainty_ribbon = "NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS")
write_json(rendering_contract, file.path(results, "rendering_contract.json"), auto_unbox = TRUE, pretty = TRUE)

writeLines(c(
  "A. The full-domain and focal panels use the same named domain colors and the tracked WGS84 boundary derivative, rendered above the cell tiles. B. The focal extent is fixed at longitude -107.5 to -96.0 and latitude 24.0 to 33.0. C. STRUCTURED_A3 combines occurrence probability with conditional positive-count prediction. D. E0_LAST_AVAILABLE holds the latest legitimately available environmental state across h=1 to h=3. Boundaries are cartographic orientation only.",
  ""), file.path(captions, "figure_01.caption.md"))
writeLines("Focal-region h=1 occurrence probability for the prespecified target weeks 2026-W17, W22, W27, W32, and W37. All maps use identical spatial and probability scales, sequential light-low/dark-high colors, and boundaries, north arrows, and scale bars above the tile surface. White outlined cells mark observed positives. The time series compares observed positive cells with the expected number of positive cells, defined as the sum of cell-level occurrence probabilities; it is not a regional risk index.", file.path(captions, "figure_03_occurrence.caption.md"))
writeLines("Candidate focal-region h=1 full hurdle expected-count maps for the same fixed weeks and extent. All maps use one count scale, with observed counts overlaid. The accompanying time series uses the sum of cell-level full hurdle expected counts. This is a descriptive visualization candidate and does not change the count model.", file.path(captions, "figure_03_expected_count.caption.md"))
writeLines("P4 support classes rebuilt from canonical cell-level classifications and rendered as areal tiles. SUPPORTED, CAUTION, and EXTRAPOLATIVE describe predictor-space representation under the unchanged P4 thresholds. They are not confidence intervals, direct measures of correctness, or causal categories. The support map is not a point-rendered reuse of the prior P4 display.", file.path(captions, "figure_06.caption.md"))
writeLines("Candidate focal-region operational trajectory for an issue at 2026-W36. Historical h=1 rows cover W17-W36; the dashed W37-W39 path uses only the single W36-origin predictions under E0_LAST_AVAILABLE. Crosses are subsequently observed outcomes shown separately for audit and are not connected as forecasts. No regional uncertainty ribbon is shown because no qualified joint region-level artifact supports one.", file.path(captions, "forecast_trajectory.caption.md"))

decision <- list(
  decision = "P7D_CARTOGRAPHY_FORECAST_SUPPORTED_WITH_LIMITATIONS", no_model_fitting = TRUE,
  changes = c("corrected boundary layering", "shared Figure 1 domain colors", "shared light-low/dark-high Figure 3 scales", "cell-level geom_tile P4 support map", "bounded W36 operational trajectory candidate"),
  limitations = c("no qualified region-level uncertainty artifact for a forecast ribbon", "boundary derivative is cartographic orientation only", "expected-count maps remain a visual candidate", "forecast trajectory is a descriptive candidate, not a scheduler or deployment")
)
write_json(decision, file.path(results, "decision.json"), auto_unbox = TRUE, pretty = TRUE)
metadata <- list(phase = "P7D", script = "analysis/p7d_cartography_forecast/scripts/generate_p7d_figures.R", r_version = R.version.string,
  model_fitting = FALSE, scientific_model_modified = FALSE, atlas_extract = "analysis/p7d_cartography_forecast/results/atlas_extract/forecast_trajectory_manifest.json",
  source_registry = "analysis/p7d_cartography_forecast/results/figure_source_registry.csv", uncertainty_status = "NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS")
write_json(metadata, file.path(results, "run_metadata.json"), auto_unbox = TRUE, pretty = TRUE)
cat("P7D_FIGURES_GENERATED\n")

