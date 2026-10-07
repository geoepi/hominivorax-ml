#!/usr/bin/env Rscript

# Reusable, frame-wise animation utility for the persisted Structured A3 GeoTIFFs.
# It never recomputes predictions. GIF output uses the repository's small
# dependency-free PNG-to-GIF helper when gifski is unavailable; MP4 uses ffmpeg
# only when that renderer is already installed.

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

coerce_animation_boundaries <- function(boundaries, template) {
  if (is.null(boundaries)) return(list())
  if (!is.list(boundaries)) boundaries <- list(boundaries)
  target <- sf::st_crs(terra::crs(template))
  lapply(boundaries, function(boundary) {
    if (is.character(boundary)) boundary <- sf::st_read(boundary, quiet = TRUE)
    if (inherits(boundary, "sf")) return(sf::st_transform(boundary, target))
    if (inherits(boundary, "SpatVector")) return(terra::project(boundary, terra::crs(template)))
    stop("boundaries must contain sf, SpatVector, or shapefile paths")
  })
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
  if (is.null(limits)) limits <- c(0, if (table$variable[[1L]] == "p_occurrence") 1 else all_max)
  if (length(limits) != 2L || !all(is.finite(limits)) || limits[[1L]] >= limits[[2L]]) stop("limits must be finite and increasing")
  dir.create(dirname(output_file), recursive = TRUE, showWarnings = FALSE)
  frame_dir <- tempfile("structured_a3_animation_frames_")
  dir.create(frame_dir)
  on.exit(unlink(frame_dir, recursive = TRUE, force = TRUE), add = TRUE)
  palette <- grDevices::hcl.colors(256L, palette = "Inferno")
  frame_paths <- file.path(frame_dir, sprintf("frame_%05d.png", seq_len(nrow(table))))
  for (index in seq_len(nrow(table))) {
    raster <- terra::rast(table$file[[index]])
    grDevices::png(frame_paths[[index]], width = width, height = height, res = 96)
    oldpar <- graphics::par(no.readonly = TRUE)
    graphics::par(mar = c(1.5, 1.5, 4.5, 5.5), oma = c(0, 0, 0, 0))
    terra::plot(raster, col = palette, zlim = limits, axes = FALSE, legend = TRUE,
                main = paste0(title_prefix, " — ", value_label),
                sub = paste0("Week: ", table$week[[index]], " | ", provenance),
                plg = list(title = value_label, cex = 0.75))
    if (length(boundary_layers)) {
      for (boundary in boundary_layers) {
        if (inherits(boundary, "sf")) graphics::plot(sf::st_geometry(boundary), add = TRUE, border = "grey35", lwd = 0.35)
        else terra::plot(boundary, add = TRUE, border = "grey35", lwd = 0.35)
      }
    }
    graphics::par(oldpar)
    grDevices::dev.off()
  }
  if (format == "gif") {
    helper <- animation_python_helper(helper_path)
    python <- Sys.getenv("PYTHON", unset = "/project/disease_ecology/STGNN-python-venv/bin/python")
    if (!file.exists(python)) python <- Sys.which("python3")
    if (!nzchar(python) || !file.exists(python)) stop("No Python interpreter available for GIF encoding")
    status <- system2(python, c(helper, "--frames", frame_dir, "--output", normalizePath(output_file, winslash = "/", mustWork = FALSE), "--fps", as.character(fps)), stdout = TRUE, stderr = TRUE)
    if (!file.exists(output_file)) stop("GIF encoder did not create ", output_file, ": ", paste(status, collapse = " | "))
    return(list(status = "GIF COMPLETE", output_file = normalizePath(output_file, winslash = "/"), frames = nrow(table), first_week = table$week[[1L]], last_week = table$week[[nrow(table)]], fps = fps, width = width, height = height, legend_min = limits[[1L]], legend_max = limits[[2L]], renderer = "dependency-free PNG-to-GIF helper"))
  }
  ffmpeg <- Sys.which("ffmpeg")
  if (!nzchar(ffmpeg)) return(list(status = "MP4 RENDERER UNAVAILABLE", output_file = normalizePath(output_file, winslash = "/", mustWork = FALSE), frames = nrow(table), first_week = table$week[[1L]], last_week = table$week[[nrow(table)]], fps = fps, width = width, height = height, legend_min = limits[[1L]], legend_max = limits[[2L]], renderer = NA_character_))
  status <- system2(ffmpeg, c("-y", "-loglevel", "error", "-framerate", as.character(fps), "-i", file.path(frame_dir, "frame_%05d.png"), "-pix_fmt", "yuv420p", output_file), stdout = TRUE, stderr = TRUE)
  if (!file.exists(output_file)) stop("ffmpeg did not create ", output_file, ": ", paste(status, collapse = " | "))
  list(status = "MP4 COMPLETE", output_file = normalizePath(output_file, winslash = "/"), frames = nrow(table), first_week = table$week[[1L]], last_week = table$week[[nrow(table)]], fps = fps, width = width, height = height, legend_min = limits[[1L]], legend_max = limits[[2L]], renderer = ffmpeg)
}
