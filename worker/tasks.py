import os
import subprocess
import tempfile
import boto3
import redis

REDIS_URL = os.environ["REDIS_URL"]
S3_ENDPOINT = os.environ["S3_ENDPOINT"]
S3_ACCESS_KEY = os.environ["S3_ACCESS_KEY"]
S3_SECRET_KEY = os.environ["S3_SECRET_KEY"]
S3_BUCKET = os.environ["S3_BUCKET"]

BLENDER_BIN = os.environ["BLENDER_BIN"]
TEMPLATE_FBX = os.environ["TEMPLATE_FBX"]
HEAD_BONE = os.environ.get("HEAD_BONE", "mixamorig:Head")

r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
)

def key_raw(scan_id: str) -> str:
    return f"raw/{scan_id}/head.glb"

def key_out(scan_id: str) -> str:
    return f"out/{scan_id}/avatar.glb"

def process_scan(scan_id: str):
    r.hset(f"scan:{scan_id}", mapping={"status": "processing"})

    with tempfile.TemporaryDirectory() as td:
        head_path = os.path.join(td, "head.glb")
        out_path = os.path.join(td, "out.glb")

        # download head.glb
        obj = s3.get_object(Bucket=S3_BUCKET, Key=key_raw(scan_id))
        with open(head_path, "wb") as f:
            f.write(obj["Body"].read())

        # run blender headless
        cmd = [
            BLENDER_BIN, "-b", "-noaudio",
            "--python", "/app/blender/attach_head.py", "--",
            "--template", TEMPLATE_FBX,
            "--head", head_path,
            "--out", out_path,
            "--head_bone", HEAD_BONE,
            "--calib", '/app/blender/calib.json',
            "--delete_template_head", "true",
            "--decimate_ratio", "0.15",
        ]
        subprocess.check_call(cmd)

        # upload out.glb
        with open(out_path, "rb") as f:
            s3.put_object(Bucket=S3_BUCKET, Key=key_out(scan_id), Body=f.read(), ContentType="model/gltf-binary")

    r.hset(f"scan:{scan_id}", mapping={"status": "done"})
