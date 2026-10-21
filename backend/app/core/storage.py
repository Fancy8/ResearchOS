from functools import lru_cache

import boto3
from botocore.config import Config

from app.core.config import get_settings


@lru_cache
def s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 2},
        ),
    )


def put_object(key, content, content_type="application/pdf"):
    return s3_client().put_object(
        Bucket=get_settings().s3_bucket, Key=key, Body=content, ContentType=content_type
    )


def get_object_bytes(key):
    response = s3_client().get_object(Bucket=get_settings().s3_bucket, Key=key)
    with response["Body"] as stream:
        return stream.read()


def copy_object(source, target):
    bucket = get_settings().s3_bucket
    return s3_client().copy_object(Bucket=bucket, Key=target, CopySource={"Bucket": bucket, "Key": source})


def remove_object(key):
    s3_client().delete_object(Bucket=get_settings().s3_bucket, Key=key)
