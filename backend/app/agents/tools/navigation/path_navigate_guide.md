# PathNavigate 工具使用指南

## 1. 工具简介

PathNavigate 是一个多功能路径规划工具，提供多种出行方式的路线距离与时长评估。该工具具有以下特点：

- 支持多种出行方式：驾车、步行、公交、骑行
- 批量路线规划：一次可处理多条路线
- 智能降级：当无法使用API时，提供本地估算模式
- 详细的日志记录：记录所有API调用和结果
- 参数验证：确保输入参数符合要求

## 2. 配置准备

### 2.1 API密钥配置

该工具依赖高德地图开放平台的API服务，需要配置有效的API密钥：

1. 在高德地图开放平台（https://lbs.amap.com/）注册开发者账号
2. 创建应用并获取API密钥（AMAP_API_KEY）
3. 将API密钥添加到项目根目录的`.env`文件中：

```
AMAP_API_KEY=your_api_key_here
```

### 2.2 依赖安装

确保已安装以下依赖：

- Python 3.8+
- requests
- pydantic
- langchain_core
- python-dotenv

## 3. 工具结构

PathNavigate 工具使用 StructuredTool 框架，主要组件包括：

- `PathNavigateInput`：输入参数模型，定义了工具接受的参数格式
- `PathNavigateTool`：核心工具类，实现路径规划功能
- `_geocode`：地理编码方法，将地址转换为坐标
- `_navigate_route`：路线规划方法，获取路线信息
- `_fallback_estimate`：离线估算模式，当API不可用时提供估算值

## 4. 参数详情

工具接受以下参数：

| 参数名 | 类型 | 必填 | 默认值 | 描述 |
|--------|------|------|--------|------|
| routes | List[Dict[str, str]] | 是 | - | 路径列表，每项包含 origin 和 destination，最少1项，最多20项 |
| travel_mode | Literal["driving", "walking", "transit", "bicycling"] | 否 | driving | 出行方式：驾车、步行、公交、骑行 |
| strategy | int | 否 | 0 | 驾车策略，仅 driving 模式生效，范围0-9 |
| city | Optional[str] | 否 | None | 可选城市名称，用于 transit 描述和地理编码 |

### 4.1 驾车策略说明

当 travel_mode 为 driving 时，strategy 参数可用：

- 0：推荐路线
- 1：最短距离
- 2：最短时间
- 3：避开拥堵
- 4：不走高速
- 5：高速优先
- 6：不走高速且避开收费
- 7：高速优先且避开收费
- 8：避开收费
- 9：避开拥堵和收费

## 5. 使用示例

### 5.1 基本使用

```python
from app.agents.tools.navigation.path_navigate import create_tool

# 创建工具实例
tool = create_tool()

# 定义路径参数
params = {
    "routes": [
        {"origin": "北京市海淀区中关村南大街5号", "destination": "北京市朝阳区建国路88号"},
        {"origin": "北京市海淀区清华大学", "destination": "北京市西城区北京大学第一医院"}
    ],
    "travel_mode": "driving",
    "strategy": 0,
    "city": "北京"
}

# 调用工具
result = tool.run(**params)
print(result)
```

### 5.2 不同出行方式示例

```python
# 步行模式
params_walking = {
    "routes": [{"origin": "北京市海淀区中关村", "destination": "北京市海淀区五道口"}],
    "travel_mode": "walking"
}

# 公交模式
params_transit = {
    "routes": [{"origin": "北京市海淀区中关村", "destination": "北京市朝阳区国贸"}],
    "travel_mode": "transit",
    "city": "北京"
}

# 骑行模式
params_bicycling = {
    "routes": [{"origin": "北京市海淀区中关村", "destination": "北京市海淀区清华大学"}],
    "travel_mode": "bicycling"
}
```

## 6. 输出格式

工具返回一个包含以下信息的字典：

```python
{
    "summary": {
        "total_routes": 2,  # 路线总数
        "travel_mode": "driving"  # 出行方式
    },
    "routes": [  # 路线详情列表
        {
            "origin": "北京市海淀区中关村南大街5号",  # 起点
            "destination": "北京市朝阳区建国路88号",  # 终点
            "status": "success",  # 状态：success/failed/estimated
            "route_info": {...},  # API返回的路线信息（仅成功时）
            "error": null  # 错误信息（仅失败时）
        },
        # 更多路线...
    ]
}
```

### 6.1 离线估算模式输出

当无法使用API时，返回的估算结果格式如下：

```python
{
    "origin": "北京市海淀区中关村南大街5号",
    "destination": "北京市朝阳区建国路88号",
    "distance_km": 15.5,  # 估算距离（公里）
    "duration_min": 35,  # 估算时长（分钟）
    "travel_mode": "driving",
    "strategy": 0,
    "city": "北京",
    "status": "estimated"  # 状态为估算
}
```

## 7. 错误处理

工具内置了错误处理机制，可能出现的错误包括：

### 7.1 参数错误

当输入参数不符合要求时，返回错误信息：

```python
{
    "error": "参数错误: routes must not be empty"
}
```

### 7.2 API相关错误

当API调用失败时，返回详细的错误信息：

```python
{
    "summary": {"total_routes": 1, "travel_mode": "driving"},
    "routes": [
        {
            "origin": "无效地址",
            "destination": "北京市朝阳区",
            "status": "failed",
            "error": "地址解析失败"
        }
    ]
}
```

## 8. 离线估算模式

当无法获取有效的API密钥或API调用失败时，工具会自动切换到离线估算模式。该模式基于以下规则：

- 距离估算：根据起点和终点字符串长度生成1-1200公里之间的距离
- 时长估算：基于不同出行方式的平均速度计算
  - 驾车：60公里/小时
  - 公交：40公里/小时
  - 骑行：15公里/小时
  - 步行：5公里/小时

## 9. 地理编码功能

工具内置了地理编码功能，用于将地址转换为坐标：

- 使用高德地图地理编码API
- 支持指定城市参数提高准确性
- 自动记录地理编码请求和响应日志

## 10. 日志记录

工具使用结构化日志记录所有操作，包括：

- 工具调用事件（invoke）
- 地理编码事件（geocode）
- 路线规划事件（route_*）
- 错误事件（error）

日志包含请求参数、响应结果、状态码和错误信息，便于问题排查和性能监控。

## 11. 性能考虑

- 批量处理限制为最多20条路线，避免API请求过多
- 每个API请求设置10秒超时，避免长时间阻塞
- 自动使用地理编码缓存，提高性能

## 12. 注意事项

- 确保配置有效的AMAP_API_KEY以获得准确的路线信息
- 公交模式下建议提供city参数以获得更准确的结果
- 大量请求可能触发高德API的频率限制
- 离线估算模式的结果仅供参考，不代表实际路线