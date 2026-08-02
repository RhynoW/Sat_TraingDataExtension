import duckdb

con = duckdb.connect('space_db.duckdb', read_only=True)

print('=== TABLES ===')
tables = con.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
).fetchall()
for t in tables:
    print(t[0])

print('\n=== ROW COUNTS ===')
for t in tables:
    cnt = con.execute(f"SELECT COUNT(*) FROM \"{t[0]}\"").fetchone()[0]
    print(f"{t[0]}: {cnt:,}")

print('\n=== COLUMNS PER TABLE ===')
for t in tables:
    cols = con.execute(
        f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{t[0]}' AND table_schema='main' ORDER BY ordinal_position"
    ).fetchall()
    print(f"\n-- {t[0]} --")
    for col in cols:
        print(f"  {col[0]}  ({col[1]})")

con.close()
