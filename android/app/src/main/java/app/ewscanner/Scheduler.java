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
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        PendingIntent pi = PendingIntent.getBroadcast(c, 0, new Intent(c, AlarmReceiver.class),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        am.cancel(pi);
        long at = next(c, System.currentTimeMillis());
        if (at <= 0) return;
        if (Build.VERSION.SDK_INT >= 31 && !am.canScheduleExactAlarms()) {
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);          // may run a few minutes late
        } else {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
        }
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
            reschedule(c);
            Intent run = new Intent(c, JobService.class).setAction(JobService.ACTION_SCHEDULED);
            if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(run); else c.startService(run);
        }
    }

    /** After a reboot or an app update, alarms are gone: set the next one again. */
    public static class BootReceiver extends BroadcastReceiver {
        @Override
        public void onReceive(Context c, Intent intent) {
            App.init(c);
            reschedule(c);
        }
    }
}
