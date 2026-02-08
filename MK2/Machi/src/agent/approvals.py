import sqlite3, json, time, os
DB_PATH = os.path.join("runtime", "memory.db")

def request_approval(action_type: str, payload: dict) -> int:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO approvals(ts, status, action_type, payload) VALUES(?,?,?,?)",
            (int(time.time()), "PENDING", action_type, json.dumps(payload, ensure_ascii=False))
        )
        con.commit()
        return cur.lastrowid

def list_pending():
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT id, ts, action_type, payload FROM approvals WHERE status='PENDING' ORDER BY id ASC"
        ).fetchall()
    out = []
    for (i, ts, t, p) in rows:
        out.append({"id": i, "ts": ts, "action_type": t, "payload": p})
    return out

def resolve(approval_id: int, approve: bool):
    status = "APPROVED" if approve else "REJECTED"
    with sqlite3.connect(DB_PATH) as con:
        con.execute("UPDATE approvals SET status=? WHERE id=?", (status, approval_id))
        con.commit()
