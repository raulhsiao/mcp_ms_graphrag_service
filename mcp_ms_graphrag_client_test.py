"""
測試 MCP Server 連線與工具呼叫。

使用方式:
    # 先啟動 server.py，然後在另一個終端機執行:
    pip install mcp
    python test_client.py
"""

import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SERVER_URL = "http://localhost:8000/mcp"


async def main():
    print(f"連線到 MCP Server: {SERVER_URL}")
    print("-" * 60)

    async with streamablehttp_client(SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            # 初始化
            await session.initialize()
            print("✓ 連線成功，session 已初始化\n")

            # 列出可用工具
            tools_result = await session.list_tools()
            print("可用工具:")
            for tool in tools_result.tools:
                print(f"  - {tool.name}: {tool.description[:60]}...")
            print()

            # 測試 1: 檢查索引狀態
            print("=" * 60)
            print("測試 1: graphrag_index_status")
            print("-" * 60)
            result = await session.call_tool("graphrag_index_status", {})
            for content in result.content:
                if hasattr(content, "text"):
                    data = json.loads(content.text)
                    print(json.dumps(data, indent=2, ensure_ascii=False))
            print()

            # 測試 2: 列出 entities
            print("=" * 60)
            print("測試 2: graphrag_list_entities (top_n=5)")
            print("-" * 60)
            result = await session.call_tool(
                "graphrag_list_entities", {"top_n": 5}
            )
            for content in result.content:
                if hasattr(content, "text"):
                    data = json.loads(content.text)
                    print(json.dumps(data, indent=2, ensure_ascii=False))
            print()

            # 測試 3: 執行查詢
            print("=" * 60)
            print("測試 3: graphrag_query (local search)")
            print("-" * 60)
            result = await session.call_tool(
                "graphrag_query",
                {
                    "query": "What are the main entities in this dataset?",
                    "method": "local",
                },
            )
            for content in result.content:
                if hasattr(content, "text"):
                    data = json.loads(content.text)
                    if data.get("success"):
                        print("查詢成功:")
                        print(data["answer"][:500])
                    else:
                        print(f"查詢失敗: {data.get('error')}")
            print()

            print("=" * 60)
            print("所有測試完成")


if __name__ == "__main__":
    asyncio.run(main())
