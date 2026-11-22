#!/usr/bin/env Rscript
# Independent base-R cross-check of raw-character and exact-decimal keys.
# All input columns are read as character. Only aggregate rows are written.

default_updated_sha <- "8fd21f9db11db3df20596fe7ad0b4cbbc8b895fbaad6f702c847ed5a05dd19fc"
expected_historical <- "a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e"
required <- c("date", "host", "lon", "lat")
subsets <- c(
  "Entire observation dataset",
  "Original W16 training horizon",
  "After original W16 training horizon",
  "Before original W16 training horizon"
)

args <- commandArgs(trailingOnly = TRUE)
if (!(length(args) %in% c(3L, 4L))) {
  stop("Usage: Rscript observation_duplicate_precision_audit.R UPDATED.csv HISTORICAL.csv OUTPUT_DIR [UPDATED_SHA256]")
}
updated_path <- args[[1L]]
historical_path <- args[[2L]]
output_dir <- args[[3L]]
expected_updated <- if (length(args) == 4L) args[[4L]] else default_updated_sha

sha256_file <- function(path) {
  result <- system2("sha256sum", shQuote(path), stdout = TRUE, stderr = TRUE)
  if (length(result) != 1L || grepl("^sha256sum:", result[[1L]])) {
    stop("Could not calculate source SHA-256.")
  }
  sub("[[:space:]].*$", "", result[[1L]])
}

read_source <- function(path, expected_sha) {
  actual_sha <- sha256_file(path)
  if (!identical(actual_sha, expected_sha)) {
    stop("Source checksum mismatch; comparison stopped.")
  }
  frame <- read.csv(
    path,
    colClasses = "character",
    na.strings = character(),
    strip.white = FALSE,
    check.names = FALSE,
    stringsAsFactors = FALSE,
    comment.char = "",
    fileEncoding = "UTF-8"
  )
  if (!all(required %in% names(frame))) stop("Required source columns are absent.")
  if (anyDuplicated(names(frame))) stop("Source header contains repeated names.")
  list(frame = frame, sha256 = actual_sha)
}

canonical_decimal_scalar <- function(value) {
  value <- trimws(value)
  match <- regmatches(
    value,
    regexec("^([+-]?)(?:(\\d+)(?:\\.(\\d*))?|\\.(\\d+))(?:[eE]([+-]?\\d+))?$",
            value, perl = TRUE)
  )[[1L]]
  if (length(match) == 0L) stop("Invalid decimal coordinate in source.")
  sign <- match[[2L]]
  integer <- match[[3L]]
  fraction <- if (nzchar(match[[3L]])) match[[4L]] else match[[5L]]
  exponent_text <- match[[6L]]
  if (is.na(integer) || !nzchar(integer)) integer <- "0"
  if (is.na(fraction)) fraction <- ""
  if (is.na(exponent_text) || !nzchar(exponent_text)) exponent_text <- "0"
  digits <- sub("^0+", "", paste0(integer, fraction))
  if (!nzchar(digits)) return("0e0")
  exponent <- as.integer(exponent_text) - nchar(fraction, type = "chars")
  while (nchar(digits, type = "chars") > 1L && endsWith(digits, "0")) {
    digits <- substr(digits, 1L, nchar(digits, type = "chars") - 1L)
    exponent <- exponent + 1L
  }
  paste0(if (sign == "-") "-" else "", digits, "e", exponent)
}

canonical_decimal <- function(values) {
  values <- trimws(as.character(values))
  scientific <- grepl("[eE]", values)
  output <- character(length(values))
  if (any(scientific)) {
    output[scientific] <- vapply(values[scientific], canonical_decimal_scalar, character(1))
  }
  plain <- !scientific
  if (any(plain)) {
    current <- values[plain]
    valid <- grepl("^[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)$", current, perl = TRUE)
    if (any(!valid)) stop("Invalid decimal coordinate in source.")
    sign <- ifelse(startsWith(current, "-"), "-", "")
    unsigned <- sub("^[+-]", "", current)
    has_point <- grepl("\\.", unsigned)
    integer <- ifelse(has_point, sub("\\..*$", "", unsigned), unsigned)
    fraction <- ifelse(has_point, sub("^[^.]*\\.", "", unsigned), "")
    integer[!nzchar(integer)] <- "0"
    digits <- sub("^0+", "", paste0(integer, fraction))
    zero <- !grepl("[1-9]", digits)
    digits[zero] <- "0"
    exponent <- -nchar(fraction, type = "chars")
    trailing <- ifelse(zero, 0L, nchar(digits, type = "chars") - nchar(sub("0+$", "", digits), type = "chars"))
    digits[!zero] <- sub("0+$", "", digits[!zero])
    exponent <- exponent + trailing
    sign[zero] <- ""
    exponent[zero] <- 0L
    output[plain] <- paste0(sign, digits, "e", exponent)
  }
  output
}

calendar_date <- function(value) {
  value <- trimws(value)
  if (nchar(value, type = "chars") >= 10L &&
      grepl("^\\d{4}-\\d{2}-\\d{2}([ T]|$)", value)) {
    token <- substr(value, 1L, 10L)
    parsed <- suppressWarnings(as.Date(token, format = "%Y-%m-%d"))
    if (!is.na(parsed)) return(format(parsed, "%Y-%m-%d"))
  }
  paste0("UNPARSED:", value)
}

subset_label <- function(value) {
  day <- calendar_date(value)
  if (startsWith(day, "UNPARSED:")) return("Unclassified date")
  parsed <- as.Date(day)
  week_id <- sprintf("%04d-W%02d", as.integer(format(parsed, "%G")),
                     as.integer(format(parsed, "%V")))
  if (week_id >= "2025-W01" && week_id <= "2026-W16") {
    "Original W16 training horizon"
  } else if (week_id > "2026-W16") {
    "After original W16 training horizon"
  } else {
    "Before original W16 training horizon"
  }
}

encode_key <- function(frame) {
  if (nrow(frame) == 0L) return(character())
  pieces <- lapply(frame, function(value) {
    value <- as.character(value)
    value[is.na(value)] <- "<NA>"
    paste0(nchar(value, type = "bytes"), ":", value)
  })
  do.call(paste0, pieces)
}

key_metrics <- function(keys) {
  if (length(keys) == 0L) {
    return(c(total = 0L, unique = 0L, groups = 0L, participating = 0L,
             redundant = 0L, maximum = 1L))
  }
  counts <- tabulate(match(keys, unique(keys)))
  repeated <- counts[counts > 1L]
  c(total = length(keys), unique = length(counts), groups = length(repeated),
    participating = sum(repeated), redundant = sum(repeated - 1L),
    maximum = if (length(repeated)) max(repeated) else 1L)
}

make_row <- function(dataset, subset, method, columns, keys) {
  metrics <- key_metrics(keys)
  result <- data.frame(
    dataset, subset, method, columns, unname(metrics[["total"]]),
    unname(metrics[["unique"]]), unname(metrics[["groups"]]),
    unname(metrics[["participating"]]), unname(metrics[["redundant"]]),
    unname(metrics[["maximum"]]), check.names = FALSE
  )
  names(result) <- c(
    "Dataset", "Temporal subset", "Comparison method", "Key columns", "Total rows",
    "Unique keys", "Duplicate groups", "Rows in duplicate groups", "Redundant rows",
    "Maximum multiplicity"
  )
  result
}

crosscheck_dataset <- function(dataset, source) {
  frame <- source$frame
  dates <- vapply(frame$date, calendar_date, character(1))
  labels <- vapply(frame$date, subset_label, character(1))
  exact <- data.frame(
    date = dates,
    lon = canonical_decimal(frame$lon),
    lat = canonical_decimal(frame$lat),
    stringsAsFactors = FALSE
  )
  all_keys <- list(
    "Complete source record: raw character fields" = encode_key(frame),
    "Raw character (date,lon,lat)" = encode_key(frame[, c("date", "lon", "lat"), drop = FALSE]),
    "Exact decimal; calendar-date key" = encode_key(exact)
  )
  columns <- c(
    "date,host,lon,lat",
    "date,lon,lat",
    "calendar date,Decimal(lon),Decimal(lat)"
  )
  output <- list()
  for (subset in subsets) {
    selected <- if (subset == "Entire observation dataset") {
      seq_len(nrow(frame))
    } else {
      which(labels == subset)
    }
    methods <- names(all_keys)
    for (index in seq_along(methods)) {
      method <- methods[[index]]
      output[[length(output) + 1L]] <- make_row(
        dataset, subset, method, columns[[index]], all_keys[[method]][selected]
      )
    }
  }
  do.call(rbind, output)
}

updated <- read_source(updated_path, expected_updated)
historical <- read_source(historical_path, expected_historical)
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
crosscheck <- rbind(
  crosscheck_dataset("Updated 2026-11-13", updated),
  crosscheck_dataset("Frozen W16 source 2027-07-31", historical)
)
write.csv(
  crosscheck,
  file.path(output_dir, "observation_duplicate_precision_r_crosscheck.csv"),
  row.names = FALSE,
  na = ""
)
cat(
  "R_CROSSCHECK_COMPLETE\n",
  "updated_rows=", nrow(updated$frame), "\n",
  "historical_rows=", nrow(historical$frame), "\n",
  "record_level_output_written=false\n",
  sep = ""
)
