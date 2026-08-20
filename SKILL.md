---
name: bookbridge
description: 接收用户提供的 Anna's Archive 官方记录地址或 MD5，或复用本机已缓存记录，下载用户有权获取的书籍并通过 WorkBuddy 的 ima-mcp 导入 IMA。用户提供 Anna 记录、MD5，或再次请求已保存书籍时使用。不按书名抓取 Anna HTML 搜索页，也不绕过 DDoS、登录或 CAPTCHA。
---

# BookBridge 本地智能读书助手

默认完成“缓存匹配或接收记录 → MD5 规范化 → 权利确认 → 下载 → IMA MCP 入库 → 可检索验证”。用户明确说“只下载、不上传”时才停在本地文件。多本书按顺序处理，不并行下载。

## 路径与依赖

从 `${CODEBUDDY_SKILL_DIR}` 解析脚本，不硬编码用户目录：

- 本地原书：当前用户 `Desktop/library/books/`
- Anna 客户端：`scripts/annas_archive_client.py`
- Anna 凭证配置：`scripts/configure_key.py`
- IMA 格式准备与预检：`scripts/format_for_ima.py`
- COS 流式上传：`scripts/cos-upload.cjs`

首次使用先运行环境检查：

```bash
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" runtime_check.py
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" configure_key.py --check
```

Python 脚本只使用标准库，通过 `scripts/python_runner.py` 运行。不要由 BookBridge 自动安装 Python、Node 或 Calibre。IMA MCP 上传需要 WorkBuddy 已连接 `ima-mcp`，COS 传输需要 Node.js 18+；MOBI/AZW/AZW3/FB2/RTF/DJVU 转 EPUB 才需要已有 Calibre `ebook-convert`。BookBridge v2 不需要 Agent Browser。

不要安装或调用独立 `ima-skill.zip`，也不要读取本地 IMA Client ID/API Key。IMA 授权完全由 WorkBuddy 连接器托管。Anna 凭证支持两种发行模式：母版不含 Key，首次由用户中文隐藏配置到 `~/.config/annas-archive/api_key`；私版在 `config/.env` 中预配置 Key，导入后直接使用，不再询问。该 Key 只用于选定 MD5 后的 Fast Download API，不能用于书名搜索。

用户提供的非敏感书目记录保存在当前用户 `~/.config/bookbridge/records.json`。该文件只保存书名、版本信息、记录地址和 MD5，不保存 Anna Key、下载 URL 或 IMA 凭证；不得加入 Git、Release 或 Skill 安装包。

`configure_key.py --check` 返回 `source: private_package` 时，直接继续，不要求用户输入。只有母版返回 `configured: false` 时，才提示用户“即将配置 Anna 下载凭证，请在隐藏输入框填写，内容只保存在本机”，然后运行：

```bash
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" configure_key.py
```

不要让用户把 Key 发在聊天里。配置成功后不再询问。私版中的 `.env` 是明文，只能交付给指定用户，禁止转发或上传公共位置。

## 单轮连续执行门禁

用户一次提出请求，只表示同意执行记录解析和 IMA 工作流，不自动构成对受版权保护文件的下载授权。除非缺少首次记录地址/MD5、权利依据不清、缓存版本歧义、同名文件、连接器未连接、缺少母版 Anna Key，或必须由用户决定的真实错误，否则禁止停下来等待用户说“继续”。

启动后台下载或 COS 上传后必须：

1. 保存后台任务 ID；
2. 在同一个 Agent 回合中立即调用 WorkBuddy 的“查看任务输出”/TaskOutput 工具，阻塞或每 15–30 秒轮询；
3. 返回仍在运行时，只发送简短进度更新，然后立刻再次调用任务输出工具；进度更新不是最终回复；
4. 任务退出后立即解析结果并进入下一步，不等待所谓“自动通知”；
5. 下载、预检、查重、创建媒体、COS 上传、入库和解析验证全部到达终态后，才允许给最终交付。

WorkBuddy 后台任务完成不会自动创建新的 Agent 回合。禁止说“完成后我会自动收到通知”“请稍后说继续”“继续完成”，也禁止在“正在下载”“正在上传”时结束本轮。若用户只要求下载、不上传，则至少等到文件校验完成并返回可点击路径后再结束。

## 1. 检查 ima-mcp 与选择知识库

在任何 IMA 操作前，调用 `mcp__ima-mcp__get_knowledge_base_list`：

```json
{"params":[{"limit":20,"type":"KBT_MINE_KB"}]}
```

`params` 必须是数组。若工具不存在、连接器未授权或调用失败，停止 IMA 阶段并提示用户到 WorkBuddy 的连接器管理页连接 `ima-mcp`；不要降级到本地 IMA 凭证或安装 `ima-skill`。

读取本机保存的默认知识库名称：

```bash
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" format_for_ima.py target-get
```

每次都用知识库名称在 MCP 返回结果中重新匹配 ID，禁止长期保存 ID。没有默认名称时，只展示 `basic_info.name` 和可添加权限，让用户选择；不要展示 ID。选定后保存名称：

```bash
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" format_for_ima.py target-set --name "<知识库名称>"
```

若个人列表中找不到保存的名称，再调用连接器的知识库搜索或可添加知识库列表工具，并严格按工具运行时 schema 传参；仍找不到则让用户重新选择。

## 2. 解析首次记录或复用本机缓存

Anna 的稳定 JSON API 只支持按 MD5 取得会员下载地址，不支持按书名搜索。禁止用脚本请求或解析 `/search`、切换镜像、伪装浏览器、读取 Cookie、连续重试 403，或尝试绕过 DDoS-Guard。

用户只给书名时，先查本机缓存：

```bash
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" annas_archive_client.py lookup --title "<书名>" --authors "<作者，可选>" --format "<格式，可选>"
```

- `status: found`：使用唯一缓存记录继续；
- `status: ambiguous`：只展示标题、作者、年份和格式，让用户选择，不展示内部缓存路径；
- `status: record_required`：这是一本尚未保存的新书。简洁说明“请在 Anna 网站选中具体版本后，把详情页 `/md5/` 地址或 32 位 MD5 发给我”；本轮到此等待用户，不安装浏览器插件，也不尝试远程书名搜索。

收到官方记录地址或 MD5 后规范化并写入本地缓存：

```bash
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" annas_archive_client.py record --record "<官方 /md5/ URL 或 MD5>" --title "<标题>" --authors "<作者，可选>" --publisher "<出版社，可选>" --year "<年份，可选>" --language zh --format auto --remember
```

记录地址必须是 `https://annas-archive.gl/md5/<32位MD5>` 或当前允许的官方 `tw` 域名；也可直接给 32 位 MD5。不要让用户提供 Anna Key、Cookie 或下载链接。`--format auto` 会在下载后通过文件签名识别 PDF、EPUB、DOCX、MOBI、DJVU、RTF、FB2 或 TXT；用户明确知道格式时可以指定。不同格式或版本有不同 MD5，应分别缓存。

## 3. 下载已授权版本

下载前必须记录权利依据。只有可靠信息表明作品属于公版、开放许可、官方开放获取，或用户明确说明自己对这一本作品拥有权利/下载许可时才继续。Anna 可搜索、用户有会员、学术用途或用户只说“帮我下载”均不构成授权；权利不明确时只返回书目信息和合法来源。

```bash
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" annas_archive_client.py download --record "<官方 /md5/ URL 或缓存中的 MD5>" --title "<标题>" --authors "<作者>" --year "<年份>" --format auto --rights-basis "<public-domain|open-license|user-authorization>" --confirm-quota --remember
```

大文件下载作为后台任务并按“单轮连续执行门禁”持续读取任务输出，直至进程退出。客户端校验 HTTPS、格式签名/容器、大小和 MD5，并用格式专属 `.part` 断点续传。最多重试三次，不使用代理、torrent 或未确认版本，不自动删除 `.part` 或既有书籍。只使用返回的本地 `path`，绝不展示临时下载 URL。

## 4. 准备与预检上传文件

```bash
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" format_for_ima.py prepare --file "<download path>"
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" format_for_ima.py inspect --file "<returned ima_file>"
```

第二条命令返回 `file_name`、`file_ext`、`file_size`、`media_type`、`content_type`，供 MCP 调用使用。PDF/EPUB/DOC/DOCX/TXT 直接上传；MOBI/AZW/AZW3/FB2/RTF/DJVU 转为同目录 `.ima.epub`，保留 Anna 原文件。转换失败、超限或缺少 Calibre时停止并建议改选版本。

## 5. 查重

上传前调用：

```json
{"knowledge_base_id":"<本次按名称解析出的 id>","limit":50,"cursor":"","sort_type":"UPDATE_TS_DESC_SORT_TYPE"}
```

工具为 `mcp__ima-mcp__get_knowledge_list`。按 `file_name` 对库内标题做精确比对；存在下一页时继续遍历，直到找到同名或到末页。IMA 不支持替换。同名时只问“保留两份还是取消”；取消则停止，保留两份则先把本地待上传文件改名为 `原名_YYYYMMDDHHmmss.扩展名`，重新预检并再次查重。

## 6. MCP 创建媒体与 COS 上传

调用 `mcp__ima-mcp__create_media`：

```json
{
  "content_type":"<preflight content_type>",
  "file_ext":"<preflight file_ext>",
  "file_name":"<preflight file_name>",
  "file_size":123,
  "knowledge_base_id":"<本次 id>"
}
```

禁止用 `application/octet-stream` 兜底。收到 `media_id` 与 `cos_credential` 后立即把 COS 命令作为后台任务运行，并按“单轮连续执行门禁”持续读取任务输出；参数只取自本次 MCP 响应：

```bash
node "${CODEBUDDY_SKILL_DIR}/scripts/cos-upload.cjs" --file "<本地待上传文件>" --secret-id "<secret_id>" --secret-key "<secret_key>" --token "<token>" --bucket "<bucket_name>" --region "<region>" --cos-key "<cos_key>" --content-type "<content_type>" --start-time "<start_time>" --expired-time "<expired_time>" --timeout 300000
```

不要在聊天或普通日志中复述命令及其参数。脚本使用文件流，不把整本书读进内存。COS 退出码非 0 时立即停止，禁止调用 `add_knowledge`。

## 7. 入库、解析与可检索验证

COS 成功后调用 `mcp__ima-mcp__add_knowledge`；MCP 版本只传：

```json
{
  "knowledge_base_id":"<本次 id>",
  "media_id":"<create_media media_id>",
  "duplicate_name_strategy":"DUPLICATE_NAME_STRATEGY_SAVE"
}
```

只有用户明确指定子文件夹时才增加 `folder_id`。不要传 `title`、`file_info` 或 `media_type`。

`add_knowledge` 成功不等于可检索。每 15 秒调用一次 `mcp__ima-mcp__get_knowledge_list`，最多 5 分钟：

```json
{"knowledge_base_id":"<本次 id>","limit":5,"cursor":"","sort_type":"UPDATE_TS_DESC_SORT_TYPE"}
```

匹配目标标题：`media_state=2` 且 `parse_progress=100` 才进入最终验证；随后调用 `mcp__ima-mcp__search_knowledge`：

```json
{"knowledge_base_id":"<本次 id>","query":"<书名关键词>","cursor":""}
```

搜索命中目标条目才报告“已可检索”。5 分钟未完成则报告“IMA 仍在解析”，不算失败，不重复上传。

## 8. 安全门禁与最终交付

- `create_media.file_name` 和库内标题必须等于本地待上传文件名（含扩展名），禁止翻译、缩写或静默改名。
- 上传前必须查重；IMA 不支持替换。
- COS 非零退出后绝不入库。
- 区分“已入库”“解析中”“已可检索”。
- 不向用户展示 COS 凭证、token、临时 URL、知识库 ID、media ID 或哈希。

正常最终只返回三项：

1. Anna 原始本地文件的可点击链接；
2. `已添加到 IMA 知识库「名称」`；
3. `已可检索` 或 `IMA 仍在解析`。

完整 MCP 字段与故障处理见 [ima-mcp.md](references/ima-mcp.md)。

## 打包

用 `scripts/package_skill.py` 分别打包：

```bash
# 无 Key 母版
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" package_skill.py --output "<母版.zip>"

# 从当前 Mac 钥匙串安全读取 Anna Key，生成私版；不显示 Key
python3 "${CODEBUDDY_SKILL_DIR}/scripts/python_runner.py" package_skill.py --private-from-keychain --output "<私版.zip>"
```

源码和母版不得包含 Anna Key。只有明确生成的私版可包含 `config/.env`；私版不得包含 IMA 凭证、默认知识库 ID、COS 临时凭证、桌面书籍、旧笔记、索引或 `.work`。重新安装不得删除或覆盖 `Desktop/library/` 与用户配置。
