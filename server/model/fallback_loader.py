"""Writer-authored fallback content loader.

The 4-level degradation chain in :mod:`server.model.degradation`
reaches for **writer-authored content** when the LLM is unavailable
or fails too many times.  This module is the file-system side of
that contract: it knows where the writer content lives on disk
(default: ``content/<case_slug>/fallbacks/``) and how to load it
into the runtime shape that the degradation chain consumes.

Content layout
--------------

::

    content/
      case_01_revolution_street/
        fallbacks/
          npc_lines.yaml        # characterId × actionType → line
          director_skips.yaml   # beatId → line
          hard_lines.yaml       # beatId → mainline
          persist_message.txt   # L4 player-facing message

Each file is YAML (or plain text) so writers can edit it without
touching code.  The loader returns a
:class:`degradation.ModelFallbackContent` that the chain uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Default content root
# ---------------------------------------------------------------------------


DEFAULT_CONTENT_ROOT: Path = (
    Path(__file__).resolve().parents[2] / "content"
)


# ---------------------------------------------------------------------------
# Fallback content shape (model-layer side)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ModelNPCFallbackLine:
    """A writer-authored NPC line, scoped to (characterId, actionType)."""

    characterId: str
    sceneId: str
    actionType: str
    line: str
    speechIntent: str = "remain_silent"


@dataclass(slots=True)
class ModelFallbackContent:
    """All writer fallback content for a single (case, scene)."""

    case_slug: str
    scene_id: str
    npc_lines: list[ModelNPCFallbackLine] = field(default_factory=list)
    director_skip_line: str = "（场景节拍暂时无法生成，由备选叙事接续）"
    hard_lines: dict[str, str] = field(default_factory=dict)
    persist_message: str = "服务暂不可用，本轮进度已为您保留。"

    def lookup_npc_line(
        self, *, characterId: str, actionType: str
    ) -> ModelNPCFallbackLine | None:
        # Exact match first
        for ln in self.npc_lines:
            if ln.characterId == characterId and ln.actionType == actionType:
                return ln
        # Action-only fallback
        for ln in self.npc_lines:
            if ln.actionType == actionType:
                return ln
        # Any line in this scene
        return self.npc_lines[0] if self.npc_lines else None

    def lookup_hard_line(self, beatId: str) -> str:
        return self.hard_lines.get(beatId, self.director_skip_line)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class FallbackContentLoader:
    """Load writer-authored fallbacks from the content tree.

    Parameters
    ----------
    content_root
        Path to the project's ``content/`` directory.  Defaults
        to :data:`DEFAULT_CONTENT_ROOT`.
    """

    def __init__(self, content_root: Path | str | None = None) -> None:
        self._root = Path(content_root) if content_root else DEFAULT_CONTENT_ROOT

    @property
    def content_root(self) -> Path:
        return self._root

    def load_for_scene(
        self,
        *,
        case_slug: str,
        scene_id: str,
    ) -> ModelFallbackContent:
        """Load the fallback content for a (case, scene).

        If the directory or files are missing, returns an empty
        :class:`ModelFallbackContent` with the defaults filled in.
        The degradation chain still works in this state — it just
        surfaces the generic defaults to the player.
        """

        fb_dir = self._root / case_slug / "fallbacks"
        result = ModelFallbackContent(case_slug=case_slug, scene_id=scene_id)

        if not fb_dir.is_dir():
            return result

        # ---- npc_lines.yaml --------------------------------------
        npc_path = fb_dir / "npc_lines.yaml"
        if npc_path.is_file():
            data = yaml.safe_load(npc_path.read_text(encoding="utf-8")) or {}
            for entry in data.get("lines", []):
                result.npc_lines.append(
                    ModelNPCFallbackLine(
                        characterId=str(entry.get("characterId", "")),
                        sceneId=str(entry.get("sceneId", scene_id)),
                        actionType=str(entry.get("actionType", "")),
                        line=str(entry.get("line", "")),
                        speechIntent=str(
                            entry.get("speechIntent", "remain_silent")
                        ),
                    )
                )

        # ---- director_skips.yaml ---------------------------------
        skip_path = fb_dir / "director_skips.yaml"
        if skip_path.is_file():
            data = yaml.safe_load(skip_path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and "line" in data:
                result.director_skip_line = str(data["line"])

        # ---- hard_lines.yaml -------------------------------------
        hard_path = fb_dir / "hard_lines.yaml"
        if hard_path.is_file():
            data = yaml.safe_load(hard_path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                for beat_id, line in data.items():
                    result.hard_lines[str(beat_id)] = str(line)

        # ---- persist_message.txt ---------------------------------
        msg_path = fb_dir / "persist_message.txt"
        if msg_path.is_file():
            text = msg_path.read_text(encoding="utf-8").strip()
            if text:
                result.persist_message = text

        return result

    def write_default_fallbacks(
        self,
        *,
        case_slug: str,
        scene_id: str,
    ) -> ModelFallbackContent:
        """Create a starter set of fallback files for ``(case_slug, scene_id)``.

        Called by W2-C / content-studio's "new scene" wizard when
        a scene is first authored, so the degradation chain has
        *something* to fall back to before writers flesh out the
        full script.  Returns the loaded :class:`ModelFallbackContent`.
        """

        fb_dir = self._root / case_slug / "fallbacks"
        fb_dir.mkdir(parents=True, exist_ok=True)

        npc_path = fb_dir / "npc_lines.yaml"
        if not npc_path.is_file():
            npc_path.write_text(
                _DEFAULT_NPC_LINES_YAML.format(scene_id=scene_id),
                encoding="utf-8",
            )

        skip_path = fb_dir / "director_skips.yaml"
        if not skip_path.is_file():
            skip_path.write_text(
                "line: （场景节拍暂时无法生成，由备选叙事接续）\n",
                encoding="utf-8",
            )

        hard_path = fb_dir / "hard_lines.yaml"
        if not hard_path.is_file():
            hard_path.write_text(
                "fallback_beat: （主线正在由备选脚本接续）\n",
                encoding="utf-8",
            )

        msg_path = fb_dir / "persist_message.txt"
        if not msg_path.is_file():
            msg_path.write_text(
                "服务暂不可用，本轮进度已为您保留。\n",
                encoding="utf-8",
            )

        return self.load_for_scene(case_slug=case_slug, scene_id=scene_id)


# ---------------------------------------------------------------------------
# Default templates
# ---------------------------------------------------------------------------


_DEFAULT_NPC_LINES_YAML = """# Writer-authored NPC fallback lines for {scene_id}.
# Each line pairs a (characterId, actionType) so the L1 fallback
# can pick the right tone.  Add at least one line per (character,
# action) the scene uses.
lines:
  - characterId: arash
    sceneId: {scene_id}
    actionType: comfort
    line: "[fallback] 阿拉什沉默片刻，摇了摇头。"
    speechIntent: remain_silent
  - characterId: leila
    sceneId: {scene_id}
    actionType: question
    line: "[fallback] 莱拉抬眼，灯光把她的影子拉得很长。"
    speechIntent: question
"""


__all__ = [
    "DEFAULT_CONTENT_ROOT",
    "ModelNPCFallbackLine",
    "ModelFallbackContent",
    "FallbackContentLoader",
]
