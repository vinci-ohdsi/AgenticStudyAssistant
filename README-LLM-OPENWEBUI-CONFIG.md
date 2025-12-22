### How to config Open-webui for this low-fi prototype

1) obtain Gemma3 12b in the models library

2) set up a workspace `AgentStudyAssistant`

3) Set the system prompt to be the contents of this file within this folder:

agentstudyassistant-system-prompt.md

NOTE: Edit the *HEURISTICS* section of the file to make improvements or add other tests and patches

4) In advanced params set (as a starting point, you can make changes for experimentation):
- stream chat responts: off
- temperature: 1.0
- max_tokens: 2048
- top_k: 64
- top_p: 0.95
- min_p: 0.01

