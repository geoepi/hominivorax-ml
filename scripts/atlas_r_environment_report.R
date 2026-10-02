#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
position <- match("--output", args)
if (is.na(position) || position == length(args)) {
  stop("Usage: Rscript scripts/atlas_r_environment_report.R --output <json>")
}
output_path <- args[[position + 1L]]

package_versions <- function(packages) {
  setNames(lapply(packages, function(package) {
    if (!requireNamespace(package, quietly = TRUE)) {
      return(NULL)
    }
    as.character(utils::packageVersion(package))
  }), packages)
}

shell_report <- function(command) {
  tryCatch(
    paste(system(command, intern = TRUE, ignore.stderr = FALSE), collapse = "\n"),
    error = function(error) paste("ERROR:", conditionMessage(error))
  )
}

external <- list()
if (requireNamespace("sf", quietly = TRUE)) {
  external$sf_extSoftVersion <- sf::sf_extSoftVersion()
}
if (requireNamespace("terra", quietly = TRUE)) {
  external$terra_gdal_all <- tryCatch(
    capture.output(terra::gdal(lib = "all")),
    error = function(error) paste("ERROR:", conditionMessage(error))
  )
}

result <- list(
  timestamp_utc = format(Sys.time(), tz = "UTC", usetz = TRUE),
  hostname = Sys.info()[["nodename"]],
  r_version = R.version.string,
  session_info = capture.output(utils::sessionInfo()),
  external_library_report = external,
  shell_and_module_report = list(
    loaded_modules_environment = Sys.getenv("LOADEDMODULES", unset = NA_character_),
    mkl_root = Sys.getenv("MKLROOT", unset = NA_character_),
    module_list = shell_report("module list 2>&1"),
    gdal = shell_report("gdalinfo --version 2>&1"),
    geos = shell_report("geos-config --version 2>&1"),
    proj = shell_report("projinfo --version 2>&1"),
    udunits = shell_report("udunits2 -h 2>&1")
  ),
  package_versions = package_versions(c("terra", "sf", "data.table", "arrow", "ggplot2", "jsonlite", "digest"))
)

if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("jsonlite is required to write the environment report")
}
jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
message("Wrote R environment report: ", output_path)
