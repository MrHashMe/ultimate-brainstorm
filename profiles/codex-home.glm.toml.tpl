# ultimate-brainstorm Codex home for the GLM family (Z.ai). Written by install.py setup-glm --codex.
# Rendered from profiles/codex-home.glm.toml.tpl, region {{REGION}}. No secret is stored here:
# Codex reads the key from the ZAI_API_KEY environment variable (env_key below).
# Use: codex-glm (launcher), or set CODEX_HOME to this folder before running codex.
model = "glm-5.3"
model_provider = "zai"
model_reasoning_effort = "high"

[model_providers.zai]
name = "Z.ai"
base_url = "{{BASE_URL}}"
env_key = "ZAI_API_KEY"
wire_api = "responses"
