import sqlite3
conn = sqlite3.connect('./data/database/cache.db')
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("TABELLE:", tables)
for t in tables:
    print(f"\n--- {t} ---")
    cur = conn.execute(f"PRAGMA table_info({t})")
    for col in cur.fetchall():
        print(f"  col {col[0]}: {col[1]} ({col[2]})")
conn.close()