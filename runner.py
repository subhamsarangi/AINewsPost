import subprocess
import time

check_cmd = ["docker", "exec", "ai-digest-db", "psql", "-U", "digest", "-d", "digest", "-c", "\\dt"]

def is_db_ready():
    return subprocess.run(check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

if not is_db_ready():
    subprocess.run(["docker", "compose", "up", "-d"])
    while not is_db_ready():
        time.sleep(2)

subprocess.run(["streamlit", "run", "ui/app.py", "--server.headless", "true", "--server.port", "8599"])