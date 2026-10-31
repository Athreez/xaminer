"""Object storage (SeaweedFS, S3 API). Buckets are private; browsers get short-lived signed links.

Two clients: one talks to storage directly (uploads), the other only signs links for the public
address the browser uses. A SigV4 signature covers the host, so links are signed for the public
host and nginx passes that host on to storage unchanged (deploy/nginx.conf, `/images/`).
"""

import asyncio
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from app.core.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

IMAGES = "images"
EVIDENCE = "evidence"


class Storage:
    def __init__(self, settings: Settings) -> None:
        def client(endpoint: str) -> "S3Client":
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
                region_name="us-east-1",
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},  # /bucket/key, so one nginx route per bucket
                    retries={"max_attempts": 2},
                    connect_timeout=3,
                    read_timeout=10,
                ),
            )

        self._direct = client(settings.s3_endpoint)
        self._signer = client(settings.s3_public_url or settings.public_base_url)

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        # boto3 is synchronous; keep the event loop free while it uploads.
        await asyncio.to_thread(
            self._direct.put_object,
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl="private, max-age=3600",
        )

    async def delete(self, bucket: str, keys: list[str]) -> None:
        """Remove objects (missing ones are fine). At most 1000 keys per call."""
        if not keys:
            return
        await asyncio.to_thread(
            self._direct.delete_objects,
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in keys], "Quiet": True},
        )

    async def copy(self, bucket: str, source: str, target: str) -> None:
        await asyncio.to_thread(
            self._direct.copy_object,
            Bucket=bucket,
            Key=target,
            CopySource={"Bucket": bucket, "Key": source},
        )

    def internal_url(self, bucket: str, key: str, seconds: int) -> str:
        """A link for other services on the storage network (the exec-worker fetching a test
        bundle), not for browsers. Made locally, like `signed_url`."""
        return self._direct.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=seconds
        )

    def signed_url(self, bucket: str, key: str, seconds: int) -> str:
        """A link that works for `seconds`. Made locally: no request to storage."""
        return self._signer.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=seconds
        )
