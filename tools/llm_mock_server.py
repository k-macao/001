#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAI 兼容的假大模型端点（联调 / 排障用，不参与日报生成）。

用途：把「大模型这一栏」的接线问题与供应商问题**分开**验证。真实 Key 可能因为余额、
限流、模型改名而失败，这时看不出是代码接线错了还是供应商那边的问题；把端点换成本地
假服务，就能单独回答「Key → 环境变量 → 研判引擎 → 日报栏目」这条链路通不通：

    python3 tools/llm_mock_server.py 8899 &
    OCTOPUS_LLM_API_KEY=mock OCTOPUS_LLM_BASE_URL=http://127.0.0.1:8899/v1 \\
        python3 output/pipeline.py --llm-check     # 探活
    OCTOPUS_LLM_API_KEY=mock OCTOPUS_LLM_BASE_URL=http://127.0.0.1:8899/v1 \\
        OCTOPUS_LLM_MODEL=deepseek-flash python3 output/pipeline.py --hk7-only

实现 /v1/models 与 /v1/chat/completions 两个接口：目录里只有 deepseek-flash / deepseek-v4-pro，
其他模型名一律回 400 Model Not Exist（于是候选链换名的行为也能在这里被看到）。
返回的 JSON 结构合法、数字全部取自请求里的因子块（不编造）。只监听 127.0.0.1、不出网、不写文件。
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
