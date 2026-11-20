package app.ewscanner;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import org.json.JSONArray;

/** The day's alert notification. Called from Python (mobile/alerts.py). */
public final class Notifier {
    static final String CHANNEL = "alerts";
    private static final int ID = 2;                 // the whole day in one notification, updated through the day
    private static final int SHOWN = 7;

    private Notifier() { }

    static final String EXTRA_RUN = "run_scan";
    private static final int DUE_ID = 5;

    /** A scheduled scan that Android would not start in the background: one tap starts it. */
    static void scanDue(Context c, String kind) {
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        channel(nm);
        Intent open = new Intent(c, MainActivity.class).putExtra(MainActivity.EXTRA_TAB, "alerts")
                .putExtra(EXTRA_RUN, kind == null ? "regular" : kind)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(c, DUE_ID, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
        String text = "Android blocked it in the background. Tap to run it now; in the Alerts tab allow "
                + "Alarms & reminders and set Battery to Unrestricted so it starts by itself.";
        nm.notify(DUE_ID, b.setContentTitle("⏰ Scheduled " + ("full".equals(kind) ? "full scan" : "scan") + " is due: tap to run")
                .setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text))
                .setSmallIcon(R.drawable.ic_stat).setAutoCancel(true).setContentIntent(pi).build());
    }

    private static void channel(NotificationManager nm) {
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "Signal alerts", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("Stocks triggered or set up today, found by the scheduled scans");
            nm.createNotificationChannel(ch);
        }
    }

    public static void show(String title, String linesJson) {
        show(title, linesJson, ID);
    }

    /** id: 2 the whole day, 3 Triggered, 4 New setups (separate notifications, each updated through the day). */
    public static void show(String title, String linesJson, int id) {
        Context c = App.get();
        if (c == null) return;
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        channel(nm);
        String[] lines;
        try {
            JSONArray a = new JSONArray(linesJson);
            lines = new String[a.length()];
            for (int i = 0; i < a.length(); i++) lines[i] = a.getString(i);
        } catch (Exception e) {
            lines = new String[]{linesJson};
        }
        Notification.InboxStyle inbox = new Notification.InboxStyle().setBigContentTitle(title);
        for (int i = 0; i < Math.min(SHOWN, lines.length); i++) inbox.addLine(lines[i]);
        if (lines.length > SHOWN) inbox.setSummaryText("+" + (lines.length - SHOWN) + " more in the Alerts tab");

        Intent open = new Intent(c, MainActivity.class).putExtra(MainActivity.EXTRA_TAB, "alerts")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(c, id, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, CHANNEL) : new Notification.Builder(c);
        nm.notify(id, b.setContentTitle(title)
                .setContentText(lines.length > 0 ? lines[0] : "")
                .setStyle(inbox)
                .setSmallIcon(R.drawable.ic_stat)
                .setAutoCancel(true)
                .setContentIntent(pi)
                .build());
    }
}
