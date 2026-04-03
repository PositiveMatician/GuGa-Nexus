package com.positive.guga;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import androidx.core.content.ContextCompat;
import android.provider.Settings;
import android.speech.tts.TextToSpeech;
import android.util.Log;

import androidx.core.app.NotificationCompat;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.net.URISyntaxException;
import java.util.Locale;

import io.socket.client.IO;
import io.socket.client.Socket;
import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

public class GuGaService extends Service implements TextToSpeech.OnInitListener {
    private static final String TAG = "GuGaAlpha";
    private static final String CHANNEL_ID = "GuGaServiceChannel";
    private static final String RESPONSE_CHANNEL_ID = "GuGaResponseChannel";
    private static final OkHttpClient HTTP_CLIENT = new OkHttpClient();

    private Socket mSocket;
    private String backendAddress = "";
    private TextToSpeech tts;
    private boolean ttsEnabled = true;
    private boolean isAppInForeground = false;

    // ----------------------------------------------------------------
    // Device Identity & Token Storage
    // ----------------------------------------------------------------

    String fetchAndroidId() {
        return Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
    }

    void saveAuthToken(String token) {
        SecurityUtils.saveAuthToken(this, token);
        Log.d(TAG, "Auth token saved securely.");
    }

    private String getAuthToken() {
        return SecurityUtils.getAuthToken(this);
    }

    // ----------------------------------------------------------------
    // Broadcast Receiver
    // ----------------------------------------------------------------

    private final BroadcastReceiver activityReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String action = intent.getAction();
            if (action == null) return;

            switch (action) {
                case "com.positive.guga.UPDATE_IP":
                    backendAddress = intent.getStringExtra("ip");
                    break;
                case "com.positive.guga.PING_BACKEND":
                    pingBackend();
                    break;
                case "com.positive.guga.CONNECT_SOCKET":
                    connectWebSocket();
                    break;
                case "com.positive.guga.SEND_MANUAL_COMMAND":
                    sendCommandToBackend(intent.getStringExtra("command"));
                    break;
                case "com.positive.guga.SET_TTS_ENABLED":
                    ttsEnabled = intent.getBooleanExtra("enabled", true);
                    break;
                case "com.positive.guga.SAVE_AUTH_TOKEN":
                    String token = intent.getStringExtra("token");
                    if (token != null) saveAuthToken(token);
                    break;
                case "com.positive.guga.SET_FOREGROUND":
                    isAppInForeground = intent.getBooleanExtra("isForeground", false);
                    Log.d(TAG, "App foreground state: " + isAppInForeground);
                    break;
            }
        }
    };

    // ----------------------------------------------------------------
    // Lifecycle
    // ----------------------------------------------------------------

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(1, buildNotification("Ready"), ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        } else {
            startForeground(1, buildNotification("Ready"));
        }

        tts = new TextToSpeech(this, this);
        backendAddress = getSharedPreferences("AlphaPrefs", MODE_PRIVATE).getString("backend_ip", "");
        ttsEnabled = getSharedPreferences("AlphaPrefs", MODE_PRIVATE).getBoolean("tts_enabled", true);

        IntentFilter filter = new IntentFilter();
        filter.addAction("com.positive.guga.UPDATE_IP");
        filter.addAction("com.positive.guga.PING_BACKEND");
        filter.addAction("com.positive.guga.CONNECT_SOCKET");
        filter.addAction("com.positive.guga.SEND_MANUAL_COMMAND");
        filter.addAction("com.positive.guga.SET_TTS_ENABLED");
        filter.addAction("com.positive.guga.SAVE_AUTH_TOKEN");
        filter.addAction("com.positive.guga.SET_FOREGROUND");
        ContextCompat.registerReceiver(this, activityReceiver, filter, ContextCompat.RECEIVER_EXPORTED);

        String storedToken = getAuthToken();
        if (!backendAddress.isEmpty() && storedToken != null) {
            connectWebSocket();
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public void onInit(int status) {
        if (status == TextToSpeech.SUCCESS) tts.setLanguage(Locale.US);
    }

    // ----------------------------------------------------------------
    // Networking
    // ----------------------------------------------------------------

    private void pingBackend() {
        if (backendAddress.isEmpty()) return;
        Request request = new Request.Builder().url(backendAddress + "/ping").build();
        HTTP_CLIENT.newCall(request).enqueue(new Callback() {
            @Override public void onFailure(Call call, IOException e) { broadcastPing(false); }
            @Override public void onResponse(Call call, Response response) {
                broadcastPing(response.isSuccessful());
                response.close();
            }
        });
    }

    private void broadcastPing(boolean success) {
        Intent intent = new Intent("com.positive.guga.PING_RESULT");
        intent.putExtra("success", success);
        sendBroadcast(intent);
    }

    private void sendCommandToBackend(String commandText) {
        if (backendAddress.isEmpty()) return;
        String authToken = getAuthToken();
        String deviceId = fetchAndroidId();
        if (authToken == null) return;

        String plaintext;
        try {
            JSONObject phraseObj = new JSONObject();
            phraseObj.put("phrase", commandText);
            plaintext = phraseObj.toString();
        } catch (JSONException e) { return; }

        if (mSocket != null && mSocket.connected()) {
            try {
                JSONObject encrypted = CryptoUtils.encrypt(plaintext, authToken);
                encrypted.put("device_id", deviceId);
                mSocket.emit("command", encrypted);
            } catch (Exception e) { Log.e(TAG, "Socket send failed", e); }
            return;
        }

        String url = backendAddress + "/api/command";
        try {
            JSONObject encrypted = CryptoUtils.encrypt(plaintext, authToken);
            encrypted.put("device_id", deviceId);
            RequestBody body = RequestBody.create(encrypted.toString(), MediaType.parse("application/json"));
            Request request = new Request.Builder().url(url).post(body).build();
            HTTP_CLIENT.newCall(request).enqueue(new Callback() {
                @Override public void onFailure(Call call, IOException e) {}
                @Override public void onResponse(Call call, Response response) { response.close(); }
            });
        } catch (Exception e) {}
    }

    private void connectWebSocket() {
        if (backendAddress.isEmpty()) return;
        try {
            if (mSocket != null) mSocket.disconnect();
            String deviceId = fetchAndroidId();
            String authToken = getAuthToken();

            IO.Options opts = new IO.Options();
            opts.query = "device_id=" + deviceId + (authToken != null ? "&token=" + authToken : "");

            mSocket = IO.socket(backendAddress, opts);
            mSocket.on(Socket.EVENT_CONNECT, args -> sendBroadcast(new Intent("com.positive.guga.SOCKET_CONNECTED")));
            mSocket.on(Socket.EVENT_DISCONNECT, args -> sendBroadcast(new Intent("com.positive.guga.SOCKET_DISCONNECTED")));
            mSocket.on("guga_response", args -> {
                if (args.length > 0 && args[0] instanceof JSONObject) {
                    try {
                        JSONObject payload = (JSONObject) args[0];
                        String currentToken = getAuthToken();
                        String message;
                        String title = null;

                        if (currentToken != null && payload.has("iv") && payload.has("ciphertext")) {
                            String decryptedJson = CryptoUtils.decrypt(payload, currentToken);
                            JSONObject decryptedObj = new JSONObject(decryptedJson);
                            message = decryptedObj.getString("message");
                            if (decryptedObj.has("title")) {
                                title = decryptedObj.getString("title");
                            }
                        } else {
                            message = payload.getString("message");
                            if (payload.has("title")) {
                                title = payload.getString("title");
                            }
                        }

                        Intent intent = new Intent("com.positive.guga.GUGA_RESPONSE");
                        intent.putExtra("message", message);
                        if (title != null) intent.putExtra("title", title);
                        sendBroadcast(intent);

                        // Also persist directly in case MainActivity is killed
                        ChatHistory.append(this, new ChatMessage(message, false));

                        if (ttsEnabled && tts != null) {
                            tts.speak(message, TextToSpeech.QUEUE_FLUSH, null, null);
                        } 
                        
                        if (!isAppInForeground) {
                            showResponseNotification(message, title);
                        }
                    } catch (Exception e) { Log.e(TAG, "Response process failed", e); }
                }
            });
            mSocket.connect();
        } catch (URISyntaxException ignored) {}
    }

    // ----------------------------------------------------------------
    // Notifications
    // ----------------------------------------------------------------

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel serviceChannel = new NotificationChannel(
                    CHANNEL_ID, "GuGa Channel", NotificationManager.IMPORTANCE_LOW);
            NotificationChannel responseChannel = new NotificationChannel(
                    RESPONSE_CHANNEL_ID, "GuGa Replies", NotificationManager.IMPORTANCE_HIGH);
            NotificationManager nm = getSystemService(NotificationManager.class);
            nm.createNotificationChannel(serviceChannel);
            nm.createNotificationChannel(responseChannel);
        }
    }

    private void showResponseNotification(String message, String title) {
        Intent intent = new Intent(this, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pendingIntent = PendingIntent.getActivity(this, 0, intent, 
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        String displayTitle = (title != null && !title.isEmpty()) ? title : "GuGa";

        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, RESPONSE_CHANNEL_ID)
                .setContentTitle(displayTitle)
                .setContentText(message)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setContentIntent(pendingIntent);

        if (ttsEnabled) {
            builder.setSilent(true);
        } else {
            builder.setDefaults(NotificationCompat.DEFAULT_ALL);
        }

        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm != null) nm.notify(2, builder.build());
    }

    private Notification buildNotification(String content) {
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("GuGa")
                .setContentText(content)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .build();
    }

    @Override
    public void onDestroy() {
        if (tts != null) { tts.stop(); tts.shutdown(); }
        if (mSocket != null) mSocket.disconnect();
        unregisterReceiver(activityReceiver);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}