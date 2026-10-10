# Backup and offline learning

The September 30 structured lessons are also versioned under
`docs/two-hour-robotics/`. Open `study.html` locally; GitHub's Markdown edition
is `study.md`. The existing travel pack keeps its original top-level
`two-hour-robotics/` copy, so saved offline links continue to work.

The lessons' command examples and optional build/check scripts refer to the
author's Mac runtime. Reading the generated HTML needs only a browser. Running
the Python experiments on another machine requires the project's simulation
dependencies and corresponding local paths.

The travel pack is a separate folder, not a shortcut into the development repo:

`/Users/jackcoleman/Developer/rover-learning`

Start with `Frontier_Rover_Field_Guide.docx` and `Open Workbook.command`.
The document and workbook need no internet, Pi, Jetson, Python, or login.
The workbook includes local diagrams, real saved model weights, measured turn
results and two fixed-seed MuJoCo replays. Its classroom exercises are labelled
separately from exported project results. Replaying a run does not rerun physics.

`Run Simulation.command` starts new MuJoCo experiments on this Mac. It opens
port 8781, or an available loopback port if 8781 is occupied. It uses the copied
`runtime/.venv`, not the original checkout. Its Python executable still depends
on this Mac's existing bundled runtime under
`~/.cache/codex-runtimes/codex-primary-runtime/dependencies/python`.
Do not remove that runtime if you want this exact offline simulator to continue
working. Moving to another computer requires installing Python and
`requirements-sim.txt`; the Word guide and workbook remain portable.

The offline server subclasses the real lab server and rejects physical-device
requests. No button in this launch mode can drive a rover. It runs only on
`127.0.0.1`. The original lab server still supports hardware operation separately.

## What is preserved

- GitHub: source, deployment scripts without embedded secrets, wiring records,
  study documents, labels, portable model files, numerical experiment logs,
  simulation evidence and the Word guide.
- Separate local pack: an independent source/evidence copy, a Git bundle,
  runnable installed simulator environment and local-only material in `private`.
- Local-only material: indoor camera photographs, raw collection manifests and
  historical DLP provisioning files. The latter may contain old credentials.
  Do not publish the private folder or share the entire pack indiscriminately.
- Private recovery archive: the customized August 27 Pi installation image is
  retained compressed in `private/recovery-image/`. Its bytes differ from the
  downloaded Ubuntu distribution, so preserve this archive rather than assuming
  it is disposable. It is not a backup of the final Pi or Jetson SD card.
- Excluded: redundant uncompressed installation media, the unmodified Ubuntu
  download, generated caches and `.DS_Store`.

`backup-manifest.json` records the exact commit, independently observed remote
commit, copied files and SHA-256 hashes. A successful push alone does not prove
that ignored files were backed up; the private inventory is checked separately.
The packaging script refuses uncommitted tracked changes and verifies copied
bytes against the working tree. `frontier-rover.bundle` can restore local Git
history without the internet:

```sh
git clone /path/to/rover-learning/frontier-rover.bundle frontier-rover-restored
```

Keep the **entire** `rover-learning` folder. Only remove the original
`frontier-rover` checkout after the manifest says remote verification succeeded
and the copied workbook and simulation have been tested. No deletion is part of
the backup procedure. This copy is on the same laptop, so it does not protect
private-only data against laptop loss. Copy that folder to your own external
storage when available; GitHub protects only its public subset.

## Rebuild the learning artifacts

```sh
python3 -m pip install python-docx markdown-it-py Pillow
python3 software/learning/build_field_guide.py --output docs/Frontier_Rover_Field_Guide.docx
MUJOCO_GL=cgl .venv/bin/python software/learning/export_offline_evidence.py
```

The evidence exporter uses two predetermined seeds and retains failures.
It is not a substitute for running the full benchmark. Review and commit
intentional changes before rebuilding the offline pack.
