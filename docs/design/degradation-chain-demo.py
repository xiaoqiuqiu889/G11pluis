"""End-to-end demo of the model-layer 4-level degradation chain.

Run from project root:

    python docs/design/degradation-chain-demo.py

This script is the W3-A acceptance demo: it shows that when
the LLM misbehaves, the chain escalates monotonically through
L1 → L2 → L3 → L4 and that L3 is sticky (no LLM call when
already at L3).
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "server"))

from model import (  # noqa: E402
    FallbackContentLoader,
    ModelDegradationChain,
    ModelDegradationLevel,
    ModelFallbackContent,
    ModelNPCFallbackLine,
    MockProvider,
    run_with_chain,
    trigger_l1,
    trigger_l2,
    trigger_l3,
    trigger_l4,
)
from model.exceptions import (  # noqa: E402
    PersistFailureError,
    ProviderTimeoutError,
    SchemaValidationError,
)


def _build_fallback() -> ModelFallbackContent:
    return ModelFallbackContent(
        case_slug="case_01_revolution_street",
        scene_id="photo_lab_2008",
        npc_lines=[
            ModelNPCFallbackLine(
                characterId="arash", sceneId="photo_lab_2008",
                actionType="comfort",
                line="[writer] 阿拉什的目光落在相纸上，没有说话。",
                speechIntent="remain_silent",
            ),
            ModelNPCFallbackLine(
                characterId="leila", sceneId="photo_lab_2008",
                actionType="question",
                line="[writer] 莱拉侧过脸，轻声问了一句。",
                speechIntent="question",
            ),
        ],
        director_skip_line="[writer] 节拍暂时跳过，由备选叙事接续。",
        hard_lines={
            "beat_divide_photos": "[writer] 两人在暗房里分享相纸的沉默。",
            "beat_collect_photos": "[writer] 莱拉把相纸收进一只旧信封。",
        },
        persist_message="服务暂不可用，本轮进度已为您保留。",
    )


def _banner(title: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n{title}\n{bar}")


def main() -> None:
    fb = _build_fallback()
    chain = ModelDegradationChain(
        run_id=str(uuid.uuid4()),
        case_slug="case_01_revolution_street",
        scene_id="photo_lab_2008",
    )

    # ----------------------------------------------------------------------
    # L1 — single NPC timeout → writer NPC line
    # ----------------------------------------------------------------------
    _banner("L1 — single NPC task timeout")
    payload = trigger_l1(
        chain, fallback=fb,
        characterId="arash", actionType="comfort",
        error="provider timeout (4s)",
    )
    print(f"  level            = {payload.level.value}")
    print(f"  source           = {payload.source}")
    print(f"  characterId      = {payload.characterId}")
    print(f"  content          = {payload.content}")
    print(f"  chain.current    = {chain.current_level.value}")
    print(f"  consecutive_fail = {chain.consecutive_failures}")
    print(f"  records          = {len(chain.records)}")

    # ----------------------------------------------------------------------
    # L2 — single Director task timeout → beat skip line
    # ----------------------------------------------------------------------
    _banner("L2 — single Director task timeout")
    payload = trigger_l2(
        chain, fallback=fb,
        beat_id="beat_divide_photos",
        error="director call timeout (4s)",
    )
    print(f"  level            = {payload.level.value}")
    print(f"  source           = {payload.source}")
    print(f"  beat_id          = {payload.beat_id}")
    print(f"  content          = {payload.content}")
    print(f"  chain.current    = {chain.current_level.value}  (L2 wins over L1)")

    # ----------------------------------------------------------------------
    # L3 — two consecutive failures → no LLM, writer mainline
    # ----------------------------------------------------------------------
    _banner("L3 — two consecutive failures → writer mainline (no LLM)")

    # Fresh chain so the demo is independent of L1/L2 above.
    chain3 = ModelDegradationChain(
        run_id=str(uuid.uuid4()),
        scene_id="photo_lab_2008",
    )

    def _npc_boom() -> None:
        raise ProviderTimeoutError("simulated NPC timeout")

    call_count = {"n": 0}

    def _npc_counted_boom() -> None:
        call_count["n"] += 1
        raise ProviderTimeoutError(f"simulated NPC timeout (call #{call_count['n']})")

    print("  Attempt 1 (expect L1)...")
    r1 = run_with_chain(
        chain=chain3, fallback=fb,
        task_name="npc_proposer", primary_call=_npc_counted_boom,
    )
    print(f"    finish={r1[1]} level={r1[2]} primary_calls={call_count['n']}")

    print("  Attempt 2 (expect L3 — 2 consecutive failures)...")
    r2 = run_with_chain(
        chain=chain3, fallback=fb,
        task_name="npc_proposer", primary_call=_npc_counted_boom,
    )
    print(f"    finish={r2[1]} level={r2[2]} primary_calls={call_count['n']}")
    print(f"    payload.source = {r2[0].source}")
    print(f"    payload.beat   = {r2[0].beat_id}")
    print(f"    payload.text   = {r2[0].content}")

    print("  Attempt 3 (expect L3 sticky — NO LLM call)...")
    r3 = run_with_chain(
        chain=chain3, fallback=fb,
        task_name="npc_proposer", primary_call=_npc_counted_boom,
    )
    print(f"    finish={r3[1]} level={r3[2]} primary_calls={call_count['n']}")
    assert call_count["n"] == 2, "L3 short-circuit failed: primary_call was invoked"
    print("    [OK] primary_call was NOT invoked (L3 short-circuit)")

    # ----------------------------------------------------------------------
    # L4 — Resolver persist failure → player-facing message
    # ----------------------------------------------------------------------
    _banner("L4 — Resolver persist failure")
    payload = trigger_l4(chain3, fallback=fb, error="DB connection lost")
    print(f"  level            = {payload.level.value}")
    print(f"  source           = {payload.source}")
    print(f"  content          = {payload.content}")
    print(f"  chain.current    = {chain3.current_level.value}")

    # ----------------------------------------------------------------------
    # Monotonicity check
    # ----------------------------------------------------------------------
    _banner("Monotonicity — L3 must NOT drop back to L2")
    mono = ModelDegradationChain(run_id=str(uuid.uuid4()), scene_id="photo_lab_2008")
    trigger_l3(mono, fallback=fb, beat_id="b1", error="x")
    trigger_l2(mono, fallback=fb, beat_id="b2", error="y")  # attempt to drop
    trigger_l1(mono, fallback=fb, characterId="arash", actionType="comfort", error="z")
    assert mono.current_level == ModelDegradationLevel.L3
    print(f"  after L3→L2→L1 attempts: chain.current = {mono.current_level.value}")
    print(f"  records = {[(r.level.value, r.trigger) for r in mono.records]}")

    # ----------------------------------------------------------------------
    # End-to-end through the gateway
    # ----------------------------------------------------------------------
    _banner("End-to-end through the gateway")
    from model import ModelGateway, build_default_router, CostController, SchemaValidator

    # Use a mock so we don't hit the wire.
    mock = MockProvider()
    gw = ModelGateway(
        providers={"mock": mock},
        router=build_default_router(),
        cost_controller=CostController(),
        validator=SchemaValidator(),
        fallback_loader=FallbackContentLoader(),
    )
    run_id = str(uuid.uuid4())
    gw.start_run(run_id=run_id, scene_id="photo_lab_2008")
    print(f"  started run {run_id}")
    summary = gw.run_summary(run_id)
    print(f"  run_summary  = {summary.to_dict()}")
    gw.end_run(run_id)
    print("  ended run")

    print("\n*** demo complete ***")


if __name__ == "__main__":
    main()
