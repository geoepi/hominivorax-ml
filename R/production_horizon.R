# Horizon and environmental-week helpers for production data construction.

production_week_horizon <- function(analysis_start, analysis_end, history_weeks = 52L) {
  analysis_start <- iso_week_start(as.Date(analysis_start))
  analysis_end <- iso_week_start(as.Date(analysis_end))
  history_weeks <- as.integer(history_weeks)
  if (length(analysis_start) != 1L || is.na(analysis_start)) stop("analysis start is invalid")
  if (length(analysis_end) != 1L || is.na(analysis_end)) stop("analysis end is invalid")
  if (!is.finite(history_weeks) || history_weeks < 0L) stop("history-weeks must be non-negative")
  if (analysis_end < analysis_start) stop("analysis end precedes analysis start")

  target_dates <- seq(analysis_start, analysis_end, by = "7 days")
  target_week_ids <- iso_week_id(target_dates)
  if (anyDuplicated(target_week_ids) || !all(target_dates == iso_week_start(target_dates))) {
    stop("target horizon is not a contiguous Monday-aligned ISO-week sequence")
  }

  history_dates <- seq(analysis_start - 7L * history_weeks, analysis_end, by = "7 days")
  history_week_ids <- iso_week_id(history_dates)
  if (length(history_week_ids) != length(target_week_ids) + history_weeks) {
    stop("history index mismatch")
  }
  list(
    analysis_start = analysis_start,
    analysis_end = analysis_end,
    history_weeks = history_weeks,
    target_dates = target_dates,
    target_week_ids = target_week_ids,
    history_dates = history_dates,
    history_week_ids = history_week_ids
  )
}

resolve_production_week_files <- function(product, environment_root, required_week_ids) {
  weekly_directory <- file.path(environment_root, product, "weekly")
  paths <- list.files(
    weekly_directory,
    full.names = TRUE,
    pattern = "\\.(tif|tiff)$",
    ignore.case = TRUE
  )
  if (!length(paths)) stop("no weekly rasters found for ", product, ": ", weekly_directory)
  parsed <- lapply(paths, parse_week_identifier)
  ids <- vapply(parsed, `[[`, character(1L), "week_id")
  if (anyNA(ids)) stop("unparseable environmental week filename for ", product)
  duplicates <- unique(ids[duplicated(ids)])
  if (length(duplicates)) {
    stop("duplicate environmental week for ", product, ": ", paste(duplicates, collapse = ", "))
  }
  missing <- setdiff(required_week_ids, ids)
  if (length(missing)) {
    stop("missing environmental weeks for ", product, ": ", paste(missing, collapse = ", "))
  }
  paths[match(required_week_ids, ids)]
}

latest_common_environment_week <- function(environment_root, products, analysis_start, history_weeks = 52L) {
  analysis_start <- iso_week_start(as.Date(analysis_start))
  history_weeks <- as.integer(history_weeks)
  week_sets <- lapply(products, function(product) {
    weekly_directory <- file.path(environment_root, product, "weekly")
    paths <- list.files(weekly_directory, full.names = TRUE, pattern = "\\.(tif|tiff)$", ignore.case = TRUE)
    if (!length(paths)) stop("no weekly rasters found for ", product, ": ", weekly_directory)
    parsed <- lapply(paths, parse_week_identifier)
    ids <- vapply(parsed, `[[`, character(1L), "week_id")
    if (anyNA(ids)) stop("unparseable environmental week filename for ", product)
    if (anyDuplicated(ids)) stop("duplicate environmental week for ", product)
    ids
  })
  common <- if (length(week_sets)) Reduce(intersect, week_sets) else character()
  if (!length(common)) stop("the environmental portfolio has no common complete ISO week")
  candidates <- sort(vapply(common, function(id) as.character(iso_week_monday(
    as.integer(sub("-W.*", "", id)), as.integer(sub(".*-W", "", id)))
  ), character(1L)))
  for (candidate in rev(candidates)) {
    required <- iso_week_id(seq(analysis_start - 7L * history_weeks, as.Date(candidate), by = "7 days"))
    if (all(required %in% common)) return(as.Date(candidate))
  }
  stop("no common environmental endpoint has the required contiguous history")
}
