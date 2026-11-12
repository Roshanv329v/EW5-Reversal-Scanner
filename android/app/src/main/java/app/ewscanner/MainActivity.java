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
    private static final int PICK_STOCK_CSV = 41;
    private static final String BG = "#0e1117";
    private WebView web;
    private TextView splash;
    private PyObject server;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        App.init(getApplicationContext());
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
