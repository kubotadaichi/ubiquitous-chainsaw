import os
import subprocess
import tempfile
import traceback
import time
import boto3
import redis

REDIS_URL = os.environ["REDIS_URL"]
S3_BUCKET = os.environ["S3_BUCKET"]
AWS_REGION = os.environ.get("AWS_REGION")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY")

BLENDER_BIN = os.environ.get("BLENDER_BIN", "/opt/blender/blender")
TEMPLATE_FBX = os.environ.get("TEMPLATE_FBX", "/app/blender/template.fbx")
TEMPLATE_BLEND_FBX = os.environ.get("TEMPLATE_BLEND_FBX", "/app/blender/template_blend.fbx")
HEAD_BONE = os.environ.get("HEAD_BONE", "mixamorig7:Head")

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

def key_raw(scan_id: str) -> str:
    return f"raw/{scan_id}/head.glb"

def key_out(scan_id: str) -> str:
    return f"out/{scan_id}/avatar.glb"

def key_out_blend(scan_id: str) -> str:
    return f"out/{scan_id}/avatar_blend.glb"

def process_scan(scan_id: str):
    r.hset(f"scan:{scan_id}", mapping={"status": "processing", "error": "", "updated_at": time.time()})

    try:
        with tempfile.TemporaryDirectory() as td:
            head_path = os.path.join(td, "head.glb")
            out_path = os.path.join(td, "out.glb")
            out_blend_path = os.path.join(td, "out_blend.glb")

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
            out_key = key_out(scan_id)
            with open(out_path, "rb") as f:
                s3.put_object(
                    Bucket=S3_BUCKET,
                    Key=out_key,
                    Body=f.read(),
                    ContentType="model/gltf-binary",
                )
            r.hset(
                f"scan:{scan_id}",
                mapping={
                    "asset_key": out_key,
                    "asset_content_type": "model/gltf-binary",
                    "asset_filename": "avatar.glb",
                    "updated_at": time.time(),
                },
            )

            # run blender headless (blend body template)
            cmd_blend = [
                BLENDER_BIN,
                "-b",
                "-noaudio",
                "--python",
                "/app/blender/attach_head.py",
                "--",
                "--template",
                TEMPLATE_BLEND_FBX,
                "--head",
                head_path,
                "--out",
                out_blend_path,
                "--head_bone",
                HEAD_BONE,
                "--calib",
                "/app/blender/calib.json",
                "--delete_template_head",
                "true",
                "--decimate_ratio",
                "0.15",
            ]
            subprocess.check_call(cmd_blend)

            # upload out_blend.glb
            out_blend_key = key_out_blend(scan_id)
            with open(out_blend_path, "rb") as f:
                s3.put_object(
                    Bucket=S3_BUCKET,
                    Key=out_blend_key,
                    Body=f.read(),
                    ContentType="model/gltf-binary",
                )
            r.hset(
                f"scan:{scan_id}",
                mapping={
                    "asset_blend_key": out_blend_key,
                    "asset_blend_content_type": "model/gltf-binary",
                    "asset_blend_filename": "avatar_blend.glb",
                    "updated_at": time.time(),
                },
            )
    except Exception as e:
        tb = traceback.format_exc(limit=10)
        r.hset(
            f"scan:{scan_id}",
            mapping={"status": "failed", "error": (str(e) + "\n" + tb)[:4000]},
        )
        raise
    else:
        r.hset(f"scan:{scan_id}", mapping={"status": "done", "updated_at": time.time()})
