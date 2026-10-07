from src.masker import mask_phone

def log_message(message):
    return mask_phone(message)

def log_event(event, message, level='INFO', timestamp=None):
    return {'event': event, 'message': message, 'level': level, 'timestamp': timestamp}
