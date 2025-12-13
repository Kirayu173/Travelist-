# P2-1：数据治理（POI 逆地理增强）

## 整改目标
- 形成可重复的数据增强流程，用于补齐 POI 的行政区与地址字段，为 Stage-8 规划质量与评测提供可靠数据基础。

## 实施步骤
1. 梳理脚本输入/输出与字段规范：`scripts/enrich_reverse_geocode.py`
2. 补齐流程文档与验收标准：`_docs/data/poi_reverse_geocode_enrichment.md`
3. 约定 Key 管理：通过 `AMAP_API_KEY` 环境变量或仓库 `.env`（不提交真实 key）。

## 完成时限
- 2025-12-13（已完成）

## 效果验证
- 脚本可在断点续跑场景下稳定执行，最终文件包含 `addr/city/province/district/township` 等字段。

## 证据材料
- `scripts/enrich_reverse_geocode.py`
- `_docs/data/poi_reverse_geocode_enrichment.md`

