# Jetson TensorRT Inference

## Objective

Prove the complete pretrained-model deployment path on the Orin GPU without
connecting any model output to rover motion.

## Architecture

```text
pretrained weights and graph -> ONNX -> TensorRT build -> Orin engine
JPEG -> RGB preprocessing -> NCHW tensor -> GPU inference -> class scores
     -> softmax -> top-five labels
```

## Model Contract

The official ONNX ResNet-50 v2 model contains 174 graph operations and 260
weight tensors. Its image input is `[N, 3, 224, 224]`, and its output is
`[N, 1000]` ImageNet class scores. The test used batch size `N = 1` and FP16
internal TensorRT execution.

Preprocessing resized the short image edge to 256 pixels, centre-cropped a
224 x 224 RGB image, converted integer pixels to floats in `[0, 1]`, applied
ImageNet channel normalization, and transposed HWC pixels into NCHW tensor
layout.

## Results

- TensorRT parsed the complete graph and built the engine in 111.9 seconds.
- The serialized engine is 49.4 MiB.
- `trtexec` measured 2.70 ms median GPU compute, 2.76 ms median host latency,
  and approximately 361 inferences per second with synthetic input.
- The Python application measured 42.7 ms image preprocessing, 92.5 ms first
  inference, 3.95 ms median warm inference, and 6.30 ms warm p95 inference.
- NVIDIA's tabby-cat sample produced `tabby` at 69.1%, `tiger cat` at 24.6%,
  and `Egyptian cat` at 5.0%.

## Interpretation

`trtexec` measures the optimized engine closely, while the Python application
includes Python, PyCUDA, copies, synchronization, and output handling. The
difference is part of the deployed system and must not be hidden.

The correct label proves that graph compilation and execution alone are not
enough: RGB order, normalization, layout, and class-index mapping also match
the model's training contract.

This model is a classifier and does not locate obstacles or command motors. It
is an inference-learning milestone, not a rover autonomy component.

## Discovered Configuration State

- TensorRT 10.3 and PyCUDA load correctly.
- OpenCV and ONNX Runtime currently expose CPU execution only.
- PyTorch 2.5 cannot import because `libcusparseLt.so.0` is missing.
- The old Pillow package required compatibility with the pre-`Resampling` API.
