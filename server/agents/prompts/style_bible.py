"""Style Bible — the project's shared literary + period guide.

The four agents (intent parser, NPC agent, Director agent, resolver
auditor) all reference :func:`style_bible_for_era` to get a textual
anchor for the era they're about to render.

This is **content**, not logic.  Editing it does not affect the
state machine; it only changes the prompts the model sees.

Why a style bible
-----------------
Without a single source of truth for the prose register, the four
agents drift (NPC voice 2011 reads like a tweet; Director voice
2024 reads like a news headline).  The style bible is the constant.

The four eras the case_01 narrative touches are:
* ``2008`` — Tehran summer, college graduation, underground cinema
* ``2011`` — Tehran airport, late-autumn
* ``2024`` — Istanbul Karaköy cafe, autumn
* ``EPILOGUE`` — final-cinematic voice

We do **not** lock the prose to a single author.  Each era can
freely evoke Saramago / Pamuk / Modaressi / Farrokhzad without the
agents having to know it; the bible is the *register*, not the
sentence-by-sentence style.
"""

from __future__ import annotations

from typing import Final


# Bump when the bible changes in a way that materially changes the
# agent's behaviour.  Tests assert against this.
STYLE_BIBLE_VERSION: Final[str] = "1.0.0"


NARRATOR_VOICE_DEFAULT: Final[str] = (
    "第三人称旁观者：'你看到了 X'，'她把动作藏在工具盒里'，"
    "不用'你做了 X'。距离感比代入感更重要。付费解锁后才换成'我看到了 X'。"
)


# ---------------------------------------------------------------------------
# Per-era register
# ---------------------------------------------------------------------------


ERA_REGISTER: Final[dict[str, str]] = {
    "2008": (
        "2008 年夏，德黑兰大学、革命街旧书店、地下放映室。"
        "节奏：胶片转动 + 灯泡频闪 + 蝉鸣；"
        "语域：文学课学生腔（追问诗中'钥匙'的意象） + 德黑兰夏夜市井（石榴、旧票、糖罐铜勺）；"
        "句法：短句多，动词强，避免数字与英语术语；"
        "声音意象：放映机的咔嗒声、灯泡的嗡鸣、胶片头的重量；"
        "色调：闷热 / 黄昏透进窄窗 / 偶尔的地铁震动；"
        "克制：禁写'我爱你'；用'我到了''别松手''我迟到了'代替。"
    ),
    "2011": (
        "2011 年秋，德黑兰伊玛目霍梅尼国际机场·国际出发大厅。"
        "节奏：时钟秒针 + 模糊广播 + 行李箱滚轮；"
        "语域：翻译软件说明书的工程腔 + 机场告别的口语；"
        "句法：动词在前（'扣紧''推到''抬头'），宾语常省略；"
        "声音意象：广播的阿拉伯语名字、闸机滴声、未点的烟的烟盒摩擦声；"
        "色调：玻璃 + 不锈钢 + 早班机前的人群 + 烧过的咖啡味；"
        "克制：禁写'我会回来'；用行李牌背面的字符代替诺言。"
    ),
    "2024": (
        "2024 年秋，伊斯坦布尔·卡拉柯伊老咖啡馆 + 街口。"
        "节奏：老木门推开 + 雨后 + 红茶杯沿的摩挲；"
        "语域：中年莱拉 / 中年阿拉什的轻熟 + 卡拉柯伊老咖啡馆的距离感；"
        "句法：长句多，每句之间用停顿分隔，停顿是叙事工具；"
        "声音意象：土耳其语 + 波斯语 + 英语混杂的远景、机场方向牌下的交通灯倒计时；"
        "色调：银发与手背细纹 / 发黄开裂的书脊 / 模糊外语人声 / 倒过来的绿光；"
        "克制：禁写'如果当年我跟你走'；用同一句'我到了'重写 13 年。"
    ),
    "EPILOGUE": (
        "终章·另一个故事。电影尾声式旁白；"
        "节奏：路口信号灯倒计时 + 鞋跟敲石板 + 远处机场广播；"
        "语域：第三人称复数 + 终章独白；"
        "句法：把'她'与'他'换成'两个背对镜头的人'；"
        "声音意象：单音 + 城市底噪；"
        "色调：逆光 / 长焦 / 雨痕与玻璃；"
        "克制：禁写'从此'；允许'我们会有另一个故事'。"
    ),
    "general": (
        "默认旁观者声音：'你看到了 X'。"
        "不要'我做了 X'。距离感比代入感更重要。"
        "数字、邮箱、网址、电话号码——一律不写到旁白里。"
    ),
}


def style_bible_for_era(era: str) -> str:
    """Return the prose register for ``era``.

    Falls back to :data:`ERA_REGISTER['general']` when ``era`` is
    not one of the registered eras (canonical Era values are also
    accepted and mapped to the era-group that matches the case).
    """

    if era in ERA_REGISTER:
        return ERA_REGISTER[era]
    # Map the canonical 13 Era values to the closest case-01 era.
    # The four canonical eras that could conceivably appear in a
    # case_01 scene are pre_1911_qing (never) / 2012_present_ai_age
    # (2024) / present (2024) / epilogue (EPILOGUE).  Anything else
    # is a future case and falls back to general.
    if era in {"2012_present_ai_age", "present"}:
        return ERA_REGISTER["2024"]
    if era == "epilogue":
        return ERA_REGISTER["EPILOGUE"]
    return ERA_REGISTER["general"]


__all__ = [
    "STYLE_BIBLE_VERSION",
    "ERA_REGISTER",
    "NARRATOR_VOICE_DEFAULT",
    "style_bible_for_era",
]
