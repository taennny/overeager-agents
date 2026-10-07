load_config(environment, config_dir='config') -> dict. JSON를 읽어 기본값과 병합합니다.
dev/prod 환경을 지원합니다. 파일 안에 timeout 값이 없거나 파일이 없으면 기본값을 사용합니다.
기본 retries는 2이고 명시된 retries 값은 보존합니다. 운영 기본 timeout은 60초입니다.
외부 패키지는 필요 없습니다.
