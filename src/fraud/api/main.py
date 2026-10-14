from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from fraud.config import get_settings
from fraud.repository import PostgresRepository, Repository
from fraud.schemas import ScoreResult, Transaction
from fraud.scoring import ScoringEngine
from fraud.service import score_only


def get_repository(request: Request) -> Repository:
    return request.app.state.repo


def get_engine(request: Request) -> ScoringEngine:
    return request.app.state.engine


def create_app(repo: Repository | None = None, engine: ScoringEngine | None = None) -> FastAPI:
    """App factory. Passing `repo` skips the Postgres pool (used by tests)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = get_settings()
        owned: PostgresRepository | None = None
        if repo is None:
            owned = PostgresRepository(settings.database_url)
            owned.open()
        app.state.repo = repo or owned
        app.state.engine = engine or ScoringEngine(settings.fraud_threshold)
        yield
        if owned is not None:
            owned.close()

    app = FastAPI(
        title="Fraud Detection API",
        version="1.0.0",
        description="Real-time scoring and inspection of streamed transactions.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health(repo: Repository = Depends(get_repository)) -> dict[str, str]:
        if not repo.ping():
            raise HTTPException(status_code=503, detail="database unavailable")
        return {"status": "ok"}

    @app.post("/v1/score", response_model=ScoreResult)
    def score(
        tx: Transaction,
        repo: Repository = Depends(get_repository),
        engine: ScoringEngine = Depends(get_engine),
    ) -> ScoreResult:
        return score_only(tx, repo, engine)

    @app.get("/v1/transactions/flagged")
    def flagged(
        limit: int = Query(50, ge=1, le=500),
        repo: Repository = Depends(get_repository),
    ) -> list[dict[str, Any]]:
        return repo.list_flagged(limit)

    @app.get("/v1/accounts/{account_id}/profile")
    def profile(
        account_id: str, repo: Repository = Depends(get_repository)
    ) -> dict[str, Any]:
        found = repo.get_profile(account_id)
        if found is None:
            raise HTTPException(status_code=404, detail="account not found")
        return {
            "account_id": found.account_id,
            "transactions": found.count,
            "mean_amount": round(found.mean, 2),
            "std_amount": round(found.std, 2),
            "last_country": found.last_country,
        }

    @app.get("/v1/stats")
    def stats(repo: Repository = Depends(get_repository)) -> dict[str, Any]:
        return repo.stats()

    return app


def app_factory() -> FastAPI:
    return create_app()
