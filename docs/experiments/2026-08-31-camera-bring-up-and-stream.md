# Camera Bring-Up and Live Stream

Date: 2026-08-31

## Objective

Verify Camera Module 3 electrically and deliver a fresh, rotated live view to
the existing operator console without weakening motor safety.

## Diagnostic result

The initial `imx708` probe returned I2C error `-5` from both the sensor and its
autofocus controller. The camera module was known to work on the Jetson. Cable
continuity and 3.3 V were present, but the Pi ribbon orientation did not engage
the required signal contacts. Reversing the ribbon into its working orientation
allowed Linux to read module ID `0x0301` and enumerate the IMX708.

The working boot configuration is:

```text
camera_auto_detect=0
dtoverlay=imx708
```

## Stream implementation

- One long-running `rpicam-vid` process captures 360 x 640 MJPEG at 15 fps.
- A Python worker extracts complete JPEG frames and stores only the newest one.
- The existing HTTP server exposes the latest frame with sequence and age
  headers.
- The browser polls without overlapping requests, skips duplicate frames, and
  rotates the newest frame on a canvas.
- A UI rotate control persists display rotation locally.
- The camera worker remains independent of the 350 ms motor watchdog.

## Evidence

- All 32 Pi-side tests passed.
- Controller and `rpicam-vid` services were active.
- HTTP returned a valid 360 x 640 JPEG, rotated to 640 x 360 in the browser.
- Steady capture rate: 15.1 fps.
- Latest frame age: 32 ms in final telemetry.
- Browser observations: 2-72 ms frame age.
- Pi temperature: 45.8 C.
- Pi memory use: 14.0%.
- Wi-Fi signal: -43 dBm.
- Motor state remained stopped with left and right outputs at zero.
- Desktop and 390 x 844 phone layouts rendered without scrolling or clipped
  drive telemetry after the responsive fix.

## Remaining measurement

The current frame-age measurement excludes sensor exposure and display refresh
delay. Measure true glass-to-glass latency with a physical clock or flashing
LED visible to the camera and compare the physical event with its displayed
image.
