from fastapi import APIRouter
from app.db.database import SessionLocal
from app.services.coach.strategy_summary import aggregate_strategy_summary

router = APIRouter(prefix="/coach/strategy", tags=["Coach"])


@router.get("/{strategy_path:path}/summary")
def strategy_summary(strategy_path: str):
    # `strategy_path` includes the leading "strategies/" and trailing ".py"
    db = SessionLocal()
    try:
        return aggregate_strategy_summary(strategy_path, db)
    finally:
        db.close()
