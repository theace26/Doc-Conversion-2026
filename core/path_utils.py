"""
Path safety utilities — validation and collision detection for bulk conversion.

All path validation and collision logic lives here. No filesystem writes — pure
computation. Tested independently of the bulk pipeline.
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

CollisionStrategy = Literal["rename", "skip", "error"]


# ── Path length check ────────────────────────────────────────────────────────

def check_path_length(output_path: Path, max_length: int = 240) -> bool:
    """Returns True if the path is within the allowed length."""
    return len(str(output_path)) <= max_length


def truncate_path_diagnosis(
    source_path: Path, output_path: Path, max_length: int
) -> dict:
    """Returns a diagnostic dict for a path that is too long."""
    path_str = str(output_path)
    return {
        "source_path": str(source_path),
        "output_path": path_str,
        "output_path_length": len(path_str),
        "max_length": max_length,
        "overage": len(path_str) - max_length,
        "suggestion": f"Shorten the directory structure or filename (needs {len(path_str) - max_length} fewer chars)",
    }


# ── Output path mapping ─────────────────────────────────────────────────────

def map_output_path(
    source_file: Path, source_root: Path, output_root: Path
) -> Path:
    """
    Maps a source file to its mirrored output .md path.

    Raises ValueError if source_file is not under source_root.
    """
    relative = source_file.relative_to(source_root)
    return output_root / relative.with_suffix(".md")


def map_output_path_renamed(
    source_file: Path, source_root: Path, output_root: Path
) -> Path:
    """
    Collision-safe variant — appends source extension before .md.

    report.pdf -> report.pdf.md
    """
    relative = source_file.relative_to(source_root)
    new_name = relative.name + ".md"  # e.g. "report.pdf.md"
    return output_root / relative.parent / new_name


# ── Collision detection ──────────────────────────────────────────────────────

def detect_collisions(
    file_list: list[Path],
    source_root: Path,
    output_root: Path,
) -> dict[str, list[Path]]:
    """
    Find output path collisions (same stem, different extension).

    Returns dict mapping each colliding output path to its source files.
    Only paths with 2+ source files are included.
    """
    seen: dict[str, list[Path]] = {}
    for f in file_list:
        out = map_output_path(f, source_root, output_root)
        key = str(out)
        seen.setdefault(key, []).append(f)
    return {k: v for k, v in seen.items() if len(v) > 1}


def detect_case_collisions(
    file_list: list[Path],
    source_root: Path,
    output_root: Path,
) -> dict[str, list[Path]]:
    """
    Find files whose output paths differ only by case.

    Returns same shape as detect_collisions() but keyed by lowercased output path.
    Only returns groups where lowercased paths match but originals differ.
    """
    seen: dict[str, list[Path]] = {}
    for f in file_list:
        out = map_output_path(f, source_root, output_root)
        key = str(out).lower()
        seen.setdefault(key, []).append(f)
    result = {}
    for k, v in seen.items():
        if len(v) <= 1:
            continue
        # Check that originals actually differ (not already a standard collision)
        originals = {str(map_output_path(f, source_root, output_root)) for f in v}
        if len(originals) > 1:
            result[k] = v
    return result


# ── Collision resolution ─────────────────────────────────────────────────────

def resolve_collision(
    collision_group: list[Path],
    source_root: Path,
    output_root: Path,
    strategy: CollisionStrategy,
) -> dict[Path, tuple[str, Path | None]]:
    """
    Apply strategy to a group of colliding source files.

    Returns dict: source_path -> (resolution, resolved_output_path)
      resolution: 'renamed' | 'skipped' | 'skipped_kept' | 'errored'
      resolved_output_path: final path (None if skipped/errored)
    """
    sorted_group = sorted(collision_group, key=lambda p: str(p))
    result: dict[Path, tuple[str, Path | None]] = {}

    if strategy == "rename":
        for f in sorted_group:
            renamed = map_output_path_renamed(f, source_root, output_root)
            result[f] = ("renamed", renamed)

    elif strategy == "skip":
        first = sorted_group[0]
        canonical = map_output_path(first, source_root, output_root)
        result[first] = ("skipped_kept", canonical)
        for f in sorted_group[1:]:
            result[f] = ("skipped", None)

    elif strategy == "error":
        for f in sorted_group:
            result[f] = ("errored", None)

    return result


# ── Full path safety pass ────────────────────────────────────────────────────

@dataclass
class PathSafetyResult:
    path_too_long: list[Path] = field(default_factory=list)
    collision_groups: dict[str, list[Path]] = field(default_factory=dict)
    case_collision_groups: dict[str, list[Path]] = field(default_factory=dict)
    resolved_paths: dict[str, tuple[str | None, str]] = field(default_factory=dict)
    # str key = str(source_path) for serializable dict keys
    total_checked: int = 0
    safe_count: int = 0
    too_long_count: int = 0
    collision_count: int = 0
    case_collision_count: int = 0


async def run_path_safety_pass(
    all_files: list[Path],
    source_root: Path,
    output_root: Path,
    max_path_length: int = 240,
    collision_strategy: CollisionStrategy = "rename",
) -> PathSafetyResult:
    """
    1. Check every file for path length overflow
    2. Detect standard collisions
    3. Detect case collisions
    4. Build resolved_paths mapping
    """
    result = PathSafetyResult(total_checked=len(all_files))

    # 1. Path length check
    length_ok: list[Path] = []
    for i, f in enumerate(all_files):
        out = map_output_path(f, source_root, output_root)
        if not check_path_length(out, max_path_length):
            result.path_too_long.append(f)
            result.resolved_paths[str(f)] = (None, f"Output path too long ({len(str(out))} chars, max {max_path_length})")
        else:
            length_ok.append(f)
        if i % 500 == 0:
            await asyncio.sleep(0)

    result.too_long_count = len(result.path_too_long)

    # 2. Standard collisions (among length-ok files)
    result.collision_groups = detect_collisions(length_ok, source_root, output_root)
    collision_files: set[str] = set()
    for output_path_str, sources in result.collision_groups.items():
        resolved = resolve_collision(sources, source_root, output_root, collision_strategy)
        for src, (resolution, resolved_path) in resolved.items():
            result.resolved_paths[str(src)] = (
                str(resolved_path) if resolved_path else None,
                resolution,
            )
            collision_files.add(str(src))
    result.collision_count = len(collision_files)

    # 3. Case collisions (among length-ok files not already in standard collisions)
    non_collision = [f for f in length_ok if str(f) not in collision_files]
    result.case_collision_groups = detect_case_collisions(non_collision, source_root, output_root)
    case_collision_files: set[str] = set()
    for _, sources in result.case_collision_groups.items():
        resolved = resolve_collision(sources, source_root, output_root, collision_strategy)
        for src, (resolution, resolved_path) in resolved.items():
            result.resolved_paths[str(src)] = (
                str(resolved_path) if resolved_path else None,
                resolution,
            )
            case_collision_files.add(str(src))
    result.case_collision_count = len(case_collision_files)

    # 4. Default mapping for safe files
    all_flagged = set(str(p) for p in result.path_too_long) | collision_files | case_collision_files
    for f in all_files:
        if str(f) not in all_flagged:
            out = map_output_path(f, source_root, output_root)
            result.resolved_paths[str(f)] = (str(out), "safe")

    result.safe_count = result.total_checked - result.too_long_count - result.collision_count - result.case_collision_count

    return result
