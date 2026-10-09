import numpy as np
from digest import db, llm

c = db.connect()
rows = c.execute("select id, title from items").fetchall()
V = np.array(llm.embed([r["title"] or "" for r in rows]))
V /= np.linalg.norm(V, axis=1, keepdims=True)
S = V @ V.T
pairs = [(S[i, j], i, j) for i in range(len(rows)) for j in range(i + 1, len(rows))]
for s, i, j in sorted(pairs, reverse=True)[:12]:
    print(f"{s:.3f} | {rows[i]['title'][:45]} | {rows[j]['title'][:45]}")
print(llm.usage_report())
