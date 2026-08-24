import os

from mcp.server.fastmcp import FastMCP

from src.core import analyze, get_report


PORT = int(
    os.getenv(
        "PORT",
        os.getenv("MCP_PORT", "8000")
    )
)


mcp = FastMCP(
    name="Enterprise API Change Impact Agent",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def analyze_api_change(
    provider_service: str,
    old_openapi: dict | str,
    new_openapi: dict | str,
    release_notes: str | None = None,
) -> dict:
    """
    Analyze changes between old and new OpenAPI specifications.

    Returns an analysis_id that should be used for subsequent MCP tools.
    """

    return analyze(
        provider_service=provider_service,
        old_openapi=old_openapi,
        new_openapi=new_openapi,
        release_notes=release_notes,
    )


@mcp.tool()
def get_breaking_changes(
    analysis_id: str,
) -> dict:
    """
    Return breaking and conditionally-breaking API changes.
    """

    report = get_report(analysis_id)

    changes = report.get("changes", [])

    breaking_changes = [
        change
        for change in changes
        if change.get("severity")
        in {
            "BREAKING",
            "CONDITIONALLY_BREAKING",
        }
    ]

    return {
        "analysis_id": analysis_id,
        "count": len(breaking_changes),
        "changes": breaking_changes,
    }


@mcp.tool()
def get_impacted_services(
    analysis_id: str,
) -> dict:
    """
    Return impacted backend services.
    """

    report = get_report(analysis_id)

    services = report.get(
        "impacted_services",
        []
    )

    return {
        "analysis_id": analysis_id,
        "count": len(services),
        "services": services,
    }


@mcp.tool()
def get_impacted_frontend_screens(
    analysis_id: str,
) -> dict:
    """
    Return frontend screens impacted by changed API operations.
    """

    report = get_report(analysis_id)

    screens = report.get(
        "impacted_frontend_screens",
        []
    )

    return {
        "analysis_id": analysis_id,
        "count": len(screens),
        "screens": screens,
    }


@mcp.tool()
def get_recommended_regression_tests(
    analysis_id: str,
) -> dict:
    """
    Return scoped regression tests recommended for this API change.
    """

    report = get_report(analysis_id)

    tests = report.get(
        "recommended_regression_tests",
        []
    )

    total_duration = sum(
        test.get(
            "estimated_duration_seconds",
            0,
        )
        for test in tests
    )

    return {
        "analysis_id": analysis_id,
        "count": len(tests),
        "estimated_duration_seconds": total_duration,
        "tests": tests,
    }


@mcp.tool()
def get_analysis_report(
    analysis_id: str,
) -> dict:
    """
    Return the full API change impact analysis report.
    """

    return get_report(analysis_id)


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http"
    )