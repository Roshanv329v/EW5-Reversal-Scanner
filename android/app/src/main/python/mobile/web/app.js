/* Elliott Wave Scanner - phone page. All numbers come from the Python API (mobile/api.py). */
"use strict";

const TOKEN = new URLSearchParams(location.search).get("t") || "";
const NATIVE = window.Android || null;              // bridge from the Android app (absent on a desktop)
const PLOT_CONFIG = { displaylogo: false, scrollZoom: false, responsive: true };
const PAGE = 150;                                   // table rows drawn at a time
const TABS = [["ew5", "📊 EW5"], ["ew3", "🚀 EW3"], ["data", "🗄️ Data"], ["run", "🔎 Run / Backtest"], ["guide", "📖 User Guide"]];
const narrow = () => window.innerWidth < 760;

// ---------------------------------------------------------------- small helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style") el.style.cssText = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = (id) => document.getElementById(id);
const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>");

async function api(path, body) {
  const opts = { headers: { "X-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(text, ms = 3200) {
  const t = h("div", { class: "toast" }, text);
  document.body.append(t);
  setTimeout(() => t.remove(), ms);
}
function note(kind, text) { return h("div", { class: `note ${kind}`, html: md(text) }); }
function spinner(text = "Loading…") { return h("div", { class: "spin" }, text); }

const SHORT_DEGREE = { intermediate: "int", major: "maj", minor: "min" };

/* Phone portrait: same figure, laid out for ~350 px (legend under the chart, short degree labels). */
function narrowLayout(fig, breakdown) {
  const L = JSON.parse(JSON.stringify(fig.layout));
  if (L.title) L.title = Object.assign({}, L.title, { font: Object.assign({}, (L.title || {}).font, { size: 13 }) });
  if (!breakdown) return L;
  L.margin = Object.assign({}, L.margin, { l: 44, r: 12, t: 44, b: L.showlegend === false ? 40 : 96 });
  L.legend = { orientation: "h", x: 0, xanchor: "left", y: -0.32, yanchor: "top", font: { size: 10, color: "#c3c2b7" } };
  (L.annotations || []).forEach((a) => (a.font = Object.assign({}, a.font, { size: 10 })));
  const cats = new Set();
  fig.data.forEach((t) => Array.isArray(t.x) && t.x.forEach((x) => typeof x === "string" && x.includes("<br>") && cats.add(x)));
  if (cats.size) {
    const vals = [...cats];
    L.xaxis = Object.assign({}, L.xaxis, { tickfont: { size: 9 }, tickvals: vals,
      ticktext: vals.map((v) => v.replace(/(intermediate|major|minor)/, (m) => SHORT_DEGREE[m])) });
  }
  return L;
}

/* Legend under a phone chart: one chip per named series, same colour; a tap hides / shows it. */
function htmlLegend(div, fig) {
  const colour = (t) => (t.line && t.line.color) || (t.marker && typeof t.marker.color === "string" && t.marker.color)
    || (t.increasing && t.increasing.line && t.increasing.line.color) || "#c3c2b7";
  const wrap = h("div", { class: "legend" });
  fig.data.forEach((t, i) => {
    if (!t.name || t.showlegend === false) return;
    const item = h("button", { class: "lg", onclick: () => {
      const off = item.classList.toggle("off");
      Plotly.restyle(div, { visible: off ? "legendonly" : true }, [i]);
    } }, h("i", { style: `background:${colour(t)}` }), t.name);
    wrap.append(item);
  });
  return wrap;
}

function plot(div, fig, onClick) {
  const breakdown = !!onClick;
  const layout = Object.assign(narrow() ? narrowLayout(fig, breakdown) : Object.assign({}, fig.layout), { autosize: true });
  delete layout.width;
  Plotly.react(div, fig.data, layout, Object.assign({}, PLOT_CONFIG, narrow() ? { displayModeBar: false } : {}));
  if (onClick && !div._ewClick) {
    div._ewClick = true;
    div.on("plotly_click", (ev) => { const p = ev.points && ev.points[0]; if (p && p.customdata) div._ewHandler(p.customdata); });
  }
  if (onClick) div._ewHandler = onClick;
  if (!breakdown && fig.layout.showlegend === false) {
    if (div.nextSibling && div.nextSibling.classList && div.nextSibling.classList.contains("legend")) div.nextSibling.remove();
    div.after(htmlLegend(div, fig));
  }
}

// ---------------------------------------------------------------- signal chart (TradingView Lightweight Charts)
/* Same content as the desktop Plotly chart (converted in mobile/lwchart.py), with TradingView
   handling: pinch or wheel to zoom, drag to move, drag the price axis to stretch it,
   double-tap an axis to reset it, and the buttons below. */
const TV_LIVE = new Set();
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function tvTime(t, intraday) {                 // times are IST wall clock stored "as UTC"
  const d = new Date(t * 1000), p = (n) => String(n).padStart(2, "0");
  const day = `${p(d.getUTCDate())} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
  return intraday ? `${day} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}` : day;
}

function tvChart(spec) {
  TV_LIVE.forEach((c) => { if (!document.body.contains(c.el)) { c.chart.remove(); TV_LIVE.delete(c); } });
  const LW = window.LightweightCharts;
  const fmt = (v) => (v === undefined || v === null ? "–" : Number(v).toFixed(2));
  const wrap = h("div", { class: "tv" });
  const title = h("div", { class: "tv-title" }, spec.title.replace(/<br>/g, " "));
  const readout = h("div", { class: "tv-readout" });
  const el = h("div", { class: "tv-chart", style: `height:${spec.height + (spec.pane ? spec.pane_height : 0)}px` });
  wrap.append(title, readout, el);

  const chart = LW.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "#1a1a19" }, textColor: "#c3c2b7", fontSize: 11,
      attributionLogo: true, panes: { separatorColor: "#383835", enableResize: true } },
    grid: { vertLines: { color: "#262624" }, horzLines: { color: "#262624" } },
    rightPriceScale: { borderColor: "#383835" },
    timeScale: { borderColor: "#383835", timeVisible: spec.intraday, secondsVisible: false, rightOffset: 3 },
    crosshair: { mode: LW.CrosshairMode.Normal },
    localization: { priceFormatter: fmt, timeFormatter: (t) => tvTime(t, spec.intraday) },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
    kineticScroll: { touch: true, mouse: false },
  });
  TV_LIVE.add({ chart, el });
  const quiet = { priceLineVisible: false, lastValueVisible: false };

  // evaluation window after the signal: a faint full-height band behind the candles
  if (spec.signal_time) {
    const shade = chart.addSeries(LW.HistogramSeries, Object.assign({ priceScaleId: "shade", base: 0 }, quiet));
    chart.priceScale("shade").applyOptions({ visible: false, scaleMargins: { top: 0, bottom: 0 } });
    shade.setData(spec.candles.filter((c) => c.time >= spec.signal_time).map((c) => ({ time: c.time, value: 1,
      color: c.time === spec.signal_time ? "rgba(195,194,183,0.22)" : "rgba(57,135,229,0.08)" })));
  }
  const candles = chart.addSeries(LW.CandlestickSeries, { upColor: spec.up, downColor: spec.down, borderVisible: false,
    wickUpColor: spec.up, wickDownColor: spec.down, priceLineVisible: false });
  candles.setData(spec.candles);
  const named = [];                               // [name, colour, series[]] for the legend
  spec.levels.forEach((l) => candles.createPriceLine({ price: l.price, color: l.color, lineWidth: 1, lineStyle: l.style,
    axisLabelVisible: true, title: l.title }));
  const marks = spec.markers.map((m) => ({ time: m.time, position: "atPriceMiddle", price: m.price, shape: m.shape,
    color: m.color, text: m.text, size: 1.2 }));
  if (spec.signal_time) marks.push({ time: spec.signal_time, position: "aboveBar", shape: "arrowDown", color: "#c3c2b7", text: "signal", size: 0.8 });
  marks.sort((a, b) => a.time - b.time);
  LW.createSeriesMarkers(candles, marks);
  named.push(["Price", spec.up, [candles]]);

  const lineSeries = {};
  spec.lines.forEach((l) => {
    const s = chart.addSeries(LW.LineSeries, Object.assign({ color: l.color, lineWidth: Math.max(1, Math.round(l.width)),
      crosshairMarkerVisible: false }, quiet), l.pane);
    s.setData(l.data);
    lineSeries[l.name] = s;
    named.push([l.name, l.color, [s]]);
  });
  spec.waves.forEach((w) => {
    const s = chart.addSeries(LW.LineSeries, Object.assign({ color: w.color, lineWidth: 2, lineStyle: w.style,
      pointMarkersVisible: true, pointMarkersRadius: 3, crosshairMarkerVisible: false }, quiet), 0);
    s.setData(w.data);
    LW.createSeriesMarkers(s, w.labels.map((x) => ({ time: x.time, position: x.position, price: x.price,
      shape: "circle", color: "#f0efec", text: x.text, size: 0.1 })));
    named.push([w.name, w.color, [s]]);
  });

  // indicator pane: 0-100 for RSI / DTosc, histogram (RSI - 50) on its own -50..50 scale so 0 sits on 50
  let hist = null;
  if (spec.pane) {
    const fixed = (lo, hi) => () => ({ priceRange: { minValue: lo, maxValue: hi } });
    Object.entries(lineSeries).forEach(([, s]) => { if (s.getPane().paneIndex() === 1) s.applyOptions({ autoscaleInfoProvider: fixed(0, 100) }); });
    const anchor = Object.values(lineSeries).find((s) => s.getPane().paneIndex() === 1);
    if (spec.hist.length) {
      hist = chart.addSeries(LW.HistogramSeries, Object.assign({ priceScaleId: "hist", autoscaleInfoProvider: fixed(-50, 50) }, quiet), 1);
      chart.priceScale("hist", 1).applyOptions({ visible: false, scaleMargins: { top: 0.06, bottom: 0.06 } });
      hist.setData(spec.hist);
      named.push(["Histogram", "#2fbf71", [hist]]);
    }
    chart.priceScale("right", 1).applyOptions({ scaleMargins: { top: 0.06, bottom: 0.06 } });
    if (anchor) spec.bands.forEach((b) => anchor.createPriceLine({ price: b.price, color: "#6b6a64", lineWidth: 1,
      lineStyle: b.style, axisLabelVisible: false }));
    const size = () => {                          // price : indicator = height : pane_height, as on the desktop
      const panes = chart.panes();
      if (panes[1]) { panes[0].setStretchFactor(spec.height); panes[1].setStretchFactor(spec.pane_height); }
    };
    size();
    requestAnimationFrame(size);
  }

  // readout like TradingView's legend: values under the crosshair (signal bar when idle)
  const byTime = new Map(spec.candles.map((c) => [c.time, c]));
  const show = (t) => {
    const c = byTime.get(t);
    if (!c) { readout.textContent = spec.readings || ""; return; }
    const parts = [`${tvTime(t, spec.intraday)}`, `O ${fmt(c.open)} H ${fmt(c.high)} L ${fmt(c.low)} C ${fmt(c.close)}`];
    spec.lines.forEach((l) => { const p = l.data.find((d) => d.time === t); if (p) parts.push(`${l.name} ${fmt(p.value)}`); });
    const hb = spec.hist.find((d) => d.time === t);
    if (hb) parts.push(`Hist ${fmt(hb.value)}`);
    readout.textContent = parts.join("  ·  ");
  };
  chart.subscribeCrosshairMove((p) => show(p && p.time ? p.time : spec.signal_time));
  show(spec.signal_time);

  // buttons: zoom out / in around the middle, reset everything, jump to the signal
  const ts = chart.timeScale();
  const zoom = (factor) => {
    const r = ts.getVisibleLogicalRange();
    if (!r) return;
    const mid = (r.from + r.to) / 2, half = Math.max(5, ((r.to - r.from) / 2) * factor);
    ts.setVisibleLogicalRange({ from: mid - half, to: mid + half });
  };
  const reset = () => {
    ts.resetTimeScale(); ts.fitContent();
    chart.panes().forEach((_, i) => chart.priceScale("right", i).applyOptions({ autoScale: true }));
  };
  const toSignal = () => {
    const i = spec.candles.findIndex((c) => c.time === spec.signal_time);
    if (i >= 0) ts.setVisibleLogicalRange({ from: i - 40, to: i + 35 });
    chart.panes().forEach((_, k) => chart.priceScale("right", k).applyOptions({ autoScale: true }));
  };
  const bar = h("div", { class: "tv-tools" },
    h("button", { class: "btn small", title: "Zoom out", onclick: () => zoom(1.35) }, "－"),
    h("button", { class: "btn small", title: "Zoom in", onclick: () => zoom(0.7) }, "＋"),
    h("button", { class: "btn small", onclick: reset }, "⟲ Reset"),
    spec.signal_time ? h("button", { class: "btn small", onclick: toSignal }, "◎ Signal") : null,
    h("span", { class: "tv-hint" }, "Pinch or scroll to zoom · drag to move · drag the price axis to stretch"));
  wrap.append(bar);

  const legend = h("div", { class: "legend" });
  named.forEach(([name, colour, series]) => {
    const item = h("button", { class: "lg", onclick: () => {
      const off = item.classList.toggle("off");
      series.forEach((s) => s.applyOptions({ visible: !off }));
    } }, h("i", { style: `background:${colour}` }), name);
    legend.append(item);
  });
  wrap.append(legend);
  requestAnimationFrame(() => ts.fitContent());
  return wrap;
}

// ---------------------------------------------------------------- widgets
function multiselect(labelText, options, selected, onChange, disabled) {
  const box = h("div", { class: "box-input" + (disabled ? " disabled" : "") });
  const draw = () => {
    clear(box);
    if (!selected.length) box.append(h("span", { class: "ph" }, "Choose options"));
    selected.forEach((v) => box.append(h("span", { class: "tag" }, v)));
  };
  draw();
  box.addEventListener("click", () => {
    const picked = new Set(selected);
    const list = h("div", { class: "list" },
      options.map((o) => h("label", {}, h("input", { type: "checkbox", checked: picked.has(o) || null,
        onchange: (e) => (e.target.checked ? picked.add(o) : picked.delete(o)) }), o)));
    const close = () => back.remove();
    const back = h("div", { class: "sheet-back", onclick: (e) => { if (e.target === back) close(); } },
      h("div", { class: "sheet" },
        h("header", {}, labelText, h("button", { class: "btn small", onclick: close }, "✕")),
        options.length ? list : h("div", { class: "spin", style: "padding:14px" }, "No options"),
        h("footer", {},
          h("button", { class: "btn", onclick: () => { picked.clear(); list.querySelectorAll("input").forEach((i) => (i.checked = false)); } }, "Clear"),
          h("button", { class: "btn primary wide", onclick: () => { close(); onChange(options.filter((o) => picked.has(o))); } }, "Done"))));
    $("layer").append(back);
  });
  return h("div", { class: "field ms" }, h("label", {}, labelText), box);
}

function chips(options, selected, onChange, single = false) {
  const wrap = h("div", { class: "radios" });
  const draw = () => {
    clear(wrap);
    options.forEach(([value, text]) => {
      const on = single ? selected === value : selected.includes(value);
      wrap.append(h("button", { class: "chip" + (on ? " on" : ""), onclick: () => {
        if (single) selected = value;
        else selected = on ? selected.filter((x) => x !== value) : [...selected, value];
        draw(); onChange(selected);
      } }, text));
    });
  };
  draw();
  return wrap;
}

function field(labelText, input) { return h("div", { class: "field" }, h("label", {}, labelText), input); }

function check(text, value, onChange, disabled) {
  return h("label", { class: "check" }, h("input", { type: "checkbox", checked: value || null, disabled: disabled || null,
    onchange: (e) => onChange(e.target.checked) }), text);
}

function cellClass(col, value, sideCol) {
  if (col === sideCol) return value === "SHORT" ? "short" : value === "LONG" ? "long" : "";
  if (col === "histogram" && value !== "") {
    const v = parseFloat(value);
    return v < -20 ? "h-good" : v > 20 ? "h-bad" : "";
  }
  if (col === "alignment") return `a-${value}`;
  if (col === "htf1_trend" || col === "htf2_trend") return `t-${value}`;
  return "";
}

/* table: {columns, rows, ids?}. opts: {sideCol, onRow(id, idx), selected, tall} */
function dataTable(t, opts = {}) {
  const wrap = h("div", { class: "tablewrap" + (opts.tall ? " tall" : "") });
  const tbl = h("table", { class: "t" });
  tbl.append(h("thead", {}, h("tr", {}, t.columns.map((c) => h("th", {}, c)))));
  const body = h("tbody");
  tbl.append(body);
  wrap.append(tbl);
  const holder = h("div", {}, wrap);
  let shown = 0;
  const more = h("button", { class: "btn small more" });
  const add = () => {
    const end = Math.min(t.rows.length, shown + PAGE);
    for (let i = shown; i < end; i++) {
      const r = t.rows[i];
      const id = t.ids ? t.ids[i] : i;
      const tr = h("tr", { class: (opts.onRow ? "click" : "") + (opts.selected === id ? " sel" : "") });
      r.forEach((v, j) => {
        const col = t.columns[j];
        const text = v === true ? "✔" : v === false ? "✘" : v;
        const numeric = typeof v === "number" || (typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v));
        tr.append(h("td", { class: [numeric ? "num" : "", cellClass(col, v, opts.sideCol)].join(" ").trim() }, text));
      });
      if (opts.onRow) tr.addEventListener("click", () => {
        body.querySelectorAll("tr.sel").forEach((x) => x.classList.remove("sel"));
        tr.classList.add("sel");
        opts.onRow(id, i);
      });
      body.append(tr);
    }
    shown = end;
    more.textContent = `Show more (${t.rows.length - shown} more rows)`;
    more.classList.toggle("hidden", shown >= t.rows.length);
  };
  more.addEventListener("click", add);
  add();
  holder.append(more);
  return holder;
}

function metric(k, v) { return h("div", { class: "metric" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v)); }

// ---------------------------------------------------------------- tabs, header, job bar
let activeTab = "ew5";
function showTab(key) {
  activeTab = key;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.key === key));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("hidden", s.id !== `tab-${key}`));
  ({ ew5: () => Dash.get("ew5").open(), ew3: () => Dash.get("ew3").open(), data: DataTab.open, run: RunTab.open, guide: Guide.open })[key]();
  window.scrollTo(0, 0);
}

async function refreshHeader() {
  try {
    const s = await api("/api/state");
    const b = clear($("badges"));
    b.append(h("span", { class: "badge blue" }, `🗄️ ${s.tickers} tickers`));
    if (s.data_to) b.append(h("span", { class: "badge green" }, `🕒 Data to ${s.data_to}`));
    b.append(h("span", { class: "badge violet" }, `📦 ${s.saved_runs} saved runs`));
    if (s.job && s.job.running) Jobs.watch();
  } catch (e) { console.error(e); }
}

const Jobs = {
  timer: null, lastId: null,
  watch() { if (!this.timer) this.poll(); },
  async poll() {
    this.timer = null;
    let job;
    try { job = (await api("/api/job")).job; } catch (e) { this.timer = setTimeout(() => this.poll(), 3000); return; }
    const bar = $("jobbar");
    if (!job) { bar.classList.add("hidden"); return; }
    if (job.running) {
      bar.classList.remove("hidden");
      clear(bar).append(h("b", {}, job.title), " · ", job.text, ` · ${Math.round(job.done * 100)}% · ${job.seconds}s`,
        h("div", { class: "bar" }, h("i", { style: `width:${Math.round(job.done * 100)}%` })));
      this.lastId = job.id;
      this.timer = setTimeout(() => this.poll(), 1500);
      if (activeTab === "data" && job.kind !== "run") DataTab.showJob(job);
      if (activeTab === "run" && job.kind === "run") RunTab.showJob(job);
    } else {
      bar.classList.add("hidden");
      if (this.lastId === job.id) { this.lastId = null; this.finished(job); }
    }
  },
  finished(job) {
    toast(job.error ? `${job.title} failed: ${job.error}` : `${job.title} finished in ${job.seconds}s`, 4500);
    refreshHeader();
    Dash.all.forEach((d) => (d.stale = true));
    if (job.kind === "run" && job.result) Dash.get(job.result.strategy).state.file = job.result.file;   // its dashboard opens this run
    if (activeTab === "data") DataTab.open(job);
    if (activeTab === "run") RunTab.open(job);
    if (activeTab === "ew5" || activeTab === "ew3") Dash.get(activeTab).open();
  },
  async start(path, body) {
    try {
      const job = await api(path, body);
      this.lastId = job.id;
      this.poll();
      return job;
    } catch (e) { toast(e.message, 5000); return null; }
  },
};

// ---------------------------------------------------------------- dashboards (EW5 / EW3)
class Dash {
  static all = [];
  static get(key) { return Dash.all.find((d) => d.key === key); }

  constructor(key) {
    this.key = key;
    this.root = $(`tab-${key}`);
    this.state = { file: null, filters: {}, search: "", ratio: [null, null], stat: null, live: {},
      bars: { outcome: [], mfemae: [], align: [], sides: [] }, groups: {}, dlg: {}, selected: null };
    this.loaded = false; this.stale = true; this.seq = 0; this.res = null; this.saved = null;
    Dash.all.push(this);
  }

  async open() {
    if (!this.loaded) {
      this.root.append(spinner());
      try { const p = await api(`/api/prefs?key=${this.key}`); this.applyPrefs(p.prefs); this.saved = p.saved ? p.prefs : null; }
      catch (e) { console.error(e); }
      this.loaded = true;
    }
    if (this.stale) this.load();
  }

  applyPrefs(p) {
    const s = this.state;
    s.filters = {};
    Object.keys(p).forEach((k) => { if (Array.isArray(p[k]) && k !== "ratio") s.filters[k] = p[k].slice(); });
    s.search = p.search || ""; s.ratio = (p.ratio || [null, null]).slice(); s.stat = p.stat || null;
    s.groups = Object.assign({}, p.chart_groups || {}); s.dlg = Object.assign({}, p.chart_groups || {});
    s.bars = { outcome: [], mfemae: [], align: [], sides: [] }; s.live = {};
  }

  currentPrefs() {
    const s = this.state, res = this.res;
    const out = {};
    (res ? res.filter_cols : []).forEach(([c]) => (out[c] = (s.filters[c] || []).slice()));
    out.search = s.search; out.ratio = s.ratio.slice(); out.stat = s.stat;
    out.chart_groups = {};
    [...(res ? res.level_groups : []), "ema", "ind"].forEach((g) => (out.chart_groups[g] = s.groups[g] !== false));
    return out;
  }

  async load(resetBars) {
    if (resetBars) this.state.bars = { outcome: [], mfemae: [], align: [], sides: [] };
    const seq = ++this.seq;
    const s = this.state;
    let res;
    try {
      res = await api("/api/dashboard", { key: this.key, file: s.file, filters: s.filters, search: s.search,
        ratio: s.ratio, stat: s.stat, bars: s.bars, live: s.live });
    } catch (e) { clear(this.root).append(note("error", e.message)); return; }
    if (seq !== this.seq) return;                       // a newer request is on its way
    this.res = res; this.stale = false;
    if (res.file) s.file = res.file;
    if (res.stat !== undefined) s.stat = res.stat;
    this.render();
  }

  render() {
    const res = this.res, s = this.state, root = this.root;
    const y = window.scrollY;
    clear(root);
    root.append(h("div", { class: "caption", html: `<b>${esc(res.name)}</b> · ${esc(res.blurb)}` }));
    if (!res.files || !res.files.length) { root.append(note("info", res.info)); return; }
    const sel = h("select", { onchange: (e) => { s.file = e.target.value; s.stat = this.saved ? this.saved.stat : null; s.live = {}; this.load(true); } },
      res.files.map((f) => h("option", { value: f, selected: f === res.file || null }, f)));
    root.append(h("div", { class: "row" }, field("Results file", sel),
      h("div", { class: "caption", style: "flex:2 1 260px" }, h("b", {}, res.caption[0]), h("br"), res.caption[1])));
    if (res.info) { root.append(note("info", res.info)); return; }

    root.append(this.filtersBox());
    if (res.warning) { root.append(note("warn", res.warning)); return; }
    root.append(res.evaluated ? this.kpiCards() : this.liveCards());
    root.append(this.breakdown());

    root.append(h("h3", {}, "📋 Signals"));
    const narrowed = res.narrowed ? " · narrowed by the selected stat / chart bar" : "";
    root.append(h("div", { class: "caption" }, `${res.counts.view} of ${res.counts.total} signals${narrowed} · newest first`));
    if (!res.table.rows.length) { root.append(note("warn", "No signals behind this selection.")); window.scrollTo(0, y); return; }
    const ids = res.table.ids;
    if (!ids.includes(s.selected)) s.selected = ids[0];
    root.append(h("div", { class: "row" },
      h("div", { class: "caption", style: "flex:3 1 220px" }, "Tap any signal to open its chart in an overlay. The same chart stays below."),
      h("button", { class: "btn small", style: "flex:0 0 auto", onclick: () => this.openDialog(s.selected) }, "⤢ Open chart overlay")));
    root.append(dataTable(res.table, { sideCol: res.side_col, selected: s.selected,
      onRow: (id) => { s.selected = id; this.openDialog(id); this.drawChart(); } }));
    this.chartBox = h("div");
    root.append(this.chartBox);
    this.drawChart();
    window.scrollTo(0, y);
  }

  filtersBox() {
    const res = this.res, s = this.state;
    const box = h("div", { class: "box" });
    const grid = h("div", { class: "row" });
    res.filter_cols.forEach(([col, lbl]) => {
      grid.append(multiselect(lbl, res.options[col] || [], s.filters[col] || [],
        (v) => { s.filters[col] = v; this.load(true); }, res.disabled.includes(col)));
    });
    box.append(grid);
    const row2 = h("div", { class: "row", style: "margin-top:10px" });
    let timer;
    row2.append(field("Ticker search", h("input", { type: "text", value: s.search, placeholder: "e.g. BAJ",
      oninput: (e) => { s.search = e.target.value; clearTimeout(timer); timer = setTimeout(() => this.load(true), 450); } })));
    if (res.ratio) row2.append(this.rangeWidget(res.ratio));
    box.append(row2);
    const prefsDiffer = this.saved && JSON.stringify(this.currentPrefs()) !== JSON.stringify(this.normalisedSaved());
    box.append(h("div", { class: "row", style: "margin-top:10px" },
      h("button", { class: "btn primary", onclick: () => this.savePrefs() }, "💾 Save filters"),
      h("button", { class: "btn", disabled: !this.saved || null, onclick: () => { this.applyPrefs(this.saved); toast("Saved filters restored."); this.load(true); } }, "↺ Restore"),
      h("button", { class: "btn", onclick: () => { this.applyPrefs({ chart_groups: {} }); toast("Filters cleared (press Save filters to make this the default)."); this.load(true); } }, "⨯ Clear")));
    if (prefsDiffer) box.append(h("div", { class: "caption" }, "Filters differ from the saved ones."));
    return box;
  }

  normalisedSaved() {
    const p = this.saved, out = {};
    this.res.filter_cols.forEach(([c]) => (out[c] = (p[c] || []).slice()));
    out.search = p.search || ""; out.ratio = (p.ratio || [null, null]).slice(); out.stat = p.stat || null;
    out.chart_groups = {};
    [...this.res.level_groups, "ema", "ind"].forEach((g) => (out.chart_groups[g] = (p.chart_groups || {})[g] !== false));
    return out;
  }

  async savePrefs() {
    const p = this.currentPrefs();
    try { const r = await api("/api/prefs/save", { key: this.key, prefs: p }); this.saved = p; toast(r.note); this.render(); }
    catch (e) { toast(e.message); }
  }

  rangeWidget(r) {
    const s = this.state;
    const step = (r.hi - r.lo) / 200;
    const fmt = (v) => Number(v).toFixed(3);
    const [low, high] = r.value;
    const vLow = h("span", { class: "val" }, fmt(low)), vHigh = h("span", { class: "val" }, fmt(high));
    const commit = (a, b) => {
      const eps = 1e-9;
      s.ratio = [a <= r.lo + eps ? null : a, b >= r.hi - eps ? null : b];
      this.load(true);
    };
    const inLow = h("input", { type: "range", min: r.lo, max: r.hi, step, value: low });
    const inHigh = h("input", { type: "range", min: r.lo, max: r.hi, step, value: high });
    inLow.addEventListener("input", () => { if (+inLow.value > +inHigh.value) inLow.value = inHigh.value; vLow.textContent = fmt(inLow.value); });
    inHigh.addEventListener("input", () => { if (+inHigh.value < +inLow.value) inHigh.value = inLow.value; vHigh.textContent = fmt(inHigh.value); });
    inLow.addEventListener("change", () => commit(+inLow.value, +inHigh.value));
    inHigh.addEventListener("change", () => commit(+inLow.value, +inHigh.value));
    return h("div", { class: "field", style: "flex:2 1 260px" }, h("label", {}, `${this.res.ratio_col} range`),
      h("div", { class: "range" }, h("div", {}, h("span", { class: "val" }, "from "), vLow), h("div", {}, h("span", { class: "val" }, "to "), vHigh), inLow, inHigh));
  }

  kpiCards() {
    const res = this.res, s = this.state;
    const wrap = h("div", { class: "cards" });
    wrap.append(h("div", { class: "card" }, h("div", { class: "k" }, "📡 Signals"), h("div", { class: "v" }, res.signals.toLocaleString()),
      h("button", { class: "btn", disabled: !s.stat || null, onclick: () => { s.stat = null; this.load(); } }, "Show all")));
    res.cards.forEach((c) => {
      const on = s.stat === c.name;
      wrap.append(h("div", { class: "card" }, h("div", { class: "k", title: c.tip }, c.label), h("div", { class: "v" }, c.value),
        h("div", { class: "tip" }, c.tip),
        h("button", { class: "btn" + (on ? " primary" : ""), onclick: () => { s.stat = on ? null : c.name; this.load(); } },
          on ? `✓ Showing ${c.count.toLocaleString()}` : `Show ${c.count.toLocaleString()}`)));
    });
    return wrap;
  }

  liveCards() {
    const res = this.res, s = this.state;
    const wrap = h("div", { class: "cards" });
    wrap.append(h("div", { class: "card" }, h("div", { class: "k" }, "📡 Signals"), h("div", { class: "v" }, res.signals.toLocaleString())));
    res.live_cards.forEach((c) => {
      wrap.append(h("div", { class: "card" }, h("div", { class: "k" }, c.label),
        h("div", { class: "pills" }, c.counts.map(([v, n]) => h("button", { class: "chip" + (c.pick === v ? " on" : ""),
          onclick: () => { s.live[c.field] = c.pick === v ? null : v; this.load(); } }, `${v} · ${n}`)))));
    });
    return wrap;
  }

  breakdown() {
    const res = this.res, s = this.state, figs = res.figures;
    const box = h("div");
    box.append(h("h3", {}, "📊 Breakdown"));
    box.append(h("div", { class: "caption" }, "Tap a bar to filter the signal table to the signals inside it. Tap more bars to add them."));
    const toggle = (chart) => (cd) => {
      const list = s.bars[chart], keyOf = JSON.stringify(cd);
      const i = list.findIndex((x) => JSON.stringify(x) === keyOf);
      if (i >= 0) list.splice(i, 1); else list.push(cd);
      this.load();
    };
    const add = (parent, name, chart) => {
      const div = h("div", { class: "plot box", style: "padding:0" });
      parent.append(div);
      requestAnimationFrame(() => plot(div, figs[name], toggle(chart)));
    };
    const grid = h("div", { class: "charts" });
    box.append(grid);
    if (res.evaluated) {
      add(grid, "outcome", "outcome");
      add(grid, "mfemae", "mfemae");
      if (figs.align) {
        add(grid, "align", "align");
        grid.append(h("div", { class: "box" }, h("b", {}, "Does trading with the higher timeframe pay?"),
          h("div", { class: "caption" }, "ALIGNED: every higher timeframe points the way of the trade · AGAINST: the next timeframe up points the other way · MIXED: in between. Rates are out of triggered signals."),
          dataTable(res.align_table)));
      }
    } else {
      add(grid, "sides", "sides");
    }
    if (res.notes.length) {
      box.append(h("div", { class: "row note info", style: "align-items:center" },
        h("div", { style: "flex:5 1 200px", html: `<b>Chart filter:</b> ${esc(res.notes.join(" · "))}` }),
        h("button", { class: "btn small", style: "flex:0 0 auto", onclick: () => this.load(true) }, "✕ Clear chart filter")));
    }
    if (res.summary_table) {
      box.append(h("details", {}, h("summary", {}, "▦ Summary table (by timeframe × degree)"), h("div", {}, dataTable(res.summary_table))));
    }
    return box;
  }

  chartToggles(bag, onChange) {
    const res = this.res;
    const names = [...res.level_groups.map((g) => [g, g]), ["ema", "EMA 13 / 55"], ["ind", "Indicators"]];
    const wrap = h("div", { class: "toggles" });
    names.forEach(([key, text]) => {
      const on = bag[key] !== false;
      wrap.append(h("button", { class: "chip" + (on ? " on" : ""), onclick: () => { bag[key] = !on; onChange(); } }, text));
    });
    return wrap;
  }

  chartRequest(id, bag, compact) {
    return { key: this.key, file: this.state.file, id, compact, narrow: narrow(),
      groups: this.res.level_groups.filter((g) => bag[g] !== false), ema: bag.ema !== false, ind: bag.ind !== false };
  }

  async drawChart() {
    const box = this.chartBox, s = this.state;
    if (!box) return;
    const seq = (this.chartSeq = (this.chartSeq || 0) + 1);
    let c;
    try { c = await api("/api/chart", this.chartRequest(s.selected, s.groups, false)); }
    catch (e) { clear(box).append(note("error", e.message)); return; }
    if (seq !== this.chartSeq) return;
    clear(box);
    const [ticker, tf, degree, side] = c.heading;
    box.append(h("h3", { html: `🕯️ ${esc(ticker)} · ${esc(tf)} · ${esc(degree)} · <span class="${side === "SHORT" ? "short" : "long"}">${esc(side)}</span>` }));
    if (c.htf) box.append(h("div", { html: `<b>Higher timeframes:</b> <span class="a-${esc(c.alignment)}">${esc(c.htf)}</span>` }));
    box.append(this.chartToggles(s.groups, () => this.drawChart()));
    if (c.warning) box.append(note("warn", c.warning));
    if (c.tv) box.append(tvChart(c.tv));
    if (c.note) box.append(h("div", { class: "caption" }, c.note));

    box.append(h("h3", {}, "ℹ️ Signal details"));
    box.append(h("div", { class: "split" },
      dataTable({ columns: ["Field", "Value"], rows: c.fields }, { tall: true }),
      h("div", {}, metric("Live count", c.live_count), h("div", { style: "height:8px" }), dataTable({ columns: ["Level", "Price"], rows: c.levels }, { tall: true }))));
  }

  async openDialog(id) {
    const s = this.state;
    const panel = h("div", { class: "panel" });
    const back = h("div", { class: "dialog" }, panel);
    const close = () => { back.remove(); Back.pop(close); };
    Back.push(close);
    $("layer").append(back);
    const draw = async () => {
      clear(panel).append(spinner());
      let c;
      try { c = await api("/api/chart", this.chartRequest(id, s.dlg, true)); }
      catch (e) { clear(panel).append(note("error", e.message)); return; }
      clear(panel);
      panel.append(h("div", { class: "head" }, h("b", {}, c.dialog_title), h("button", { class: "btn small", onclick: close }, "✕")));
      panel.append(h("div", { class: "facts", html: c.facts.map(([k, v]) => `<b>${esc(k)}</b> ${esc(v)}`).join("  |  ") }));
      panel.append(this.chartToggles(s.dlg, draw));
      if (c.warning) panel.append(note("warn", c.warning));
      if (c.tv) panel.append(tvChart(c.tv));
      if (c.note) panel.append(h("div", { class: "caption" }, c.note));
    };
    draw();
  }
}

// Android back button closes the top-most overlay first.
const Back = {
  stack: [],
  push(fn) { this.stack.push(fn); },
  pop(fn) { this.stack = this.stack.filter((x) => x !== fn); },
  handle() {
    const sheet = document.querySelector(".sheet-back");
    if (sheet) { sheet.remove(); return true; }
    const fn = this.stack[this.stack.length - 1];
    if (fn) { fn(); return true; }
    if (activeTab !== "ew5") { showTab("ew5"); return true; }
    return false;
  },
};
window.appBack = () => Back.handle();

// ---------------------------------------------------------------- Data tab
const DataTab = {
  form: null, preview: { tickers: [], timeframes: [], newest: true },
  async open(finishedJob) {
    const root = clear($("tab-data"));
    root.append(spinner());
    let d, tick;
    try { [d, tick] = await Promise.all([api("/api/data"), api("/api/tickers")]); }
    catch (e) { clear(root).append(note("error", e.message)); return; }
    if (!DataTab.form) DataTab.form = { pasted: "", save_pasted: false, timeframes: d.timeframes.slice(), days: d.incremental_days, confirm: false };
    const f = DataTab.form;
    clear(root);

    // ---- update controls (the desktop sidebar)
    const ctl = h("div", { class: "box" }, h("h3", { style: "margin-top:0" }, "☁️ Data update"));
    ctl.append(h("div", { class: "caption", html: `Final list = <b>${tick.count}</b> stock tickers + ${tick.indices} indices + ${tick.commodities} commodities (lists in <code>stock_data.py</code>)` }));
    const edit = h("textarea", { rows: 6 }, tick.text);
    ctl.append(h("details", {}, h("summary", {}, `✎ Stock tickers file (${tick.count})`), h("div", {},
      h("div", { class: "caption" }, "yfinance symbols, one per line or separated by commas, e.g. RELIANCE.NS"), edit,
      h("button", { class: "btn small", style: "margin-top:6px", onclick: async () => {
        try { const r = await api("/api/tickers", { text: edit.value }); toast(`Saved ${r.count} tickers`); DataTab.open(); } catch (e) { toast(e.message); } } }, "Save tickers file"))));
    const paste = h("textarea", { rows: 2, placeholder: "RELIANCE.NS, TCS.NS, INFY.NS", oninput: (e) => { f.pasted = e.target.value; saveBox.querySelector("input").disabled = !f.pasted.trim(); } }, f.pasted);
    const saveBox = check("Save pasted list to the tickers file", f.save_pasted, (v) => (f.save_pasted = v), !f.pasted.trim());
    ctl.append(field("…or paste stock tickers (replaces the file for this update)", paste), saveBox);
    ctl.append(field("Timeframes", chips(d.timeframes.map((t) => [t, t]), f.timeframes, (v) => (f.timeframes = v))));
    ctl.append(h("div", { class: "row" },
      field("Incremental days", h("input", { type: "number", min: 1, max: 700, value: f.days, onchange: (e) => (f.days = +e.target.value) })),
      h("button", { class: "btn primary", onclick: () => Jobs.start("/api/data/update", { pasted: f.pasted, save_pasted: f.save_pasted, timeframes: f.timeframes, days: f.days, full: false }).then(() => DataTab.open()) }, "⟳ Update data")));
    ctl.append(h("div", { class: "caption" }, "New tickers get their full history; all others only the last N days."));
    ctl.append(h("hr", { style: "border:0;border-top:1px solid var(--border);margin:12px 0" }));
    const fullBtn = h("button", { class: "btn", disabled: !f.confirm || null, onclick: () => Jobs.start("/api/data/update", { pasted: f.pasted, save_pasted: f.save_pasted, timeframes: f.timeframes, days: f.days, full: true }).then(() => DataTab.open()) }, "⟲ Full re-download");
    ctl.append(h("div", { class: "row", style: "align-items:center" }, check("Yes, replace all stored history", f.confirm, (v) => { f.confirm = v; fullBtn.disabled = !v; }), fullBtn));
    if (NATIVE && NATIVE.pickStockCsv) {
      ctl.append(h("div", { class: "row", style: "margin-top:10px;align-items:center" },
        h("div", { class: "caption", style: "flex:3 1 200px" }, "Have the desktop's data/stock.csv on this phone? Import it instead of downloading."),
        h("button", { class: "btn", style: "flex:0 0 auto", onclick: () => NATIVE.pickStockCsv() }, "📥 Import stock.csv")));
    }
    if (d.import_ready) ctl.append(h("div", { class: "row" }, note("info", "A stock.csv is ready to import."), h("button", { class: "btn primary", onclick: () => Jobs.start("/api/data/import", {}) }, "Import now")));
    root.append(ctl);

    root.append(h("h3", {}, "🗄️ Stock data"));
    root.append(h("div", { class: "caption" }, `${d.parts} part files · ${d.size_mb} MB · Daily, 4hr and 60m bars from Yahoo (4hr is built from the 60m bars), stored as timezone-naive IST, with indicators. Weekly (1W) bars are built from the daily ones for the higher-timeframe trend.`));
    DataTab.jobBox = h("div");
    root.append(DataTab.jobBox);
    if (finishedJob && finishedJob.kind !== "run") DataTab.showJob(finishedJob);
    if (d.report) root.append(DataTab.report(d.report));

    if (d.empty) { root.append(note("info", "No data yet. Press **Update data** above - the first run downloads the full history (3 years daily, about 2 years of 60m). It takes a while for all tickers; the phone can stay locked.")); return; }
    if (d.new_tickers.length) root.append(note("info", `${d.new_tickers.length} ticker(s) in your list are not stored yet and will get a full download on the next update: ${d.new_tickers.slice(0, 15).join(", ")}${d.new_tickers.length > 15 ? " …" : ""}`));
    if (!d.has_weekly) root.append(h("div", {}, note("warn", `No weekly (${d.weekly}) bars yet. Daily signals need them for the higher-timeframe trend.`),
      h("button", { class: "btn", onclick: () => Jobs.start("/api/data/weekly", {}) }, "Build weekly bars from the daily data")));

    root.append(h("div", { class: "split" },
      h("div", {}, h("h4", {}, "Coverage per timeframe"), dataTable(d.coverage)),
      h("div", {}, h("h4", {}, `Bars per ticker · ${d.n_short} with short history (< ${d.short_history_bars} bars in a timeframe; ${d.weekly} not counted)`), dataTable(d.per_ticker))));

    root.append(h("h4", {}, "Preview"));
    const p = DataTab.preview;
    const out = h("div");
    const reload = async () => {
      clear(out).append(spinner());
      try {
        const t = await api("/api/data/preview", p);
        clear(out).append(h("div", { class: "caption" }, `${t.total.toLocaleString()} rows` + (t.total > t.rows.length ? ` (showing the first ${t.rows.length.toLocaleString()})` : "")), dataTable(t, { tall: true }));
      } catch (e) { clear(out).append(note("error", e.message)); }
    };
    root.append(h("div", { class: "row" },
      multiselect("Ticker", d.stored_tickers, p.tickers, (v) => { p.tickers = v; DataTab.open(); }),
      multiselect("Timeframe", d.stored_timeframes, p.timeframes, (v) => { p.timeframes = v; DataTab.open(); }),
      h("div", { style: "flex:0 0 auto" }, check("Newest first", p.newest, (v) => { p.newest = v; reload(); }))));
    root.append(out);
    reload();
  },
  report(r) {
    const box = h("div", { class: "box" }, h("b", {}, "Last update"));
    box.append(h("div", { class: "metrics", style: "margin-top:8px" }, metric("Rows before", r.rows_before.toLocaleString()), metric("Rows after", r.rows_after.toLocaleString()),
      metric("Rows added", r.added.toLocaleString()), metric("Rows replaced", r.replaced.toLocaleString())));
    if (r.stats) box.append(h("div", { style: "margin-top:8px" }, dataTable(r.stats)));
    const failed = Object.entries(r.failed || {});
    failed.forEach(([tf, bad]) => box.append(note("warn", `**${tf}** – no data for ${bad.length} ticker(s): ${bad.join(", ")}`)));
    if (!failed.length && r.saved) box.append(note("ok", "All tickers downloaded."));
    if (!r.saved) box.append(note("error", "Nothing was downloaded, the stored data is unchanged."));
    box.append(h("details", {}, h("summary", {}, "Download log"), h("div", {}, h("pre", { style: "white-space:pre-wrap;font-size:0.75rem" }, r.log.join("\n")))));
    return box;
  },
  showJob(job) {
    if (!DataTab.jobBox) return;
    clear(DataTab.jobBox).append(h("div", { class: "box" }, h("b", {}, job.title), " · ",
      job.running ? `${Math.round(job.done * 100)}% · ${job.text}` : (job.error ? `failed: ${job.error}` : `finished in ${job.seconds}s`),
      job.log.length ? h("details", {}, h("summary", {}, "Log"), h("div", {}, h("pre", { style: "white-space:pre-wrap;font-size:0.75rem" }, job.log.slice(-60).join("\n")))) : null));
  },
};

// ---------------------------------------------------------------- Run / Backtest tab
const RunTab = {
  f: null, opts: null,
  async open(finishedJob) {
    const root = clear($("tab-run"));
    root.append(h("h2", {}, "🔎 Run a screener"));
    let o;
    try { o = RunTab.opts = await api("/api/run/options"); } catch (e) { root.append(note("error", e.message)); return; }
    if (o.empty) { root.append(note("info", "Download data first (Data tab).")); return; }
    if (!RunTab.f) {
      RunTab.f = { strategy: "ew5", mode: "live", as_of: o.default_asof, start: o.default_start, end: o.last_day,
        timeframes: o.default_timeframes.slice(), lengths: o.default_lengths.slice(), horizon_bars: o.horizon_bars,
        pivot_tie: o.pivot_tie, hi_source: o.hi_source, lo_source: o.lo_source, min_w5_vs_w1: o.min_w5_vs_w1,
        max_since: "", contexts: o.default_contexts.slice(), min_retrace: o.min_retrace, max_retrace: o.max_retrace,
        resignal: false, aligned_only: false, stages: {} };
    }
    const f = RunTab.f;
    const S = o.strategies.find((x) => x.key === f.strategy);
    if (!f.stages[f.strategy]) f.stages[f.strategy] = S.default_stages.slice();
    const isEw3 = f.strategy === "ew3";
    const redraw = () => RunTab.open();
    const box = h("div", { class: "box" });
    box.append(field("Strategy", chips(o.strategies.map((x) => [x.key, x.name]), f.strategy, (v) => { f.strategy = v; redraw(); }, true)));
    box.append(h("div", { class: "caption" }, S.blurb));
    box.append(field("Mode", chips(o.modes, f.mode, (v) => { f.mode = v; redraw(); }, true)));
    const date = (key, lbl) => field(lbl, h("input", { type: "date", value: f[key], min: o.first_day, max: o.last_day, onchange: (e) => { f[key] = e.target.value; RunTab.check(); } }));
    if (f.mode === "asof") box.append(date("as_of", "As-of date (signals as they stood after this day's close)"));
    if (f.mode === "backtest") box.append(h("div", { class: "row" }, date("start", "Start date"), date("end", "End date")));
    box.append(field(`Timeframes (${o.weekly} is built from the daily bars and can also be scanned)`, chips(o.timeframes.map((t) => [t, t]), f.timeframes, (v) => { f.timeframes = v; RunTab.check(); })));
    box.append(field("ZigZag lengths", chips(o.lengths, f.lengths, (v) => { f.lengths = v; RunTab.check(); })));
    box.append(field("Stages", chips(S.stages.map((x) => [x, x]), f.stages[f.strategy], (v) => { f.stages[f.strategy] = v; RunTab.check(); })));
    const num = (key, lbl, attrs) => field(lbl, h("input", Object.assign({ type: "number", value: f[key], onchange: (e) => { f[key] = e.target.value === "" ? "" : +e.target.value; RunTab.check(); } }, attrs)));
    const sel = (key, lbl, options) => field(lbl, h("select", { onchange: (e) => (f[key] = e.target.value) }, options.map((x) => h("option", { value: x, selected: f[key] === x || null }, x))));
    const r1 = h("div", { class: "row" }, num("horizon_bars", "horizon_bars", { min: 1, max: 500 }),
      num("max_since", isEw3 ? "max_bars_since_w2 (optional)" : "max_bars_since_w5 (optional)", { min: 0 }));
    if (!isEw3) r1.append(num("min_w5_vs_w1", "min_w5_vs_w1", { min: 0, step: 0.1 }));
    r1.append(sel("pivot_tie", "pivot_tie", o.pivot_ties));
    box.append(r1);
    if (isEw3) {
      box.append(field("Context", chips(o.contexts.map((x) => [x, x]), f.contexts, (v) => { f.contexts = v; RunTab.check(); })));
      box.append(h("div", { class: "caption" }, "AFTER_WAVE5: wave 1 starts where a completed wave 5 ended (reversal). AFTER_ABC: wave 1 starts where an a-b-c correction ended (trend resumes). OTHER: any other 0-1-2, roughly ten times more signals."));
      box.append(h("div", { class: "row" }, num("min_retrace", "Wave 2 retracement of wave 1 · from", { min: 0.1, max: 0.99, step: 0.001 }),
        num("max_retrace", "to", { min: 0.1, max: 0.99, step: 0.001 })));
    }
    box.append(h("div", { class: "row" }, sel("hi_source", "High source", o.hi_sources), sel("lo_source", "Low source", o.lo_sources)));
    box.append(check(isEw3 ? "resignal_on_new_w2 (backtest only: a new signal when the wave-2 pivot moves to a new extreme)"
      : "resignal_on_extension (backtest only: a new signal each time wave 5 makes a new confirmed extreme)", f.resignal, (v) => (f.resignal = v), f.mode !== "backtest"));
    box.append(check("Keep only signals aligned with the higher timeframes", f.aligned_only, (v) => (f.aligned_only = v)));
    box.append(h("div", { class: "caption" }, `Every signal is tagged ALIGNED / MIXED / AGAINST from the trend of the timeframes above it (60m → 4hr, 1D · 4hr → 1D, 1W · 1D → 1W). Leave this off to keep all of them and filter on the dashboard. min_bars = ${o.min_bars} (config.yaml)`));
    RunTab.checkBox = h("div");
    box.append(RunTab.checkBox);
    box.append(h("button", { class: "btn primary", style: "margin-top:8px", onclick: RunTab.run }, `▶ Run ${f.strategy.toUpperCase()}`));
    root.append(box);
    RunTab.jobBox = h("div");
    root.append(RunTab.jobBox);
    if (finishedJob && finishedJob.kind === "run") RunTab.showJob(finishedJob);
    RunTab.lastBox = h("div");
    root.append(RunTab.lastBox);
    RunTab.check();
    RunTab.showLast();
  },
  body() {
    const f = RunTab.f;
    return Object.assign({}, f, { stages: f.stages[f.strategy] || [] });
  },
  async check() {
    const box = RunTab.checkBox;
    if (!box) return;
    try {
      const c = await api("/api/run/check", RunTab.body());
      clear(box);
      c.problems.forEach((p) => box.append(note("error", p)));
      if (c.short_warning) box.append(note("warn", c.short_warning), h("details", {}, h("summary", {}, "Show them"), h("div", {}, dataTable(c.short))));
    } catch (e) { clear(box).append(note("error", e.message)); }
  },
  async run() { if (await Jobs.start("/api/run", RunTab.body())) toast("Running… you can leave this screen; the phone keeps working."); },
  showJob(job) {
    if (!RunTab.jobBox) return;
    clear(RunTab.jobBox).append(h("div", { class: "box" }, h("b", {}, job.title), " · ",
      job.running ? `${Math.round(job.done * 100)}% · ${job.text}` : (job.error ? `failed: ${job.error}` : `finished in ${job.seconds}s`)));
  },
  async showLast() {
    const box = RunTab.lastBox;
    let r;
    try { r = await api("/api/run/last"); } catch (e) { return; }
    if (!r.file) return;
    clear(box);
    box.append(note("ok", `${r.rows} signal(s) · saved to \`results/${r.file}\` (+ .json with the parameters). Open the **${r.strategy.toUpperCase()}** tab for the charts.`));
    if (r.summary) box.append(h("h4", {}, "Backtest summary (summarize_backtest)"), dataTable(r.summary));
    box.append(h("h4", {}, "Signals"), dataTable(r.signals, { tall: true }));
    if (r.signals.total > r.signals.rows.length) box.append(h("div", { class: "caption" }, `Showing the first ${r.signals.rows.length} of ${r.signals.total}. The full file is in the dashboard and the CSV.`));
    const url = `/files/results/${encodeURIComponent(r.file)}?t=${TOKEN}`;
    box.append(h("div", { style: "margin-top:8px" }, NATIVE && NATIVE.shareResult
      ? h("button", { class: "btn", onclick: () => NATIVE.shareResult(r.file) }, "⇪ Share results CSV")
      : h("a", { class: "btn", href: url, download: r.file }, "⤓ Download results CSV")));
  },
};

// ---------------------------------------------------------------- User Guide
const Guide = {
  docs: null, which: "functional",
  async open() {
    const root = clear($("tab-guide"));
    if (!Guide.docs) { root.append(spinner()); try { Guide.docs = await api("/api/guide"); } catch (e) { clear(root).append(note("error", e.message)); return; } clear(root); }
    const tabs = [["functional", "How to use it (F&O)"], ["technical", "Technical documentation"], ["phone", "Phone app"]].filter(([k]) => Guide.docs[k]);
    root.append(h("div", { class: "subtabs" }, chips(tabs, Guide.which, (v) => { Guide.which = v; Guide.open(); }, true)));
    root.append(h("div", { class: "guide", html: Guide.docs[Guide.which] }));
  },
};

// ---------------------------------------------------------------- start
function boot() {
  const nav = $("tabs");
  TABS.forEach(([key, text]) => nav.append(h("button", { "data-key": key, onclick: () => showTab(key) }, text)));
  new Dash("ew5"); new Dash("ew3");
  refreshHeader();
  showTab("ew5");
  let w = window.innerWidth;
  window.addEventListener("resize", () => {
    if (Math.abs(window.innerWidth - w) < 80) return;          // keyboard / toolbar changes
    w = window.innerWidth;
    if (activeTab === "ew5" || activeTab === "ew3") Dash.get(activeTab).load();   // breakdown charts re-laid out
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { refreshHeader(); Jobs.watch(); } });
}
window.onImportReady = () => { toast("File copied. Importing…"); Jobs.start("/api/data/import", {}).then(() => DataTab.open()); };
window.onImportFailed = (msg) => toast(`Import failed: ${msg}`, 5000);
boot();
