"""Shared R2 helpers for the CapCut export spike (read-only)."""
import json, os, re
import boto3
from dotenv import dotenv_values

_env = dotenv_values("/Users/aleksandrsgraholskis/Claude_Code/content-factory-saas/.env.local")
BUCKET = _env["R2_BUCKET_NAME"]
s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{_env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=_env["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=_env["R2_SECRET_ACCESS_KEY"],
    region_name="auto",
)

def ls(prefix):
    out = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        out += page.get("Contents", [])
    return out

def latest(run_id, stage, name):
    objs = ls(f"users/operator/runs/{run_id}/{stage}/{name}@v")
    if not objs:
        return None
    return max(objs, key=lambda o: int(re.search(r"@v(\d+)", o["Key"]).group(1)))["Key"]

def get_json(key):
    return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
