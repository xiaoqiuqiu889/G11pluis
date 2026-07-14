"""W4 end-to-end smoke test — exercises all 13 brief endpoints.

Usage::

    python tools/w4_e2e_smoke.py

Assumes the FastAPI server is running at http://127.0.0.1:8000.
Resets the database on every run (the smoke test is the canonical
sample; it should be repeatable).
"""
import json
import sys
import uuid
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method, path, body=None, timeout=10):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body}


def section(name):
    print(f"\n=== {name} ===")


def main():
    section("GET /health")
    status, body = call("GET", "/health")
    assert status == 200, body
    print(f"db={body['database']['db']} llm={body['llm']['isMock']} activeRuns={body['activeRuns']}")

    section("GET /v1/catalog")
    status, body = call("GET", "/v1/catalog")
    assert status == 200, body
    assert len(body["products"]) == 7, f"expected 7 products, got {len(body['products'])}"
    print(f"products={len(body['products'])}")

    section("GET /v1/entitlements")
    status, body = call("GET", "/v1/entitlements?userId=demo-user")
    assert status == 200, body
    # demo-user is auto-seeded on first run; the test against a
    # fresh DB has no entitlements until we create a run.
    print(f"entitlements={len(body['entitlements'])}")

    section("POST /v1/runs")
    status, body = call("POST", "/v1/runs", {
        "userId": "demo-user",
        "caseSlug": "case_01_revolution_street",
        "startSceneId": "photo_lab_2008",
        "startEra": "2008",
    })
    assert status == 200, body
    run_id = body["run"]["runId"]
    print(f"run={run_id}")

    section("GET /v1/runs/:id")
    status, body = call("GET", f"/v1/runs/{run_id}")
    assert status == 200, body
    print(f"currentSceneId={body['currentSceneId']} eventSequence={body['eventSequence']}")

    section("POST /v1/runs/:id/scenes/photo_lab_2008/enter")
    status, body = call("POST", f"/v1/runs/{run_id}/scenes/photo_lab_2008/enter", {
        "userId": "demo-user", "startEra": "2008",
    })
    assert status == 200, body
    print(f"scene={body['sceneId']} active.phase={body['active']['phase']}")

    section("POST /v1/runs/:id/actions (give photo_A → leila, plants photo_in_pocket)")
    status, body = call("POST", f"/v1/runs/{run_id}/actions", {
        "runId": run_id,
        "sceneId": "photo_lab_2008",
        "clientActionId": str(uuid.uuid4()),
        "expectedEventSequence": 1,
        "playerAction": {
            "actionType": "give",
            "actorId": "leila",
            "targetId": "leila",
            "evidenceIds": ["photo_A"],
            "utterance": "把这一张放进我包里",
            "tone": "neutral",
            "disclosureLevel": 0.5,
            "isDeceptive": False,
        },
        "clientVersion": "1.0.0",
    })
    assert status == 200, body
    print(f"eventSequence={body['eventSequence']} degraded={body['degraded']} latencyMs={body['latencyMs']}")

    section("POST /v1/runs/:id/actions (give photo_B → arash, plants photo_in_book)")
    status, body = call("POST", f"/v1/runs/{run_id}/actions", {
        "runId": run_id,
        "sceneId": "photo_lab_2008",
        "clientActionId": str(uuid.uuid4()),
        "expectedEventSequence": 2,
        "playerAction": {
            "actionType": "give",
            "actorId": "leila",
            "targetId": "arash",
            "evidenceIds": ["photo_B"],
            "utterance": "这一张你收好",
            "tone": "gentle",
            "disclosureLevel": 0.5,
            "isDeceptive": False,
        },
        "clientVersion": "1.0.0",
    })
    assert status == 200, body
    print(f"eventSequence={body['eventSequence']} degraded={body['degraded']} latencyMs={body['latencyMs']}")

    section("GET /v1/runs/:id/timeline")
    status, body = call("GET", f"/v1/runs/{run_id}/timeline")
    assert status == 200, body
    print(f"events={body['count']}")
    assert body["count"] == 2, "expected 2 events after two actions"

    section("GET /v1/runs/:id/archive (verifies decision 3 propagation)")
    status, body = call("GET", f"/v1/runs/{run_id}/archive")
    assert status == 200, body
    print(
        f"artifacts={len(body['artifacts'])} "
        f"beliefs={len(body['beliefs'])} "
        f"seeds={len(body['causalSeeds'])} "
        f"memories={len(body['memories'])} "
        f"modelCalls={len(body['modelCalls'])}"
    )
    # Decisions 3 sanity: photo_in_pocket and photo_in_book must
    # be present in the seed list (cross-era propagation).
    seed_ids = {s["seedId"] for s in body["causalSeeds"]}
    assert "photo_in_pocket" in seed_ids, f"photo_in_pocket not in {seed_ids}"
    assert "photo_in_book" in seed_ids, f"photo_in_book not in {seed_ids}"
    # The Resolver must have logged 2 LLM calls (NPC + Director).
    assert len(body["modelCalls"]) == 2, f"expected 2 model calls, got {len(body['modelCalls'])}"

    section("POST /v1/runs/:id/branches")
    status, body = call("POST", f"/v1/runs/{run_id}/branches", {
        "sourceRunId": run_id,
        "forkEventSequence": 2,
        "label": "Smoke branch",
    })
    assert status == 200, body
    print(f"branchId={body['branch']['branchId']}")

    section("POST /v1/analytics/events")
    status, body = call("POST", "/v1/analytics/events", {
        "userId": "demo-user",
        "runId": run_id,
        "eventName": "w4_e2e_smoke_completed",
        "payload": {"events": 2, "artifacts": 4, "seeds": 2},
        "clientVersion": "1.0.0",
    })
    assert status == 200, body
    print(f"eventId={body['event'].get('id')}")

    section("POST /v1/purchases/mock-confirm")
    status, body = call("POST", "/v1/purchases/mock-confirm", {
        "userId": "demo-user",
        "productId": "passport",
        "credits": 200,
        "meta": {"receiptId": "smoke-receipt-001"},
    })
    assert status == 200, body
    print(f"entitlement.scope={body['entitlement']['scope']} credits={body['entitlement']['credits']}")

    section("POST /v1/runs/:id/resume")
    status, body = call("POST", f"/v1/runs/{run_id}/resume", {"userId": "demo-user"})
    assert status == 200, body
    print(f"resumed.phase={body['active']['phase']} eventSeq={body['active']['eventSequence']}")

    section("GET /v1/catalog (post-purchase; should still list all 7)")
    status, body = call("GET", "/v1/catalog")
    assert status == 200, body
    assert len(body["products"]) == 7

    print("\n[OK] All 13 endpoints exercised. Decision 3 propagation verified.")
    print(f"  run={run_id}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"\n✗ FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
