(function () {
  const mode = document.body.dataset.mode;
  const api = (action) => `/api/${mode}/${action}`;
  const $ = (id) => document.getElementById(id);
  const stageOrder = ["detection", "gpio", "uart", "spi", "i2c", "wifi", "bluetooth", "complete"];

  function setStateClass(element, value) {
    element.className = `status ${String(value).toLowerCase().replace(/\s+/g, "-")}`;
    element.textContent = value;
  }

  function renderNames(element, names) {
    const entries = names.length ? names : ["None detected"];
    element.replaceChildren(...entries.map((name) => {
      const item = document.createElement("li");
      item.textContent = name;
      return item;
    }));
  }

  function render(state) {
    const result = state.result;
    $("count-today").textContent = state.count_today;
    setStateClass($("tester-status"), state.tester_connected ? "Connected" : "Disconnected");
    setStateClass($("dut-status"), state.dut_detected ? "Detected" : "Not Detected");
    $("stage-label").textContent = state.stage_label;
    $("run-status").className = `pill ${state.running ? "running" : state.stage === "complete" ? "pass" : "neutral"}`;
    $("run-status").textContent = state.running ? "RUNNING" : state.stage === "complete" ? "COMPLETE" : state.stage.toUpperCase();
    document.querySelectorAll("#progress-list li").forEach((item) => {
      const current = stageOrder.indexOf(state.stage);
      const itemIndex = stageOrder.indexOf(item.dataset.stage);
      item.className = itemIndex < current ? "done" : itemIndex === current ? "active" : "";
    });
    $("gpio-tested").textContent = result.gpio.tested;
    $("gpio-pass").textContent = result.gpio.pass;
    $("gpio-fail").textContent = result.gpio.fail;
    $("gpio-summary").textContent = `${result.gpio.pass} / ${result.gpio.tested} PASS`;
    $("gpio-summary").className = `pill ${result.gpio.fail ? "fail" : result.gpio.tested ? "pass" : "neutral"}`;
    $("gpio-table").innerHTML = result.gpio.results.length ? result.gpio.results.map((row) => `<tr><td>GPIO ${row.gpio}</td><td>${row.high_voltage.toFixed(2)}</td><td>${row.low_voltage.toFixed(2)}</td><td><span class="table-status ${row.status.toLowerCase()}">${row.status}</span></td></tr>`).join("") : '<tr><td colspan="4" class="empty">No GPIO readings yet</td></tr>';
    ["uart", "spi", "i2c"].forEach((name) => {
      const element = $(name);
      element.textContent = result[name];
      element.className = `status ${result[name].toLowerCase().replace(/\s+/g, "-")}`;
    });
    $("wifi-count").textContent = result.wifi.count;
    $("wifi-result").textContent = result.wifi.result;
    $("wifi-result").className = `status ${result.wifi.result.toLowerCase().replace(/\s+/g, "-")}`;
    $("bluetooth-count").textContent = result.bluetooth.count;
    $("bluetooth-result").textContent = result.bluetooth.result;
    $("bluetooth-result").className = `status ${result.bluetooth.result.toLowerCase().replace(/\s+/g, "-")}`;
    renderNames($("wifi-names"), result.wifi.names);
    renderNames($("bluetooth-names"), result.bluetooth.names);
    $("overall-result").textContent = result.overall;
    $("overall-result").className = `result-badge ${result.overall.toLowerCase().replace(/\s+/g, "-")}`;
  }

  async function requestAction(action) {
    try {
      const response = await fetch(api(action), { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Request failed");
      $("notification").textContent = "";
      render(data);
    } catch (error) {
      $("notification").textContent = error.message;
      $("notification").className = "notification error";
    }
  }

  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => requestAction(button.dataset.action));
  });

  const configForm = $("gpio-config-form");
  configForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const notice = $("gpio-config-notice");
    const rawPins = $("gpio-config-input").value.split(",").map((value) => value.trim());
    const pins = rawPins.map(Number);
    if (rawPins.some((value) => value === "") || pins.some((pin) => !Number.isInteger(pin))) {
      notice.textContent = "Enter GPIO numbers separated by commas, for example: 4, 5, 12";
      notice.className = "notification error";
      return;
    }
    try {
      const response = await fetch(api("gpio-config"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gpios: pins })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not save GPIO configuration");
      $("gpio-config-input").value = data.gpios.join(", ");
      notice.textContent = `Saved ${data.gpios.length} GPIO pins for this mode.`;
      notice.className = "notification";
    } catch (error) {
      notice.textContent = error.message;
      notice.className = "notification error";
    }
  });

  async function refresh() {
    try {
      const response = await fetch(api("status"));
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load test status");
      render(data);
    } catch (error) {
      $("notification").textContent = error.message;
      $("notification").className = "notification error";
    }
  }
  async function loadGpioConfig() {
    try {
      const response = await fetch(api("gpio-config"));
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load GPIO configuration");
      $("gpio-config-input").value = data.gpios.join(", ");
    } catch (error) {
      $("gpio-config-notice").textContent = error.message;
      $("gpio-config-notice").className = "notification error";
    }
  }
  refresh();
  loadGpioConfig();
  window.setInterval(refresh, 2000);
})();
