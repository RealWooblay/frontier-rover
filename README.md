# Frontier Rover

A hands-on apprenticeship in building a reliable autonomous 4WD rover.

The project progresses one measured subsystem at a time. The current milestone
is M0: establish a supported 64-bit Raspberry Pi platform, reliable headless
access, and an evidence-based development workflow.

## Current Platform

- Raspberry Pi 4 Model B Rev 1.5, 4 GB
- Ubuntu Server 26.04 LTS, ARM64
- Hostname: `frontier-pi`
- Remote user: `rover`
- SSH: public-key authentication from the development Mac

Connect from the development Mac:

```sh
ssh rover@frontier-pi.local
```

Shut down before removing Pi power:

```sh
sudo shutdown -h now
```

Wait at least 20 seconds after SSH disconnects before unplugging power.

## Working Method

Read [AGENTS.md](AGENTS.md) before contributing. Experiments belong in
`docs/experiments/`; architecture decisions belong in `docs/decisions/`.
