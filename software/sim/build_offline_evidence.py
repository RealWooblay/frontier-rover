#!/usr/bin/env python3
"""Build and verify the laptop-only autonomy evidence manifest."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/sim/offline-autonomy-evidence.json"
FILES = {
    "physical_imu_log": ROOT / "artifacts/physical/2026-09-06-imu-motion.csv",
    "real2sim_fit": ROOT / "artifacts/sim/2026-09-06-imu-turn-fit.json",
    "turn_validation": ROOT / "artifacts/sim/2026-09-06-closed-loop-turn-validation.json",
    "mapping_benchmark": ROOT / "artifacts/sim/2026-09-06-high-fidelity-exploration.json",
    "policy_model": ROOT / "artifacts/models/high-fidelity-navigation-policy.npz",
    "policy_training": ROOT / "artifacts/models/high-fidelity-navigation-policy-training.json",
    "policy_evaluation": ROOT / "artifacts/sim/high-fidelity-policy-evaluation.json",
    "rejected_policy_baseline": ROOT / "artifacts/sim/high-fidelity-policy-evaluation-baseline.json",
    "contact_environment": ROOT / "software/sim/high_fidelity_env.py",
    "learned_policy_and_safety": ROOT / "software/sim/mlp_policy.py",
    "policy_training_code": ROOT / "software/sim/train_high_fidelity_policy.py",
    "policy_evaluation_code": ROOT / "software/sim/evaluate_high_fidelity_policy.py",
    "mapping_code": ROOT / "software/sim/exploration_scenario.py",
    "autonomy_lab_server": ROOT / "software/sim/lab_server.py",
    "autonomy_lab_ui": ROOT / "software/sim/lab.html",
    "camera_freshness_ui": ROOT / "software/sim/camera_freshness.js",
    "manual_drive_ui": ROOT / "software/sim/manual_drive.js",
    "simulation_course": ROOT / "docs/simulation-and-sim2real-course.md",
    "practical_course": ROOT / "docs/rover-practical-course.md",
    "learning_workshop": ROOT / "software/learning/rover_workshop.py",
    "controller_ablation": ROOT / "artifacts/sim/2026-09-08-controller-ablation.json",
    "policy_arena_desktop_capture": ROOT / "artifacts/images/policy-arena-desktop.png",
    "policy_arena_mobile_capture": ROOT / "artifacts/images/policy-arena-mobile.png",
}


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest() -> dict[str, object]:
    missing = [str(path) for path in FILES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing required evidence: {missing}")
    fit = read_json(FILES["real2sim_fit"])
    validation = read_json(FILES["turn_validation"])
    mapping = read_json(FILES["mapping_benchmark"])
    training = read_json(FILES["policy_training"])
    evaluation = read_json(FILES["policy_evaluation"])
    ablation = read_json(FILES["controller_ablation"])
    model_hash = sha256(FILES["policy_model"])
    if training["model_sha256"] != model_hash:
        raise ValueError("training report does not match the policy model")
    if evaluation["model"]["sha256"] != model_hash:
        raise ValueError("evaluation report does not match the policy model")
    if ablation["model_sha256"] != model_hash:
        raise ValueError("ablation report does not match the policy model")

    learned = evaluation["summary"]["high_fidelity_learned_mlp"]
    expert = evaluation["summary"]["deterministic_expert"]
    fault = evaluation["fault_recovery"]["summary"]["high_fidelity_learned_mlp"]
    checks = {
        "model_hash_matches_training_and_evaluation": True,
        "training_reduced_validation_error": (
            training["final_validation_mse"] < training["initial_validation_mse"]
        ),
        "learned_policy_beats_expert_success_rate": (
            learned["success_rate"] > expert["success_rate"]
        ),
        "learned_nominal_contact_episodes_zero": learned["contact_episodes"] == 0,
        "learned_fault_contact_episodes_zero": fault["contact_episodes"] == 0,
        "real2sim_improves_held_out_yaw_error": (
            validation["summary"]["held_out_rmse_reduction_percent"] > 0.0
        ),
        "rendered_mapping_majority_success": mapping["summary"]["success_rate"] >= 0.8,
    }
    return {
        "schema_version": 1,
        "generated_on": datetime.now(timezone.utc).date().isoformat(),
        "scope": "laptop-completable simulation, training, replay, and evidence",
        "stages": [
            {
                "name": "Real2Sim directional yaw identification",
                "state": "complete with physical data",
                "evidence": "MPU-9250 log, fitted MuJoCo parameters, three held-out final-yaw endpoints",
            },
            {
                "name": "Contact-physical Gymnasium environment",
                "state": "complete on laptop",
                "evidence": "MuJoCo wheel forces, friction, contacts, rays, latency, noise, and dead reckoning",
            },
            {
                "name": "Behavior cloning plus DAgger",
                "state": "complete on laptop",
                "evidence": "9-32-2 MLP, deterministic seeds, training report, immutable model hash",
            },
            {
                "name": "Held-out policy and actuator-fault evaluation",
                "state": "complete on laptop",
                "evidence": "same randomized worlds; ideal contact/stuck flags in policy observations; physical equivalents pending",
            },
            {
                "name": "Rendered-camera mapping and exploration",
                "state": "complete in simulation",
                "evidence": "RGB render, HSV target detector, occupancy map, frontiers, A*, target memory",
            },
            {
                "name": "Physical Sim2Real policy transfer",
                "state": "blocked by observation parity",
                "evidence": "physical rover lacks metric range and wheel displacement observations",
            },
        ],
        "metrics": {
            "real2sim": {
                "yaw_axis": fit["yaw_axis"],
                "fitted_parameters": fit["fit"],
                **validation["summary"],
            },
            "policy_training": {
                "samples": training["training_samples"],
                "validation_samples": training["validation_samples"],
                "initial_validation_mse": training["initial_validation_mse"],
                "final_validation_mse": training["final_validation_mse"],
                "model_sha256": model_hash,
            },
            "policy_evaluation": {
                "learned": learned,
                "expert": expert,
                "actuator_stall_learned": fault,
            },
            "mapping": mapping["summary"],
            "controller_ablation": ablation["summary"],
        },
        "acceptance_checks": checks,
        "all_laptop_checks_pass": all(checks.values()),
        "files": {
            name: {
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for name, path in FILES.items()
        },
        "reproduce": [
            "python software/sim/train_high_fidelity_policy.py",
            "python software/sim/evaluate_high_fidelity_policy.py",
            "python software/sim/build_offline_evidence.py",
            "MUJOCO_GL=cgl python software/sim/lab_server.py --port 8780",
        ],
        "claim_boundary": (
            "Simulation evidence supports implementation and controlled virtual evaluation. "
            "It does not claim physical metric navigation or physical deployment of the learned policy."
        ),
        "interpretation_limits": [
            "Yaw validation RMSE covers three turn endpoints, not the complete trajectories.",
            "The historical evaluation compared learned plus safety against baseline alone.",
            "The fresh four-way ablation isolates safety within each controller family; output bounds differ across families.",
            "Contact/stuck inputs include ideal simulator information; physical observation parity remains incomplete.",
            "Historical benchmark results informed development and are not a never-seen blind final test.",
        ],
    }


def main() -> int:
    manifest = build_manifest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(OUTPUT.relative_to(ROOT)),
                "all_laptop_checks_pass": manifest["all_laptop_checks_pass"],
                "acceptance_checks": manifest["acceptance_checks"],
            },
            indent=2,
        )
    )
    return 0 if manifest["all_laptop_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
