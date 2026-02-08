import sqlite3, os, time

DB_PATH = os.path.join("runtime", "memory.db")

def init_db():
    os.makedirs("runtime", exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()

        # 안정성 향상(특히 Windows)
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA foreign_keys=ON;")

        cur.execute("""CREATE TABLE IF NOT EXISTS chat_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS kv(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS approvals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            status TEXT NOT NULL,
            action_type TEXT NOT NULL,
            payload TEXT NOT NULL
        )""")
        con.commit()
    finally:
        con.close()

def add_chat(role: str, content: str):
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("INSERT INTO chat_log(ts, role, content) VALUES(?,?,?)",
                    (int(time.time()), role, content))
        con.commit()
    finally:
        con.close()

def last_chats(limit: int = 12):
    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute(
            "SELECT role, content FROM chat_log ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return list(reversed(rows))
    finally:
        con.close()
