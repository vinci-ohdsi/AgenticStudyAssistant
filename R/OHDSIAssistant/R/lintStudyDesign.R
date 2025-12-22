#' Lint study design (prototype)
#' @param studyProtocol path or URL to protocol.md
#' @param studyPackage path to local study folder ('.' ok)
#' @param lintTasks character vector of tasks
#' @param apply logical; not used in prototype (advisory only)
#' @param interactive logical; print plans and findings
#' @param streamThoughts logical; placeholder
#' @return list of results by task
lintStudyDesign <- function(
  studyProtocol,
  studyPackage = ".",
  lintTasks = c("concept-sets-review","cohort-critique-general-design"),
  apply = FALSE,
  interactive = TRUE,
  streamThoughts = TRUE
) {
  conceptSetRef <- file.path(studyPackage, "concept_set.json")
  cohortRef     <- file.path(studyPackage, "cohort_definition.json")

  results <- list()
  use_acp <- !is.null(acp_state$url)

  if ("concept-sets-review" %in% lintTasks) {
    res <- if (use_acp) {
      .acp_post("/tools/propose_concept_set_diff", list(
        conceptSetRef = conceptSetRef,
        studyIntent   = paste(readLines(studyProtocol, warn = FALSE), collapse=" ")
      ))
    } else {
      local_concept_sets_review(conceptSetRef, studyIntent = paste(readLines(studyProtocol, warn = FALSE), collapse=" "))
    }
    res$artifact <- conceptSetRef
    if (interactive) {
      cat("\n== Concept Sets Review ==\n")
      cat(sprintf("File: %s\n", conceptSetRef))
      cat(res$plan, "\n")
      print_findings(res$findings)
    }
    results$`concept-sets-review` <- res
  }

  if ("cohort-critique-general-design" %in% lintTasks) {
    res <- if (use_acp) {
      .acp_post("/tools/cohort_lint", list(cohortRef = cohortRef))
    } else {
      local_cohort_critique_general(cohortRef)
    }
    res$artifact <- cohortRef
    if (interactive) {
      cat("\n== Cohort Critique: General Design ==\n")
      cat(sprintf("File: %s\n", cohortRef))
      cat(res$plan, "\n")
      print_findings(res$findings)
    }
    results$`cohort-critique-general-design` <- res
  }

  outdir <- file.path(studyPackage, "inst", "assistant")
  if (!dir.exists(outdir)) dir.create(outdir, recursive = TRUE)
  ts <- format(Sys.time(), "%Y%m%dT%H%M%S")
  jsonlite::write_json(results, file.path(outdir, paste0("advice_", ts, ".json")), auto_unbox = TRUE, pretty = TRUE)

  invisible(results)
}
