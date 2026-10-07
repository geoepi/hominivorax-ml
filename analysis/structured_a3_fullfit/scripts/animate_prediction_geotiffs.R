#!/usr/bin/env Rscript

# Reusable, frame-wise animation utility for the persisted Structured A3 GeoTIFFs.
# It never recomputes predictions. Each frame derives x/y/value together from
# terra::as.data.frame(), then renders an opaque, fixed-extent ggplot frame.

parse_animation_week_files <- function(raster_dir) {
  files <- list.files(raster_dir, pattern = "\\.tif$", full.names = TRUE)
  if (!length(files)) stop("No GeoTIFF files found in ", raster_dir)
  names <- basename(files)
  match <- regexec("^a3_(p_occurrence|conditional_count|expected_count)_([0-9]{4})_W([0-9]{2})\\.tif$", names)
  parts <- regmatches(names, match)
  good <- lengths(parts) == 4L
  if (!all(good)) stop("Unrecognized GeoTIFF filename(s): ", paste(names[!good], collapse = ", "))
  table <- data.frame(
    file = files,
    variable = vapply(parts, `[[`, character(1), 2L),
    year = as.integer(vapply(parts, `[[`, character(1), 3L)),
    week_number = as.integer(vapply(parts, `[[`, character(1), 4L)),
    week = sprintf("%04d-W%02d", as.integer(vapply(parts, `[[`, character(1), 3L)), as.integer(vapply(parts, `[[`, character(1), 4L))),
    stringsAsFactors = FALSE
  )
  table[order(table$year, table$week_number), , drop = FALSE]
}

animation_raster_geometry <- function(raster) {
  e <- as.vector(terra::ext(raster))
  r <- terra::res(raster)
  o <- terra::origin(raster)
  list(
    raster_crs = terra::crs(raster),
    nrow = terra::nrow(raster),
    ncol = terra::ncol(raster),
    xmin = unname(e[1]), xmax = unname(e[2]),
    ymin = unname(e[3]), ymax = unname(e[4]),
    resolution_x = unname(r[1]), resolution_y = unname(r[2]),
    origin_x = unname(o[1]), origin_y = unname(o[2])
  )
}

animation_frame_data <- function(path, week = NULL) {
  raster <- terra::rast(path)
  frame <- terra::as.data.frame(raster, xy = TRUE, cells = FALSE, na.rm = FALSE)
  if (ncol(frame) != 3L) stop("Expected one raster value column in ", path)
  names(frame)[3] <- "value"
  if (!is.null(week)) frame$week <- week
  frame
}

animation_cell_identity_check <- function(path, frame, minimum_cells = 20L) {
  raster <- terra::rast(path)
  values <- terra::values(raster, mat = FALSE)
  valid <- which(!is.na(values))
  if (!length(valid)) stop("No valid raster cells available for identity check: ", path)
  coordinates <- terra::xyFromCell(raster, valid)
  center <- c(mean(coordinates[, 1]), mean(coordinates[, 2]))
  choose_cells <- c(
    valid[order(coordinates[, 2], decreasing = TRUE)[seq_len(min(3L, length(valid)))]],
    valid[order(coordinates[, 2], decreasing = FALSE)[seq_len(min(3L, length(valid)))]],
    valid[order(coordinates[, 1], decreasing = TRUE)[seq_len(min(3L, length(valid)))]],
    valid[order(coordinates[, 1], decreasing = FALSE)[seq_len(min(3L, length(valid)))]],
    valid[order((coordinates[, 1] - center[1])^2 + (coordinates[, 2] - center[2])^2)[seq_len(min(3L, length(valid)))]],
    valid[order(values[valid], decreasing = TRUE)[seq_len(min(4L, length(valid)))]],
    valid[order(values[valid], decreasing = FALSE)[seq_len(min(4L, length(valid)))] ]
  )
  choose_cells <- unique(choose_cells)
  if (length(choose_cells) < minimum_cells) choose_cells <- unique(c(choose_cells, valid[seq_len(min(minimum_cells, length(valid)))]))
  choose_cells <- choose_cells[seq_len(min(length(choose_cells), length(valid)))]
  animation_cells <- terra::cellFromXY(raster, cbind(frame$x, frame$y))
  frame_rows <- match(choose_cells, animation_cells)
  if (anyNA(frame_rows)) stop("Animation dataframe does not cover selected raster cells")
  xy <- terra::xyFromCell(raster, choose_cells)
  check <- data.frame(
    cell_number = choose_cells,
    x = xy[, 1],
    y = xy[, 2],
    geotiff_value = as.numeric(values[choose_cells]),
    animation_value = as.numeric(frame$value[frame_rows]),
    difference = as.numeric(frame$value[frame_rows]) - as.numeric(values[choose_cells])
  )
  check$selection <- "spatial/high-low diagnostic cell"
  max_difference <- max(abs(check$difference), na.rm = TRUE)
  list(table = check, max_absolute_difference = max_difference, status = if (is.finite(max_difference) && max_difference <= 1e-12) "PASS" else "FAIL")
}

coerce_animation_boundaries <- function(boundaries, template) {
  if (is.null(boundaries)) return(list())
  if (!is.list(boundaries)) boundaries <- list(boundaries)
  target <- sf::st_crs(terra::crs(template))
  lapply(boundaries, function(boundary) {
    if (is.character(boundary)) boundary <- sf::st_read(boundary, quiet = TRUE)
    if (inherits(boundary, "sf")) return(sf::st_transform(boundary, target))
    if (inherits(boundary, "SpatVector")) return(sf::st_as_sf(terra::project(boundary, terra::crs(template))))
    stop("boundaries must contain sf, SpatVector, or shapefile paths")
  })
}

render_animation_frame <- function(frame, template, boundaries, limits, value_label, title_prefix, week, width = 800, height = 700, provenance = NULL) {
  geometry <- animation_raster_geometry(template)
  target_crs <- sf::st_crs(terra::crs(template))
  subtitle <- paste0("Week: ", week)
  if (!is.null(provenance)) subtitle <- paste0(subtitle, " | ", provenance)
  plot <- ggplot2::ggplot(frame, ggplot2::aes(x = x, y = y, fill = value)) +
    ggplot2::geom_raster(na.rm = FALSE) +
    ggplot2::scale_fill_viridis_c(
      option = "magma", limits = limits, oob = scales::squish,
      na.value = "white", name = value_label
    ) +
    ggplot2::coord_sf(
      crs = target_crs,
      xlim = c(geometry$xmin, geometry$xmax), ylim = c(geometry$ymin, geometry$ymax),
      expand = FALSE, datum = NA
    ) +
    ggplot2::labs(
      title = paste0(title_prefix, " - ", value_label),
      subtitle = subtitle
    ) +
    ggplot2::theme_void(base_size = 12) +
    ggplot2::theme(
      plot.background = ggplot2::element_rect(fill = "white", color = NA),
      panel.background = ggplot2::element_rect(fill = "white", color = NA),
      legend.background = ggplot2::element_rect(fill = "white", color = NA),
      legend.key = ggplot2::element_rect(fill = "white", color = NA),
      plot.title = ggplot2::element_text(hjust = 0.5, face = "bold"),
      plot.subtitle = ggplot2::element_text(hjust = 0.5, size = 9),
      legend.position = "right"
    )
  for (boundary in boundaries) {
    plot <- plot + ggplot2::geom_sf(data = boundary, inherit.aes = FALSE, fill = NA, color = "grey35", linewidth = 0.35)
  }
  plot
}

animation_python_helper <- function(helper_path = NULL) {
  if (!is.null(helper_path)) return(normalizePath(helper_path, winslash = "/", mustWork = TRUE))
  candidates <- c(
    file.path(Sys.getenv("A3_FULLFIT_SCRIPT_DIR", unset = ""), "gif_from_png_frames.py"),
    file.path(getwd(), "analysis/structured_a3_fullfit/scripts/gif_from_png_frames.py")
  )
  candidates <- candidates[nzchar(candidates) & file.exists(candidates)]
  if (!length(candidates)) stop("gif_from_png_frames.py was not found; supply helper_path")
  normalizePath(candidates[[1L]], winslash = "/", mustWork = TRUE)
}

animate_prediction_geotiffs <- function(
    raster_dir,
    output_file,
    value_label,
    title_prefix,
    boundaries = NULL,
    fps = 4,
    width = 800,
    height = 700,
    limits = NULL,
    format = c("gif", "mp4"),
    helper_path = NULL,
    provenance = "Full-fit through 2026-W29 | Descriptive output; not independent validation") {
  format <- match.arg(format)
  if (length(fps) != 1L || !is.finite(fps) || fps <= 0) stop("fps must be positive")
  if (length(width) != 1L || length(height) != 1L || width <= 0 || height <= 0) stop("width and height must be positive")
  table <- parse_animation_week_files(raster_dir)
  template <- terra::rast(table$file[[1L]])
  for (path in table$file[-1L]) terra::compareGeom(template, terra::rast(path), stopOnError = TRUE)
  boundary_layers <- coerce_animation_boundaries(boundaries, template)
  all_max <- max(vapply(table$file, function(path) max(terra::values(terra::rast(path), mat = FALSE), na.rm = TRUE), numeric(1L)))
  if (!is.finite(all_max)) stop("No finite raster values found in ", raster_dir)
  if (is.null(limits)) limits <- c(0, if (table$variable[[1L]] == "p_occurrence") 0.6 else all_max)
  if (length(limits) != 2L || !all(is.finite(limits)) || limits[[1L]] >= limits[[2L]]) stop("limits must be finite and increasing")
  dir.create(dirname(output_file), recursive = TRUE, showWarnings = FALSE)
  frame_dir <- tempfile("structured_a3_animation_frames_")
  dir.create(frame_dir)
  on.exit(unlink(frame_dir, recursive = TRUE, force = TRUE), add = TRUE)
  frame_paths <- file.path(frame_dir, sprintf("frame_%05d.png", seq_len(nrow(table))))
  for (index in seq_len(nrow(table))) {
    raster <- terra::rast(table$file[[index]])
    frame <- animation_frame_data(table$file[[index]], table$week[[index]])
    frame_plot <- render_animation_frame(frame, raster, boundary_layers, limits, value_label, title_prefix, table$week[[index]], width, height, provenance)
    ggplot2::ggsave(frame_paths[[index]], frame_plot, width = width / 96, height = height / 96, units = "in", dpi = 96, bg = "white", limitsize = FALSE)
  }
  geometry <- animation_raster_geometry(template)
  result <- list(
    output_file = normalizePath(output_file, winslash = "/", mustWork = FALSE),
    frames = nrow(table), first_week = table$week[[1L]], last_week = table$week[[nrow(table)]],
    fps = fps, width = width, height = height, legend_min = limits[[1L]], legend_max = limits[[2L]],
    raster_crs = geometry$raster_crs, nrow = geometry$nrow, ncol = geometry$ncol,
    xmin = geometry$xmin, xmax = geometry$xmax, ymin = geometry$ymin, ymax = geometry$ymax,
    resolution_x = geometry$resolution_x, resolution_y = geometry$resolution_y,
    origin_x = geometry$origin_x, origin_y = geometry$origin_y,
    opaque_background = TRUE,
    boundary_alignment = "transformed to raster CRS; fixed raster extent",
    renderer = NA_character_
  )
  if (format == "gif") {
    helper <- animation_python_helper(helper_path)
    python <- Sys.getenv("PYTHON", unset = "/project/disease_ecology/STGNN-python-venv/bin/python")
    if (!file.exists(python)) python <- Sys.which("python3")
    if (!nzchar(python) || !file.exists(python)) stop("No Python interpreter available for GIF encoding")
    status <- system2(python, c(helper, "--frames", frame_dir, "--output", normalizePath(output_file, winslash = "/", mustWork = FALSE), "--fps", as.character(fps)), stdout = TRUE, stderr = TRUE)
    if (!file.exists(output_file)) stop("GIF encoder did not create ", output_file, ": ", paste(status, collapse = " | "))
    result$status <- "GIF COMPLETE"
    result$renderer <- "decoder-synchronized dependency-free PNG-to-GIF helper"
    return(result)
  }
  ffmpeg <- Sys.which("ffmpeg")
  if (!nzchar(ffmpeg)) {
    result$status <- "MP4 RENDERER UNAVAILABLE"
    return(result)
  }
  status <- system2(ffmpeg, c("-y", "-loglevel", "error", "-framerate", as.character(fps), "-i", file.path(frame_dir, "frame_%05d.png"), "-pix_fmt", "yuv420p", output_file), stdout = TRUE, stderr = TRUE)
  if (!file.exists(output_file)) stop("ffmpeg did not create ", output_file, ": ", paste(status, collapse = " | "))
  result$status <- "MP4 COMPLETE"
  result$renderer <- ffmpeg
  result
}
