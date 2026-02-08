DANGEROUS_ACTIONS = {
    "POST_EXTERNAL", "RUN_SHELL", "DELETE_FILES", "SPEND_MONEY", "SEND_EMAIL"
}

def needs_approval(action_type: str) -> bool:
    return action_type in DANGEROUS_ACTIONS
