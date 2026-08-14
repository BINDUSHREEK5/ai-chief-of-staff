import sqlite3

db = './agent.db'
conn = sqlite3.connect(db)

print('=== APPROVALS (latest 5) ===')
for row in conn.execute('SELECT approval_code, status, conversation_id FROM approvals ORDER BY created_at DESC LIMIT 5'):
    print(row)

print()
print('=== CONVERSATIONS (latest 5) ===')
for row in conn.execute('SELECT id, channel, external_conversation_id FROM conversations ORDER BY id DESC LIMIT 5'):
    print(row)

conn.close()