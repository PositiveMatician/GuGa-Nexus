package com.example.myapplication;

import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.util.Log;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

import io.socket.client.IO;
import io.socket.client.Socket;
import io.socket.emitter.Emitter;

import java.io.IOException;
import java.net.URISyntaxException;
import java.util.Locale;

import org.json.JSONException;
import org.json.JSONObject;

import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;

public class VoiceAssistantService extends Service implements WakeWordDetector.WakeWordListener {

    private static final String CHANNEL_ID = "VoiceAssistantChannel";
    private static final int NOTIFICATION_ID = 1;
    
    private WakeWordDetector wakeWordDetector;
    private AudioRecord audioRecord;
    private Thread audioThread;
    private boolean isListening = false;
    private SpeechRecognizer speechRecognizer;
    private Intent recognizerIntent;
    private String backendIp = "";
    private Socket mSocket;
    private TextToSpeech tts;
    private OkHttpClient httpClient = new OkHttpClient();
    
    private static final int SAMPLE_RATE = 16000;
    private static final int CHUNK_SIZE = 1280; // 80ms

    private final android.content.BroadcastReceiver actionReceiver = new android.content.BroadcastReceiver() {
        @Override
        public void onReceive(android.content.Context context, Intent intent) {
            if ("com.example.myapplication.UPDATE_THRESHOLD".equals(intent.getAction())) {
                float threshold = intent.getFloatExtra("threshold", 0.05f);
                if (wakeWordDetector != null) {
                    wakeWordDetector.setThreshold(threshold);
                }
            } else if ("com.example.myapplication.SWITCH_MODEL".equals(intent.getAction())) {
                String modelFileName = intent.getStringExtra("model_file");
                if (wakeWordDetector != null && modelFileName != null) {
                    wakeWordDetector.switchWakeWordModel(context, modelFileName);
                }
            } else if ("com.example.myapplication.SIMULATE_WAKE_WORD".equals(intent.getAction())) {
                new Handler(Looper.getMainLooper()).post(() -> onWakeWordDetected());
            } else if ("com.example.myapplication.UPDATE_IP".equals(intent.getAction())) {
                backendIp = intent.getStringExtra("ip");
                if (backendIp == null) backendIp = "";
                Log.d("Assistant", "Backend IP updated to: " + backendIp);
                // No longer auto-connecting Socket.IO here
            } else if ("com.example.myapplication.CONNECT_SOCKET".equals(intent.getAction())) {
                connectWebSocket();
            } else if ("com.example.myapplication.PING_BACKEND".equals(intent.getAction())) {
                pingBackend();
            } else if ("com.example.myapplication.SEND_MANUAL_COMMAND".equals(intent.getAction())) {
                String command = intent.getStringExtra("command");
                if (command != null && !command.trim().isEmpty()) {
                    sendCommandToBackend(command);
                }
            } else if ("com.example.myapplication.TOGGLE_LISTENING".equals(intent.getAction())) {
                boolean state = intent.getBooleanExtra("state", false);
                if (state) {
                    startForeground(NOTIFICATION_ID, createNotification());
                    startWakeWordListening();
                } else {
                    stopWakeWordListening();
                    stopForeground(true);
                }
            }
        }
    };

    private Notification createNotification() {
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("Assistant Active")
                .setContentText("Listening for commands...")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    private void stopWakeWordListening() {
        isListening = false;
        if (audioRecord != null) {
            try {
                if (audioRecord.getState() == AudioRecord.STATE_INITIALIZED) {
                    audioRecord.stop();
                }
                audioRecord.release();
            } catch (Exception e) {
                Log.e("Assistant", "Error stopping AudioRecord", e);
            }
            audioRecord = null;
        }
        Log.d("Assistant", "Microphone released. Wake word engine sleeping.");
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        wakeWordDetector = new WakeWordDetector(this, this);
        initSpeechRecognizer();
        initTTS();
    }

    private void initTTS() {
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                tts.setLanguage(Locale.US);
            }
        });
    }

    private void connectWebSocket() {
        if (backendIp.isEmpty()) return;
        
        if (mSocket != null) {
            mSocket.disconnect();
            mSocket.off();
        }

        try {
            String url = "http://" + sanitizeIp(backendIp) + ":6769";
            Log.d("Assistant", "Connecting to Socket.IO at " + url);
            mSocket = IO.socket(url);

            mSocket.on(Socket.EVENT_CONNECT, args -> {
                Log.d("Assistant", "Socket connected");
                Intent connectedIntent = new Intent("com.example.myapplication.SOCKET_CONNECTED");
                sendBroadcast(connectedIntent);
                
                // Also ask server for a status update just in case
                mSocket.emit("request_status", new JSONObject());
            });
            mSocket.on(Socket.EVENT_DISCONNECT, args -> {
                Log.d("Assistant", "Socket disconnected");
                Intent disconnectedIntent = new Intent("com.example.myapplication.SOCKET_DISCONNECTED");
                sendBroadcast(disconnectedIntent);
            });
            mSocket.on("jarvis_response", args -> {
                if (args.length > 0 && args[0] instanceof JSONObject) {
                    JSONObject response = (JSONObject) args[0];
                    try {
                        String message = response.getString("message");
                        Log.d("Assistant", "Jarvis says: " + message);
                        
                        // Speak it
                        if (tts != null) {
                            tts.speak(message, TextToSpeech.QUEUE_FLUSH, null, null);
                        }

                        // Broadcast to UI
                        Intent intent = new Intent("com.example.myapplication.JARVIS_RESPONSE");
                        intent.putExtra("message", message);
                        sendBroadcast(intent);
                        
                    } catch (JSONException e) {
                        Log.e("Assistant", "Error parsing jarvis_response", e);
                    }
                }
            });

            mSocket.connect();
        } catch (URISyntaxException e) {
            Log.e("Assistant", "Socket connection error", e);
        }
    }

    private void initSpeechRecognizer() {
        new Handler(Looper.getMainLooper()).post(() -> {
            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this);
            recognizerIntent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            recognizerIntent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);

            speechRecognizer.setRecognitionListener(new RecognitionListener() {
                @Override
                public void onReadyForSpeech(Bundle params) {
                    Log.d("Assistant", "SpeechRecognizer is ready and listening...");
                }

                @Override
                public void onBeginningOfSpeech() {}

                @Override
                public void onRmsChanged(float rmsdB) {}

                @Override
                public void onBufferReceived(byte[] buffer) {}

                @Override
                public void onEndOfSpeech() {}

                @Override
                public void onError(int error) {
                    Log.e("Assistant", "SpeechRecognizer error: " + error);
                    Intent intent = new Intent("com.example.myapplication.COMMAND_TRANSCRIBED");
                    intent.putExtra("command", "Error: " + error);
                    sendBroadcast(intent);
                    startWakeWordListening();
                }

                @Override
                public void onResults(Bundle results) {
                    java.util.ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    if (matches != null && !matches.isEmpty()) {
                        String recognizedText = matches.get(0);
                        Log.d("Assistant", "COMMAND TRANSCRIBED: " + recognizedText);
                        Intent intent = new Intent("com.example.myapplication.COMMAND_TRANSCRIBED");
                        intent.putExtra("command", recognizedText);
                        sendBroadcast(intent);
                        sendCommandToBackend(recognizedText);
                    }
                    startWakeWordListening();
                }

                @Override
                public void onPartialResults(Bundle partialResults) {}

                @Override
                public void onEvent(int eventType, Bundle params) {}
            });
        });
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            CharSequence name = "Voice Assistant Service";
            int importance = NotificationManager.IMPORTANCE_LOW;
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID, name, importance);
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(NOTIFICATION_ID, createNotification());
        startWakeWordListening();

        android.content.IntentFilter filter = new android.content.IntentFilter();
        filter.addAction("com.example.myapplication.UPDATE_THRESHOLD");
        filter.addAction("com.example.myapplication.SWITCH_MODEL");
        filter.addAction("com.example.myapplication.SIMULATE_WAKE_WORD");
        filter.addAction("com.example.myapplication.UPDATE_IP");
        filter.addAction("com.example.myapplication.PING_BACKEND");
        filter.addAction("com.example.myapplication.CONNECT_SOCKET");
        filter.addAction("com.example.myapplication.SEND_MANUAL_COMMAND");
        filter.addAction("com.example.myapplication.TOGGLE_LISTENING");
        androidx.core.content.ContextCompat.registerReceiver(this, actionReceiver,
                filter,
                androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED);

        return START_STICKY;
    }

    @SuppressLint("MissingPermission")
    private void startWakeWordListening() {
        if (isListening) return;

        int bufferSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, 
                AudioFormat.CHANNEL_IN_MONO, 
                AudioFormat.ENCODING_PCM_16BIT);

        if (bufferSize == AudioRecord.ERROR || bufferSize == AudioRecord.ERROR_BAD_VALUE) {
            bufferSize = SAMPLE_RATE * 2;
        }

        audioRecord = new AudioRecord(MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                Math.max(bufferSize, CHUNK_SIZE * 2));

        if (audioRecord.getState() != AudioRecord.STATE_INITIALIZED) {
            Log.e("Assistant", "AudioRecord initialization failed");
            return;
        }

        audioRecord.startRecording();
        isListening = true;

        audioThread = new Thread(() -> {
            // Pre-allocate array outside the loop as requested
            short[] audioBuffer = new short[CHUNK_SIZE];
            
            while (isListening) {
                int bytesRead = audioRecord.read(audioBuffer, 0, audioBuffer.length);
                if (bytesRead == audioBuffer.length) {
                    if (wakeWordDetector != null) {
                        wakeWordDetector.processAudioChunk(audioBuffer);
                    }
                }
            }
        });
        audioThread.start();
    }

    @Override
    public void onWakeWordDetected() {
        Log.d("Assistant", "WAKE WORD DETECTED: JARVIS!");
        Intent intent = new Intent("com.example.myapplication.WAKE_WORD_DETECTED");
        sendBroadcast(intent);

        isListening = false;
        
        new Handler(Looper.getMainLooper()).post(() -> {
            if (audioRecord != null) {
                try {
                    audioRecord.stop();
                    audioRecord.release();
                } catch (Exception e) {
                    e.printStackTrace();
                }
                audioRecord = null;
            }
            if (speechRecognizer != null) {
                speechRecognizer.startListening(recognizerIntent);
            }
        });
    }

    private void pingBackend() {
        if (backendIp == null || backendIp.trim().isEmpty()) {
            Intent intent = new Intent("com.example.myapplication.PING_RESULT");
            intent.putExtra("success", false);
            sendBroadcast(intent);
            return;
        }

        String cleanIp = sanitizeIp(backendIp);
        String url = "http://" + cleanIp + ":6769/ping";
        Log.d("Assistant", "Attempting to ping URL: " + url);
        Request request = new Request.Builder().url(url).build();
        httpClient.newCall(request).enqueue(new Callback() {
            @Override
            public void onFailure(Call call, IOException e) {
                Log.e("Assistant", "Ping failed", e);
                Intent intent = new Intent("com.example.myapplication.PING_RESULT");
                intent.putExtra("success", false);
                sendBroadcast(intent);
            }

            @Override
            public void onResponse(Call call, Response response) throws IOException {
                boolean success = response.isSuccessful();
                Log.d("Assistant", "Ping success: " + success);
                Intent intent = new Intent("com.example.myapplication.PING_RESULT");
                intent.putExtra("success", success);
                sendBroadcast(intent);
                response.close();
            }
        });
    }

    private void sendCommandToBackend(String command) {
        if (mSocket != null && mSocket.connected()) {
            try {
                JSONObject json = new JSONObject();
                json.put("phrase", command);
                Log.d("Assistant", "Emitting command via Socket.IO: " + command);
                mSocket.emit("command", json);
            } catch (JSONException e) {
                Log.e("Assistant", "Error creating JSON for command", e);
            }
        } else {
            Log.d("Assistant", "Socket not connected. Falling back to OkHttp POST.");
            if (backendIp == null || backendIp.trim().isEmpty()) {
                Log.e("Assistant", "Cannot send command: backendIp is empty");
                return;
            }

            String cleanIp = sanitizeIp(backendIp);
            String url = "http://" + cleanIp + ":6769/api/command";
            
            try {
                JSONObject jsonBody = new JSONObject();
                jsonBody.put("command", command);
                
                okhttp3.MediaType JSON = okhttp3.MediaType.parse("application/json; charset=utf-8");
                okhttp3.RequestBody body = okhttp3.RequestBody.create(JSON, jsonBody.toString());

                Request request = new Request.Builder()
                        .url(url)
                        .post(body)
                        .build();
                
                httpClient.newCall(request).enqueue(new Callback() {
                    @Override
                    public void onFailure(Call call, IOException e) {
                        Log.e("Assistant", "Fallback sendCommand failed", e);
                    }
                    @Override
                    public void onResponse(Call call, Response response) {
                        Log.d("Assistant", "Fallback sendCommand result: " + response.isSuccessful());
                        response.close();
                    }
                });
            } catch (Exception e) {
                Log.e("Assistant", "Error creating JSON for fallback command", e);
            }
        }
    }

    private String sanitizeIp(String ip) {
        String cleanIp = ip.trim();
        if (cleanIp.startsWith("http://")) {
            cleanIp = cleanIp.substring(7);
        } else if (cleanIp.startsWith("https://")) {
            cleanIp = cleanIp.substring(8);
        }
        if (cleanIp.contains(":")) {
            cleanIp = cleanIp.split(":")[0];
        }
        if (cleanIp.endsWith("/")) {
            cleanIp = cleanIp.substring(0, cleanIp.length() - 1);
        }
        return cleanIp;
    }

    @Override
    public void onDestroy() {
        isListening = false;
        
        if (audioThread != null) {
            try {
                audioThread.join(500);
            } catch (InterruptedException e) {
                e.printStackTrace();
            }
        }
        
        if (audioRecord != null) {
            try {
                audioRecord.stop();
            } catch (IllegalStateException e) {
                e.printStackTrace();
            }
            audioRecord.release();
        }
        
        if (wakeWordDetector != null) {
            wakeWordDetector.close();
        }
        
        if (speechRecognizer != null) {
            new Handler(Looper.getMainLooper()).post(() -> {
                speechRecognizer.destroy();
            });
        }
        
        if (mSocket != null) {
            mSocket.disconnect();
            mSocket.off();
        }

        if (tts != null) {
            tts.stop();
            tts.shutdown();
        }

        unregisterReceiver(actionReceiver);
        
        super.onDestroy();
    }
}
