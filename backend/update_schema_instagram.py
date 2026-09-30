"""Add the instagram_media_id column. Mirrors update_schema_post_type.py."""

from app.database import SessionLocal
from sqlalchemy import text


def update_schema():
    db = SessionLocal()
    try:
        print("Executing schema update...")
        sql = text("ALTER TABLE posts ADD COLUMN IF NOT EXISTS instagram_media_id VARCHAR(255);")
        db.execute(sql)
        db.commit()
        print("Schema updated successfully: 'instagram_media_id' column added.")
    except Exception as e:
        print(f"Error updating schema: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    update_schema()
