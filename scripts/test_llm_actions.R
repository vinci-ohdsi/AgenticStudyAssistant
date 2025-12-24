# Demo: apply LLM-proposed actions vs deterministic patch helper

## NOTE: running from a directory above the AgenticStudyAssistant so that we can reuse the .renv
devtools::load_all("AgenticStudyAssistant/R/OHDSIAssistant")
OHDSIAssistant::acp_connect("http://127.0.0.1:7777")

concept_set_ref <- "demo/concept_set.json"  # This path is relative to the ACP server's base folder

# --- LLM actions path ---
# Ask tool for findings and actions
resp <- OHDSIAssistant:::`.acp_post`("/tools/propose_concept_set_diff", list(
  conceptSetRef = concept_set_ref,
  studyIntent   = paste(readLines("./AgenticStudyAssistant/demo/protocol.md", warn = FALSE), collapse = " ") # this path is relative the start of the R session
))

actions <- resp$actions
cat("LLM actions:\n"); print(actions)

# Preview execution of actions
prev <- OHDSIAssistant::applyLLMActionsConceptSet(concept_set_ref, actions, preview = TRUE)
cat("LLM preview counts:\n"); print(prev$counts)
cat("Preview rows (first few):\n"); print(head(prev$preview_changes))

# Apply (writes new file if overwrite = FALSE)
applied <- OHDSIAssistant::applyLLMActionsConceptSet(concept_set_ref, actions, preview = FALSE, overwrite = FALSE, backup = TRUE)
cat("LLM applied written_to:\n"); print(applied$written_to)

# --- Deterministic helper path ---
patch <- OHDSIAssistant::proposeIncludeDescendantsPatch(concept_set_ref)
OHDSIAssistant::previewConceptSetPatch(concept_set_ref, patch)
OHDSIAssistant::applyConceptSetPatch(concept_set_ref, patch, backup = TRUE, overwrite = FALSE)
