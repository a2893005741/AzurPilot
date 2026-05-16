# Python 3.14 Docker 构建说明

## 问题背景

由于 Python 3.14 目前仍在开发阶段（alpha 版本），Docker Hub 上还没有官方的 `python:3.14-slim-bookworm` 镜像。

## 解决方案

本项目的 Dockerfile 采用**多阶段构建**的方式，从源码编译 Python 3.14：

### 构建流程

1. **第一阶段（python-builder）**：
   - 使用 `debian:bookworm-slim` 作为基础镜像
   - 安装编译 Python 所需的所有依赖
   - 从 python.org 下载 Python 3.14.0a7 源码
   - 使用优化选项编译 Python（`--enable-optimizations --with-lto`）
   - 将编译好的 Python 安装到 `/usr/local`

2. **第二阶段（最终镜像）**：
   - 使用干净的 `debian:bookworm-slim` 作为基础
   - 从第一阶段复制编译好的 Python
   - 安装运行时依赖和项目所需的 Python 包

### 优势

- ✅ 使用真正的 Python 3.14
- ✅ 最终镜像体积较小（不包含编译工具）
- ✅ 支持所有 Python 3.14 的新特性

### 劣势

- ⚠️ 首次构建时间较长（约 10-20 分钟，取决于 CPU 性能）
- ⚠️ 使用的是 alpha 版本，可能存在不稳定性

## 构建命令

```bash
# 基本构建
docker build -t hgjazhgj/alas:latest -f deploy/docker/Dockerfile .

# 使用代理构建
docker build \
  --build-arg HTTP_PROXY=http://proxy.example.com:8080 \
  --build-arg HTTPS_PROXY=http://proxy.example.com:8080 \
  -t hgjazhgj/alas:latest \
  -f deploy/docker/Dockerfile .

# 指定不同的 Python 3.14 版本
docker build \
  --build-arg PYTHON_VERSION=3.14.0a8 \
  -t hgjazhgj/alas:latest \
  -f deploy/docker/Dockerfile .
```

## 运行命令

```bash
docker run -v ${PWD}:/app/AzurLaneAutoScript -p 22267:22267 --name alas -it --rm hgjazhgj/alas
```

## 注意事项

1. **Python 版本更新**：
   - 当前使用 `3.14.0a7`（2024年发布的 alpha 版本）
   - 可以通过修改 `PYTHON_VERSION` 构建参数来使用更新的版本
   - 查看可用版本：https://www.python.org/downloads/source/

2. **稳定性考虑**：
   - Python 3.14 预计在 2025 年 10 月正式发布
   - 在正式版发布前，建议在生产环境中谨慎使用
   - 官方镜像发布后，可以简化 Dockerfile 直接使用 `FROM python:3.14-slim-bookworm`

3. **构建缓存**：
   - Docker 会缓存构建阶段，后续构建会更快
   - 如需重新编译 Python，使用 `docker build --no-cache`

## 未来迁移

当 Python 3.14 官方 Docker 镜像发布后，可以将 Dockerfile 简化为：

```dockerfile
FROM python:3.14-slim-bookworm

# ... 其余配置保持不变
```

这将大大减少构建时间和复杂度。
