# Minimal NumPy .npy writers used for the reproducible Atlas export.

npy_header <- function(descr, shape) {
  shape_text <- if (length(shape) == 1L) {
    sprintf("(%d,)", as.integer(shape))
  } else {
    paste0("(", paste(as.integer(shape), collapse = ", "), ")")
  }
  dictionary <- sprintf(
    "{'descr': '%s', 'fortran_order': False, 'shape': %s, }",
    descr,
    shape_text
  )
  prefix_length <- 6L + 2L + 2L
  padding <- (16L - ((prefix_length + nchar(dictionary) + 1L) %% 16L)) %% 16L
  header <- paste0(dictionary, strrep(" ", padding), "\n")
  if (nchar(header, type = "bytes") > 65535L) {
    stop("NumPy v1.0 header is too long")
  }
  header
}

npy_open <- function(path, descr, shape) {
  directory <- dirname(path)
  if (!dir.exists(directory)) dir.create(directory, recursive = TRUE, showWarnings = FALSE)
  connection <- file(path, open = "wb")
  writeBin(charToRaw("\x93NUMPY"), connection)
  writeBin(as.raw(c(1L, 0L)), connection)
  header <- charToRaw(npy_header(descr, shape))
  writeBin(as.raw(c(bitwAnd(length(header), 255L), bitwAnd(length(header) %/% 256L, 255L))), connection)
  writeBin(header, connection)
  connection
}

npy_write_weekwise <- function(path, values_for_week, shape, descr = "<f4") {
  connection <- npy_open(path, descr, shape)
  on.exit(close(connection), add = TRUE)
  for (week_index in seq_len(shape[[1L]])) {
    values <- values_for_week(week_index)
    if (descr == "<f4") {
      writeBin(as.numeric(values), connection, size = 4L, endian = "little")
    } else if (descr == "<i4") {
      writeBin(as.integer(values), connection, size = 4L, endian = "little")
    } else if (descr == "|u1") {
      writeBin(as.raw(values), connection, size = 1L)
    } else {
      stop("unsupported NumPy dtype: ", descr)
    }
  }
}

npy_write_matrix <- function(path, matrix_values, descr = "<f4") {
  if (!is.matrix(matrix_values)) matrix_values <- as.matrix(matrix_values)
  connection <- npy_open(path, descr, dim(matrix_values))
  on.exit(close(connection), add = TRUE)
  values <- as.numeric(t(matrix_values))
  if (descr == "<f4") {
    writeBin(values, connection, size = 4L, endian = "little")
  } else if (descr == "<i4") {
    writeBin(as.integer(values), connection, size = 4L, endian = "little")
  } else if (descr == "|u1") {
    writeBin(as.raw(values), connection, size = 1L)
  } else {
    stop("unsupported NumPy dtype: ", descr)
  }
}
