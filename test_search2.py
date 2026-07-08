import sqlite3
conn = sqlite3.connect(r'C:\Users\lee\Desktop\mediavault\data\mediavault.db')
c = conn.cursor()

# Test LIKE query directly
c.execute("SELECT id, filename FROM files WHERE filename LIKE ? AND is_deleted = 0 LIMIT 10", ['%002431%'])
r = c.fetchall()
print(f'LIKE %002431%: {len(r)} results')
for row in r:
    print(f'  id={row[0]}, filename={row[1]}')

c.execute("SELECT id, filename FROM files WHERE filename LIKE ? AND is_deleted = 0 LIMIT 10", ['%590%'])
r = c.fetchall()
print(f'LIKE %590%: {len(r)} results')
for row in r:
    print(f'  id={row[0]}, filename={row[1]}')

conn.close()
