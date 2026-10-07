from alembic import command


def test_migrations_match_models(alembic_config, engine):
    """Fails when a model changes but no migration was generated for it."""
    command.check(alembic_config)
