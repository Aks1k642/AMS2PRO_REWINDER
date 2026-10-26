package io.github.ams2rewinder;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.net.Uri;
import android.view.View;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

/** Offline material calculator + optional PC/LAN bridge. Does not directly drive AMS. */
public class MainActivity extends Activity {
    private WebView web;
    private EditText address;
    private TextView label;

    private static boolean privateV4(String host) {
        if (host == null || !host.matches("\\d{1,3}(\\.\\d{1,3}){3}")) return false;
        String[] items=host.split("\\.");
        int[] b=new int[4];
        try { for(int i=0;i<4;i++){b[i]=Integer.parseInt(items[i]); if(b[i]>255)return false;} }catch(Exception e){return false;}
        return b[0]==10 || b[0]==127 || (b[0]==192 && b[1]==168) || (b[0]==172 && b[1]>=16 && b[1]<=31);
    }
    private static boolean allowed(String url) {
        if(url.startsWith("file:///android_asset/")) return true;
        try { Uri uri=Uri.parse(url); return "http".equals(uri.getScheme()) && privateV4(uri.getHost()) && uri.getPort()>=1024 && uri.getPort()<=65535; }
        catch(Exception e) { return false; }
    }
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().setStatusBarColor(Color.rgb(21,19,25));getWindow().setNavigationBarColor(Color.rgb(21,19,25));
        LinearLayout layout=new LinearLayout(this);layout.setOrientation(LinearLayout.VERTICAL);layout.setBackgroundColor(Color.rgb(21,19,25));
        LinearLayout toolbar=new LinearLayout(this);toolbar.setOrientation(LinearLayout.HORIZONTAL);toolbar.setPadding(10,10,10,10);
        address=new EditText(this);address.setSingleLine(true);address.setTextColor(Color.WHITE);address.setHintTextColor(0xffa99ba5);address.setTextSize(12);address.setHint("http://IP_ПК:8899/#token=...");
        toolbar.addView(address,new LinearLayout.LayoutParams(0,55,1));
        Button open=new Button(this);open.setText("LAN");toolbar.addView(open);
        Button offline=new Button(this);offline.setText("Офлайн");toolbar.addView(offline);
        layout.addView(toolbar);
        web=new WebView(this); web.setBackgroundColor(Color.rgb(16,16,21));
        WebSettings settings=web.getSettings();settings.setJavaScriptEnabled(true);settings.setDomStorageEnabled(true);settings.setAllowFileAccess(true);settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request){
                if(!allowed(request.getUrl().toString())){Toast.makeText(MainActivity.this,"Разрешён только адрес домашнего моста с портом 1024–65535",Toast.LENGTH_LONG).show();return true;}return false;
            }
        });
        layout.addView(web,new LinearLayout.LayoutParams(-1,0,1));setContentView(layout);
        web.loadUrl("file:///android_asset/index.html");
        offline.setOnClickListener(v->web.loadUrl("file:///android_asset/index.html"));
        open.setOnClickListener(v->{String url=address.getText().toString().trim();if(!allowed(url)){Toast.makeText(this,"Вставь полный адрес из окна Windows, включая #token=",Toast.LENGTH_LONG).show();return;}web.loadUrl(url);});
    }
    @Override public void onBackPressed(){ if(web.canGoBack())web.goBack();else super.onBackPressed(); }
}
