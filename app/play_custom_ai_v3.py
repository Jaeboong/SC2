from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for extra in (PROJECT_ROOT, PROJECT_ROOT / "v3"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from sc2team.custom_config import (  # noqa: E402
    CONTROLLERS,
    DEFAULT_BUILD_BY_RACE,
    PROTOSS_FACTIONS,
    RACES,
    TEAM_MODE_LABELS,
    TEAM_REGION_LABELS,
    CustomLauncherConfig,
    SlotConfig,
    team_for_slot,
)
from sc2team.custom_runtime import (  # noqa: E402
    RACE_VALUES,
    player_setups,
    runtime_player_id,
)
from sc2team.live_observe import DEFAULT_PORT as OBSERVE_PORT, LiveObserveBridge  # noqa: E402
from sc2team.map_preview import PREVIEW_CONTENT_SIZE, preview_path, slot_positions  # noqa: E402
from sc2team.map_profile import MapProfile, read_map_profiles  # noqa: E402
from sc2team.process import discover_sc2_executable, launch_sc2, stop_process  # noqa: E402
from sc2team.protocol import Sc2Connection  # noqa: E402
from sc2team.team_layout import resolve_team_layout  # noqa: E402
from sc2team_v3.config import (  # noqa: E402
    V3_DEFAULT_BUILD_BY_RACE,
    V3_GROUND_BUILDS,
    V3BuildConfig,
)
from sc2team_v3.runtime import build_v3_map, install_v3_mod  # noqa: E402


APP_VERSION = "3.2.0"
MAP_SOURCE_DIR = PROJECT_ROOT / "map" / "source"
MAP_IMAGE_DIR = PROJECT_ROOT / "map" / "img"
PREVIEW_TOOL = PROJECT_ROOT / "tools" / "make_map_previews.py"
DEFAULT_MAP_NAME = "europe-melee-2-7v7-rich-50000-fixed-teams"
SETTINGS_FILE = PROJECT_ROOT / "runtime" / "v3_launcher_settings.json"
PORT = 14180

# 프리뷰 콘텐츠 폭에 테두리·좌우 여백(26px)을 더한 값. 생성기와 하나의
# 상수를 공유하므로 프리뷰 크기를 바꿔도 패널 폭이 함께 맞춰진다.
PREVIEW_PANEL_WIDTH = PREVIEW_CONTENT_SIZE + 26

TEAM_SECTION_COLORS: dict[int, tuple[str, str]] = {
    1: ("#203d61", "#cce6ff"),
    2: ("#643333", "#ffd6d2"),
    3: ("#30533a", "#d5f6dc"),
    4: ("#563665", "#efd7ff"),
}


def map_source_files() -> list[Path]:
    if not MAP_SOURCE_DIR.is_dir():
        return []
    return sorted(MAP_SOURCE_DIR.glob("*.SC2Map"))


def runtime_map_for(map_name: str) -> Path:
    return PROJECT_ROOT / "runtime" / "maps" / f"v3-{map_name}.SC2Map"


def map_blocker(profile: MapProfile | None) -> str:
    """이 맵으로 지금 게임을 시작할 수 없는 이유. 빈 문자열이면 시작할 수 있다."""

    if profile is None:
        return "맵 능력을 읽지 못했습니다."
    if not profile.readable:
        return profile.reason or "맵을 읽을 수 없습니다."
    if not profile.prepared:
        return (
            "아직 준비되지 않은 맵입니다. `node tools/build_team_map.cjs <원본> <출력>` "
            "으로 한 번 준비해야 합니다."
        )
    if profile.max_players < 2:
        return f"수용 인원이 {profile.max_players}명입니다. 최소 2명 맵이 필요합니다."
    return ""


def wild_zerg_availability(
    profile: MapProfile | None, active_player_count: int
) -> tuple[bool, str]:
    """현재 맵과 활성 슬롯 조합에서 야생 저그를 켤 수 있는지 판정한다."""

    if profile is None:
        return False, "맵 능력을 읽지 못했습니다."
    return profile.wild_zerg_available(active_player_count)


def _fallback_team_layout(slot_ids: tuple[int, ...], team_mode: int) -> dict[int, int]:
    """프로필 좌표를 읽지 못했을 때만 쓰는 안전한 연속 분할."""

    if not slot_ids:
        return {}
    return {
        slot: min(team_mode, index * team_mode // len(slot_ids) + 1)
        for index, slot in enumerate(slot_ids)
    }


def _default_state(max_players: int = 14) -> tuple[CustomLauncherConfig, dict[int, str]]:
    active_ai = {2, 3, 4, 8, 9, 10, 11}
    race_order = ("Terran", "Protoss", "Zerg")
    slots: list[SlotConfig] = []
    builds: dict[int, str] = {}
    ai_index = 0
    for slot_id in range(1, max_players + 1):
        if slot_id == 1:
            controller = "human"
            race = "Terran"
        elif slot_id in active_ai:
            controller = "custom_ai"
            race = race_order[ai_index % len(race_order)]
            ai_index += 1
            builds[slot_id] = V3_DEFAULT_BUILD_BY_RACE[race]
        else:
            controller = "empty"
            race = "Random"
        slots.append(
            SlotConfig(
                slot=slot_id,
                controller=controller,
                team=team_for_slot(slot_id, 2)
                if max_players == 14
                else _fallback_team_layout(tuple(range(1, max_players + 1)), 2)[slot_id],
                race=race,
                build=DEFAULT_BUILD_BY_RACE[race],
                melee_build="Macro" if controller == "custom_ai" else "",
            )
        )
    config = CustomLauncherConfig(
        version=1,
        slots=tuple(slots),
        allow_support_air=False,
        unit_control=False,
    )
    config.validate()
    return config, builds


def _resize_config(
    config: CustomLauncherConfig, builds: dict[int, str], max_players: int, team_mode: int
) -> tuple[CustomLauncherConfig, dict[int, str]]:
    """저장된 슬롯을 맵 수용 인원에 맞춘다. 앞 슬롯 상태를 보존한다."""

    slot_ids = tuple(range(1, max_players + 1))
    teams = _fallback_team_layout(slot_ids, team_mode)
    saved = {slot.slot: slot for slot in config.slots}
    slots: list[SlotConfig] = []
    human_seen = False
    for slot_id in slot_ids:
        previous = saved.get(slot_id)
        if previous is None:
            controller, race, build, melee_build = "empty", "Random", "Random", ""
        else:
            controller, race = previous.controller, previous.race
            build, melee_build = previous.build, previous.melee_build
        if controller == "human":
            if human_seen:
                controller, race, build, melee_build = "empty", "Random", "Random", ""
            human_seen = True
        slots.append(
            SlotConfig(
                slot=slot_id,
                controller=controller,
                team=teams[slot_id],
                race=race,
                build=build,
                melee_build=melee_build,
            )
        )
    if not human_seen:
        first = slots[0]
        slots[0] = SlotConfig(
            slot=first.slot,
            controller="human",
            team=first.team,
            race="Terran",
            build=DEFAULT_BUILD_BY_RACE["Terran"],
            melee_build="",
        )
    resized = CustomLauncherConfig(
        version=config.version,
        slots=tuple(slots),
        full_vision=config.full_vision,
        allow_support_air=config.allow_support_air,
        protoss_faction=config.protoss_faction,
        wild_zerg=config.wild_zerg,
        unit_control=config.unit_control,
        fullscreen=config.fullscreen,
    )
    return resized, {slot: build for slot, build in builds.items() if slot in slot_ids}


async def run_v3_game(
    config: CustomLauncherConfig,
    builds: dict[int, str],
    cancel_event: threading.Event,
    status: Callable[[str], None],
    *,
    base_map: Path,
    runtime_map_file: Path,
    observer: bool = False,
    live_observe: bool = False,
    command_card: bool = False,
) -> str:
    config.validate()
    v3_config = V3BuildConfig(
        campaign_units=True,
        player_builds=tuple(sorted(builds.items())),
    )
    v3_config.validate()
    status(f"{base_map.stem} 맵과 V3 커스텀 AI를 빌드하는 중…")
    runtime_map = build_v3_map(
        PROJECT_ROOT,
        base_map,
        runtime_map_file,
        config,
        v3_config,
        observer_mode=observer,
        active_config_file=runtime_map_file.with_suffix(".json"),
    )
    executable = discover_sc2_executable()
    installed = install_v3_mod(PROJECT_ROOT, executable.parents[2])
    status(f"V3 커스텀 AI 설치 완료: {installed.name} — SC2 연결 중…")
    process = launch_sc2(
        executable, PORT, 0, width=1280, height=720, fullscreen=config.fullscreen
    )
    connection: Sc2Connection | None = None
    bridge: LiveObserveBridge | None = None
    try:
        connection = await Sc2Connection.open(PORT)
        version = await connection.ping()
        await connection.create_game_with_setups(
            runtime_map.name,
            runtime_map.read_bytes(),
            player_setups(config, observer=observer),
            realtime=True,
        )
        if observer:
            await connection.join_as_observer("V3 Observer", command_card=command_card)
        else:
            player_id = await connection.join_game(
                RACE_VALUES[config.human.race],
                f"P{config.human.slot} Local Human",
                None,
                command_card=command_card,
            )
            expected = runtime_player_id(config, config.human.slot)
            if player_id != expected:
                raise RuntimeError(
                    f"사람 슬롯 매핑 실패: 내부 P{expected}가 아니라 P{player_id}로 참가했습니다."
                )
        if live_observe:
            try:
                bridge = LiveObserveBridge(port=OBSERVE_PORT, log=status)
                await bridge.start()
            except OSError as error:
                # 브리지는 진단 보조다. 포트가 이미 잡혀 있다는 이유로 게임 실행
                # 자체를 실패시키지 않는다.
                bridge = None
                status(f"라이브 관측 브리지를 열지 못했습니다({error}). 게임은 그대로 진행합니다.")
        status(
            f"SC2 {version.game_version} — V3 지상군 정책 적용 완료. "
            + (
                f"옵저버 모드: P{config.human.slot}까지 AI가 플레이합니다."
                if observer
                else "생산·테크·확장·출격은 맵 내부 V3 Galaxy 정책이 담당합니다."
            )
            + (f" 라이브 관측: {bridge.url}" if bridge is not None else "")
        )
        while not cancel_event.is_set() and process.poll() is None:
            started = time.perf_counter()
            observation = await connection.observation(disable_fog=True)
            roundtrip_ms = (time.perf_counter() - started) * 1000.0
            if bridge is not None:
                # 브리지는 이 관측을 재사용만 한다. 조회 요청마다 새 관측을 뜨면
                # realtime 게임의 프레임을 갉아먹는다.
                bridge.publish(observation, roundtrip_ms=roundtrip_ms)
            if observation.player_result:
                return "V3 게임이 종료되었습니다."
            await asyncio.sleep(1.0)
        if cancel_event.is_set():
            return "사용자가 V3 게임을 종료했습니다."
        return "SC2 창이 닫혔습니다."
    finally:
        if bridge is not None:
            await bridge.stop()
        if connection is not None:
            try:
                await connection.quit()
            finally:
                await connection.close()
        stop_process(process)


class SlotRow:
    def __init__(self, app: "V3LauncherApp", parent: tk.Widget, slot: SlotConfig, build: str | None) -> None:
        self.app = app
        self.slot_id = slot.slot
        self.build_id = build
        self._changing = False
        self.slot_label = tk.Label(
            parent,
            text=f"P{slot.slot}",
            bg="#111a28",
            fg="#f4f7fb",
            width=5,
        )
        self.team_label = tk.Label(parent, bg="#111a28", fg="#90a4bf", width=12)
        self.controller_var = tk.StringVar(value=CONTROLLERS[slot.controller])
        self.controller_box = ttk.Combobox(parent, textvariable=self.controller_var, values=list(CONTROLLERS.values()), state="readonly", width=12)
        self.race_var = tk.StringVar(value=RACES[slot.race])
        self.race_box = ttk.Combobox(parent, textvariable=self.race_var, values=list(RACES.values()), state="readonly", width=12)
        self.build_var = tk.StringVar()
        self.build_box = ttk.Combobox(parent, textvariable=self.build_var, state="readonly", width=39)
        self.controller_box.bind("<<ComboboxSelected>>", self._controller_changed)
        self.race_box.bind("<<ComboboxSelected>>", self._race_changed)
        self.build_box.bind("<<ComboboxSelected>>", self._build_changed)
        self.refresh()

    def grid(self, row: int) -> None:
        self.slot_label.grid(row=row, column=0, pady=2, sticky="ew")
        self.team_label.grid(row=row, column=1, pady=2, sticky="ew")
        self.controller_box.grid(row=row, column=2, padx=3, pady=2, sticky="ew")
        self.race_box.grid(row=row, column=3, padx=3, pady=2, sticky="ew")
        self.build_box.grid(
            row=row,
            column=4,
            padx=(3, 7),
            pady=2,
            sticky="ew",
        )

    def destroy(self) -> None:
        for widget in (
            self.slot_label,
            self.team_label,
            self.controller_box,
            self.race_box,
            self.build_box,
        ):
            widget.destroy()

    @property
    def controller(self) -> str:
        return next(key for key, value in CONTROLLERS.items() if value == self.controller_var.get())

    @property
    def race(self) -> str:
        return next(key for key, value in RACES.items() if value == self.race_var.get())

    def _controller_changed(self, _event=None) -> None:
        if not self._changing:
            self.app.on_controller_changed(self)
        self.refresh()

    def _race_changed(self, _event=None) -> None:
        self.build_id = V3_DEFAULT_BUILD_BY_RACE.get(self.race)
        self.refresh()

    def _build_changed(self, _event=None) -> None:
        builds = V3_GROUND_BUILDS.get(self.race, {})
        self.build_id = next((key for key, label in builds.items() if label == self.build_var.get()), None)

    def refresh(self) -> None:
        self.team_label.configure(
            text=self.app.team_label_for(self.slot_id)
        )
        active = self.controller != "empty"
        ai = self.controller == "custom_ai" or (
            self.controller == "human" and self.app.observer_var.get()
        )
        self.race_box.configure(state="readonly" if active else "disabled")
        builds = V3_GROUND_BUILDS.get(self.race, {})
        if ai and self.build_id not in builds:
            self.build_id = V3_DEFAULT_BUILD_BY_RACE.get(self.race)
        self.build_box.configure(values=list(builds.values()))
        self.build_var.set(builds.get(self.build_id, "종족을 먼저 선택하세요" if ai else "—"))
        self.build_box.configure(state="readonly" if ai and builds else "disabled")

    def set_controller(self, controller: str) -> None:
        self.controller_var.set(CONTROLLERS[controller])
        self.refresh()

    def set_enabled(self, enabled: bool) -> None:
        self.controller_box.configure(state="readonly" if enabled else "disabled")
        if enabled:
            self.refresh()
        else:
            self.race_box.configure(state="disabled")
            self.build_box.configure(state="disabled")

    def to_slot(self) -> SlotConfig:
        return SlotConfig(
            slot=self.slot_id,
            controller=self.controller,
            team=self.app.team_for(self.slot_id),
            race=self.race,
            build=DEFAULT_BUILD_BY_RACE[self.race],
            melee_build="Macro" if self.controller == "custom_ai" else "",
        )


class V3LauncherApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"SC2 V3 Ground AI v{APP_VERSION}")
        self.root.geometry("1440x920")
        # 슬롯 표와 360px 프리뷰(푸터 포함)를 모두 표시하는 요구 높이가
        # 867px이므로, 축소 시 어느 패널도 잘리지 않게 여유를 둔다.
        self.root.minsize(1120, 880)
        self.root.configure(bg="#08101d")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.running = False
        self.close_requested = False
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.rows: list[SlotRow] = []
        self.observer_var = tk.BooleanVar(value=False)
        # 진단용 옵트인. 기본은 꺼짐 — 평소 플레이는 지금과 완전히 동일해야 한다.
        self.live_observe_var = tk.BooleanVar(value=False)
        self.command_card_var = tk.BooleanVar(value=False)
        # PhotoImage 는 참조가 끊기면 즉시 회수돼 라벨이 비어 버린다.
        self.preview_image: tk.PhotoImage | None = None
        self.profiles: dict[str, MapProfile] = {}
        self.profile_error = ""
        self._team_layout: dict[int, int] = {}
        self._team_mode_labels: dict[str, int] = {}
        self.requested_map = DEFAULT_MAP_NAME
        self._style()
        config, builds = self._load()
        self.map_var = tk.StringVar(value=self._initial_map_name())
        self._load_profiles(refresh=False)
        max_players = max(
            2, self.map_profile.max_players if self.map_profile else len(config.slots)
        )
        max_teams = self.map_profile.max_teams if self.map_profile else 4
        modes = self._available_team_modes(max_players, max_teams)
        team_mode = config.team_mode if config.team_mode in modes else modes[-1]
        config, builds = _resize_config(config, builds, max_players, team_mode)
        self.team_mode_var = tk.StringVar()
        self._set_team_modes(modes, team_mode)
        self._build_ui(config, builds)
        self._refresh_map_panel()

    def _initial_map_name(self) -> str:
        names = [path.stem for path in map_source_files()]
        if self.requested_map in names:
            return self.requested_map
        if DEFAULT_MAP_NAME in names:
            return DEFAULT_MAP_NAME
        return names[0] if names else ""

    @property
    def map_name(self) -> str:
        return self.map_var.get()

    @property
    def map_profile(self) -> MapProfile | None:
        return self.profiles.get(self.map_name)

    def _load_profiles(self, *, refresh: bool = True) -> None:
        """맵 능력을 읽는다. node 를 부르므로 실패해도 런처는 살아야 한다."""

        paths = map_source_files()
        if not paths:
            self.profile_error = f"{MAP_SOURCE_DIR} 에 맵이 없습니다."
        else:
            try:
                self.profiles = {
                    profile.name: profile
                    for profile in read_map_profiles(PROJECT_ROOT, *paths)
                }
                self.profile_error = ""
            except (OSError, RuntimeError, FileNotFoundError) as error:
                self.profile_error = f"맵 능력을 읽지 못했습니다: {error}"
        if refresh:
            self._refresh_map_panel()

    @property
    def team_mode(self) -> int:
        selected = self.team_mode_var.get()
        if selected in self._team_mode_labels:
            return self._team_mode_labels[selected]
        # 이전 저장 라벨과 기존 조립 스모크는 14인 문구를 직접 넣는다. UI 목록에는
        # 새 맵 크기 문구만 남기되, 이 경로에서는 안전하게 같은 팀 수로 해석한다.
        return next(
            (mode for mode, label in TEAM_MODE_LABELS.items() if label == selected), 2
        )

    @staticmethod
    def _available_team_modes(max_players: int, max_teams: int) -> tuple[int, ...]:
        upper = min(max_players, max_teams, 4)
        return tuple(mode for mode in TEAM_MODE_LABELS if mode <= upper) or (2,)

    @staticmethod
    def _team_mode_label(team_mode: int) -> str:
        return f"{team_mode}팀 · {'/'.join(TEAM_REGION_LABELS[team_mode].values())}"

    def _set_team_modes(self, modes: tuple[int, ...], selected: int) -> None:
        labels = {self._team_mode_label(mode): mode for mode in modes}
        self._team_mode_labels = labels
        self.team_mode_var.set(next(label for label, mode in labels.items() if mode == selected))
        if hasattr(self, "team_mode_box"):
            self.team_mode_box.configure(values=list(labels))

    def _update_team_layout(self) -> None:
        slot_ids = tuple(row.slot_id for row in self.rows)
        fallback = _fallback_team_layout(slot_ids, self.team_mode)
        profile = self.map_profile
        if profile is None or not profile.readable:
            self._team_layout = fallback
            return
        try:
            positions, _provisional = slot_positions(profile)
            layout = resolve_team_layout(positions, self.team_mode)
            self._team_layout = (
                layout if set(layout) == set(slot_ids) else fallback
            )
        except (RuntimeError, ValueError):
            self._team_layout = fallback

    def team_for(self, slot_id: int) -> int:
        return self._team_layout.get(slot_id, 1)

    def team_label_for(self, slot_id: int) -> str:
        team = self.team_for(slot_id)
        return f"{TEAM_REGION_LABELS[self.team_mode][team]} · {team}팀"

    def _style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground="#17243a", background="#17243a", foreground="#f4f7fb", arrowcolor="#8ec5ff", padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", "#17243a"), ("disabled", "#101827")], foreground=[("readonly", "#f4f7fb"), ("disabled", "#6e7c90")])

    def _build_ui(self, config: CustomLauncherConfig, builds: dict[int, str]) -> None:
        header = tk.Frame(self.root, bg="#08101d")
        header.pack(fill="x", padx=22, pady=(16, 8))
        tk.Label(header, text="V3 지상군 AI", bg="#08101d", fg="#f6fbff", font=("Malgun Gothic", 21, "bold")).pack(anchor="w")
        tk.Label(header, text="각 AI 슬롯에서 확정한 종족별 2개 빌드를 선택합니다. 캠페인 유닛 포함 · 공중 전투 빌드 제외", bg="#08101d", fg="#90a4bf", font=("Malgun Gothic", 10)).pack(anchor="w")
        team_controls = tk.Frame(header, bg="#08101d")
        team_controls.pack(fill="x", pady=(8, 0))
        tk.Label(
            team_controls,
            text="팀 구성",
            bg="#08101d",
            fg="#d6e3f3",
            font=("Malgun Gothic", 10, "bold"),
        ).pack(side="left", padx=(0, 8))
        self.team_mode_box = ttk.Combobox(
            team_controls,
            textvariable=self.team_mode_var,
            values=list(self._team_mode_labels),
            state="readonly",
            width=42,
        )
        self.team_mode_box.pack(side="left")
        self.team_mode_box.bind("<<ComboboxSelected>>", self._team_mode_changed)
        body = tk.Frame(self.root, bg="#08101d")
        body.pack(fill="both", expand=True, padx=22, pady=6)
        self.table = tk.Frame(body, bg="#111a28", highlightbackground="#2b4667", highlightthickness=1)
        self.table.pack(side="left", fill="both", expand=True)
        self._build_map_panel(body)
        for column, (heading, width) in enumerate(zip(("슬롯", "위치·팀", "플레이어", "종족", "V3 지상군 빌드"), (5, 12, 13, 13, 40))):
            tk.Label(self.table, text=heading, width=width, bg="#1a2a40", fg="#bcd7f5", font=("Malgun Gothic", 9, "bold"), pady=7).grid(row=0, column=column, sticky="ew")
            self.table.grid_columnconfigure(column, weight=3 if column == 4 else 1)
        self.team_section_labels: dict[int, tk.Label] = {}
        for team in range(1, 5):
            background, foreground = TEAM_SECTION_COLORS[team]
            self.team_section_labels[team] = tk.Label(
                self.table,
                bg=background,
                fg=foreground,
                anchor="w",
                padx=10,
                pady=4,
                font=("Malgun Gothic", 10, "bold"),
            )
        self._rebuild_slot_rows(config.slots, builds)
        options = tk.Frame(self.root, bg="#08101d")
        options.pack(fill="x", padx=22, pady=4)
        self.full_vision_var = tk.BooleanVar(value=config.full_vision)
        self.wild_zerg_var = tk.BooleanVar(value=config.wild_zerg)
        self.fullscreen_var = tk.BooleanVar(value=config.fullscreen)
        self.faction_var = tk.StringVar(value=PROTOSS_FACTIONS[config.protoss_faction])
        for label, variable in (("사람 전체 시야", self.full_vision_var),):
            tk.Checkbutton(options, text=label, variable=variable, bg="#08101d", fg="#d6e3f3", selectcolor="#17243a", activebackground="#08101d", activeforeground="#fff").pack(side="left", padx=(0, 18))
        self.wild_zerg_check = tk.Checkbutton(
            options,
            text="야생 저그 활성화",
            variable=self.wild_zerg_var,
            bg="#08101d",
            fg="#d6e3f3",
            selectcolor="#17243a",
            activebackground="#08101d",
            activeforeground="#fff",
        )
        self.wild_zerg_check.pack(side="left", padx=(0, 18))
        tk.Checkbutton(options, text="전체 화면", variable=self.fullscreen_var, bg="#08101d", fg="#d6e3f3", selectcolor="#17243a", activebackground="#08101d", activeforeground="#fff").pack(side="left", padx=(0, 18))
        tk.Label(options, text="프로토스 전역 진영", bg="#08101d", fg="#d6e3f3").pack(side="left", padx=(8, 6))
        self.faction_box = ttk.Combobox(options, textvariable=self.faction_var, values=list(PROTOSS_FACTIONS.values()), state="readonly", width=13)
        self.faction_box.pack(side="left")
        observer_options = tk.Frame(self.root, bg="#08101d")
        observer_options.pack(fill="x", padx=22, pady=(2, 4))
        self.observer_check = tk.Checkbutton(
            observer_options,
            text="옵저버 모드 (사람 슬롯도 V3 AI가 플레이)",
            variable=self.observer_var,
            command=self._observer_changed,
            bg="#08101d",
            fg="#ffcf8a",
            selectcolor="#17243a",
            activebackground="#08101d",
            activeforeground="#ffffff",
            font=("Malgun Gothic", 9, "bold"),
        )
        self.observer_check.pack(side="left")
        diagnostics = tk.Frame(self.root, bg="#08101d")
        diagnostics.pack(fill="x", padx=22, pady=(2, 4))
        self.live_observe_check = tk.Checkbutton(
            diagnostics,
            text=f"라이브 관측 브리지 (127.0.0.1:{OBSERVE_PORT}, 읽기 전용)",
            variable=self.live_observe_var,
            command=self._live_observe_changed,
            bg="#08101d",
            fg="#9ee8c0",
            selectcolor="#17243a",
            activebackground="#08101d",
            activeforeground="#ffffff",
        )
        self.live_observe_check.pack(side="left", padx=(0, 18))
        self.command_card_check = tk.Checkbutton(
            diagnostics,
            text="명령카드 계측 (ui_data·abilities)",
            variable=self.command_card_var,
            bg="#08101d",
            fg="#9ee8c0",
            selectcolor="#17243a",
            activebackground="#08101d",
            activeforeground="#ffffff",
        )
        self.command_card_check.pack(side="left")
        self._live_observe_changed()
        footer = tk.Frame(self.root, bg="#08101d")
        footer.pack(fill="x", padx=22, pady=(6, 15))
        self.status_var = tk.StringVar(value="AI 슬롯의 종족과 V3 빌드를 선택하세요.")
        tk.Label(footer, textvariable=self.status_var, bg="#08101d", fg="#9fb0c7", anchor="w").pack(side="left", fill="x", expand=True)
        self.start_button = tk.Button(footer, text="V3 게임 시작", command=self._start, bg="#1674b9", fg="#fff", relief="flat", padx=16, pady=8)
        self.start_button.pack(side="right", padx=(8, 0))
        self.stop_button = tk.Button(footer, text="게임 종료", command=self._stop, state="disabled", bg="#713a3a", fg="#fff", relief="flat", padx=12, pady=8)
        self.stop_button.pack(side="right")

    def _rebuild_slot_rows(
        self, slots: tuple[SlotConfig, ...], builds: dict[int, str]
    ) -> None:
        """맵 슬롯 수가 바뀔 때 표 위젯을 교체한다."""

        for row in self.rows:
            row.destroy()
        self.rows.clear()
        # SlotRow 생성 중에도 팀 라벨을 갱신하므로, 이전 맵의 팀 번호가 새 모드에
        # 남아 있지 않게 먼저 안전한 배치를 넣는다.
        self._team_layout = _fallback_team_layout(
            tuple(slot.slot for slot in slots), self.team_mode
        )
        self.rows.extend(
            SlotRow(self, self.table, slot, builds.get(slot.slot)) for slot in slots
        )
        self._update_team_layout()
        self._layout_team_sections()

    def _build_map_panel(self, parent: tk.Widget) -> None:
        """오른쪽 맵 패널. 맵 선택 · 프리뷰 · 맵이 정하는 상한을 보여준다."""

        panel = tk.Frame(
            parent,
            bg="#111a28",
            highlightbackground="#2b4667",
            highlightthickness=1,
            width=PREVIEW_PANEL_WIDTH,
        )
        panel.pack(side="right", fill="y", padx=(12, 0))
        panel.pack_propagate(False)
        tk.Label(
            panel,
            text="맵",
            bg="#1a2a40",
            fg="#bcd7f5",
            font=("Malgun Gothic", 9, "bold"),
            pady=7,
        ).pack(fill="x")
        chooser = tk.Frame(panel, bg="#111a28")
        chooser.pack(fill="x", padx=10, pady=(10, 6))
        self.map_box = ttk.Combobox(
            chooser,
            textvariable=self.map_var,
            values=[path.stem for path in map_source_files()],
            state="readonly",
        )
        self.map_box.pack(fill="x")
        self.map_box.bind("<<ComboboxSelected>>", self._map_changed)
        # 버튼과 설명을 먼저 아래쪽에 고정한다. 세로로 긴 맵의 프리뷰가 패널보다
        # 높아도 컨트롤이 화면 밖으로 밀리지 않고 이미지만 잘린다.
        self.preview_button = tk.Button(
            panel,
            text="프리뷰 다시 만들기",
            command=self._rebuild_preview,
            bg="#1e3a5c",
            fg="#dbe9fb",
            relief="flat",
            padx=10,
            pady=5,
        )
        self.preview_button.pack(side="bottom", padx=12, pady=(8, 12), anchor="w")
        self.map_detail_var = tk.StringVar()
        tk.Label(
            panel,
            textvariable=self.map_detail_var,
            bg="#111a28",
            fg="#9fb0c7",
            anchor="w",
            justify="left",
            wraplength=PREVIEW_PANEL_WIDTH - 30,
            font=("Malgun Gothic", 9),
        ).pack(side="bottom", fill="x", padx=12, pady=(6, 0))
        self.preview_label = tk.Label(
            panel,
            bg="#0b1220",
            fg="#8296b0",
            justify="center",
            wraplength=PREVIEW_PANEL_WIDTH - 40,
        )
        self.preview_label.pack(side="top", padx=10, pady=4)

    def _map_changed(self, _event=None) -> None:
        current, builds = self._current_unvalidated()
        profile = self.map_profile
        max_players = max(2, profile.max_players) if profile else len(self.rows)
        max_teams = profile.max_teams if profile else 4
        modes = self._available_team_modes(max_players, max_teams)
        team_mode = self.team_mode if self.team_mode in modes else modes[-1]
        current, builds = _resize_config(current, builds, max_players, team_mode)
        self._set_team_modes(modes, team_mode)
        self._rebuild_slot_rows(current.slots, builds)
        self._refresh_map_panel()
        blocker = map_blocker(self.map_profile)
        self.status_var.set(
            f"{self.map_name} 맵을 선택했습니다."
            if not blocker
            else f"{self.map_name}: {blocker}"
        )

    def _refresh_map_panel(self) -> None:
        """선택된 맵의 프리뷰와 설명을 갱신한다."""

        name = self.map_name
        if not name:
            self.preview_label.configure(image="", text=self.profile_error or "맵이 없습니다.")
            self.preview_image = None
            self.map_detail_var.set(f"{MAP_SOURCE_DIR} 에 .SC2Map 을 넣으세요.")
            self._refresh_wild_zerg_control()
            return

        image_file = next(
            (
                candidate
                for candidate in (
                    preview_path(MAP_IMAGE_DIR, name, self.team_mode),
                    preview_path(MAP_IMAGE_DIR, name, None),
                )
                if candidate.is_file()
            ),
            None,
        )
        if image_file is None:
            self.preview_image = None
            self.preview_label.configure(
                image="",
                text="프리뷰가 없습니다.\n아래 버튼으로 만드세요.",
                height=12,
                width=46,
            )
        else:
            try:
                self.preview_image = tk.PhotoImage(file=str(image_file))
            except tk.TclError as error:
                self.preview_image = None
                self.preview_label.configure(image="", text=f"프리뷰를 읽지 못했습니다: {error}")
            else:
                self.preview_label.configure(
                    image=self.preview_image, text="", height=0, width=0
                )

        profile = self.profiles.get(name)
        if profile is None:
            self.map_detail_var.set(self.profile_error or "맵 능력을 읽는 중…")
            self._refresh_wild_zerg_control()
            return
        lines = [
            f"수용 {profile.max_players}명 · 최대 {profile.max_teams}팀 · "
            f"시작 지점 {len(profile.start_locations)}",
        ]
        available, reason = self._refresh_wild_zerg_control()
        lines.append(
            f"야생 저그 캠프 {profile.wild_zerg_town_halls}"
            + ("" if available else f" — 사용 불가: {reason}")
        )
        blocker = map_blocker(profile)
        lines.append("✔ 이 맵으로 시작할 수 있습니다." if not blocker else f"⚠ {blocker}")
        self.map_detail_var.set("\n".join(lines))

    def _active_player_count(self) -> int:
        """비어 있지 않은 현재 로비 슬롯 수를 센다."""

        return sum(row.controller != "empty" for row in self.rows)

    def _wild_zerg_availability(self) -> tuple[bool, str]:
        return wild_zerg_availability(self.map_profile, self._active_player_count())

    def _refresh_wild_zerg_control(self) -> tuple[bool, str]:
        """맵·슬롯 조합에 맞춰 야생 저그 설정을 강제하거나 푼다."""

        available, reason = self._wild_zerg_availability()
        if not available:
            self.wild_zerg_var.set(False)
        self.wild_zerg_check.configure(
            state="normal" if available and not self.running else "disabled"
        )
        return available, reason

    def _rebuild_preview(self) -> None:
        name = self.map_name
        if not name or self.running:
            return
        self.preview_button.configure(state="disabled")
        self.status_var.set(f"{name} 프리뷰를 만드는 중…")

        def worker() -> None:
            completed = subprocess.run(
                [sys.executable, str(PREVIEW_TOOL), "--force", name],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            message = (
                f"{name} 프리뷰를 만들었습니다."
                if completed.returncode == 0
                else "프리뷰 생성 실패: "
                + ((completed.stderr or completed.stdout).strip().splitlines() or [""])[-1]
            )
            self.root.after(0, self._preview_rebuilt, message)

        threading.Thread(target=worker, name="v3-map-preview", daemon=True).start()

    def _preview_rebuilt(self, message: str) -> None:
        self.preview_button.configure(state="normal" if not self.running else "disabled")
        self.status_var.set(message)
        self._refresh_map_panel()

    def on_controller_changed(self, changed: SlotRow) -> None:
        if changed.controller == "human":
            for row in self.rows:
                if row is not changed and row.controller == "human":
                    row.set_controller("empty")
        self._refresh_map_panel()

    def _layout_team_sections(self) -> None:
        for label in self.team_section_labels.values():
            label.grid_remove()

        rows_by_slot = {row.slot_id: row for row in self.rows}
        grid_row = 1
        for team in range(1, self.team_mode + 1):
            slot_ids = tuple(
                slot
                for slot in rows_by_slot
                if self.team_for(slot) == team
            )
            region = TEAM_REGION_LABELS[self.team_mode][team]
            section = self.team_section_labels[team]
            section.configure(
                text=(
                    f"{team}팀 · {region}  |  "
                    + ", ".join(f"P{slot}" for slot in slot_ids)
                    + f"  ({len(slot_ids)}개 슬롯)"
                )
            )
            section.grid(
                row=grid_row,
                column=0,
                columnspan=5,
                padx=1,
                pady=(5 if grid_row > 1 else 2, 1),
                sticky="ew",
            )
            grid_row += 1
            for slot in slot_ids:
                rows_by_slot[slot].grid(grid_row)
                grid_row += 1

    def _team_mode_changed(self, _event=None) -> None:
        self._update_team_layout()
        for row in self.rows:
            row.refresh()
        self._layout_team_sections()
        self._refresh_map_panel()
        self.status_var.set(
            f"팀 구성을 {self._team_mode_label(self.team_mode)} 모드로 변경했습니다."
        )

    def _live_observe_changed(self) -> None:
        # 명령카드 계측은 브리지로만 읽을 수 있으므로 브리지가 꺼지면 같이 끈다.
        if not self.live_observe_var.get():
            self.command_card_var.set(False)
        self.command_card_check.configure(
            state="normal" if self.live_observe_var.get() else "disabled"
        )

    def _observer_changed(self) -> None:
        for row in self.rows:
            row.refresh()
        self.status_var.set(
            "옵저버 모드: 사람 슬롯도 선택한 V3 빌드의 컴퓨터로 실행됩니다."
            if self.observer_var.get()
            else "일반 모드: 사람 슬롯으로 직접 플레이합니다."
        )

    def _current_unvalidated(self) -> tuple[CustomLauncherConfig, dict[int, str]]:
        slots = tuple(row.to_slot() for row in self.rows)
        config = CustomLauncherConfig(
            version=1,
            slots=slots,
            full_vision=self.full_vision_var.get(),
            allow_support_air=False,
            protoss_faction=next(key for key, label in PROTOSS_FACTIONS.items() if label == self.faction_var.get()),
            wild_zerg=self.wild_zerg_var.get(),
            unit_control=False,
            fullscreen=self.fullscreen_var.get(),
        )
        builds: dict[int, str] = {}
        for row in self.rows:
            is_v3_ai = row.controller == "custom_ai" or (
                self.observer_var.get() and row.controller == "human"
            )
            if not is_v3_ai:
                continue
            if row.race == "Random" or row.build_id not in V3_GROUND_BUILDS.get(row.race, {}):
                raise ValueError(f"P{row.slot_id}: V3 AI는 종족과 세부 빌드를 직접 선택해야 합니다.")
            builds[row.slot_id] = row.build_id
        return config, builds

    def _current(self) -> tuple[CustomLauncherConfig, dict[int, str]]:
        config, builds = self._current_unvalidated()
        config.validate()
        return config, builds

    def _load(self) -> tuple[CustomLauncherConfig, dict[int, str]]:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.observer_var.set(bool(data.get("observer_mode", False)))
            self.live_observe_var.set(bool(data.get("live_observe", False)))
            self.command_card_var.set(bool(data.get("command_card", False)))
            self.requested_map = str(data.get("map", DEFAULT_MAP_NAME))
            return CustomLauncherConfig.from_dict(data["launcher"]), {int(key): str(value) for key, value in data["builds"].items()}
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.observer_var.set(False)
            self.live_observe_var.set(False)
            self.command_card_var.set(False)
            self.requested_map = DEFAULT_MAP_NAME
            return _default_state()

    def _save(self, config: CustomLauncherConfig, builds: dict[int, str]) -> None:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(
                {
                    "version": 3,
                    "map": self.map_name,
                    "launcher": config.to_dict(),
                    "builds": builds,
                    "observer_mode": self.observer_var.get(),
                    "live_observe": self.live_observe_var.get(),
                    "command_card": self.command_card_var.get(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _set_enabled(self, enabled: bool) -> None:
        for row in self.rows:
            row.set_enabled(enabled)
        self.team_mode_box.configure(state="readonly" if enabled else "disabled")
        self.map_box.configure(state="readonly" if enabled else "disabled")
        self.preview_button.configure(state="normal" if enabled else "disabled")
        self.faction_box.configure(state="readonly" if enabled else "disabled")
        if enabled:
            self._refresh_wild_zerg_control()
        else:
            self.wild_zerg_check.configure(state="disabled")
        self.observer_check.configure(state="normal" if enabled else "disabled")
        self.live_observe_check.configure(state="normal" if enabled else "disabled")
        self.command_card_check.configure(
            state="normal" if enabled and self.live_observe_var.get() else "disabled"
        )
        self.start_button.configure(state="normal" if enabled else "disabled")
        self.stop_button.configure(state="disabled" if enabled else "normal")

    def _start(self) -> None:
        if self.running:
            return
        try:
            blocker = map_blocker(self.map_profile)
            if blocker:
                raise ValueError(f"{self.map_name or '맵 없음'}: {blocker}")
            config, builds = self._current()
            available, reason = self._wild_zerg_availability()
            if config.wild_zerg and not available:
                raise ValueError(f"야생 저그를 사용할 수 없습니다: {reason}")
            self._save(config, builds)
        except Exception as error:
            messagebox.showerror("V3 설정 오류", str(error), parent=self.root)
            return
        base_map = MAP_SOURCE_DIR / f"{self.map_name}.SC2Map"
        runtime_map_file = runtime_map_for(self.map_name)
        self.running = True
        observer = self.observer_var.get()
        live_observe = self.live_observe_var.get()
        command_card = live_observe and self.command_card_var.get()
        self.cancel_event.clear()
        self._set_enabled(False)

        def status(message: str) -> None:
            self.root.after(0, self.status_var.set, message)

        def worker() -> None:
            try:
                result = asyncio.run(
                    run_v3_game(
                        config,
                        builds,
                        self.cancel_event,
                        status,
                        base_map=base_map,
                        runtime_map_file=runtime_map_file,
                        observer=observer,
                        live_observe=live_observe,
                        command_card=command_card,
                    )
                )
                self.root.after(0, self._finished, result, None)
            except Exception as error:
                self.root.after(0, self._finished, "V3 실행 실패", error)

        self.worker = threading.Thread(target=worker, name="sc2-v3-launcher", daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        self.status_var.set("V3 게임을 종료하는 중…")
        self.cancel_event.set()
        self.stop_button.configure(state="disabled")

    def _finished(self, result: str, error: Exception | None) -> None:
        self.running = False
        if self.close_requested:
            self.root.destroy()
            return
        self._set_enabled(True)
        self.status_var.set(result if error is None else f"실행 실패: {error}")
        if error is not None:
            messagebox.showerror("V3 실행 실패", str(error), parent=self.root)

    def _close(self) -> None:
        if self.close_requested:
            return
        if self.running:
            if not messagebox.askyesno("게임 종료", "SC2를 종료하고 런처를 닫을까요?", parent=self.root):
                return
            self.close_requested = True
            self.status_var.set("SC2를 종료한 뒤 V3 런처를 닫는 중…")
            self.cancel_event.set()
            return
        self.close_requested = True
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    V3LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
