"""Tests for the Kubernetes operator (ZfrogJob -> batch/v1 Job).

The operator talks to the API server over httpx, so a respx-backed
`httpx.AsyncClient` is injected into `K8sClient` and every request is asserted
against the real API paths the operator builds.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from zfrog.config import settings
from zfrog.k8s.operator import (
    K8sClient,
    Operator,
    api_base,
    build_job_manifest,
    child_job_name,
    job_phase_to_cr_status,
    load_token,
)

API = "https://k8s.test:6443"
CRD = f"{API}/apis/zfrog.io/v1alpha1/namespaces/default/zfrogjobs"
JOBS = f"{API}/apis/batch/v1/namespaces/default/jobs"
DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy" / "k8s"

@pytest.fixture(autouse=True)
def _k8s_settings(tmp_path, monkeypatch):
    """Isolate the operator settings from the developer machine / real cluster."""
    monkeypatch.setattr(settings, "k8s_namespace", "default")
    monkeypatch.setattr(settings, "k8s_worker_image", "zfrog-worker:latest")
    monkeypatch.setattr(settings, "k8s_api_server", None)
    monkeypatch.setattr(settings, "k8s_token_file", tmp_path / "missing-token")
    monkeypatch.setattr(settings, "k8s_ca_file", tmp_path / "missing-ca.crt")

def _client(http: httpx.AsyncClient) -> K8sClient:
    return K8sClient(base_url=API, token="sa-token", namespace="default", client=http)

def _cr(name: str = "docs", phase: str | None = None, **spec) -> dict:
    cr: dict = {
        "apiVersion": "zfrog.io/v1alpha1",
        "kind": "ZfrogJob",
        "metadata": {"name": name, "namespace": "default"},
        "spec": {"url": "https://example.com", "mode": "mirror", **spec},
    }
    if phase is not None:
        cr["status"] = {"phase": phase, "jobName": child_job_name(name)}
    return cr

# ── build_job_manifest ──

def test_build_job_manifest_uses_cr_values():
    cr = {
        "metadata": {"name": "docs", "namespace": "crawl"},
        "spec": {
            "url": "https://example.com/docs",
            "mode": "scrape",
            "maxDepth": 3,
            "ttlSecondsAfterFinished": 120,
        },
    }
    manifest = build_job_manifest(cr, image="zfrog-worker:test")
    assert manifest["apiVersion"] == "batch/v1"
    assert manifest["kind"] == "Job"
    assert manifest["metadata"]["name"] == "docs-job"
    assert manifest["metadata"]["namespace"] == "crawl"
    assert manifest["metadata"]["labels"] == {"app": "zfrog-worker", "zfrog.io/zfrogjob": "docs"}
    spec = manifest["spec"]
    assert spec["backoffLimit"] == 0
    assert spec["ttlSecondsAfterFinished"] == 120
    assert spec["template"]["spec"]["restartPolicy"] == "Never"
    assert spec["template"]["metadata"]["labels"] == manifest["metadata"]["labels"]
    container = spec["template"]["spec"]["containers"][0]
    assert container["image"] == "zfrog-worker:test"
    assert {e["name"]: e["value"] for e in container["env"]} == {
        "ZFROG_JOB_URL": "https://example.com/docs",
        "ZFROG_JOB_MODE": "scrape",
        "ZFROG_JOB_MAX_DEPTH": "3",
    }

def test_build_job_manifest_defaults():
    manifest = build_job_manifest({"metadata": {"name": "docs"}, "spec": {"url": "https://a.test", "mode": "pdf"}})
    spec = manifest["spec"]
    assert "ttlSecondsAfterFinished" not in spec
    assert manifest["metadata"]["namespace"] == settings.k8s_namespace
    container = spec["template"]["spec"]["containers"][0]
    assert container["image"] == settings.k8s_worker_image
    assert {"name": "ZFROG_JOB_MAX_DEPTH", "value": "1"} in container["env"]

def test_build_job_manifest_requires_url():
    with pytest.raises(ValueError):
        build_job_manifest({"metadata": {"name": "docs"}, "spec": {"mode": "mirror"}})

def test_build_job_manifest_requires_mode():
    with pytest.raises(ValueError):
        build_job_manifest({"metadata": {"name": "docs"}, "spec": {"url": "https://a.test"}})

# ── job_phase_to_cr_status ──

def test_job_phase_pending_without_status():
    status = job_phase_to_cr_status({"metadata": {"name": "docs-job"}})
    assert status == {"phase": "Pending", "message": "Job created", "jobName": "docs-job", "completedAt": None}

def test_job_phase_running_with_active_pods():
    status = job_phase_to_cr_status({"metadata": {"name": "docs-job"}, "status": {"active": 2, "startTime": "t0"}})
    assert status["phase"] == "Running"
    assert status["jobName"] == "docs-job"
    assert status["completedAt"] is None

def test_job_phase_succeeded():
    job = {"metadata": {"name": "docs-job"}, "status": {"succeeded": 1, "completionTime": "2026-01-01T00:00:09Z"}}
    status = job_phase_to_cr_status(job)
    assert status["phase"] == "Succeeded"
    assert status["completedAt"] == "2026-01-01T00:00:09Z"

def test_job_phase_failed_condition():
    job = {
        "metadata": {"name": "docs-job"},
        "status": {
            "failed": 1,
            "conditions": [{"type": "Failed", "status": "True", "message": "BackoffLimitExceeded"}],
        },
    }
    status = job_phase_to_cr_status(job)
    assert status["phase"] == "Failed"
    assert status["message"] == "BackoffLimitExceeded"

# ── reconcile_once ──

async def test_reconcile_creates_job_and_patches_pending():
    async with httpx.AsyncClient() as http:
        client = _client(http)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(CRD).mock(return_value=httpx.Response(200, json={"items": [_cr(mode="scrape")]}))
            mock.get(f"{JOBS}/docs-job").mock(return_value=httpx.Response(404, json={"kind": "Status"}))
            create = mock.post(JOBS).mock(return_value=httpx.Response(201, json={"metadata": {"name": "docs-job"}}))
            patch = mock.patch(f"{CRD}/docs").mock(return_value=httpx.Response(200, json={}))
            acted = await Operator(client=client, image="zfrog-worker:test").reconcile_once()
    assert acted == ["docs"]
    assert create.call_count == 1
    request = create.calls[0].request
    assert request.headers["authorization"] == "Bearer sa-token"
    body = json.loads(request.content)
    assert body["metadata"]["name"] == "docs-job"
    container = body["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "zfrog-worker:test"
    assert {"name": "ZFROG_JOB_MODE", "value": "scrape"} in container["env"]
    assert json.loads(patch.calls[0].request.content) == {"status": {"phase": "Pending", "jobName": "docs-job"}}

async def test_reconcile_patches_running_when_job_active():
    job = {"metadata": {"name": "docs-job"}, "status": {"active": 1}}
    async with httpx.AsyncClient() as http:
        client = _client(http)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(CRD).mock(return_value=httpx.Response(200, json={"items": [_cr(phase="Pending")]}))
            mock.get(f"{JOBS}/docs-job").mock(return_value=httpx.Response(200, json=job))
            create = mock.post(JOBS).mock(return_value=httpx.Response(201, json={}))
            patch = mock.patch(f"{CRD}/docs").mock(return_value=httpx.Response(200, json={}))
            acted = await Operator(client=client).reconcile_once()
    assert acted == ["docs"]
    assert not create.called
    assert json.loads(patch.calls[0].request.content)["status"]["phase"] == "Running"

async def test_reconcile_patches_succeeded_when_job_succeeded():
    job = {"metadata": {"name": "docs-job"}, "status": {"succeeded": 1, "completionTime": "2026-01-01T00:00:09Z"}}
    async with httpx.AsyncClient() as http:
        client = _client(http)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(CRD).mock(return_value=httpx.Response(200, json={"items": [_cr(phase="Running")]}))
            mock.get(f"{JOBS}/docs-job").mock(return_value=httpx.Response(200, json=job))
            patch = mock.patch(f"{CRD}/docs").mock(return_value=httpx.Response(200, json={}))
            acted = await Operator(client=client).reconcile_once()
    assert acted == ["docs"]
    status = json.loads(patch.calls[0].request.content)["status"]
    assert status["phase"] == "Succeeded"
    assert status["completedAt"] == "2026-01-01T00:00:09Z"

async def test_reconcile_skips_cr_in_final_phase():
    async with httpx.AsyncClient() as http:
        client = _client(http)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(CRD).mock(return_value=httpx.Response(200, json={"items": [_cr(phase="Succeeded")]}))
            create = mock.post(JOBS).mock(return_value=httpx.Response(201, json={}))
            patch = mock.patch(f"{CRD}/docs").mock(return_value=httpx.Response(200, json={}))
            get_job = mock.get(f"{JOBS}/docs-job").mock(return_value=httpx.Response(200, json={}))
            acted = await Operator(client=client).reconcile_once()
    assert acted == []
    assert not create.called
    assert not patch.called
    assert not get_job.called

async def test_reconcile_noop_when_phase_matches():
    job = {"metadata": {"name": "docs-job"}, "status": {"active": 1}}
    async with httpx.AsyncClient() as http:
        client = _client(http)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(CRD).mock(return_value=httpx.Response(200, json={"items": [_cr(phase="Running")]}))
            mock.get(f"{JOBS}/docs-job").mock(return_value=httpx.Response(200, json=job))
            patch = mock.patch(f"{CRD}/docs").mock(return_value=httpx.Response(200, json={}))
            acted = await Operator(client=client).reconcile_once()
    assert acted == []
    assert not patch.called

async def test_one_failing_cr_does_not_block_the_others():
    bad, good = _cr("bad"), _cr("good")
    running_job = {"metadata": {"name": "good-job"}, "status": {"active": 1}}
    async with httpx.AsyncClient() as http:
        client = _client(http)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(CRD).mock(return_value=httpx.Response(200, json={"items": [bad, good]}))
            mock.get(f"{JOBS}/bad-job").mock(return_value=httpx.Response(404, json={"kind": "Status"}))
            mock.post(JOBS).mock(return_value=httpx.Response(201, json={}))
            mock.patch(f"{CRD}/bad").mock(return_value=httpx.Response(500, json={"kind": "Status", "code": 500}))
            mock.get(f"{JOBS}/good-job").mock(return_value=httpx.Response(200, json=running_job))
            good_patch = mock.patch(f"{CRD}/good").mock(return_value=httpx.Response(200, json={}))
            acted = await Operator(client=client).reconcile_once()
    assert acted == ["good"]
    assert json.loads(good_patch.calls[0].request.content)["status"]["phase"] == "Running"

async def test_reconcile_deletes_child_job_of_terminating_cr():
    cr = _cr("docs")
    cr["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    async with httpx.AsyncClient() as http:
        client = _client(http)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(CRD).mock(return_value=httpx.Response(200, json={"items": [cr]}))
            mock.get(f"{JOBS}/docs-job").mock(return_value=httpx.Response(200, json={"metadata": {"name": "docs-job"}}))
            delete = mock.delete(f"{JOBS}/docs-job").mock(return_value=httpx.Response(200, json={}))
            create = mock.post(JOBS).mock(return_value=httpx.Response(201, json={}))
            patch = mock.patch(f"{CRD}/docs").mock(return_value=httpx.Response(200, json={}))
            acted = await Operator(client=client).reconcile_once()
    assert acted == ["docs"]
    assert delete.call_count == 1
    assert not create.called
    assert not patch.called

async def test_reconcile_tolerates_missing_child_job_on_delete():
    cr = _cr("docs")
    cr["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
    async with httpx.AsyncClient() as http:
        client = _client(http)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(CRD).mock(return_value=httpx.Response(200, json={"items": [cr]}))
            mock.get(f"{JOBS}/docs-job").mock(return_value=httpx.Response(404, json={"kind": "Status"}))
            delete = mock.delete(f"{JOBS}/docs-job").mock(return_value=httpx.Response(200, json={}))
            acted = await Operator(client=client).reconcile_once()
    assert acted == []
    assert not delete.called

# ── client plumbing ──

async def test_client_builds_namespaced_paths_and_sends_bearer_token():
    async with httpx.AsyncClient() as http:
        client = K8sClient(base_url=API, token="tok", namespace="crawl", client=http)
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(f"{API}/apis/zfrog.io/v1alpha1/namespaces/crawl/zfrogjobs").mock(
                return_value=httpx.Response(200, json={"items": [{"metadata": {"name": "a"}}]})
            )
            items = await client.list_zfrogjobs()
    assert items == [{"metadata": {"name": "a"}}]
    assert route.calls[0].request.headers["authorization"] == "Bearer tok"

async def test_get_job_returns_none_on_404_and_lists_by_selector():
    async with httpx.AsyncClient() as http:
        client = _client(http)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(f"{JOBS}/docs-job").mock(return_value=httpx.Response(404, json={"kind": "Status"}))
            assert await client.get_job("docs-job") is None
            listed = mock.get(JOBS, params={"labelSelector": "zfrog.io/zfrogjob=docs"}).mock(
                return_value=httpx.Response(200, json={"items": [{"metadata": {"name": "docs-job"}}]})
            )
            jobs = await client.list_jobs("zfrog.io/zfrogjob=docs")
    assert jobs == [{"metadata": {"name": "docs-job"}}]
    assert listed.called

def test_load_token_missing_file_returns_none(tmp_path):
    assert load_token(tmp_path / "nope") is None

def test_load_token_strips_whitespace(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("  sa-token\n", encoding="utf-8")
    assert load_token(token_file) == "sa-token"

def test_load_token_blank_file_returns_none(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("\n", encoding="utf-8")
    assert load_token(token_file) is None

def test_api_base_prefers_explicit_setting(monkeypatch):
    monkeypatch.setattr(settings, "k8s_api_server", "https://api.example:6443/")
    assert api_base() == "https://api.example:6443"

def test_api_base_uses_in_cluster_url_when_token_exists(tmp_path, monkeypatch):
    token_file = tmp_path / "token"
    token_file.write_text("sa-token", encoding="utf-8")
    monkeypatch.setattr(settings, "k8s_token_file", token_file)
    assert api_base() == "https://kubernetes.default.svc"

def test_api_base_falls_back_to_localhost():
    assert api_base() == "http://localhost:8000"

# ── deploy manifests ──

MANIFEST_KINDS = {
    "crd.yaml": ["CustomResourceDefinition"],
    "rbac.yaml": ["ServiceAccount", "ClusterRole", "ClusterRoleBinding"],
    "operator.yaml": ["Deployment"],
    "worker.yaml": ["Deployment"],
    "example-job.yaml": ["ZfrogJob"],
}

@pytest.mark.parametrize("name", sorted(MANIFEST_KINDS))
def test_manifest_exists_and_is_not_empty(name):
    path = DEPLOY_DIR / name
    assert path.is_file(), f"{path} is missing"
    assert path.read_text(encoding="utf-8").strip(), f"{path} is empty"

@pytest.mark.parametrize("name,expected_kinds", sorted(MANIFEST_KINDS.items()))
def test_manifest_declares_expected_kinds(name, expected_kinds):
    text = (DEPLOY_DIR / name).read_text(encoding="utf-8")
    try:
        import yaml
    except ImportError:  # PyYAML is not a project dependency
        assert "apiVersion:" in text
        for kind in expected_kinds:
            assert f"kind: {kind}" in text
        pytest.skip("PyYAML unavailable: verified apiVersion/kind lines textually")
    kinds = [doc.get("kind") for doc in yaml.safe_load_all(text) if doc]
    assert kinds == expected_kinds

@pytest.mark.parametrize("name", ["crd.yaml", "rbac.yaml", "operator.yaml", "worker.yaml", "example-job.yaml"])
def test_manifest_is_well_formed_yaml(name):
    yaml = pytest.importorskip("yaml")
    docs = [doc for doc in yaml.safe_load_all((DEPLOY_DIR / name).read_text(encoding="utf-8")) if doc]
    assert docs
    for doc in docs:
        assert doc.get("apiVersion")
        assert doc.get("metadata", {}).get("name")

def test_crd_exposes_the_operator_contract():
    yaml = pytest.importorskip("yaml")
    crd = yaml.safe_load((DEPLOY_DIR / "crd.yaml").read_text(encoding="utf-8"))
    assert crd["spec"]["group"] == "zfrog.io"
    assert crd["spec"]["scope"] == "Namespaced"
    assert crd["spec"]["names"]["plural"] == "zfrogjobs"
    assert crd["spec"]["names"]["kind"] == "ZfrogJob"
    version = crd["spec"]["versions"][0]
    assert version["name"] == "v1alpha1"
    assert "status" in version["subresources"]
    columns = {c["name"]: c["jsonPath"] for c in version["additionalPrinterColumns"]}
    assert columns["URL"] == ".spec.url"
    assert columns["Mode"] == ".spec.mode"
    assert columns["Phase"] == ".status.phase"
    spec_schema = version["schema"]["openAPIV3Schema"]["properties"]["spec"]
    assert spec_schema["required"] == ["url", "mode"]
    assert spec_schema["properties"]["mode"]["enum"] == [
        "mirror",
        "scrape",
        "singlepage",
        "extract",
        "analyze",
        "compare",
        "ask",
        "pdf",
        "summarize",
    ]
    assert spec_schema["properties"]["maxDepth"]["default"] == 1
    status_schema = version["schema"]["openAPIV3Schema"]["properties"]["status"]
    assert set(status_schema["properties"]) == {"phase", "jobName", "message", "completedAt"}

def test_rbac_grants_the_verbs_the_operator_uses():
    yaml = pytest.importorskip("yaml")
    docs = [d for d in yaml.safe_load_all((DEPLOY_DIR / "rbac.yaml").read_text(encoding="utf-8")) if d]
    role = next(d for d in docs if d["kind"] == "ClusterRole")
    rules = {(r["apiGroups"][0], tuple(r["resources"])): set(r["verbs"]) for r in role["rules"]}
    assert rules[("zfrog.io", ("zfrogjobs", "zfrogjobs/status"))] >= {"get", "list", "watch", "patch", "update"}
    assert rules[("batch", ("jobs",))] >= {"get", "list", "watch", "create", "delete"}
    binding = next(d for d in docs if d["kind"] == "ClusterRoleBinding")
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    assert binding["subjects"][0]["kind"] == "ServiceAccount"
    assert binding["subjects"][0]["name"] == "zfrog-operator"

def test_operator_deployment_runs_the_module():
    yaml = pytest.importorskip("yaml")
    deployment = yaml.safe_load((DEPLOY_DIR / "operator.yaml").read_text(encoding="utf-8"))
    assert deployment["spec"]["template"]["spec"]["serviceAccountName"] == "zfrog-operator"
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] == ["python", "-m", "zfrog.k8s.operator"]
    assert container["resources"]["requests"]["cpu"]
    assert container["resources"]["limits"]["memory"]
    assert "livenessProbe" in container

def test_example_job_is_a_valid_zfrogjob():
    yaml = pytest.importorskip("yaml")
    cr = yaml.safe_load((DEPLOY_DIR / "example-job.yaml").read_text(encoding="utf-8"))
    assert cr["apiVersion"] == "zfrog.io/v1alpha1"
    assert cr["kind"] == "ZfrogJob"
    assert cr["spec"]["url"].startswith("https://")
    assert cr["spec"]["mode"] in {
        "mirror",
        "scrape",
        "singlepage",
        "extract",
        "analyze",
        "compare",
        "ask",
        "pdf",
        "summarize",
    }
    # The example must be reconcilable by the operator as written.
    assert build_job_manifest(cr)["metadata"]["name"] == f"{cr['metadata']['name']}-job"
