"""
背备不悲 · 大模型客户端

设计要点：
  1. 统一走 **OpenAI 兼容协议**，换厂商基本只改 base_url（DeepSeek/通义/智谱/月之暗面都兼容）
  2. 厂商配置以 MySQL 的 bb_ai_provider 为准，bb_model_route 决定「哪个任务用哪个模型」
  3. 每次调用写 bb_ai_call_log，记录 token 与估算费用
  4. JSON 输出带重试与容错解析（LLM 偶尔会包 markdown 代码块或加前言）

⚠️ embedding 模型不在这里 —— 它是本地 BGE-M3，与 LLM 厂商完全解耦（硬约束 1）。
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.core.logging import get_logger
from app.db.mysql import get_engine

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
#  数据结构
# ---------------------------------------------------------------------------

@dataclass
class Provider:
    """一个可用的模型厂商配置。"""

    id: int
    name: str
    vendor: str
    protocol: str
    base_url: str
    model: str
    api_key: str
    extra_params: dict[str, Any] = field(default_factory=dict)

    @property
    def chat_url(self) -> str:
        base = self.base_url.rstrip("/")
        # DeepSeek 同时支持带 /v1 和不带；统一补上 /v1 更通用
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/v1/chat/completions"


@dataclass
class LlmResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    provider_id: int
    vendor: str
    model: str
    retry_times: int = 0


class LlmError(RuntimeError):
    """LLM 调用失败。"""


# ---------------------------------------------------------------------------
#  客户端
# ---------------------------------------------------------------------------

class LlmClient:
    """
    轻量 LLM 客户端。刻意不引入 openai SDK —— 直接 httpx 调 HTTP，
    依赖更少，也更容易看清请求到底发了什么。
    """

    def __init__(self) -> None:
        self._provider_cache: dict[str, Provider] = {}
        self._client = httpx.Client(timeout=httpx.Timeout(180.0, connect=15.0))

    # ---------------- 厂商解析 ----------------

    def resolve_provider(self, task_type: str) -> Provider:
        """
        按任务类型找模型：bb_model_route 指定 → 该能力的 is_active → 优先级最高的。
        全程查不到就退回 .env 里的 DeepSeek 配置。
        开启 LLM_MOCK 时直接返回本地 Mock 模型。
        """
        cache_key = task_type or ""
        if cache_key in self._provider_cache:
            return self._provider_cache[cache_key]

        settings = get_settings()
        if settings.llm_mock:
            provider = self._mock_provider()
        else:
            provider = self._from_route(task_type) or self._from_active() or self._from_env()
        self._provider_cache[cache_key] = provider
        logger.debug("任务 %s 使用模型 %s/%s", task_type, provider.vendor, provider.model)
        return provider

    @staticmethod
    def _mock_provider() -> Provider:
        return Provider(
            id=-1, name="Mock 演示模式", vendor="mock", protocol="mock",
            base_url="", model="mock-llm", api_key="mock",
            extra_params={"temperature": 0.0, "max_tokens": 8192},
        )

    def _row_to_provider(self, row: Any) -> Provider:
        extra: dict[str, Any] = {}
        if row[6]:
            try:
                extra = json.loads(row[6]) if isinstance(row[6], str) else dict(row[6])
            except (TypeError, ValueError):
                extra = {}
        return Provider(
            id=int(row[0]), name=row[1], vendor=row[2], protocol=row[3],
            base_url=row[4] or "", model=row[5] or "", api_key=row[7] or "",
            extra_params=extra,
        )

    _PROVIDER_COLUMNS = (
        "SELECT p.id, p.name, p.vendor, p.protocol, p.base_url, p.model, "
        "       p.extra_params, %s AS api_key "
        "FROM bb_ai_provider p"
    )

    def _api_key_expr(self) -> str:
        """
        取 API Key。运行时真值在数据库里是 AES 加密的（由 Java 侧加密），
        Python 侧解不开，所以这里的策略是：
          - 数据库里存的是明文（本地自用场景，界面上直接填）→ 直接用
          - 解不开/为空 → 回退到 .env 的 DEEPSEEK_API_KEY
        后续要做真加密时，把解密逻辑放到这里即可。
        """
        return "p.api_key_enc"

    def _from_route(self, task_type: str) -> Provider | None:
        if not task_type:
            return None
        sql = (
            self._PROVIDER_COLUMNS % self._api_key_expr()
            + " JOIN bb_model_route r ON r.provider_id = p.id "
              "WHERE r.task_type = :task AND p.enabled = 1 LIMIT 1"
        )
        return self._query_provider(sql, {"task": task_type})

    def _from_active(self) -> Provider | None:
        sql = (
            self._PROVIDER_COLUMNS % self._api_key_expr()
            + " WHERE p.enabled = 1 AND p.is_active = 1 "
              "  AND p.capability LIKE '%CHAT%' "
              "ORDER BY p.priority ASC LIMIT 1"
        )
        return self._query_provider(sql, {})

    def _query_provider(self, sql: str, params: dict[str, Any]) -> Provider | None:
        try:
            with get_engine().connect() as conn:
                row = conn.execute(text(sql), params).fetchone()
                if row is None:
                    return None
                provider = self._row_to_provider(row)
                if not provider.api_key:
                    return None
                # 数据库里是 AES 加密的，这里解开；解不开会原样返回（兼容明文）
                from app.core.crypto import decrypt
                provider.api_key = decrypt(provider.api_key, get_settings().secret_key)
                return provider
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取 AI 厂商配置失败：%s", exc)
            return None

    def _from_env(self) -> Provider:
        settings = get_settings()
        if not settings.deepseek_api_key:
            raise LlmError(
                "没有可用的大模型配置。请在「设置 → AI 配置」里填写 API Key，"
                "或在 beibei-agent/.env 里设置 DEEPSEEK_API_KEY"
            )
        return Provider(
            id=0, name="DeepSeek（.env 兜底）", vendor="deepseek",
            protocol="openai-compatible",
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            extra_params={"temperature": 0.7, "max_tokens": 8192},
        )

    # ---------------- Mock 模式 ----------------

    def _mock_chat(
        self, provider: Provider, messages: list[dict[str, str]],
        task_type: str, biz_type: str, biz_id: int,
    ) -> LlmResult:
        from app.services.mock_llm import mock_completion

        started = time.time()
        content = mock_completion(task_type, messages)
        latency = int((time.time() - started) * 1000)

        # 粗略估 token，让成本统计面板有数据可看
        prompt_tokens = sum(len(m.get("content") or "") for m in messages) // 2
        completion_tokens = len(content) // 2

        self._log_call(
            task_type=task_type, provider=provider, biz_type=biz_type, biz_id=biz_id,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            latency_ms=latency, success=True, retry_times=0,
            request_preview=(messages[-1].get("content", "")[:1900] if messages else ""),
            response_preview=content[:1900],
        )
        return LlmResult(
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency,
            provider_id=provider.id,
            vendor=provider.vendor,
            model=provider.model,
            retry_times=0,
        )

    # ---------------- 对话 ----------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        task_type: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        max_retry: int = 3,
        biz_type: str = "",
        biz_id: int = 0,
    ) -> LlmResult:
        provider = self.resolve_provider(task_type)

        # Mock 模式：不发网络请求，本地生成结构化结果
        if provider.vendor == "mock":
            return self._mock_chat(provider, messages, task_type, biz_type, biz_id)

        extra = provider.extra_params or {}

        body: dict[str, Any] = {
            "model": provider.model,
            "messages": messages,
            "temperature": temperature if temperature is not None
            else float(extra.get("temperature", 0.7)),
            "max_tokens": max_tokens if max_tokens is not None
            else int(extra.get("max_tokens", 8192)),
            "stream": False,
        }
        if json_mode and provider.vendor in ("deepseek", "openai", "qwen", "zhipu", "moonshot"):
            # DeepSeek / OpenAI 系支持 response_format
            body["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(1, max_retry + 1):
            started = time.time()
            try:
                resp = self._client.post(provider.chat_url, json=body, headers=headers)
                latency = int((time.time() - started) * 1000)

                if resp.status_code != 200:
                    snippet = resp.text[:300]
                    raise LlmError(f"HTTP {resp.status_code}: {snippet}")

                payload = resp.json()
                content = payload["choices"][0]["message"]["content"] or ""
                usage = payload.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens", 0))
                completion_tokens = int(usage.get("completion_tokens", 0))

                self._log_call(
                    task_type=task_type, provider=provider, biz_type=biz_type, biz_id=biz_id,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    latency_ms=latency, success=True, retry_times=attempt - 1,
                    request_preview=messages[-1].get("content", "")[:1900] if messages else "",
                    response_preview=content[:1900],
                )
                return LlmResult(
                    content=content,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    latency_ms=latency,
                    provider_id=provider.id,
                    vendor=provider.vendor,
                    model=provider.model,
                    retry_times=attempt - 1,
                )

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                latency = int((time.time() - started) * 1000)
                logger.warning("LLM 调用失败（第 %d/%d 次）: %s", attempt, max_retry, exc)
                self._log_call(
                    task_type=task_type, provider=provider, biz_type=biz_type, biz_id=biz_id,
                    prompt_tokens=0, completion_tokens=0, latency_ms=latency,
                    success=False, retry_times=attempt - 1,
                    error_msg=str(exc)[:900], request_preview="", response_preview="",
                )
                if attempt < max_retry:
                    time.sleep(min(2 ** attempt, 8))

        raise LlmError(f"LLM 调用失败（已重试 {max_retry} 次）：{last_error}")

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        task_type: str = "",
        biz_type: str = "",
        biz_id: int = 0,
        max_parse_retry: int = 2,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], LlmResult]:
        """
        要求 LLM 输出 JSON 并解析。解析失败会把错误回喂让它重出，最多 max_parse_retry 次。
        """
        convo = list(messages)
        last_text = ""
        for attempt in range(max_parse_retry + 1):
            result = self.chat(convo, task_type=task_type, json_mode=True,
                               biz_type=biz_type, biz_id=biz_id, **kwargs)
            last_text = result.content
            parsed = extract_json(result.content)
            if parsed is not None:
                return parsed, result

            logger.warning("LLM 返回的不是合法 JSON（第 %d 次），回喂纠错", attempt + 1)
            convo = list(messages) + [
                {"role": "assistant", "content": result.content[:2000]},
                {"role": "user", "content":
                    "你上一次的输出不是合法 JSON，无法解析。请严格只输出一个 JSON 对象，"
                    "不要任何解释文字，不要 markdown 代码块。"},
            ]

        raise LlmError(f"LLM 连续 {max_parse_retry + 1} 次未返回合法 JSON，最后输出片段：{last_text[:300]}")

    # ---------------- 日志 ----------------

    def _log_call(
        self, *, task_type: str, provider: Provider, biz_type: str, biz_id: int,
        prompt_tokens: int, completion_tokens: int, latency_ms: int,
        success: bool, retry_times: int,
        request_preview: str, response_preview: str, error_msg: str = "",
    ) -> None:
        cost = self._estimate_cost(provider, prompt_tokens, completion_tokens)
        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO bb_ai_call_log "
                        "(task_type, provider_id, vendor, model, biz_type, biz_id, "
                        " prompt_tokens, completion_tokens, total_tokens, cost, latency_ms, "
                        " success, retry_times, error_msg, request_preview, response_preview) "
                        "VALUES (:task_type, :provider_id, :vendor, :model, :biz_type, :biz_id, "
                        " :pt, :ct, :tt, :cost, :latency, :success, :retry, :err, :req, :resp)"
                    ),
                    {
                        "task_type": task_type, "provider_id": provider.id,
                        "vendor": provider.vendor, "model": provider.model,
                        "biz_type": biz_type, "biz_id": biz_id,
                        "pt": prompt_tokens, "ct": completion_tokens,
                        "tt": prompt_tokens + completion_tokens, "cost": cost,
                        "latency": latency_ms, "success": 1 if success else 0,
                        "retry": retry_times, "err": error_msg[:900],
                        "req": request_preview, "resp": response_preview,
                    },
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("写调用日志失败（不影响主流程）：%s", exc)

    @staticmethod
    def _estimate_cost(provider: Provider, prompt_tokens: int, completion_tokens: int) -> float:
        """
        估算费用（元）。单价从 extra_params 里读，单位「元 / 百万 token」。
        没配单价就记 0，不影响功能。
        """
        extra = provider.extra_params or {}
        price_in = float(extra.get("price_in", 0) or 0)
        price_out = float(extra.get("price_out", 0) or 0)
        if price_in == 0 and price_out == 0:
            return 0.0
        return round(prompt_tokens / 1_000_000 * price_in
                     + completion_tokens / 1_000_000 * price_out, 6)

    def clear_cache(self) -> None:
        self._provider_cache.clear()


# ---------------------------------------------------------------------------
#  工具
# ---------------------------------------------------------------------------

_CODE_FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*|\s*```\s*$")


def extract_json(raw: str) -> dict[str, Any] | None:
    """
    从 LLM 输出里尽力抠出 JSON 对象。

    要处理三种常见污染：
      1. 包了 ```json ... ``` 代码块
      2. 前后有解释性文字
      3. 末尾多了逗号（非严格 JSON）
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # 1) 去掉代码块围栏
    fenced = re.search(r"```(?:json|JSON)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    else:
        text = _CODE_FENCE.sub("", text).strip()

    # 2) 直接尝试
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # 3) 截取第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start:end + 1]
        for fix in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                obj = json.loads(fix)
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                continue

    return None


llm_client = LlmClient()
