package app.ewscanner;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Calendar;

/**
 * Wakes the app at the times set in the Alerts tab (files/data/alert_settings.json, written by
 * mobile/alerts.py). Only the next time is set; each alarm sets the one after it. Exact,
 * idle-proof alarms, so the scan runs on time with the screen off.
 */
public final class Scheduler {
    private Scheduler() { }

    /** Called by Python after the settings change, by the app at start, after a reboot or an update. */
    public static void reschedule() {
        Context c = App.get();
        if (c != null) reschedule(c);
    }

    static void reschedule(Context c) {
        long at = next(c, System.currentTimeMillis());
        set(c, 0, at);
        log(c, at > 0 ? "next scan set for " + stamp(at) : "scheduled scans off");
    }

    /** A one-off scan in `minutes` (Alerts tab: "Test with the phone locked"). */
    public static void testIn(int minutes) {
        Context c = App.get();
        if (c == null) return;
        long at = System.currentTimeMillis() + minutes * 60_000L;
        set(c, 1, at);
        log(c, "test scan set for " + stamp(at));
    }

    /**
     * Alarm-clock alarms (setAlarmClock) are the kind Android and phone makers are least likely
     * to delay or drop while the phone is locked or in deep sleep; they show the alarm icon.
     */
    private static void set(Context c, int code, long at) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        PendingIntent pi = PendingIntent.getBroadcast(c, code, new Intent(c, AlarmReceiver.class),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        am.cancel(pi);
        if (at <= 0) return;
        if (Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms()) {
            PendingIntent show = PendingIntent.getActivity(c, 10 + code,
                    new Intent(c, MainActivity.class).putExtra(MainActivity.EXTRA_TAB, "alerts"),
                    PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            am.setAlarmClock(new AlarmManager.AlarmClockInfo(at, show), pi);
        } else {
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);          // may run a few minutes late
        }
    }

    static String stamp(long at) {
        return new java.text.SimpleDateFormat("EEE dd MMM HH:mm", java.util.Locale.ENGLISH).format(new java.util.Date(at));
    }

    /** files/data/alarm_log.txt: what the scheduler did (shown in the Alerts tab). */
    static void log(Context c, String what) {
        try {
            File f = new File(new File(c.getFilesDir(), "data"), "alarm_log.txt");
            f.getParentFile().mkdirs();
            String line = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss", java.util.Locale.ENGLISH)
                    .format(new java.util.Date()) + "  " + what + "\n";
            String old = f.exists() ? new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8) : "";
            String[] lines = (old + line).split("\n");
            int from = Math.max(0, lines.length - 60);                     // keep the last 60 lines
            StringBuilder sb = new StringBuilder();
            for (int i = from; i < lines.length; i++) if (!lines[i].isEmpty()) sb.append(lines[i]).append("\n");
            Files.write(f.toPath(), sb.toString().getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) { }
    }

    /** Next scheduled time in milliseconds, or 0 when alerts are off. Same rule as alerts.next_runs. */
    static long next(Context c, long now) {
        try {
            File f = new File(new File(c.getFilesDir(), "data"), "alert_settings.json");
            if (!f.exists()) return 0;
            JSONObject s = new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
            if (!s.optBoolean("enabled", false)) return 0;
            JSONArray days = s.getJSONArray("days"), times = s.getJSONArray("times");
            for (int offset = 0; offset < 15; offset++) {
                Calendar day = Calendar.getInstance();
                day.setTimeInMillis(now);
                day.add(Calendar.DAY_OF_YEAR, offset);
                int iso = (day.get(Calendar.DAY_OF_WEEK) + 5) % 7 + 1;          // Monday = 1 ... Sunday = 7
                boolean on = false;
                for (int i = 0; i < days.length(); i++) on |= days.getInt(i) == iso;
                if (!on) continue;
                long best = Long.MAX_VALUE;
                for (int i = 0; i < times.length(); i++) {
                    String[] hm = times.getString(i).split(":");
                    Calendar t = (Calendar) day.clone();
                    t.set(Calendar.HOUR_OF_DAY, Integer.parseInt(hm[0]));
                    t.set(Calendar.MINUTE, Integer.parseInt(hm[1]));
                    t.set(Calendar.SECOND, 0);
                    t.set(Calendar.MILLISECOND, 0);
                    if (t.getTimeInMillis() > now) best = Math.min(best, t.getTimeInMillis());
                }
                if (best != Long.MAX_VALUE) return best;
            }
        } catch (Exception ignored) { }
        return 0;
    }

    /** The alarm: set the next one, then run the scan in the background service. */
    public static class AlarmReceiver extends BroadcastReceiver {
        @Override
        public void onReceive(Context c, Intent intent) {
            App.init(c);
            log(c, "alarm fired: starting the scan");
            reschedule(c);
            Intent run = new Intent(c, JobService.class).setAction(JobService.ACTION_SCHEDULED);
            try {
                if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(run); else c.startService(run);
            } catch (RuntimeException e) {
                log(c, "could not start the scan: " + e);
            }
        }
    }

    /** After a reboot or an app update, alarms are gone: set the next one again. */
    public static class BootReceiver extends BroadcastReceiver {
        @Override
        public void onReceive(Context c, Intent intent) {
            App.init(c);
            log(c, "phone restarted or app updated");
            reschedule(c);
        }
    }
}
