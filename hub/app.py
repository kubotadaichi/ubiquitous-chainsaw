import os
import uuid
import time
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import boto3
from botocore.exceptions import ClientError
import redis
import mimetypes

REDIS_URL = os.environ["REDIS_URL"]
S3_BUCKET = os.environ["S3_BUCKET"]
AWS_REGION = os.environ.get("AWS_REGION")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def make_s3_client():
    kwargs: dict = {}
    if S3_ENDPOINT:
        kwargs["endpoint_url"] = S3_ENDPOINT
        if S3_ACCESS_KEY and S3_SECRET_KEY:
            kwargs["aws_access_key_id"] = S3_ACCESS_KEY
            kwargs["aws_secret_access_key"] = S3_SECRET_KEY
    else:
        if not AWS_REGION:
            raise RuntimeError("AWS_REGION is required when S3_ENDPOINT is not set")
        kwargs["region_name"] = AWS_REGION
    return boto3.client("s3", **kwargs)

s3 = make_s3_client()

app = FastAPI()

def key_raw(scan_id: str) -> str:
    return f"raw/{scan_id}/head.glb"

def key_out(scan_id: str) -> str:
    return f"out/{scan_id}/avatar.glb"

def candidate_out_keys(scan_id: str, scan_meta: dict | None = None) -> list[str]:
    scan_meta = scan_meta or {}
    keys = []
    if scan_meta.get("asset_key"):
        keys.append(scan_meta["asset_key"])
    keys.append(key_out(scan_id))
    keys.append(f"out/{scan_id}/avatar.fbx")  # backward compatibility
    seen = set()
    out = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out

def guess_content_type(key: str, scan_meta: dict | None = None) -> str:
    scan_meta = scan_meta or {}
    if scan_meta.get("asset_content_type"):
        return scan_meta["asset_content_type"]
    if key.lower().endswith(".glb"):
        return "model/gltf-binary"
    if key.lower().endswith(".gltf"):
        return "model/gltf+json"
    if key.lower().endswith(".fbx"):
        return "application/octet-stream"
    return mimetypes.guess_type(key)[0] or "application/octet-stream"

def guess_filename(scan_id: str, key: str, scan_meta: dict | None = None) -> str:
    scan_meta = scan_meta or {}
    if scan_meta.get("asset_filename"):
        return scan_meta["asset_filename"]
    ext = os.path.splitext(key)[1] or ".bin"
    return f"avatar_{scan_id}{ext}"

def head_object_exists(key: str) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def ensure_bucket():
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
    except ClientError as e:
        if S3_ENDPOINT:
            s3.create_bucket(Bucket=S3_BUCKET)
            return
        raise RuntimeError(
            f"S3 bucket not accessible: {S3_BUCKET}. Create it via Terraform and ensure EC2 IAM Role has access."
        ) from e

ensure_bucket()

#別のappからのリクエスト送信を許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"], #GET,POSTなど
    allow_headers=["*"], 
)

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

    for key in candidate_out_keys(scan_id, d):
        if head_object_exists(key):
            url = s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": S3_BUCKET, "Key": key},
                ExpiresIn=60 * 10,
            )
            return {"download_url": url, "key": key}

    # doneなのに実体がない: hub側は落とさずクライアントに伝える
    return JSONResponse({"status": "missing_asset"}, status_code=409)

@app.get("/scan/{scan_id}/download")
def download(scan_id: str):
    d = r.hgetall(f"scan:{scan_id}")
    if not d or d.get("status") != "done":
        raise HTTPException(404, "not ready")

    last_err: Exception | None = None
    for key in candidate_out_keys(scan_id, d):
        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
            content_type = guess_content_type(key, d)
            filename = guess_filename(scan_id, key, d)
            return StreamingResponse(
                obj["Body"],
                media_type=content_type,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code")
            if code in ("404", "NoSuchKey", "NotFound"):
                last_err = e
                continue
            raise

    return JSONResponse({"status": "missing_asset"}, status_code=409)
