import argparse
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

API_BASE = "https://open-api.123pan.com"
PLATFORM = "open_platform"
MAX_WORKERS = 8
SINGLE_UPLOAD_MAX_BYTES = 100 * 1024 * 1024  # 100MB — use single-step upload below this
RETRY_MAX = 5


class Pan123Error(RuntimeError):
    pass


def mask(s):
    """Replace all characters with *"""
    return "*" * len(str(s))


def log(msg):
    print(mask(msg))


def info(msg):
    """Show progress info — numbers only, no paths/IDs."""
    print(msg)


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def request_with_retry(session, method, url, attempts=RETRY_MAX, timeout=(30, 600), **kwargs):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return session.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as e:
            last_error = e
            if attempt == attempts:
                break
            wait = min(2 ** attempt, 30)
            time.sleep(wait)
    raise last_error


def md5_file(path):
    digest = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def api_json(session, method, url, token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Platform"] = PLATFORM
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = request_with_retry(session, method, url, headers=headers, **kwargs)
    response.raise_for_status()
    data = response.json()
    if data.get("code") == 20103:
        raise Pan123Error("upload is still verifying")
    if data.get("code") != 0:
        raise Pan123Error(f"code={data.get('code')}, message={data.get('message')}")
    return data.get("data")


def get_access_token(session, client_id, client_secret):
    data = api_json(
        session,
        "POST",
        f"{API_BASE}/api/v1/access_token",
        headers={"Content-Type": "application/json"},
        json={"clientID": client_id, "clientSecret": client_secret},
    )
    return data["accessToken"]


def create_file(session, token, parent_file_id, remote_path, path):
    return api_json(
        session,
        "POST",
        f"{API_BASE}/upload/v2/file/create",
        token=token,
        headers={"Content-Type": "application/json"},
        json={
            "parentFileID": parent_file_id,
            "filename": remote_path,
            "etag": md5_file(path),
            "size": path.stat().st_size,
            "duplicate": 2,
            "containDir": True,
        },
    )


def _upload_one_slice(session, server, token, preupload_id, slice_no, chunk_data):
    """Upload a single slice. Runs in a thread."""
    slice_md5 = hashlib.md5(chunk_data).hexdigest()
    files = {"slice": (f"slice_{slice_no}", chunk_data, "application/octet-stream")}
    data = {
        "preuploadID": preupload_id,
        "sliceNo": str(slice_no),
        "sliceMD5": slice_md5,
    }
    for attempt in range(1, RETRY_MAX + 1):
        try:
            api_json(
                session,
                "POST",
                f"{server}/upload/v2/file/slice",
                token=token,
                data=data,
                files=files,
                timeout=(30, 300),
            )
            return slice_no
        except Exception:
            if attempt == RETRY_MAX:
                raise
            time.sleep(min(2 ** attempt, 30))


def upload_slices_parallel(token, create_data, path):
    preupload_id = create_data["preuploadID"]
    slice_size = int(create_data["sliceSize"])
    server = create_data["servers"][0].rstrip("/")

    chunks = []
    with path.open("rb") as f:
        while True:
            chunk = f.read(slice_size)
            if not chunk:
                break
            chunks.append(chunk)

    total = len(chunks)
    if total == 0:
        return

    log(f"uploading {total} slices ({slice_size}B each)")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for i, chunk in enumerate(chunks, start=1):
            # Each thread gets its own session for connection reuse
            s = requests.Session()
            futures[executor.submit(_upload_one_slice, s, server, token, preupload_id, i, chunk)] = i

        done = 0
        for future in as_completed(futures):
            slice_no = future.result()
            done += 1
            log(f"slice done [{done}/{total}]")


def complete_upload(session, token, preupload_id):
    for _ in range(30):
        try:
            data = api_json(
                session,
                "POST",
                f"{API_BASE}/upload/v2/file/upload_complete",
                token=token,
                headers={"Content-Type": "application/json"},
                json={"preuploadID": preupload_id},
            )
        except Pan123Error as e:
            if "still verifying" in str(e):
                time.sleep(1)
                continue
            raise
        if data.get("completed") and data.get("fileID"):
            return data["fileID"]
        time.sleep(1)
    raise Pan123Error("Upload was not completed")


def single_upload(session, token, parent_file_id, remote_path, path):
    """Single-step upload for small files (<100MB)."""
    domain_data = api_json(
        session,
        "GET",
        f"{API_BASE}/upload/v2/file/domain",
        token=token,
    )
    server = domain_data[0].rstrip("/")

    with path.open("rb") as f:
        file_bytes = f.read()

    files = {"file": (path.name, file_bytes, "application/octet-stream")}
    data = {
        "parentFileID": str(parent_file_id),
        "filename": remote_path,
        "etag": hashlib.md5(file_bytes).hexdigest(),
        "size": str(len(file_bytes)),
        "containDir": "true",
        "duplicate": "2",
    }
    result = api_json(
        session,
        "POST",
        f"{server}/upload/v2/file/single/create",
        token=token,
        data=data,
        files=files,
        timeout=(30, 600),
    )
    if result.get("completed") and result.get("fileID"):
        return result["fileID"]
    raise Pan123Error("single upload did not complete")


def upload_file(session, token, parent_file_id, local_root, path, remote_prefix):
    rel = path.relative_to(local_root).as_posix()
    remote_path = f"/{remote_prefix.strip('/')}/{rel}" if remote_prefix else f"/{rel}"
    size = path.stat().st_size

    # Use single-step upload for small files
    if size <= SINGLE_UPLOAD_MAX_BYTES:
        log(f"single upload {size}B")
        file_id = single_upload(session, token, parent_file_id, remote_path, path)
        log(f"done -> {mask(file_id)}")
        return file_id

    # Large file: chunked upload with parallel slices
    create_data = create_file(session, token, parent_file_id, remote_path, path)
    if create_data.get("reuse"):
        log(f"reuse -> {mask(create_data.get('fileID'))}")
        return create_data.get("fileID")

    upload_slices_parallel(token, create_data, path)
    file_id = complete_upload(session, token, create_data["preuploadID"])
    log(f"done -> {mask(file_id)}")
    return file_id


def main():
    parser = argparse.ArgumentParser(description="Upload git-over-cdn files to 123pan.")
    parser.add_argument("--source", default="dist/git-over-cdn")
    parser.add_argument("--parent-file-id", type=int, default=int(os.environ.get("PAN123_PARENT_FILE_ID", "0")))
    parser.add_argument("--remote-prefix", default=os.environ.get("PAN123_REMOTE_PREFIX", "AzurPilot_master"))
    args = parser.parse_args()

    client_id = os.environ["PAN123_CLIENT_ID"]
    client_secret = os.environ["PAN123_CLIENT_SECRET"]
    source = Path(args.source)

    session = requests.Session()
    token = get_access_token(session, client_id, client_secret)

    files = sorted(
        path for path in source.rglob("*")
        if path.is_file() and (path.name == "latest.json" or path.suffix == ".zip")
    )

    log(f"total {len(files)} file(s)")
    for path in files:
        try:
            upload_file(session, token, args.parent_file_id, source, path, args.remote_prefix)
        except Exception as e:
            log(f"FAIL: {type(e).__name__}")
            raise


if __name__ == "__main__":
    main()
