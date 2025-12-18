import os
import uuid
import time
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
import boto3
from botocore.exceptions import ClientError
import redis

REDIS_URL = os.environ["REDIS_URL"]
S3_ENDPOINT = os.environ["S3_ENDPOINT"]
S3_ACCESS_KEY = os.environ["S3_ACCESS_KEY"]
S3_SECRET_KEY = os.environ["S3_SECRET_KEY"]
S3_BUCKET = os.environ["S3_BUCKET"]

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
)

app = FastAPI()

def key_raw(scan_id: str) -> str:
    return f"raw/{scan_id}/head.glb"

def key_out(scan_id: str) -> str:
    return f"out/{scan_id}/avatar.fbx"


def ensure_bucket():
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=S3_BUCKET)

ensure_bucket()

#スキャンデータのアップロード
@app.post("/scan")
async def upload_scan(head: UploadFile = File(...)):
    if not head.filename.lower().endswith((".glb", ".gltf")):
        raise HTTPException(400, "head must be .glb/.gltf")

    scan_id = str(uuid.uuid4())
    create_at = time.time() #時間によるソートを想定
    r.hset(f"scan:{scan_id}", mapping={"status": "queued", "created_at": create_at})
    r.zadd("scans:index", {scan_id:create_at})
    data = await head.read()

    s3.put_object(Bucket=S3_BUCKET, Key=key_raw(scan_id), Body=data, ContentType="model/gltf-binary")

    # キュー投入（Celeryが拾う）
    r.lpush("queue:scans", scan_id)

    return {"scan_id": scan_id}

#状態の出力
@app.get("/scan/{scan_id}/status")
def status(scan_id: str):
    d = r.hgetall(f"scan:{scan_id}")
    if not d:
        raise HTTPException(404, "scan_id not found")
    return d

#一覧の出力スキャンidをリストで返す機能の作成
@app.get("/scans")
def list_scans(
    limit: int = Query(100, ge=1, le=1000),
    cursor: float | None = Query(None), 
):
    max_score = cursor if cursor is not None else "+inf"
    
    scan_ids = r.zrevrangebyscore("scans:index", max=max_score, min ="-inf", start = 0, num=limit,withscores=True) 
    items = []
    next_cursor = None
    
    for scan_id, score in scan_ids:
        d = r.hgetall(f"scan:{scan_id}")
        items.append({"scan_id":scan_id, "status": d.get("status"), "created_at":float(score)})
        next_cursor = score
    
    return {"items": items, "next_cursor": next_cursor if len(items)==limit else None}

#scan一覧を取得
@app.get("/scan/{scan_id}/asset")
def asset(scan_id: str):
    d = r.hgetall(f"scan:{scan_id}")
    if not d:
        raise HTTPException(404, "scan_id not found")
    if d.get("status") != "done":
        return JSONResponse({"status": d.get("status", "unknown")}, status_code=409)

    # 署名URL（MinIOでも使える）
    url = s3.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": S3_BUCKET, "Key": key_out(scan_id)},
        ExpiresIn=60 * 10,
    )
    return {"download_url": url}

@app.get("/scan/{scan_id}/download")
def download(scan_id: str):
    d = r.hgetall(f"scan:{scan_id}")
    if not d or d.get("status") != "done":
        raise HTTPException(404, "not ready")

    key = key_out(scan_id)
    obj = s3.get_object(Bucket=S3_BUCKET, Key=key)

    return StreamingResponse(
        obj["Body"],
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="avatar_{scan_id}.fbx"'
        },
    )