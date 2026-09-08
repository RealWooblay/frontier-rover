#!/usr/bin/env python3
"""Export actual project functions and two seeded MuJoCo runs for offline study."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for name in ("sim", "shared", "jetson", "pi", "learning"):
    sys.path.insert(0, str(ROOT / "software" / name))

import numpy as np
from high_fidelity_env import generate_scenarios, randomized_dynamics, randomized_fidelity, run_policy_episode
from mlp_policy import TinyMLP, LearnedNavigationPolicy, INPUT_NAMES
from rover_workshop import gradient, vision


def main() -> None:
    out = ROOT / "artifacts/learning"
    out.mkdir(parents=True, exist_ok=True)
    model_file = ROOT / "artifacts/models/high-fidelity-navigation-policy.npz"
    model = TinyMLP.load(model_file)
    scenarios = generate_scenarios(40, 9201)
    episodes = []
    for index in (0, 1):
        run = run_policy_episode(
            scenarios[index], LearnedNavigationPolicy(model),
            dynamics=randomized_dynamics(920100 + index),
            fidelity=randomized_fidelity(970100 + index), seed=9201 + index,
            capture_frames=True, frame_period_s=0.6,
        )
        # Preserve the recorded data while explicitly correcting its broad provenance label.
        run["provenance"]["observation_limit"] = (
            "Speed/gyro/range are modeled imperfect measurements. Contact and stuck "
            "flags still derive from simulator state; physical equivalents are absent."
        )
        episodes.append(run)
        print(json.dumps(run["result"]), flush=True)
        for label, frame in (("start", run["frames"][0]), ("end", run["frames"][-1])):
            for camera in ("chase", "onboard"):
                (out / f"arena-{index}-{label}-{camera}.jpg").write_bytes(
                    base64.b64decode(frame[f"{camera}_jpeg_base64"])
                )
    boxes = []
    for box, age, lost in (([440, 180, 520, 260], 100, False),
                            ([280, 180, 360, 260], 100, False),
                            ([270, 250, 370, 350], 100, False),
                            ([280, 180, 360, 260], 1000, False),
                            ([280, 180, 360, 260], 100, True)):
        boxes.append(vision(argparse.Namespace(box=box, frame_age_ms=age,
                     lost=lost, left_scale=0.8, right_scale=1.0)))
    validation = json.loads((ROOT / "artifacts/sim/2026-09-06-closed-loop-turn-validation.json").read_text())
    ablation = json.loads((ROOT / "artifacts/sim/2026-09-08-controller-ablation.json").read_text())
    payload = {
        "description": "Offline teaching export. No hardware contacted. Replay is not a new simulation run.",
        "model_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
        "model": {name: values.tolist() for name, values in model.parameters.items()},
        "input_names": INPUT_NAMES,
        "model_test": {"input": [0.6, 0.25, 0.8, 0.9, 0.5, 0, 0, 0, 0],
                       "output": model.predict(np.array([[0.6, 0.25, 0.8, 0.9, 0.5, 0, 0, 0, 0]])).tolist()[0]},
        "gradient": gradient(argparse.Namespace()), "box_cases": boxes,
        "validation": validation, "ablation": ablation["summary"], "episodes": episodes,
    }
    (out / "offline-evidence.json").write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    (out / "evidence.js").write_text("window.ROVER_EVIDENCE = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    print(f"Exported to {out}")


if __name__ == "__main__":
    main()
