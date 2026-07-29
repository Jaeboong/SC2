"""맵이 우리 계층을 얼마나 받아줄 수 있는지 읽는 계층.

MPQ 를 읽는 쪽은 node(`tools/map_capabilities.cjs`)다. 파이썬은 그 JSON 을
받아 런처가 쓰는 형태로 감싸기만 한다 — MPQ 파서를 두 언어로 중복해서
들고 갈 이유가 없다.

여기서 나오는 값이 "몇 명, 몇 팀, 야생 저그 가능?"의 유일한 근거다. 맵이
정하는 상한이므로 사용자 설정으로 넘길 수 없다.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


CAPABILITIES_TOOL = Path("tools") / "map_capabilities.cjs"

# 논리 슬롯 P1~P14. P15 는 야생 저그, P16 은 중립이라 사람/커스텀 AI 가
# 앉을 수 없다. tools/build/map_capabilities.cjs 의 같은 상수와 짝이다.
MAX_PLAYER_SLOTS = 14

MIN_PLAYERS = 2
MAX_TEAMS = 4


def max_teams_for(player_count: int) -> int:
    """플레이어 수가 허용하는 팀 수 상한.

    2명은 2팀, 3명은 3팀, 4명부터 4팀이다. 팀이 플레이어보다 많으면 빈 팀이
    생겨 승리 판정이 이상해진다.
    """

    if player_count < MIN_PLAYERS:
        return 0
    return min(MAX_TEAMS, player_count)


@dataclass(frozen=True)
class StartLocation:
    id: int
    x: float
    y: float


@dataclass(frozen=True)
class PlayerStart:
    """논리 슬롯 하나가 실제로 앉는 좌표."""

    slot: int
    start_point: int
    x: float
    y: float


@dataclass(frozen=True)
class PlayableBounds:
    """카메라 경계. 미니맵 이미지가 덮는 사각형이 정확히 이것이다."""

    left: int
    bottom: int
    right: int
    top: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.top - self.bottom


@dataclass(frozen=True)
class MapGeometry:
    width: int
    height: int
    bounds: PlayableBounds


@dataclass(frozen=True)
class MapProfile:
    """한 맵의 수용 능력. 전부 맵에서 읽은 사실이며 설정이 아니다."""

    name: str
    path: Path
    readable: bool
    reason: str
    map_info_slots: int
    max_players: int
    geometry: MapGeometry | None
    start_locations: tuple[StartLocation, ...]
    player_starts: tuple[PlayerStart, ...]
    wild_zerg_town_halls: int
    has_minimap: bool
    prepared: bool
    preparable: bool

    @property
    def max_teams(self) -> int:
        return max_teams_for(self.max_players)

    @property
    def usable(self) -> bool:
        """런처 목록에 올릴 수 있는가.

        준비 표식이 없는 맵은 아직 못 쓴다 — `tools/build_team_map.cjs` 로
        한 번 준비해야 SC2TEAM 커스텀 블록이 생긴다. `preparable` 이 참이면
        그 준비가 가능하다는 뜻이다.
        """

        return self.readable and self.prepared

    def wild_zerg_available(self, active_player_count: int) -> tuple[bool, str]:
        """야생 저그를 켤 수 있는지와, 안 되면 그 이유.

        두 조건을 동시에 만족해야 한다. 선배치된 P15 저그 본진이 있어야 하고
        (없으면 중립 적대는 전투 유닛을 한 기도 만들지 못한다), 활성
        플레이어가 쓰고 남은 시작 지점이 하나 있어야 한다(P15 를 로비
        Computer 로 승격시킬 때 그 자리를 준다).
        """

        if not self.readable:
            return False, "맵을 읽을 수 없습니다."
        if self.wild_zerg_town_halls < 1:
            return False, "이 맵에는 P15 소유 저그 본진이 배치돼 있지 않습니다."
        if len(self.start_locations) <= active_player_count:
            return False, (
                f"여분 시작 지점이 없습니다 "
                f"(시작 지점 {len(self.start_locations)}, 활성 플레이어 {active_player_count})."
            )
        return True, ""


def _node_environment(project_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    shared = str(project_root / "tools" / "node_modules")
    existing = env.get("NODE_PATH")
    env["NODE_PATH"] = f"{shared}{os.pathsep}{existing}" if existing else shared
    return env


def _geometry_from_entry(raw: object) -> MapGeometry | None:
    if not isinstance(raw, dict):
        return None
    bounds = raw.get("bounds")
    if not isinstance(bounds, dict):
        return None
    return MapGeometry(
        width=int(raw.get("width", 0) or 0),
        height=int(raw.get("height", 0) or 0),
        bounds=PlayableBounds(
            left=int(bounds.get("left", 0) or 0),
            bottom=int(bounds.get("bottom", 0) or 0),
            right=int(bounds.get("right", 0) or 0),
            top=int(bounds.get("top", 0) or 0),
        ),
    )


def _profile_from_entry(entry: dict[str, object]) -> MapProfile:
    starts = tuple(
        StartLocation(id=int(item["id"]), x=float(item["x"]), y=float(item["y"]))
        for item in entry.get("startLocations", ())  # type: ignore[union-attr]
    )
    player_starts = tuple(
        PlayerStart(
            slot=int(item["slot"]),
            start_point=int(item["startPoint"]),
            x=float(item["x"]),
            y=float(item["y"]),
        )
        for item in entry.get("playerStarts", ())  # type: ignore[union-attr]
    )
    return MapProfile(
        name=str(entry.get("name", "")),
        path=Path(str(entry.get("path", ""))),
        readable=bool(entry.get("readable", False)),
        reason=str(entry.get("reason", "")),
        map_info_slots=int(entry.get("mapInfoSlots", 0) or 0),
        max_players=int(entry.get("maxPlayers", 0) or 0),
        geometry=_geometry_from_entry(entry.get("geometry")),
        start_locations=starts,
        player_starts=player_starts,
        wild_zerg_town_halls=int(entry.get("wildZergTownHalls", 0) or 0),
        has_minimap=bool(entry.get("hasMinimap", False)),
        prepared=bool(entry.get("prepared", False)),
        preparable=bool(entry.get("preparable", False)),
    )


def read_map_profiles(project_root: Path, *targets: Path) -> list[MapProfile]:
    """맵 파일이나 디렉터리를 받아 능력을 읽는다.

    읽을 수 없는 맵도 결과에 남는다(``readable=False`` 와 ``reason``). 런처가
    왜 못 쓰는지 보여줘야 하므로 조용히 빠뜨리지 않는다.
    """

    if not targets:
        return []
    tool = project_root / CAPABILITIES_TOOL
    if not tool.is_file():
        raise FileNotFoundError(f"맵 능력 판정 도구를 찾을 수 없습니다: {tool}")
    completed = subprocess.run(
        ["node", str(tool), *(str(target) for target in targets)],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_node_environment(project_root),
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"맵 능력 판정 실패: {detail}")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"맵 능력 판정 출력을 해석할 수 없습니다: {error}") from error
    return [_profile_from_entry(entry) for entry in report]


__all__ = [
    "MAX_PLAYER_SLOTS",
    "MAX_TEAMS",
    "MIN_PLAYERS",
    "MapGeometry",
    "MapProfile",
    "PlayableBounds",
    "PlayerStart",
    "StartLocation",
    "max_teams_for",
    "read_map_profiles",
]
