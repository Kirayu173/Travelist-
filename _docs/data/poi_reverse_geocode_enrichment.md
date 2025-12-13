# POI 逆地理编码数据增强流程（Amap）

## 目标
为 `pois_data/*.csv` 补齐 `addr/city/province/district/township` 字段，提升规划候选 POI 的可解释性与目的地匹配质量（Stage-8 Deep/评测对比所需）。

## 输入/输出
- 输入：`pois_data/poi_final.csv`、`pois_data/traffic_pois_final.csv`
- 输出：原文件原地更新，新增/覆盖字段：
  - `response`：Amap reverse geocode 原始 JSON（字符串）
  - `addr/city/province/district/township`：从 `response` 解析得到

## 运行前置
- 配置环境变量或 `.env`：`AMAP_API_KEY=<your_key>`
- 安装依赖：`pip install -r requirements.txt`（或 `pip install -e .[dev]`）

## 执行命令
```bash
python scripts/enrich_reverse_geocode.py
```
或指定文件：
```bash
python scripts/enrich_reverse_geocode.py pois_data/poi_final.csv
```

## 可靠性与规范
- 速率限制：脚本默认 `SLEEP_SECONDS=0.35`（约 3 req/s），遵循平台限流约束。
- 断点续跑：脚本会周期性 checkpoint 写盘（`SAVE_EVERY_BATCHES`），并复用已存在 `response` 的行。
- 跨文件复用：相同坐标会通过内存 cache 复用响应，避免重复请求。
- 错误记录：`response` 会写入 `{"error": ...}` 结构，解析阶段会自动留空，不会中断整批。

## 验收标准（建议）
- `response` 非空占比达到预期（>= 95%，视 key 配额与坐标质量而定）
- `city/province/district` 字段可用于后续检索或统计，不出现大规模空值回归
- 文件可被后端正常读取（UTF-8 编码、列名一致）

