package com.example.myapplication;

import android.util.Base64;
import android.util.Log;

import org.json.JSONException;
import org.json.JSONObject;

import java.security.SecureRandom;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * AES-256-GCM encryption/decryption utility.
 * Mirrors the Python CryptoHelper in server.py.
 */
public class CryptoUtils {
    private static final String TAG = "CryptoUtils";
    private static final String ALGORITHM = "AES/GCM/NoPadding";
    private static final int TAG_LENGTH_BITS = 128;
    private static final int IV_LENGTH_BYTES = 12;

    /**
     * Encrypts plaintext using AES-256-GCM.
     *
     * @param plaintext the string to encrypt
     * @param hexToken  the 256-bit hex token from pairing
     * @return JSONObject with "iv" and "ciphertext" (both Base64)
     */
    public static JSONObject encrypt(String plaintext, String hexToken) throws Exception {
        byte[] key = hexToBytes(hexToken);
        byte[] iv = new byte[IV_LENGTH_BYTES];
        new SecureRandom().nextBytes(iv);

        SecretKeySpec keySpec = new SecretKeySpec(key, "AES");
        GCMParameterSpec paramSpec = new GCMParameterSpec(TAG_LENGTH_BITS, iv);

        Cipher cipher = Cipher.getInstance(ALGORITHM);
        cipher.init(Cipher.ENCRYPT_MODE, keySpec, paramSpec);
        byte[] ciphertext = cipher.doFinal(plaintext.getBytes("UTF-8"));

        JSONObject result = new JSONObject();
        result.put("iv", Base64.encodeToString(iv, Base64.NO_WRAP));
        result.put("ciphertext", Base64.encodeToString(ciphertext, Base64.NO_WRAP));
        return result;
    }

    /**
     * Decrypts an AES-256-GCM encrypted payload.
     *
     * @param encryptedData JSONObject with "iv" and "ciphertext" (Base64)
     * @param hexToken      the 256-bit hex token from pairing
     * @return decrypted plaintext string
     */
    public static String decrypt(JSONObject encryptedData, String hexToken) throws Exception {
        byte[] key = hexToBytes(hexToken);
        byte[] iv = Base64.decode(encryptedData.getString("iv"), Base64.NO_WRAP);
        byte[] ciphertext = Base64.decode(encryptedData.getString("ciphertext"), Base64.NO_WRAP);

        SecretKeySpec keySpec = new SecretKeySpec(key, "AES");
        GCMParameterSpec paramSpec = new GCMParameterSpec(TAG_LENGTH_BITS, iv);

        Cipher cipher = Cipher.getInstance(ALGORITHM);
        cipher.init(Cipher.DECRYPT_MODE, keySpec, paramSpec);
        byte[] plaintext = cipher.doFinal(ciphertext);
        return new String(plaintext, "UTF-8");
    }

    /** Converts a hex string to a byte array. */
    private static byte[] hexToBytes(String hex) {
        int len = hex.length();
        byte[] data = new byte[len / 2];
        for (int i = 0; i < len; i += 2) {
            data[i / 2] = (byte) ((Character.digit(hex.charAt(i), 16) << 4)
                    + Character.digit(hex.charAt(i + 1), 16));
        }
        return data;
    }
}
