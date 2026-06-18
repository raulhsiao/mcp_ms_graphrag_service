# 讓 Claude 自動參考 GraphRAG MCP 的兩種方案

本文件說明如何讓 Claude Code 在回答時**自動參考 graphrag MCP**，包含兩種做法：

- **方案一：CLAUDE.md（軟性引導）** — 簡單、CP 值高，已套用。
- **方案二：Hook（強制執行）** — 系統層級保證，不依賴模型自覺。

---

## 方案一：CLAUDE.md（推薦，已完成）

### 原理

`CLAUDE.md` 的內容每次 session 都會載入 Claude 的 context，因此在裡面寫一條規則，就能讓 Claude 每次都「傾向」先查 graphrag。這是**引導式**的——模型會遵循，但本質上是提示而非程式強制。

重點：規則要寫清楚「**何時**該用、**怎麼**用」，比單純寫 "always use graphrag" 有效得多，因為這樣模型才知道在哪些問題上觸發。

### 已寫入的規則

放置於專案層級 `/workspace/CLAUDE.md`：

```markdown
# GraphRAG 使用規則
- 當問題與「已索引文件的內容」相關（例如 Airoha LE Audio SDK、BT/LE Audio 服務、
  建置流程、授權、驅動等），回答前必須先查詢 graphrag MCP，不要僅憑記憶回答。
- 流程：先（必要時）用 graphrag_index_status 確認索引可用 → 再用 graphrag_query 查詢。
- method 選擇：具體實體/細節用 local；全局主題/總結用 global；不確定用 drift。
- community_level：數字越小越概觀、越大越精細（預設 2）；global 查詢通常用較小值。
- 若 graphrag 查無結果或回傳 success=false，再回退到一般推理，並明確說明已回退。
```

### 放置位置選項

| 檔案 | 生效範圍 |
|------|----------|
| `/workspace/CLAUDE.md` | 只對這個專案生效（建議） |
| `~/.claude/CLAUDE.md` | 對所有專案生效（全域） |

> 下次起新 session 時自動載入並生效。

---

## 方案二：Hook（強制執行）

### 原理

在你**每次送出訊息時**，由 Claude Code 的 harness 自動執行一段 shell 指令，把「提醒」（甚至直接把查詢結果）注入到 context，不依賴模型自覺。使用的是 `UserPromptSubmit` 這個 hook 事件，其指令的 **stdout** 會被當作額外 context 注入該輪輸入。

### 步驟 1：選擇設定檔位置

編輯下列其中一個 `settings.json`（JSON 格式，非 CLAUDE.md）：

| 檔案 | 生效範圍 | 是否進版控 |
|------|----------|-----------|
| `/workspace/.claude/settings.json` | 本專案、團隊共用 | 會 commit |
| `/workspace/.claude/settings.local.json` | 本專案、僅你自己 | 不進版控 |
| `~/.claude/settings.json` | 所有專案（全域） | — |

建議用專案層級的 `.claude/settings.json`。

### 步驟 2：寫入 hook 設定（注入固定提醒，最穩定）

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo '[提醒] 若本題與已索引文件內容（Airoha LE Audio SDK、BT/LE Audio 服務、建置、授權、驅動等）相關，回答前務必先呼叫 graphrag MCP（graphrag_index_status → graphrag_query），勿僅憑記憶作答。'"
          }
        ]
      }
    ]
  }
}
```

運作方式：`UserPromptSubmit` hook 把指令的 stdout 內容當作額外 context 注入。每次對話都會看到這段強制提醒。

### 步驟 3（進階，可選）：直接把查詢結果塞進來

不只是提醒，而是**直接自動跑 graphrag CLI 並把結果注入**。把 `command` 換成一支腳本，讀取 prompt（hook 會以 JSON 從 stdin 傳入，含 `prompt` 欄位），呼叫 graphrag CLI 查詢後輸出結果。骨架：

```bash
#!/usr/bin/env bash
# .claude/hooks/graphrag_inject.sh
input=$(cat)                                   # 從 stdin 取得 JSON
prompt=$(echo "$input" | jq -r '.prompt')      # 取出使用者問題
# 視需要加關鍵字判斷是否該觸發；這裡示意直接查
result=$(cd /workspace/DbAB157x && graphrag query --method global --query "$prompt" 2>/dev/null)
echo "[GraphRAG 自動查詢結果]"
echo "$result"
```

settings.json 中改為 `"command": "bash /workspace/.claude/hooks/graphrag_inject.sh"`，並記得 `chmod +x`。

> 注意：步驟 3 每則訊息都會實跑一次 CLI（可能數十秒、且耗 token），建議在腳本內加關鍵字判斷，只有相關問題才觸發；否則回 exit 0、不輸出即可。

### 步驟 4：驗證

設定後執行 `/hooks` 指令可檢視已註冊的 hooks；送一則測試訊息確認提醒/結果有被注入。

---

## 兩種做法比較

| | 方案一：CLAUDE.md | 方案二：Hook |
|---|---|---|
| 機制 | 引導模型主動呼叫工具 | 系統每輪自動注入 |
| 可靠度 | 高，但仍由模型判斷 | 強制，不依賴模型自覺 |
| 成本 | 低 | 步驟 2 低／步驟 3 較高 |
| 設定難度 | 極簡 | 中等 |

### 實務建議

1. 先用**方案一（CLAUDE.md）**，對絕大多數情況已足夠。
2. 若發現偶爾仍漏查、想要更高保證，再加上**方案二步驟 2 的提醒型 hook**（CP 值最高）。
3. 需要 100% 自動注入查詢結果時，才考慮**步驟 3 的腳本型 hook**（注意成本與延遲）。
