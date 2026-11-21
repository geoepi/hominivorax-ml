#!/usr/bin/env Rscript

script_file <- sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE)[[1L]])
script_path <- normalizePath(script_file, winslash = "/", mustWork = TRUE)
source(file.path(dirname(script_path), "cartographic_style.R"))

stopifnot(identical(
  A3_CARTOGRAPHIC_PALETTE,
  c("#F4F4F4", "#E0EDF7", "#A6CEE3", "#5596C5", "#2166AC", "#08306B")
))
palette_check <- a3_cartographic_palette_check()
stopifnot(palette_check$monotonic_light_to_dark)
stopifnot(identical(palette_check$zero_colour, "#F4F4F4"))

sample <- data.frame(x = 1:4, y = 1, value = c(0, 0.25, 0.75, NA_real_))
plot <- ggplot2::ggplot(sample, ggplot2::aes(x, y, fill = value)) +
  ggplot2::geom_tile() +
  a3_cartographic_fill_scale(c(0, 1), "Test probability")
fill <- ggplot2::ggplot_build(plot)$data[[1L]]$fill
stopifnot(identical(toupper(fill[[1L]]), "#F4F4F4"))
stopifnot(identical(toupper(fill[[4L]]), A3_CARTOGRAPHIC_NODATA))
mapped_luminance <- a3_cartographic_luminance(fill[1:3])
stopifnot(all(diff(mapped_luminance) < 0))

reference <- 0.0015
trans <- a3_scaled_log1p_trans(reference)
mapped <- trans$transform(c(0, reference, 1))
stopifnot(all(is.finite(mapped)), all(diff(mapped) > 0))
stopifnot(max(abs(trans$inverse(mapped) - c(0, reference, 1))) < 1e-12)

cat("cartographic style tests passed\n")
