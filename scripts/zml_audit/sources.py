from __future__ import annotations

import os
from pathlib import Path

from .models import Blocker, SourceResolution


REMOTE_PREFIXES = ("s3://", "http://", "https://")
ZML_SUFFIXES = (".zml", ".zml.zst")
REFUSED_DIRECTORY_ROOTS = {Path("/"), Path("/Systems"), Path("/home"), Path.home(), Path("/tmp")}
MAX_DISCOVERY_DEPTH = 12
MAX_DISCOVERY_DIRS = 1000
MAX_DISCOVERY_FILES = 5000
MAX_DISCOVERY_ENTRIES_PER_DIR = 2000


def resolve_source(raw: str, max_candidates: int = 200) -> SourceResolution:
  if raw.startswith(REMOTE_PREFIXES):
    return SourceResolution(
      input=raw,
      kind="remote",
      blockers=(
        Blocker(
          tool="source",
          message="remote ZML references are not downloaded by this read-only helper",
          guidance="provide an already-local .zml or .zml.zst path, or download artifacts outside this helper",
        ),
      ),
    )

  path = Path(raw).expanduser()
  if not path.exists():
    return SourceResolution(
      input=raw,
      kind="missing",
      blockers=(Blocker(tool="source", message=f"local path does not exist: {path}"),),
    )

  if path.is_file():
    if is_zml_candidate(path):
      return SourceResolution(input=raw, kind="file", candidates=(str(path),))
    return SourceResolution(
      input=raw,
      kind="unsupported_file",
      blockers=(Blocker(tool="source", message=f"local file is not a .zml or .zml.zst candidate: {path}"),),
    )

  if path.is_dir():
    if blocker := refused_directory_blocker(path):
      return SourceResolution(input=raw, kind="refused_directory", blockers=(blocker,))
    candidates, truncated, blocker = zml_candidates_under(path, max_candidates)
    blockers: list[Blocker] = []
    if blocker:
      blockers.append(blocker)
    if truncated:
      blockers.append(
        Blocker(
          tool="source",
          message=f"candidate list truncated to {max_candidates} files under provided directory",
          guidance="pass a narrower log root or exact ZML file for complete coverage",
        )
      )
    if not candidates:
      blockers.append(Blocker(tool="source", message=f"no .zml or .zml.zst files found under provided directory: {path}"))
    return SourceResolution(input=raw, kind="directory", candidates=tuple(candidates), blockers=tuple(blockers))

  return SourceResolution(
    input=raw,
    kind="unsupported",
    blockers=(Blocker(tool="source", message=f"unsupported local path type: {path}"),),
  )


def is_zml_candidate(path: Path) -> bool:
  text = path.name.lower()
  return any(text.endswith(suffix) for suffix in ZML_SUFFIXES)


def refused_directory_blocker(path: Path) -> Blocker | None:
  resolved = safe_resolve(path)
  if resolved in REFUSED_DIRECTORY_ROOTS:
    return Blocker(
      tool="source",
      message=f"refusing to scan broad directory for ZML files: {resolved}",
      guidance="pass an exact .zml/.zml.zst file or a narrower Phoenix log directory",
    )
  return None


def zml_candidates_under(path: Path, max_candidates: int) -> tuple[list[str], bool, Blocker | None]:
  candidates: list[str] = []
  seen: set[str] = set()
  seen_dirs = 0
  seen_files = 0
  stack: list[tuple[Path, int]] = [(path, 0)]
  while stack:
    directory, depth = stack.pop()
    seen_dirs += 1
    if seen_dirs > MAX_DISCOVERY_DIRS:
      return sorted(candidates[:max_candidates]), True, Blocker(tool="source", message=f"ZML directory discovery stopped after {MAX_DISCOVERY_DIRS} directories", guidance="pass a narrower log root or exact ZML file")
    try:
      entries = []
      with os.scandir(directory) as iterator:
        for index, entry in enumerate(iterator, start=1):
          if index > MAX_DISCOVERY_ENTRIES_PER_DIR:
            return sorted(candidates[:max_candidates]), True, Blocker(tool="source", message=f"ZML directory discovery stopped after {MAX_DISCOVERY_ENTRIES_PER_DIR} entries in {directory}", guidance="pass a narrower log root or exact ZML file")
          entries.append(entry)
    except OSError as exc:
      return sorted(candidates[:max_candidates]), True, Blocker(tool="source", message=f"ZML directory discovery stopped at unreadable directory {directory}: {exc}", guidance="pass a readable narrower log root or exact ZML file")
    child_dirs: list[Path] = []
    for entry in entries:
      try:
        if entry.is_dir(follow_symlinks=False):
          child_dirs.append(Path(entry.path))
        elif entry.is_file(follow_symlinks=False):
          seen_files += 1
          if seen_files > MAX_DISCOVERY_FILES:
            return sorted(candidates[:max_candidates]), True, Blocker(tool="source", message=f"ZML directory discovery stopped after {MAX_DISCOVERY_FILES} files", guidance="pass a narrower log root or exact ZML file")
          candidate = Path(entry.path)
          if is_zml_candidate(candidate):
            text = str(candidate)
            if text not in seen:
              seen.add(text)
              candidates.append(text)
              if len(candidates) > max_candidates:
                return sorted(candidates[:max_candidates]), True, None
      except OSError:
        continue
    if depth < MAX_DISCOVERY_DEPTH:
      stack.extend((child, depth + 1) for child in child_dirs)
  return sorted(candidates), False, None


def safe_resolve(path: Path) -> Path:
  try:
    return path.resolve()
  except OSError:
    return path.absolute()
