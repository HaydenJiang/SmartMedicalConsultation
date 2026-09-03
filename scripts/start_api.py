"""
一键启动整合后的服务（API + 前端静态文件，单进程）。

用法：
    python scripts/start_api.py            # 直接启动（需已构建前端）
    python scripts/start_api.py --build    # 先构建前端再启动
    python scripts/start_api.py --port 9000

启动后访问 http://localhost:8000 即为完整应用（聊天界面 + API + /docs）。
"""

import sys
import argparse
import faulthandler
import subprocess
from pathlib import Path

# 项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# 原生崩溃（如访问违例）时向 stderr 打印 Python 调用栈，便于诊断。
# 背景：2026-08-08 的 arrow.dll 崩溃没有任何 traceback，只能靠 Windows 事件查看器定位。
faulthandler.enable()

from config.settings import settings  # noqa: E402


def build_frontend() -> bool:
    """构建 Vue 前端为静态文件"""
    frontend_dir = PROJECT_ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        print("[WARN] 未找到 frontend/package.json，跳过前端构建。")
        return False

    print("[BUILD] 构建前端 (npm run build) ...")
    try:
        subprocess.run(["npm", "run", "build"], cwd=str(frontend_dir), check=True)
        print("[BUILD] ✅ 前端构建完成 -> frontend/dist/")
        return True
    except FileNotFoundError:
        print("[ERROR] 未找到 npm，请先安装 Node.js (建议 18+)。")
        return False
    except subprocess.CalledProcessError:
        print("[ERROR] 前端构建失败，请查看上方 npm 输出。")
        return False


def preload_retrieval_stack() -> bool:
    """启动预热：主线程预加载嵌入检索栈（sentence_transformers/torch/pyarrow 原生依赖链 + BGE-M3）。

    背景（2026-08-08 线上 bug）：若在 uvicorn 请求工作线程中**首次** import
    sentence_transformers（连带首次加载 torch/pyarrow 原生 DLL），完整服务进程上下文
    中会发生原生访问违例（故障模块 arrow.dll，异常码 c0000005），整个进程被直接杀掉——
    无 Python 异常、try/except 拦不住。任何"知识类"提问（路由到 MedicalKnowledgeAgent）
    在该进程的第一次必然触发闪退。
    在 uvicorn.run 之前于主线程预加载即可确定性规避（已实测验证），
    同时首条知识类问题不再承担 ~10-20s 的模型加载延迟。
    """
    try:
        from src.vector_store.search import preload_embedding_stack
        preload_embedding_stack()
        print("[PRELOAD] ✅ 向量检索栈预热完成（BGE-M3 已加载，原生依赖链就绪）")
        return True
    except Exception as e:
        print(f"[PRELOAD] ⚠️ 向量检索栈预热失败: {e}")
        print("[PRELOAD]    服务仍将启动，但首个「知识类」提问可能无法正常回答；")
        print("[PRELOAD]    请检查 data/indexes/ 与 models/bge-m3 是否完整。")
        return False


def main():
    parser = argparse.ArgumentParser(description="启动整合服务（API + 前端单进程）")
    parser.add_argument("--build", action="store_true", help="启动前先构建前端")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=settings.api_port, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument("--skip-port-check", action="store_true",
                        help="跳过启动端口占用检查（不推荐，详见 config/port_check.py）")
    args = parser.parse_args()

    # 启动自检（必须最先执行，1 秒内失败）：端口若已被其他进程占用
    # （如 VS Code 端口转发、残留进程），uvicorn 仍可绑定通配地址并「看似启动成功」，
    # 但 127.0.0.1 流量会被具体地址监听劫持，服务收不到任何请求（2026-08-08 线上 bug）。
    if not args.skip_port_check:
        from config.port_check import ensure_port_free
        ensure_port_free(args.port)

    dist_dir = PROJECT_ROOT / "frontend" / "dist"

    if args.build or not (dist_dir / "index.html").exists():
        if not (dist_dir / "index.html").exists() and not args.build:
            print("[INFO] 未检测到 frontend/dist，自动构建前端 ...")
        build_frontend()

    if not (dist_dir / "index.html").exists():
        print("[WARN] frontend/dist 不存在，将以「仅 API」模式启动（访问 /docs 查看接口）。")

    # 启动预热（必须早于 uvicorn.run）：主线程预加载嵌入检索栈，
    # 修复「首条知识类提问导致进程原生崩溃」bug（详见 preload_retrieval_stack 文档）。
    # 注：--reload 模式下实际服务运行在子进程，由 src/api/main.py 的 lifespan 兜底预热。
    print("[PRELOAD] 正在预加载向量检索栈（BGE-M3 嵌入模型，首次约需 10-30s）...")
    preload_retrieval_stack()

    print("=" * 60)
    print(" 智慧问诊Agent系统 · 整合服务（单进程）")
    print("=" * 60)
    print(f"  地址: http://localhost:{args.port}")
    print(f"  界面: http://localhost:{args.port}/        （Vue 聊天界面）")
    print(f"  文档: http://localhost:{args.port}/docs    （Swagger UI）")
    print(f"  接口: http://localhost:{args.port}/api/consult")
    print("=" * 60)

    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
