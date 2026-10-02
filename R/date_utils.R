# Date and ISO-week helpers used by the Task 1 audit.

parse_strict_date <- function(x) {
  x <- as.character(x)
  out <- rep(as.Date(NA_character_), length(x))
  candidate <- !is.na(x) & grepl("^[0-9]{4}-[0-9]{2}-[0-9]{2}$", x)
  if (!any(candidate)) {
    return(out)
  }

  parsed <- suppressWarnings(as.Date(x[candidate], format = "%Y-%m-%d"))
  valid <- !is.na(parsed) & format(parsed, "%Y-%m-%d") == x[candidate]
  positions <- which(candidate)[valid]
  out[positions] <- parsed[valid]
  out
}

iso_week_start <- function(dates) {
  dates <- as.Date(dates)
  weekday <- as.integer(format(dates, "%u"))
  dates - (weekday - 1L)
}

iso_week_end <- function(dates) {
  iso_week_start(dates) + 6L
}

iso_week_id <- function(dates) {
  dates <- as.Date(dates)
  paste0(format(dates, "%G"), "-W", format(dates, "%V"))
}

latest_complete_iso_week <- function(
  dates,
  analysis_start = as.Date("2024-01-01")
) {
  dates <- as.Date(dates)
  valid <- dates[!is.na(dates)]
  if (!length(valid)) {
    return(list(
      available = FALSE,
      max_observation_date = as.Date(NA_character_),
      max_observation_iso_week = NA_character_,
      latest_complete_iso_week = NA_character_,
      candidate_analysis_end = as.Date(NA_character_),
      target_week_count = 0L
    ))
  }

  max_date <- max(valid)
  weekday <- as.integer(format(max_date, "%u"))
  candidate_end <- if (weekday == 7L) max_date else max_date - weekday
  candidate_start <- candidate_end - 6L
  available <- candidate_end >= analysis_start
  target_week_count <- if (available) {
    as.integer(as.integer(candidate_end - analysis_start + 1L) %/% 7L)
  } else {
    0L
  }

  list(
    available = available,
    max_observation_date = max_date,
    max_observation_iso_week = iso_week_id(max_date),
    latest_complete_iso_week = if (available) iso_week_id(candidate_start) else NA_character_,
    candidate_analysis_end = if (available) candidate_end else as.Date(NA_character_),
    target_week_count = target_week_count
  )
}

filter_target_period <- function(
  dates,
  analysis_start = as.Date("2024-01-01"),
  analysis_end = NULL
) {
  dates <- as.Date(dates)
  keep <- !is.na(dates) & dates >= analysis_start
  if (!is.null(analysis_end)) {
    keep <- keep & dates <= as.Date(analysis_end)
  }
  keep
}
