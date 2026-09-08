#include <cuda_runtime.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {

void check_cuda(cudaError_t result, const char* operation) {
    if (result != cudaSuccess) {
        throw std::runtime_error(
            std::string(operation) + ": " + cudaGetErrorString(result));
    }
}

__host__ __device__ float transform_pixel(float value) {
    return fminf(255.0F, fmaxf(0.0F, value * 1.1F + 12.0F));
}

__global__ void transform_pixels(
    const float* input,
    float* output,
    std::size_t count) {
    const std::size_t index = blockIdx.x * blockDim.x + threadIdx.x;
    if (index < count) {
        output[index] = transform_pixel(input[index]);
    }
}

double elapsed_ms(
    std::chrono::steady_clock::time_point start,
    std::chrono::steady_clock::time_point end) {
    return std::chrono::duration<double, std::milli>(end - start).count();
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const std::size_t pixel_count = argc > 1
            ? std::strtoull(argv[1], nullptr, 10)
            : 1920ULL * 1080ULL * 8ULL;
        const std::size_t byte_count = pixel_count * sizeof(float);

        cudaDeviceProp properties{};
        check_cuda(cudaGetDeviceProperties(&properties, 0), "read GPU properties");
        std::cout << "gpu=" << properties.name << '\n';
        std::cout << "pixels=" << pixel_count << '\n';

        std::vector<float> input(pixel_count);
        std::vector<float> cpu_output(pixel_count);
        std::vector<float> gpu_output(pixel_count);
        for (std::size_t index = 0; index < pixel_count; ++index) {
            input[index] = static_cast<float>(index % 256);
        }

        const auto cpu_start = std::chrono::steady_clock::now();
        for (std::size_t index = 0; index < pixel_count; ++index) {
            cpu_output[index] = transform_pixel(input[index]);
        }
        const auto cpu_end = std::chrono::steady_clock::now();

        float* device_input = nullptr;
        float* device_output = nullptr;
        check_cuda(cudaMalloc(&device_input, byte_count), "allocate GPU input");
        check_cuda(cudaMalloc(&device_output, byte_count), "allocate GPU output");

        cudaEvent_t kernel_start{};
        cudaEvent_t kernel_end{};
        check_cuda(cudaEventCreate(&kernel_start), "create start event");
        check_cuda(cudaEventCreate(&kernel_end), "create end event");

        constexpr int threads_per_block = 256;
        const int block_count = static_cast<int>(
            (pixel_count + threads_per_block - 1) / threads_per_block);

        const auto gpu_pipeline_start = std::chrono::steady_clock::now();
        check_cuda(
            cudaMemcpy(device_input, input.data(), byte_count, cudaMemcpyHostToDevice),
            "copy input to GPU");
        check_cuda(cudaEventRecord(kernel_start), "record kernel start");
        transform_pixels<<<block_count, threads_per_block>>>(
            device_input, device_output, pixel_count);
        check_cuda(cudaGetLastError(), "launch pixel kernel");
        check_cuda(cudaEventRecord(kernel_end), "record kernel end");
        check_cuda(
            cudaMemcpy(gpu_output.data(), device_output, byte_count, cudaMemcpyDeviceToHost),
            "copy output to CPU");
        const auto gpu_pipeline_end = std::chrono::steady_clock::now();

        float kernel_ms = 0.0F;
        check_cuda(cudaEventElapsedTime(&kernel_ms, kernel_start, kernel_end),
                   "measure kernel time");

        float maximum_error = 0.0F;
        for (std::size_t index = 0; index < pixel_count; ++index) {
            maximum_error = std::max(
                maximum_error,
                std::abs(cpu_output[index] - gpu_output[index]));
        }

        const double cpu_ms = elapsed_ms(cpu_start, cpu_end);
        const double gpu_pipeline_ms = elapsed_ms(gpu_pipeline_start, gpu_pipeline_end);
        std::cout << "cpu_ms=" << cpu_ms << '\n';
        std::cout << "gpu_kernel_ms=" << kernel_ms << '\n';
        std::cout << "gpu_pipeline_ms=" << gpu_pipeline_ms << '\n';
        std::cout << "kernel_speedup=" << cpu_ms / kernel_ms << '\n';
        std::cout << "pipeline_speedup=" << cpu_ms / gpu_pipeline_ms << '\n';
        std::cout << "maximum_error=" << maximum_error << '\n';

        check_cuda(cudaEventDestroy(kernel_start), "destroy start event");
        check_cuda(cudaEventDestroy(kernel_end), "destroy end event");
        check_cuda(cudaFree(device_input), "free GPU input");
        check_cuda(cudaFree(device_output), "free GPU output");
        return maximum_error == 0.0F ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << "error=" << error.what() << '\n';
        return 1;
    }
}
