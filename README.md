# 让果子熟（guozi-ripe）

前端 SPA（柳树画布）+ FastAPI 后端的本地单体仓库。

## 结构

- `frontend/` — 静态页与代理：`index.html`、`willow-canvas.js`、`serve.py`
- `backend/` — FastAPI 应用：`main.py`、`banned_words.txt`、`uploads/`

## 本地运行

需本机已安装 Python 3，以及 FastAPI 相关依赖（如 `fastapi`、`uvicorn`、`sqlalchemy`、`httpx` 等）。

**1. 启动后端（默认 :8100）**

```bash
cd backend
uvicorn main:app --host 127.0.0.1 --port 8100
```

**2. 启动前端代理（:8771，并把 `/api/`、`/uploads/` 转到后端）**

```bash
cd frontend
python3 serve.py
```

浏览器打开：http://127.0.0.1:8771/

## 说明

- 本地会生成 SQLite 库（如 `guozi.db`）与日志，已列入 `.gitignore`，请勿提交。
- `.env` / 密钥文件不要入库；按需在运行环境自行配置。
- 评审截图、`*.bak*` 备份与大体积参考图默认排除，以保持仓库精简。
