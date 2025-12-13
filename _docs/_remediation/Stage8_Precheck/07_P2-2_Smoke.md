# P2-2：E2E 冒烟脚本

## 整改目标
- 提供可重复的端到端冒烟，验证：
  - `POST /api/ai/plan`（fast）可用
  - `GET /admin/plan/summary` 指标可读且调用次数递增

## 实施步骤
1. 新增脚本：`scripts/smoke_stage7.py`
2. README 增加用法提示：`README.md`

## 完成时限
- 2025-12-13（已完成）

## 使用方式
- 需要服务已启动（本地或容器均可），并设置 `ADMIN_API_TOKEN`
```bash
ADMIN_API_TOKEN=please-change-admin-token python scripts/smoke_stage7.py --base-url http://127.0.0.1:8000
```

## 验收标准
- 输出 `OK: Stage-7 smoke passed.`

## 证据材料
- `scripts/smoke_stage7.py`
- `README.md`

