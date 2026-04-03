package com.positive.guga;

public class ChatMessage {
    private String text;
    private String title;
    private boolean isUser;

    public ChatMessage(String text, boolean isUser) {
        this(text, null, isUser);
    }

    public ChatMessage(String text, String title, boolean isUser) {
        this.text = text;
        this.title = title;
        this.isUser = isUser;
    }

    public String getText() { return text; }
    public String getTitle() { return title; }
    public boolean isUser() { return isUser; }
}
