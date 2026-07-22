from __future__ import annotations

from contextlib import suppress

from s2clientprotocol import sc2api_pb2 as sc_pb
from websockets.asyncio.client import connect
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed


# Unit type ids are stable SC2 protocol ids. Burrowed drones are included so a
# Zerg bot does not temporarily lose a worker from its internal economy count.
WORKER_UNIT_TYPE_IDS = frozenset({45, 84, 104, 116})
PROTOSS_TOWNHALL_TYPE_IDS = frozenset({59})  # Nexus
RICH_GAS_STRUCTURE_TO_STANDARD = {
    1943: 20,  # RefineryRich -> Refinery
    1994: 61,  # AssimilatorRich -> Assimilator
    1995: 88,  # ExtractorRich -> Extractor
}


def restore_worker_supply(response: sc_pb.Response) -> int | None:
    """Make zero-supply workers look normal to a bot's API observation.

    The map keeps the real worker Food value at zero. Only the observation sent
    to the external bot is adjusted, so players still receive the intended
    zero-population workers while bots that use supply_workers as a worker
    count can follow their normal build logic.
    """

    if not response.HasField("observation"):
        return None
    observation = response.observation.observation
    if not observation.HasField("player_common") or not observation.HasField(
        "raw_data"
    ):
        return None

    player_id = observation.player_common.player_id
    worker_count = sum(
        1
        for unit in observation.raw_data.units
        if unit.owner == player_id and unit.unit_type in WORKER_UNIT_TYPE_IDS
    )
    common = observation.player_common
    common.food_workers = worker_count
    common.food_used += worker_count
    # The bundled Torches map uses an older melee dependency where each Nexus
    # contributes 13 supply. Changeling's current Deimos build orders assume
    # the modern 15-supply Nexus and place the first Pylon at supply 14.
    # Correct only the bot-facing observation; the real map rules stay intact.
    completed_nexuses = sum(
        1
        for unit in observation.raw_data.units
        if unit.owner == player_id
        and unit.unit_type in PROTOSS_TOWNHALL_TYPE_IDS
        and unit.build_progress >= 1.0
    )
    common.food_cap += completed_nexuses * 2

    # The map correctly creates rich-gas variants after construction, but the
    # bundled bots only count the standard structure ids when advancing their
    # build orders. Normalize the bot-facing unit type while keeping the real
    # in-game rich structure and its resource behavior unchanged.
    for unit in observation.raw_data.units:
        if unit.owner == player_id and unit.unit_type in RICH_GAS_STRUCTURE_TO_STANDARD:
            unit.unit_type = RICH_GAS_STRUCTURE_TO_STANDARD[unit.unit_type]
    return worker_count


class WorkerSupplyProxy:
    def __init__(
        self,
        *,
        listen_port: int,
        sc2_port: int,
        host: str = "127.0.0.1",
    ) -> None:
        self.listen_port = listen_port
        self.sc2_port = sc2_port
        self.host = host
        self.server: Server | None = None
        self.last_worker_count: int | None = None
        self.last_actual_food_used: int | None = None
        self.last_patched_food_used: int | None = None
        self.last_food_cap: int | None = None
        self.last_patched_food_cap: int | None = None
        self.last_player_id: int | None = None

    async def start(self) -> None:
        if self.server is not None:
            raise RuntimeError("Worker supply proxy is already running")
        self.server = await serve(
            self._handle,
            self.host,
            self.listen_port,
            max_size=None,
            ping_interval=None,
        )

    async def close(self) -> None:
        if self.server is None:
            return
        self.server.close()
        await self.server.wait_closed()
        self.server = None

    async def _handle(self, incoming: ServerConnection) -> None:
        downstream_uri = f"ws://{self.host}:{self.sc2_port}/sc2api"
        async with connect(
            downstream_uri,
            open_timeout=10,
            max_size=None,
            ping_interval=None,
        ) as downstream:
            try:
                async for request_payload in incoming:
                    await downstream.send(request_payload)
                    response_payload = await downstream.recv()
                    if isinstance(response_payload, bytes):
                        response = sc_pb.Response()
                        response.ParseFromString(response_payload)
                        if response.HasField("observation"):
                            observation = response.observation.observation
                            if observation.HasField("player_common"):
                                common = observation.player_common
                                self.last_actual_food_used = common.food_used
                                self.last_food_cap = common.food_cap
                                self.last_player_id = common.player_id
                        worker_count = restore_worker_supply(response)
                        if worker_count is not None:
                            self.last_worker_count = worker_count
                            self.last_patched_food_used = (
                                response.observation.observation.player_common.food_used
                            )
                            self.last_patched_food_cap = (
                                response.observation.observation.player_common.food_cap
                            )
                        response_payload = response.SerializeToString()
                    await incoming.send(response_payload)
            except ConnectionClosed:
                # Normal when the launcher closes the game before the bot has
                # consumed the final SC2 response.
                pass
            finally:
                with suppress(Exception):
                    await downstream.close()
