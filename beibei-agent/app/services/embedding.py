"""
背备不悲 · 向量化（BGE-M3）

⚠️ 硬约束：embedding 模型一旦确定**不可更换**。
不同 embedding 产出的向量空间不可比，混用会让同一个知识库的检索彻底失效。
换模型只能新建知识库、全量重新入库。

因此本模块刻意**不提供「切换模型」的能力**，只负责加载当前配置的模型。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingService:
    """BGE-M3 编码器，进程内单例、懒加载、线程安全。"""

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self._load_error: str | None = None
        self._load_seconds: float = 0.0

    # ---------------- 加载 ----------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self):
        """加载模型。首次会从 HF 下载权重（已配 hf-mirror 镜像）。"""
        if self._model is not None:
            return self._model
        if self._load_error:
            raise RuntimeError(f"向量模型加载此前失败过：{self._load_error}")

        with self._lock:
            if self._model is not None:
                return self._model

            settings = get_settings()
            started = time.time()
            try:
                from sentence_transformers import SentenceTransformer

                logger.info("正在加载向量模型 %s（device=%s）...",
                            settings.embedding_model, settings.embedding_device)
                try:
                    model = SentenceTransformer(settings.embedding_model, device=settings.embedding_device)
                except Exception as exc:  # noqa: BLE001
                    # CUDA 不可用时自动退回 CPU，而不是直接失败
                    if settings.embedding_device != "cpu":
                        logger.warning("以 %s 加载失败（%s），回退 CPU", settings.embedding_device, exc)
                        model = SentenceTransformer(settings.embedding_model, device="cpu")
                    else:
                        raise

                # 限制最大序列长度。BGE-M3 的默认是 8192，而我们的分块目标是 700 token，
                # 留到 1024 绰绰有余。不设上限的话，一旦某个分块异常长（表格/代码块没切开），
                # 同批所有文本都要 padding 到那个长度 —— CPU 上这是分钟级的代价。
                original_max = getattr(model, "max_seq_length", None)
                if original_max is None or original_max > 1024:
                    model.max_seq_length = 1024
                    logger.info("max_seq_length 从 %s 限制为 1024（分块目标 700 token）", original_max)

                # sentence-transformers 6.x 把 get_sentence_embedding_dimension
                # 改名成了 get_embedding_dimension，两个都兼容一下
                getter = getattr(model, "get_embedding_dimension", None)
                if getter is None:
                    getter = model.get_sentence_embedding_dimension
                dim = getter()
                if dim != settings.embedding_dim:
                    logger.warning(
                        "模型实际维度 %s 与配置 EMBEDDING_DIM=%s 不一致，"
                        "Milvus 集合是按配置维度建的，可能写入失败！",
                        dim, settings.embedding_dim,
                    )

                self._model = model
                self._load_seconds = time.time() - started
                logger.info("向量模型加载完成：%s (dim=%s, 用时 %.1fs)",
                            settings.embedding_model, dim, self._load_seconds)
                return model

            except Exception as exc:  # noqa: BLE001
                self._load_error = f"{type(exc).__name__}: {exc}"
                logger.error("向量模型加载失败：%s", self._load_error)
                raise

    # ---------------- 编码 ----------------

    def encode(self, texts: list[str], *, batch_size: int | None = None) -> list[list[float]]:
        """批量编码，返回归一化后的向量（BGE 系列必须归一化，COSINE 距离才正确）。"""
        if not texts:
            return []

        settings = get_settings()
        model = self.load()
        bs = batch_size or settings.embedding_batch_size

        started = time.time()
        vectors = model.encode(
            texts,
            batch_size=bs,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        elapsed = time.time() - started
        speed = len(texts) / elapsed if elapsed > 0 else 0
        logger.info("向量化 %d 条文本，用时 %.2fs（%.1f 条/秒）", len(texts), elapsed, speed)

        return [v.tolist() for v in vectors]

    def encode_one(self, text: str) -> list[float]:
        result = self.encode([text])
        return result[0] if result else []

    # ---------------- 健康检查 ----------------

    def health(self, *, quick: bool = False) -> dict[str, Any]:
        """
        健康检查。

        quick=True 时不做真实编码 —— 首页自检每次刷新都加载一遍模型太慢，
        所以未加载时只报告依赖与 CUDA 状态，真正编码留到首次向量化。
        """
        settings = get_settings()
        info: dict[str, Any] = {
            "ok": False,
            "model": settings.embedding_model,
            "configuredDim": settings.embedding_dim,
            "device": settings.embedding_device,
            "loaded": self.is_loaded,
        }
        try:
            import torch

            info["torch"] = torch.__version__
            info["cudaAvailable"] = bool(torch.cuda.is_available())
            if torch.cuda.is_available():
                info["gpu"] = torch.cuda.get_device_name(0)
                info["vramGb"] = round(
                    torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, 1)
        except Exception:  # noqa: BLE001
            pass

        if self._load_error:
            info["error"] = self._load_error
            return info

        if quick and not self.is_loaded:
            info["ok"] = True
            info["pending"] = True
            info["note"] = "依赖就绪，模型尚未加载（首次向量化时自动加载）"
            return info

        try:
            vector = self.encode_one("健康检查")
            info["ok"] = True
            info["dim"] = len(vector)
            info["loaded"] = self.is_loaded
            if self._load_seconds:
                info["loadSeconds"] = round(self._load_seconds, 1)
        except Exception as exc:  # noqa: BLE001
            info["error"] = f"{type(exc).__name__}: {exc}"

        return info


embedding_service = EmbeddingService()
