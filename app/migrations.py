import logging

from passlib.context import CryptContext
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .models import AdminUser
from .config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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


def migrate_notices_is_active(engine: Engine) -> None:
    inspector = inspect(engine)
    if "notices" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("notices")}
    if "is_active" in columns:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE notices ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
        if "published" in columns:
            connection.execute(text("UPDATE notices SET is_active = published"))


def is_valid_bcrypt_hash(password_hash: str) -> bool:
    """Check if the password hash is a valid bcrypt hash."""
    if not password_hash:
        return False
    return password_hash.startswith(("$2a$", "$2b$", "$2y$")) and len(password_hash) == 60


def migrate_plaintext_passwords(engine: Engine, session_factory) -> dict:
    """Migrate any plain text passwords in admin_users table to bcrypt.
    
    This function:
    1. Finds any admin users with non-bcrypt passwords
    2. Automatically migrates the default admin if needed
    
    Returns a dict with migration status info.
    """
    result = {
        "checked": 0,
        "needs_migration": [],
        "migrated": 0,
        "errors": []
    }
    
    inspector = inspect(engine)
    if "admin_users" not in inspector.get_table_names():
        logger.warning("admin_users table not found - skipping password migration")
        return result
    
    session = session_factory()
    try:
        admins = session.execute(select(AdminUser)).scalars().all()
        result["checked"] = len(admins)
        
        for admin in admins:
            password_hash = admin.password_hash
            
            # Skip if already valid bcrypt
            if is_valid_bcrypt_hash(password_hash):
                # Verify it can be used with current bcrypt version
                try:
                    pwd_context.verify("test", password_hash)
                except Exception as e:
                    logger.warning(f"Rehashing admin '{admin.username}' due to bcrypt version mismatch")
                    # Force rehash with current bcrypt
                    new_hash = pwd_context.hash(settings.admin_password)
                    admin.password_hash = new_hash
                    session.commit()
                    result["migrated"] += 1
                    logger.info(f"Successfully rehashed password for admin '{admin.username}'")
                continue
            
            # Check if it's a plain text password (no $ prefix, short length)
            if len(password_hash) < 60 and not password_hash.startswith("$"):
                logger.warning(
                    f"Plain text password detected for admin '{admin.username}'. "
                    f"Auto-migrating to bcrypt..."
                )
                
                # Auto-migrate to bcrypt using the default password from config
                new_hash = pwd_context.hash(settings.admin_password)
                admin.password_hash = new_hash
                session.commit()
                
                result["needs_migration"].append({
                    "username": admin.username,
                    "action": "auto_migrated"
                })
                result["migrated"] += 1
                logger.info(f"Successfully auto-migrated password for admin '{admin.username}'")
            else:
                # Invalid hash format (e.g., malformed bcrypt)
                logger.error(
                    f"Invalid password hash format for admin '{admin.username}'. "
                    f"Hash starts with: '{password_hash[:10] if password_hash else 'empty'}'"
                )
                result["errors"].append({
                    "username": admin.username,
                    "issue": "Invalid hash format - auto-fixing with default password"
                })
                
                # Auto-fix with default password
                new_hash = pwd_context.hash(settings.admin_password)
                admin.password_hash = new_hash
                session.commit()
                result["migrated"] += 1
                logger.info(f"Fixed invalid hash for admin '{admin.username}'")
        
        return result
        
    except Exception as e:
        logger.error(f"Error during password migration check: {type(e).__name__}: {e}")
        result["errors"].append({"issue": str(e)})
        return result
    finally:
        session.close()


def force_migrate_plaintext_password(engine, session_factory, username: str, plain_password: str) -> bool:
    """Force migrate a specific admin user's plain text password to bcrypt.
    
    WARNING: Only use this if you know the plain text password!
    
    Args:
        engine: SQLAlchemy engine
        session_factory: Session factory
        username: Admin username to migrate
        plain_password: The plain text password (will be hashed)
    
    Returns:
        True if migration successful, False otherwise
    """
    session = session_factory()
    try:
        admin = session.execute(
            select(AdminUser).where(AdminUser.username == username)
        ).scalar_one_or_none()
        
        if not admin:
            logger.error(f"Admin user '{username}' not found")
            return False
        
        # Hash the plain password
        new_hash = pwd_context.hash(plain_password)
        admin.password_hash = new_hash
        session.commit()
        
        logger.info(f"Successfully migrated password for admin '{username}'")
        return True
        
    except Exception as e:
        logger.error(f"Error force migrating password for '{username}': {type(e).__name__}: {e}")
        session.rollback()
        return False
    finally:
        session.close()
