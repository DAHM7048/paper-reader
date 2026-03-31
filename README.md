# Paper Reader

学术论文智能阅读助手。当前工作流分为三步：

1. `translate.py`：调用 `pdf2zh` 生成双语 PDF
2. `extract.py`：从 PDF 提取 `full.md`
3. `index.py`：基于 `full.md` 生成面向问答的 `index.json`

## 目录结构

```text
papers/{论文名}/
├── original.pdf
├── bilingual.pdf
├── full.md
└── index.json
```

## 配置文件

项目使用两个层级的配置：

- `paper_reader_config.json`
  共享默认配置，可安全提交到仓库。这里不要填写真实 API Key。
- `paper_reader_config.local.json`
  本地私有配置，用于覆盖共享配置中的字段，适合放个人 API Key。该文件已加入 `.gitignore`，不会上传。

优先级从低到高：

1. `paper_reader_config.json`
2. `paper_reader_config.local.json`
3. 环境变量
4. 命令行参数

### 推荐做法

仓库里保留空的共享配置：

```json
{
  "api": {
    "api_key": "",
    "endpoint_mode": "coding-plan",
    "base_url": "https://open.bigmodel.cn/api/coding/paas/v4"
  }
}
```

每个人自己在本地创建 `paper_reader_config.local.json`：

```json
{
  "api": {
    "api_key": "your-api-key"
  }
}
```

最小可用内容就是：

```json
{
  "api": {
    "api_key": "XXXX"
  }
}
```

## 当前默认模型

- 翻译模型：`GLM-4-Flash-250414`
- 索引模型：`GLM-4-Flash-250414`
- 翻译并发：`5`

说明：

- 翻译和索引会调用模型
- `extract.py` 不调用模型，它只做 PDF 文本提取

## 安装依赖

```powershell
D:\study\python3.12\python.exe -m pip install -r requirements.txt
```

## 使用方式

### 1. 翻译

```powershell
D:\study\python3.12\python.exe tools/translate.py "你的论文.pdf"
```

### 2. 提取

```powershell
D:\study\python3.12\python.exe tools/extract.py "你的论文.pdf"
```

### 3. 索引

```powershell
D:\study\python3.12\python.exe tools/index.py "papers/论文名/full.md"
```

## 问答策略

问论文内容时，建议按下面的顺序：

1. 先看 `index.json.sections`
2. 命中弱时再看 `index.json.page_fallback`
3. 用 `start_offset` / `end_offset` 回到 `full.md` 读取原文
4. 最终用中文回答，并标注章节名和页码

## 版本库建议

建议提交这些文件：

- `AGENTS.md`
- `README.md`
- `paper_reader_config.json`
- `requirements.txt`
- `tools/`

不要提交这些内容：

- `paper_reader_config.local.json`
- `papers/`
- `.runtime/`
- `.cache/`
- `.config/`
