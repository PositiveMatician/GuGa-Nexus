package com.example.myapplication;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.os.Build;
import android.os.IBinder;
import android.provider.Settings;
import android.speech.tts.TextToSpeech;
import android.util.Log;

import androidx.core.app.NotificationCompat;
import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.net.URISyntaxException;
import java.security.GeneralSecurityException;
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
    private static final String ENCRYPTED_PREFS_NAME = "guga_secure_prefs";
    private static final String KEY_AUTH_TOKEN = "auth_token";
    private static final OkHttpClient HTTP_CLIENT = new OkHttpClient();

    private Socket mSocket;
    private String backendAddress = "";
    private TextToSpeech tts;
    private boolean ttsEnabled = true;

    // ----------------------------------------------------------------
    // Device Identity & Token Storage
    // ----------------------------------------------------------------

    /** Returns the stable Android device ID (unique per app signing). */
    String fetchAndroidId() {
        return Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
    }

    /** Securely persists the pairing token. */
    void saveAuthToken(String token) {
        SecurityUtils.saveAuthToken(this, token);
        Log.d(TAG, "Auth token saved securely.");
    }

    /** Retrieves the stored auth token, or null if not paired yet. */
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
                case "com.example.myapplication.UPDATE_IP":
                    backendAddress = intent.getStringExtra("ip");
                    Log.d(TAG, "IP updated to: " + backendAddress);
                    break;
                case "com.example.myapplication.PING_BACKEND":
                    pingBackend();
                    break;
                case "com.example.myapplication.CONNECT_SOCKET":
                    connectWebSocket();
                    break;
                case "com.example.myapplication.SEND_MANUAL_COMMAND":
                    sendCommandToBackend(intent.getStringExtra("command"));
                    break;
                case "com.example.myapplication.SET_TTS_ENABLED":
                    ttsEnabled = intent.getBooleanExtra("enabled", true);
                    break;
                case "com.example.myapplication.SAVE_AUTH_TOKEN":
                    String token = intent.getStringExtra("token");
                    if (token != null) saveAuthToken(token);
                    break;
            }
            Log.d(TAG, "Received broadcast: " + action);
        }
    };

    // ----------------------------------------------------------------
    // Lifecycle
    // ----------------------------------------------------------------

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        startForeground(1, buildNotification("Ready"));

        tts = new TextToSpeech(this, this);
        backendAddress = getSharedPreferences("AlphaPrefs", MODE_PRIVATE).getString("backend_ip", "");
        ttsEnabled = getSharedPreferences("AlphaPrefs", MODE_PRIVATE).getBoolean("tts_enabled", true);

        IntentFilter filter = new IntentFilter();
        filter.addAction("com.example.myapplication.UPDATE_IP");
        filter.addAction("com.example.myapplication.PING_BACKEND");
        filter.addAction("com.example.myapplication.CONNECT_SOCKET");
        filter.addAction("com.example.myapplication.SEND_MANUAL_COMMAND");
        filter.addAction("com.example.myapplication.SET_TTS_ENABLED");
        filter.addAction("com.example.myapplication.SAVE_AUTH_TOKEN");
        registerReceiver(activityReceiver, filter, Context.RECEIVER_EXPORTED);

        String storedToken = getAuthToken();
        Log.d(TAG, "GuGaService started. Device ID: " + fetchAndroidId()
                + " | Token present: " + (storedToken != null));

        // Auto-connect if IP is present
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
        Request request = new Request.Builder().url("http://" + backendAddress + "/").build();
        HTTP_CLIENT.newCall(request).enqueue(new Callback() {
            @Override
            public void onFailure(Call call, IOException e) {
                broadcastPing(false);
            }
            @Override
            public void onResponse(Call call, Response response) {
                Log.d(TAG, "Ping response: " + response.code());
                broadcastPing(response.isSuccessful());
                response.close();
            }
        });
    }

    private void broadcastPing(boolean success) {
        Intent intent = new Intent("com.example.myapplication.PING_RESULT");
        intent.putExtra("success", success);
        sendBroadcast(intent);
    }

    private void sendCommandToBackend(String commandText) {
        if (backendAddress.isEmpty()) return;

        String authToken = getAuthToken();
        String deviceId = fetchAndroidId();

        if (authToken == null) {
            Log.e(TAG, "No auth token — cannot send encrypted command. Please re-pair.");
            return;
        }

        // Build plaintext payload
        String plaintext;
        try {
            JSONObject phraseObj = new JSONObject();
            phraseObj.put("phrase", commandText);
            plaintext = phraseObj.toString();
        } catch (JSONException e) {
            Log.e(TAG, "Failed to build command JSON", e);
            return;
        }

        // Prefer socket if connected
        if (mSocket != null && mSocket.connected()) {
            try {
                JSONObject encrypted = CryptoUtils.encrypt(plaintext, authToken);
                encrypted.put("device_id", deviceId);
                Log.d(TAG, "Sending encrypted command via socket");
                mSocket.emit("command", encrypted);
            } catch (Exception e) {
                Log.e(TAG, "Socket encryption/send failed", e);
            }
            return;
        }

        // HTTP fallback — encrypted
        String url = "http://" + backendAddress + "/api/command";
        try {
            JSONObject encrypted = CryptoUtils.encrypt(plaintext, authToken);
            encrypted.put("device_id", deviceId);
            RequestBody body = RequestBody.create(encrypted.toString(), MediaType.parse("application/json"));
            Request request = new Request.Builder().url(url).post(body).build();
            HTTP_CLIENT.newCall(request).enqueue(new Callback() {
                @Override public void onFailure(Call call, IOException e) {
                    Log.e(TAG, "HTTP command send failed", e);
                }
                @Override public void onResponse(Call call, Response response) {
                    Log.d(TAG, "HTTP command sent, response: " + response.code());
                    response.close();
                }
            });
        } catch (Exception e) {
            Log.e(TAG, "HTTP encryption/send failed", e);
        }
    }

    private void connectWebSocket() {
        if (backendAddress.isEmpty()) return;
        try {
            if (mSocket != null) mSocket.disconnect();

            // Pass device_id and auth_token as query parameters for server identification
            String deviceId = fetchAndroidId();
            String authToken = getAuthToken();

            IO.Options opts = new IO.Options();
            opts.query = "device_id=" + deviceId + (authToken != null ? "&token=" + authToken : "");
            Log.d(TAG, "Connecting socket with device_id=" + deviceId + " token_present=" + (authToken != null));

            mSocket = IO.socket("http://" + backendAddress, opts);
            mSocket.on(Socket.EVENT_CONNECT, args -> sendBroadcast(new Intent("com.example.myapplication.SOCKET_CONNECTED")));
            mSocket.on(Socket.EVENT_DISCONNECT, args -> sendBroadcast(new Intent("com.example.myapplication.SOCKET_DISCONNECTED")));
            mSocket.on("guga_response", args -> {
                if (args.length > 0 && args[0] instanceof JSONObject) {
                    try {
                        JSONObject payload = (JSONObject) args[0];
                        String currentToken = getAuthToken();
                        String message;

                        // Try to decrypt; if token missing or decryption fails, fall back to plain
                        if (currentToken != null && payload.has("iv") && payload.has("ciphertext")) {
                            String decryptedJson = CryptoUtils.decrypt(payload, currentToken);
                            message = new JSONObject(decryptedJson).getString("message");
                            Log.d(TAG, "Decrypted socket message: " + message);
                        } else {
                            message = payload.getString("message");
                            Log.d(TAG, "Plain socket message: " + message);
                        }

                        Intent intent = new Intent("com.example.myapplication.GUGA_RESPONSE");
                        intent.putExtra("message", message);
                        sendBroadcast(intent);
                        if (ttsEnabled && tts != null) {
                            tts.speak(message, TextToSpeech.QUEUE_FLUSH, null, null);
                        } else {
                            showResponseNotification(message);
                        }
                    } catch (Exception e) {
                        Log.e(TAG, "Failed to process guga_response", e);
                    }
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
            responseChannel.setDescription("Alerts when GuGu replies via text");

            NotificationManager nm = getSystemService(NotificationManager.class);
            nm.createNotificationChannel(serviceChannel);
            nm.createNotificationChannel(responseChannel);
        }
    }

    private void showResponseNotification(String message) {
        Notification notification = new NotificationCompat.Builder(this, RESPONSE_CHANNEL_ID)
                .setContentTitle("GuGu")
                .setContentText(message)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .build();

        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm != null) nm.notify(2, notification);
    }

    private Notification buildNotification(String content) {
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("GuGa")
                .setContentText(content)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .build();
    }

    // ----------------------------------------------------------------
    // Cleanup
    // ----------------------------------------------------------------

    @Override
    public void onDestroy() {
        if (tts != null) { tts.stop(); tts.shutdown(); }
        if (mSocket != null) mSocket.disconnect();
        unregisterReceiver(activityReceiver);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}