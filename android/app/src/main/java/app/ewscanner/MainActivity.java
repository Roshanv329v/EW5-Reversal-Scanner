package app.ewscanner;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * The whole app is one WebView. Python (the desktop engine plus mobile/) runs a small
 * server on 127.0.0.1 inside this process; the page talks to it. Java only adds what a
 * page cannot do on its own: picking a file, sharing a CSV, the back button, and the
 * background notification while a long job runs (JobService).
 */
public class MainActivity extends Activity {
    static final String EXTRA_TAB = "open_tab";
    private static final int PICK_STOCK_CSV = 41;
    private String pendingTab;
    private boolean pageReady;
    private static final String BG = "#0e1117";
    private WebView web;
    private TextView splash;
    private PyObject server;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        App.init(getApplicationContext());
        pendingTab = getIntent().getStringExtra(EXTRA_TAB);
        getWindow().setStatusBarColor(Color.parseColor(BG));
        getWindow().setNavigationBarColor(Color.parseColor(BG));

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor(BG));
        root.setOnApplyWindowInsetsListener((v, insets) -> {        // keep clear of status / navigation bars
            int top, bottom, left, right;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
                top = bars.top; bottom = bars.bottom; left = bars.left; right = bars.right;
            } else {
                top = insets.getSystemWindowInsetTop(); bottom = insets.getSystemWindowInsetBottom();
                left = insets.getSystemWindowInsetLeft(); right = insets.getSystemWindowInsetRight();
            }
            v.setPadding(left, top, right, bottom);
            return insets;
        });

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor(BG));
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(false);
        ws.setAllowContentAccess(false);
        ws.setTextZoom(100);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                pageReady = true;
                openPendingTab();
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri uri = req.getUrl();
                if ("127.0.0.1".equals(uri.getHost())) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); } catch (ActivityNotFoundException ignored) { }
                return true;                                       // other links open in the browser
            }
        });
        web.addJavascriptInterface(new Bridge(), "Android");
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) WebView.setWebContentsDebuggingEnabled(true);
        root.addView(web);

        splash = new TextView(this);
        splash.setText("Starting the Elliott Wave engine…");
        splash.setTextColor(Color.parseColor("#c3c6cf"));
        splash.setTextSize(16);
        splash.setGravity(Gravity.CENTER);
        splash.setBackgroundColor(Color.parseColor(BG));
        root.addView(splash);
        setContentView(root);

        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 7);
        }

        new Thread(() -> {
            try {
                if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                server = Python.getInstance().getModule("mobile.server");
                String url = server.callAttr("start", getFilesDir().getAbsolutePath(), 0).toString();
                Scheduler.reschedule(getApplicationContext());           // alerts schedule (settings written by Python)
                runOnUiThread(() -> {
                    web.loadUrl(url);
                    splash.animate().alpha(0f).setDuration(250).withEndAction(() -> splash.setVisibility(View.GONE));
                });
            } catch (Throwable e) {
                runOnUiThread(() -> splash.setText("Could not start Python:\n" + e));
            }
        }, "python-start").start();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String tab = intent.getStringExtra(EXTRA_TAB);
        if (tab != null) { pendingTab = tab; if (pageReady) openPendingTab(); }
    }

    private void openPendingTab() {
        if (pendingTab == null || web == null) return;
        String tab = pendingTab.replaceAll("[^a-z0-9]", "");
        pendingTab = null;
        web.evaluateJavascript("window.showTab && showTab('" + tab + "')", null);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web == null) { super.onBackPressed(); return; }
        web.evaluateJavascript("window.appBack ? window.appBack() : false", value -> {
            if (!"true".equals(value)) moveTaskToBack(true);      // keep Python (and any job) alive
        });
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != PICK_STOCK_CSV || result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        Toast.makeText(this, "Copying the file…", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            try {
                File target = new File(server.callAttr("import_target").toString());
                try (InputStream in = getContentResolver().openInputStream(uri); OutputStream out = new FileOutputStream(target)) {
                    byte[] buf = new byte[1 << 16];
                    int n;
                    while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                }
                runOnUiThread(() -> web.evaluateJavascript("window.onImportReady && window.onImportReady()", null));
            } catch (Throwable e) {
                String msg = String.valueOf(e.getMessage()).replace("'", " ");
                runOnUiThread(() -> web.evaluateJavascript("window.onImportFailed && window.onImportFailed('" + msg + "')", null));
            }
        }, "import-copy").start();
    }

    /** The phone maker's own "auto-start" screen, where one exists (Xiaomi, Oppo, Vivo, ...). */
    private Intent autostartIntent() {
        String[][] screens = {
                {"com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"},
                {"com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"},
                {"com.coloros.safecenter", "com.coloros.safecenter.startupapp.StartupAppListActivity"},
                {"com.oplus.safecenter", "com.oplus.safecenter.permission.startup.StartupAppListActivity"},
                {"com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"},
                {"com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity"},
                {"com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"},
                {"com.asus.mobilemanager", "com.asus.mobilemanager.entry.FunctionActivity"},
                {"com.letv.android.letvsafe", "com.letv.android.letvsafe.AutobootManageActivity"},
        };
        for (String[] s : screens) {
            Intent i = new Intent().setComponent(new android.content.ComponentName(s[0], s[1]));
            if (getPackageManager().resolveActivity(i, android.content.pm.PackageManager.MATCH_DEFAULT_ONLY) != null) return i;
        }
        return null;
    }

    /** Called from the page as window.Android.* */
    private class Bridge {
        @JavascriptInterface
        public void pickStockCsv() {
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType("*/*");
            i.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"text/csv", "text/comma-separated-values", "text/plain", "application/octet-stream"});
            runOnUiThread(() -> startActivityForResult(i, PICK_STOCK_CSV));
        }

        /** {"exact": alarms on time, "battery": app is battery-optimised, "notifications": allowed} */
        @JavascriptInterface
        public String alertStatus() {
            android.app.AlarmManager am = (android.app.AlarmManager) getSystemService(ALARM_SERVICE);
            android.os.PowerManager pm = (android.os.PowerManager) getSystemService(POWER_SERVICE);
            android.app.NotificationManager nm = (android.app.NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            boolean exact = Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms();
            boolean battery = !pm.isIgnoringBatteryOptimizations(getPackageName());
            boolean notes = Build.VERSION.SDK_INT < 24 || nm.areNotificationsEnabled();
            android.net.ConnectivityManager cm = (android.net.ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
            boolean dataSaver = Build.VERSION.SDK_INT >= 24 && cm.getRestrictBackgroundStatus()
                    == android.net.ConnectivityManager.RESTRICT_BACKGROUND_STATUS_ENABLED;
            String maker = Build.MANUFACTURER == null ? "" : Build.MANUFACTURER.toLowerCase(java.util.Locale.ROOT);
            return "{\"exact\":" + exact + ",\"battery\":" + battery + ",\"notifications\":" + notes
                    + ",\"data_saver\":" + dataSaver + ",\"maker\":\"" + maker.replaceAll("[^a-z0-9 ]", "") + "\""
                    + ",\"autostart\":" + (autostartIntent() != null) + "}";
        }

        @JavascriptInterface
        public void testScheduleIn(int minutes) { Scheduler.testIn(Math.max(1, Math.min(30, minutes))); }

        @JavascriptInterface
        public void openSetting(String which) {
            Intent i;
            Uri pkg = Uri.parse("package:" + getPackageName());
            if ("autostart".equals(which) && autostartIntent() != null) i = autostartIntent();
            else if ("app".equals(which)) i = new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS, pkg);
            else if ("data".equals(which) && Build.VERSION.SDK_INT >= 24) i = new Intent(android.provider.Settings.ACTION_IGNORE_BACKGROUND_DATA_RESTRICTIONS_SETTINGS, pkg);
            else if ("battery".equals(which)) i = new Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, pkg);
            else if ("exact".equals(which) && Build.VERSION.SDK_INT >= 31) i = new Intent(android.provider.Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, pkg);
            else if (Build.VERSION.SDK_INT >= 26) i = new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, getPackageName());
            else i = new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS, pkg);
            runOnUiThread(() -> { try { startActivity(i); } catch (Exception ignored) { } });
        }

        @JavascriptInterface
        public void shareResult(String name) {
            File file = new File(new File(getFilesDir(), "results"), new File(name).getName());
            if (!file.exists()) return;
            Uri uri = ResultsProvider.uriFor(MainActivity.this, file);
            Intent send = new Intent(Intent.ACTION_SEND);
            send.setType("text/csv");
            send.putExtra(Intent.EXTRA_STREAM, uri);
            send.putExtra(Intent.EXTRA_SUBJECT, file.getName());
            send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            runOnUiThread(() -> startActivity(Intent.createChooser(send, "Share " + file.getName())));
        }
    }
}
