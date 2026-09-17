# Passagen MCP Server

[Passagen MCP Server](https://github.com/PassagenWerk/passagen-mcp-server) 将现有 Passagen
论文库提供给支持 [Model Context Protocol](https://modelcontextprotocol.io/) 的客户端
和 Agent Host。LibreChat、Claude Desktop、Cursor、VS Code/Copilot、自定义 research agent
及其他兼容 MCP 的工具都可以通过统一接口调用 Passagen 数据，让 Agent 先发现论文和
collection，再按范围读取摘要、全文 evidence、synthesis 与 research report。

服务默认只读；显式启用写能力后，可以维护 collection 和 tag、批量调整论文标签，并保存
collection Markdown 文档。它不会导入或删除论文，不会启动 processing、synthesis 或 report
generation，也不会在读取时调用 LLM。论文正文和生成内容始终被视为不可信研究数据，而不是
Agent 指令。

## 能力

- 按标题、状态、标签、venue、年份和 collection 筛选、排序和分页浏览论文，并按字段投影结果。
- 批量读取论文，或按 ID、规范化标题、DOI 和 arXiv ID 解析论文。
- 读取经过校验的 Author/Cleaned Abstract、Structured Summary、Outline 和用户笔记。
- 在限定论文或 collection 范围内检索全文 section，返回页码、excerpt 和 artifact hash。
- 浏览标签、有序 collection、最新 collection synthesis 和已有 research report。
- 可选地创建和更新 collection、逐项校验成员添加、维护 tag 和批量调整论文标签。
- 返回 citation、coverage 和 stale-source 状态，不暴露受管理 artifact 的文件系统路径。
- 通过本地 `stdio` 或带 Bearer 认证的 Streamable HTTP `/mcp` 提供同一组能力。

## 与 Passagen 配合

MCP Server 读取由以下入口维护的同一个 data directory：

- [Passagen Web](https://github.com/PassagenWerk/passagen-web)：在浏览器中导入、处理、阅读和整理
  论文，并生成 collection research 内容。
- [Passagen CLI](https://github.com/PassagenWerk/passagen-cli)：批量导入和处理论文，维护数据库、
  配置和备份。
- [Passagen Core](https://github.com/PassagenWerk/passagen-core)：三者共享的数据模型、artifact
  校验和查询逻辑。

MCP Server 不初始化或迁移数据库。首次使用前，先通过 Web 或 CLI 创建并处理论文库。
MCP Server `0.3.x` 需要 Passagen Core `0.9.x` 和 Schema version 13；升级时应保持 Web、CLI、
Core 和 MCP Server 的兼容 release line。

## 快速开始

### Python 安装

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。从发布包安装：

```bash
uv tool install passagen-mcp-server
```

本地 MCP Host 可以直接启动 `stdio` transport：

```bash
passagen-mcp stdio --data-dir /absolute/path/to/passagen-library
```

客户端配置示例：

```json
{
  "mcpServers": {
    "passagen": {
      "command": "passagen-mcp",
      "args": [
        "stdio",
        "--data-dir",
        "/absolute/path/to/passagen-library"
      ]
    }
  }
}
```

从源码运行时，将 `passagen-core` 与本仓库放在同一父目录：

```bash
git clone https://github.com/PassagenWerk/passagen-core.git
git clone https://github.com/PassagenWerk/passagen-mcp-server.git
cd passagen-mcp-server
uv sync --frozen
uv run passagen-mcp stdio --data-dir ../passagen-cli/data
```

### Streamable HTTP

只在本机使用时：

```bash
passagen-mcp serve \
  --data-dir /absolute/path/to/passagen-library \
  --host 127.0.0.1 \
  --port 8766
```

客户端连接 `http://127.0.0.1:8766/mcp`。监听局域网或容器网络地址时必须设置 Bearer token；
监听 wildcard address 时还必须显式允许客户端发送的 Host：

```bash
export PASSAGEN_MCP_TOKEN="$(openssl rand -hex 32)"
passagen-mcp serve \
  --data-dir /absolute/path/to/passagen-library \
  --host 0.0.0.0 \
  --port 8766 \
  --allow-host mcp.example.internal
```

客户端请求需要包含：

```text
Authorization: Bearer <PASSAGEN_MCP_TOKEN>
```

`--allow-origin` 仅用于确实从浏览器 origin 直接访问 `/mcp` 的客户端；它必须与浏览器地址栏中
的 protocol、host 和 port 完全一致。不要将无 TLS 的 HTTP endpoint 暴露到不可信网络。

### Collection 写能力

默认不会注册任何写工具。可信的本地 `stdio` 客户端可以显式启用：

```bash
passagen-mcp stdio \
  --data-dir /absolute/path/to/passagen-library \
  --allow-write
```

HTTP 写模式始终要求 Bearer token，包括仅监听 loopback 时：

```bash
export PASSAGEN_MCP_TOKEN="$(openssl rand -hex 32)"
passagen-mcp serve \
  --data-dir /absolute/path/to/passagen-library \
  --host 127.0.0.1 \
  --allow-write
```

写能力只维护 collection、tag、论文的 tag 关联和外部 Markdown 文档，不会导入或删除论文、
修改 PDF/生成内容或生成研究产物。建议 Agent 在写入前确认 collection、tag 和 paper IDs，并在
批量写入前优先使用 `dry_run=true`。

### Docker

MCP Server 作为独立 companion image 发布，不包含论文、artifact、配置或 secret：

```bash
docker run --rm \
  -p 127.0.0.1:8766:8766 \
  -e PASSAGEN_MCP_TOKEN="$PASSAGEN_MCP_TOKEN" \
  -v /absolute/path/to/passagen-library:/data:ro \
  docker.io/sycstudio/passagen-mcp-server:0.3.0 \
  passagen-mcp serve \
  --data-dir /data \
  --host 0.0.0.0 \
  --port 8766 \
  --allow-host localhost \
  --allow-host 127.0.0.1
```

如果 SQLite 因部署环境需要创建 shared-memory/journal 文件而无法在只读 mount 上打开，请先
确认没有迁移或写任务，再将 volume 改为读写挂载。启用 `--allow-write` 时必须使用读写挂载；
默认命令仍然只注册读取能力。不同 Agent Host 的连接方式以各自 MCP 文档为准：本地客户端使用
`stdio`，跨进程或容器客户端使用 Streamable HTTP `/mcp`、Bearer header 和受限网络。

## Agent 工作流

推荐让 Agent 按以下顺序调用，避免把整个论文库一次性放入上下文：

1. 使用 `list_tags`、`list_collections` 或带过滤条件的 `list_papers` 发现并缩小范围。
2. 使用 `get_paper_context` 或 `get_collection_context` 读取结构化上下文。
3. 使用带 `paper_ids` 或 `collection_id` 的 `search_paper_sections` 查找可定位到页码的 evidence。
4. 需要已有研究产物时，使用 `list_collection_reports` 和 `get_collection_report`。
5. 根据响应中的 citation、page 和 artifact hash 验证最终结论。

所有列表使用显式 `offset` 和 `limit`，并返回 `returned`、`total`、`next_offset` 和
`has_more`。`list_papers` 默认只返回 `id`、`title`、`year` 和 `tags`；需要作者、collection、
artifact 状态或资源 URI 时，通过 `fields` 明确请求。调用方可以改变 `limit` 后从任意 offset
继续，不需要保存与过滤条件绑定的游标。

`search_paper_sections` 是 bounded English lexical search。单次 scope 最多 100 篇论文，显式
`paper_ids` 最多 50 个；更大的库应按 collection 或 paper ID 批次检索。该边界使 MCP Server
能够安全嵌入包含网页搜索、代码执行、写作、任务规划等其他工具的 Agent 工作流，而不让一次
检索无界占用内存或上下文。

## MCP 接口

Tools：

| Tool | 用途 |
|---|---|
| `list_papers` | 筛选、排序和分页列出紧凑论文元数据。 |
| `get_papers` | 按 ID 批量读取可选字段，并单独返回未命中的 ID。 |
| `resolve_papers` | 按 ID、标题、DOI 或 arXiv ID 批量解析论文。 |
| `get_paper_context` | 读取论文 metadata、组织关系及选定内容。 |
| `get_paper_citation` | 获取并持久化 BibTeX；可按需强制刷新 DOI/local metadata。 |
| `search_paper_sections` | 在限定 scope 中检索带页码的全文 section。 |
| `list_tags` | 列出标签及论文使用数。 |
| `list_collections` | 列出 collection 及论文数。 |
| `get_collection_context` | 按需分页读取有序论文和最新 persisted synthesis。 |
| `list_collection_reports` | 列出已有 report 及 lifecycle/stale 状态。 |
| `get_collection_report` | 读取一个已有 report、citation 和安全 artifact metadata。 |
| `create_collection` | 创建空 collection；仅在 `--allow-write` 模式提供。 |
| `update_collection` | 更新 collection 名称或 description；仅在 `--allow-write` 模式提供。 |
| `add_papers_to_collection` | 逐项校验并追加最多 100 篇论文，支持 dry-run/atomic；仅在写模式提供。 |
| `create_tag` | 创建 tag；仅在 `--allow-write` 模式提供。 |
| `update_tag` | 修改 tag 名称或颜色；仅在 `--allow-write` 模式提供。 |
| `update_paper_tags` | 批量添加或移除论文 tag，支持 dry-run；仅在写模式提供。 |
| `list_collection_documents` | 分页列出手工与生成型文档；paper 快照和成员差异按需返回。 |
| `get_collection_document` | 读取一个手工或已完成的生成型 collection 文档。 |
| `create_collection_document` | 添加 Markdown 文档；仅在 `--allow-write` 模式提供，可用 `external_id` 安全重试。 |

Resource templates：

```text
passagen://papers/{paper_id}
passagen://papers/{paper_id}/abstract
passagen://papers/{paper_id}/summary
passagen://papers/{paper_id}/outline
passagen://papers/{paper_id}/sections/{ordinal}
passagen://collections/{collection_id}
passagen://collections/{collection_id}/synthesis
passagen://collections/{collection_id}/reports/{report_id}
passagen://collections/{collection_id}/documents/{document_id}
```

Collection 没有 synthesis/report 时会返回明确的 unavailable/空列表状态，而不会隐式生成内容。

## 验证与排错

健康检查：

```bash
curl http://127.0.0.1:8766/health
```

使用不依赖浏览器的 MCP Inspector CLI：

```bash
npx --yes @modelcontextprotocol/inspector --cli \
  --server-url http://127.0.0.1:8766/mcp \
  --transport http \
  --method tools/list \
  --strict \
  --header "Authorization: Bearer $PASSAGEN_MCP_TOKEN"
```

常见错误：

- `401`：Bearer token 缺失或与服务进程启动时读取的值不同。
- `421`：请求的 HTTP Host 不在 `--allow-host` 中。
- `Search scope has ... papers`：先通过 collection 或 paper IDs 缩小全文检索范围。
- synthesis/report 为空：先在 Passagen Web 或 CLI 中生成对应的 collection research 内容。

## 开发

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run basedpyright
uv run pytest
uv build
```

构建本地镜像需要相邻 Core checkout：

```bash
docker build \
  --build-context passagen-core=../passagen-core \
  -t passagen-mcp-server:local .
```

## 许可证

[GNU Affero General Public License v3.0](LICENSE)，SPDX 标识为 `AGPL-3.0-only`。
