from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://fraud:fraud@localhost:5432/fraud"

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "transactions"
    kafka_dlq_topic: str = "transactions.dlq"
    kafka_group_id: str = "fraud-consumer"

    fraud_threshold: float = 0.7

    producer_rate_per_second: float = 5.0
    producer_fraud_ratio: float = 0.05


@lru_cache
def get_settings() -> Settings:
    return Settings()
