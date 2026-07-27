"""시작 지점 좌표에서 팀 배치를 유도한다.

지금까지 팀 배치는 유럽 맵 전용으로 손으로 적은 14칸 고정표였다. 임의의
맵을 받으려면 같은 개념을 좌표에서 유도해야 한다. 방위 구분은 그대로다 —
2팀은 서/동, 3팀은 북서·북동·남부, 4팀은 사분면.

SC2 좌표계에서 +y 가 북쪽이다(베이스 맵 실측: 북서 팀 P4~P7 의 y 가
176~245 로 가장 크다).

**단순 사분면 컷을 쓰지 않는다.** 중심을 기준으로 그냥 나누면 경계에 걸친
지점 하나 때문에 팀 인원이 5/2 로 쏠린다(베이스 맵의 P3 은 중심보다 y 가
2.5 크다). 그래서 팀 정원을 먼저 정하고, 방위 기준점에서 가까운 순으로
정원을 채운다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations


# 팀 번호 -> 방위. TEAM_REGION_LABELS 와 같은 번호 체계를 유지한다.
TEAM_ANCHORS: dict[int, dict[int, float]] = {
    2: {1: 180.0, 2: 0.0},
    3: {1: 135.0, 2: 45.0, 3: 270.0},
    4: {1: 135.0, 2: 45.0, 3: 225.0, 4: 315.0},
}

SUPPORTED_TEAM_MODES = tuple(sorted(TEAM_ANCHORS))


@dataclass(frozen=True)
class SlotPosition:
    """논리 슬롯 하나와 그 슬롯이 실제로 앉는 좌표."""

    slot: int
    x: float
    y: float


def team_sizes(player_count: int, team_mode: int) -> list[int]:
    """가능한 한 균등하게 나눈 팀별 정원의 대표값.

    14명 4팀이면 4/4/3/3 이다. 실제 배치에서 **어느** 팀이 여분을 갖는지는
    기하가 정한다(:func:`derive_team_layout` 가 모든 조합을 시도한다). 이
    함수는 목록에 보여줄 정원 분포만 돌려준다.
    """

    if team_mode not in TEAM_ANCHORS:
        raise ValueError(f"지원하지 않는 팀 모드입니다: {team_mode}")
    if player_count < team_mode:
        raise ValueError(
            f"플레이어 {player_count}명으로는 {team_mode}팀을 만들 수 없습니다."
        )
    base, remainder = divmod(player_count, team_mode)
    return [base + (1 if index < remainder else 0) for index in range(team_mode)]


def _balanced_quota_vectors(player_count: int, team_mode: int) -> list[tuple[int, ...]]:
    """각 팀이 floor 또는 ceil 인원을 갖는 모든 정원 조합.

    어느 팀이 여분 한 명을 갖는지를 미리 정하면 기하적으로 나쁜 배치가
    강제된다 — 베이스 맵에서 남쪽 끝 P14 가 북동 팀으로 끌려갔다. 조합을
    전부 시도하고 비용이 가장 낮은 것을 고른다.
    """

    base, remainder = divmod(player_count, team_mode)
    if remainder == 0:
        return [tuple([base] * team_mode)]
    vectors: list[tuple[int, ...]] = []
    for extras in combinations(range(team_mode), remainder):
        quota = [base] * team_mode
        for index in extras:
            quota[index] += 1
        vectors.append(tuple(quota))
    return vectors


def _optimal_assignment(
    slots: list[int], costs: dict[tuple[int, int], float], quota: tuple[int, ...]
) -> tuple[float, dict[int, int]] | None:
    """정원을 지키면서 총 방위 비용이 최소인 배정을 정확히 구한다.

    슬롯을 순서대로 훑는 DP 다. 상태는 팀별로 이미 채운 인원 수다. 팀이 최대
    4개, 슬롯이 최대 14개라 상태 공간이 작아 정확해를 그대로 구할 수 있다 —
    그리디는 여기서 실제로 틀린 답을 냈다.
    """

    team_count = len(quota)
    start = tuple([0] * team_count)
    best: dict[tuple[int, ...], tuple[float, dict[int, int]]] = {start: (0.0, {})}
    for slot in slots:
        nxt: dict[tuple[int, ...], tuple[float, dict[int, int]]] = {}
        for counts, (total, layout) in best.items():
            for index in range(team_count):
                if counts[index] >= quota[index]:
                    continue
                team = index + 1
                moved = list(counts)
                moved[index] += 1
                key = tuple(moved)
                candidate = total + costs[(slot, team)]
                current = nxt.get(key)
                if current is None or candidate < current[0]:
                    nxt[key] = (candidate, {**layout, slot: team})
        best = nxt
        if not best:
            return None
    return best.get(quota)


def _angle_degrees(x: float, y: float, center_x: float, center_y: float) -> float:
    angle = math.degrees(math.atan2(y - center_y, x - center_x))
    return angle + 360.0 if angle < 0.0 else angle


def _angular_distance(first: float, second: float) -> float:
    raw = abs(first - second)
    return min(raw, 360.0 - raw)


def derive_team_layout(
    positions: list[SlotPosition] | tuple[SlotPosition, ...], team_mode: int
) -> dict[int, int]:
    """슬롯 -> 팀 번호. ``positions`` 는 참가하는 슬롯만 담는다.

    각 슬롯의 방위각을 전체 중심에서 재고, 팀 인원이 균등하다는 제약 아래
    총 방위 비용이 최소인 배정을 고른다. 결과는 결정적이다.
    """

    if team_mode not in TEAM_ANCHORS:
        raise ValueError(f"지원하지 않는 팀 모드입니다: {team_mode}")
    ordered = sorted(positions, key=lambda position: position.slot)
    if not ordered:
        return {}
    if len(ordered) < team_mode:
        raise ValueError(
            f"플레이어 {len(ordered)}명으로는 {team_mode}팀을 만들 수 없습니다."
        )

    center_x = sum(position.x for position in ordered) / len(ordered)
    center_y = sum(position.y for position in ordered) / len(ordered)
    anchors = TEAM_ANCHORS[team_mode]

    costs: dict[tuple[int, int], float] = {}
    for position in ordered:
        angle = _angle_degrees(position.x, position.y, center_x, center_y)
        for team, anchor in anchors.items():
            costs[(position.slot, team)] = _angular_distance(angle, anchor)

    slots = [position.slot for position in ordered]
    best: tuple[float, dict[int, int]] | None = None
    for quota in _balanced_quota_vectors(len(ordered), team_mode):
        result = _optimal_assignment(slots, costs, quota)
        if result is None:
            continue
        if best is None or result[0] < best[0]:
            best = result

    if best is None:
        raise RuntimeError("팀 배치를 유도하지 못했습니다.")
    layout = best[1]

    unassigned = [slot for slot in slots if slot not in layout]
    if unassigned:
        raise RuntimeError(f"팀을 배정하지 못한 슬롯이 있습니다: {unassigned}")
    return layout


__all__ = [
    "SUPPORTED_TEAM_MODES",
    "TEAM_ANCHORS",
    "SlotPosition",
    "derive_team_layout",
    "team_sizes",
]
