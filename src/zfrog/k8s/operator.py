"""Kubernetes operator for `ZfrogJob` custom resources.

The operator talks to the Kubernetes API server directly over `httpx` (no
client library, no extra dependency). For every `ZfrogJob` CR it ensures a
child `batch/v1` Job exists that runs the worker image, and mirrors the Job's
phase back into the CR status.

Run it with ``python -m zfrog.k8s.operator`` inside the cluster (see
``deploy/k8s/operator.yaml``) or from a machine with a kubeconfig-backed
``ZFROG_K8S_API_SERVER`` / ``ZFROG_K8S_TOKEN_FILE``.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from zfrog.config import settings

logger = logging.getLogger(__name__)

CRD_GROUP = "zfrog.io"
CRD_VERSION = "v1alpha1"
CRD_PLURAL = "zfrogjobs"
JOB_API_VERSION = "batch/v1"
IN_CLUSTER_API = "https://kubernetes.default.svc"
LOCAL_API = "http://localhost:8000"
FINAL_PHASES = ("Succeeded", "Failed")
JOB_SUFFIX = "-job"
REQUEST_TIMEOUT_S = 30.0

def load_token(path: Path | None = None) -> str | None:
    """Read the service-account bearer token, or None when unavailable."""
    token_file = Path(path) if path is not None else Path(settings.k8s_token_file)
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None

def api_base() -> str:
    """Resolve the API server URL: explicit setting, in-cluster, then localhost."""
    if settings.k8s_api_server:
        return settings.k8s_api_server.rstrip("/")
    if load_token() is not None:
        return IN_CLUSTER_API
    return LOCAL_API

def child_job_name(cr_name: str) -> str:
    """Name of the child Job owned by a ZfrogJob."""
    return f"{cr_name}{JOB_SUFFIX}"

def _as_int(value: Any) -> int:
    """Coerce a Kubernetes status counter to int, treating junk as 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

def _failed_condition(status: dict[str, Any]) -> dict[str, Any] | None:
    """Return the Job's `Failed` condition when it is currently true."""
    for condition in status.get("conditions") or []:
        if condition.get("type") == "Failed" and condition.get("status") == "True":
            return condition
    return None

class K8sClient:
    """Thin async Kubernetes API client scoped to one namespace."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        ca_file: Path | None = None,
        namespace: str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._client = client
        self._owns_client = client is None
        if base_url is None:
            injected_base = str(client.base_url) if client is not None else ""
            base_url = injected_base or api_base()
        self.base_url = base_url.rstrip("/")
        self.token = token if token is not None else load_token()
        self.ca_file = Path(ca_file) if ca_file is not None else Path(settings.k8s_ca_file)
        self.namespace = namespace or settings.k8s_namespace

    def _ensure_client(self) -> httpx.AsyncClient:
        """Return the injected client, or build and cache one."""
        if self._client is None:
            verify: Any = str(self.ca_file) if self.ca_file.exists() else True
            self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, verify=verify)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        """Close the HTTP client, but only when this instance created it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _prepare(self, path: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Build the absolute URL and headers for a request."""
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        headers = dict(kwargs.pop("headers", None) or {})
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
        headers.setdefault("Accept", "application/json")
        kwargs["headers"] = headers
        return url, kwargs

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Perform a request against the API server, raising on error status."""
        client = self._ensure_client()
        url, kwargs = self._prepare(path, kwargs)
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    async def _request_optional(self, method: str, path: str, **kwargs: Any) -> httpx.Response | None:
        """Perform a request, returning None instead of raising on 404."""
        client = self._ensure_client()
        url, kwargs = self._prepare(path, kwargs)
        response = await client.request(method, url, **kwargs)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response

    def _zfrogjob_path(self, name: str | None = None) -> str:
        base = f"/apis/{CRD_GROUP}/{CRD_VERSION}/namespaces/{self.namespace}/{CRD_PLURAL}"
        return f"{base}/{name}" if name else base

    def _job_path(self, name: str | None = None) -> str:
        base = f"/apis/batch/v1/namespaces/{self.namespace}/jobs"
        return f"{base}/{name}" if name else base

    async def list_zfrogjobs(self) -> list[dict]:
        """List every ZfrogJob in the operator's namespace."""
        response = await self.request("GET", self._zfrogjob_path())
        return list(response.json().get("items") or [])

    async def get_zfrogjob(self, name: str) -> dict | None:
        """Fetch one ZfrogJob, or None when it does not exist."""
        response = await self._request_optional("GET", self._zfrogjob_path(name))
        return response.json() if response is not None else None

    async def patch_zfrogjob_status(self, name: str, status: dict) -> dict:
        """Merge-patch the status subresource of a ZfrogJob."""
        response = await self.request(
            "PATCH",
            self._zfrogjob_path(name),
            json={"status": status},
            headers={"Content-Type": "application/merge-patch+json"},
        )
        return response.json()

    async def create_job(self, manifest: dict) -> dict:
        """Create a batch/v1 Job from a manifest."""
        response = await self.request("POST", self._job_path(), json=manifest)
        return response.json()

    async def get_job(self, name: str) -> dict | None:
        """Fetch one Job, or None when it does not exist."""
        response = await self._request_optional("GET", self._job_path(name))
        return response.json() if response is not None else None

    async def delete_job(self, name: str) -> None:
        """Delete a Job, ignoring a 404 (already gone)."""
        await self._request_optional("DELETE", self._job_path(name))

    async def list_jobs(self, label_selector: str) -> list[dict]:
        """List Jobs matching a label selector."""
        response = await self.request("GET", self._job_path(), params={"labelSelector": label_selector})
        return list(response.json().get("items") or [])

def build_job_manifest(cr: dict, image: str | None = None) -> dict:
    """Build the child `batch/v1` Job manifest for a ZfrogJob."""
    metadata = cr.get("metadata") or {}
    spec = cr.get("spec") or {}
    url = spec.get("url")
    mode = spec.get("mode")
    if not url:
        raise ValueError("ZfrogJob spec.url is required")
    if not mode:
        raise ValueError("ZfrogJob spec.mode is required")
    name = metadata.get("name") or "zfrog"
    labels = {"app": "zfrog-worker", "zfrog.io/zfrogjob": name}
    max_depth = spec.get("maxDepth")
    container = {
        "name": "worker",
        "image": image or settings.k8s_worker_image,
        "env": [
            {"name": "ZFROG_JOB_URL", "value": str(url)},
            {"name": "ZFROG_JOB_MODE", "value": str(mode)},
            {"name": "ZFROG_JOB_MAX_DEPTH", "value": str(1 if max_depth is None else max_depth)},
        ],
    }
    job_spec: dict[str, Any] = {
        "backoffLimit": 0,
        "template": {
            "metadata": {"labels": labels},
            "spec": {
                "restartPolicy": "Never",
                "containers": [container],
            },
        },
    }
    ttl = spec.get("ttlSecondsAfterFinished")
    if ttl is not None:
        job_spec["ttlSecondsAfterFinished"] = _as_int(ttl)
    return {
        "apiVersion": JOB_API_VERSION,
        "kind": "Job",
        "metadata": {
            "name": child_job_name(name),
            "namespace": metadata.get("namespace") or settings.k8s_namespace,
            "labels": labels,
        },
        "spec": job_spec,
    }

def job_phase_to_cr_status(job: dict) -> dict:
    """Map a batch/v1 Job status onto the ZfrogJob status subresource."""
    job_name = (job.get("metadata") or {}).get("name")
    status = job.get("status") or {}
    if not status:
        return {"phase": "Pending", "message": "Job created", "jobName": job_name, "completedAt": None}
    succeeded = _as_int(status.get("succeeded"))
    failed = _as_int(status.get("failed"))
    active = _as_int(status.get("active"))
    completion_time = status.get("completionTime")
    if succeeded > 0:
        return {
            "phase": "Succeeded",
            "message": f"Job completed ({succeeded} pod(s) succeeded)",
            "jobName": job_name,
            "completedAt": completion_time,
        }
    failure = _failed_condition(status)
    if failure is not None:
        return {
            "phase": "Failed",
            "message": failure.get("message") or failure.get("reason") or "Job failed",
            "jobName": job_name,
            "completedAt": completion_time,
        }
    if active > 0 and failed == 0:
        return {
            "phase": "Running",
            "message": f"Job running ({active} active pod(s))",
            "jobName": job_name,
            "completedAt": None,
        }
    return {"phase": "Pending", "message": "Job pending", "jobName": job_name, "completedAt": None}

class Operator:
    """Reconciles ZfrogJob custom resources into batch/v1 Jobs."""

    def __init__(
        self,
        client: K8sClient | None = None,
        image: str | None = None,
        reconcile_interval_s: float = 5.0,
    ):
        self.client = client or K8sClient()
        self.image = image
        self.reconcile_interval_s = reconcile_interval_s

    async def reconcile_once(self) -> list[str]:
        """Reconcile every ZfrogJob once; returns the names acted upon."""
        acted: list[str] = []
        try:
            crs = await self.client.list_zfrogjobs()
        except httpx.HTTPError as exc:
            logger.warning("could not list ZfrogJobs: %s", exc)
            return acted
        for cr in crs:
            name = (cr.get("metadata") or {}).get("name")
            if not name:
                logger.warning("skipping ZfrogJob without metadata.name")
                continue
            try:
                if await self._reconcile_cr(cr, name):
                    acted.append(name)
            except Exception as exc:  # one broken CR must not stall the others
                logger.warning("reconcile of ZfrogJob %s failed: %s", name, exc)
        return acted

    async def _reconcile_cr(self, cr: dict, name: str) -> bool:
        """Reconcile a single CR; True when the API server was written to."""
        metadata = cr.get("metadata") or {}
        status = cr.get("status") or {}
        job_name = child_job_name(name)
        if metadata.get("deletionTimestamp"):
            if await self.client.get_job(job_name) is not None:
                await self.client.delete_job(job_name)
                logger.info("deleted child Job %s of terminating ZfrogJob %s", job_name, name)
                return True
            return False
        if status.get("phase") in FINAL_PHASES:
            return False
        job = await self.client.get_job(job_name)
        if job is None:
            manifest = build_job_manifest(cr, self.image)
            manifest["metadata"]["namespace"] = self.client.namespace
            await self.client.create_job(manifest)
            await self.client.patch_zfrogjob_status(name, {"phase": "Pending", "jobName": job_name})
            logger.info("created Job %s for ZfrogJob %s", job_name, name)
            return True
        mapped = job_phase_to_cr_status(job)
        if mapped["phase"] != status.get("phase"):
            await self.client.patch_zfrogjob_status(name, mapped)
            logger.info("ZfrogJob %s -> %s", name, mapped["phase"])
            return True
        return False

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        """Reconcile in a loop until `stop_event` is set (or forever)."""
        stop = stop_event if stop_event is not None else asyncio.Event()
        logger.info(
            "operator started (namespace=%s, interval=%ss)",
            self.client.namespace,
            self.reconcile_interval_s,
        )
        while not stop.is_set():
            await self.reconcile_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.reconcile_interval_s)
            except (TimeoutError, asyncio.TimeoutError):
                continue
        logger.info("operator stopped")

async def _serve() -> None:
    """Run the operator with its own client until interrupted."""
    client = K8sClient()
    try:
        await Operator(client=client).run()
    finally:
        await client.aclose()

def main() -> None:
    """Console entry point used by the operator Deployment."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        logger.info("operator interrupted, shutting down")

if __name__ == "__main__":
    main()
