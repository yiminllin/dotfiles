from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HilPreset:
    name: str
    canonical_test: str
    display_name: str
    test_record_query: str
    aliases: tuple[str, ...] = ()
    run_title_fragments: tuple[str, ...] = ()
    job_name_fragments: tuple[str, ...] = ()

    def to_legacy_config(self) -> dict[str, Any]:
        return {
            "canonical_test": self.canonical_test,
            "display_name": self.display_name,
            "test_record_query": self.test_record_query,
            "run_title_fragments": self.run_title_fragments,
            "job_name_fragments": self.job_name_fragments,
        }


COMPATIBILITY_ALIASES = {
    "autokiosk": "zip_autokiosk",
    "real-dock-delivery": "zip_delivery_real_dock",
}

RELEASE_SUITE_TESTS = {
    "redock_back_to_back_5x",
    "delivery_back_to_back_2x",
    "mission_suite",
    "zip_delivery_ev3",
    "zip_delivery_with_redirect",
    "zip_delivery_ev3_with_redirect",
    "zip_delivery_real_dock",
    "zip_delivery_high_frequency_shadows",
    "auto_cloud_mission",
}

MISSION_SUITE_MEMBER_TESTS = {
    "zip_redock",
    "zip_delivery",
    "zip_fixed_wing",
    "zip_autokiosk",
    "zip_delivery_long",
}

HIL_TEST_TOKEN_RE = re.compile(r"\bHIL Test:\s*([A-Za-z0-9_]+)", re.IGNORECASE)
TOKEN_CHARS = "A-Za-z0-9_"

SCHEDULED_RUN_TITLES = {
    "zip_delivery": ("Scheduled - Hourly", "Scheduled - Experimental Hourly"),
    "zip_delivery_ev3": ("Scheduled - Hourly", "Scheduled - Experimental Hourly"),
    "dock_hil_full_suite": ("Scheduled - Dock Suite",),
    "lower_and_raise_droid": ("Scheduled - Experimental Suite",),
    "zip_delivery_v4": ("Scheduled - Experimental Suite",),
    "avionics_faulted_suite_memory_leak": ("Scheduled - Experimental Suite",),
    "avionics_faulted_suite_wifi_firmware_fault": ("Scheduled - Experimental Suite",),
    "zip_adsb_stress_test": ("Scheduled - Experimental Suite",),
    "noop_test": ("Scheduled - Experimental Suite",),
    "delivery_back_to_back_10x": ("Scheduled - Experimental Suite",),
    "test_ota_jp5_to_jp6": ("Scheduled - Experimental Suite",),
    "return_to_service": ("Scheduled - RTS Suite",),
    "return_to_service_ev3": ("Scheduled - RTS Suite",),
}

PRESET_SOURCE_ROWS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("auto_cloud_mission", "Auto Cloud Mission Test", "phoenix_delivery_real_cloud", ()),
    ("avionics_faulted_suite_memory_leak", "Avionics Faulted Suite", "avionics_faulted_suite_memory_leak", ()),
    ("avionics_faulted_suite_wifi_firmware_fault", "Avionics Faulted Suite", "avionics_wifi_fault", ()),
    ("bootloader_validation_test", "Bootloader Validation Test", "BootloaderValidationTestSuite", ()),
    ("cell_modem_switching", "Cell Modem Switching Test", "CellModemSwitchTest", ()),
    ("compute_failover", "Compute Failover Test", "compute_failover", ()),
    ("cloud_mode", "Cloud Mode Test", "phoenix_cloud_mode", ()),
    ("delivery_back_to_back_2x", "Zip Delivery Back-to-Back Test", "phoenix_delivery_back_to_back_2x", ()),
    ("delivery_back_to_back_10x", "Zip Delivery 10x B2B Test (Phoenix)", "phoenix_delivery_back_to_back_10x", ()),
    ("delivery_back_to_back_100x", "Zip Delivery 100x B2B Test (Phoenix)", "phoenix_delivery_back_to_back_100x", ()),
    ("dock_hil_full_suite", "Dock HIL Test", "DockSysTestSuite", ()),
    ("ev3_zip_droid_delivery", "EV3 Zip Droid Delivery Test", "ev3_zip_droid_delivery", ()),
    ("hil_health_check", "HIL Health Check", "FullHilHealthCheck", ()),
    ("lower_and_raise_droid", "Zip Lower and Raise Droid Test", "phoenix_lower_and_raise_droid", ()),
    ("mission_suite", "Mission Suite", "phoenix_suite", ()),
    ("noop_test", "Noop Test", "NoopTest", ()),
    ("ota_deploy", "OTA Deploy Only", "DeployOTA", ()),
    ("paraland_mission", "Paraland Mission Test", "paraland_mission", ()),
    ("redock_back_to_back_5x", "Zip Redock 5x Back-to-Back Test", "phoenix_redock_back_to_back_5x", ()),
    ("return_to_service", "Return to Service Test", "phoenix_delivery", ()),
    ("return_to_service_ev3", "Return to Service EV3 Test", "phoenix_delivery_ev3", ()),
    ("test_ota_jp5_to_jp6", "JP6 OTA Test", "TestOtaJP5ToJP6", ()),
    ("test_zipping_point_hil", "Zipping Point HIL Test", "test_zipping_point_hil", ()),
    ("zip_adsb_stress_test", "Zip ADSB Stress Test", "ZipAdsbStressTest", ()),
    ("zip_autokiosk", "Zip Autokiosk Load + Delivery Test", "phoenix_autokiosk_load_and_deliver", ("autokiosk",)),
    ("zip_delivery", "Zip Droid Delivery Test", "phoenix_delivery", ()),
    ("zip_delivery_ev3", "EV3 Zip Droid Delivery Test", "phoenix_delivery_ev3", ()),
    ("zip_delivery_ev3_with_redirect", "EV3 Zip Droid Delivery Test With Redirect", "phoenix_delivery_ev3_with_redirect", ()),
    ("zip_delivery_high_frequency_shadows", "Zip Droid Delivery Test (Higher Frequency Shadows)", "phoenix_delivery_high_frequency_shadows", ()),
    ("zip_delivery_log_processing", "Zip Delivery Log Processing Test", "phoenix_delivery_log_processing", ()),
    ("zip_delivery_long", "Zip Droid Delivery Long Transit Test", "phoenix_delivery_long_transit", ()),
    ("zip_delivery_real_dock", "Zip Droid Delivery with Real Dock", "phoenix_delivery_real_dock", ("real-dock-delivery",)),
    ("zip_delivery_v4", "Zip Droid Delivery Test (Phoenix V4)", "phoenix_delivery_v4", ()),
    ("zip_delivery_with_redirect", "Zip Droid Delivery Test With Redirect", "phoenix_delivery_with_redirect", ()),
    ("zip_fixed_wing", "Zip Droid Long Range Delivery Test", "phoenix_fixed_wing", ()),
    ("zip_redock", "Zip Redock Test", "phoenix_redock", ()),
)


def preset_names() -> tuple[str, ...]:
    return tuple(PRESET_CONFIGS)


def canonical_preset_names() -> tuple[str, ...]:
    return tuple(PRESETS)


def resolve_preset(name: str | None) -> HilPreset | None:
    if not name:
        return None
    return PRESET_LOOKUP.get(name)


def preset_test_record_query(name: str | None) -> str | None:
    preset = resolve_preset(name)
    return preset.test_record_query if preset else None


def preset_matches(value: Any, preset: str, fragment_key: str) -> bool:
    resolved = resolve_preset(preset)
    if not resolved:
        return False
    text = str(value or "")
    if fragment_key == "job_name_fragments":
        return job_text_matches_preset(text, resolved)
    if fragment_key == "run_title_fragments":
        return run_title_matches_preset(text, resolved)
    fragments = getattr(resolved, fragment_key)
    return any(fragment.lower() in text.lower() for fragment in fragments)


def job_text_matches_preset(text: str, preset: HilPreset) -> bool:
    hil_test_tokens = [match.group(1).lower() for match in HIL_TEST_TOKEN_RE.finditer(text)]
    if hil_test_tokens:
        allowed = {preset.name}
        if preset.name in MISSION_SUITE_MEMBER_TESTS:
            allowed.add("mission_suite")
        return any(token in allowed for token in hil_test_tokens)

    normalized_text = normalize_phrase(text)
    return any(
        normalize_phrase(fragment) == normalized_text or (is_identifier_fragment(fragment) and safe_token_match(text, fragment))
        for fragment in preset.job_name_fragments
    )


def run_title_matches_preset(text: str, preset: HilPreset) -> bool:
    if safe_token_match(text, preset.name):
        return True
    if preset.name in MISSION_SUITE_MEMBER_TESTS and safe_token_match(text, "mission_suite"):
        return True
    return any(
        fragment.lower() in text.lower()
        for fragment in preset.run_title_fragments
        if not is_manual_canonical_fragment(fragment, preset.name)
    )


def safe_token_match(text: str, token: str) -> bool:
    return bool(re.search(rf"(?<![{TOKEN_CHARS}]){re.escape(token)}(?![{TOKEN_CHARS}])", text, re.IGNORECASE))


def is_manual_canonical_fragment(fragment: str, canonical_name: str) -> bool:
    return fragment.lower() == f"manual run - {canonical_name.lower()}"


def normalize_phrase(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def is_identifier_fragment(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]+", value))


def alias_targets() -> dict[str, str]:
    return {alias: preset.name for preset in PRESETS.values() for alias in preset.aliases}


def _build_preset(name: str, display_name: str, test_record_query: str, aliases: tuple[str, ...]) -> HilPreset:
    return HilPreset(
        name=name,
        canonical_test=name,
        display_name=display_name,
        test_record_query=test_record_query,
        aliases=aliases,
        run_title_fragments=run_title_fragments(name),
        job_name_fragments=job_name_fragments(name, display_name),
    )


def run_title_fragments(name: str) -> tuple[str, ...]:
    fragments = [f"Manual Run - {name.upper()}", f"Manual Run - {name}"]
    fragments.extend(SCHEDULED_RUN_TITLES.get(name, ()))
    if name in RELEASE_SUITE_TESTS or name in MISSION_SUITE_MEMBER_TESTS:
        fragments.extend(("Scheduled - Release Suite", "Manual Run - RELEASE_SUITE", "Manual Run - release_suite"))
    if name in MISSION_SUITE_MEMBER_TESTS:
        fragments.extend(("Manual Run - MISSION_SUITE", "Manual Run - mission_suite"))
    return unique_tuple(fragments)


def job_name_fragments(name: str, display_name: str) -> tuple[str, ...]:
    fragments = [f"HIL Test: {name}", name, display_name]
    if name in MISSION_SUITE_MEMBER_TESTS:
        fragments.extend(("Mission Suite", "HIL Test: mission_suite", "mission_suite"))
    return unique_tuple(fragments)


def unique_tuple(values: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return tuple(result)


PRESETS = {
    name: _build_preset(name, display_name, test_record_query, aliases)
    for name, display_name, test_record_query, aliases in PRESET_SOURCE_ROWS
}

PRESET_LOOKUP = {
    lookup_name: preset
    for preset in PRESETS.values()
    for lookup_name in (preset.name, *preset.aliases)
}

PRESET_CONFIGS = {name: preset.to_legacy_config() for name, preset in PRESET_LOOKUP.items()}
