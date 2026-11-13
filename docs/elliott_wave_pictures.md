## Elliott Wave in pictures

Four pictures cover everything the scanner looks for. Prices go up the page; time goes to
the right. The levels have the names used in the tables and on the charts.

### 1. The basic pattern: five waves, then three

<figure class="ew-fig">
<svg viewBox="0 0 640 300" role="img" aria-label="Five-wave impulse followed by an a-b-c correction">
<line class="grid" x1="20" y1="275" x2="620" y2="275"/>
<polyline class="wave" points="40,262 112,182 162,228 292,74 352,130 432,44"/>
<polyline class="corr" points="432,44 502,138 548,96 612,190"/>
<circle class="dot" cx="40" cy="262" r="5"/><circle class="dot" cx="112" cy="182" r="5"/><circle class="dot" cx="162" cy="228" r="5"/>
<circle class="dot" cx="292" cy="74" r="5"/><circle class="dot" cx="352" cy="130" r="5"/><circle class="dot" cx="432" cy="44" r="5"/>
<text class="lbl" x="30" y="296">0</text><text class="lbl" x="98" y="170">1</text><text class="lbl" x="152" y="256">2</text>
<text class="lbl" x="282" y="62">3</text><text class="lbl" x="344" y="158">4</text><text class="lbl" x="424" y="32">5</text>
<text class="lbl" x="506" y="164">a</text><text class="lbl" x="546" y="84">b</text><text class="lbl" x="606" y="218">c</text>
<text class="small" x="30" y="28">impulse 1-2-3-4-5</text>
<text class="small" x="476" y="262">correction a-b-c</text>
</svg>
<figcaption>A trend moves in five waves (1, 3, 5 push; 2, 4 pull back), then corrects in three (a, b, c).</figcaption>
</figure>

The engine only accepts a count that keeps the three hard rules:

- **Wave 2** never goes beyond the start of wave 1 (point 0).
- **Wave 3** is never the shortest of waves 1, 3 and 5.
- **Wave 4** does not enter wave 1's price range (it stays above point 1 in an up-move).

The same shape upside down is a falling impulse. The **degree** (minor, intermediate, major)
is how big the swings are that count as waves: a minor wave 1 can be one small part of an
intermediate wave 1.

### 2. EW5: the end of the move, trade the reversal

<figure class="ew-fig">
<svg viewBox="0 0 640 310" role="img" aria-label="EW5 reversal setup with STOP, TRIGGER, W4 and Fibonacci levels">
<polyline class="wave" points="30,286 110,196 160,240 280,100 340,154 410,64"/>
<polyline class="next" points="410,64 460,150 490,128 540,176"/>
<rect class="down" x="406" y="64" width="8" height="18" rx="1"/>
<line class="lvl stop" x1="395" y1="64" x2="630" y2="64"/><text class="ltxt stop" x="470" y="56">STOP · W5 end</text>
<line class="lvl trig" x1="395" y1="82" x2="630" y2="82"/><text class="ltxt trig" x="470" y="102">TRIGGER</text>
<line class="lvl tgt" x1="330" y1="154" x2="630" y2="154"/><text class="ltxt tgt" x="556" y="146">W4 end</text>
<line class="lvl fib" x1="30" y1="175" x2="630" y2="175"/><text class="ltxt fib" x="580" y="194">0.5</text>
<line class="lvl fib" x1="30" y1="200" x2="630" y2="200"/><text class="ltxt fib" x="572" y="219">0.618</text>
<line class="lvl fib" x1="30" y1="252" x2="630" y2="252"/><text class="ltxt fib" x="572" y="271">0.854</text>
<text class="lbl" x="22" y="306">0</text><text class="lbl" x="96" y="184">1</text><text class="lbl" x="150" y="268">2</text>
<text class="lbl" x="270" y="88">3</text><text class="lbl" x="332" y="182">4</text><text class="lbl" x="380" y="52">5</text>
<text class="small" x="30" y="26">bullish impulse → SHORT</text>
</svg>
<figcaption>Wave 5 of a rising impulse is in place. TRIGGER is the low of the wave-5 bar: a close below it is the entry. Above STOP (the wave-5 end) the idea is wrong: wave 5 extended. W4 end is the first objective, FIB 0.5 the second (Fibonacci levels of the whole impulse 0 → 5); below 0.854 it is no longer a correction.</figcaption>
</figure>

- **Stage WAVE5_IN_PROGRESS**: wave 5's high is the latest swing; nothing has turned yet.
- **Status after the signal**: *TRIGGERED* (closed beyond TRIGGER), *EXTENDED* (went beyond
  STOP first: wave 5 was not finished) or *NOT_TRIGGERED* (neither within the horizon).
- A falling impulse is the mirror image: **LONG**, TRIGGER at the wave-5 bar's high.

### 3. EW3: wave 2 is over, trade wave 3

<figure class="ew-fig">
<svg viewBox="0 0 640 320" role="img" aria-label="EW3 setup with the wave-2 zone, TRIGGER, STOP and wave-3 targets">
<rect class="zone" x="200" y="222" width="430" height="44"/>
<text class="ltxt fib" x="486" y="262">wave-2 zone</text>
<polyline class="wave" points="60,290 200,180 260,246"/>
<polyline class="next" points="260,246 320,178 350,196 430,68"/>
<rect class="up" x="256" y="234" width="8" height="12" rx="1"/>
<line class="lvl trig" x1="240" y1="234" x2="630" y2="234"/><text class="ltxt trig" x="300" y="226">TRIGGER</text>
<line class="lvl stop" x1="240" y1="246" x2="630" y2="246"/><text class="ltxt stop" x="300" y="266">STOP · W2 end</text>
<line class="lvl fib" x1="40" y1="290" x2="630" y2="290"/><text class="ltxt fib" x="466" y="310">W0 · invalid below</text>
<line class="lvl tgt" x1="190" y1="180" x2="630" y2="180"/><text class="ltxt tgt" x="500" y="172">W1 end</text>
<line class="lvl tgt" x1="300" y1="136" x2="630" y2="136"/><text class="ltxt tgt" x="470" y="128">W3 1.0 × W1</text>
<line class="lvl tgt" x1="300" y1="68" x2="630" y2="68"/><text class="ltxt tgt" x="456" y="60">W3 1.618 × W1</text>
<text class="lbl" x="50" y="314">0</text><text class="lbl" x="188" y="168">1</text><text class="lbl" x="250" y="276">2</text>
<text class="lbl" x="414" y="58">3</text>
<text class="small" x="30" y="26">waves 1 and 2 up → LONG</text>
</svg>
<figcaption>Wave 1 is done and wave 2 has pulled back 38.2–78.6% of it (the shaded zone) without passing point 0. TRIGGER is the high of the wave-2 bar: a close above it is the entry; below STOP wave 2 was not over. Wave 3 is usually the longest: 1.0 × wave 1 is the minimum, 1.618 the classic target (2.618 for strong moves).</figcaption>
</figure>

- **Context AFTER_WAVE5**: wave 1 starts where an EW5 reversal ended. It is the second, more
  confirmed entry into the same turn.
- **Context AFTER_ABC**: wave 1 starts where an a-b-c correction ended: the old trend resumes.
- **Stage WAVE3_CONFIRMED**: price has already closed above W1 end; later, with a wider stop.

### 4. Higher-timeframe alignment

<figure class="ew-fig">
<svg viewBox="0 0 640 270" role="img" aria-label="Aligned versus against the higher timeframe">
<rect x="10" y="10" width="300" height="250" rx="10" fill="none" stroke="currentColor" stroke-opacity="0.15"/>
<rect x="330" y="10" width="300" height="250" rx="10" fill="none" stroke="currentColor" stroke-opacity="0.15"/>
<text class="lbl" x="24" y="40">ALIGNED</text><text class="lbl" x="344" y="40">AGAINST</text>
<text class="small" x="24" y="66">1D falling</text><text class="small" x="344" y="66">1D rising</text>
<polyline points="24,84 90,108 150,102 220,160 296,210" fill="none" stroke="#e66767" stroke-width="3"/>
<polyline class="wave" points="150,200 175,178 187,188 212,150 226,162 246,138"/>
<text class="small" x="120" y="246">60m: 5 waves up</text><text class="ltxt trig" x="214" y="128">SHORT ✓</text>
<polyline points="344,212 410,188 470,196 540,132 616,84" fill="none" stroke="#2fbf71" stroke-width="3"/>
<polyline class="wave" points="460,200 485,178 497,188 522,150 536,162 556,138"/>
<text class="small" x="440" y="246">60m: 5 waves up</text><text class="ltxt stop" x="430" y="118">SHORT ✗</text>
</svg>
<figcaption>The same 60m wave-5 SHORT. On the left the daily trend is down (below its EMA 55), so the small rally was only a bounce and the reversal goes with the bigger move: ALIGNED. On the right the daily trend is up: the SHORT fights it: AGAINST.</figcaption>
</figure>

Each signal is tagged from the timeframes above it: 60m → 4hr and 1D, 4hr → 1D and 1W,
1D → 1W. **ALIGNED** means every one of them points the way of the trade, **AGAINST** that
the next one up points the other way, **MIXED** anything in between. In the backtest the
ALIGNED group reached its targets more often; the stop rate changed little, so the stop and
position size still decide the loss on a trade.
