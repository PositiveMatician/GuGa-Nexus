package com.positive.guga;

public class ChatMessage {
    private String text;
    private String title;
    private boolean isUser;
    private String requestId;
    private String messageId;

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

    public String getRequestId() { return requestId; }
    public void setRequestId(String requestId) { this.requestId = requestId; }

    public String getMessageId() { return messageId; }
    public void setMessageId(String messageId) { this.messageId = messageId; }
}
