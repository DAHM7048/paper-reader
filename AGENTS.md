# 学术论文智能阅读助手

## 项目简介

学术论文智能阅读助手，提供翻译、提取、索引工具。用户用 opencode 打开项目目录，通过对话完成论文阅读、定位和总结。

## 目录约定

```text
papers/{论文名}/
├── original.pdf    ← 原始 PDF
├── bilingual.pdf   ← 翻译脚本产出（pdf2zh）
├── full.md         ← 全文 Markdown
└── index.json      ← 问答检索索引
```

## 工具命令

opencode 自动调用这些命令：

- **翻译**：`D:\study\python3.12\python.exe tools/translate.py <pdf_path>`
- **提取**：`D:\study\python3.12\python.exe tools/extract.py <pdf_path>`
- **索引**：`D:\study\python3.12\python.exe tools/index.py <md_path>`

## 配置文件

项目默认从 `paper_reader_config.json` 读取共享配置。

如果需要放个人 API Key，可在仓库根目录额外创建 `paper_reader_config.local.json`。
加载顺序是：

1. `paper_reader_config.json`
2. `paper_reader_config.local.json`
3. 环境变量
4. 命令行参数

本地私有配置文件的最小内容如下：

```json
{
  "api": {
    "api_key": "user_api"
  }
}
```

- API Key
- 端点模式
- Base URL
- 翻译模型与并发
- 索引模型与分块参数

## 默认工作流

当用户说“处理这篇论文”时执行：

1. 将 PDF 拷贝到 `papers/{论文名}/original.pdf`
2. 运行 `translate`
3. 运行 `extract`
4. 运行 `index`
5. 确认 `bilingual.pdf`、`full.md`、`index.json` 都已生成

## 翻译策略

- `tools/translate.py` 默认使用当前已验证成功的 Coding Plan / OpenAI-compatible 工作流
- 默认模型：`GLM-4-Flash-250414`
- 默认并发：`5`
- 仍可通过命令行参数覆盖模型、端点模式、并发和超时

## 索引策略

- `tools/index.py` 是索引执行器
- `tools/index.md` 是索引提示词模板
- 默认流程是：
  1. `index.py` 读取 `full.md`
  2. `index.py` 读取 `tools/index.md`
  3. 优先调用模型生成 `index.json`
  4. 如果模型失败或输出非法 JSON，自动回退到规则式索引

`index.json` 主要包含：

- `document_title`
- `source_markdown`
- `source_pdf_candidates`
- `total_pages`
- `total_chars`
- `sections`
- `page_fallback`
- `retrieval_hints`

其中：

- `sections` 用于章节级问答定位
- `page_fallback` 用于章节命中弱时按页回退

## 对话策略

当用户问论文相关问题时：

1. 先读 `index.json.sections`
2. 按 `title_zh`、`title_en`、`keywords`、`questions_answered` 找候选章节
3. 如果章节命中弱，再读 `index.json.page_fallback`
4. 用 `start_offset` / `end_offset` 回到 `full.md` 读取英文原文和上下文
5. 用中文回答，但引用时标注章节名和页码
6. 如果索引摘要与原文冲突，以 `full.md` 原文为准

## 实施约束

- 不要把 `index.json` 改成纯 Markdown 索引
- `index.md` 是提示词模板，不是最终索引结果
- 问答时优先使用 `index.json + full.md` 的组合
- 如果 `full.md` 文本质量较差，优先指出原文抽取噪声，而不是盲信索引摘要
