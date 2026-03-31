package com.example.myapplication;

import android.content.Context;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.List;

public class ChatHistory {
    private static final String FILE_NAME = "chat_history.json";
    
    public static void save(Context context, List<ChatMessage> messages) {
        try {
            JSONArray array = new JSONArray();
            for (ChatMessage m : messages) {
                JSONObject obj = new JSONObject();
                obj.put("text", m.getText());
                obj.put("isUser", m.isUser());
                array.put(obj);
            }
            try (FileOutputStream fos = context.openFileOutput(FILE_NAME, Context.MODE_PRIVATE)) {
                fos.write(array.toString().getBytes());
            }
        } catch (Exception e) {
            Log.e("ChatHistory", "Save failed", e);
        }
    }
    
    public static void append(Context context, ChatMessage message) {
        List<ChatMessage> current = load(context);
        current.add(message);
        save(context, current);
    }
    
    public static List<ChatMessage> load(Context context) {
        List<ChatMessage> list = new ArrayList<>();
        try {
            FileInputStream fis = context.openFileInput(FILE_NAME);
            int size = fis.available();
            if (size <= 0) {
                fis.close();
                return list;
            }
            byte[] bytes = new byte[size];
            fis.read(bytes);
            fis.close();
            JSONArray array = new JSONArray(new String(bytes));
            for (int i = 0; i < array.length(); i++) {
                JSONObject obj = array.getJSONObject(i);
                list.add(new ChatMessage(obj.getString("text"), obj.getBoolean("isUser")));
            }
        } catch (FileNotFoundException ignored) {
        } catch (Exception e) {
            Log.e("ChatHistory", "Load failed", e);
        }
        return list;
    }

    public static void clear(Context context) {
        context.deleteFile(FILE_NAME);
    }
}
