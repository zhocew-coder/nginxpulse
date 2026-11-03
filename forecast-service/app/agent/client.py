"""OpenAI 兼容 Chat Completions 客户端 + 工具调用闭环（阶段五，需求 §8.1/8.3）。

安全要求：
  - API Key 仅服务端保存，**禁止发送至浏览器，禁止写入明文日志**。
  - 日志中对 Key 做脱敏处理。
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SCHEMAS, execute_tool

# 默认配置文件路径（复用 NginxPulse 现有 AI 配置）
_DEFAULT_CFG = Path(__file__).resolve().parents[3] / "configs" / "ai_config.json"


def _mask(s: Optional[str]) -> str:
    """对密钥脱敏，避免明文出现在日志中。"""
    if not s:
        return ""
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}***{s[-4:]}"


class LLMConfig:
    def __init__(self, base_url: str, api_key: str, model: str,
                 temperature: float = 0.3, max_tokens: int = 4096,
                 timeout: int = 120, max_tool_rounds: int = 6,
                 enable_thinking: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_tool_rounds = max_tool_rounds
        self.enable_thinking = enable_thinking

    def safe_dict(self) -> Dict:
        """返回脱敏后的配置（可安全输出到日志/接口）。"""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "max_tool_rounds": self.max_tool_rounds,
            "api_key": _mask(self.api_key),
            "api_key_present": bool(self.api_key),
        }


def load_llm_config(path: Optional[str] = None) -> LLMConfig:
    """从配置文件或环境变量加载 LLM 配置。

    优先级：环境变量 > configs/ai_config.json
    """
    base_url = os.getenv("LLM_BASE_URL", "")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "")

    cfg_path = Path(path) if path else _DEFAULT_CFG
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                data = json.load(f)
            llm = data.get("llm", {})
            base_url = base_url or llm.get("baseUrl", "")
            api_key = api_key or llm.get("apiKey", "")
            model = model or llm.get("model", "")
        except Exception:
            pass

    return LLMConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
        timeout=int(os.getenv("LLM_TIMEOUT", "120")),
        max_tool_rounds=int(os.getenv("LLM_MAX_TOOL_ROUNDS", "6")),
    )


def _chat_completions(cfg: LLMConfig, payload: Dict) -> Dict:
    """调用 OpenAI 兼容的 /chat/completions。"""
    url = f"{cfg.base_url}/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg.timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def run_agent(question: str, cfg: Optional[LLMConfig] = None,
              tool_call_enabled: bool = True) -> Dict[str, Any]:
    """执行一次 Agent 问答，自动完成「调用工具 → 回填 → 再调用」的闭环。

    返回 {answer, tool_calls, rounds, config(脱敏), error}
    """
    cfg = cfg or load_llm_config()
    if not cfg.api_key or not cfg.base_url:
        return {"error": "未配置 LLM（缺少 API Key 或 base_url）",
                "config": cfg.safe_dict()}

    messages: List[Dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    tool_trace: List[Dict] = []
    rounds = 0

    try:
        while rounds < cfg.max_tool_rounds:
            rounds += 1
            payload: Dict[str, Any] = {
                "model": cfg.model,
                "messages": messages,
                "temperature": cfg.temperature,
                "max_tokens": cfg.max_tokens,
                "chat_template_kwargs": {"enable_thinking": cfg.enable_thinking},
            }
            if tool_call_enabled:
                payload["tools"] = TOOL_SCHEMAS
                payload["tool_choice"] = "auto"

            resp = _chat_completions(cfg, payload)
            choice = (resp.get("choices") or [{}])[0]
            msg = choice.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                return {
                    "answer": msg.get("content", ""),
                    "tool_calls": tool_trace,
                    "rounds": rounds,
                    "config": cfg.safe_dict(),
                    "usage": resp.get("usage"),
                }

            # 执行工具并回填
            messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                result = execute_tool(name, args)
                tool_trace.append({
                    "round": rounds, "tool": name,
                    "args": args, "result_preview": _preview(result),
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        return {"error": f"工具调用轮数超过上限 {cfg.max_tool_rounds}",
                "tool_calls": tool_trace, "rounds": rounds,
                "config": cfg.safe_dict()}
    except Exception as e:
        return {"error": f"Agent 执行失败：{type(e).__name__}: {e}",
                "tool_calls": tool_trace, "rounds": rounds,
                "config": cfg.safe_dict()}


def _preview(result: Any, limit: int = 400) -> str:
    """工具结果预览（截断，避免刷屏）。"""
    try:
        s = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        s = str(result)
    return s[:limit] + ("..." if len(s) > limit else "")
