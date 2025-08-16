from __future__ import annotations
from app.extensions import db
from app.models import Badge, BadgeGrant, PointLedger

def grant_badge(user_id: int, badge_id: int, issued_by_id: int, *, commit: bool = True) -> tuple[BadgeGrant, bool]:
    """
    Idempotently grant a badge and write points to the ledger.
    Returns (grant, created). If commit=True (default), commits the session;
    otherwise caller is responsible for committing/rolling back.
    """
    # Check existing grant
    grant = (db.session.query(BadgeGrant)
             .filter_by(user_id=user_id, badge_id=badge_id)
             .first())
    if grant:
        return grant, False

    # Create grant + ledger
    grant = BadgeGrant(user_id=user_id, badge_id=badge_id, issued_by_id=issued_by_id)
    db.session.add(grant)

    badge = db.session.get(Badge, badge_id)
    if badge and (badge.points or 0) != 0:
        db.session.add(PointLedger(
            user_id=user_id,
            delta=badge.points,
            reason=f"Badge: {badge.name}",
            source="badge",
            issued_by_id=issued_by_id,
        ))

    if commit:
        db.session.commit()
    return grant, True
