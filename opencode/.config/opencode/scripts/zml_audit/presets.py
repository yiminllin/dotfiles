from __future__ import annotations

from .models import TopicSpec


CLOCK_BIAS_FIELDS = ("clock_bias", "clock_bias_m", "clock_bias_s", "clock_drift", "clock_drift_mps", "clock_drift_sps")


BUNDLES: dict[str, list[TopicSpec]] = {
  "prod_nav_truth_vs_nav": [
    TopicSpec("nav.gnc_state"),
    TopicSpec("/compute_a.nav.gnc_state"),
    TopicSpec("/compute_b.nav.gnc_state"),
    TopicSpec("nav.gnc_state_status"),
    TopicSpec("nav.state+"),
    TopicSpec("/compute_a.nav.state+"),
    TopicSpec("transforms.local_TD_body"),
    TopicSpec("/compute_b.transforms.local_TD_body"),
    TopicSpec("/zip.transforms.local_T_ecef"),
    TopicSpec("phoenix.physics_truth_output"),
    TopicSpec("phoenix.physics_truth"),
    TopicSpec("ground_truth"),
  ],
  "gnss_timing_residuals": [
    TopicSpec("/compute_a.fusion_engine.pose"),
    TopicSpec("/compute_b.fusion_engine.pose"),
    TopicSpec("/compute_a.gnss.raw_data"),
    TopicSpec("/compute_b.gnss.raw_data"),
    TopicSpec("/compute_a.gnss.pps"),
    TopicSpec("/compute_b.gnss.pps"),
    TopicSpec("gnss.health"),
    TopicSpec("/compute_b.gnss.health"),
    TopicSpec("pps.health"),
    TopicSpec("clock_manager.health"),
    TopicSpec("/compute_b.clock_manager.health"),
    TopicSpec("clock_manager.alarm_report"),
    TopicSpec("/compute_b.clock_manager.alarm_report"),
    TopicSpec("zip_antenna_status"),
    TopicSpec("hil.zip_antenna_status"),
    TopicSpec("nav.state+", CLOCK_BIAS_FIELDS),
  ],
  "imu_bias_pim_nav_filter": [
    TopicSpec("nav.state+"),
    TopicSpec("nav.imu_monitor"),
    TopicSpec("imu.raw_samples"),
    TopicSpec("imu.prefiltered"),
    TopicSpec("hil.nav.gnc_state"),
    TopicSpec("hil.nav.gnc_state_status"),
    TopicSpec("hil.nav.status"),
    TopicSpec("diagnostics.imu_monitor"),
    TopicSpec("diagnostics.StateWithPrefiltering"),
    TopicSpec("diagnostics.NavigationTelemetry"),
  ],
  "dock_winch_latch": [
    TopicSpec("dock_presence_detection"),
    TopicSpec("/compute_a.dock_presence_detection"),
    TopicSpec("dock_status"),
    TopicSpec("/compute_a.dock_status"),
    TopicSpec("/compute_a.dock_latch_status"),
    TopicSpec("winch.gnc.droid_gnc"),
    TopicSpec("/droid.droid.gnc.winch_gnc"),
    TopicSpec("zip.gnc.droid_gnc"),
    TopicSpec("/droid.nav.vision_docking_state"),
    TopicSpec("nav.localization_status"),
  ],
  "wind_airdata_qbar": [
    TopicSpec("gnc.wind_estimator.output"),
    TopicSpec("/compute_b.gnc.wind_estimator.output"),
    TopicSpec("gnc.wind_estimator.debug"),
    TopicSpec("air_data.absolute_pressure"),
    TopicSpec("/compute_a.air_data.absolute_pressure"),
    TopicSpec("air_data.differential_pressure"),
    TopicSpec("/compute_a.air_data.differential_pressure"),
    TopicSpec("air_data.temperature"),
    TopicSpec("/compute_b.vane.angle_of_attack"),
    TopicSpec("/compute_b.vane.temperature_humidity"),
  ],
  "process_alarm_watchdog_status": [
    TopicSpec("zip_executive_v4.status"),
    TopicSpec("linux_exception_report"),
    TopicSpec("/compute_b.linux_exception_report"),
    TopicSpec("service_restart_monitor.status"),
    TopicSpec("service_restart_monitor.alarm_report"),
    TopicSpec("c2_status"),
    TopicSpec("comms_agent.alarm_report"),
    TopicSpec("zml_logger.zml_logger_health"),
    TopicSpec("/compute_a.zml_logger.zml_logger_health"),
    TopicSpec("/compute_b.zml_logger.zml_logger_health"),
    TopicSpec("/droid.droid_log_manager.status"),
    TopicSpec("/droid.systemd_target_agent.flight.state?"),
    TopicSpec("/droid.systemd_target_agent.sleep.state?"),
  ],
}


ALIASES = {
  "prod-nav-truth-vs-nav": "prod_nav_truth_vs_nav",
  "prod-nav": "prod_nav_truth_vs_nav",
  "truth-vs-nav": "prod_nav_truth_vs_nav",
  "gnss-timing-residuals": "gnss_timing_residuals",
  "gnss-timing": "gnss_timing_residuals",
  "imu-bias-pim-nav-filter": "imu_bias_pim_nav_filter",
  "imu-bias": "imu_bias_pim_nav_filter",
  "pim-residuals": "imu_bias_pim_nav_filter",
  "dock-winch-latch": "dock_winch_latch",
  "wind-airdata-qbar": "wind_airdata_qbar",
  "process-alarm-watchdog-status": "process_alarm_watchdog_status",
}


PRESETS: dict[str, list[TopicSpec]] = {name: specs for name, specs in BUNDLES.items()}
PRESETS.update({alias: BUNDLES[target] for alias, target in ALIASES.items()})


def expand_specs(topics: list[str], fields: list[str], preset: str | None) -> list[TopicSpec]:
  specs: list[TopicSpec] = []
  if preset:
    specs.extend(PRESETS[preset])
  specs.extend(TopicSpec(topic, tuple(fields)) for topic in topics)
  return merge_specs(specs)


def merge_specs(specs: list[TopicSpec]) -> list[TopicSpec]:
  merged: dict[str, set[str]] = {}
  order: list[str] = []
  for spec in specs:
    if spec.name not in merged:
      merged[spec.name] = set()
      order.append(spec.name)
    merged[spec.name].update(spec.fields)
  return [TopicSpec(name, tuple(sorted(merged[name]))) for name in order]
