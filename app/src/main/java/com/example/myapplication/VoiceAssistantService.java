package com.example.myapplication;

import android.annotation.SuppressLint;
import android.app.*;
import android.content.*;
import android.media.*;
import android.os.*;
import android.speech.*;
import android.speech.tts.TextToSpeech;
import android.util.Log;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;

import org.json.*;

import java.io.IOException;
import java.net.URISyntaxException;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import io.socket.client.IO;
import io.socket.client.Socket;
import okhttp3.*;

public class VoiceAssistantService extends Service implements WakeWordDetector.WakeWordListener {

    private static final String TAG = "VoiceAssistant";
    private static final String CHANNEL_ID = "VoiceAssistantChannel";
    private static final int NOTIFICATION_ID = 1;

    private static final int SAMPLE_RATE = 16000;
    private static final int CHUNK_SIZE = 1280;

    // ✅ Static OkHttpClient
    private static final OkHttpClient HTTP_CLIENT = new OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build();

    private WakeWordDetector wakeWordDetector;
    private AudioRecord audioRecord;
    private Thread audioThread;
    private final AtomicBoolean isListening = new AtomicBoolean(false);

    private SpeechRecognizer speechRecognizer;
    private Intent recognizerIntent;

    private Socket mSocket;
    private String backendAddress = "";

    private TextToSpeech tts;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private boolean receiverRegistered = false;
    /** True only when the listening toggle is ON. Gates TTS, STT, and wake word. */
    private boolean voiceEnabled = false;

    // -------------------- Broadcast Receiver --------------------

    private final BroadcastReceiver actionReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (intent == null || intent.getAction() == null)
                return;

            switch (intent.getAction()) {

                case "com.example.myapplication.TOGGLE_LISTENING":
                    boolean state = intent.getBooleanExtra("state", false);
                    voiceEnabled = state;
                    if (state) {
                        startForeground(NOTIFICATION_ID, createNotification("Listening..."));
                        startWakeWordListening();
                    } else {
                        stopWakeWordListening();
                        // Instead of stopping foreground completely, keep it alive for networking
                        // but with a different message.
                        startForeground(NOTIFICATION_ID, createNotification("Active (Silent Mode)"));

                        if (tts != null) tts.stop();
                        // Cancel any pending STT
                        if (speechRecognizer != null) {
                            mainHandler.post(() -> speechRecognizer.cancel());
                        }
                    }
                    break;

                case "com.example.myapplication.UPDATE_IP":
                    backendAddress = intent.getStringExtra("ip");
                    if (backendAddress == null)
                        backendAddress = "";
                    break;

                case "com.example.myapplication.CONNECT_SOCKET":
                    connectWebSocket();
                    break;

                case "com.example.myapplication.SEND_MANUAL_COMMAND":
                    String command = intent.getStringExtra("command");
                    if (command != null)
                        sendCommandToBackend(command);
                    break;

                case "com.example.myapplication.SIMULATE_WAKE_WORD":
                    mainHandler.post(VoiceAssistantService.this::onWakeWordDetected);
                    break;

                case "com.example.myapplication.PING_BACKEND":
                    pingBackend();
                    break;

                case "com.example.myapplication.UPDATE_THRESHOLD":
                    float threshold = intent.getFloatExtra("threshold", 0.05f);
                    if (wakeWordDetector != null)
                        wakeWordDetector.setThreshold(threshold);
                    break;

                case "com.example.myapplication.SWITCH_MODEL":
                    String modelFileName = intent.getStringExtra("model_file");
                    if (wakeWordDetector != null && modelFileName != null)
                        wakeWordDetector.switchWakeWordModel(context, modelFileName);
                    break;
            }
        }
    };

    // -------------------- Lifecycle --------------------

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        wakeWordDetector = new WakeWordDetector(this, this);
        initSpeechRecognizer();
        initTTS();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {

        // ALWAYS call startForeground to satisfy Context.startForegroundService requirement
        // Use a generic "Active" message if voice is disabled, otherwise "Listening..."
        startForeground(NOTIFICATION_ID, createNotification(voiceEnabled ? "Listening..." : "Active (Silent Mode)"));

        if (!receiverRegistered) {
            IntentFilter filter = new IntentFilter();
            filter.addAction("com.example.myapplication.TOGGLE_LISTENING");
            filter.addAction("com.example.myapplication.UPDATE_IP");
            filter.addAction("com.example.myapplication.CONNECT_SOCKET");
            filter.addAction("com.example.myapplication.SEND_MANUAL_COMMAND");
            filter.addAction("com.example.myapplication.SIMULATE_WAKE_WORD");
            filter.addAction("com.example.myapplication.PING_BACKEND");
            filter.addAction("com.example.myapplication.UPDATE_THRESHOLD");
            filter.addAction("com.example.myapplication.SWITCH_MODEL");
            ContextCompat.registerReceiver(this, actionReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED);
            receiverRegistered = true;
        }

        // Auto-connect socket if IP was already provided
        if (!backendAddress.isEmpty()) {
            connectWebSocket();
        }

        return START_STICKY;
    }

    @Override
    public void onDestroy() {

        isListening.set(false);

        if (audioRecord != null) {
            try {
                audioRecord.stop();
            } catch (Exception ignored) {
            }
        }

        if (audioThread != null) {
            try {
                audioThread.join(1000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }

        if (audioRecord != null) {
            audioRecord.release();
            audioRecord = null;
        }

        if (speechRecognizer != null) {
            mainHandler.post(() -> speechRecognizer.destroy());
        }

        if (mSocket != null) {
            mSocket.disconnect();
            mSocket.off();
        }

        if (tts != null) {
            tts.shutdown();
        }

        unregisterReceiver(actionReceiver);
        super.onDestroy();
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // -------------------- Speech Recognizer --------------------

    private void initSpeechRecognizer() {
        mainHandler.post(() -> {

            if (speechRecognizer != null) {
                speechRecognizer.destroy();
            }

            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this);

            recognizerIntent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            recognizerIntent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                    RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);

            speechRecognizer.setRecognitionListener(new RecognitionListener() {

                @Override
                public void onReadyForSpeech(Bundle params) {
                }

                @Override
                public void onBeginningOfSpeech() {
                }

                @Override
                public void onRmsChanged(float rmsdB) {
                }

                @Override
                public void onBufferReceived(byte[] buffer) {
                }

                @Override
                public void onEndOfSpeech() {
                }

                @Override
                public void onError(int error) {
                    Log.e(TAG, "Speech error: " + error);
                    if (voiceEnabled) resumeWakeWordWithDelay();
                }

                @Override
                public void onResults(Bundle results) {
                    ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);

                    if (matches != null && !matches.isEmpty()) {
                        String text = matches.get(0);
                        // Always broadcast transcribed text so UI shows it
                        Intent txIntent = new Intent("com.example.myapplication.COMMAND_TRANSCRIBED");
                        txIntent.putExtra("command", text);
                        sendBroadcast(txIntent);
                        sendCommandToBackend(text);
                    }

                    if (voiceEnabled) resumeWakeWordWithDelay();
                }

                @Override
                public void onPartialResults(Bundle partialResults) {
                }

                @Override
                public void onEvent(int eventType, Bundle params) {
                }
            });
        });
    }

    // -------------------- Wake Word --------------------

    @SuppressLint("MissingPermission")
    private void startWakeWordListening() {
        if (isListening.get())
            return;

        int bufferSize = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT);

        audioRecord = new AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                Math.max(bufferSize, CHUNK_SIZE * 2));

        audioRecord.startRecording();
        isListening.set(true);

        audioThread = new Thread(() -> {
            short[] buffer = new short[CHUNK_SIZE];

            while (isListening.get() && !Thread.currentThread().isInterrupted()) {
                int read = audioRecord.read(buffer, 0, buffer.length);
                if (read > 0 && wakeWordDetector != null) {
                    wakeWordDetector.processAudioChunk(buffer);
                }
            }
        });

        audioThread.start();
    }

    private void stopWakeWordListening() {
        if (!isListening.getAndSet(false))
            return;

        if (audioRecord != null) {
            try {
                audioRecord.stop();
                audioRecord.release();
            } catch (Exception ignored) {
            }
            audioRecord = null;
        }
    }

    @Override
    public void onWakeWordDetected() {

        stopWakeWordListening();

        // Notify UI
        sendBroadcast(new Intent("com.example.myapplication.WAKE_WORD_DETECTED"));

        mainHandler.post(() -> {
            if (speechRecognizer != null) {
                speechRecognizer.cancel();
                speechRecognizer.startListening(recognizerIntent);
            }
        });
    }

    private void resumeWakeWordWithDelay() {
        mainHandler.postDelayed(this::startWakeWordListening, 800);
    }

    // -------------------- Ping --------------------

    private void pingBackend() {
        if (backendAddress == null || backendAddress.isEmpty()) {
            Intent result = new Intent("com.example.myapplication.PING_RESULT");
            result.putExtra("success", false);
            sendBroadcast(result);
            return;
        }

        String url = "http://" + backendAddress + "/ping";
        Request request = new Request.Builder().url(url).build();
        HTTP_CLIENT.newCall(request).enqueue(new Callback() {
            @Override
            public void onFailure(Call call, IOException e) {
                Log.e(TAG, "Ping failed", e);
                Intent result = new Intent("com.example.myapplication.PING_RESULT");
                result.putExtra("success", false);
                sendBroadcast(result);
            }

            @Override
            public void onResponse(Call call, Response response) throws IOException {
                boolean success = response.isSuccessful();
                response.close();
                Intent result = new Intent("com.example.myapplication.PING_RESULT");
                result.putExtra("success", success);
                sendBroadcast(result);
            }
        });
    }

    private void sendCommandToBackend(String command) {

        if (mSocket != null && mSocket.connected()) {
            try {
                JSONObject json = new JSONObject();
                json.put("phrase", command);
                mSocket.emit("command", json);
            } catch (JSONException ignored) {
            }
            return;
        }

        if (backendAddress.isEmpty())
            return;

        String url = "http://" + backendAddress + "/api/command";

        try {
            JSONObject json = new JSONObject();
            json.put("command", command);

            RequestBody body = RequestBody.create(
                    json.toString(),
                    MediaType.parse("application/json"));

            Request request = new Request.Builder().url(url).post(body).build();

            HTTP_CLIENT.newCall(request).enqueue(new Callback() {
                @Override
                public void onFailure(Call call, IOException e) {
                    Log.e(TAG, "HTTP failed", e);
                }

                @Override
                public void onResponse(Call call, Response response) {
                    response.close();
                }
            });

        } catch (JSONException ignored) {
        }
    }

    private void connectWebSocket() {
        if (backendAddress.isEmpty())
            return;

        if (mSocket != null) {
            mSocket.disconnect();
            mSocket.off();
        }

        try {
            mSocket = IO.socket("http://" + backendAddress);

            mSocket.on(Socket.EVENT_CONNECT, args -> {
                Log.d(TAG, "Socket connected");
                sendBroadcast(new Intent("com.example.myapplication.SOCKET_CONNECTED"));
            });

            mSocket.on(Socket.EVENT_DISCONNECT, args -> {
                Log.d(TAG, "Socket disconnected");
                sendBroadcast(new Intent("com.example.myapplication.SOCKET_DISCONNECTED"));
            });

            mSocket.on("assistant_response", args -> {
                if (args.length > 0 && args[0] instanceof JSONObject) {
                    try {
                        String message = ((JSONObject) args[0]).getString("message");
                        Log.d(TAG, "Assistant says: " + message);
                        // Always show in UI
                        Intent responseIntent = new Intent("com.example.myapplication.ASSISTANT_RESPONSE");
                        responseIntent.putExtra("message", message);
                        sendBroadcast(responseIntent);
                        // Only speak aloud when voice is enabled
                        if (voiceEnabled && tts != null) {
                            tts.speak(message, TextToSpeech.QUEUE_FLUSH, null, null);
                        }
                    } catch (JSONException ignored) {}
                }
            });

            mSocket.connect();
        } catch (URISyntaxException e) {
            Log.e(TAG, "Socket error", e);
        }
    }

    // -------------------- TTS --------------------

    private void initTTS() {
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                tts.setLanguage(Locale.US);
            }
        });
    }

    // -------------------- Notification --------------------

    private Notification createNotification(String text) {
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("Assistant Service")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setOngoing(true)
                .setSilent(true) // Less intrusive
                .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    "Voice Assistant",
                    NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(channel);
        }
    }
}