from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sc2team.map_sync import plan_map_sync


def profile(*, prepared: bool, preparable: bool, max_teams: int = 4) -> SimpleNamespace:
    return SimpleNamespace(prepared=prepared, preparable=preparable, max_teams=max_teams)


class MapSyncPlanTests(unittest.TestCase):
    def plan(self, root: Path, profiles: dict[str, SimpleNamespace]):
        return plan_map_sync(profiles, root / "img", profiles)

    def complete_preview(self, image_dir: Path, name: str, max_teams: int = 4) -> None:
        target = image_dir / name
        target.mkdir(parents=True)
        for file_name in ("terrain.png", *(f"{team}team.png" for team in range(2, max_teams + 1))):
            (target / file_name).touch()

    def test_preparable_unprepared_map_needs_prepare_and_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self.plan(Path(temporary), {"asia": profile(prepared=False, preparable=True)})
        self.assertEqual(plan.to_prepare, ("asia",))
        self.assertEqual(plan.to_preview, ("asia",))

    def test_unpreparable_map_is_reported_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            plan = self.plan(Path(temporary), {"broken": profile(prepared=False, preparable=False)})
        self.assertEqual(plan.unpreparable, ("broken",))
        self.assertEqual(plan.to_prepare, ())
        self.assertEqual(plan.to_preview, ())

    def test_prepared_complete_map_needs_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.complete_preview(root / "img", "ready")
            plan = self.plan(root, {"ready": profile(prepared=True, preparable=True)})
        self.assertEqual(plan.to_preview, ())
        self.assertEqual(plan.stale_image_dirs, ())

    def test_missing_team_preview_needs_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.complete_preview(root / "img", "ready")
            (root / "img" / "ready" / "3team.png").unlink()
            plan = self.plan(root, {"ready": profile(prepared=True, preparable=True)})
        self.assertEqual(plan.to_preview, ("ready",))

    def test_orphan_directory_is_stale_but_file_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_dir = root / "img"
            (image_dir / "orphan").mkdir(parents=True)
            (image_dir / "not-a-directory").touch()
            plan = self.plan(root, {"ready": profile(prepared=True, preparable=True)})
        self.assertEqual(tuple(path.name for path in plan.stale_image_dirs), ("orphan",))

    def test_two_team_map_does_not_need_higher_team_previews(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.complete_preview(root / "img", "duel", max_teams=2)
            plan = self.plan(root, {"duel": profile(prepared=True, preparable=True, max_teams=2)})
        self.assertEqual(plan.to_preview, ())


if __name__ == "__main__":
    unittest.main()
