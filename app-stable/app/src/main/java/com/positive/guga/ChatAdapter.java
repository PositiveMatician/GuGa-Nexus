package com.positive.guga;

import android.graphics.Color;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class ChatAdapter extends RecyclerView.Adapter<ChatAdapter.ChatViewHolder> {
    private static final int TYPE_USER = 1;
    private static final int TYPE_BOT = 2;

    private final List<ChatMessage> allMessages;
    private final List<ChatMessage> filteredMessages = new java.util.ArrayList<>();
    private final Set<Integer> selectedPositions = new HashSet<>();
    private boolean isSelectionMode = false;
    private OnSelectionChangeListener selectionChangeListener;
    private String currentRegex = "";

    public interface OnSelectionChangeListener {
        void onSelectionChanged(int count);
        void onSelectionModeChanged(boolean active);
    }

    public interface OnItemClickListener {
        void onItemClick(ChatMessage message, int position);
    }

    private OnItemClickListener itemClickListener;

    public void setOnItemClickListener(OnItemClickListener listener) {
        this.itemClickListener = listener;
    }

    public List<ChatMessage> getFilteredMessages() {
        return filteredMessages;
    }

    public ChatAdapter(List<ChatMessage> messages) {
        this.allMessages = messages;
        applyFilter("");
    }

    public void setFilter(String regex) {
        this.currentRegex = regex != null ? regex : "";
        applyFilter(currentRegex);
        notifyDataSetChanged();
    }

    private void applyFilter(String regex) {
        filteredMessages.clear();
        if (regex.isEmpty() || regex.equals("*")) {
            filteredMessages.addAll(allMessages);
        } else {
            try {
                java.util.regex.Pattern pattern = java.util.regex.Pattern.compile(regex, java.util.regex.Pattern.CASE_INSENSITIVE);
                for (ChatMessage m : allMessages) {
                    String title = m.getTitle();
                    if (title != null && pattern.matcher(title).find()) {
                        filteredMessages.add(m);
                    } else if (m.isUser()) {
                        // Keep user messages usually? Or filter them too?
                        // User said: "apply it to titles only". User messages don't have titles.
                        // I'll show user messages always, or only if they match (which they won't).
                        // I'll stick to: if title is present and matches OR if it's a user message (optional).
                        // Let's re-read: "apply it to titles only".
                        // I'll only show bot messages that match, AND all user messages for context.
                        filteredMessages.add(m);
                    }
                }
            } catch (Exception e) {
                // Invalid regex, show all
                filteredMessages.addAll(allMessages);
            }
        }
    }

    public void onMessageAdded() {
        int oldSize = filteredMessages.size();
        applyFilter(currentRegex);
        int newSize = filteredMessages.size();
        if (newSize > oldSize) {
            notifyItemInserted(newSize - 1);
        }
    }

    public void setOnSelectionChangeListener(OnSelectionChangeListener listener) {
        this.selectionChangeListener = listener;
    }

    @Override
    public int getItemViewType(int position) {
        return filteredMessages.get(position).isUser() ? TYPE_USER : TYPE_BOT;
    }

    @NonNull
    @Override
    public ChatViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        int layout = (viewType == TYPE_USER) ? R.layout.chat_item_usr : R.layout.chat_item_bot;
        View view = LayoutInflater.from(parent.getContext()).inflate(layout, parent, false);
        return new ChatViewHolder(view);
    }

    @Override
    public void onBindViewHolder(@NonNull ChatViewHolder holder, int position) {
        ChatMessage msg = filteredMessages.get(position);
        holder.messageText.setText(msg.getText());
        
        if (holder.titleText != null) {
            String title = msg.getTitle();
            if (title != null && !title.isEmpty()) {
                holder.titleText.setText(title);
                holder.titleText.setVisibility(View.VISIBLE);
            } else {
                holder.titleText.setVisibility(View.GONE);
            }
        }

        // Selection Visual State
        boolean isSelected = selectedPositions.contains(position);
        if (isSelected) {
            holder.itemView.setBackgroundColor(Color.WHITE);
            holder.messageText.setTextColor(Color.BLACK);
            if (holder.titleText != null) holder.titleText.setTextColor(Color.parseColor("#444444"));
        } else {
            holder.itemView.setBackgroundColor(Color.TRANSPARENT);
            holder.messageText.setTextColor(Color.WHITE);
            if (holder.titleText != null) holder.titleText.setTextColor(Color.GRAY);
        }
        holder.selectionOverlay.setVisibility(View.GONE);

        // Click Listeners
        holder.itemView.setOnClickListener(v -> {
            if (isSelectionMode) {
                toggleSelection(position);
            } else if (itemClickListener != null) {
                itemClickListener.onItemClick(msg, position);
            }
        });

        holder.itemView.setOnLongClickListener(v -> {
            if (!isSelectionMode) {
                setSelectionMode(true);
                toggleSelection(position);
                return true;
            }
            return false;
        });
    }

    public void setSelectionMode(boolean active) {
        if (this.isSelectionMode == active) return;
        this.isSelectionMode = active;
        if (!active) selectedPositions.clear();
        notifyDataSetChanged();
        if (selectionChangeListener != null) {
            selectionChangeListener.onSelectionModeChanged(active);
        }
    }

    public boolean isSelectionMode() {
        return isSelectionMode;
    }

    private void toggleSelection(int position) {
        if (selectedPositions.contains(position)) {
            selectedPositions.remove(position);
        } else {
            selectedPositions.add(position);
        }
        notifyItemChanged(position);
        if (selectionChangeListener != null) {
            selectionChangeListener.onSelectionChanged(selectedPositions.size());
        }
        if (selectedPositions.isEmpty()) {
            setSelectionMode(false);
        }
    }

    public List<ChatMessage> getSelectedMessages() {
        List<ChatMessage> selected = new java.util.ArrayList<>();
        for (Integer pos : selectedPositions) {
            selected.add(filteredMessages.get(pos));
        }
        return selected;
    }

    public Set<Integer> getSelectedPositions() {
        return new HashSet<>(selectedPositions);
    }

    @Override
    public int getItemCount() {
        return filteredMessages.size();
    }

    static class ChatViewHolder extends RecyclerView.ViewHolder {
        TextView messageText;
        TextView titleText;
        View selectionOverlay;

        ChatViewHolder(View itemView) {
            super(itemView);
            messageText = itemView.findViewById(R.id.messageText);
            titleText = itemView.findViewById(R.id.titleText);
            selectionOverlay = itemView.findViewById(R.id.selectionOverlay);
        }
    }
}
