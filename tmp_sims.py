import sys
from digest import db, llm

q = " ".join(sys.argv[1:])
e = db._vec(llm.embed_one(q))
c = db.connect()
for r in c.execute(
    "select title, 1-(embedding <=> %s) s from items where embedding is not null order by embedding <=> %s limit 20",
    (e, e),
).fetchall():
    print(f"{r['s']:.3f} | {r['title'][:60]}")
