import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with streamable_http_client(
        "https://api-change-impact-mcp-gya2wuoicq-uc.a.run.app/mcp"
    ) as (read_stream, write_stream, _):

        async with ClientSession(
            read_stream,
            write_stream
        ) as session:

            await session.initialize()

            tools = await session.list_tools()

            print("\nAvailable MCP Tools:")
            print("====================")

            for tool in tools.tools:
                print(f"- {tool.name}")


if __name__ == "__main__":
    asyncio.run(main())