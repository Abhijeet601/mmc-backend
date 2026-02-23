from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def migrate_notices_publish_date(engine: Engine) -> None:
    inspector = inspect(engine)
    if "notices" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("notices")}
    if "publish_date" in columns:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE notices ADD COLUMN publish_date DATETIME"))
        connection.execute(
            text("UPDATE notices SET publish_date = created_at WHERE publish_date IS NULL")
        )

