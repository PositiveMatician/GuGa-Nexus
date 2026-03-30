package com.example.myapplication;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;
import android.os.IBinder;
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

    private final BroadcastReceiver activityReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String action = intent.getAction();
            if (action == null) return;

            switch (action) {
                case "com.example.myapplication.UPDATE_IP":
                    backendAddress = intent.getStringExtra("ip");
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
            }
            Log.d(TAG, "Received broadcast: " + action);
        }
    };

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
        registerReceiver(activityReceiver, filter, Context.RECEIVER_EXPORTED);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public void onInit(int status) {
        if (status == TextToSpeech.SUCCESS) tts.setLanguage(Locale.US);
    }

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

    private void sendCommandToBackend(String command) {
        if (backendAddress.isEmpty()) return;
        String url = "http://" + backendAddress + "/api/command";
        try {
            JSONObject json = new JSONObject();
            json.put("command", command);
            RequestBody body = RequestBody.create(json.toString(), MediaType.parse("application/json"));
            Request request = new Request.Builder().url(url).post(body).build();
            HTTP_CLIENT.newCall(request).enqueue(new Callback() {
                @Override public void onFailure(Call call, IOException e) {
                    Log.e(TAG, "Failed to send command", e);
                }
                @Override public void onResponse(Call call, Response response) {
                    Log.d(TAG, "Command sent, response: " + response.code());
                    response.close();
                }
            });
        } catch (JSONException ignored) {}
    }

    private void connectWebSocket() {
        if (backendAddress.isEmpty()) return;
        try {
            if (mSocket != null) mSocket.disconnect();
            mSocket = IO.socket("http://" + backendAddress);
            mSocket.on(Socket.EVENT_CONNECT, args -> sendBroadcast(new Intent("com.example.myapplication.SOCKET_CONNECTED")));
            mSocket.on("guga_response", args -> {
                if (args.length > 0 && args[0] instanceof JSONObject) {
                    try {
                        String message = ((JSONObject) args[0]).getString("message");
                        Log.d(TAG, "Socket message received: " + message);
                        Intent intent = new Intent("com.example.myapplication.GUGA_RESPONSE");
                        intent.putExtra("message", message);
                        sendBroadcast(intent);
                        if (ttsEnabled && tts != null) {
                            tts.speak(message, TextToSpeech.QUEUE_FLUSH, null, null);
                        } else {
                            showResponseNotification(message);
                        }
                    } catch (JSONException ignored) {}
                }
            });
            mSocket.connect();
        } catch (URISyntaxException ignored) {}
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel serviceChannel = new NotificationChannel(
                    CHANNEL_ID, "GuGa Channel", NotificationManager.IMPORTANCE_LOW);
            
            NotificationChannel responseChannel = new NotificationChannel(
                    RESPONSE_CHANNEL_ID, "GuGa Replies", NotificationManager.IMPORTANCE_HIGH);
            responseChannel.setDescription("Alerts when GuGa replies via text");

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

    @Override
    public void onDestroy() {
        if (tts != null) { tts.stop(); tts.shutdown(); }
        if (mSocket != null) mSocket.disconnect();
        unregisterReceiver(activityReceiver);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}