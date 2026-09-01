"""
启动端口自检（仅标准库，无项目依赖，可在任何重加载之前调用）。

背景（2026-08-08「服务显示启动成功、浏览器一直转圈、服务端 0 请求」bug）：
Windows 上若已有进程绑定 127.0.0.1:<port>（常见：VS Code 端口转发、
早前崩溃/挂起进程未释放的监听、其他开发工具），uvicorn 仍可以成功绑定
通配地址 0.0.0.0:<port> 并正常打印 "Uvicorn running" —— 但内核会把
目的地址为 127.0.0.1 的流量**优先**路由到更具体的 127.0.0.1 监听
（具体地址绑定优先于通配绑定）。结果是：浏览器（及系统代理）的所有请求
全部流入占位进程，本服务一个请求都收不到，前端无限转圈，服务端日志
Total requests 恒为 0，极难定位。

因此在 uvicorn.run 之前探测目标端口：只要 127.0.0.1:<port> 已可建立连接，
就中止启动并给出排查指引，避免「假启动」。
"""

import socket


def port_is_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    """探测 host:port 是否已有进程在接受连接（能建立 TCP 连接即为 True）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def ensure_port_free(port: int) -> None:
    """端口已被占用（127.0.0.1 可连接）时抛出 SystemExit 中止启动，并附排查指引。"""
    if not port_is_listening("127.0.0.1", port):
        return

    raise SystemExit(
        f"""
[PORT] ❌ 检测到端口 {port} 已被占用：127.0.0.1:{port} 当前正在接受连接。
        此时若强行启动会发生「静默劫持」：Windows 下已存在的具体地址监听
        （127.0.0.1:{port}）会优先于本服务的通配监听（0.0.0.0:{port}）接收
        127.0.0.1 流量，浏览器请求将全部流入占用端口的进程——服务看似
        启动成功，实际收不到任何请求，前端无限转圈。

        常见占用方与处理办法：
        1) VS Code 端口转发：打开「端口 / PORTS」面板（Ctrl+Shift+P →
           "Ports: Focus on Ports View"），找到端口 {port} → 右键
           「停止转发端口 / Stop Forwarding Port」；找不到则重启 VS Code。
        2) 早前崩溃/挂起的残留进程：
           netstat -ano | findstr :{port}   找到 PID →
           tasklist /FI "PID eq <PID>" 确认进程 → taskkill /PID <PID>
        3) 或换一个端口启动：--port {port + 1}

        确认无误仍需强行启动时，可加 --skip-port-check 跳过本检查。
"""
    )
