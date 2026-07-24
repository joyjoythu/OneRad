# 安装部署

本页面向**评委 / 试用者**：使用离线部署包，无需从源码构建，5 步即可运行。如果你是开发者，请直接跳到 [从源码构建](#从源码构建开发者)。

## 离线部署（评委用）

### 前置条件

电脑需安装 Docker Desktop：https://www.docker.com/products/docker-desktop/

### 第一步：导入镜像（只需一次）

打开终端，进入部署包所在目录，执行：

> Windows 用户请用 **Git Bash**（右键文件夹 → Open Git Bash Here）。

```bash
docker load < autoradiomics.tar.gz
```

### 第二步：设置 API Key（二选一）

**方式一：在网页中配置（推荐，启动后操作）**

启动容器后，打开 http://localhost:8000，点击 **⚙ 设置**，在 **API Key** 栏中填入你的密钥并保存。

> 用网页配置的 Key 会持久保存，下次启动无需再次设置。

**方式二：通过环境变量设置（命令行操作）**

::: code-group

```cmd [Windows CMD]
set DEEPSEEK_API_KEY=sk-你的key
```

```powershell [Windows PowerShell]
$env:DEEPSEEK_API_KEY="sk-你的key"
```

```bash [Mac / Linux]
export DEEPSEEK_API_KEY=sk-你的key
```

:::

### 第三步：配置影像数据路径

用记事本（或任意文本编辑器）打开 `docker-compose.offline.yml`，找到这一行（默认挂载整个 D 盘）：

```yaml
- D:\你的影像数据目录（或者上一级目录）:/data/input
```

把冒号**左边**的路径改成你电脑上影像数据所在的**实际目录**，右边 `/data/input` 保持不变：

```yaml
# Windows 示例
- D:\MedicalImages:/data/input

# Mac / Linux 示例
- /home/judge/images:/data/input
```

### 第四步：启动

```bash
docker compose -f docker-compose.offline.yml up -d
```

### 第五步：使用

1. 浏览器打开 http://localhost:8000
2. 左侧点击 **+ 新建项目**
3. 点击 **浏览**，左侧位置列表会出现 **📂 /data/input**
4. 进入后选择你的影像数据目录，确认
5. 在对话中告诉 AI 你要做什么分析，例如「**开始分析**」

接下来怎么走，见 [5 分钟快速上手](/guide/quickstart)。

### 停止

```bash
docker compose -f docker-compose.offline.yml down
```

### 离线部署常见问题

**Q: 浏览器打开后页面空白或报错？**
等待 10 秒后刷新页面，容器启动需要时间。

**Q: 创建项目时提示「路径已被使用」？**
该路径已创建过项目，在左侧边栏右键删除旧项目后重新创建即可。

**Q: 文件选择器看不到我的数据？**
检查 `docker-compose.offline.yml` 中的宿主机路径是否正确。修改后重启：

```bash
docker compose -f docker-compose.offline.yml down && docker compose -f docker-compose.offline.yml up -d
```

**Q: 8000 端口被占用？**
修改 `docker-compose.offline.yml` 中 `ports` 左边的端口号（如 `"8080:8000"`），重启后用对应端口访问。

---

## 从源码构建（开发者）

适合需要修改代码或二次开发的场景。完整源码见 [GitHub 仓库](https://github.com/joyjoythu/OneRad)。

### Docker 构建

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 2. 构建镜像（首次约 5–10 分钟）
docker compose build

# 3. 启动
docker compose up -d

# 4. 访问 http://localhost:8000
```

常用命令：

| 操作 | 命令 |
|------|------|
| 停止 | `docker compose down` |
| 查看日志 | `docker compose logs -f` |
| 重建镜像 | `docker compose build --no-cache` |

数据持久化：`./data`（SQLite 数据库、配置）和 `./output`（分析报告、图表）挂载在宿主机，删除容器不丢数据。

### 本地开发

::: code-group

```bash [后端]
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
pip install -r requirements.txt
pip install --no-build-isolation pyradiomics==3.0.1
python main.py  # http://localhost:8000
```

```bash [前端]
cd frontend
npm install
npm run dev  # http://localhost:5173，自动代理 /api 到 :8000
```

:::

### CLI 模式

跳过 Web UI，直接从命令行运行分析：

```bash
python main.py --feature-csv features.csv --clinical clinical.xlsx --output-dir ./output
```

完整参数见 `python main.py --help`。

---

## 首次启动检查清单

1. ✅ 浏览器能打开 http://localhost:8000（空白等 10 秒刷新）
2. ✅ API Key 已配置（网页设置页显示「已配置」，或环境变量已设置）
3. ✅ 新建项目时能浏览到 `/data/input` 下的影像数据
4. ✅ 发送一条消息能收到 Agent 回复

全部通过后，进入 [5 分钟快速上手](/guide/quickstart)。
