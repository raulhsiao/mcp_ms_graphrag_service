"""
GraphRAG MCP Server — Streamable HTTP Transport

合規的 MCP Server，透過 Streamable HTTP 提供 GraphRAG 查詢能力。
所有工具回傳都走 MCP 協定，無 side-channel。

使用方式:
    GRAPHRAG_DB_ROOT=/path/to/database python server.py
    e.g GRAPHRAG_DB_ROOT=/workspace/DbAB157x python mcp_ms_graphrag_server.py

Claude Code 連接:
    claude mcp add --transport http graphrag http://localhost:8000/mcp
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
GRAPHRAG_DB_ROOT = os.environ.get("GRAPHRAG_DB_ROOT", "/workspace/grapgrag_db_general")
HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8000"))
QUERY_TIMEOUT = int(os.environ.get("GRAPHRAG_QUERY_TIMEOUT", "120"))

# ---------------------------------------------------------------------------
# MCP Server 初始化
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="graphrag",
    # host/port 必須在建構時設定，run() 不接受這些參數
    host=HOST,
    port=PORT,
    # stateless_http=True 讓每個請求獨立處理，方便水平擴展
    # json_response=True 讓回傳格式更穩定
    stateless_http=True,
    json_response=True,
)


# ---------------------------------------------------------------------------
# 輔助函式
# ---------------------------------------------------------------------------
def _resolve_root() -> Path:
    """解析並驗證 GraphRAG 專案根目錄"""
    root = Path(GRAPHRAG_DB_ROOT).resolve()
    if not root.exists():
        raise FileNotFoundError(
            f"GraphRAG 專案目錄不存在: {root}\n"
            f"請設定環境變數 GRAPHRAG_DB_ROOT 指向已 index 的專案目錄"
        )
    return root


async def _run_graphrag_cli(
    args: list[str],
    timeout: int = QUERY_TIMEOUT,
) -> dict:
    """
    透過 subprocess 執行 graphrag CLI 指令。
    回傳 {"success": bool, "output": str, "error": str}
    """
    cmd = [sys.executable, "-m", "graphrag"] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_resolve_root()),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode == 0:
            return {"success": True, "output": stdout_text, "error": ""}
        else:
            return {
                "success": False,
                "output": stdout_text,
                "error": stderr_text or f"exit code {proc.returncode}",
            }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "output": "",
            "error": f"查詢逾時（超過 {timeout} 秒）",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "output": "",
            "error": "找不到 graphrag 指令，請確認已安裝: pip install graphrag",
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": f"執行錯誤: {type(e).__name__}: {e}",
        }


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def graphrag_query(
    query: str,
    method: str = "local",
    community_level: int = 2,
) -> str:
    """
    對 GraphRAG 知識圖譜執行查詢。

    Args:
        query: 查詢問題，例如 "這個專案的核心架構是什麼？"
        method: 搜尋方式，可選 local（特定實體）、global（全局主題）、drift（混合）
        community_level: 社群階層等級，數字越小涵蓋越廣，越大越精細（預設 2）

    Returns:
        GraphRAG 的查詢結果文字
    """
    # 驗證 method 參數
    valid_methods = ("local", "global", "drift")
    if method not in valid_methods:
        return json.dumps(
            {
                "success": False,
                "error": f"method 必須是 {valid_methods} 其中之一，收到: {method}",
            },
            ensure_ascii=False,
        )

    # 組合 CLI 指令
    args = [
        "query",
        query,
        "--method", method,
        "--community-level", str(community_level),
    ]

    result = await _run_graphrag_cli(args)

    if result["success"]:
        return json.dumps(
            {
                "success": True,
                "method": method,
                "community_level": community_level,
                "query": query,
                "answer": result["output"],
            },
            ensure_ascii=False,
        )
    else:
        return json.dumps(
            {
                "success": False,
                "method": method,
                "query": query,
                "error": result["error"],
                "detail": result["output"],
            },
            ensure_ascii=False,
        )


@mcp.tool()
async def graphrag_index_status() -> str:
    """
    檢查 GraphRAG 索引狀態。回傳專案目錄結構、output 目錄內的 artifact 檔案清單與大小。
    用於確認索引是否已完成、資料是否可用。
    """
    try:
        root = _resolve_root()
    except FileNotFoundError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    status = {
        "success": True,
        "root": str(root),
        "settings_exists": (root / "settings.yaml").exists(),
        "env_exists": (root / ".env").exists(),
        "input_dir": None,
        "output_dir": None,
    }

    # 檢查 input 目錄
    input_dir = root / "input"
    if input_dir.exists():
        input_files = list(input_dir.rglob("*"))
        input_files = [f for f in input_files if f.is_file()]
        status["input_dir"] = {
            "file_count": len(input_files),
            "total_size_mb": round(
                sum(f.stat().st_size for f in input_files) / (1024 * 1024), 2
            ),
        }

    # 檢查 output 目錄
    output_dir = root / "output"
    if output_dir.exists():
        artifacts = {}
        for f in sorted(output_dir.rglob("*")):
            if f.is_file():
                rel = str(f.relative_to(output_dir))
                artifacts[rel] = {
                    "size_kb": round(f.stat().st_size / 1024, 1),
                }
        status["output_dir"] = {
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
        }
    else:
        status["output_dir"] = {"error": "output 目錄不存在，可能尚未執行 graphrag index"}

    return json.dumps(status, ensure_ascii=False)


@mcp.tool()
async def graphrag_list_entities(top_n: int = 20) -> str:
    """
    列出知識圖譜中的 entities（實體）名稱。

    Args:
        top_n: 回傳前幾筆 entity（預設 20，最大 200）

    Returns:
        Entity 名稱清單與基本資訊
    """
    top_n = min(max(1, top_n), 200)

    try:
        root = _resolve_root()
    except FileNotFoundError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    # 嘗試找 entities parquet 檔
    output_dir = root / "output"
    entity_files = list(output_dir.rglob("*entities*.parquet")) if output_dir.exists() else []

    if not entity_files:
        # 嘗試找 create_final_entities parquet
        entity_files = list(output_dir.rglob("*final*entities*.parquet")) if output_dir.exists() else []

    if not entity_files:
        return json.dumps(
            {
                "success": False,
                "error": "找不到 entities parquet 檔案，請確認已完成 graphrag index",
            },
            ensure_ascii=False,
        )

    # 用 pandas 讀取（graphrag 依賴 pandas，應該已安裝）
    try:
        import pandas as pd

        df = pd.read_parquet(entity_files[0])

        # 常見欄位名稱
        name_col = None
        for candidate in ("name", "title", "entity_name", "entity"):
            if candidate in df.columns:
                name_col = candidate
                break

        if name_col is None:
            return json.dumps(
                {
                    "success": True,
                    "warning": "無法辨識 name 欄位",
                    "columns": list(df.columns),
                    "row_count": len(df),
                },
                ensure_ascii=False,
            )

        # 取前 N 筆
        entities = []
        for _, row in df.head(top_n).iterrows():
            entity = {"name": str(row[name_col])}
            # 嘗試附加 type 和 description
            if "type" in df.columns:
                entity["type"] = str(row["type"])
            if "description" in df.columns:
                desc = str(row["description"])
                entity["description"] = desc[:200] + "..." if len(desc) > 200 else desc
            entities.append(entity)

        return json.dumps(
            {
                "success": True,
                "total_entities": len(df),
                "showing": len(entities),
                "source_file": str(entity_files[0].name),
                "entities": entities,
            },
            ensure_ascii=False,
        )

    except ImportError:
        return json.dumps(
            {
                "success": False,
                "error": "需要 pandas 和 pyarrow 來讀取 parquet: pip install pandas pyarrow",
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "error": f"讀取 entities 失敗: {type(e).__name__}: {e}",
            },
            ensure_ascii=False,
        )


# ---------------------------------------------------------------------------
# 啟動
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"GraphRAG MCP Server")
    print(f"  Root:      {Path(GRAPHRAG_DB_ROOT).resolve()}")
    print(f"  Endpoint:  http://{HOST}:{PORT}/mcp")
    print(f"  Transport: Streamable HTTP")
    print(f"  Timeout:   {QUERY_TIMEOUT}s")
    print()
    print("Claude Code 連接指令:")
    print(f"  claude mcp add --transport http graphrag http://localhost:{PORT}/mcp")
    print()

    mcp.run(transport="streamable-http")
