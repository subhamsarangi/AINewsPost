from digest import db
from datetime import date

today = date.today()

with db.connect() as conn:
    # Delete digest for today
    conn.execute("DELETE FROM digests WHERE date = %s", (today,), prepare=False)
    
    # Clear bg tasks and logs
    conn.execute("TRUNCATE TABLE bg_tasks CASCADE", prepare=False)
    conn.execute("TRUNCATE TABLE bg_logs CASCADE", prepare=False)
    
    conn.commit()

print(f"Cleared digest for {today}, bg_tasks, and bg_logs")
