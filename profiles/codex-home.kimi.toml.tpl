# ultimate-brainstorm Codex home for the Kimi family (Moonshot Platform). Written by install.py setup-kimi --codex.
# Rendered from profiles/codex-home.kimi.toml.tpl, region {{REGION}}. No secret is stored here:
# Codex reads the key from the KIMI_API_KEY environment variable (env_key below).
# Use: codex-kimi (launcher), or set CODEX_HOME to this folder before running codex.
model = "kimi-k3"
model_provider = "kimi"
model_context_window = 1048576

[model_providers.kimi]
name = "Kimi"
base_url = "{{BASE_URL}}"
env_key = "KIMI_API_KEY"
wire_api = "responses"
