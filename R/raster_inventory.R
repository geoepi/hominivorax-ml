# Metadata-only environmental and livestock raster inventory helpers.

expected_environmental_products <- function() {
  c(
    "era5_mintemp",
    "era5_soilmoist",
    "era5_lai_low",
    "agera5_relhum_min",
    "era5land_tmean",
    "era5land_soiltemp_l1_mean",
    "era5land_soiltemp_l2_mean",
    "era5land_soilwater_l1_mean",
    "era5land_soilwater_l2_mean",
    "era5land_surface_pressure_mean",
    "era5land_lai_high_mean",
    "era5land_lai_low_mean"
  )
}

expected_livestock_files <- function() {
  c(
    "goat_density20.tif",
    "cattle_density20.tif",
    "sheep_density20.tif",
    "horse_density.tif",
    "pig_density20.tiff"
  )
}

iso_week_monday <- function(year, week) {
  year <- as.integer(year)
  week <- as.integer(week)
  jan_four <- as.Date(sprintf("%04d-01-04", year))
  monday <- jan_four - (as.integer(format(jan_four, "%u")) - 1L) +
    7L * (week - 1L)
  if (as.character(iso_week_id(monday)) != sprintf("%04d-W%02d", year, week)) {
    return(as.Date(NA_character_))
  }
  monday
}

parse_week_identifier <- function(filename) {
  basename_value <- basename(filename)
  iso_match <- regexec(
    "([0-9]{4})[-_]?W([0-9]{1,2})",
    basename_value,
    ignore.case = TRUE
  )
  iso_parts <- regmatches(basename_value, iso_match)[[1L]]
  if (length(iso_parts) == 3L) {
    monday <- iso_week_monday(iso_parts[2L], iso_parts[3L])
    if (!is.na(monday)) {
      return(list(
        filename = basename_value,
        week_id = iso_week_id(monday),
        iso_year = as.integer(format(monday, "%G")),
        iso_week = as.integer(format(monday, "%V")),
        parse_method = "ISO year-week"
      ))
    }
  }

  date_match <- regexec(
    "([0-9]{4})[-_]?([0-9]{2})[-_]?([0-9]{2})",
    basename_value
  )
  date_parts <- regmatches(basename_value, date_match)[[1L]]
  if (length(date_parts) == 4L) {
    parsed <- suppressWarnings(as.Date(
      paste(date_parts[2L], date_parts[3L], date_parts[4L], sep = "-")
    ))
    if (!is.na(parsed)) {
      monday <- iso_week_start(parsed)
      return(list(
        filename = basename_value,
        week_id = iso_week_id(monday),
        iso_year = as.integer(format(monday, "%G")),
        iso_week = as.integer(format(monday, "%V")),
        parse_method = "calendar date"
      ))
    }
  }

  list(
    filename = basename_value,
    week_id = NA_character_,
    iso_year = NA_integer_,
    iso_week = NA_integer_,
    parse_method = NA_character_
  )
}

expected_week_sequence <- function(first_week, last_week) {
  if (is.na(first_week) || is.na(last_week)) {
    return(character())
  }
  iso_week_id(seq(as.Date(first_week), as.Date(last_week), by = "7 days"))
}

summarize_week_identifiers <- function(parsed_table) {
  parsed_ids <- parsed_table$week_id[!is.na(parsed_table$week_id)]
  id_counts <- table(parsed_ids)
  duplicate_ids <- names(id_counts[id_counts > 1L])
  first_week <- if (length(parsed_ids)) {
    iso_week_monday(
      parsed_table$iso_year[match(min(parsed_ids), parsed_table$week_id)],
      parsed_table$iso_week[match(min(parsed_ids), parsed_table$week_id)]
    )
  } else {
    as.Date(NA_character_)
  }
  last_week <- if (length(parsed_ids)) {
    iso_week_monday(
      parsed_table$iso_year[match(max(parsed_ids), parsed_table$week_id)],
      parsed_table$iso_week[match(max(parsed_ids), parsed_table$week_id)]
    )
  } else {
    as.Date(NA_character_)
  }
  list(
    parsed_ids = parsed_ids,
    first_week = first_week,
    last_week = last_week,
    missing_ids = setdiff(expected_week_sequence(first_week, last_week), parsed_ids),
    duplicate_ids = duplicate_ids
  )
}

safe_raster_header <- function(
  path,
  include_values = FALSE,
  include_minmax = FALSE
) {
  if (!requireNamespace("terra", quietly = TRUE)) {
    stop("terra is required for raster metadata inspection")
  }
  raster <- terra::rast(path, lyrs = 1)
  values <- NULL
  if (isTRUE(include_values)) {
    values <- tryCatch(
      terra::values(raster, mat = FALSE),
      error = function(error) NULL
    )
  }
  nonmissing <- if (is.null(values)) numeric() else values[!is.na(values)]
  metadata <- tryCatch(terra::metags(raster), error = function(error) NULL)
  description <- tryCatch(terra::describe(raster), error = function(error) NULL)
  valid_cell_mask_sha256 <- if (!is.null(values) &&
      requireNamespace("digest", quietly = TRUE)) {
    digest::digest(!is.na(values), algo = "sha256")
  } else {
    NA_character_
  }
  minmax <- if (isTRUE(include_minmax)) {
    tryCatch(terra::minmax(raster), error = function(error) NULL)
  } else {
    NULL
  }
  list(
    path = normalizePath(path, winslash = "/", mustWork = TRUE),
    filename = basename(path),
    file_size_bytes = unname(file.info(path)$size),
    crs = terra::crs(raster),
    nrow = terra::nrow(raster),
    ncol = terra::ncol(raster),
    resolution = as.numeric(terra::res(raster)),
    extent = as.vector(terra::ext(raster)),
    origin = as.numeric(terra::origin(raster)),
    nodata = tryCatch(terra::NAflag(raster), error = function(error) NA_real_),
    data_type = terra::datatype(raster),
    bands = terra::nlyr(raster),
    metadata = metadata,
    description = description,
    minmax = minmax,
    minimum = if (length(nonmissing)) min(nonmissing) else NA_real_,
    maximum = if (length(nonmissing)) max(nonmissing) else NA_real_,
    valid_cell_count = if (is.null(values)) NA_integer_ else sum(!is.na(values)),
    valid_cell_mask_sha256 = valid_cell_mask_sha256,
    values_inspected = isTRUE(include_values)
  )
}

raster_geometry_signature <- function(header) {
  paste(
    header$crs,
    paste(header$nrow, header$ncol, collapse = ","),
    paste(format(header$resolution, digits = 17), collapse = ","),
    paste(format(header$extent, digits = 17), collapse = ","),
    paste(format(header$origin, digits = 17), collapse = ","),
    paste(header$nodata, collapse = ","),
    sep = "|"
  )
}

inventory_environmental_product <- function(product, weekly_root) {
  weekly_directory <- file.path(weekly_root, product, "weekly")
  all_entries <- if (dir.exists(weekly_directory)) {
    list.files(weekly_directory, full.names = TRUE, recursive = FALSE)
  } else {
    character()
  }
  raster_files <- all_entries[
    !file.info(all_entries)$isdir &
      grepl("\\.(tif|tiff)$", all_entries, ignore.case = TRUE)
  ]
  parsed <- lapply(raster_files, parse_week_identifier)
  parsed_table <- if (length(parsed)) {
    do.call(rbind, lapply(parsed, as.data.frame, stringsAsFactors = FALSE))
  } else {
    data.frame(
      filename = character(),
      week_id = character(),
      iso_year = integer(),
      iso_week = integer(),
      parse_method = character(),
      stringsAsFactors = FALSE
    )
  }
  parsed_table$iso_year <- as.integer(parsed_table$iso_year)
  parsed_table$iso_week <- as.integer(parsed_table$iso_week)
  week_summary <- summarize_week_identifiers(parsed_table)
  unexpected <- c(
    basename(all_entries)[file.info(all_entries)$isdir],
    basename(setdiff(all_entries, raster_files)),
    parsed_table$filename[is.na(parsed_table$week_id)]
  )
  headers <- lapply(raster_files, safe_raster_header, include_values = FALSE)
  signatures <- if (length(headers)) {
    vapply(headers, raster_geometry_signature, character(1L))
  } else {
    character()
  }
  representative_values <- if (length(raster_files)) {
    safe_raster_header(raster_files[[1L]], include_values = TRUE)
  } else {
    NULL
  }

  list(
    product = product,
    weekly_directory = normalizePath(weekly_directory, winslash = "/", mustWork = FALSE),
    file_count = length(raster_files),
    files = parsed_table,
    earliest_week = if (is.na(week_summary$first_week)) NA_character_ else iso_week_id(week_summary$first_week),
    latest_week = if (is.na(week_summary$last_week)) NA_character_ else iso_week_id(week_summary$last_week),
    missing_week_ids = week_summary$missing_ids,
    duplicate_week_ids = week_summary$duplicate_ids,
    unexpected_filenames = unique(unexpected),
    headers = headers,
    geometry_signatures = unique(signatures),
    representative_value_summary = representative_values
  )
}

inventory_livestock_layer <- function(path) {
  if (!file.exists(path)) {
    return(list(
      path = normalizePath(path, winslash = "/", mustWork = FALSE),
      missing = TRUE
    ))
  }
  result <- safe_raster_header(
    path,
    include_values = FALSE,
    include_minmax = TRUE
  )
  result$units_assessment <- "Not inferred from filename; report only explicit raster metadata."
  result$quantity_semantics_assessment <-
    "Density/count semantics remain unresolved pending metadata review."
  result
}

compare_inventory_geometry <- function(environmental_inventory) {
  headers <- unlist(
    lapply(environmental_inventory, function(product) product$headers),
    recursive = FALSE
  )
  if (!length(headers)) {
    return(list(reference = NULL, comparisons = list(), common_geometry = FALSE))
  }
  reference <- headers[[1L]]
  reference_signature <- raster_geometry_signature(reference)
  comparisons <- lapply(headers, function(header) {
    list(
      product_file = header$path,
      exact_match_to_reference =
        identical(raster_geometry_signature(header), reference_signature),
      crs_equal = identical(header$crs, reference$crs),
      dimensions_equal = identical(
        c(header$nrow, header$ncol),
        c(reference$nrow, reference$ncol)
      ),
      resolution_equal = identical(header$resolution, reference$resolution),
      extent_equal = identical(header$extent, reference$extent),
      origin_equal = identical(header$origin, reference$origin),
      nodata_equal = identical(header$nodata, reference$nodata)
    )
  })
  list(
    reference = reference,
    comparisons = comparisons,
    common_geometry = all(vapply(
      comparisons,
      function(comparison) comparison$exact_match_to_reference,
      logical(1L)
    ))
  )
}
