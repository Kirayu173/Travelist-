# AreaWeather 工具使用指南

## 1. 工具简介

**AreaWeather** 是一个基于高德地图 API 的天气查询工具，支持查询多个地点的实时天气和天气预报。该工具具有以下特点：

- 支持多地点同时查询
- 提供实时天气和天气预报两种查询模式
- 内置行政区编码缓存机制，提高查询效率
- 完善的日志记录和错误处理
- 当 API Key 未配置时提供模拟数据

## 2. 配置准备

### 2.1 API Key 配置

该工具使用高德地图 API，需要先获取高德地图开放平台的 API Key：

1. 访问 [高德开放平台](https://lbs.amap.com/)
2. 注册并登录开发者账号
3. 创建应用并获取 API Key
4. 将 API Key 配置到环境变量中，使用键名 `AMAP_API_KEY`

### 2.2 环境变量加载

工具使用统一的配置加载机制，会自动从以下位置加载环境变量：

- 当前目录的 `.env` 文件
- toolkit 目录的 `.env` 文件
- 项目根目录的 `.env` 文件
- 系统环境变量

## 3. 工具结构

```
backend/app/agents/tools/weather/area_weather.py
```

工具主要包含以下类和函数：

- `AreaWeatherInput`：输入参数模型
- `AreaWeatherTool`：主要工具类，实现天气查询功能
- `create_tool()`：工厂函数，用于创建工具实例

## 4. 参数说明

### 4.1 输入参数

使用 `AreaWeatherInput` 模型定义输入参数：

| 参数名 | 类型 | 默认值 | 说明 | 是否必填 |
|--------|------|--------|------|----------|
| locations | List[str] | - | 查询地点列表，支持城市名或区县名 | 是 |
| weather_type | str | "realtime" | 天气类型，可选值："realtime"(实时天气)、"forecast"(天气预报) | 否 |
| days | int | 1 | 预报天数，仅当 weather_type=forecast 时生效，范围：1-4 天 | 否 |

### 4.2 返回结果

工具返回一个字典，包含以下结构：

```python
{
    "summary": {
        "weather_type": "realtime",  # 查询类型
        "days": 1,                   # 查询天数
        "total_locations": 2         # 查询地点总数
    },
    "results": [                     # 每个地点的查询结果
        {
            "location": "北京",      # 查询地点
            "adcode": "110000",     # 行政区编码
            "status": "success",    # 查询状态
            # 实时天气字段 (weather_type=realtime 时)
            "weather": "晴",         # 天气状况
            "temperature": "25",    # 温度
            "humidity": "40",       # 湿度
            "winddirection": "东南风", # 风向
            "windpower": "3级",     # 风力
            "report_time": "2023-05-01 12:00:00"  # 报告时间
        },
        # 更多地点结果...
    ]
}
```

#### 实时天气 (realtime) 特有字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| weather | str | 天气状况描述 |
| temperature | str | 温度（摄氏度） |
| humidity | str | 湿度百分比 |
| winddirection | str | 风向 |
| windpower | str | 风力等级 |
| report_time | str | 数据发布时间 |

#### 天气预报 (forecast) 特有字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| forecast | List[dict] | 预报数据列表，每项包含一天的预报信息 |
| report_time | str | 预报发布时间 |

#### 预报数据 (forecast 项) 字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| date | str | 预报日期 |
| dayweather | str | 白天天气 |
| nightweather | str | 夜间天气 |
| daytemp | str | 白天温度 |
| nighttemp | str | 夜间温度 |
| daywind | str | 白天风向 |
| nightwind | str | 夜间风向 |
| daypower | str | 白天风力 |
| nightpower | str | 夜间风力 |

## 5. 使用示例

### 5.1 基本使用方法

```python
from app.agents.tools.weather.area_weather import create_tool

# 创建工具实例
weather_tool = create_tool()

# 查询单个地点的实时天气
result = weather_tool._run(
    locations=["北京"],
    weather_type="realtime"
)
print(json.dumps(result, ensure_ascii=False, indent=2))

# 查询多个地点的天气预报
result = weather_tool._run(
    locations=["上海", "广州", "深圳"],
    weather_type="forecast",
    days=3  # 查询未来3天预报
)
print(json.dumps(result, ensure_ascii=False, indent=2))
```

### 5.2 在 Agent 中集成

```python
from langchain.agents import initialize_agent, AgentType
from langchain_core.tools import Tool
from app.agents.tools.weather.area_weather import create_tool

# 创建天气工具
weather_tool_instance = create_tool()

# 包装为 LangChain Tool
tools = [
    Tool(
        name="area_weather",
        func=weather_tool_instance._run,
        description="查询多地点天气（支持实时/预报）"
    )
]

# 初始化 Agent
agent = initialize_agent(
    tools=tools,
    llm=your_llm_instance,
    agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION
)

# 使用 Agent 查询天气
response = agent.run("查询北京和上海的实时天气情况")
```

## 6. 错误处理

工具内置了完善的错误处理机制，当出现以下情况时会返回相应的错误信息：

### 6.1 常见错误状态

| 状态码 | 说明 | 处理方式 |
|--------|------|----------|
| missing_api_key | API Key 未配置 | 返回模拟天气数据 |
| invalid_params | 参数验证失败 | 返回参数错误信息 |
| adcode_request_failed | 行政区编码查询失败 | 返回失败状态，不影响其他地点查询 |
| request_failed | 天气 API 请求失败 | 返回失败状态和错误信息 |

### 6.2 失败响应示例

```python
{
    "summary": {
        "weather_type": "realtime",
        "days": 1,
        "total_locations": 1
    },
    "results": [
        {
            "location": "未知地点",
            "status": "failed",
            "error": "无法获取行政区编码"
        }
    ]
}
```

## 7. 模拟数据

当 API Key 未配置或查询失败时，工具会提供模拟天气数据，格式与真实数据一致，便于开发和测试。模拟数据的来源标记为 `source: "mock"`。

## 8. 性能优化

### 8.1 缓存机制

工具使用了两级缓存来提高性能：

1. **内存缓存**：将查询过的行政区编码缓存在内存中
2. **文件缓存**：从 `resources/adcoder.json` 文件加载预定义的行政区编码

## 9. 注意事项

1. **API 使用限制**：请遵守高德地图 API 的使用限制和配额
2. **参数格式**：地点名称需要准确，建议使用标准的城市或区县名称
3. **API Key 安全**：请勿在代码中硬编码 API Key，使用环境变量配置
4. **错误处理**：调用时请检查返回结果中的 status 字段，合理处理失败情况

## 10. 相关 API 文档

- [高德地图地理编码/逆地理编码 API](https://lbs.amap.com/api/webservice/guide/api/georegeo)
- [高德地图天气查询 API](https://lbs.amap.com/api/webservice/guide/api/weatherinfo)
