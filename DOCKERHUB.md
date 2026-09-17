[Passagen MCP Server](https://github.com/PassagenWerk/passagen-mcp-server) 将现有 Passagen 论文库
提供给支持 Model Context Protocol 的客户端和 Agent Host。它支持字段投影的论文发现、稳定的
offset 分页、批量论文解析、论文上下文、带页码的全文检索、引用、集合、标签、synthesis、
research report 和 collection document。

服务默认只读。可信部署可以启用受限的组织写入，用于维护集合、标签、论文标签关联和 Markdown
文档。它不会导入或删除论文，不会运行 processing，也不会生成研究 artifact。

## 快速开始

`0.3` 镜像要求论文库使用 Passagen Core `0.9` 和 Schema version 13。

```bash
export PASSAGEN_MCP_TOKEN="$(openssl rand -hex 32)"

docker run --rm \
  -p 127.0.0.1:8766:8766 \
  -e PASSAGEN_MCP_TOKEN="$PASSAGEN_MCP_TOKEN" \
  -v /absolute/path/to/passagen-library:/data:ro \
  docker.io/sycstudio/passagen-mcp-server:0.3.1 \
  passagen-mcp serve \
  --data-dir /data \
  --host 0.0.0.0 \
  --port 8766 \
  --allow-host localhost \
  --allow-host 127.0.0.1
```

客户端连接 `http://127.0.0.1:8766/mcp`，并发送：

```text
Authorization: Bearer <PASSAGEN_MCP_TOKEN>
```

不要将内置的明文 HTTP endpoint 暴露到不可信网络。远程访问应使用 TLS reverse proxy。

## 可选写入

在服务命令中加入 `--allow-write`，并以读写方式挂载 `/data`。HTTP 写模式始终要求 Bearer
token。不要为不可信客户端启用写入。

## 镜像标签

- `0.3.1`：固定版本
- `0.3`：当前 `0.3` 系列版本
- `latest`：最新稳定版本

支持平台：

- `linux/amd64`
- `linux/arm64`

## 健康检查

```bash
curl http://127.0.0.1:8766/health
```

## 文档

- [仓库与完整使用指南](https://github.com/PassagenWerk/passagen-mcp-server)
- [LibreChat 部署](https://github.com/PassagenWerk/passagen-mcp-server/blob/main/docs/librechat.md)
- [Passagen Web](https://github.com/PassagenWerk/passagen-web)

Passagen MCP Server 使用 GNU AGPL-3.0-only 许可证。
