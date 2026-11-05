(function () {
  const dataElement = document.getElementById("chart-data");
  if (!dataElement || !window.Chart) return;

  const data = JSON.parse(dataElement.textContent);
  const history = data.history;
  const filter = document.getElementById("topic-filter");
  const CORRECT_LABEL = "✓ Acertos";
  const WRONG_LABEL = "✗ Erros";
  const TOPIC_ROW_HEIGHT = 36;
  const TOPIC_CHROME_HEIGHT = 72;
  const HISTORY_TICK_STEP_DAYS = 7;

  Object.keys(history.byTopic).forEach((topic) => {
    filter.add(new Option(topic, topic));
  });

  function token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function formatDay(iso) {
    const [, month, day] = iso.split("-");
    return `${day}/${month}`;
  }

  function dataset(label, values, color, surface, roundedEnd) {
    return {
      label,
      data: values,
      backgroundColor: color,
      hoverBackgroundColor: color,
      borderColor: surface,
      borderWidth: 1,
      borderSkipped: false,
      borderRadius: roundedEnd,
      maxBarThickness: 20,
      stack: "answers",
    };
  }

  function baseOptions(colors) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          align: "start",
          labels: { color: colors.secondary, boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 2 },
        },
        tooltip: { displayColors: true, boxPadding: 4 },
      },
    };
  }

  function axis(colors, overrides) {
    return Object.assign(
      {
        stacked: true,
        grid: { color: colors.grid, drawTicks: false },
        border: { color: colors.axis },
        ticks: { color: colors.muted, precision: 0, padding: 6 },
      },
      overrides
    );
  }

  let charts = [];

  function currentHistory() {
    return filter.value ? history.byTopic[filter.value] : history.overall;
  }

  function renderHistoryTable(series) {
    const body = document.getElementById("history-table");
    body.replaceChildren();
    history.days.forEach((day, index) => {
      if (!series.correct[index] && !series.wrong[index]) return;
      const row = body.insertRow(0);
      row.insertCell().textContent = formatDay(day);
      [series.correct[index], series.wrong[index]].forEach((value) => {
        const cell = row.insertCell();
        cell.textContent = value;
        cell.className = "num";
      });
    });
  }

  function render() {
    charts.forEach((chart) => chart.destroy());
    const colors = {
      correct: token("--chart-correct"),
      wrong: token("--chart-wrong"),
      surface: token("--surface"),
      secondary: token("--text-secondary"),
      muted: token("--chart-muted"),
      grid: token("--chart-grid"),
      axis: token("--chart-axis"),
    };
    Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';

    const topicBox = document.getElementById("topic-chart-box");
    topicBox.style.height = `${data.byTopic.length * TOPIC_ROW_HEIGHT + TOPIC_CHROME_HEIGHT}px`;
    const topicOptions = baseOptions(colors);
    topicOptions.indexAxis = "y";
    topicOptions.plugins.tooltip.callbacks = {
      afterBody: (items) => `Aproveitamento: ${data.byTopic[items[0].dataIndex].accuracy}%`,
    };
    const topicChart = new Chart(document.getElementById("topic-chart"), {
      type: "bar",
      data: {
        labels: data.byTopic.map((row) => row.topic),
        datasets: [
          dataset(CORRECT_LABEL, data.byTopic.map((row) => row.correct), colors.correct, colors.surface, 0),
          dataset(WRONG_LABEL, data.byTopic.map((row) => row.wrong), colors.wrong, colors.surface, { topRight: 4, bottomRight: 4 }),
        ],
      },
      options: Object.assign(topicOptions, {
        scales: {
          x: axis(colors, { beginAtZero: true }),
          y: axis(colors, { grid: { display: false }, ticks: { color: colors.secondary, padding: 6 } }),
        },
      }),
    });

    const series = currentHistory();
    const historyChart = new Chart(document.getElementById("history-chart"), {
      type: "bar",
      data: {
        labels: history.days.map(formatDay),
        datasets: [
          dataset(CORRECT_LABEL, series.correct, colors.correct, colors.surface, 0),
          dataset(WRONG_LABEL, series.wrong, colors.wrong, colors.surface, { topLeft: 4, topRight: 4 }),
        ],
      },
      options: Object.assign(baseOptions(colors), {
        scales: {
          x: axis(colors, {
            grid: { display: false },
            ticks: {
              color: colors.muted,
              autoSkip: false,
              maxRotation: 0,
              padding: 6,
              // Conta a partir de hoje, para que o último rótulo seja sempre o dia atual.
              callback: (value, index) =>
                (history.days.length - 1 - index) % HISTORY_TICK_STEP_DAYS === 0
                  ? formatDay(history.days[index])
                  : "",
            },
          }),
          y: axis(colors, { beginAtZero: true }),
        },
      }),
    });

    charts = [topicChart, historyChart];
    renderHistoryTable(series);
  }

  filter.addEventListener("change", render);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
  render();
})();
