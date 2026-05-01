package com.positive.guga;

import android.app.AlertDialog;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.media.AudioManager;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.media.ToneGenerator;
import android.net.Uri;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.Settings;
import android.util.Log;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import android.graphics.Canvas;
import android.graphics.Color;
import android.animation.LayoutTransition;
import android.media.ToneGenerator;
import android.media.AudioManager;

import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;
import androidx.annotation.NonNull;
import androidx.appcompat.widget.SwitchCompat;
import androidx.activity.result.ActivityResultLauncher;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import androidx.core.content.ContextCompat;
import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

public class MainActivity extends AppCompatActivity {
    private static final String TAG = "GuGaUI";

    private static final String PREFS_NAME = "AlphaPrefs";
    private static final String PREF_BACKEND_IP = "backend_ip";
    private static final String PREF_TTS_ENABLED = "tts_enabled";
    private static final String PREF_HIDE_REPLY_FIELD = "hide_reply_field";
    private static final String PREF_TITLE_FILTER_REGEX = "title_filter_regex";

    private static final String ACTION_PING_RESULT       = "com.positive.guga.PING_RESULT";
    private static final String ACTION_GUGA_RESPONSE     = "com.positive.guga.GUGA_RESPONSE";
    private static final String ACTION_SOCKET_CONNECTED  = "com.positive.guga.SOCKET_CONNECTED";
    private static final String ACTION_SOCKET_DISCONNECTED = "com.positive.guga.SOCKET_DISCONNECTED";
    private static final String ACTION_UPDATE_IP         = "com.positive.guga.UPDATE_IP";
    private static final String ACTION_PING_BACKEND      = "com.positive.guga.PING_BACKEND";
    private static final String ACTION_CONNECT_SOCKET    = "com.positive.guga.CONNECT_SOCKET";
    private static final String ACTION_SEND_MANUAL_COMMAND = "com.positive.guga.SEND_MANUAL_COMMAND";
    private static final String ACTION_SET_TTS_ENABLED   = "com.positive.guga.SET_TTS_ENABLED";
    private static final String ACTION_SAVE_AUTH_TOKEN   = "com.positive.guga.SAVE_AUTH_TOKEN";
    private static final String ACTION_SET_FOREGROUND    = "com.positive.guga.SET_FOREGROUND";

    private TextView statusText;
    private RecyclerView chatRecyclerView;
    private ChatAdapter chatAdapter;
    private List<ChatMessage> chatMessages = new ArrayList<>();
    
    private EditText ipInput, manualCommandInput, filterInput, chatSearchInput;
    private SwitchCompat ttsToggle, hideReplyToggle;
    private android.view.View settingsOverlay, advancedSettingsOverlay, searchOverlay, connectionOverlay, mainContent, inputContainer, replyPreviewContainer;
    private android.view.View selectionModeHeader, selectionModeFooter;
    private TextView selectionCountText, replyTitleText, replyContentText;
    private android.widget.ImageButton cancelSelectionButton, deleteSelectionButton, copySelectionButton, replySelectionButton, cancelReplyButton;
    private Button saveIpButton, scanQrButton, pingButton, connectSocketButton, sendManualCommandButton, toggleSettingsButton, clearHistoryButton, openAdvancedButton, closeAdvancedButton, bypassToggleButton, applyFilterButton, searchChatsButton, closeSearchButton;
    private RecyclerView searchRecyclerView;
    private ChatAdapter searchResultAdapter;
    private List<ChatMessage> searchResults = new ArrayList<>();

    private String pendingReplyRequestId = null;
    private String pendingReplyMessageId = null;
    private boolean isBypassActive = false;

    private boolean isSettingsOpen = false;
    private boolean isBackendOnline = false;
    private boolean isSocketConnected = false;

    private SharedPreferences prefs;
    private boolean isReviewMode = false;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final OkHttpClient httpClient = new OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build();
    private ToneGenerator toneGenerator;
    
    private String currentGeneratedPin = "";
    private boolean isPollingForApproval = false;

    // ----------------------------------------------------------------
    // QR Scanner
    // ----------------------------------------------------------------

    private final ActivityResultLauncher<ScanOptions> qrCodeLauncher = registerForActivityResult(
            new ScanContract(),
            result -> {
                if (result.getContents() != null) {
                    String scannedUrl = result.getContents().trim();
                    if (scannedUrl.endsWith("/")) scannedUrl = scannedUrl.substring(0, scannedUrl.length() - 1);
                    
                    vibrate(); 
                    
                    ipInput.setText(scannedUrl);
                    prefs.edit().putString(PREF_BACKEND_IP, scannedUrl).apply();
                    Intent updateIntent = new Intent(ACTION_UPDATE_IP);
                    updateIntent.putExtra("ip", scannedUrl);
                    sendBroadcast(updateIntent);
                    statusText.setText("Connecting to GuGu...");
                    performHandshake(scannedUrl);
                }
            });

    // ----------------------------------------------------------------
    // Broadcast Receiver
    // ----------------------------------------------------------------

    private final BroadcastReceiver serviceReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String action = intent.getAction();
            if (action == null) return;

            switch (action) {
                case ACTION_PING_RESULT:
                    boolean success = intent.getBooleanExtra("success", false);
                    isBackendOnline = success;
                    updateConnectionVisibility();
                    statusText.setText(success ? "STATUS: BACKEND ONLINE" : "STATUS: PING FAILED");
                    statusText.setTextColor(Color.WHITE);
                    break;
                case ACTION_SOCKET_CONNECTED:
                    isSocketConnected = true;
                    updateConnectionVisibility();
                    statusText.setText("STATUS: LIVE SYNC ACTIVE");
                    statusText.setTextColor(Color.WHITE);
                    break;
                case ACTION_SOCKET_DISCONNECTED:
                    isSocketConnected = false;
                    updateConnectionVisibility();
                    runOnUiThread(() -> {
                        statusText.setText("⚠️ Connection Failed. Hint: Ensure you are on the same Wi-Fi network as the server, or check if the Python server is running.");
                        statusText.setTextColor(Color.GRAY);
                    });
                    break;
                case ACTION_GUGA_RESPONSE:
                    String msg = intent.getStringExtra("message");
                    String title = intent.getStringExtra("title");
                    String msgId = intent.getStringExtra("message_id");
                    String reqId = intent.getStringExtra("request_id");
                    
                    if (msg != null) {
                        ChatMessage chatMsg = new ChatMessage(msg, title, false);
                        chatMsg.setMessageId(msgId);
                        chatMsg.setRequestId(reqId);
                        appendChat(chatMsg);
                        playTing();
                    }
                    break;
            }
        }
    };

    // ----------------------------------------------------------------
    // Lifecycle
    // ----------------------------------------------------------------

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        toneGenerator = new ToneGenerator(AudioManager.STREAM_NOTIFICATION, 100);

        initViews();
        setupHistory();
        setupListeners();
        setupBackButton();

        IntentFilter filter = new IntentFilter();
        filter.addAction(ACTION_PING_RESULT);
        filter.addAction(ACTION_SOCKET_CONNECTED);
        filter.addAction(ACTION_SOCKET_DISCONNECTED);
        filter.addAction(ACTION_GUGA_RESPONSE);
        ContextCompat.registerReceiver(this, serviceReceiver, filter, ContextCompat.RECEIVER_EXPORTED);

        startService(new Intent(this, GuGaService.class));

        String currentIp = prefs.getString(PREF_BACKEND_IP, "");
        if (!currentIp.isEmpty()) {
            ipInput.setText(currentIp);
            performHandshake(currentIp);
        }
    }

    private void setupBackButton() {
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (chatAdapter.isSelectionMode()) {
                    chatAdapter.setSelectionMode(false);
                } else if (searchOverlay.getVisibility() == android.view.View.VISIBLE) {
                    toggleSearchOverlay();
                } else if (advancedSettingsOverlay.getVisibility() == android.view.View.VISIBLE) {
                    toggleAdvancedSettings();
                } else if (isSettingsOpen) {
                    toggleSettings();
                } else {
                    setEnabled(false);
                    MainActivity.this.onBackPressed();
                }
            }
        });
    }

    @Override
    protected void onStart() {
        super.onStart();
        sendForegroundState(true);
    }

    @Override
    protected void onStop() {
        super.onStop();
        sendForegroundState(false);
    }

    private void sendForegroundState(boolean isForeground) {
        Intent intent = new Intent(ACTION_SET_FOREGROUND);
        intent.putExtra("isForeground", isForeground);
        sendBroadcast(intent);
    }

    @Override
    protected void onDestroy() {
        unregisterReceiver(serviceReceiver);
        if (toneGenerator != null) toneGenerator.release();
        super.onDestroy();
    }

    // ----------------------------------------------------------------
    // Setup
    // ----------------------------------------------------------------

    private void initViews() {
        statusText           = findViewById(R.id.statusText);
        chatRecyclerView     = findViewById(R.id.chatRecyclerView);
        ipInput              = findViewById(R.id.ipInput);
        saveIpButton         = findViewById(R.id.saveIpButton);
        scanQrButton         = findViewById(R.id.scanQrButton);
        pingButton           = findViewById(R.id.pingButton);
        connectSocketButton  = findViewById(R.id.connectSocketButton);
        manualCommandInput   = findViewById(R.id.manualCommandInput);
        sendManualCommandButton = findViewById(R.id.sendManualCommandButton);
        ttsToggle            = findViewById(R.id.ttsToggle);
        toggleSettingsButton = findViewById(R.id.toggleSettingsButton);
        clearHistoryButton   = findViewById(R.id.clearHistoryButton);
        settingsOverlay      = findViewById(R.id.settingsOverlay);
        advancedSettingsOverlay = findViewById(R.id.advancedSettingsOverlay);
        connectionOverlay    = findViewById(R.id.connectionOverlay);
        mainContent          = findViewById(R.id.mainContent);
        inputContainer       = findViewById(R.id.inputContainer);
        if (inputContainer instanceof android.view.ViewGroup) {
            LayoutTransition transition = ((android.view.ViewGroup)inputContainer).getLayoutTransition();
            if (transition != null) {
                transition.enableTransitionType(LayoutTransition.CHANGING);
            }
        }
        
        openAdvancedButton   = findViewById(R.id.openAdvancedButton);
        closeAdvancedButton  = findViewById(R.id.closeAdvancedButton);
        hideReplyToggle      = findViewById(R.id.hideReplyToggle);
        selectionModeHeader  = findViewById(R.id.selectionModeHeader);
        selectionModeFooter  = findViewById(R.id.selectionModeFooter);
        selectionCountText   = findViewById(R.id.selectionCountText);
        cancelSelectionButton = findViewById(R.id.cancelSelectionButton);
        deleteSelectionButton = findViewById(R.id.deleteSelectionButton);
        copySelectionButton   = findViewById(R.id.copySelectionButton);
        replySelectionButton  = findViewById(R.id.replySelectionButton);
        
        replyPreviewContainer = findViewById(R.id.replyPreviewContainer);
        replyTitleText       = findViewById(R.id.replyTitleText);
        replyContentText     = findViewById(R.id.replyContentText);
        cancelReplyButton    = findViewById(R.id.cancelReplyButton);
        bypassToggleButton   = findViewById(R.id.bypassToggleButton);
        filterInput          = findViewById(R.id.filterInput);
        applyFilterButton    = findViewById(R.id.applyFilterButton);
        searchOverlay        = findViewById(R.id.searchOverlay);
        searchChatsButton    = findViewById(R.id.searchChatsButton);
        chatSearchInput      = findViewById(R.id.chatSearchInput);
        searchRecyclerView   = findViewById(R.id.searchRecyclerView);
        closeSearchButton    = findViewById(R.id.closeSearchButton);

        chatAdapter = new ChatAdapter(chatMessages);
        chatAdapter.setOnSelectionChangeListener(new ChatAdapter.OnSelectionChangeListener() {
            @Override
            public void onSelectionChanged(int count) {
                selectionCountText.setText(count + " Selected");
                updateSelectionFooterState();
            }

            @Override
            public void onSelectionModeChanged(boolean active) {
                selectionModeHeader.setVisibility(android.view.View.VISIBLE);
                selectionModeFooter.setVisibility(android.view.View.VISIBLE);
                if (!active) {
                    selectionModeHeader.setVisibility(android.view.View.GONE);
                    selectionModeFooter.setVisibility(android.view.View.GONE);
                }
                toggleSettingsButton.setVisibility(active ? android.view.View.GONE : android.view.View.VISIBLE);
            }
        });
        chatRecyclerView.setLayoutManager(new LinearLayoutManager(this));
        chatRecyclerView.setAdapter(chatAdapter);
        setupSwipeToReply();

        chatRecyclerView.addOnScrollListener(new RecyclerView.OnScrollListener() {
            @Override
            public void onScrolled(@NonNull RecyclerView recyclerView, int dx, int dy) {
                LinearLayoutManager layoutManager = (LinearLayoutManager) recyclerView.getLayoutManager();
                if (layoutManager != null) {
                    int lastVisible = layoutManager.findLastVisibleItemPosition();
                    int total = chatAdapter.getItemCount();
                    // If user is scrolled up by more than 4 messages, enter review mode
                    isReviewMode = (total - lastVisible) > 5; // > 4 messages gap
                }
            }
        });

        searchRecyclerView.setLayoutManager(new LinearLayoutManager(this));
        searchResultAdapter = new ChatAdapter(searchResults);
        searchRecyclerView.setAdapter(searchResultAdapter);

        searchResultAdapter.setOnItemClickListener((msg, pos) -> {
            // 1. Hide everything
            searchOverlay.setVisibility(android.view.View.GONE);
            advancedSettingsOverlay.setVisibility(android.view.View.GONE);
            settingsOverlay.setVisibility(android.view.View.GONE);
            isSettingsOpen = false;
            toggleSettingsButton.setText(">");
            hideKeyboard();

            // 2. Clear regex if it hides this message
            String currentRegex = filterInput.getText().toString().trim();
            if (!currentRegex.isEmpty() && !currentRegex.equals("*")) {
                String title = msg.getTitle();
                try {
                    java.util.regex.Pattern p = java.util.regex.Pattern.compile(currentRegex, java.util.regex.Pattern.CASE_INSENSITIVE);
                    if (title == null || !p.matcher(title).find()) {
                        if (!msg.isUser()) {
                            filterInput.setText("");
                            chatAdapter.setFilter("");
                        }
                    }
                } catch (Exception ignored) {}
            }

            // 3. Scroll to message
            chatRecyclerView.post(() -> {
                int displayPos = chatAdapter.getFilteredMessages().indexOf(msg);
                if (displayPos != -1) {
                    chatRecyclerView.smoothScrollToPosition(displayPos);
                }
            });
        });

        boolean ttsEnabled = prefs.getBoolean(PREF_TTS_ENABLED, false); // Default OFF
        ttsToggle.setChecked(ttsEnabled);
        updateTtsToggleColor(ttsEnabled);
        Intent ttsIntent = new Intent(ACTION_SET_TTS_ENABLED);
        ttsIntent.putExtra("enabled", ttsEnabled);
        sendBroadcast(ttsIntent);

        boolean hideReply = prefs.getBoolean(PREF_HIDE_REPLY_FIELD, false);
        hideReplyToggle.setChecked(hideReply);
        updateHideReplyState(hideReply);

        String savedRegex = prefs.getString(PREF_TITLE_FILTER_REGEX, "");
        filterInput.setText(savedRegex);
        chatAdapter.setFilter(savedRegex);
    }

    private void setupHistory() {
        List<ChatMessage> history = ChatHistory.load(this);
        chatMessages.addAll(history);
        chatAdapter.notifyDataSetChanged();
        if (!chatMessages.isEmpty()) {
            chatRecyclerView.scrollToPosition(chatMessages.size() - 1);
        }
    }

    private void setupListeners() {
        saveIpButton.setOnClickListener(v -> handleNewIp(ipInput.getText().toString()));
        scanQrButton.setOnClickListener(v -> {
            ScanOptions options = new ScanOptions();
            options.setDesiredBarcodeFormats(ScanOptions.QR_CODE);
            options.setPrompt("Scan GuGu IP");
            options.setBeepEnabled(false);
            options.setOrientationLocked(false);
            qrCodeLauncher.launch(options);
        });

        pingButton.setOnClickListener(v -> sendBroadcast(new Intent(ACTION_PING_BACKEND)));
        connectSocketButton.setOnClickListener(v -> {
            if (!isNetworkAvailable()) {
                statusText.setText("⚠️ Hint: Turn on Wi-Fi or Cellular Data to connect.");
                return;
            }
            String ip = ipInput.getText().toString().trim();
            if (!ip.isEmpty()) performHandshake(ip);
        });

        ttsToggle.setOnCheckedChangeListener((btn, checked) -> {
            prefs.edit().putBoolean(PREF_TTS_ENABLED, checked).apply();
            updateTtsToggleColor(checked);
            Intent intent = new Intent(ACTION_SET_TTS_ENABLED);
            intent.putExtra("enabled", checked);
            sendBroadcast(intent);
        });

        sendManualCommandButton.setOnClickListener(v -> sendManualCommand());
        manualCommandInput.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendManualCommand();
                return true;
            }
            return false;
        });

        toggleSettingsButton.setOnClickListener(v -> toggleSettings());

        clearHistoryButton.setOnClickListener(v -> {
            new AlertDialog.Builder(this)
                .setTitle("Clear History")
                .setMessage("Delete all saved messages?")
                .setPositiveButton("Clear", (dialog, which) -> {
                    ChatHistory.clear(this);
                    chatMessages.clear();
                    chatAdapter.notifyDataSetChanged();
                    Toast.makeText(this, "History cleared", Toast.LENGTH_SHORT).show();
                })
                .setNegativeButton("Cancel", null)
                .show();
        });

        openAdvancedButton.setOnClickListener(v -> toggleAdvancedSettings());
        closeAdvancedButton.setOnClickListener(v -> toggleAdvancedSettings());

        hideReplyToggle.setOnCheckedChangeListener((btn, checked) -> {
            prefs.edit().putBoolean(PREF_HIDE_REPLY_FIELD, checked).apply();
            updateHideReplyState(checked);
        });

        cancelSelectionButton.setOnClickListener(v -> chatAdapter.setSelectionMode(false));
        
        deleteSelectionButton.setOnClickListener(v -> {
            List<ChatMessage> selected = chatAdapter.getSelectedMessages();
            chatMessages.removeAll(selected);
            // Refresh filtered list
            chatAdapter.setFilter(prefs.getString(PREF_TITLE_FILTER_REGEX, ""));
            chatAdapter.setSelectionMode(false);
            ChatHistory.save(this, chatMessages);
            Toast.makeText(this, "Deleted " + selected.size() + " messages", Toast.LENGTH_SHORT).show();
        });

        copySelectionButton.setOnClickListener(v -> {
            List<ChatMessage> selected = chatAdapter.getSelectedMessages();
            StringBuilder sb = new StringBuilder();
            for (ChatMessage m : selected) {
                if (m.getTitle() != null && !m.getTitle().isEmpty()) {
                    sb.append("[").append(m.getTitle()).append("]\n");
                }
                sb.append(m.getText()).append("\n\n");
            }
            android.content.ClipboardManager clipboard = (android.content.ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            android.content.ClipData clip = android.content.ClipData.newPlainText("GuGa Messages", sb.toString().trim());
            clipboard.setPrimaryClip(clip);
            chatAdapter.setSelectionMode(false);
            Toast.makeText(this, "Copied to clipboard", Toast.LENGTH_SHORT).show();
        });

        replySelectionButton.setOnClickListener(v -> {
            List<ChatMessage> selected = chatAdapter.getSelectedMessages();
            if (selected.size() == 1) {
                ChatMessage m = selected.get(0);
                startReply(m);
                chatAdapter.setSelectionMode(false);
            }
        });

        cancelReplyButton.setOnClickListener(v -> cancelReply());
        
        bypassToggleButton.setOnClickListener(v -> {
            isBypassActive = !isBypassActive;
            updateBypassToggleUI();
        });

        applyFilterButton.setOnClickListener(v -> {
            String regex = filterInput.getText().toString().trim();
            prefs.edit().putString(PREF_TITLE_FILTER_REGEX, regex).apply();
            chatAdapter.setFilter(regex);
            Toast.makeText(this, "Filter Applied", Toast.LENGTH_SHORT).show();
        });

        searchChatsButton.setOnClickListener(v -> toggleSearchOverlay());
        closeSearchButton.setOnClickListener(v -> toggleSearchOverlay());
        
        chatSearchInput.addTextChangedListener(new android.text.TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {
                performSearch(s.toString());
            }
            @Override public void afterTextChanged(android.text.Editable s) {}
        });
    }

    private void performSearch(String query) {
        searchResults.clear();
        if (!query.isEmpty()) {
            String q = query.toLowerCase();
            for (ChatMessage m : chatMessages) {
                if (m.getText().toLowerCase().contains(q) || (m.getTitle() != null && m.getTitle().toLowerCase().contains(q))) {
                    searchResults.add(m);
                }
            }
        }
        searchResultAdapter.setFilter(""); // No filtering in search results
        searchResultAdapter.notifyDataSetChanged();
    }

    private void toggleSearchOverlay() {
        boolean isOpen = searchOverlay.getVisibility() == android.view.View.VISIBLE;
        searchOverlay.setVisibility(isOpen ? android.view.View.GONE : android.view.View.VISIBLE);
        advancedSettingsOverlay.setVisibility(isOpen ? android.view.View.VISIBLE : android.view.View.GONE);
        if (!isOpen) {
            chatSearchInput.requestFocus();
            showKeyboard();
        } else {
            hideKeyboard();
        }
    }

    private void startReply(ChatMessage m) {
        pendingReplyRequestId = m.getRequestId();
        pendingReplyMessageId = m.getMessageId();
        
        replyTitleText.setText(m.getTitle() != null ? m.getTitle() : "Bot Message");
        replyContentText.setText(m.getText());
        replyPreviewContainer.setVisibility(android.view.View.VISIBLE);
        
        manualCommandInput.requestFocus();
        showKeyboard();
    }

    private void cancelReply() {
        pendingReplyRequestId = null;
        pendingReplyMessageId = null;
        replyPreviewContainer.setVisibility(android.view.View.GONE);
    }

    private void updateBypassToggleUI() {
        bypassToggleButton.setTextColor(isBypassActive ? Color.WHITE : Color.GRAY);
        // Optional: add a small visual indicator or toast
    }

    private void updateSelectionFooterState() {
        List<ChatMessage> selected = chatAdapter.getSelectedMessages();
        boolean allBot = true;
        for (ChatMessage m : selected) {
            if (m.isUser()) {
                allBot = false;
                break;
            }
        }
        // Only allow reply if exactly ONE bot message is selected (per usual UX, but user said "if only bot messages are selected")
        // I'll stick to 1 for simplicity of correlating, or I could handle a list.
        // User said: "Only shown if only bot items are selected"
        replySelectionButton.setVisibility(allBot && !selected.isEmpty() && selected.size() == 1 ? android.view.View.VISIBLE : android.view.View.GONE);
    }

    private void setupSwipeToReply() {
        androidx.recyclerview.widget.ItemTouchHelper.SimpleCallback callback = 
            new androidx.recyclerview.widget.ItemTouchHelper.SimpleCallback(0, androidx.recyclerview.widget.ItemTouchHelper.LEFT) {
                @Override
                public boolean onMove(@NonNull RecyclerView rv, @NonNull RecyclerView.ViewHolder vh, @NonNull RecyclerView.ViewHolder t) { return false; }

                @Override
                public int getSwipeDirs(@NonNull RecyclerView rv, @NonNull RecyclerView.ViewHolder vh) {
                    int pos = vh.getAdapterPosition();
                    if (pos != RecyclerView.NO_POSITION && !chatMessages.get(pos).isUser()) {
                        return super.getSwipeDirs(rv, vh);
                    }
                    return 0;
                }

                @Override
                public void onChildDraw(@NonNull Canvas c, @NonNull RecyclerView recyclerView, @NonNull RecyclerView.ViewHolder viewHolder, float dX, float dY, int actionState, boolean isCurrentlyActive) {
                    float limit = -recyclerView.getWidth() * 0.05f; // 5% limit
                    float newX = Math.max(dX, limit);
                    super.onChildDraw(c, recyclerView, viewHolder, newX, dY, actionState, isCurrentlyActive);
                }

                @Override
                public void onSwiped(@NonNull RecyclerView.ViewHolder vh, int dir) {
                    int pos = vh.getAdapterPosition();
                    if (pos != RecyclerView.NO_POSITION) {
                        startReply(chatAdapter.getFilteredMessages().get(pos));
                        chatAdapter.notifyItemChanged(pos); // Reset swipe visual
                    }
                }
            };
        new androidx.recyclerview.widget.ItemTouchHelper(callback).attachToRecyclerView(chatRecyclerView);
    }

    private void updateTtsToggleColor(boolean enabled) {
        int color = enabled ? Color.WHITE : Color.GRAY;
        ttsToggle.setTextColor(color);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            ttsToggle.setThumbTintList(android.content.res.ColorStateList.valueOf(color));
        }
    }

    // ----------------------------------------------------------------
    // Phase 11 Handshake
    // ----------------------------------------------------------------

    private String fetchAndroidId() {
        return Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
    }

    private void performHandshake(String ipBase) {
        performHandshake(ipBase, false);
    }

    private void performHandshake(String ipBase, boolean forcePair) {
        if (!isNetworkAvailable()) {
            statusText.setText("⚠️ Hint: Turn on Wi-Fi or Cellular Data to connect.");
            return;
        }
        String url = cleanIp(ipBase) + "/api/hello";
        String deviceId = fetchAndroidId();
        String pin = generateRandomPin();
        String deviceName = Build.MODEL != null ? Build.MODEL : "Android Device";
        
        try {
            JSONObject payload = new JSONObject();
            payload.put("device_id", deviceId);
            payload.put("pin", pin);
            payload.put("device_name", deviceName);
            payload.put("force_pair", forcePair);
            
            RequestBody body = RequestBody.create(payload.toString(), MediaType.parse("application/json"));
            Request request = new Request.Builder().url(url).post(body).build();

            httpClient.newCall(request).enqueue(new Callback() {
                @Override
                public void onFailure(Call call, IOException e) {
                    mainHandler.post(() -> statusText.setText("HANDSHAKE FAILED"));
                }

                @Override
                public void onResponse(Call call, Response response) throws IOException {
                    try {
                        String responseBody = response.body().string();
                        JSONObject json = new JSONObject(responseBody);
                        String status = json.getString("status");

                        if ("trusted".equals(status)) {
                            String token = SecurityUtils.getAuthToken(MainActivity.this);
                            if (token == null) {
                                mainHandler.post(() -> performHandshake(ipBase, true));
                            } else {
                                mainHandler.post(() -> {
                                    statusText.setText("TRUSTED DEVICE");
                                    sendBroadcast(new Intent(ACTION_CONNECT_SOCKET));
                                });
                            }
                        } else if ("pin_required".equals(status)) {
                            mainHandler.post(() -> showPinDialog(ipBase, deviceId, pin));
                        }
                    } catch (Exception e) {
                        Log.e(TAG, "Handshake response error", e);
                    } finally {
                        response.close();
                    }
                }
            });
        } catch (Exception e) {
            Log.e(TAG, "Handshake request error", e);
        }
    }

    private String generateRandomPin() {
        SecureRandom random = new SecureRandom();
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 8; i++) {
            sb.append(random.nextInt(10));
        }
        return sb.toString();
    }

    private void showPinDialog(String ip, String deviceId, String pin) {
        currentGeneratedPin = pin;
        isPollingForApproval = true;

        TextView pinDisplay = new TextView(this);
        // Format PIN with spaces: "1 2 3 4 5 6 7 8"
        String spacedPin = pin.replace("", " ").trim();
        pinDisplay.setText(spacedPin);
        pinDisplay.setTextSize(32);
        pinDisplay.setGravity(android.view.Gravity.CENTER);
        pinDisplay.setPadding(0, 40, 0, 40);
        pinDisplay.setTextColor(Color.WHITE);
        pinDisplay.setTypeface(null, android.graphics.Typeface.BOLD);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(64, 32, 64, 0);
        layout.addView(pinDisplay);

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("Pairing Request Sent")
                .setMessage("Show this PIN to your Linux machine and run 'guga --approve' to authorize this device.")
                .setView(layout)
                .setNegativeButton("Cancel", (d, w) -> isPollingForApproval = false)
                .setCancelable(false)
                .show();

        // Start polling loop
        pollForApproval(dialog, ip, deviceId, pin, 0);
    }

    private void pollForApproval(AlertDialog dialog, String ip, String deviceId, String pin, int attempt) {
        if (!isPollingForApproval || dialog == null || !dialog.isShowing()) return;

        if (attempt > 60) { // 5 minutes timeout (5s * 60)
            dialog.dismiss();
            Toast.makeText(this, "Pairing timed out", Toast.LENGTH_LONG).show();
            return;
        }

        verifyPin(ip, deviceId, pin, new PinVerificationCallback() {
            @Override
            public void onResult(boolean success, String error) {
                if (success) {
                    dialog.dismiss();
                    isPollingForApproval = false;
                } else if ("too many attempts".equals(error)) {
                    dialog.dismiss();
                    isPollingForApproval = false;
                    Toast.makeText(MainActivity.this, "Too many failed attempts. Device blocked.", Toast.LENGTH_LONG).show();
                } else {
                    // Still waiting or failed, try again in 5 seconds
                    mainHandler.postDelayed(() -> pollForApproval(dialog, ip, deviceId, pin, attempt + 1), 5000);
                }
            }
        });
    }

    interface PinVerificationCallback {
        void onResult(boolean success, String error);
    }

    private void verifyPin(String ip, String deviceId, String pin, PinVerificationCallback callback) {
        if (!isNetworkAvailable()) {
            if (callback != null) callback.onResult(false, "No network");
            return;
        }
        String url = cleanIp(ip) + "/api/verify_pin";
        try {
            JSONObject body = new JSONObject();
            body.put("device_id", deviceId);
            body.put("pin", pin);
            body.put("client_type", "app");

            RequestBody reqBody = RequestBody.create(body.toString(), MediaType.parse("application/json"));
            Request request = new Request.Builder().url(url).post(reqBody).build();

            httpClient.newCall(request).enqueue(new Callback() {
                @Override
                public void onFailure(Call call, IOException e) {
                    if (callback != null) callback.onResult(false, e.getMessage());
                }

                @Override
                public void onResponse(Call call, Response response) throws IOException {
                    try {
                        String responseBody = response.body().string();
                        if (response.isSuccessful()) {
                            JSONObject json = new JSONObject(responseBody);
                            String token = json.getString("token");
                            
                            SecurityUtils.saveAuthToken(MainActivity.this, token);
                            
                            Intent intent = new Intent(ACTION_SAVE_AUTH_TOKEN);
                            intent.putExtra("token", token);
                            sendBroadcast(intent);
                            
                            mainHandler.post(() -> {
                                statusText.setText("PAIRED SUCCESSFULLY");
                                sendBroadcast(new Intent(ACTION_CONNECT_SOCKET));
                            });
                            if (callback != null) callback.onResult(true, null);
                        } else {
                            JSONObject json = new JSONObject(responseBody);
                            String error = json.optString("error", "Failed");
                            if (callback != null) callback.onResult(false, error);
                        }
                    } catch (Exception e) {
                        if (callback != null) callback.onResult(false, e.getMessage());
                    } finally {
                        response.close();
                    }
                }
            });
        } catch (Exception e) {
            if (callback != null) callback.onResult(false, e.getMessage());
        }
    }

    // ----------------------------------------------------------------
    // Helpers
    // ----------------------------------------------------------------

    private String cleanIp(String ip) {
        if (ip == null) return "";
        String clean = ip.trim();
        if (clean.endsWith("/")) clean = clean.substring(0, clean.length() - 1);
        if (!clean.startsWith("http")) clean = "http://" + clean;
        return clean;
    }

    private void handleNewIp(String ip) {
        String clean = cleanIp(ip);
        if (clean.isEmpty()) return;
        ipInput.setText(clean);
        prefs.edit().putString(PREF_BACKEND_IP, clean).apply();
        Intent intent = new Intent(ACTION_UPDATE_IP);
        intent.putExtra("ip", clean);
        sendBroadcast(intent);
        statusText.setText("IP UPDATED");
        performHandshake(clean);
    }

    private void toggleSettings() {
        isSettingsOpen = !isSettingsOpen;
        settingsOverlay.setVisibility(isSettingsOpen ? android.view.View.VISIBLE : android.view.View.GONE);
        if (!isSettingsOpen) advancedSettingsOverlay.setVisibility(android.view.View.GONE);
        
        toggleSettingsButton.setText(isSettingsOpen ? "<" : ">");
        if (!isSettingsOpen) updateConnectionVisibility();
    }

    private void toggleAdvancedSettings() {
        boolean isAdvancedOpen = advancedSettingsOverlay.getVisibility() == android.view.View.VISIBLE;
        advancedSettingsOverlay.setVisibility(isAdvancedOpen ? android.view.View.GONE : android.view.View.VISIBLE);
        settingsOverlay.setVisibility(isAdvancedOpen ? android.view.View.VISIBLE : android.view.View.GONE);
    }

    private void updateHideReplyState(boolean hide) {
        inputContainer.setVisibility(hide ? android.view.View.GONE : android.view.View.VISIBLE);
        hideReplyToggle.setTextColor(hide ? Color.WHITE : Color.GRAY);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            hideReplyToggle.setThumbTintList(android.content.res.ColorStateList.valueOf(hide ? Color.WHITE : Color.GRAY));
        }
    }

    private void updateConnectionVisibility() {
        if (isBackendOnline || isSocketConnected) {
            connectionOverlay.setVisibility(android.view.View.GONE);
            mainContent.setVisibility(android.view.View.VISIBLE);
        } else {
            connectionOverlay.setVisibility(android.view.View.VISIBLE);
            mainContent.setVisibility(android.view.View.GONE);
        }
    }

    private void sendManualCommand() {
        String cmd = manualCommandInput.getText().toString().trim();
        if (cmd.isEmpty()) return;
        appendChat(new ChatMessage(cmd, true));
        Intent intent = new Intent(ACTION_SEND_MANUAL_COMMAND);
        intent.putExtra("command", cmd);
        
        if (isBypassActive) {
            intent.putExtra("request_id", "None");
        } else if (pendingReplyRequestId != null) {
            intent.putExtra("request_id", pendingReplyRequestId);
        }
        
        if (pendingReplyMessageId != null) {
            intent.putExtra("message_id", pendingReplyMessageId);
        }
        sendBroadcast(intent);
        manualCommandInput.setText("");
        cancelReply();
        hideKeyboard();
    }

    private void appendChat(ChatMessage msg) {
        mainHandler.post(() -> {
            chatMessages.add(msg);
            chatAdapter.onMessageAdded();
            
            // Auto-scroll logic
            if (msg.isUser()) {
                // User messages always force scroll and exit review mode
                isReviewMode = false;
                chatRecyclerView.smoothScrollToPosition(chatAdapter.getItemCount());
            } else if (!isReviewMode) {
                // Bot messages only scroll if we are not in review mode
                chatRecyclerView.smoothScrollToPosition(chatAdapter.getItemCount());
            }
            
            ChatHistory.save(this, chatMessages);
        });
    }

    private void playTing() {
        boolean ttsEnabled = prefs.getBoolean(PREF_TTS_ENABLED, true);
        if (ttsEnabled) return; // Silent if TTS on

        try {
            Uri notification = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
            Ringtone r = RingtoneManager.getRingtone(getApplicationContext(), notification);
            r.play();
        } catch (Exception e) {
            if (toneGenerator != null) toneGenerator.startTone(ToneGenerator.TONE_PROP_BEEP, 200);
        }
    }

    private boolean isNetworkAvailable() {
        ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) return false;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            android.net.Network network = cm.getActiveNetwork();
            if (network == null) return false;
            NetworkCapabilities capabilities = cm.getNetworkCapabilities(network);
            return capabilities != null && (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || 
                                           capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ||
                                           capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET));
        } else {
            android.net.NetworkInfo activeNetwork = cm.getActiveNetworkInfo();
            return activeNetwork != null && activeNetwork.isConnected();
        }
    }

    private void vibrate() {
        Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
        if (v != null && v.hasVibrator()) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                v.vibrate(VibrationEffect.createOneShot(100, VibrationEffect.DEFAULT_AMPLITUDE));
            } else {
                v.vibrate(100);
            }
        }
    }

    private void hideKeyboard() {
        InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(manualCommandInput.getWindowToken(), 0);
    }

    private void showKeyboard() {
        InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (imm != null) imm.showSoftInput(manualCommandInput, InputMethodManager.SHOW_IMPLICIT);
    }
}
