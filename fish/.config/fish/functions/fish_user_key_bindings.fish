function fish_user_key_bindings
    fish_vi_key_bindings

    # Copy the visual selection to the system clipboard.
    bind -M visual y fish_clipboard_copy
end
