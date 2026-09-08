# Synthetic AprilTag Learning

## Objective

Train and deploy a small learned perception model while keeping all learned
outputs disconnected from rover motion.

## Learning Problem

The synthetic renderer places AprilTag 36h11 ID 0 at a known horizontal
location in a 160 x 96 grayscale image. It varies tag size, rotation,
brightness, background gradient, blur, and noise. The known placement becomes
the supervised target:

```text
horizontal_error = (tag_center_x - image_center_x) / image_half_width
```

The CNN maps `[N, 1, 96, 160]` images to `[N, 1]` horizontal-error estimates.
Mean squared error supplies the training loss. Adam updates 497,665 parameters
using gradients produced by backpropagation.

## Results

- Dataset generation: 6,000 training and 1,200 validation images in 4.67 s.
- GPU training: 10 epochs in 17.67 s.
- Validation MAE: 0.0683 after epoch 1 and 0.00984 after epoch 10.
- ONNX export: opset 17 with dynamic batch size.
- TensorRT FP16 engine: 1.01 MiB, 0.092 ms median GPU compute, and 0.109 ms
  median host latency under `trtexec`.
- Independent 512-image comparison: PyTorch MAE 0.010013, TensorRT MAE
  0.010041, and maximum implementation disagreement 0.000700.

## Interpretation

This proves the mechanics of synthetic supervised learning and the complete
PyTorch-to-ONNX-to-TensorRT deployment path. It does not prove real-world
perception. The synthetic renderer does not yet model every camera effect, and
the model cannot report whether a tag is absent.

The deterministic AprilTag detector remains the trustworthy baseline. A real
camera comparison must measure learned-model error against detector geometry
before this experiment can influence any control decision.

## Simulation Boundary

This experiment simulates sensor images, not rover dynamics. A physics
simulator must separately model pose, wheel commands, wheel speed, skid-steer
slip, and timing. It should expose the same observation and command interfaces
as the physical system so deterministic and learned controllers can be tested
without hardware-specific branches.
