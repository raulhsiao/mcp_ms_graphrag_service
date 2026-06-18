# Rules:
- Always respond me in Tradition Chinese, no mater what language I used.

# GraphRAG 使用規則
- 當問題與「已索引文件的內容」相關（例如 Airoha LE Audio SDK、BT/LE Audio 服務、
  建置流程、授權、驅動，或 MS GraphRAG 相關內容），回答前必須先查詢 graphrag MCP，
  不要僅憑記憶回答。
- 流程：先（必要時）用 graphrag_index_status 確認索引可用 → 再用 graphrag_query 查詢。
- 資料庫選擇（database 參數，每次查詢獨立指定，無全域狀態）：
  - "Airoha"（預設）：Airoha LE Audio SDK / BT 相關內容，對應 /workspace/DB_AIROHA。
  - "MS GraphRAG"：MS GraphRAG 相關內容，對應 /workspace/DB_MS_GRAPHRAG。
  - 三個工具皆吃 database 參數：graphrag_query、graphrag_index_status、graphrag_list_entities；
    未指定時預設 "Airoha"；同一輪可在連續查詢中切換不同庫而互不干擾。
- method 選擇：具體實體/細節用 local；全局主題/總結用 global；不確定用 drift。
- community_level：數字越小越概觀、越大越精細（預設 2）；global 查詢通常用較小值。
- 查詢會實際執行 graphrag CLI，可能數十秒（預設逾時 240 秒），請耐心等待。
- 若不確定圖譜內容，可先用 graphrag_list_entities 瀏覽；需完整用法可讀 resource guide://graphrag。
- 若 graphrag 查無結果或回傳 success=false，再回退到一般推理，並明確說明已回退。