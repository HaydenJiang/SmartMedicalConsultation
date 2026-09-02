# Medical Website Crawler

医疗网站爬虫模块，用于采集疾病、症状、科室、药物等医疗数据。

## 功能特性

- ✅ **多数据源支持**：好大夫在线（主）+ 寻医问药网（备）
- ✅ **robots.txt 合规**：自动检查并遵守网站的 robots.txt 规则
- ✅ **反爬策略**：随机 User-Agent、请求延时（3-5秒）
- ✅ **异常处理**：自动重试机制（最多3次）
- ✅ **断点续爬**：支持中断后继续爬取
- ✅ **数据清洗**：自动去重、清洗、格式化
- ✅ **双格式输出**：JSON（程序使用）+ Excel（人工查看）
- ✅ **完整日志**：详细的爬取和清洗日志

## 目录结构

```
crawler/
├── __init__.py              # 模块初始化
├── medical_crawler.py       # 爬虫主程序
├── data_processor.py        # 数据清洗程序
└── README.md               # 使用说明

data/
├── raw/                    # 原始数据
│   ├── diseases.json       # 爬取的原始数据
│   └── .crawl_checkpoint.json  # 断点续爬记录
└── processed/              # 清洗后的数据
    ├── diseases.json       # JSON 格式（程序使用）
    └── diseases.xlsx       # Excel 格式（人工查看）
```

## 使用方法

### 1. 爬取数据

```bash
# 默认爬取 500 条疾病数据（预定义 500 种常见疾病种子列表，寻医问药备用源自动补齐）
python crawler/medical_crawler.py

# 小批量验证（先跑通流程、确认解析质量，再全量扩采）
python crawler/medical_crawler.py --max 200

# 仅使用好大夫在线，不启用寻医问药备用源
python crawler/medical_crawler.py --no-backup

# 重新开始爬取（清除断点记录）
python crawler/medical_crawler.py --reset

# 查看帮助
python crawler/medical_crawler.py --help
```

### 2. 清洗数据

```bash
# 运行数据清洗
python crawler/data_processor.py
```

### 3. 在代码中使用

```python
from crawler import MedicalCrawler

# 创建爬虫实例
crawler = MedicalCrawler()

# 默认爬取 500 条（预定义种子列表 + 备用源补齐）
crawler.run()

# 小批量验证：先爬 200 条确认解析质量
# crawler.run(max_diseases=200)

# 查看结果
print(f"爬取了 {len(crawler.diseases)} 条疾病数据")
```

## 采集字段

每条疾病数据包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 疾病名称 |
| `description` | str | 疾病描述 |
| `symptoms` | list | 症状列表 |
| `department` | str | 就诊科室 |
| `treatment` | str | 治疗方案 |
| `medications` | list | 相关药物 |
| `source` | str | 数据来源（haodf.com / xywy.com） |
| `url` | str | 原始页面 URL |
| `crawled_at` | str | 爬取时间 |

## robots.txt 合规

### 好大夫在线 (haodf.com)

**允许爬取的路径**：
- `/jibing/*` - 疾病百科 ✅
- `/keshi/*` - 科室信息 ✅
- `/hospital/*` - 医院信息 ✅
- `/doctor/*` - 医生信息 ✅

**禁止爬取的路径**：
- `/*/ajax*` - API 接口 ❌
- `/bingcheng/*` - 病程记录 ❌

**注意**：AI 爬虫（GPTBot、ClaudeBot 等）被完全禁止

### 寻医问药网 (xywy.com)

需要检查 `https://www.xywy.com/robots.txt` 确认允许的路径

## 爬虫礼仪

1. **请求频率**：每次请求间隔 3-5 秒
2. **User-Agent**：使用标准浏览器 User-Agent
3. **数据量**：单次爬取不超过 1000 条
4. **用途**：仅用于学习和研究目的

## 常见问题

### Q: 爬虫中断了怎么办？

A: 直接重新运行即可，爬虫会自动从断点继续：

```bash
python crawler/medical_crawler.py
```

### Q: 如何重新开始爬取？

A: 使用 `--reset` 参数：

```bash
python crawler/medical_crawler.py --reset
```

### Q: 爬取的数据在哪里？

A: 
- 原始数据：`data/raw/diseases.json`
- 清洗后数据：`data/processed/diseases.json`
- Excel 格式：`data/processed/diseases.xlsx`

### Q: 如何查看爬取日志？

A: 日志文件在 `logs/crawler.log`

## 注意事项

⚠️ **法律合规**：
- 仅用于学习和研究目的
- 遵守 robots.txt 规则
- 不对目标网站造成过大访问压力
- 不用于商业用途

⚠️ **数据质量**：
- 爬取的数据可能存在不完整的情况
- 建议人工检查 Excel 文件确认数据质量
- 数据清洗会去除空值和重复数据

## 技术栈

- `requests` - HTTP 请求
- `BeautifulSoup` - HTML 解析
- `tenacity` - 重试机制
- `pandas` - 数据处理
- `openpyxl` - Excel 导出
- `logging` - 日志记录
