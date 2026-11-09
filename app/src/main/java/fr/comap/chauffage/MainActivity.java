package fr.comap.chauffage;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.net.Uri;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.DisplayCutout;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.chaquo.python.Python;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * Écran unique sans barre de titre : une WebView affiche la page servie par le code Python (127.0.0.1),
 * et un formulaire de réglages s'affiche au premier lancement (puis via l'icône d'engrenage de la page).
 * Les réglages sont conservés dans les préférences privées de l'application (aucun fichier utilisateur).
 */
public class MainActivity extends Activity {
    private static final String PREFS = "comap";
    private static final String[] KEYS = {"email", "password", "serial", "zone", "lat", "lon", "off_in", "off_sp"};
    private static final String[] LABELS = {
            "E-mail du compte Comap", "Mot de passe Comap", "Numéro de série du thermostat",
            "Identifiant de zone (facultatif)", "Latitude (pour la météo)", "Longitude (pour la météo)",
            "Correction température intérieure (°C)", "Correction consigne (°C)"};
    private static final String[] DEFAULTS = {"", "", "", "", "47.8736", "-3.5486", "0.5", "0.5"};

    private WebView web;
    private ScrollView form;
    private TextView message;
    private TextView loading;
    private Button cancel;
    private boolean night;
    private int bg, ink, muted;
    private final EditText[] fields = new EditText[KEYS.length];
    private int generation = 0;
    private boolean pageLoaded = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        night = (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        // mêmes couleurs que la page : pas de flash blanc au démarrage, barres système fondues dans le fond
        bg = night ? Color.parseColor("#0F1416") : Color.parseColor("#EEF1F0");
        ink = night ? Color.parseColor("#E8ECEE") : Color.parseColor("#1B2326");
        muted = night ? Color.parseColor("#93A2A8") : Color.parseColor("#5F6E74");
        getWindow().setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(bg));
        getWindow().setStatusBarColor(bg);
        getWindow().setNavigationBarColor(bg);
        if (Build.VERSION.SDK_INT >= 28) {
            // l'application utilise aussi la zone de l'encoche en paysage (plus de bande noire sur le côté)
            WindowManager.LayoutParams wlp = getWindow().getAttributes();
            wlp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            getWindow().setAttributes(wlp);
        }

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(bg);
        // marges : barres système et encoche
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int l = insets.getSystemWindowInsetLeft(), t = insets.getSystemWindowInsetTop();
            int r = insets.getSystemWindowInsetRight(), b = insets.getSystemWindowInsetBottom();
            if (Build.VERSION.SDK_INT >= 28) {
                DisplayCutout c = insets.getDisplayCutout();
                if (c != null) {
                    l = Math.max(l, c.getSafeInsetLeft()); t = Math.max(t, c.getSafeInsetTop());
                    r = Math.max(r, c.getSafeInsetRight()); b = Math.max(b, c.getSafeInsetBottom());
                }
            }
            v.setPadding(l, t, r, b);
            return insets;
        });
        setContentView(root);

        web = new WebView(this);
        web.setBackgroundColor(bg);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        web.setLongClickable(false);
        web.setHapticFeedbackEnabled(false);
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setBuiltInZoomControls(false);
        ws.setSupportZoom(false);
        web.addJavascriptInterface(new Object() {
            @JavascriptInterface
            public void openSettings() {
                runOnUiThread(() -> showForm("Réglages (l'application redémarre quand vous enregistrez)."));
            }
        }, "Android");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if ("127.0.0.1".equals(uri.getHost())) return false;
                startActivity(new Intent(Intent.ACTION_VIEW, uri));  // lien externe (Open-Meteo...) : navigateur
                return true;
            }
        });
        web.setVisibility(View.GONE);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        loading = new TextView(this);
        loading.setText("Démarrage…");
        loading.setTextColor(muted);
        loading.setTextSize(16);
        loading.setVisibility(View.GONE);
        root.addView(loading, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));

        form = buildForm();
        form.setVisibility(View.GONE);
        root.addView(form, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        applySystemBars();
        if (isConfigured()) startBackend(); else showForm("Renseignez vos identifiants Comap pour commencer.");
    }

    /** Pas de barre de titre ; en paysage, la barre d'état est masquée pour laisser toute la hauteur au graphique. */
    private void applySystemBars() {
        boolean land = getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE;
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = getWindow().getInsetsController();
            if (c == null) return;
            if (land) c.hide(WindowInsets.Type.statusBars()); else c.show(WindowInsets.Type.statusBars());
            c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            int light = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
            c.setSystemBarsAppearance(night ? 0 : light, light);
        } else {
            int f = View.SYSTEM_UI_FLAG_LAYOUT_STABLE;
            if (!night) {
                f |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
                if (Build.VERSION.SDK_INT >= 26) f |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            }
            getWindow().getDecorView().setSystemUiVisibility(f);
            if (land) getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
            else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        }
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        applySystemBars();
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private boolean isConfigured() {
        SharedPreferences p = prefs();
        return !p.getString("email", "").isEmpty() && !p.getString("password", "").isEmpty()
                && !(p.getString("serial", "").isEmpty() && p.getString("zone", "").isEmpty());
    }

    private ScrollView buildForm() {
        float d = getResources().getDisplayMetrics().density;
        int pad = (int) (20 * d);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("Réglages");
        title.setTextSize(26);
        title.setTextColor(ink);
        col.addView(title);

        message = new TextView(this);
        message.setTextSize(14);
        message.setTextColor(muted);
        message.setPadding(0, pad / 4, 0, pad / 2);
        col.addView(message);

        SharedPreferences p = prefs();
        for (int i = 0; i < KEYS.length; i++) {
            TextView label = new TextView(this);
            label.setText(LABELS[i]);
            label.setTextSize(13);
            label.setTextColor(muted);
            label.setPadding(0, pad / 2, 0, 0);
            col.addView(label);
            EditText e = new EditText(this);
            e.setSingleLine(true);
            e.setTextColor(ink);
            e.setText(p.getString(KEYS[i], DEFAULTS[i]));
            if (i == 0) e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS);
            else if (i == 1) e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            else if (i >= 4) e.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL | InputType.TYPE_NUMBER_FLAG_SIGNED);
            else e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
            fields[i] = e;
            col.addView(e);
        }

        Button save = new Button(this);
        save.setText("Enregistrer et démarrer");
        save.setOnClickListener(v -> {
            SharedPreferences.Editor ed = prefs().edit();
            for (int i = 0; i < KEYS.length; i++) ed.putString(KEYS[i], fields[i].getText().toString().trim());
            ed.apply();
            startBackend();
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = pad;
        col.addView(save, lp);

        cancel = new Button(this);
        cancel.setText("Annuler");
        cancel.setOnClickListener(v -> closeForm());
        cancel.setVisibility(View.GONE);
        col.addView(cancel);

        TextView note = new TextView(this);
        note.setText("Les identifiants restent sur ce téléphone (stockage privé de l'application) et ne sont envoyés qu'à Comap.");
        note.setTextSize(12);
        note.setTextColor(muted);
        note.setPadding(0, pad, 0, 0);
        col.addView(note);

        ScrollView sv = new ScrollView(this);
        sv.setBackgroundColor(bg);
        sv.setFillViewport(true);
        sv.addView(col);
        return sv;
    }

    private void closeForm() {
        form.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
    }

    private void showForm(String text) {
        message.setText(text);
        loading.setVisibility(View.GONE);
        cancel.setVisibility(pageLoaded ? View.VISIBLE : View.GONE);
        web.setVisibility(View.GONE);
        form.setVisibility(View.VISIBLE);
    }

    /** Démarre (ou redémarre) le serveur Python puis charge la page. */
    private void startBackend() {
        final int gen = ++generation;
        pageLoaded = false;
        form.setVisibility(View.GONE);
        web.setVisibility(View.GONE);
        loading.setVisibility(View.VISIBLE);
        final SharedPreferences p = prefs();
        new Thread(() -> {
            try {
                JSONObject cfg = new JSONObject();
                for (int i = 0; i < KEYS.length; i++) cfg.put(KEYS[i], p.getString(KEYS[i], DEFAULTS[i]));
                int port = Python.getInstance().getModule("comap_android").callAttr("start", cfg.toString()).toInt();
                runOnUiThread(() -> {
                    if (gen != generation) return;
                    loading.setVisibility(View.GONE);
                    web.setVisibility(View.VISIBLE);
                    web.loadUrl("http://127.0.0.1:" + port + "/");
                    pageLoaded = true;
                });
            } catch (JSONException | RuntimeException e) {
                runOnUiThread(() -> {
                    if (gen != generation) return;
                    showForm("Démarrage impossible : " + e.getMessage());
                });
            }
        }).start();
    }

    @Override
    protected void onResume() {
        super.onResume();
        // au retour dans l'application : actualisation immédiate des données (le minuteur de la page peut avoir été suspendu)
        if (pageLoaded) web.evaluateJavascript("if (typeof loop === 'function') loop();", null);
    }

    @Override
    public void onBackPressed() {
        if (form.getVisibility() == View.VISIBLE && pageLoaded) {
            closeForm();
        } else {
            super.onBackPressed();
        }
    }
}
