import os
import time
import redis
from tasks import process_scan

REDIS_URL = os.environ["REDIS_URL"]
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

print("worker started")

while True:
    scan_id = r.brpop("queue:scans", timeout=2)
    if not scan_id:
        continue
    _, scan_id = scan_id
    try:
        process_scan(scan_id)
    except Exception as e:
        print("ERROR", scan_id, e)
