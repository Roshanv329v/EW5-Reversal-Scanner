package app.ewscanner;

import android.content.Context;

/** Application context for code that Python calls (JobService.update). */
final class App {
    private static Context context;

    private App() { }

    static void init(Context c) { context = c.getApplicationContext(); }

    static Context get() { return context; }
}
