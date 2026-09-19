"""
背备不悲 · beibei-agent 全局配置

所有配置来自 beibei-agent/.env（模板见 .env.example）。
带默认值的字段保证在 .env 缺失时也能启动，便于首次运行排查问题。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

# beibei-agent 目录（app 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------- 服务 ----------------
    agent_host: str = "127.0.0.1"
    agent_port: int = 8000
    internal_token: str = "change_me"
    # API Key 的 AES 加密口令，必须与 Java 侧 beibei.security.secret 完全一致
    secret_key: str = ""
    log_level: str = "INFO"
    debug: bool = True

    # ---------------- MySQL ----------------
    mysql_host: str = "192.168.1.100"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_db: str = "beibei"

    # ---------------- Milvus ----------------
    milvus_host: str = "192.168.1.100"
    milvus_port: int = 19530
    milvus_collection_prefix: str = "bb_chunk"
    milvus_partition_prefix: str = "kb_"

    # ---------------- 向量化 ----------------
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    embedding_device: str = "cuda"
    embedding_batch_size: int = 16

    # ---------------- OCR ----------------
    ocr_lang: str = "ch"
    ocr_use_gpu: bool = False

    # ---------------- LLM ----------------
    llm_provider: str = "deepseek"
    # 无 API Key 时的演示模式：用本地 Mock 模型跑通全链路（不是假数据，
    # 而是真的从材料里抽句子出题）。配好真实 Key 后把它关掉即可。
    llm_mock: bool = False
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"

    # ---------------- ASR ----------------
    xfyun_app_id: str = ""
    xfyun_api_key: str = ""
    xfyun_api_secret: str = ""

    # ---------------- 媒体 ----------------
    ffmpeg_path: str = "ffmpeg"

    # ---------------- RAG ----------------
    rag_top_k: int = 8
    rag_hybrid_enabled: bool = True
    rag_rrf_k: int = 60
    chunk_size: int = 700
    chunk_overlap: int = 105

    # ---------------- 路径 ----------------
    upload_dir: str = "D:/beibei-data/upload"

    # ================== 派生属性 ==================

    @property
    def mysql_url(self) -> str:
        """SQLAlchemy 连接串（密码做 URL 编码，防止特殊字符炸掉连接串）。"""
        pwd = quote_plus(self.mysql_password)
        user = quote_plus(self.mysql_user)
        return (
            f"mysql+pymysql://{user}:{pwd}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}"
            f"?charset=utf8mb4"
        )

    @property
    def mysql_url_server(self) -> str:
        """不带库名的连接串，用于建库前探测。"""
        pwd = quote_plus(self.mysql_password)
        user = quote_plus(self.mysql_user)
        return (
            f"mysql+pymysql://{user}:{pwd}"
            f"@{self.mysql_host}:{self.mysql_port}/?charset=utf8mb4"
        )

    @property
    def milvus_uri(self) -> str:
        return f"http://{self.milvus_host}:{self.milvus_port}"

    @property
    def embed_model_key(self) -> str:
        """模型名归一化：BAAI/bge-m3 → bge_m3"""
        short = self.embedding_model.split("/")[-1].lower()
        return short.replace("-", "_").replace(".", "_")

    @property
    def chunk_collection(self) -> str:
        """分块向量集合名，由 embedding 模型决定（硬约束 1 的落地点）。"""
        return f"{self.milvus_collection_prefix}_{self.embed_model_key}"

    @property
    def question_collection(self) -> str:
        """题目向量集合名，用于出题查重。"""
        return f"bb_question_{self.embed_model_key}"

    def partition(self, kb_id: int) -> str:
        """知识库分区名（Milvus partition 内隔离，检索更准）。"""
        return f"{self.milvus_partition_prefix}{kb_id}"

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
