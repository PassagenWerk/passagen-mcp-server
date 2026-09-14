# LibreChat 部署

LibreChat 推荐通过 Streamable HTTP 连接 Passagen MCP Server。`stdio` 仅适合 LibreChat 能在
同一主机启动进程并访问相同 data directory 的部署；Docker 中推荐独立 companion container。

## Docker Network

直接使用发布镜像，或从本仓库和相邻 Core checkout 构建：

```bash
docker pull docker.io/sycstudio/passagen-mcp-server:0.1.0
```

```bash
docker build \
  --build-context passagen-core=../passagen-core \
  -t passagen-mcp-server:local .
```

将 MCP 与 LibreChat 放在同一私有 Docker network，并挂载 Web/CLI 使用的完整 data directory。
优先使用只读 mount；SQLite 在部分 storage driver 上可能需要 shared-memory/journal 文件，此时
需验证版本不会执行迁移或写任务后再改为普通共享挂载。

```yaml
services:
  passagen-mcp:
    image: docker.io/sycstudio/passagen-mcp-server:0.1.0
    restart: unless-stopped
    environment:
      PASSAGEN_MCP_TOKEN: ${PASSAGEN_MCP_TOKEN:?set PASSAGEN_MCP_TOKEN}
    volumes:
      - /srv/passagen/data:/data:ro
    networks:
      - librechat

networks:
  librechat:
    external: true
```

镜像默认监听 `0.0.0.0:8766` 并允许 Host `passagen-mcp`。LibreChat 共享该 network 时无需向
宿主机发布端口，也不应公开 GROBID 或 MCP 的明文 HTTP 端口。

## LibreChat Configuration

在 `librechat.yaml` 中允许准确的私有地址并声明 server：

```yaml
mcpSettings:
  allowedAddresses:
    - passagen-mcp:8766

mcpServers:
  passagen:
    title: Passagen Library
    description: Search and read papers managed by Passagen
    type: streamable-http
    url: http://passagen-mcp:8766/mcp
    headers:
      Authorization: Bearer ${PASSAGEN_MCP_TOKEN}
    requiresOAuth: false
    timeout: 60000
    initTimeout: 15000
    serverInstructions: true
```

`allowedAddresses` 使用 `host:port`，不包含 protocol 或 `/mcp`。如果部署已有
`mcpSettings.allowedDomains` 严格白名单，还必须加入 `http://passagen-mcp:8766`。修改后重启
LibreChat。Bearer token 必须以同一个环境变量注入两个容器，不要提交到仓库。

## Agent 工作流

LibreChat 可以先使用 `list_tags`、`list_collections` 和 `list_papers` 缩小研究范围，再用
`get_paper_context`、`search_paper_sections` 获取结构化上下文和带页码 evidence。已有 collection
research 可以通过 `get_collection_context`、`list_collection_reports` 和
`get_collection_report` 读取。

这些工具可与 LibreChat 中的网页搜索、代码执行、文件处理、规划和写作工具组合。Passagen 仅
作为只读、可引用的研究来源，不启动 synthesis/report generation，也不调用 LLM。响应包含
source-staleness reasons 和安全 artifact metadata，但不暴露受管路径或内部错误详情。

## Host Deployment

Passagen MCP 运行在 Docker host 时，应绑定 LibreChat container 可达的地址，并通过
`--allow-host` 允许 MCP URL 中的主机名。Linux 上使用 `host.docker.internal` 时，LibreChat
service 可能还需要 `extra_hosts: ["host.docker.internal:host-gateway"]`。

出现连接问题时，先从 LibreChat API container 请求 `http://<mcp-host>:8766/health`，再检查：

- `401`：`Authorization` header 必须是 `Bearer <PASSAGEN_MCP_TOKEN>`，并设置
  `requiresOAuth: false`。
- `421`：MCP URL 的 Host 未加入 Passagen MCP `--allow-host`。
- `domain is not in the allowed domains list`：补充 LibreChat `allowedAddresses`；存在严格
  `allowedDomains` 时也加入准确 protocol/host/port。
- `Search scope has ... papers`：通过 collection 或最多 50 个 paper IDs 分批检索。

不要将明文 HTTP endpoint 暴露到不可信网络。远程部署应使用 TLS reverse proxy 和适当的访问
控制；内置静态 Bearer token 面向可信 service-to-service 部署，不能替代 user-scoped OAuth。
