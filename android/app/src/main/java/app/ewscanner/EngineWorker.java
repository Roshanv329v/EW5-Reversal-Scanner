package app.ewscanner;

import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.IBinder;
import android.os.Process;

/**
 * One EW5 / EW3 worker: a service in its OWN process (W0 ... W5 in AndroidManifest.xml, each
 * with android:process=":w0" ...), so it gets its own Python and its own CPU core.
 * mobile/workers.py writes task_k.pkl, starts the workers with startAll() and collects
 * out_k.pkl; this class only runs mobile.workers.work(task) and ends the process.
 */
public class EngineWorker extends Service {
    static final String EXTRA_TASK = "task";
    private static final Class<?>[] SLOTS = {W0.class, W1.class, W2.class, W3.class, W4.class, W5.class};

    /** Called from Python: start n workers on folder/task_k.pkl; returns how many started. */
    public static int startAll(String folder, int n) {
        Context c = App.get();
        if (c == null) return 0;
        int started = 0;
        for (int k = 0; k < Math.min(n, SLOTS.length); k++) {
            try {
                c.startService(new Intent(c, SLOTS[k]).putExtra(EXTRA_TASK, folder + "/task_" + k + ".pkl"));
                started++;
            } catch (RuntimeException e) {                 // e.g. background start not allowed
                break;
            }
        }
        return started;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        final String task = intent == null ? null : intent.getStringExtra(EXTRA_TASK);
        if (task == null) { stopSelf(); return START_NOT_STICKY; }
        App.init(getApplicationContext());
        new Thread(() -> {
            try {
                if (!com.chaquo.python.Python.isStarted()) {
                    com.chaquo.python.Python.start(new com.chaquo.python.android.AndroidPlatform(getApplicationContext()));
                }
                com.chaquo.python.Python.getInstance().getModule("mobile.workers").callAttr("work", task);
            } catch (Throwable e) {
                try {                                       // tell the main process; it runs these parts itself
                    java.io.File f = new java.io.File(task);
                    String k = f.getName().replace("task_", "").replace(".pkl", "");
                    java.nio.file.Files.write(new java.io.File(f.getParentFile(), "error_" + k).toPath(),
                            String.valueOf(e).getBytes(java.nio.charset.StandardCharsets.UTF_8));
                } catch (Exception ignored) { }
            }
            stopSelf();
            Process.killProcess(Process.myPid());           // give the memory back at once
        }, "ew-worker").start();
        return START_NOT_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    public static class W0 extends EngineWorker { }
    public static class W1 extends EngineWorker { }
    public static class W2 extends EngineWorker { }
    public static class W3 extends EngineWorker { }
    public static class W4 extends EngineWorker { }
    public static class W5 extends EngineWorker { }
}
