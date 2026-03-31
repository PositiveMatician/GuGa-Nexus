package com.example.myapplication;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import androidx.security.crypto.EncryptedSharedPreferences;
import androidx.security.crypto.MasterKey;

import java.io.IOException;
import java.security.GeneralSecurityException;

public class SecurityUtils {
    private static final String TAG = "SecurityUtils";
    private static final String ENCRYPTED_PREFS_NAME = "guga_secure_prefs";
    private static final String KEY_AUTH_TOKEN = "auth_token";

    public static SharedPreferences getEncryptedPrefs(Context context) {
        try {
            MasterKey masterKey = new MasterKey.Builder(context)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                    .build();
            return EncryptedSharedPreferences.create(
                    context,
                    ENCRYPTED_PREFS_NAME,
                    masterKey,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            );
        } catch (GeneralSecurityException | IOException e) {
            Log.e(TAG, "Failed to create EncryptedSharedPreferences", e);
            return context.getSharedPreferences("guga_prefs_fallback", Context.MODE_PRIVATE);
        }
    }

    public static String getAuthToken(Context context) {
        return getEncryptedPrefs(context).getString(KEY_AUTH_TOKEN, null);
    }

    public static void saveAuthToken(Context context, String token) {
        getEncryptedPrefs(context).edit().putString(KEY_AUTH_TOKEN, token).apply();
    }
}
