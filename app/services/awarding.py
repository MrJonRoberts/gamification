from __future__ import annotations
from app.extensions import db
from app.models import Badge, BadgeGrant, PointLedger

def grant_badge(user_id: int, badge_id: int, issued_by_id: int) -> tuple[BadgeGrant, bool]:
    """
    Atomically grant a badge to a user and write the points to the ledger.
    Returns (grant_obj, created_bool). Idempotent (no duplicate grants).
    """
    with db.session.begin():
        grant = (db.session.query(BadgeGrant)
                 .filter_by(user_id=user_id, badge_id=badge_id)
                 .first())
        if grant:
            return grant, False

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
    return grant, True
