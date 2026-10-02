# Read-only observation-data audit. This script never writes to the source CSV.

audit_observations <- function(
  path,
  analysis_start = as.Date("2024-01-01")
) {
  if (!requireNamespace("data.table", quietly = TRUE)) {
    stop("data.table is required for the observation audit")
  }
  if (!requireNamespace("digest", quietly = TRUE)) {
    stop("digest is required for SHA-256 provenance")
  }
  if (!file.exists(path)) {
    stop("observation file does not exist: ", path)
  }

  observations <- data.table::fread(path, showProgress = FALSE)
  required <- c("lon", "lat", "date")
  missing_columns <- setdiff(required, names(observations))
  if (length(missing_columns)) {
    stop("missing required columns: ", paste(missing_columns, collapse = ", "))
  }

  lon <- suppressWarnings(as.numeric(observations[["lon"]]))
  lat <- suppressWarnings(as.numeric(observations[["lat"]]))
  parsed_date <- parse_strict_date(observations[["date"]])
  valid_coordinate <- is.finite(lon) & is.finite(lat) &
    lon >= -180 & lon <= 180 & lat >= -90 & lat <= 90
  valid_date <- !is.na(parsed_date)
  target <- valid_date & parsed_date >= analysis_start
  complete_week <- latest_complete_iso_week(parsed_date, analysis_start)

  row_duplicate_count <- nrow(observations) -
    data.table::uniqueN(observations)
  coordinate_date_duplicate_count <- nrow(observations) -
    data.table::uniqueN(observations, by = required)

  weekly_counts <- data.table::data.table(
    date = parsed_date,
    iso_week = ifelse(valid_date, iso_week_id(parsed_date), NA_character_)
  )[target, .(records = .N), by = iso_week]
  weekly_counts <- weekly_counts[order(iso_week)]

  list(
    path = normalizePath(path, winslash = "/", mustWork = TRUE),
    sha256 = digest::digest(file = path, algo = "sha256"),
    file_size_bytes = unname(file.info(path)$size),
    row_count = nrow(observations),
    column_names = names(observations),
    column_types = vapply(observations, function(x) paste(class(x), collapse = "/"), character(1L)),
    missing_lon = sum(is.na(observations[["lon"]])),
    missing_lat = sum(is.na(observations[["lat"]])),
    missing_date = sum(is.na(observations[["date"]])),
    malformed_coordinates = sum(!valid_coordinate & !is.na(observations[["lon"]]) &
      !is.na(observations[["lat"]])),
    coordinate_range = list(
      lon_min = if (any(valid_coordinate)) min(lon[valid_coordinate]) else NA_real_,
      lon_max = if (any(valid_coordinate)) max(lon[valid_coordinate]) else NA_real_,
      lat_min = if (any(valid_coordinate)) min(lat[valid_coordinate]) else NA_real_,
      lat_max = if (any(valid_coordinate)) max(lat[valid_coordinate]) else NA_real_
    ),
    date_parsing_failures = sum(!valid_date & !is.na(observations[["date"]])),
    min_valid_date = if (any(valid_date)) as.character(min(parsed_date[valid_date])) else NA_character_,
    max_valid_date = if (any(valid_date)) as.character(max(parsed_date[valid_date])) else NA_character_,
    records_before_2024 = sum(valid_date & parsed_date < analysis_start),
    records_on_or_after_2024 = sum(target),
    exact_duplicate_rows = row_duplicate_count,
    duplicate_lon_lat_date = coordinate_date_duplicate_count,
    unique_valid_dates = data.table::uniqueN(parsed_date[valid_date]),
    unique_coordinate_pairs = data.table::uniqueN(
      data.table::data.table(lon = lon, lat = lat)[valid_coordinate]
    ),
    weekly_record_counts = weekly_counts,
    candidate_period = complete_week
  )
}
