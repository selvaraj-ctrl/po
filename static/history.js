(function () {
  const mode = document.body.dataset.mode;
  const chart = document.getElementById("hourly-chart");
  const total = document.getElementById("history-total");
  const date = document.getElementById("history-date");
  const errorMessage = document.getElementById("history-error");

  function formatHour(hour) {
    return `${String(hour).padStart(2, "0")}:00`;
  }

  function render(data) {
    total.textContent = data.count_today;
    date.textContent = new Date(`${data.date}T00:00:00`).toLocaleDateString(undefined, {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric"
    });
    const maxCount = Math.max(1, ...data.hourly.map((slot) => slot.count));
    chart.replaceChildren(...data.hourly.map((slot) => {
      const column = document.createElement("div");
      column.className = "hour-column";
      const count = document.createElement("span");
      count.className = "hour-count";
      count.textContent = slot.count ? String(slot.count) : "";
      const track = document.createElement("div");
      track.className = "hour-track";
      const bar = document.createElement("div");
      bar.className = "hour-bar";
      bar.style.height = `${slot.count ? Math.max(5, (slot.count / maxCount) * 100) : 0}%`;
      track.append(bar);
      const label = document.createElement("span");
      label.className = "hour-label";
      label.textContent = formatHour(slot.hour);
      column.append(count, track, label);
      return column;
    }));
  }

  async function refresh() {
    try {
      const response = await fetch(`/api/${mode}/history`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not load test history");
      errorMessage.textContent = "";
      render(data);
    } catch (error) {
      errorMessage.textContent = error.message;
      errorMessage.className = "notification error";
    }
  }

  refresh();
  window.setInterval(refresh, 10000);
})();
