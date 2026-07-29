"""런처 시작 시 맵 준비물의 상태를 판정하는 순수 로직."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from sc2team.map_profile import MapProfile


@dataclass(frozen=True)
class MapSyncPlan:
    to_prepare: tuple[str, ...]
    to_preview: tuple[str, ...]
    stale_image_dirs: tuple[Path, ...]
    unpreparable: tuple[str, ...]


def plan_map_sync(
    source_names: Iterable[str], image_dir: Path, profiles: Mapping[str, MapProfile]
) -> MapSyncPlan:
    """원본 맵·저장된 프리뷰·능력 보고서로 필요한 동기화 작업을 계산한다."""

    names = tuple(sorted(set(source_names)))
    to_prepare: list[str] = []
    to_preview: list[str] = []
    unpreparable: list[str] = []
    for name in names:
        profile = profiles.get(name)
        if profile is None:
            continue
        if not profile.prepared:
            if profile.preparable:
                to_prepare.append(name)
            else:
                unpreparable.append(name)
                continue
        required = ["terrain.png", *(f"{team}team.png" for team in range(2, profile.max_teams + 1))]
        image_map_dir = image_dir / name
        if name in to_prepare or any(not (image_map_dir / file_name).is_file() for file_name in required):
            to_preview.append(name)

    stale_image_dirs = tuple(
        sorted(
            (path for path in image_dir.iterdir() if path.is_dir() and path.name not in names),
            key=lambda path: path.name,
        )
        if image_dir.is_dir()
        else ()
    )
    return MapSyncPlan(
        to_prepare=tuple(to_prepare),
        to_preview=tuple(to_preview),
        stale_image_dirs=stale_image_dirs,
        unpreparable=tuple(unpreparable),
    )


__all__ = ["MapSyncPlan", "plan_map_sync"]
