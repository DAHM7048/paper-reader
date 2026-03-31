# Paper Reader

学术论文智能阅读助手。

中英文对照 PDF 翻译基于 `pdf2zh` / `PDFMathTranslate` 实现；在此基础上，项目补充了全文提取、问答索引和统一配置，方便在本地通过对话完成论文阅读。

当前工作流分为三步：
1. `translate.py`：调用 `pdf2zh` 生成双语 PDF
2. `extract.py`：从 PDF 提取 `full.md`
3. `index.py`：基于 `full.md` 生成面向问答的 `index.json`

目前默认的模型调用链路使用的是智谱 GLM 系列模型。

## 目录结构

```text
papers/{论文名}/
├── original.pdf
├── bilingual.pdf
├── full.md
└── index.json
```

## 配置文件

项目使用两层配置：

- `paper_reader_config.json`
  仓库共享配置，可以安全提交到版本库，不要在这里填写真实 API Key。
- `paper_reader_config.local.json`
  本地私有配置，用于覆盖共享配置中的字段，适合填写个人 API Key。该文件已加入 `.gitignore`，不会上传。

加载优先级从低到高：

1. `paper_reader_config.json`
2. `paper_reader_config.local.json`
3. 环境变量
4. 命令行参数

仓库里保留的是共享配置，例如：

```json
{
  "api": {
    "api_key": "",
    "endpoint_mode": "coding-plan",
    "base_url": "https://open.bigmodel.cn/api/coding/paas/v4"
  }
}
```

每个人在本地新建 `paper_reader_config.local.json`，按下面这个格式填写自己的 API：

```json
{
  "api": {
    "api_key": "XXXX"
  }
}
```

如果需要，也可以在这个本地文件里继续覆盖模型、端点或并发参数。

## 当前默认模型

当前默认工作流依赖 GLM 模型完成翻译和索引。

- 翻译模型：`GLM-4-Flash-250414`
- 索引模型：`GLM-4-Flash-250414`
- 翻译并发：`5`

说明：
- 翻译和索引会调用模型
- `extract.py` 不调用模型，只负责 PDF 文本提取

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

