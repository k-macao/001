#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时：OpenAI 兼容的假大模型端点（只为验证 pipeline 的接线，验证完删除）。

用途：真实 DeepSeek Key 目前返回 402（余额），无法用来证明「Key → 环境变量 → 研判 → 日报栏目」
这条链路是通的。本服务在 127.0.0.1 上实现 /v1/models 与 /v1/chat/completions 两个接口，
返回结构合法的 JSON（数字全部取自请求里的探活/预测因子块，不编造），于是可以在 CI 里跑：
    OCTOPUS_LLM_BASE_URL=http://127.0.0.1:8899/v1 python3 output/pipeline.py --hk7-only
    OCTOPUS_LLM_BASE_URL=http://127.0.0.1:8899/v1 python3 output/pipeline.py --no-push
只在本机回环，不出网，不写任何文件。
"""
from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = ["deepseek-flash", "deepseek-v4-pro"]


def _codes(payload):
    """从请求提示词里取出要覆盖的代码（探活样本 / 真实因子块都适用）。"""
    text = "".join(str(m.get("content") or "") for m in payload.get("messages") or [])
    return sorted(set(re.findall(r'"code"\s*:\s*"(\^[A-Z]+)"', text))) or ["^HSI"]


def _answer(payload):
    model = str(payload.get("model") or "")
    if model not in MODELS:                    # 让候选链真的有机会换名字（真实链路行为）
        return {"error": {"message": f"Model Not Exist: {model}", "type": "invalid_request_error"}}
    targets = [{"code": c, "p_up": 0.57, "summary": "假端点：接口联调样本，非真实研判",
                "drivers": ["假端点固定值"], "risks": ["假端点固定值"],
                "support": None, "resistance": None} for c in _codes(payload)]
    return {"id": "mock", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant",
                         "content": json.dumps({"targets": targets,
                                                "cross_note": "假端点：接口联调样本"},
                                               ensure_ascii=False)},
                         "finish_reason": "stop"}]}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                            # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._send(200, {"object": "list",
                             "data": [{"id": m, "object": "model", "owned_by": "mock"}
                                      for m in MODELS]})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):                                           # noqa: N802
        if not self.path.endswith("/chat/completions"):
            self._send(404, {"error": {"message": "not found"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8", "replace") or "{}")
        except ValueError:
            payload = {}
        answer = _answer(payload)
        self._send(400 if "error" in answer else 200, answer)

    def log_message(self, *args):                                # 安静运行
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
