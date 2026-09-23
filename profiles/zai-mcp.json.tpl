{
  "mcpServers": {
    "web-search-prime": {
      "type": "http",
      "url": "{{ZAI_MCP_BASE}}/web_search_prime/mcp",
      "headers": {
        "Authorization": "Bearer {{ZAI_API_KEY}}"
      }
    },
    "web-reader": {
      "type": "http",
      "url": "{{ZAI_MCP_BASE}}/web_reader/mcp",
      "headers": {
        "Authorization": "Bearer {{ZAI_API_KEY}}"
      }
    }
  }
}
