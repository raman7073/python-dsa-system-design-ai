from alembic import context
from app.db.session import Base, engine
import app.models  # Register model metadata.

def include_object(obj, name, type_, reflected, compare_to):
    # Never propose deleting the deliberately preserved legacy table.
    return not (type_ == "table" and name == "todos" and reflected and compare_to is None)

if context.is_offline_mode():
    context.configure(url=engine.url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata,
                          include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()
