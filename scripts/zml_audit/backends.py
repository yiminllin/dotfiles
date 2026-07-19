from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from .models import Blocker, JsonDict, TimeWindow, compact_dict


BACKEND_CHOICES = ("auto", "zml-conv", "zml-cli", "local-text")
DEFAULT_SYSTEMS_ROOT = Path("/Systems")


def default_systems_root() -> str | None:
  return str(DEFAULT_SYSTEMS_ROOT) if DEFAULT_SYSTEMS_ROOT.exists() else None


def resolve_systems_root(systems_root: str | None = None) -> str | None:
  if systems_root:
    return str(Path(systems_root).expanduser())
  return default_systems_root()


@dataclass(frozen=True)
class BackendResult:
  stdout: str = ""
  blocker: Blocker | None = None
  backend: str = ""
  metadata: JsonDict = field(default_factory=dict)


class ZmlBackend(Protocol):
  name: str

  def list_topics(self, path: str) -> BackendResult: ...

  def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()) -> BackendResult: ...


class CommandBackend:
  name = "command"

  def __init__(self, timeout_seconds: float = 60.0, runner: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> None:
    self.timeout_seconds = timeout_seconds
    self.runner = runner or subprocess.run

  def _run(self, command: list[str], action: str, cwd: str | None = None, timeout_seconds: float | None = None, env: dict[str, str] | None = None, metadata: JsonDict | None = None) -> BackendResult:
    timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
    result_metadata = self.metadata(action, {"cwd": cwd, **(metadata or {})})
    try:
      completed = self.runner(command, check=False, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    except subprocess.TimeoutExpired as exc:
      return BackendResult(
        blocker=Blocker(
          tool=self.name,
          message=f"{self.name} {action} timed out after {timeout:g}s",
          command=format_command(command, cwd),
          stderr_excerpt=(exc.stderr or "")[:500] if isinstance(exc.stderr, str) else None,
        ),
        backend=self.name,
        metadata=result_metadata,
      )
    if completed.returncode != 0:
      return BackendResult(
        blocker=Blocker(
          tool=self.name,
          message=f"{self.name} {action} failed",
          command=format_command(command, cwd),
          returncode=completed.returncode,
          stderr_excerpt=completed.stderr[:500],
        ),
        backend=self.name,
        metadata=result_metadata,
      )
    return BackendResult(stdout=completed.stdout, backend=self.name, metadata=result_metadata)

  def metadata(self, operation: str, extra: JsonDict | None = None) -> JsonDict:
    return compact_dict({"selected": self.name, "operation": operation, **(extra or {})})


class ZmlCliBackend(CommandBackend):
  name = "zml-cli"

  def __init__(self, binary: str = "zml", timeout_seconds: float = 60.0, runner: Callable[..., subprocess.CompletedProcess[str]] | None = None) -> None:
    super().__init__(timeout_seconds=timeout_seconds, runner=runner)
    self.binary = binary

  def available_blocker(self) -> Blocker | None:
    if shutil.which(self.binary) is not None:
      return None
    return Blocker(
      tool=self.name,
      message="zml binary is not available on PATH",
      guidance="install zml or run this helper in an environment with the ZML CLI available",
    )

  def list_topics(self, path: str) -> BackendResult:
    if blocker := self.available_blocker():
      return unavailable_result(self.name, blocker, [self.binary, "--zml", path, "list"], "list topics")
    return self._run([self.binary, "--zml", path, "list"], "list topics")

  def field_metadata(self, path: str) -> BackendResult:
    command = [self.binary, "--zml", path, "list", "--metadata"]
    metadata = self.metadata("field metadata", {"source": "zml-list"})
    if blocker := self.available_blocker():
      return unavailable_result(self.name, blocker, command, "field metadata", metadata)
    return with_metadata(self._run(command, "field metadata", timeout_seconds=min(self.timeout_seconds, 1.5)), metadata)

  def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()) -> BackendResult:
    if blocker := self.available_blocker():
      return unavailable_result(self.name, blocker, [self.binary, "--zml", path, "print", topic], f"read topic {topic}", zml_cli_metadata(window))
    result = self._run([self.binary, "--zml", path, "print", topic], f"read topic {topic}")
    return with_metadata(result, zml_cli_metadata(window))

  def read_topic_raw_decoded(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...]) -> BackendResult:
    command = [self.binary, "--zml", path, "print_raw", topic]
    metadata = compact_dict({"selected": "zml-print-raw", "operation": "read topic raw", "local_time_filtering": bool(window.normalized().to_dict()), "field_filtering": "raw_decode"})
    if blocker := self.available_blocker():
      return unavailable_result("zml-print-raw", blocker, command, f"read raw topic {topic}", metadata)
    raw_result = self._run_raw(command, f"read raw topic {topic}")
    if raw_result.blocker:
      return with_metadata(raw_result, metadata)
    from .raw import decode_print_raw_stdout

    stdout, decode_blocker = decode_print_raw_stdout(raw_result.stdout, topic, tuple(fields), window)
    if decode_blocker:
      return BackendResult(blocker=decode_blocker, backend="zml-print-raw", metadata=metadata)
    return BackendResult(stdout=stdout, backend="zml-print-raw", metadata=metadata)

  def _run_raw(self, command: list[str], action: str) -> BackendResult:
    try:
      completed = self.runner(command, check=False, capture_output=True, text=True, timeout=self.timeout_seconds)
    except subprocess.TimeoutExpired as exc:
      return BackendResult(
        blocker=Blocker(tool="zml-print-raw", message=f"zml print_raw {action} timed out after {self.timeout_seconds:g}s", command=format_command(command), stderr_excerpt=(exc.stderr or "")[:500] if isinstance(exc.stderr, str) else None),
        backend="zml-print-raw",
        metadata={"selected": "zml-print-raw", "operation": action},
      )
    if completed.returncode != 0:
      return BackendResult(
        blocker=Blocker(tool="zml-print-raw", message="zml print_raw failed", command=format_command(command), returncode=completed.returncode, stderr_excerpt=completed.stderr[:500]),
        backend="zml-print-raw",
        metadata={"selected": "zml-print-raw", "operation": action},
      )
    return BackendResult(stdout=completed.stdout, backend="zml-print-raw", metadata={"selected": "zml-print-raw", "operation": action})

  def print_topic(self, path: str, topic: str) -> BackendResult:
    return self.read_topic(path, topic, TimeWindow())


class ZmlConvBackend(CommandBackend):
  name = "zml-conv"

  def __init__(self, timeout_seconds: float = 60.0, runner: Callable[..., subprocess.CompletedProcess[str]] | None = None, systems_root: str | None = None, prefer_bazel: bool = False, require_systems_root: bool = False) -> None:
    super().__init__(timeout_seconds=timeout_seconds, runner=runner)
    self.systems_root = resolve_systems_root(systems_root)
    self.prefer_bazel = prefer_bazel
    self.require_systems_root = require_systems_root

  def available_command(self) -> tuple[list[str], str | None, JsonDict, Blocker | None]:
    fallback_reasons: list[JsonDict] = []
    bazel_command = self._bazel_command()
    if self.prefer_bazel and bazel_command:
      return bazel_command, self.systems_root, self.command_metadata("bazel", fallback_reasons), None

    for binary in ("zml_conv", "zml-conv"):
      if shutil.which(binary):
        if self.require_systems_root:
          fallback_reasons.append({"backend": "direct", "reason": "systems_root_execution_required"})
          break
        return [binary], None, self.command_metadata("direct", fallback_reasons, binary=binary), None

    if not fallback_reasons:
      fallback_reasons.append({"backend": "direct", "reason": "zml_conv/zml-conv not on PATH"})
    if bazel_command:
      return bazel_command, self.systems_root, self.command_metadata("bazel", fallback_reasons), None

    if not self.systems_root:
      fallback_reasons.append({"backend": "bazel", "reason": "systems_root unavailable"})
    elif not Path(self.systems_root).exists():
      fallback_reasons.append({"backend": "bazel", "reason": f"systems_root does not exist: {self.systems_root}"})
    elif not shutil.which("bazel"):
      fallback_reasons.append({"backend": "bazel", "reason": "bazel not on PATH"})
    return [], self.systems_root, self.command_metadata(None, fallback_reasons), Blocker(
      tool=self.name,
      message="no zml-conv execution path is available",
      guidance="install zml_conv/zml-conv, run with --systems-root /Systems where Bazel is available, or use --backend zml-cli for standalone files",
    )

  def _bazel_command(self) -> list[str] | None:
    if not self.systems_root or not Path(self.systems_root).exists() or not shutil.which("bazel"):
      return None
    return ["bazel", "run", "//tools/zml_conv:zml_conv", "--"]

  def command_metadata(self, invocation: str | None, fallback_reasons: list[JsonDict], binary: str | None = None) -> JsonDict:
    return compact_dict({
      "systems_root": self.systems_root,
      "cwd": self.systems_root if invocation == "bazel" else None,
      "zml_conv_invocation": invocation,
      "zml_conv_binary": binary,
      "fallbacks": fallback_reasons,
    })

  def list_topics(self, path: str) -> BackendResult:
    return BackendResult(
      blocker=Blocker(
        tool=self.name,
        message="zml-conv does not provide topic listing; use --backend auto or --backend zml-cli for topics/list-topics",
        command=f"zml-conv --input {path} --identifier <topic> --output - --format jsonl",
      ),
      backend=self.name,
      metadata=self.metadata("list topics", {"unsupported_operation": True}),
    )

  def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()) -> BackendResult:
    prefix, cwd, command_metadata, blocker = self.available_command()
    command = build_zml_conv_command(path, topic, window, prefix=prefix or ["zml_conv"])
    metadata = self.metadata("read topic", {"pushed_down_time_window": bool(window.normalized().to_dict()), **command_metadata})
    if blocker:
      return unavailable_result(self.name, blocker, command, f"read topic {topic}", metadata)
    return with_metadata(self._run(command, f"read topic {topic}", cwd=cwd, metadata=command_metadata), metadata)


class LocalTextBackend:
  name = "local-text"

  def list_topics(self, path: str) -> BackendResult:
    text, blocker = self._read_text(path)
    if blocker:
      return BackendResult(blocker=blocker, backend=self.name, metadata=self.metadata("list topics"))
    from .extract import parse_samples

    topics = sorted({sample.topic for sample in parse_samples(text)})
    return BackendResult(stdout="\n".join(topics) + ("\n" if topics else ""), backend=self.name, metadata=self.metadata("list topics"))

  def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()) -> BackendResult:
    text, blocker = self._read_text(path)
    if blocker:
      return BackendResult(blocker=blocker, backend=self.name, metadata=self.metadata("read topic"))
    from .extract import parse_samples

    samples = [sample.to_dict() for sample in parse_samples(text) if sample.topic == topic and window.normalized().contains(sample.timestamp)]
    return BackendResult(stdout="\n".join(json.dumps(sample) for sample in samples), backend=self.name, metadata=self.metadata("read topic"))

  def _read_text(self, path: str) -> tuple[str, Blocker | None]:
    try:
      return Path(path).read_text(encoding="utf-8"), None
    except UnicodeDecodeError as exc:
      return "", Blocker(tool=self.name, message=f"input is not UTF-8 text and no binary ZML backend decoded it: {exc}", guidance="Use zml-conv or zml-cli for binary .zml/.zml.zst files.")
    except OSError as exc:
      return "", Blocker(tool=self.name, message=f"input could not be read: {exc}", guidance="Provide an existing local ZML/ZST path.")

  def metadata(self, operation: str) -> JsonDict:
    return {"selected": self.name, "operation": operation}


class AutoBackend:
  name = "auto"

  def __init__(self, factories: list[Callable[[], ZmlBackend]] | None = None) -> None:
    self.factories = factories or [ZmlConvBackend, ZmlCliBackend]
    self._backend_cache: dict[int, ZmlBackend] = {}
    self._availability_cache: dict[int, Blocker | None] = {}
    self._field_metadata_blocker: BackendResult | None = None

  def list_topics(self, path: str) -> BackendResult:
    return self._first_available(lambda backend: getattr(backend, "name") != "zml-conv", lambda backend: backend.list_topics(path), "list topics", unsupported_if_no_backend=True)

  def field_metadata(self, path: str) -> BackendResult:
    if self._field_metadata_blocker is not None:
      metadata = {**self._field_metadata_blocker.metadata, "cached_unavailable": True}
      return BackendResult(blocker=self._field_metadata_blocker.blocker, backend=self._field_metadata_blocker.backend, metadata=compact_dict(metadata))
    result = self._first_available(lambda backend: callable(getattr(backend, "field_metadata", None)), lambda backend: backend.field_metadata(path), "field metadata", unsupported_if_no_backend=True)  # type: ignore[attr-defined]
    if result.blocker and result.metadata.get("unsupported_operation"):
      self._field_metadata_blocker = result
    return result

  def read_topic(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...] = ()) -> BackendResult:
    if fields:
      return self._read_topic_with_raw_fallback(path, topic, window, fields)
    return self._first_available(lambda backend: True, lambda backend: backend.read_topic(path, topic, window), f"read topic {topic}")

  def _read_topic_with_raw_fallback(self, path: str, topic: str, window: TimeWindow, fields: tuple[str, ...]) -> BackendResult:
    failures: list[JsonDict] = []
    raw_backend: object | None = None
    for index, _factory in enumerate(self.factories):
      backend = self._backend(index)
      name = getattr(backend, "name", backend.__class__.__name__)
      blocker = self._available_blocker(index, backend)
      if blocker:
        failures.append({"backend": name, "reason": blocker.message})
        continue
      if hasattr(backend, "read_topic_raw_decoded"):
        raw_backend = backend
      try:
        result = backend.read_topic(path, topic, window, fields=fields)  # type: ignore[call-arg]
      except TypeError:
        result = backend.read_topic(path, topic, window)  # type: ignore[call-arg]
      metadata = {**result.metadata, "requested": "auto"}
      if failures:
        metadata["fallbacks"] = failures
      if not result.blocker:
        return with_metadata(result, metadata)
      failures.append({"backend": name, "reason": result.blocker.message, "tool": result.blocker.tool})

    if raw_backend is not None:
      raw_result = raw_backend.read_topic_raw_decoded(path, topic, window, fields)  # type: ignore[attr-defined]
      metadata = {**raw_result.metadata, "requested": "auto", "decoded_failures": failures}
      return with_metadata(raw_result, metadata)
    return BackendResult(
      blocker=Blocker(tool="auto", message=f"no decoded ZML backend succeeded for read topic {topic} and no raw fallback was available", guidance="install zml CLI for raw fallback or use a decoded backend"),
      backend="auto",
      metadata=compact_dict({"requested": "auto", "decoded_failures": failures}),
    )

  def _first_available(self, supports_operation: Callable[[ZmlBackend], bool], operation: Callable[[ZmlBackend], BackendResult], action: str, unsupported_if_no_backend: bool = False) -> BackendResult:
    fallbacks: list[JsonDict] = []
    for index, _factory in enumerate(self.factories):
      backend = self._backend(index)
      name = getattr(backend, "name", backend.__class__.__name__)
      if not supports_operation(backend):
        fallbacks.append({"backend": name, "reason": "unsupported_operation"})
        continue
      blocker = self._available_blocker(index, backend)
      if blocker:
        fallbacks.append({"backend": name, "reason": blocker.message})
        continue
      result = operation(backend)
      metadata = {**result.metadata, "requested": "auto"}
      if fallbacks:
        metadata["fallbacks"] = fallbacks
      return with_metadata(result, metadata)
    metadata = {"requested": "auto", "fallbacks": fallbacks}
    if unsupported_if_no_backend:
      metadata["unsupported_operation"] = True
    return BackendResult(
      blocker=Blocker(
        tool="auto",
        message=f"no usable ZML backend found for {action}",
        guidance="install zml_conv/zml-conv, run with --systems-root /Systems where Bazel is available, or install zml CLI",
      ),
      backend="auto",
      metadata=compact_dict(metadata),
    )

  def _backend(self, index: int) -> ZmlBackend:
    if index not in self._backend_cache:
      self._backend_cache[index] = self.factories[index]()
    return self._backend_cache[index]

  def _available_blocker(self, index: int, backend: ZmlBackend) -> Blocker | None:
    if index not in self._availability_cache:
      self._availability_cache[index] = backend_available_blocker(backend)
    return self._availability_cache[index]


def select_backend(name: str = "auto", timeout_seconds: float = 60.0, systems_root: str | None = None) -> ZmlBackend:
  resolved_systems_root = resolve_systems_root(systems_root)
  if name == "auto":
    return AutoBackend(factories=[lambda: ZmlConvBackend(timeout_seconds, systems_root=resolved_systems_root, prefer_bazel=bool(resolved_systems_root)), lambda: ZmlCliBackend(timeout_seconds=timeout_seconds)])
  if name == "zml-conv":
    return ZmlConvBackend(timeout_seconds=timeout_seconds, systems_root=resolved_systems_root)
  if name == "zml-cli":
    return ZmlCliBackend(timeout_seconds=timeout_seconds)
  if name == "local-text":
    return LocalTextBackend()
  raise ValueError(f"unsupported backend: {name}")


def backend_available_blocker(backend: object) -> Blocker | None:
  available_blocker = getattr(backend, "available_blocker", None)
  if callable(available_blocker):
    return available_blocker()
  available_command = getattr(backend, "available_command", None)
  if callable(available_command):
    result = available_command()
    if len(result) == 4:
      _, _, _, blocker = result
    elif len(result) == 3:
      _, _, blocker = result
    else:
      _, blocker = result
    return blocker
  return None


def build_zml_conv_command(path: str, topic: str, window: TimeWindow, prefix: list[str] | None = None) -> list[str]:
  command = list(prefix or ["zml_conv"])
  command.extend(["--input", path, "--output", "-", "--identifier", topic, "--format", "jsonl"])
  normalized = window.normalized()
  if normalized.start is not None:
    command.extend(["--start-ts", epoch_to_rfc3339(normalized.start)])
  if normalized.end is not None:
    command.extend(["--end-ts", epoch_to_rfc3339(exclusive_end_for_inclusive_window(normalized.end))])
  return command


def exclusive_end_for_inclusive_window(value: float) -> float:
  return value + 0.000001


def epoch_to_rfc3339(value: float) -> str:
  return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def zml_cli_metadata(window: TimeWindow) -> JsonDict:
  return {"local_time_filtering": bool(window.normalized().to_dict())}


def unavailable_result(name: str, blocker: Blocker, command: list[str], action: str, metadata: JsonDict | None = None) -> BackendResult:
  updated = Blocker(
    tool=blocker.tool,
    message=blocker.message,
    command=format_command(command),
    guidance=blocker.guidance,
    returncode=blocker.returncode,
    stderr_excerpt=blocker.stderr_excerpt,
  )
  return BackendResult(blocker=updated, backend=name, metadata=compact_dict({"selected": name, "operation": action, **(metadata or {})}))


def with_metadata(result: BackendResult, metadata: JsonDict) -> BackendResult:
  return BackendResult(stdout=result.stdout, blocker=result.blocker, backend=result.backend, metadata=compact_dict({**result.metadata, **metadata}))


def format_command(command: list[str], cwd: str | None = None) -> str:
  text = " ".join(command)
  return f"(cd {cwd} && {text})" if cwd else text
