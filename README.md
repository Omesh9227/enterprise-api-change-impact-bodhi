# Enterprise API Change Impact Agent for Bodhi

## Run
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
python scripts/local_demo.py
python mcp_server.py
```

MCP endpoint: `http://127.0.0.1:8000/mcp`

The server accepts OpenAPI as either dictionaries/JSON objects or YAML/JSON strings. This avoids the common Bodhi integration error where YAML text is supplied to a dict-only tool.

## MCP tools
- analyze_api_change
- get_breaking_changes
- get_impacted_services
- get_impacted_frontend_screens
- get_recommended_regression_tests
- get_analysis_report

See `bodhi/SETUP.md` for the exact Agent Studio configuration and workflow.
