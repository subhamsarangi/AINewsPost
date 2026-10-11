"""Cloudflare R2 PDF storage."""

import os
import boto3
from io import BytesIO


class R2Error(RuntimeError):
    """R2 operation failed."""

    pass


def get_client():
    """Return configured S3 client for R2."""
    account_id = os.getenv("R2_ACCOUNT_ID")
    access_key = os.getenv("R2_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY")

    if not all([account_id, access_key, secret_key]):
        raise R2Error(
            "Missing R2 credentials. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY"
        )

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )


def upload(pdf_bytes: bytes, date_str: str) -> str:
    """Upload PDF to R2, return public URL.

    Args:
        pdf_bytes: PDF file content
        date_str: YYYY-MM-DD, used as object key

    Returns:
        Public R2 URL of the uploaded PDF

    Raises:
        R2Error: If upload fails or credentials missing
    """
    bucket = os.getenv("R2_BUCKET_NAME")
    public_url = os.getenv("R2_PUBLIC_URL")
    
    if not bucket:
        raise R2Error("R2_BUCKET_NAME not set")
    if not public_url:
        raise R2Error("R2_PUBLIC_URL not set")

    key = f"digests/{date_str}.pdf"

    try:
        client = get_client()
        client.put_object(Bucket=bucket, Key=key, Body=BytesIO(pdf_bytes))
    except Exception as e:
        raise R2Error(f"Failed to upload {key}: {e}") from e

    # Use configured public URL
    return f"{public_url.rstrip('/')}/{key}"
