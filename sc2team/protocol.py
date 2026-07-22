from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable

from s2clientprotocol import common_pb2 as common_pb
from s2clientprotocol import debug_pb2 as debug_pb
from s2clientprotocol import raw_pb2 as raw_pb
from s2clientprotocol import sc2api_pb2 as sc_pb
from websockets.asyncio.client import ClientConnection, connect


class Sc2ProtocolError(RuntimeError):
    """Raised when the SC2 API rejects a request."""


@dataclass(frozen=True)
class PortSet:
    game_port: int
    base_port: int


@dataclass(frozen=True)
class MultiplayerPorts:
    shared_port: int
    server: PortSet
    clients: tuple[PortSet, ...]


@dataclass(frozen=True)
class ComputerPlayer:
    race: int
    difficulty: int
    ai_build: int
    player_name: str


@dataclass(frozen=True)
class GamePlayerSetup:
    """One map slot in RequestCreateGame order."""

    player_type: int
    race: int = common_pb.Random
    difficulty: int = sc_pb.VeryEasy
    ai_build: int = sc_pb.RandomBuild
    player_name: str = ""


class Sc2Connection:
    def __init__(self, websocket: ClientConnection, api_port: int) -> None:
        self.websocket = websocket
        self.api_port = api_port
        self._request_id = 0

    @classmethod
    async def open(
        cls,
        api_port: int,
        *,
        host: str = "127.0.0.1",
        timeout: float = 45.0,
    ) -> "Sc2Connection":
        uri = f"ws://{host}:{api_port}/sc2api"
        deadline = asyncio.get_running_loop().time() + timeout
        last_error: Exception | None = None

        while asyncio.get_running_loop().time() < deadline:
            try:
                # SC2's API endpoint doesn't implement WebSocket ping frames.
                # websockets sends one after 20 seconds by default, which makes
                # SC2 drop an otherwise healthy multiplayer API connection.
                websocket = await connect(
                    uri,
                    open_timeout=2,
                    max_size=None,
                    ping_interval=None,
                )
                connection = cls(websocket, api_port)
                await connection.ping()
                return connection
            except Exception as error:  # SC2 takes a few seconds to expose its API.
                last_error = error
                await asyncio.sleep(0.25)

        raise TimeoutError(f"SC2 API port {api_port} did not become ready") from last_error

    async def close(self) -> None:
        await self.websocket.close()

    async def request(self, request: sc_pb.Request) -> sc_pb.Response:
        self._request_id += 1
        request.id = self._request_id
        await self.websocket.send(request.SerializeToString())
        payload = await self.websocket.recv()
        if not isinstance(payload, bytes):
            raise Sc2ProtocolError("SC2 returned a non-binary WebSocket frame")

        response = sc_pb.Response()
        response.ParseFromString(payload)
        if response.error:
            raise Sc2ProtocolError("; ".join(response.error))
        return response

    async def ping(self) -> sc_pb.ResponsePing:
        request = sc_pb.Request()
        request.ping.CopyFrom(sc_pb.RequestPing())
        return (await self.request(request)).ping

    async def create_game(
        self,
        map_path: str,
        map_data: bytes,
        participant_count: int,
        *,
        computer_count: int = 0,
        computer_players: Iterable[ComputerPlayer] | None = None,
        realtime: bool = True,
    ) -> None:
        if computer_players is not None and computer_count:
            raise ValueError(
                "computer_count and computer_players cannot be used together"
            )
        create = sc_pb.RequestCreateGame(realtime=realtime)
        create.local_map.map_path = map_path
        create.local_map.map_data = map_data
        for index in range(participant_count):
            player = create.player_setup.add()
            player.type = sc_pb.Participant
            player.player_name = f"Player {index + 1}"
        if computer_players is None:
            computer_players = (
                ComputerPlayer(
                    race=(common_pb.Terran, common_pb.Zerg, common_pb.Protoss)[
                        index % 3
                    ],
                    difficulty=sc_pb.VeryHard,
                    ai_build=sc_pb.RandomBuild,
                    player_name=f"Built-in AI {index + 1}",
                )
                for index in range(computer_count)
            )
        for computer in computer_players:
            player = create.player_setup.add()
            player.type = sc_pb.Computer
            player.race = computer.race
            player.difficulty = computer.difficulty
            player.ai_build = computer.ai_build
            player.player_name = computer.player_name

        request = sc_pb.Request()
        request.create_game.CopyFrom(create)
        response = (await self.request(request)).create_game
        if response.HasField("error"):
            detail = response.error_details if response.HasField("error_details") else ""
            raise Sc2ProtocolError(
                f"create_game failed ({response.error}): {detail}".rstrip()
            )

    async def create_game_with_setups(
        self,
        map_path: str,
        map_data: bytes,
        player_setups: Iterable[GamePlayerSetup],
        *,
        realtime: bool = True,
    ) -> None:
        """Create a game with participant/computer entries in exact map-slot order."""

        setups = tuple(player_setups)
        if not setups:
            raise ValueError("At least one player setup is required")
        participants = sum(
            setup.player_type == sc_pb.Participant for setup in setups
        )
        observers = sum(setup.player_type == sc_pb.Observer for setup in setups)
        # 통상 게임은 정확히 한 명의 Participant, §66 옵저버 게임은 Participant
        # 없이 정확히 한 명의 Observer로 만든다(전 슬롯 컴퓨터).
        if not (participants == 1 or (participants == 0 and observers == 1)):
            raise ValueError(
                "This local launcher requires exactly one Participant "
                "or exactly one Observer"
            )

        create = sc_pb.RequestCreateGame(realtime=realtime)
        create.local_map.map_path = map_path
        create.local_map.map_data = map_data
        for setup in setups:
            player = create.player_setup.add()
            player.type = setup.player_type
            player.player_name = setup.player_name
            if setup.player_type == sc_pb.Computer:
                player.race = setup.race
                player.difficulty = setup.difficulty
                player.ai_build = setup.ai_build

        request = sc_pb.Request()
        request.create_game.CopyFrom(create)
        response = (await self.request(request)).create_game
        if response.HasField("error"):
            detail = response.error_details if response.HasField("error_details") else ""
            raise Sc2ProtocolError(
                f"create_game failed ({response.error}): {detail}".rstrip()
            )

    async def join_game(
        self,
        race: int,
        player_name: str,
        ports: MultiplayerPorts | None,
    ) -> int:
        options = sc_pb.InterfaceOptions(
            raw=True,
            score=True,
            show_cloaked=True,
            show_burrowed_shadows=True,
        )
        join = sc_pb.RequestJoinGame(race=race, options=options, player_name=player_name)
        if ports is not None:
            join.shared_port = ports.shared_port
            join.server_ports.game_port = ports.server.game_port
            join.server_ports.base_port = ports.server.base_port
            for port_set in ports.clients:
                client = join.client_ports.add()
                client.game_port = port_set.game_port
                client.base_port = port_set.base_port

        request = sc_pb.Request()
        request.join_game.CopyFrom(join)
        response = (await self.request(request)).join_game
        if response.HasField("error"):
            detail = response.error_details if response.HasField("error_details") else ""
            raise Sc2ProtocolError(
                f"join_game failed ({response.error}): {detail}".rstrip()
            )
        return response.player_id

    async def join_as_observer(self, player_name: str = "Observer") -> int:
        """§66 옵저버 참가: 게임에 플레이어가 아니라 관전자로 들어간다.

        RequestCreateGame의 player_setup에 Observer 항목이 있어야 하고,
        participation 필드로 race 대신 observed_player_id를 보낸다(0 = 전체
        관전). 응답 player_id는 관전자에게 배정된 ID다."""

        options = sc_pb.InterfaceOptions(
            raw=True,
            score=True,
            show_cloaked=True,
            show_burrowed_shadows=True,
        )
        join = sc_pb.RequestJoinGame(
            observed_player_id=0, options=options, player_name=player_name
        )
        request = sc_pb.Request()
        request.join_game.CopyFrom(join)
        response = (await self.request(request)).join_game
        if response.HasField("error"):
            detail = response.error_details if response.HasField("error_details") else ""
            raise Sc2ProtocolError(
                f"join_as_observer failed ({response.error}): {detail}".rstrip()
            )
        return response.player_id

    async def observation(self, *, disable_fog: bool = False) -> sc_pb.ResponseObservation:
        request = sc_pb.Request()
        request.observation.CopyFrom(sc_pb.RequestObservation(disable_fog=disable_fog))
        return (await self.request(request)).observation

    async def step(self, count: int = 1) -> None:
        if count < 1:
            raise ValueError("step count must be positive")
        request = sc_pb.Request()
        request.step.CopyFrom(sc_pb.RequestStep(count=count))
        await self.request(request)

    async def debug_create_units(
        self,
        unit_type: int,
        owner: int,
        x: float,
        y: float,
        quantity: int,
    ) -> None:
        request = sc_pb.Request()
        command = request.debug.debug.add()
        command.create_unit.unit_type = unit_type
        command.create_unit.owner = owner
        command.create_unit.pos.x = x
        command.create_unit.pos.y = y
        command.create_unit.quantity = quantity
        await self.request(request)

    async def debug_set_unit_life(self, unit_tag: int, value: float) -> None:
        """Set unit life in a local verification game."""

        request = sc_pb.Request()
        command = request.debug.debug.add()
        command.unit_value.unit_value = debug_pb.DebugSetUnitValue.Life
        command.unit_value.value = value
        command.unit_value.unit_tag = unit_tag
        await self.request(request)

    async def debug_set_unit_shields(self, unit_tag: int, value: float) -> None:
        """Set unit shields in a local verification game."""

        request = sc_pb.Request()
        command = request.debug.debug.add()
        command.unit_value.unit_value = debug_pb.DebugSetUnitValue.Shields
        command.unit_value.value = value
        command.unit_value.unit_tag = unit_tag
        await self.request(request)

    async def debug_game_state(self, state: int) -> None:
        """Apply a `DebugGameState` cheat to this local game.

        These apply to the requesting Participant. Note that `all_resources` is a
        one-off grant of 5000 minerals and 5000 vespene, not a standing state, so
        "infinite resources" means calling it again whenever the bank runs down.
        """

        request = sc_pb.Request()
        command = request.debug.debug.add()
        command.game_state = state
        await self.request(request)

    async def debug_control_enemy(self) -> None:
        """Allow this local API connection to issue actions for non-self units."""

        await self.debug_game_state(debug_pb.control_enemy)

    async def debug_show_map(self) -> None:
        """Reveal the map for a local controller feasibility test."""

        await self.debug_game_state(debug_pb.show_map)

    async def raw_unit_command(
        self,
        unit_tags: Iterable[int],
        ability_id: int,
        *,
        target_position: tuple[float, float] | None = None,
        target_unit_tag: int | None = None,
        queue: bool = False,
    ) -> tuple[int, ...]:
        """Issue one raw command and return SC2's per-action result codes."""

        tags = tuple(unit_tags)
        if not tags:
            raise ValueError("At least one unit tag is required")
        if target_position is not None and target_unit_tag is not None:
            raise ValueError("A command can have only one target")

        request = sc_pb.Request()
        action = request.action.actions.add()
        command: raw_pb.ActionRawUnitCommand = action.action_raw.unit_command
        command.ability_id = ability_id
        command.unit_tags.extend(tags)
        command.queue_command = queue
        if target_position is not None:
            command.target_world_space_pos.x = target_position[0]
            command.target_world_space_pos.y = target_position[1]
        elif target_unit_tag is not None:
            command.target_unit_tag = target_unit_tag

        response = (await self.request(request)).action
        return tuple(response.result)

    async def save_replay(self) -> bytes:
        """현재 게임의 리플레이 바이트를 받아온다. 게임 진행 중에도 호출할 수
        있으며, 그 시점까지의 리플레이가 담긴다. API로 만든 게임은 클라이언트가
        리플레이를 자동 저장하지 않으므로 이 요청이 유일한 저장 수단이다."""

        request = sc_pb.Request()
        request.save_replay.CopyFrom(sc_pb.RequestSaveReplay())
        response = (await self.request(request)).save_replay
        if not response.data:
            raise Sc2ProtocolError("save_replay returned no data")
        return response.data

    async def map_command(self, trigger_command: str) -> None:
        """Execute a named map trigger through SC2's string bridge."""

        request = sc_pb.Request()
        request.map_command.CopyFrom(
            sc_pb.RequestMapCommand(trigger_cmd=trigger_command)
        )
        response = (await self.request(request)).map_command
        if response.HasField("error"):
            detail = response.error_details if response.HasField("error_details") else ""
            raise Sc2ProtocolError(
                f"map_command failed ({response.error}): {detail}".rstrip()
            )

    async def quit(self) -> None:
        request = sc_pb.Request()
        request.quit.CopyFrom(sc_pb.RequestQuit())
        try:
            await self.request(request)
        except Exception:
            # The game may close the socket before acknowledging quit.
            pass


def make_multiplayer_ports(start_port: int, player_count: int) -> MultiplayerPorts:
    if player_count < 2:
        raise ValueError("Multiplayer needs at least two participants")
    return MultiplayerPorts(
        shared_port=start_port + 1,
        server=PortSet(start_port + 2, start_port + 3),
        clients=tuple(
            PortSet(start_port + 4 + index * 2, start_port + 5 + index * 2)
            for index in range(player_count - 1)
        ),
    )


def races_for_players(player_count: int) -> Iterable[int]:
    races = (common_pb.Terran, common_pb.Zerg, common_pb.Protoss)
    for index in range(player_count):
        yield races[index % len(races)]
