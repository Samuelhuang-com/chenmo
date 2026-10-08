from functools import lru_cache

from app.config import get_settings


@lru_cache
def get_repo():
    s = get_settings()
    if s.repo_backend == "firestore":
        from app.repositories.firestore_repo import FirestoreCaseRepository
        return FirestoreCaseRepository(project=s.gcp_project, database=s.firestore_database)
    if s.repo_backend == "sqlite":
        from app.repositories.sqlite_repo import SqliteCaseRepository
        return SqliteCaseRepository(s.sqlite_path)
    from app.repositories.memory import MemoryCaseRepository
    return MemoryCaseRepository()
