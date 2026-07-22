from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from s2clientprotocol import common_pb2 as common_pb
from s2clientprotocol import sc2api_pb2 as sc_pb

from .protocol import ComputerPlayer


RACES: dict[str, tuple[str, int]] = {
    "Random": ("무작위", common_pb.Random),
    "Terran": ("테란", common_pb.Terran),
    "Zerg": ("저그", common_pb.Zerg),
    "Protoss": ("프로토스", common_pb.Protoss),
}

DIFFICULTIES: dict[str, tuple[str, int]] = {
    "VeryEasy": ("아주 쉬움", sc_pb.VeryEasy),
    "Easy": ("쉬움", sc_pb.Easy),
    "Medium": ("보통", sc_pb.Medium),
    "MediumHard": ("어려움", sc_pb.MediumHard),
    "Hard": ("아주 어려움", sc_pb.Hard),
    "Harder": ("전문가", sc_pb.Harder),
    "VeryHard": ("정예", sc_pb.VeryHard),
    "CheatVision": ("시야 치터", sc_pb.CheatVision),
    "CheatMoney": ("자원 치터", sc_pb.CheatMoney),
    "CheatInsane": ("광란의 치터", sc_pb.CheatInsane),
}

AI_BUILDS: dict[str, int] = {
    "RandomBuild": sc_pb.RandomBuild,
    "Rush": sc_pb.Rush,
    "Timing": sc_pb.Timing,
    "Power": sc_pb.Power,
    "Macro": sc_pb.Macro,
}

BUILD_LABELS: dict[str, dict[str, str]] = {
    race: {
        "RandomBuild": "무작위",
        "Rush": "러쉬 공격",
        "Timing": "타이밍 공격",
        "Power": "압박 공격",
        "Macro": "자원 집중",
    }
    for race in RACES
}

DEFAULT_BUILD_BY_RACE: dict[str, str] = {
    race: "Macro" for race in RACES
}


@dataclass(frozen=True)
class AISelection:
    slot: int
    race: str = "Random"
    build: str = "Macro"
    difficulty: str = "VeryHard"


@dataclass(frozen=True)
class LauncherConfig:
    human_race: str
    ai_players: tuple[AISelection, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "human_race": self.human_race,
            "ai_players": [asdict(player) for player in self.ai_players],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LauncherConfig":
        human_race = str(data["human_race"])
        players = tuple(AISelection(**item) for item in data["ai_players"])
        config = cls(human_race=human_race, ai_players=players)
        config.validate()
        return config

    def validate(self) -> None:
        if self.human_race not in RACES:
            raise ValueError(f"Unknown human race: {self.human_race}")
        if tuple(player.slot for player in self.ai_players) != tuple(range(2, 15)):
            raise ValueError("AI slots must be exactly P2 through P14")
        for player in self.ai_players:
            if player.race not in RACES:
                raise ValueError(f"Unknown race for P{player.slot}: {player.race}")
            if player.build not in BUILD_LABELS[player.race]:
                raise ValueError(f"Unknown AI build for P{player.slot}: {player.build}")
            if player.difficulty not in DIFFICULTIES:
                raise ValueError(
                    f"Unknown difficulty for P{player.slot}: {player.difficulty}"
                )

    @property
    def human_race_value(self) -> int:
        return RACES[self.human_race][1]

    def computer_players(self) -> tuple[ComputerPlayer, ...]:
        self.validate()
        return tuple(
            ComputerPlayer(
                race=RACES[player.race][1],
                difficulty=DIFFICULTIES[player.difficulty][1],
                ai_build=AI_BUILDS[player.build],
                player_name=f"P{player.slot} Built-in AI",
            )
            for player in self.ai_players
        )


def default_config() -> LauncherConfig:
    return LauncherConfig(
        human_race="Random",
        ai_players=tuple(
            AISelection(
                slot=slot,
                race="Random",
                build="Macro",
                difficulty="CheatMoney" if slot == 14 else "VeryHard",
            )
            for slot in range(2, 15)
        ),
    )


def race_display(key: str) -> str:
    return RACES[key][0]


def race_key(display: str) -> str:
    return next(key for key, (label, _) in RACES.items() if label == display)


def difficulty_display(key: str) -> str:
    return DIFFICULTIES[key][0]


def difficulty_key(display: str) -> str:
    return next(
        key for key, (label, _) in DIFFICULTIES.items() if label == display
    )


def build_display(race: str, build: str) -> str:
    return BUILD_LABELS[race][build]


def build_key(race: str, display: str) -> str:
    return next(key for key, label in BUILD_LABELS[race].items() if label == display)
