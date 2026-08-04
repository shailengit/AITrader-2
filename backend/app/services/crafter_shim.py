from typing import List, Optional
from sqlalchemy.orm import Session

from app.services.hypothesis_service import list_hypotheses


def format_hypothesis_prompt(
    hypothesis_ids: List[str],
    extra_instructions: str = "",
    db: Session = None,
) -> str:
    """Build a structured prompt for the strategy-crafter skill from a list of hypotheses.

    The shim does NOT modify the crafter skill itself. It only emits a prompt
    that the user (or Claude in the Terminal) can pass to the skill.
    """
    rows = list_hypotheses(db=db, limit=500)
    selected = [h for h in rows if str(h.id) in hypothesis_ids]
    if not selected:
        return extra_instructions  # caller passed nothing; return raw instructions

    lines = [
        "Generate a strategy based on the following user-approved hypotheses:",
        "",
    ]
    for h in selected:
        head = f"[Hypothesis #{str(h.id)[:8]} | {h.source.value}] {h.why}"
        bits = []
        if h.ticker:
            bits.append(h.ticker)
        if h.sector:
            bits.append(f"sector: {h.sector}")
        if h.regime:
            bits.append(f"regime: {h.regime}")
        if h.conviction:
            bits.append(f"conviction: {h.conviction}")
        ctx = "Context: " + str(h.context) if h.context else "Source: " + str(h.source_meta)
        if bits:
            head += "  (" + ", ".join(bits) + ")"
        lines.append(head)
        lines.append(f"  {ctx}")
        lines.append("")

    if extra_instructions:
        lines.append("[User instructions]")
        lines.append(extra_instructions)

    return "\n".join(lines)
