from pydantic import Field


def register_testing_tools(mcp, log_event):
    @mcp.tool(
        name="echo",
        description="Return the same text you send. Useful for MCP connectivity testing.",
    )
    def echo(
        message: str = Field(description="Message to echo back"),
    ) -> str:
        log_event("tool.echo.start", message=message)
        log_event("tool.echo.success", message=message)
        return message

    @mcp.tool(
        name="ping",
        description="Simple health-check tool that returns pong.",
    )
    def ping() -> str:
        log_event("tool.ping.start")
        log_event("tool.ping.success", response="pong")
        return "pong"

    @mcp.tool(
        name="input_output",
        description="Return both input and output values to validate tool payload handling.",
    )
    def input_output(
        user_input: str = Field(description="Input text to process"),
        mode: str = Field(
            default="none",
            description="Output mode: none, upper, or lower",
        ),
    ) -> dict[str, str]:
        log_event("tool.input_output.start", user_input=user_input, mode=mode)
        normalized_mode = mode.lower().strip()
        if normalized_mode == "upper":
            output = user_input.upper()
        elif normalized_mode == "lower":
            output = user_input.lower()
        else:
            normalized_mode = "none"
            output = user_input

        result = {
            "input": user_input,
            "mode": normalized_mode,
            "output": output,
        }
        log_event("tool.input_output.success", result=result)
        return result
