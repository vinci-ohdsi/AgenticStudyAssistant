# OHDSI Assistant Prototype

This repo contains:
- A tiny **ACP-like bridge** (`acp/server.py`) exposing:
  - `/tools/propose_concept_set_diff` (concept-sets-review)
  - `/tools/cohort_lint` (cohort-critique-general-design)
- An **R package** `OHDSIAssistant` with `lintStudyDesign()` that calls the bridge (or uses a local fallback).
- A **demo** study in `demo/`.

## Quick start

1) Start bridge:

```bash
./scripts/start_acp.sh
```

Optional) Use another ACP-style CLI backend:

```bash
export ACP_MODEL_CMD="my-cli --reads-stdin"  # prompt sent via stdin; must return JSON
./scripts/start_acp.sh
```

Optional) Use OpenWebUI HTTP backend (recommended):

```bash
export OPENWEBUI_API_KEY="..."  # required
export OPENWEBUI_API_URL="http://localhost:3000/api/chat/completions"  # default
export OPENWEBUI_MODEL="agentstudyassistant"  # default
./scripts/start_acp.sh
```

In R:

```r
devtools::load_all("R/OHDSIAssistant")
OHDSIAssistant::acp_connect("http://127.0.0.1:7777")
OHDSIAssistant::lintStudyDesign(
  studyProtocol = "demo/protocol.md",
  studyPackage  = "demo",
  lintTasks     = c("concept-sets-review","cohort-critique-general-design"),
  apply         = FALSE,
  interactive   = TRUE
)
```

You'll see plans, findings, and suggested patches. Advice logs are saved under demo/inst/assistant/.

Executable action (concept-set includeDescendants helper):

```r
patch <- OHDSIAssistant::proposeIncludeDescendantsPatch("demo/concept_set.json")
OHDSIAssistant::previewConceptSetPatch("demo/concept_set.json", patch)
OHDSIAssistant::applyConceptSetPatch("demo/concept_set.json", patch, backup = TRUE)
```

Next steps

Replace "note" patches with executable JSON Patch aligned to ATLAS schema.

Add WebAPI resolvers for webapi://cohort/<id> and webapi://conceptSet/<id>.

Pull in Achilles/DQD summaries to drive severity and evidence links.
