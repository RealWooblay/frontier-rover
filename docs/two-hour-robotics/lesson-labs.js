(function () {
  'use strict';

  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

  // These pure calculations illustrate the text. They never address hardware.
  function control(headingDeg, ageMs, feedback = true) {
    if (![headingDeg, ageMs].every(Number.isFinite) || ageMs < 0) {
      throw new Error('Heading and measurement age must be valid numbers.');
    }
    const error = -headingDeg;
    const raw = feedback ? error * 0.02 : 0;
    const applied = clamp(raw, -0.2, 0.2);
    const stale = ageMs > 500;
    return {
      error, raw, applied, stale,
      saturated: feedback && Math.abs(raw) > 0.2,
      left: stale ? 0 : 0.4 - applied,
      right: stale ? 0 : 0.4 + applied,
    };
  }

  function vision(center) {
    if (!Number.isFinite(center) || center < 40 || center > 600) {
      throw new Error('The example box must remain inside the image.');
    }
    const offset = center - 320;
    return { center, offset, error: offset / 320, side: offset === 0 ? 'Centred' : offset > 0 ? 'Right of image centre' : 'Left of image centre' };
  }

  function weightStep(weight, rate = 0.1) {
    if (![weight, rate].every(Number.isFinite) || rate < 0) throw new Error('Invalid training values.');
    const x = 0.5;
    const target = 0.3;
    const prediction = weight * x;
    const loss = (prediction - target) ** 2;
    const gradient = 2 * (prediction - target) * x;
    const nextWeight = weight - rate * gradient;
    const nextPrediction = nextWeight * x;
    return { x, target, weight, rate, prediction, loss, gradient, nextWeight, nextPrediction, nextLoss: (nextPrediction - target) ** 2 };
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { control, vision, weightStep };
    return;
  }

  const signed = (value, digits = 0) => (value > 0 ? '+' : '') + value.toFixed(digits);

  function mountControl(root) {
    root.innerHTML = `<section class="lesson-lab" aria-label="Motor-request calculation">
      <p class="lab-caption">Teaching calculation. No wheel motion is simulated.</p>
      <div class="lab-controls">
        <label for="lc-heading">Measured heading <output id="lc-heading-value"></output>
          <input id="lc-heading" type="range" min="-30" max="30" step="1" value="5"></label>
        <label for="lc-age">Measurement age <output id="lc-age-value"></output>
          <input id="lc-age" type="range" min="0" max="1000" step="10" value="100"></label>
      </div>
      <label class="lab-check"><input id="lc-feedback" type="checkbox" checked> Use feedback to adjust the fixed 40/40 request</label>
      <div class="lab-motors">
        <label>Left request <output id="lc-left"></output><meter id="lc-left-meter" min="0" max="1" value="0.5"></meter></label>
        <label>Right request <output id="lc-right"></output><meter id="lc-right-meter" min="0" max="1" value="0.3"></meter></label>
      </div>
      <p class="lab-result" id="lc-result" aria-live="polite"></p>
      <p class="lab-detail" id="lc-math"></p>
      <button type="button" id="lc-reset">Reset example</button>
    </section>`;
    const heading = root.querySelector('#lc-heading');
    const age = root.querySelector('#lc-age');
    const feedback = root.querySelector('#lc-feedback');
    function draw() {
      const h = Number(heading.value);
      const ms = Number(age.value);
      const result = control(h, ms, feedback.checked);
      root.querySelector('#lc-heading-value').textContent = `${signed(h)} degrees (${h > 0 ? 'left' : h < 0 ? 'right' : 'on target'})`;
      root.querySelector('#lc-age-value').textContent = `${ms} ms`;
      for (const side of ['left', 'right']) {
        root.querySelector(`#lc-${side}`).textContent = `${(100 * result[side]).toFixed(0)}%`;
        root.querySelector(`#lc-${side}-meter`).value = result[side];
      }
      root.querySelector('#lc-result').textContent = result.stale
        ? 'Timeout: the measurement is older than 500 ms. Request zero effort on both sides.'
        : !feedback.checked ? 'Feedback off: the measured direction does not change the fixed request.'
          : result.saturated ? 'Saturation: the correction is capped at 20 percentage points.'
            : h === 0 ? 'No heading error: no correction is requested.'
              : `Correction requests a ${h > 0 ? 'right' : 'left'} turn. Actual movement is not calculated here.`;
      root.querySelector('#lc-math').textContent = `Desired 0 - measured ${signed(h)} = error ${signed(result.error)} degrees. Raw correction ${signed(result.raw * 100)} percentage points; capped correction ${signed(result.applied * 100)}.${result.stale ? ' Timeout overrides these calculations.' : ''}`;
    }
    for (const input of [heading, age, feedback]) input.addEventListener('input', draw);
    root.querySelector('#lc-reset').addEventListener('click', () => {
      heading.value = '5'; age.value = '100'; feedback.checked = true; draw();
    });
    draw();
  }

  function mountVision(root) {
    root.innerHTML = `<section class="lesson-lab" aria-label="Image position calculation">
      <p class="lab-caption">Illustrated image coordinates. Not a live camera or detector.</p>
      <label for="lv-center">Box centre <output id="lv-center-value"></output>
        <input id="lv-center" type="range" min="40" max="600" step="1" value="480"></label>
      <svg class="lab-image" viewBox="0 0 640 230" role="img" aria-labelledby="lv-title lv-desc">
        <title id="lv-title">A target box relative to a 640-pixel image's centre</title>
        <desc id="lv-desc">The target starts right of centre. Moving its slider changes the pixel offset and normalised error below.</desc>
        <rect x="0" y="0" width="640" height="230" fill="#eef3f4"></rect>
        <line x1="320" x2="320" y1="0" y2="176" stroke="#075e72" stroke-width="3" stroke-dasharray="8 5"></line>
        <rect id="lv-box" x="440" y="55" width="80" height="90" fill="#f3c795" stroke="#85441c" stroke-width="3"></rect>
        <text x="12" y="214" font-size="24" fill="#20242a">0 px</text>
        <text x="320" y="214" text-anchor="middle" font-size="24" fill="#20242a">Centre: 320 px</text>
        <text x="628" y="214" text-anchor="end" font-size="24" fill="#20242a">640 px</text>
      </svg>
      <p id="lv-result" class="lab-result" aria-live="polite"></p>
      <p id="lv-math" class="lab-detail"></p>
    </section>`;
    const input = root.querySelector('#lv-center');
    function draw() {
      const result = vision(Number(input.value));
      root.querySelector('#lv-center-value').textContent = `${result.center} px`;
      root.querySelector('#lv-box').setAttribute('x', String(result.center - 40));
      root.querySelector('#lv-result').textContent = `${result.side}. Normalised error: ${signed(result.error, 3)}.`;
      root.querySelector('#lv-math').textContent = `(${result.center} - 320) / 320 = ${signed(result.error, 3)}. Pixel offset: ${signed(result.offset)}. No distance or angle is measured here.`;
    }
    input.addEventListener('input', draw);
    draw();
  }

  function mountWeight(root) {
    root.innerHTML = `<section class="lesson-lab" aria-label="One-weight training calculation">
      <p class="lab-caption">One teaching weight. Input = 0.5; target = 0.3; learning rate = 0.1.</p>
      <label for="lw-weight">Weight <output id="lw-weight-value"></output>
        <input id="lw-weight" type="range" min="0" max="1" step="any" value="0.2"></label>
      <dl class="lab-numbers">
        <div><dt>Prediction = weight times 0.5</dt><dd id="lw-prediction"></dd></div>
        <div><dt>Loss = (prediction - 0.3) squared</dt><dd id="lw-loss"></dd></div>
      </dl>
      <div class="lab-actions"><button type="button" id="lw-step">Apply one training step</button><button type="button" id="lw-reset">Reset</button></div>
      <p class="lab-result" id="lw-result" aria-live="polite"></p>
      <p class="lab-detail" id="lw-math"></p>
    </section>`;
    let weight = 0.2;
    let updates = 0;
    const slider = root.querySelector('#lw-weight');
    function draw(last = null, manual = false) {
      const result = weightStep(weight);
      slider.value = String(weight);
      root.querySelector('#lw-weight-value').textContent = weight.toFixed(6);
      root.querySelector('#lw-prediction').textContent = result.prediction.toFixed(6);
      root.querySelector('#lw-loss').textContent = result.loss.toFixed(6);
      root.querySelector('#lw-result').textContent = last
        ? `Update ${updates}: weight ${last.weight.toFixed(6)} becomes ${last.nextWeight.toFixed(6)}. Loss ${last.loss.toFixed(6)} becomes ${last.nextLoss.toFixed(6)}.`
        : manual ? 'You manually changed the multiplier. No optimiser step was applied.' : 'Starting example: prediction 0.1 is below the target 0.3.';
      root.querySelector('#lw-math').textContent = last
        ? `Gradient = 2 x (${last.prediction.toFixed(6)} - 0.3) x 0.5 = ${last.gradient.toFixed(6)}. New weight = ${last.weight.toFixed(6)} - 0.1 x (${last.gradient.toFixed(6)}).`
        : `Current prediction = ${weight.toFixed(6)} x 0.5 = ${result.prediction.toFixed(6)}. All changes are temporary teaching calculations.`;
    }
    slider.addEventListener('input', () => { weight = Number(slider.value); updates = 0; draw(null, true); });
    root.querySelector('#lw-step').addEventListener('click', () => {
      const last = weightStep(weight); weight = last.nextWeight; updates += 1; draw(last);
    });
    root.querySelector('#lw-reset').addEventListener('click', () => { weight = 0.2; updates = 0; draw(); });
    draw();
  }

  const mounts = { control: mountControl, vision: mountVision, weight: mountWeight };
  document.querySelectorAll('[data-lab]').forEach(root => {
    const mount = mounts[root.dataset.lab];
    if (mount) mount(root);
  });
}());
