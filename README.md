# 本地智能读书助手

> 面向 WorkBuddy 的本地读书工作流：搜索用户有权获取的电子书，将原始文件安全保存到本机，并自动导入 IMA 知识库。

[![Version](https://img.shields.io/badge/version-v1-blue.svg)](https://github.com/starryChenstudent/-_workbuddy-imaknowledgebase/tree/v1)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![WorkBuddy Skill](https://img.shields.io/badge/WorkBuddy-Skill-7c3aed.svg)](SKILL.md)

## 项目简介

本项目是一套用于 WorkBuddy 的 Skill。用户提出书籍请求后，它会依次完成版本搜索、格式筛选、授权下载、本地校验、IMA 查重、上传入库和可检索验证。

下载的原始书籍默认保存在当前用户的：

```text
Desktop/library/books/
```

本项目只应用于公版、开放许可，或用户已经获得合法访问与下载授权的内容。请遵守所在地法律、内容许可条款及相关服务的使用规则。

## 核心能力

- 按书名、作者、ISBN、DOI 或 MD5 搜索书籍。
- 优先选择 PDF，其次 EPUB，再考虑 IMA 可接收或可转换的格式。
- 下载过程中支持断点续传，并校验 HTTPS、文件签名、大小和 MD5。
- 将原始文件保存在本机，不静默覆盖已有书籍。
- 通过 WorkBuddy 已连接的 `ima-mcp` 上传到指定 IMA 知识库。
- 上传前遍历知识库检查同名文件，避免误重复。
- 区分“已入库”“解析中”和“已可检索”，避免过早报告完成。
- 母版不包含 Anna's Archive Key、IMA 凭证或 COS 临时凭证。

## 工作流程

```mermaid
flowchart LR
    A[用户提出书籍请求] --> B[搜索并选择版本]
    B --> C[授权下载与文件校验]
    C --> D[保存到本地书库]
    D --> E[IMA 格式预检与查重]
    E --> F[上传并添加到知识库]
    F --> G[等待解析并验证检索]
```

## 运行要求

- WorkBuddy，并已连接可用的 `ima-mcp` 连接器。
- Python 3.10 或更高版本；核心 Python 脚本只使用标准库。
- Node.js 18 或更高版本，用于把文件流式上传到腾讯云 COS。
- Anna's Archive 会员 Fast Download API Key，由用户在本机隐藏配置。
- 可选：Calibre 的 `ebook-convert`。仅在 MOBI、AZW、AZW3、FB2、RTF 或 DJVU 需要转换为 EPUB 时使用。

项目不会自动安装 Python、Node.js、Calibre 或其他软件。

## 安装

### 方式一：下载版本包

下载 [`v1` 源码包](https://github.com/starryChenstudent/-_workbuddy-imaknowledgebase/archive/refs/tags/v1.zip)，解压后将包含 `SKILL.md` 的目录导入 WorkBuddy。

### 方式二：克隆仓库

```bash
git clone https://github.com/starryChenstudent/-_workbuddy-imaknowledgebase.git
cd ./-_workbuddy-imaknowledgebase
```

然后在 WorkBuddy 中将该目录添加为 Skill。

## 首次配置

进入 Skill 根目录后，先检查运行环境：

```bash
python3 scripts/python_runner.py runtime_check.py
python3 scripts/python_runner.py configure_key.py --check
```

如果返回 `configured: false`，在本机终端运行：

```bash
python3 scripts/python_runner.py configure_key.py
```

程序会使用隐藏输入读取 Key，并将其保存在当前用户的 `~/.config/annas-archive/api_key`。不要把 Key 发到聊天、提交到 Git，或写入公开的 Skill 包。

之后，在 WorkBuddy 连接器管理页面连接 `ima-mcp`。IMA 授权由 WorkBuddy 托管，本项目不会读取本地 IMA Client ID 或 API Key。

## 使用示例

安装并连接 `ima-mcp` 后，可以直接在 WorkBuddy 中提出请求：

```text
帮我查找并下载《书名》，然后添加到我的 IMA 知识库。
```

```text
找 ISBN 978xxxxxxxxxx 对应的中文版本，只下载到本地，不上传 IMA。
```

```text
把我有权下载的这本 EPUB 导入默认 IMA 知识库，并确认它已经可以检索。
```

默认行为是完成“搜索 → 下载 → IMA 入库 → 可检索验证”。只有明确说“只下载、不上传”时，流程才会停在本地文件。

## 项目结构

```text
.
├── SKILL.md                         # Skill 主流程与安全门禁
├── agents/openai.yaml               # WorkBuddy/Agent 展示信息
├── references/
│   ├── api.md                       # Fast Download API 说明
│   └── ima-mcp.md                   # IMA MCP 调用约定
└── scripts/
    ├── annas_archive_client.py      # 搜索、授权下载与完整性校验
    ├── configure_key.py             # 本地隐藏配置下载凭证
    ├── cos-upload.cjs               # COS 文件流上传
    ├── format_for_ima.py            # 格式准备、预检与目标配置
    ├── library_paths.py             # 本地书库路径解析
    ├── package_skill.py             # 母版/私版打包
    ├── python_runner.py             # Python 运行入口
    └── runtime_check.py             # 运行环境检查
```

## 安全与隐私

- 公共源码和母版不得包含 Anna's Archive Key。
- 不记录或展示临时下载 URL、COS 凭证、Token、知识库 ID、Media ID 或文件哈希。
- 网络下载只接受 HTTPS，不使用代理、Torrent 或绕过访问控制的方式。
- COS 上传失败时不会继续执行 IMA 入库。
- 打包或重新安装不会删除 `Desktop/library/` 中的书籍及用户配置。

更完整的执行规则请阅读 [SKILL.md](SKILL.md)。

## 版本

当前首个公开版本为 **v1**。

## 许可证

本项目采用 [MIT License](LICENSE)。第三方内容、服务和下载文件仍受其各自许可条款约束。
