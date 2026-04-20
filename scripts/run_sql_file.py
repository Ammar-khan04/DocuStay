"""Run a .sql file against DATABASE_URL from .env (fallback when psql is not installed)."""
import re
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_env = _root / ".env"


def load_database_url() -> str:
    raw = _env.read_text(encoding="utf-8")
    for line in raw.splitlines():
        m = re.match(r"^\s*DATABASE_URL\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    raise SystemExit("DATABASE_URL not found in .env")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/run_sql_file.py <path-to.sql>")
    path = _root / sys.argv[1].replace("/", __import__("os").sep)
    if not path.is_file():
        raise SystemExit(f"not found: {path}")
    import psycopg2

    url = load_database_url()
    sql = path.read_text(encoding="utf-8")
    # Strip full-line SQL comments (psycopg2 executes one statement per execute())
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    statements = [s.strip() + ";" for s in re.split(r";\s*\n", body) if s.strip()]

    conn = psycopg2.connect(url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
        print(f"OK: {path.relative_to(_root)} ({len(statements)} statements)")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
