import json

import typer

from app.db.session import SessionLocal
from app.services.mapping_review import approve_mapping, reject_mapping


def main(
    mapping_id: int,
    tmdb_id: int | None = None,
    reject: bool = False,
    actor: str = "local-user",
    reason: str | None = None,
) -> None:
    if reject == (tmdb_id is not None):
        raise typer.BadParameter("Choose exactly one of --tmdb-id or --reject")
    with SessionLocal() as session:
        result = (
            reject_mapping(session, mapping_id, actor=actor, reason=reason)
            if reject
            else approve_mapping(session, mapping_id, int(tmdb_id), actor=actor, reason=reason)
        )
    typer.echo(json.dumps(result.__dict__, indent=2))


if __name__ == "__main__":
    typer.run(main)
