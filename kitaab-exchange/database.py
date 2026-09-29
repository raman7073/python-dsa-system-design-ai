from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy_utils import database_exists, create_database

DATABASE_URL = "postgresql://postgres:admin@localhost:5432/kitaab_db"

engine = create_engine(DATABASE_URL, echo=True)


def init_db():
    """Ensure database and all tables exist."""
    # 1. Create PostgreSQL database if it does not exist
    if not database_exists(engine.url):
        create_database(engine.url)
        print("Database 'reviews_db' created.")

    # 2. Create tables defined by SQLModel classes
    SQLModel.metadata.create_all(engine)
    print("Tables verified and initialized.")


def get_session():
    """Dependency that provides a database session per request."""
    with Session(engine) as session:
        yield session
