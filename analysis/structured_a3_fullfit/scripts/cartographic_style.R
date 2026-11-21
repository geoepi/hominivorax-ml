# Shared cartographic style for Structured A3 geographic prediction figures.
# This file defines display styling only; it never transforms stored values.

A3_CARTOGRAPHIC_PALETTE <- c(
  "#F4F4F4",
  "#E0EDF7",
  "#A6CEE3",
  "#5596C5",
  "#2166AC",
  "#08306B"
)

A3_CARTOGRAPHIC_NODATA <- "#BDBDBD"

a3_cartographic_luminance <- function(colours) {
  rgb <- t(grDevices::col2rgb(colours)) / 255
  linear <- ifelse(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055)^2.4)
  rowSums(sweep(linear, 2L, c(0.2126, 0.7152, 0.0722), `*`))
}

a3_cartographic_palette_check <- function() {
  luminance <- a3_cartographic_luminance(A3_CARTOGRAPHIC_PALETTE)
  list(
    colours = A3_CARTOGRAPHIC_PALETTE,
    relative_luminance = luminance,
    zero_colour = A3_CARTOGRAPHIC_PALETTE[[1L]],
    monotonic_light_to_dark = all(diff(luminance) < 0),
    nodata_colour = A3_CARTOGRAPHIC_NODATA
  )
}

a3_cartographic_fill_scale <- function(
    limits,
    label,
    breaks = ggplot2::waiver(),
    labels = ggplot2::waiver(),
    trans = NULL,
    na.value = A3_CARTOGRAPHIC_NODATA) {
  if (!is.numeric(limits) || length(limits) != 2L || any(!is.finite(limits)) ||
      limits[[1L]] != 0 || limits[[2L]] <= 0) {
    stop("Cartographic fill limits must be finite and start at zero")
  }
  args <- list(
    colours = A3_CARTOGRAPHIC_PALETTE,
    limits = limits,
    breaks = breaks,
    labels = labels,
    oob = scales::squish,
    na.value = na.value,
    name = label,
    guide = ggplot2::guide_colorbar(
      barheight = grid::unit(48, "mm"),
      frame.colour = "grey55",
      ticks.colour = "grey45"
    )
  )
  if (!is.null(trans)) args$trans <- trans
  do.call(ggplot2::scale_fill_gradientn, args)
}

a3_scaled_log1p_trans <- function(reference_value) {
  if (length(reference_value) != 1L || !is.finite(reference_value) || reference_value <= 0) {
    stop("The log1p display reference must be one positive finite value")
  }
  scales::trans_new(
    name = paste0("log1p_count_ref_", format(reference_value, scientific = TRUE)),
    transform = function(x) log1p(x / reference_value),
    inverse = function(x) reference_value * expm1(x),
    breaks = function(x) {
      original_limits <- reference_value * expm1(x)
      original_breaks <- pretty(c(0, original_limits), n = 6L)
      original_breaks <- original_breaks[original_breaks >= 0]
      log1p(original_breaks / reference_value)
    },
    format = function(x) scales::label_number(accuracy = 0.001)(reference_value * expm1(x)),
    domain = c(0, Inf)
  )
}
