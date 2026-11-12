"""
Phone version of the Elliott Wave scanner.

The desktop engine and core modules run unchanged; this package only adds what the
phone needs instead of Streamlit:

    server.py  small HTTP server on 127.0.0.1 that the app's WebView talks to
    api.py     the dashboard, data, run and guide logic of app.py, as JSON endpoints
    jobs.py    one background job at a time (data update, screener run) with progress
    fetch.py   Yahoo download without yfinance (parallel, same data shape)
    scan.py    run_engine one group of tickers at a time, to keep memory low
    web/       the page: tabs, dashboards, tables and Plotly charts
"""
