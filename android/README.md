# EW Scanner for Android

The full scanner on the phone, with no computer or server: EW5 and EW3 dashboards, Data,
Run / Backtest and User Guide tabs, like the desktop app. Only the price download needs
internet.

`dist/EWScanner-1.0.apk` is the last release build (not in git).

## How it is built

Streamlit cannot run on Android (it needs `pyarrow`, which has no Android build), so the app
keeps every Python part of the desktop and only replaces Streamlit's page:

```
desktop files, synced in on every build        core/*, elliott_wave*_screener.py, stock_data.py,
(not copied by hand)                            config.yaml, docs/*.md, data/tickers.csv
app/src/main/python/mobile/
  server.py    HTTP server on 127.0.0.1 inside the app (session token on every request)
  api.py       app.py's dashboard, data, run and guide logic as JSON (same core calls)
  store.py     stock.csv as 16 part files, so memory stays at one part (~0.6 GB peak)
  scan.py      run_engine part by part (same rows as one run; tested)
  fetch.py     Yahoo download without yfinance, 6 requests in parallel
  jobs.py      one background job at a time, with progress
  web/         the page: tabs, filters, stat cards, Plotly charts, tables
app/src/main/java/app/ewscanner/
  MainActivity.java    one WebView; starts Python; back button; file import; share CSV
  JobService.java      notification + wake lock while a download or run is working
  ResultsProvider.java shares results/*.csv with other apps
```

The charts are `core/charts.py` figures sent as Plotly JSON, so they are the desktop charts.
On a phone held upright the signal chart moves its legend under the chart and shortens the
level labels; turned sideways it is the desktop layout.

| Desktop | Phone | Why |
|---|---|---|
| TA-Lib | `core/ta_lite.py` | No Android build of the TA-Lib C library. Same formulas, checked against TA-Lib. |
| yfinance | `mobile/fetch.py` | yfinance needs a native HTTP library with no Android build. Same Yahoo data. |
| pandas 3 / numpy 2 | pandas 2.1.3 / numpy 1.26.2 | Versions Chaquopy ships for Android. All tests pass on both. |
| one stock.csv | 16 part files | Memory. Same format; Data → Import stock.csv splits a desktop file. |

## Build

Needs JDK 17 and the Android SDK (platform 35, build-tools 34), with `local.properties`
pointing at the SDK (`sdk.dir=/opt/homebrew/share/android-commandlinetools`). From this folder:

```bash
JAVA_HOME=/opt/homebrew/opt/openjdk@17 ./gradlew assembleRelease
```

The signed APK lands in `app/build/outputs/apk/release/app-release.apk`.

**Signing key.** `keystore/ew-release.jks` and its passwords in `keystore.properties` were
created on this Mac and are not in git. Keep a private backup of both: every future update
of the app must be signed with the same key, or the phone refuses to install it over the old
one (you would have to uninstall, which deletes the app's data).

## Test the page on a desktop

The same page and API run on the Mac, against any folder that plays the app's storage:

```bash
PYTHONPATH=..:app/src/main/python python -m mobile.server --root /tmp/ewphone --port 8790
```

Open the printed address. `tests/test_mobile.py` checks that the phone code gives the
desktop's results.

## Install on a phone (arm64, Android 7 or newer)

Copy `dist/EWScanner-1.0.apk` to the phone and open it (allow "install unknown apps" for the
app you opened it from), or with USB debugging on:

```bash
/opt/homebrew/share/android-commandlinetools/platform-tools/adb install -r dist/EWScanner-1.0.apk
```

The proof-of-concept app (`app.ewscanner.poc`) is separate and can be uninstalled.
The phone section of the User Guide (`docs/phone_guide.md`) explains first start and daily use.
