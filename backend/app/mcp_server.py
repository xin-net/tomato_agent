from app.tools.date_tool import DateTool
from app.tools.weather_tool import WeatherTool

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - optional runtime dependency guard
    FastMCP = None


if FastMCP is not None:
    mcp = FastMCP("tomato-agent-tools")

    @mcp.tool()
    def current_date(timezone_name: str = "Asia/Shanghai") -> dict:
        """Return the current date/time observation for agent planning."""
        return DateTool().observe(timezone_name).model_dump()

    @mcp.tool()
    def observe_weather(
        location: str,
        user_description: str = "",
        latitude: float | None = None,
        longitude: float | None = None,
        location_source: str | None = None,
        location_error: str | None = None,
        explicit_weather: str | None = None,
    ) -> dict:
        """Extract weather and environment risk signals from the current case context."""
        return WeatherTool().observe(
            location,
            user_description,
            latitude=latitude,
            longitude=longitude,
            location_source=location_source,
            location_error=location_error,
            explicit_weather=explicit_weather,
        ).model_dump()
else:
    mcp = None


def main() -> None:
    if mcp is None:
        raise RuntimeError("Install the 'mcp' package to run the Tomato Agent MCP server.")
    mcp.run()


if __name__ == "__main__":
    main()
