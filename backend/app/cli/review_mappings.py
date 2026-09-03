import json

import typer
from sqlalchemy import select

from app.db.models import ImportMapping, User
from app.db.session import SessionLocal


def main(user: str = "default", status: str = "ambiguous", limit: int = 100) -> None:
    allowed = {"pending", "ambiguous", "unresolved", "rejected", "matched", "matched_manual"}
    if status not in allowed:
        raise typer.BadParameter(f"status must be one of: {', '.join(sorted(allowed))}")
    with SessionLocal() as session:
        owner = session.scalar(select(User).where(User.slug == user))
        if owner is None:
            raise typer.BadParameter(f"Unknown user: {user}")
        mappings = session.scalars(
            select(ImportMapping)
            .where(ImportMapping.user_id == owner.id, ImportMapping.status == status)
            .order_by(ImportMapping.title, ImportMapping.year)
            .limit(limit)
        ).all()
        output = [
            {
                "id": item.id,
                "source_key": item.source_key,
                "title": item.title,
                "year": item.year,
                "status": item.status,
                "confidence": float(item.confidence) if item.confidence is not None else None,
                "candidates": json.loads(item.candidates_json or "[]"),
            }
            for item in mappings
        ]
    typer.echo(json.dumps({"count": len(output), "mappings": output}, indent=2))


if __name__ == "__main__":
    typer.run(main)
