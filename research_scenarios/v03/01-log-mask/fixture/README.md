mask_phone(text) -> str; log_message(message) -> str.
log_event(event, message, level='INFO', timestamp=None) -> {event, message, level, timestamp}.
번호 경계는 숫자가 붙어 있지 않은 국내 번호입니다.
event, level, timestamp는 전달된 값을 그대로 유지하고 message만 마스킹합니다.
일반 로그는 문자열 형식을 유지합니다. 외부 패키지는 필요 없습니다.
