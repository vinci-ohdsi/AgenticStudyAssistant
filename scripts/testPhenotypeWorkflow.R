# Demo phenotype workflow (stubbed if LLM not connected)
# Run from repo root or within AgenticStudyAssistant

devtools::load_all("AgenticStudyAssistant/R/OHDSIAssistant")

# Connect if ACP is running; otherwise local stubs will be used
try(OHDSIAssistant::acp_connect("http://127.0.0.1:7777"), silent = TRUE)

protocol <- "AgenticStudyAssistant/demo/protocol.md"
catalog  <- "AgenticStudyAssistant/demo/Cohorts.csv"
study_dir <- "AgenticStudyAssistant/demo"

rec <- OHDSIAssistant::suggestPhenotypes(protocol, catalog, maxResults = 3, interactive = TRUE)

ids <- OHDSIAssistant::selectPhenotypeRecommendations(rec$phenotype_recommendations, select = NULL, interactive = interactive())
if (length(ids)) {
  paths <- OHDSIAssistant::pullPhenotypeDefinitions(ids, outputDir = study_dir, overwrite = FALSE)
  OHDSIAssistant::reviewPhenotypes(protocol, paths, interactive = TRUE)
} else {
  cat("No phenotype recommendations returned (likely stub mode).\n")
}
