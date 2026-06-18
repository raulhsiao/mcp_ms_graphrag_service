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
# instructions 會在 MCP initialize handshake 時回傳給 client，
# client（如 Claude）通常會把它注入 system prompt，
# 讓 agent 在呼叫任何工具「之前」就知道這個服務怎麼用。
SERVER_INSTRUCTIONS = """\
這是一個 GraphRAG 知識圖譜查詢服務，對「已索引的文件」提供圖譜式問答。

建議使用流程：
1. 首次使用先呼叫 graphrag_index_status，確認索引已完成、資料可用。
2. 若不清楚圖譜內容，用 graphrag_list_entities 瀏覽有哪些實體（entity）。
3. 用 graphrag_query 提問，並依問題類型選擇 method：
   • local ：針對特定實體或具體細節（「X 是什麼？」「A 與 B 的關係？」）。
   • global：針對全局、主題式、需彙整全文的問題（「主要主題有哪些？」「整體總結」）。
   • drift ：兼顧細節與廣度的混合查詢；不確定時的折衷選擇。

注意事項：
- community_level 數字越小越概觀、越大越精細（預設 2）；global 查詢通常用較小的值。
- 查詢會實際執行 graphrag CLI，可能需數十秒，請耐心等待（預設逾時 120 秒）。
- 所有工具皆回傳 JSON 字串並含 success 欄位；success=false 時請讀取 error 欄位。
- 需要完整使用範例與錯誤排解，可讀取 resource：guide://graphrag。
"""

mcp = FastMCP(
    name="graphrag",
    # instructions：連線時自動傳給 agent 的服務使用說明
    instructions=SERVER_INSTRUCTIONS,
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
# MCP Resource — 完整使用手冊（agent 可按需讀取）
# ---------------------------------------------------------------------------
_GUIDE = """\
# GraphRAG 知識圖譜查詢服務 — 使用手冊

## 服務簡介
對「已用 Microsoft GraphRAG 索引過的文件」提供圖譜式問答，底層透過 graphrag CLI 執行查詢。

## 可用工具
- `graphrag_index_status()`：檢查索引狀態與 output artifact 清單。
- `graphrag_list_entities(top_n=20)`：列出圖譜中的實體（entity），最大 200。
- `graphrag_query(query, method, community_level)`：核心查詢工具。

## 建議工作流程
1. 先 `graphrag_index_status()` 確認 output 目錄已有 artifact（代表索引完成）。
2. 不熟悉內容時，用 `graphrag_list_entities()` 了解圖譜涵蓋哪些實體。
3. 用 `graphrag_query()` 提問。

## method 怎麼選
| method | 適用情境 | 範例 |
| ------ | -------- | ---- |
| local  | 特定實體 / 具體細節 | 「X 元件的職責是什麼？」 |
| global | 全局主題 / 跨文件彙整 | 「這批文件的主要議題有哪些？」 |
| drift  | 兼顧細節與廣度的混合查詢 | 「X 如何運作、又與誰相關？」 |

## community_level
- 控制社群階層細緻度：數字小 → 大社群、偏概觀；數字大 → 小社群、偏細節。
- global 查詢建議 1–2；local 查詢可用 2–3。預設 2。

## 範例
- 全局總結：`graphrag_query(query="總結整體內容", method="global", community_level=1)`
- 實體關係：`graphrag_query(query="A 與 B 的關係", method="local")`

## 錯誤排解（success=false 時讀 error 欄位）
- 「找不到 graphrag 指令」→ `pip install graphrag`
- 「output 目錄不存在」→ 尚未執行 `graphrag index`
- 「查詢逾時」→ 調高環境變數 GRAPHRAG_QUERY_TIMEOUT，或簡化問題
"""


@mcp.resource(
    "guide://graphrag",
    name="graphrag_usage_guide",
    title="GraphRAG 使用手冊",
    description="GraphRAG 查詢服務的完整使用手冊：工作流程、method 選擇、範例與錯誤排解。",
    mime_type="text/markdown",
)
def usage_guide() -> str:
    """回傳完整使用手冊（Markdown）。"""
    return _GUIDE


# ---------------------------------------------------------------------------
# MCP Prompts — 預設提問範本（使用者可在 client 介面挑選）
# ---------------------------------------------------------------------------
@mcp.prompt(
    name="summarize_knowledge_base",
    title="總結知識庫",
    description="引導 agent 用 global 查詢，對整個知識庫做結構化總結。",
)
def summarize_knowledge_base() -> str:
    return (
        "請先用 graphrag_index_status 確認索引可用，"
        '再用 graphrag_query 以 method="global"、community_level=1 '
        "對整個知識庫做一份結構化總結，列出主要主題及其關聯。"
    )


@mcp.prompt(
    name="ask_about_topic",
    title="查詢特定主題",
    description="針對指定主題提問，並自動建議合適的查詢 method。",
)
def ask_about_topic(topic: str) -> str:
    return (
        f"請用 graphrag_query 查詢「{topic}」。"
        '若問題聚焦於特定實體或細節，使用 method="local"；'
        '若需要跨文件彙整，使用 method="global"。'
        "必要時先用 graphrag_list_entities 確認相關實體名稱。"
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
