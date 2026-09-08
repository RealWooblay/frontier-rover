# Synthetic AprilTag Regressor

`tag-regressor.pt` is the PyTorch checkpoint. `tag-regressor.onnx` is the
portable inference graph exported at ONNX opset 17. TensorRT engine files are
not stored because they are generated for a specific GPU and TensorRT version.

## Contract

```text
input:  float32 [N, 1, 96, 160], grayscale normalized to [-1, 1]
output: float32 [N, 1], normalized horizontal error in [-1, 1]
```

The model has 497,665 trainable parameters. It was trained for ten epochs on
6,000 procedurally generated AprilTag 36h11 ID 0 images and evaluated on 1,200
separately seeded synthetic images.

Final synthetic validation mean absolute error was 0.00984. A second 512-image
comparison measured 0.01001 PyTorch MAE, 0.01004 TensorRT FP16 MAE, and 0.00070
maximum implementation disagreement.

## Reproduction

Run `software/jetson/train_synthetic_tag_regressor.py` through
`software/jetson/run_with_ai_env.sh`, then compile the exported ONNX graph with
TensorRT for the target Jetson.

## Limitation

This model assumes a complete visible tag and was validated only on synthetic
images. It has no target-presence output, no confidence estimate, and no
proven real-camera accuracy. It must not command motors.

## Checksums

```text
f7c628cf25f2369d944de53ab08bbc985a6fa804899dd2f31ab24c5b166a8062  tag-regressor.pt
d0b5770e8ea558dedb9f1149159cf33358245a50a71ea87e5977f61e1fc9dca0  tag-regressor.onnx
```
