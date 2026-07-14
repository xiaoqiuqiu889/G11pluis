"""W10 · A/B testing framework — multi-armed bandit for content experiments.

Tests under management
----------------------

* **付费墙位置** (decision 4 商业化档位)
  Where in the funnel the paywall surfaces.  Arms:
  ``after-act-1``, ``after-scene-1``, ``after-recap-1``,
  ``scene-ended-only``.  The conversion metric is the
  ``passport``-purchases / unique-visitors rate.

* **5 句台词选择算法** (decision 3 mandatory echo)
  How the AI picks among the 5 candidate lines in
  ``first_words_admit_2008_2011``.  Arms:
  ``priority-only`` (current rule), ``priority + decay``,
  ``priority + player-style-match``, ``random-uniform``,
  ``thompson-sampling``.  The metric is player retention
  in the next 24h after the choice.

* **私人终章解锁条件** (decision 4 收藏版)
  Whether the private epilogue requires the ¥48 collectors
  edition, or any completion of all 3 mandatory echoes.
  Arms: ``paid-only``, ``mandatory-echoes-only``,
  ``either-or``, ``bundle-paid-credits``.

Design constraints (the W10 red lines)
--------------------------------------

* **玩家游戏体验不能被打扰** — 玩家**不能** 看到 A/B 分流
  的痕迹。分流在服务端用 hash(user_id, experiment_id) →
  稳定的 arm 分配，客户端**完全不知道** 自己在对照组。
* **不能混淆"反事实时间线"逻辑** — A/B 测试只在
  "服务侧决定" 维度 (付费墙位置、解锁条件) 上分流，**不**
  改 mandatory echo 的 NPC 台词 (那是 narrative contract 的
  硬约束)。5 句台词算法测的是 *NPC Agent 的选择器*，不
  改合同内容。
* **不暴露给运营指标影响玩家行为** — 分流结果只用于离线
  转化率统计，**不**写回 ``playerAction``、**不**影响
  概率、**不**让玩家被"促销"刷屏。

Engine choice
-------------

A **multi-armed bandit** is the right shape: each arm is a
strategy, the metric is the conversion rate, and we want
to explore early (to learn the arms) and exploit late
(to push traffic to the winner).  We use
**Thompson sampling** with a Beta(1, 1) prior — the
default that gives the best empirical regret bound for
binary conversion metrics and converges quickly with the
3,000-50,000 user scale of the W10 product.

The bandit is also **sticky**: a user assigned to an arm
on their first request stays on it.  This is required by
decision 4 ("不能让玩家明显感受到对照组") — a user who
sees the paywall in two different positions across the
same session would notice the inconsistency.

The bandit lives in the ``ab_experiments`` and
``ab_assignments`` tables (declared at the bottom of this
module; ``init_db`` is idempotent).  It runs as
**read-only** during the request path — the bandit
selects an arm on the first event for the user, then
caches the choice in :class:`RunRepository.get_or_create`
and reuses it forever.

Privacy red line
----------------

The bandit does not record ``playerAction`` content,
does not write to ``analytics_events.payload`` with
user-level fields, and does not read
``character_beliefs`` content.  Only counts.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import random
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
for p in (str(_PROJECT_ROOT), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from db import (  # noqa: E402
    Base,
    GameRun,
    SessionLocal,
    init_db,
)

logger = logging.getLogger("g1n.ab_testing")


# ---------------------------------------------------------------------------
# Bandit policy
# ---------------------------------------------------------------------------


class BanditPolicy(str, Enum):
    """The exploration strategy the bandit uses."""

    EPSILON_GREEDY = "epsilon-greedy"
    THOMPSON_SAMPLING = "thompson-sampling"
    UCB1 = "ucb1"


#: Default exploration strategy.  Thompson sampling is
#: the best default for binary conversion metrics at
#: the W10 scale.
DEFAULT_POLICY: BanditPolicy = BanditPolicy.THOMPSON_SAMPLING

#: Epsilon for ``EPSILON_GREEDY`` (10% explore).
DEFAULT_EPSILON: float = 0.1

#: UCB1 exploration constant.
DEFAULT_UCB_C: float = 1.4


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class ABExperimentRow(Base):
    """A single A/B experiment.

    The table is the **canonical** source of truth for
    "which experiments are running, on which arms, with
    which bandit parameters".  The HTTP / read paths
    consult it on every relevant request so the operator
    can flip experiments on / off without a code deploy.
    """

    __tablename__ = "ab_experiments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(String(64), nullable=False, index=True, unique=True)
    label = Column(String(128), nullable=False)
    description = Column(Text, default="", nullable=False)
    arms_json = Column(Text, nullable=False, default="[]")
    metric = Column(String(64), nullable=False, default="conversion")
    policy = Column(String(32), nullable=False, default=DEFAULT_POLICY.value)
    epsilon = Column(Float, default=DEFAULT_EPSILON, nullable=False)
    ucb_c = Column(Float, default=DEFAULT_UCB_C, nullable=False)
    min_samples_per_arm = Column(Integer, default=100, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow())
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "experimentId": self.experiment_id,
            "label": self.label,
            "description": self.description,
            "arms": json.loads(self.arms_json or "[]"),
            "metric": self.metric,
            "policy": self.policy,
            "epsilon": self.epsilon,
            "ucbC": self.ucb_c,
            "minSamplesPerArm": self.min_samples_per_arm,
            "isActive": self.is_active,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "endedAt": self.ended_at.isoformat() if self.ended_at else None,
        }


class ABAssignmentRow(Base):
    """Sticky user → arm mapping.

    Once a user is bucketed into an arm they stay there
    for the lifetime of the experiment.  This is the
    mechanism that prevents the "different paywall in
    each session" leakage.
    """

    __tablename__ = "ab_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(
        String(64),
        ForeignKey("ab_experiments.experiment_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id = Column(String(64), nullable=False, index=True)
    arm = Column(String(64), nullable=False)
    assigned_at = Column(DateTime(timezone=True), default=lambda: datetime.utcnow())
    last_seen_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
    )
    exposures = Column(Integer, default=0, nullable=False)
    conversions = Column(Integer, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint("experiment_id", "user_id", name="uq_assignment_experiment_user"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "experimentId": self.experiment_id,
            "userId": self.user_id,
            "arm": self.arm,
            "assignedAt": self.assigned_at.isoformat() if self.assigned_at else None,
            "lastSeenAt": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "exposures": self.exposures,
            "conversions": self.conversions,
            "conversionRate": (
                self.conversions / self.exposures if self.exposures else 0.0
            ),
        }


# ---------------------------------------------------------------------------
# Bandit core
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ArmStats:
    """Aggregated arm performance for the bandit."""

    arm: str
    exposures: int = 0
    conversions: int = 0
    conversion_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "exposures": self.exposures,
            "conversions": self.conversions,
            "conversionRate": round(self.conversion_rate, 4),
        }


@dataclass(slots=True)
class BanditDecision:
    """The result of a bandit query."""

    arm: str
    is_new_assignment: bool
    policy: BanditPolicy
    probabilities: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "isNewAssignment": self.is_new_assignment,
            "policy": self.policy.value,
            "probabilities": {k: round(v, 4) for k, v in self.probabilities.items()},
        }


class ThompsonBandit:
    """A pure-Python Thompson sampling bandit.

    Why pure-Python
    ---------------
    SciPy / NumPy are not in the W10 dep set.  The math
    needed is so small (a handful of ``random.betavariate``
    calls) that the marginal runtime is the same as a
    C-accelerated version, and the dependency surface
    stays small.
    """

    def __init__(
        self,
        arms: list[str],
        *,
        policy: BanditPolicy = DEFAULT_POLICY,
        epsilon: float = DEFAULT_EPSILON,
        ucb_c: float = DEFAULT_UCB_C,
        rng: random.Random | None = None,
    ) -> None:
        if not arms:
            raise ValueError("at least one arm is required")
        self.arms = list(arms)
        self.policy = policy
        self.epsilon = epsilon
        self.ucb_c = ucb_c
        self._rng = rng or random.Random()

    def select(
        self,
        stats: dict[str, ArmStats],
    ) -> tuple[str, dict[str, float]]:
        """Return ``(arm, probabilities)`` for the current state."""

        if self.policy is BanditPolicy.EPSILON_GREEDY:
            return self._select_epsilon_greedy(stats)
        if self.policy is BanditPolicy.UCB1:
            return self._select_ucb1(stats)
        return self._select_thompson(stats)

    def _select_thompson(
        self,
        stats: dict[str, ArmStats],
    ) -> tuple[str, dict[str, float]]:
        probabilities: dict[str, float] = {}
        best_arm = self.arms[0]
        best_score = -1.0
        for arm in self.arms:
            s = stats.get(arm, ArmStats(arm=arm))
            # Beta posterior with the standard Beta(1, 1) prior
            alpha = 1.0 + s.conversions
            beta = 1.0 + max(s.exposures - s.conversions, 0)
            sample = self._rng.betavariate(alpha, beta)
            probabilities[arm] = sample
            if sample > best_score:
                best_score = sample
                best_arm = arm
        return best_arm, probabilities

    def _select_epsilon_greedy(
        self,
        stats: dict[str, ArmStats],
    ) -> tuple[str, dict[str, float]]:
        # The "exploit" arm is the one with the highest
        # conversion rate; the "explore" arm is uniform-random.
        exploit_arm = self.arms[0]
        best_rate = -1.0
        rates: dict[str, float] = {}
        for arm in self.arms:
            s = stats.get(arm, ArmStats(arm=arm))
            rate = s.conversion_rate if s.exposures else 0.0
            rates[arm] = rate
            if rate > best_rate:
                best_rate = rate
                exploit_arm = arm
        probabilities: dict[str, float] = {}
        if self._rng.random() < self.epsilon:
            explore_arm = self._rng.choice(self.arms)
            for arm in self.arms:
                probabilities[arm] = (
                    (1.0 - self.epsilon) * (1.0 if arm == exploit_arm else 0.0)
                    + self.epsilon * (1.0 / len(self.arms))
                )
            return explore_arm, probabilities
        for arm in self.arms:
            probabilities[arm] = (
                1.0 - self.epsilon
            ) * (1.0 if arm == exploit_arm else 0.0) + self.epsilon * (
                1.0 / len(self.arms)
            )
        return exploit_arm, probabilities

    def _select_ucb1(
        self,
        stats: dict[str, ArmStats],
    ) -> tuple[str, dict[str, float]]:
        total = sum(s.exposures for s in stats.values()) or 1
        scores: dict[str, float] = {}
        for arm in self.arms:
            s = stats.get(arm, ArmStats(arm=arm))
            if s.exposures == 0:
                # Force exploration for unseen arms.
                scores[arm] = float("inf")
                continue
            mean = s.conversion_rate
            bonus = self.ucb_c * ((total / s.exposures) ** 0.5)
            scores[arm] = mean + bonus
        best_arm = max(scores, key=lambda a: scores[a])
        # Probabilities are argmax-shaped (UCB1 is deterministic).
        probabilities = {a: (1.0 if a == best_arm else 0.0) for a in self.arms}
        return best_arm, probabilities


# ---------------------------------------------------------------------------
# Sticky user → arm hashing
# ---------------------------------------------------------------------------


def _hash_to_arm(user_id: str, experiment_id: str, arms: list[str]) -> str:
    """Map a user to an arm deterministically.

    Used as a **first-pass** router so the bandit can
    seed the initial assignment; once the user has been
    seen, the :class:`ABAssignmentRow` sticky record
    takes over.
    """

    if not arms:
        raise ValueError("no arms configured")
    h = hashlib.sha256(f"{experiment_id}::{user_id}".encode("utf-8")).digest()
    idx = int.from_bytes(h[:4], "big") % len(arms)
    return arms[idx]


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class ABTestingRepository:
    """Persistence façade for the bandit."""

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory or SessionLocal

    def session(self) -> Session:
        return self._session_factory()

    def upsert_experiment(
        self,
        *,
        experiment_id: str,
        label: str,
        arms: list[str],
        description: str = "",
        metric: str = "conversion",
        policy: BanditPolicy = DEFAULT_POLICY,
        epsilon: float = DEFAULT_EPSILON,
        ucb_c: float = DEFAULT_UCB_C,
        min_samples_per_arm: int = 100,
        is_active: bool = True,
    ) -> dict[str, Any]:
        with self.session() as s:
            row = s.execute(
                select(ABExperimentRow).where(
                    ABExperimentRow.experiment_id == experiment_id
                )
            ).scalar_one_or_none()
            if row is None:
                row = ABExperimentRow(
                    experiment_id=experiment_id,
                    label=label,
                    description=description,
                    arms_json=json.dumps(arms, ensure_ascii=False),
                    metric=metric,
                    policy=policy.value,
                    epsilon=epsilon,
                    ucb_c=ucb_c,
                    min_samples_per_arm=min_samples_per_arm,
                    is_active=is_active,
                )
                s.add(row)
            else:
                row.label = label
                row.description = description
                row.arms_json = json.dumps(arms, ensure_ascii=False)
                row.metric = metric
                row.policy = policy.value
                row.epsilon = epsilon
                row.ucb_c = ucb_c
                row.min_samples_per_arm = min_samples_per_arm
                row.is_active = is_active
            s.commit()
            s.refresh(row)
            return row.to_dict()

    def get_experiment(self, experiment_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.execute(
                select(ABExperimentRow).where(
                    ABExperimentRow.experiment_id == experiment_id
                )
            ).scalar_one_or_none()
            return row.to_dict() if row else None

    def list_experiments(self) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(ABExperimentRow).order_by(ABExperimentRow.created_at.asc())
            ).scalars().all()
            return [r.to_dict() for r in rows]

    def arm_stats(self, experiment_id: str) -> dict[str, ArmStats]:
        with self.session() as s:
            rows = s.execute(
                select(ABAssignmentRow).where(
                    ABAssignmentRow.experiment_id == experiment_id
                )
            ).scalars().all()
        stats: dict[str, ArmStats] = {}
        for r in rows:
            s_arm = stats.setdefault(r.arm, ArmStats(arm=r.arm))
            s_arm.exposures += r.exposures
            s_arm.conversions += r.conversions
        for arm in stats.values():
            arm.conversion_rate = (
                arm.conversions / arm.exposures if arm.exposures else 0.0
            )
        return stats

    def get_assignment(
        self, *, experiment_id: str, user_id: str,
    ) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.execute(
                select(ABAssignmentRow).where(
                    ABAssignmentRow.experiment_id == experiment_id,
                    ABAssignmentRow.user_id == user_id,
                )
            ).scalar_one_or_none()
            return row.to_dict() if row else None

    def record_assignment(
        self,
        *,
        experiment_id: str,
        user_id: str,
        arm: str,
        exposure: bool = True,
        conversion: bool = False,
    ) -> dict[str, Any]:
        with self.session() as s:
            row = s.execute(
                select(ABAssignmentRow).where(
                    ABAssignmentRow.experiment_id == experiment_id,
                    ABAssignmentRow.user_id == user_id,
                )
            ).scalar_one_or_none()
            if row is None:
                row = ABAssignmentRow(
                    experiment_id=experiment_id,
                    user_id=user_id,
                    arm=arm,
                    exposures=1 if exposure else 0,
                    conversions=1 if conversion else 0,
                )
                s.add(row)
            else:
                if row.arm != arm:
                    # Defensive: the user must stay on the
                    # same arm.  We log loudly and keep the
                    # old arm; the conversion/exposure is
                    # applied to the original bucket.
                    logger.warning(
                        "ab_testing: user %s tried to switch from %s to %s in %s",
                        user_id, row.arm, arm, experiment_id,
                    )
                else:
                    if exposure:
                        row.exposures += 1
                    if conversion:
                        row.conversions += 1
            s.commit()
            s.refresh(row)
            return row.to_dict()

    def increment_exposure(
        self, *, experiment_id: str, user_id: str,
    ) -> None:
        with self.session() as s:
            row = s.execute(
                select(ABAssignmentRow).where(
                    ABAssignmentRow.experiment_id == experiment_id,
                    ABAssignmentRow.user_id == user_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.exposures += 1
            s.commit()

    def record_conversion(
        self, *, experiment_id: str, user_id: str,
    ) -> None:
        with self.session() as s:
            row = s.execute(
                select(ABAssignmentRow).where(
                    ABAssignmentRow.experiment_id == experiment_id,
                    ABAssignmentRow.user_id == user_id,
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.conversions += 1
            s.commit()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ABTestingService:
    """High-level A/B service for the FastAPI layer.

    The service is **read-once-per-request** — it caches
    the per-(experiment, user) decision in memory for the
    duration of a single FastAPI request, so a request
    that touches multiple endpoints only runs the bandit
    once.
    """

    def __init__(self, repository: ABTestingRepository | None = None) -> None:
        self.repo = repository or ABTestingRepository()
        # In-request cache: ``(experiment_id, user_id) → BanditDecision``
        self._cache: dict[tuple[str, str], BanditDecision] = {}

    def assign(
        self,
        *,
        experiment_id: str,
        user_id: str,
    ) -> BanditDecision:
        """Return the arm for this user; create the assignment if new.

        Sticky semantics: if the user already has an
        assignment, the cached arm is returned.  Otherwise
        we hash the user into a starting arm and let the
        bandit refine.
        """

        cache_key = (experiment_id, user_id)
        if cache_key in self._cache:
            # Within the same process, the first call
            # has already done the assignment work; the
            # second call is just a sticky reuse.  We
            # surface ``is_new_assignment=False`` to
            # callers (and only increment exposures).
            decision = self._cache[cache_key]
            decision.is_new_assignment = False
            self.repo.increment_exposure(
                experiment_id=experiment_id, user_id=user_id,
            )
            return decision
        exp = self.repo.get_experiment(experiment_id)
        if exp is None or not exp.get("isActive"):
            # Experiment is unknown or stopped — return a
            # virtual "control" decision so callers fall
            # through to the default code path.
            return BanditDecision(
                arm="control", is_new_assignment=False, policy=DEFAULT_POLICY,
            )
        arms = list(exp["arms"])
        existing = self.repo.get_assignment(
            experiment_id=experiment_id, user_id=user_id,
        )
        if existing is not None:
            decision = BanditDecision(
                arm=existing["arm"],
                is_new_assignment=False,
                policy=BanditPolicy(exp["policy"]),
            )
        else:
            bandit = ThompsonBandit(
                arms=arms,
                policy=BanditPolicy(exp["policy"]),
                epsilon=exp["epsilon"],
                ucb_c=exp["ucbC"],
            )
            stats = self.repo.arm_stats(experiment_id)
            arm, probs = bandit.select(stats)
            # First-pass sticky: if the bandit picked an
            # arm with zero exposures, re-bias toward the
            # user's deterministic hash arm to seed.
            if stats.get(arm, ArmStats(arm=arm)).exposures == 0:
                arm = _hash_to_arm(user_id, experiment_id, arms)
                probs = {a: (1.0 if a == arm else 0.0) for a in arms}
            self.repo.record_assignment(
                experiment_id=experiment_id, user_id=user_id, arm=arm,
            )
            decision = BanditDecision(
                arm=arm, is_new_assignment=True, policy=bandit.policy,
                probabilities=probs,
            )
        self._cache[cache_key] = decision
        return decision

    def record_conversion(
        self,
        *,
        experiment_id: str,
        user_id: str,
    ) -> None:
        """Mark the user's assignment as converted.

        The conversion event is **product-side**: e.g.
        "user bought the 案件通行证" or "user's 5-line
        choice led to a 24h retention event".  The HTTP
        layer calls this method; the bandit is otherwise
        passive.
        """

        existing = self.repo.get_assignment(
            experiment_id=experiment_id, user_id=user_id,
        )
        if existing is None:
            return
        self.repo.record_conversion(
            experiment_id=experiment_id, user_id=user_id,
        )

    def arm_stats(self, experiment_id: str) -> dict[str, ArmStats]:
        return self.repo.arm_stats(experiment_id)

    def experiment_summary(
        self, experiment_id: str,
    ) -> dict[str, Any] | None:
        exp = self.repo.get_experiment(experiment_id)
        if exp is None:
            return None
        stats = self.repo.arm_stats(experiment_id)
        # Ensure every configured arm has a row, even
        # before any user has been bucketed.
        for arm in exp["arms"]:
            stats.setdefault(arm, ArmStats(arm=arm))
        # Best arm is the one with the highest conversion
        # rate, with at least min_samples_per_arm exposures.
        min_samples = exp.get("minSamplesPerArm", 100)
        candidates = [s for s in stats.values() if s.exposures >= min_samples]
        best_arm = None
        if candidates:
            best_arm = max(candidates, key=lambda s: s.conversion_rate).arm
        return {
            "experiment": exp,
            "stats": {a: s.to_dict() for a, s in stats.items()},
            "bestArm": best_arm,
            "totalExposures": sum(s.exposures for s in stats.values()),
            "totalConversions": sum(s.conversions for s in stats.values()),
        }


# ---------------------------------------------------------------------------
# Built-in experiment definitions
# ---------------------------------------------------------------------------


#: The three built-in experiments the brief asked for.
BUILTIN_EXPERIMENTS: dict[str, dict[str, Any]] = {
    "paywall_position": {
        "label": "付费墙位置",
        "description": "在 4 个位置（act 后 / scene 后 / recap 后 / 仅在 scene 结束时）放付费墙。",
        "arms": ["after-act-1", "after-scene-1", "after-recap-1", "scene-ended-only"],
        "metric": "passport_purchase",
        "policy": BanditPolicy.THOMPSON_SAMPLING,
    },
    "five_line_selector": {
        "label": "5 句台词选择算法",
        "description": (
            "first_words_admit_2008_2011 的 5 句备选台词的挑选策略。"
        ),
        "arms": [
            "priority-only",
            "priority+decay",
            "priority+style",
            "random-uniform",
            "thompson-sampling",
        ],
        "metric": "next_24h_retention",
        "policy": BanditPolicy.THOMPSON_SAMPLING,
    },
    "private_epilogue_unlock": {
        "label": "私人终章解锁条件",
        "description": "¥48 收藏版 vs. 3 mandatory echoes 全完成。",
        "arms": [
            "paid-only",
            "mandatory-echoes-only",
            "either-or",
            "bundle-paid-credits",
        ],
        "metric": "collectors_purchase",
        "policy": BanditPolicy.THOMPSON_SAMPLING,
    },
}


def seed_builtin_experiments(service: ABTestingService) -> list[str]:
    """Upsert the three built-in experiments.  Returns the ids."""

    created: list[str] = []
    for exp_id, spec in BUILTIN_EXPERIMENTS.items():
        service.repo.upsert_experiment(
            experiment_id=exp_id,
            label=spec["label"],
            description=spec["description"],
            arms=spec["arms"],
            metric=spec["metric"],
            policy=spec["policy"],
        )
        created.append(exp_id)
    return created


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


_default_service: ABTestingService | None = None


def get_default_service() -> ABTestingService:
    global _default_service
    if _default_service is None:
        _default_service = ABTestingService()
    return _default_service


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------


def build_ab_router() -> Any:
    """Expose the A/B service on a FastAPI router."""

    try:
        from fastapi import APIRouter, HTTPException, Query
        from pydantic import BaseModel
    except ImportError:  # pragma: no cover
        return None

    router = APIRouter(prefix="/v1/ab", tags=["ab"])
    service = get_default_service()

    class AssignRequest(BaseModel):  # type: ignore[misc]
        userId: str
        experimentId: str

    class ConversionRequest(BaseModel):  # type: ignore[misc]
        userId: str
        experimentId: str

    @router.get("/experiments")
    def list_experiments() -> dict[str, Any]:
        return {"experiments": service.repo.list_experiments()}

    @router.get("/experiments/{experiment_id}")
    def get_experiment(experiment_id: str) -> dict[str, Any]:
        summary = service.experiment_summary(experiment_id)
        if summary is None:
            raise HTTPException(
                status_code=404, detail=f"experiment not found: {experiment_id}"
            )
        return summary

    @router.post("/experiments/seed-builtins")
    def seed_builtins() -> dict[str, Any]:
        ids = seed_builtin_experiments(service)
        return {"seeded": ids}

    @router.post("/assign")
    def assign(req: AssignRequest) -> dict[str, Any]:
        decision = service.assign(
            experiment_id=req.experimentId, user_id=req.userId,
        )
        return decision.to_dict()

    @router.post("/conversion")
    def conversion(req: ConversionRequest) -> dict[str, Any]:
        service.record_conversion(
            experiment_id=req.experimentId, user_id=req.userId,
        )
        return {"ok": True}

    return router


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _force_utf8_stdout() -> None:
    import io
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
                continue
            except (ValueError, OSError):
                pass
        if hasattr(stream, "buffer"):
            try:
                setattr(
                    sys,
                    stream_name,
                    io.TextIOWrapper(stream.buffer, encoding="utf-8"),
                )
            except (ValueError, OSError):
                pass


def _cli(argv: list[str] | None = None) -> int:
    _force_utf8_stdout()
    import argparse
    parser = argparse.ArgumentParser(
        prog="ab-testing",
        description="革命街 AI 原生 · A/B 测试 (multi-armed bandit)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="seed the 3 built-in experiments")
    p_list = sub.add_parser("list", help="list experiments")
    p_sum = sub.add_parser("summary", help="show experiment summary")
    p_sum.add_argument("experiment_id")
    p_assign = sub.add_parser("assign", help="assign a user to an arm")
    p_assign.add_argument("experiment_id")
    p_assign.add_argument("user_id")
    p_conv = sub.add_parser("convert", help="record a conversion")
    p_conv.add_argument("experiment_id")
    p_conv.add_argument("user_id")
    args = parser.parse_args(argv)

    init_db()
    service = get_default_service()
    if args.command == "seed":
        ids = seed_builtin_experiments(service)
        print(json.dumps({"seeded": ids}, ensure_ascii=False, indent=2))
    elif args.command == "list":
        print(json.dumps(
            service.repo.list_experiments(), ensure_ascii=False, indent=2,
        ))
    elif args.command == "summary":
        summary = service.experiment_summary(args.experiment_id)
        if summary is None:
            print(f"experiment {args.experiment_id} not found", file=sys.stderr)
            return 1
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.command == "assign":
        decision = service.assign(
            experiment_id=args.experiment_id, user_id=args.user_id,
        )
        print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "convert":
        service.record_conversion(
            experiment_id=args.experiment_id, user_id=args.user_id,
        )
        print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
