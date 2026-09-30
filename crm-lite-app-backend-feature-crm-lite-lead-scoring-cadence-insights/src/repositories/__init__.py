"""Data-access layer: real, Postgres-backed repository classes per module,
isolating services from SQLAlchemy — services (and, once written, route
handlers) call these classes, never a Session directly.

Why this exists
----------------
Every entity across all 8 modules has a full CRUD repository class already
implemented (see src/repositories/_base.py for the generic list/get/create/
update/delete helpers every module's repository classes are built from, and
each `<module>_repository.py` for the entity-specific classes + a
`get_<entity>_repository()` factory per class). A developer building out a
module's service/route layer only needs to import and call these — there is
no database code left to write, only business logic.

Test fixtures that need a clean database should wrap each test in a
transaction against the real Postgres instance (see docker-compose.yml) and
roll it back afterward, rather than reaching into any repository's internals.
"""
