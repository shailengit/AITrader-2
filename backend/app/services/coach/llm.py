"""LLM critique engine for the Trade Coach.

Pipeline:
  1. Build prompts (prompts.py)
  2. Call shared LLM (llm_engine.get_llm_client) — reuses retry/timeout
  3. Validate every number in the output appears in the bundle
  4. On validation failure, retry once with a stricter suffix
  5. Persist the result to journal_coach_report
"""
from __future__ import annotations
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import date as date_cls
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import SQLAlchemyError

from app.services.llm_engine import get_llm_client
from app.services.coach.prompts import SYSTEM_PROMPT, user_prompt
from app.models.journal import JournalCoachReport

logger = logging.getLogger(__name__)

# Permissive regex for any number in a markdown report. Uses lookarounds so a
# digit run inside an alphanumeric token (e.g. a truncated trade ID like
# "582f18d6") is NOT extracted — only standalone numeric values are.
_NUMBER_RE = re.compile(
    r"(?<![0-9a-zA-Z])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![0-9a-zA-Z])"
)


@dataclass
class ReportResult:
    markdown: Optional[str] = None
    error: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    model_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    report_id: Optional[str] = None


# Full UUIDs and ISO dates contain digit runs that are NOT metric values. The
# LLM is instructed to cite trade IDs and dates, so strip these before number
# extraction — otherwise the validator flags their digits as "invented numbers"
# and every report that cites an ID/date fails with llm_invented_numbers.
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _extract_numbers(text: str) -> List[str]:
    # Remove full UUIDs and dates so their digits aren't mistaken for metrics.
    # (Truncated hex IDs are already excluded by the _NUMBER_RE lookarounds.)
    text = _UUID_RE.sub(" ", text)
    text = _DATE_RE.sub(" ", text)
    return _NUMBER_RE.findall(text)


def _bundle_number_set(bundle: dict) -> set:
    """Flatten the bundle into a set of numeric strings for membership checks."""
    def walk(node):
        out = []
        if isinstance(node, dict):
            for v in node.values():
                out.extend(walk(v))
        elif isinstance(node, list):
            for v in node:
                out.extend(walk(v))
        elif isinstance(node, bool):
            return out
        elif isinstance(node, (int, float)):
            out.append(node)
        return out
    nums = walk(bundle)
    out = set()
    for n in nums:
        out.add(f"{n:.4f}".rstrip("0").rstrip("."))
        out.add(f"{n:.2f}")
        out.add(f"{n:.0f}")
        out.add(str(n))
    return out


def _validate_numbers(md: str, bundle: dict) -> Tuple[bool, List[str]]:
    """Return (ok, list_of_unmatched_numbers)."""
    allowed = _bundle_number_set(bundle)
    unmatched: List[str] = []
    for n in _extract_numbers(md):
        if n in allowed:
            continue
        try:
            f = float(n)
            # Small integers (0-100) are almost always counts the LLM derived
            # from the data (e.g. "8 WBD trades", "7-day hold", "20 recent
            # trades"). Allow them — they're not invented metrics.
            if f.is_integer() and 0 <= f <= 100:
                continue
            for fmt in (f"{f:.2f}", f"{f:.0f}", f"{f:.4f}".rstrip("0").rstrip(".")):
                if fmt in allowed:
                    break
            else:
                unmatched.append(n)
        except ValueError:
            unmatched.append(n)
    return (len(unmatched) == 0), unmatched


def _call_llm(client, model: str, system: str, user: str) -> Tuple[Optional[str], Optional[str], int, int]:
    """One LLM call. Returns (content, error, prompt_tokens, completion_tokens)."""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
        )
        content = resp.choices[0].message.content if resp.choices else None
        usage = getattr(resp, "usage", None)
        pt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        ct = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        return content, None, pt, ct
    except Exception as e:
        return None, f"llm_unavailable: {e}", 0, 0


def _persist_report(session, bundle: dict, period_start: date_cls, period_end: date_cls,
                    strategy_id: Optional[uuid.UUID], markdown: str, model_id: str,
                    prompt_tokens: int, completion_tokens: int, duration_ms: int) -> Optional[str]:
    try:
        row = JournalCoachReport(
            period_start=period_start,
            period_end=period_end,
            strategy_id=strategy_id,
            bundle=bundle,
            report_md=markdown,
            metrics=_metrics_summary(bundle),
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return str(row.id)
    except SQLAlchemyError as e:
        logger.warning("Failed to persist coach report: %s", e)
        try:
            session.rollback()
        except Exception:
            pass
        return None


def _metrics_summary(bundle: dict) -> dict:
    k = bundle.get("kpis", {})
    return {
        "n_trades": k.get("n_trades", 0),
        "win_rate": k.get("win_rate", 0.0),
        "expectancy": k.get("expectancy", 0.0),
        "total_pnl": k.get("total_pnl", 0.0),
        "max_dd": k.get("max_dd", 0.0),
    }


def generate_report(session, bundle: dict, model: Optional[str] = None) -> ReportResult:
    """Generate a Coach report. Returns a ReportResult. Persists on success."""
    started = time.time()
    client, default_model = get_llm_client()
    if client is None:
        return ReportResult(error="llm_unavailable", metrics=_metrics_summary(bundle), model_id=model or default_model)
    used_model = model or default_model

    # Attempt 1
    content, err, pt, ct = _call_llm(client, used_model, SYSTEM_PROMPT, user_prompt(bundle))
    if err or not content:
        return ReportResult(
            error=err or "llm_empty_response",
            metrics=_metrics_summary(bundle),
            model_id=used_model,
            prompt_tokens=pt,
            completion_tokens=ct,
        )

    # Validate numbers
    ok, unmatched = _validate_numbers(content, bundle)
    if not ok:
        # Attempt 2 with stricter suffix
        stricter = user_prompt(bundle) + (
            f"\n\nIMPORTANT: Your previous draft contained {len(unmatched)} number(s) "
            "not present in the bundle. Re-issue the report using ONLY bundle values."
        )
        content2, err2, pt2, ct2 = _call_llm(client, used_model, SYSTEM_PROMPT, stricter)
        if err2 or not content2:
            return ReportResult(
                error="llm_unavailable",
                metrics=_metrics_summary(bundle),
                model_id=used_model,
                prompt_tokens=pt + pt2,
                completion_tokens=ct + ct2,
            )
        ok2, unmatched2 = _validate_numbers(content2, bundle)
        if not ok2:
            return ReportResult(
                error="llm_invented_numbers",
                metrics=_metrics_summary(bundle),
                model_id=used_model,
                prompt_tokens=pt + pt2,
                completion_tokens=ct + ct2,
            )
        content, pt, ct = content2, pt + pt2, ct + ct2

    duration = int((time.time() - started) * 1000)
    period_start = date_cls.fromisoformat(bundle["period"]["start"])
    period_end = date_cls.fromisoformat(bundle["period"]["end"])
    strategy_id_obj = uuid.UUID(bundle["strategy_id"]) if bundle.get("strategy_id") else None
    report_id = _persist_report(
        session, bundle, period_start, period_end, strategy_id_obj,
        markdown=content, model_id=used_model,
        prompt_tokens=pt, completion_tokens=ct, duration_ms=duration,
    )
    return ReportResult(
        markdown=content,
        metrics=_metrics_summary(bundle),
        duration_ms=duration,
        model_id=used_model,
        prompt_tokens=pt,
        completion_tokens=ct,
        report_id=report_id,
    )
