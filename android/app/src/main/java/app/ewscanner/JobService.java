package app.ewscanner;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

/**
 * Keeps the app alive while a long job (data download, screener run) is working, so it
 * finishes even with the screen off or the app in the background. Python calls
 * update(true, text) when a job starts or makes progress and update(false, "") at the end.
 */
public class JobService extends Service {
    static final String ACTION_SCHEDULED = "app.ewscanner.SCHEDULED_SCAN";
    private static final String CHANNEL = "jobs";
    private static final int ID = 1;
    private static volatile String text = "Working…";
    private static volatile JobService running;
    private PowerManager.WakeLock lock;

    /** Called from Python (mobile/jobs.py) on its own thread. */
    public static void update(boolean running, String message) {
        Context c = App.get();
        if (c == null) return;
        Intent i = new Intent(c, JobService.class);
        try {
            if (running) {
                text = message == null || message.isEmpty() ? "Working…" : message;
                JobService live = JobService.running;
                if (live != null) {                                   // already in the foreground: new text only
                    ((NotificationManager) c.getSystemService(NOTIFICATION_SERVICE)).notify(ID, live.build());
                } else if (Build.VERSION.SDK_INT >= 26) {
                    c.startForegroundService(i);
                } else {
                    c.startService(i);
                }
            } else {
                c.stopService(i);
            }
        } catch (RuntimeException ignored) {                          // e.g. not allowed from the background
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        App.init(this);
        boolean scheduled = intent != null && ACTION_SCHEDULED.equals(intent.getAction());
        if (scheduled) text = "Scheduled scan: starting…";
        Notification n = build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        else startForeground(ID, n);
        running = this;
        if (lock == null) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            lock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ewscanner:job");
            lock.acquire(6 * 60 * 60 * 1000L);                    // safety cap: 6 hours
        }
        if (scheduled) runScheduled();
        return START_NOT_STICKY;
    }

    /** Start Python if the app was closed, then mobile.server.scheduled(); the job stops this service. */
    private void runScheduled() {
        new Thread(() -> {
            try {
                if (!com.chaquo.python.Python.isStarted()) {
                    com.chaquo.python.Python.start(new com.chaquo.python.android.AndroidPlatform(getApplicationContext()));
                }
                com.chaquo.python.Python.getInstance().getModule("mobile.server")
                        .callAttr("scheduled", getFilesDir().getAbsolutePath());
            } catch (Throwable e) {
                update(false, "");
            }
        }, "scheduled-scan").start();
    }

    private Notification build() {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Downloads and scans", NotificationManager.IMPORTANCE_LOW));
        }
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        return b.setContentTitle("Elliott Wave Scanner")
                .setContentText(text)
                .setSmallIcon(R.drawable.ic_stat)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setContentIntent(open)
                .build();
    }

    @Override
    public void onDestroy() {
        running = null;
        if (lock != null && lock.isHeld()) lock.release();
        lock = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
