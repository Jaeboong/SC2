from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_EXE = (
    PROJECT_ROOT
    / "vendor"
    / "SC2AIApp_2025_S1"
    / "SC2AIApp_2025_S1"
    / "Bots"
    / "changeling"
    / "changeling.exe"
)
OUTPUT_EXE = SOURCE_EXE.with_name("changeling-fixed.exe")


def patched_main_source(source: str) -> str:
    before_common = """        await super(MyBot, self).on_start()
        self._starting_enemy_race = self.enemy_race
        if self.race == Race.Protoss:
"""
    after_common = """        if self.race == Race.Protoss:
"""
    before_protoss = """            self._switched_opening_due_to_random: bool = False
            # await self.on_start()

        elif self.race == Race.Terran:
"""
    after_protoss = """            self._switched_opening_due_to_random: bool = False
            await DeimosBot.on_start(self)
            return

        elif self.race == Race.Terran:
"""
    before_terran = """            from bot.phobos.bot.consts import OpeningBuildNames
            self.__class__ = PhobosBot
            self._phobos_mediator: PhobosMediator = PhobosMediator()
            self._switched_opening_due_to_random: bool = False
            self.opening_build = OpeningBuildNames(self.build_order_runner.chosen_opening)
            logger.info(f"Chosen Opening: {self.opening_build}")
            # await self.on_start()
"""
    after_terran = """            self.__class__ = PhobosBot
            self._phobos_mediator: PhobosMediator = PhobosMediator()
            self._starting_enemy_race: Race = Race.Protoss
            self._switched_opening_due_to_random: bool = False
            await PhobosBot.on_start(self)
            return
"""

    replacements = (
        (before_common, after_common),
        (before_protoss, after_protoss),
        (before_terran, after_terran),
    )
    updated = source.replace("\r\n", "\n")
    for before, after in replacements:
        if updated.count(before) != 1:
            raise RuntimeError("Changeling source layout did not match the expected build")
        updated = updated.replace(before, after, 1)
    return updated


def patched_deimos_transition_source(source: str) -> str:
    """Keep the Protoss opening active on rich-resource maps.

    Deimos treats 950 minerals as proof that its opening is stuck. Rich
    mineral fields can legitimately cross that threshold before the first
    tech structure finishes, which skips the Pylon and leaves every later
    Protoss structure without power.
    """

    before = "self.ai.minerals >= 950"
    after = "self.ai.minerals >= 999999999"
    updated = source.replace("\r\n", "\n")
    if updated.count(before) != 1:
        raise RuntimeError("Deimos transition source did not match the expected build")
    return updated.replace(before, after, 1)


def patched_map_analyzer_constructs_source(source: str) -> str:
    """Allow MapAnalyzer ramps that initially touch no detected region.

    The large Europe melee terrain contains decorative/edge ramps whose
    perimeter lookup returns zero regions. MapAnalyzer 0.2.0 assumes at least
    one and indexes ``self.regions[0]``, which crashes Changeling before the
    first game step. Select the nearest regions until two are attached instead.
    """

    before = """        if len(self.regions) < 2:
            region_list = list(self.map_data.regions.values())
            region_list.remove(self.regions[0])
            closest_region = self.closest_region(region_list=region_list)
            assert closest_region not in self.regions
            self.areas.append(closest_region)
"""
    after = """        while len(self.regions) < 2:
            region_list = [
                region
                for region in self.map_data.regions.values()
                if region not in self.regions
            ]
            if not region_list:
                break
            closest_region = self.closest_region(region_list=region_list)
            self.areas.append(closest_region)
"""
    updated = source.replace("\r\n", "\n")
    if updated.count(before) != 1:
        raise RuntimeError("MapAnalyzer constructs source did not match the expected build")
    return updated.replace(before, after, 1)


def compile_with_python_312(
    source: str,
    directory: Path,
    source_name: str,
    compiled_filename: str,
) -> bytes:
    source_path = directory / f"{source_name}.py"
    blob_path = directory / f"{source_name}.zlib"
    source_path.write_text(source, encoding="utf-8", newline="\n")
    compiler = (
        "import marshal,sys,zlib; from pathlib import Path; "
        "s=Path(sys.argv[1]).read_text(encoding='utf-8'); "
        "c=compile(s,sys.argv[3],'exec'); "
        "Path(sys.argv[2]).write_bytes(zlib.compress(marshal.dumps(c),9))"
    )
    subprocess.run(
        [
            "uv",
            "run",
            "--python",
            "3.12",
            "--no-project",
            "python",
            "-c",
            compiler,
            str(source_path),
            str(blob_path),
            compiled_filename,
        ],
        check=True,
    )
    return blob_path.read_bytes()


def compile_pyc_with_python_312(
    source: str,
    original_pyc: bytes,
    directory: Path,
    source_name: str,
    compiled_filename: str,
) -> bytes:
    source_path = directory / f"{source_name}.py"
    original_path = directory / f"{source_name}.original.pyc"
    blob_path = directory / f"{source_name}.pyc"
    source_path.write_text(source, encoding="utf-8", newline="\n")
    original_path.write_bytes(original_pyc)
    compiler = (
        "import marshal,sys; from pathlib import Path; "
        "s=Path(sys.argv[1]).read_text(encoding='utf-8'); "
        "header=Path(sys.argv[2]).read_bytes()[:16]; "
        "c=compile(s,sys.argv[4],'exec'); "
        "Path(sys.argv[3]).write_bytes(header+marshal.dumps(c))"
    )
    subprocess.run(
        [
            "uv",
            "run",
            "--python",
            "3.12",
            "--no-project",
            "python",
            "-c",
            compiler,
            str(source_path),
            str(original_path),
            str(blob_path),
            compiled_filename,
        ],
        check=True,
    )
    return blob_path.read_bytes()


def main() -> None:
    if not SOURCE_EXE.is_file():
        raise FileNotFoundError(SOURCE_EXE)

    archive = CArchiveReader(str(SOURCE_EXE))
    pyz = archive.open_embedded_archive("PYZ.pyz")

    pyz_patches = (
        (
            "bot.main",
            "bot/main.py",
            patched_main_source(archive.extract(r"bot\main.py").decode("utf-8")),
        ),
        (
            "map_analyzer.constructs",
            "map_analyzer/constructs.py",
            patched_map_analyzer_constructs_source(
                archive.extract(r"map_analyzer\constructs.py").decode("utf-8")
            ),
        ),
    )
    deimos_pyc_name = (
        r"bot\deimos\bot\managers\__pycache__"
        r"\opening_transition_manager.cpython-312.pyc"
    )
    deimos_source = patched_deimos_transition_source(
        archive.extract(
            r"bot\deimos\bot\managers\opening_transition_manager.py"
        ).decode("utf-8")
    )
    original_deimos_pyc = archive.extract(deimos_pyc_name)

    with tempfile.TemporaryDirectory(prefix="changeling-patch-") as temp:
        compiled = {
            module_name: compile_with_python_312(
                source,
                Path(temp),
                f"patch_{index}",
                filename,
            )
            for index, (module_name, filename, source) in enumerate(pyz_patches)
        }
        compiled_deimos_pyc = compile_pyc_with_python_312(
            deimos_source,
            original_deimos_pyc,
            Path(temp),
            "deimos_opening_transition",
            (
                r"C:\Users\Tom\PycharmProjects\changeling\bot\deimos\bot\managers"
                r"\opening_transition_manager.py"
            ),
        )

    for module_name, _filename, _source in pyz_patches:
        _typecode, _offset, entry_length = pyz.toc[module_name]
        if len(compiled[module_name]) > entry_length:
            raise RuntimeError(
                f"Patched module {module_name} is too large: "
                f"{len(compiled[module_name])} > {entry_length} bytes"
            )

    deimos_offset, deimos_compressed_size, deimos_size, _compressed, _type = (
        archive.toc[deimos_pyc_name]
    )
    if len(compiled_deimos_pyc) != deimos_size:
        raise RuntimeError(
            "Patched Deimos pyc size changed: "
            f"{len(compiled_deimos_pyc)} != {deimos_size} bytes"
        )
    compressed_deimos_pyc = zlib.compress(compiled_deimos_pyc, 9)
    if len(compressed_deimos_pyc) > deimos_compressed_size:
        raise RuntimeError(
            "Patched Deimos pyc is too large: "
            f"{len(compressed_deimos_pyc)} > {deimos_compressed_size} bytes"
        )

    shutil.copy2(SOURCE_EXE, OUTPUT_EXE)
    with OUTPUT_EXE.open("r+b") as executable:
        for module_name, _filename, _source in pyz_patches:
            _typecode, entry_offset, entry_length = pyz.toc[module_name]
            compressed = compiled[module_name]
            executable.seek(pyz._start_offset + entry_offset)
            executable.write(compressed)
            executable.write(b"\0" * (entry_length - len(compressed)))
        executable.seek(archive._start_offset + deimos_offset)
        executable.write(compressed_deimos_pyc)
        executable.write(b"\0" * (deimos_compressed_size - len(compressed_deimos_pyc)))

    verification_archive = CArchiveReader(str(OUTPUT_EXE)).open_embedded_archive(
        "PYZ.pyz"
    )
    for module_name, _filename, _source in pyz_patches:
        if verification_archive.extract(module_name, raw=True) != zlib.decompress(
            compiled[module_name]
        ):
            OUTPUT_EXE.unlink(missing_ok=True)
            raise RuntimeError(f"Patched PYZ module verification failed: {module_name}")
    verification_archive = CArchiveReader(str(OUTPUT_EXE))
    if verification_archive.extract(deimos_pyc_name) != compiled_deimos_pyc:
        OUTPUT_EXE.unlink(missing_ok=True)
        raise RuntimeError("Patched Deimos pyc verification failed")

    print(f"Built: {OUTPUT_EXE}")
    for module_name, _filename, _source in pyz_patches:
        _typecode, _offset, entry_length = pyz.toc[module_name]
        print(
            f"Patched {module_name}: "
            f"{len(compiled[module_name])}/{entry_length} compressed bytes"
        )
    print(
        "Patched Deimos opening transition: "
        f"{len(compressed_deimos_pyc)}/{deimos_compressed_size} compressed bytes"
    )
    print("Protoss: Deimos managers initialize before the first step")
    print("Protoss: rich-mineral income no longer aborts the opening at 950 minerals")
    print("Terran: Phobos managers initialize before the first step")
    print("MapAnalyzer: ramps with zero detected regions use nearest-region fallback")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
