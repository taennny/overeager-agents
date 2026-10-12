# EXAONE·Qwen3-8B 로컬 서빙 / 상용 API 연결

## 현재 상태

2026-09-30 확인: 현재 작업 컴퓨터는 macOS arm64, Python 3.9.6이며 NVIDIA 도구·vLLM·연구용 API 환경변수가 없습니다. Docker Desktop 엔진은 실행 가능함을 확인했습니다. **실제 모델 서빙과 상용 API 호출은 검증 전**입니다.

여기서 ‘로컬 서빙’은 연구용 GPU 서버에서 직접 모델을 돌린다는 뜻입니다. macOS용 vLLM-Metal도 공식 문서에 별도로 안내되어 있지만, NVIDIA 서버와는 다른 실행 환경이므로 이번 배포 레시피를 대체한 것으로 간주하지 않습니다. [공식 설치 문서](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)

## 먼저 확보할 정보

- GPU 서버 SSH 주소·사용자, GPU 이름·메모리 용량, 드라이버 버전.
- 정확한 EXAONE 버전과 크기. 계획서의 ‘EXAONE’만으로는 모델을 결정할 수 없습니다.
- 상용 API 제공사, OpenAI 호환 base URL, 사용할 모델 ID, 소액 연결 테스트 예산.
- 키는 채팅·Notion·Git에 붙이지 않고 해당 서버의 환경변수로 설정합니다.

한 장의 GPU에는 모델을 순차적으로 올리는 방식을 기본으로 합니다. 모델 파라미터의 단순 메모리 계산만으로 실행 가능성을 판단하지 않고 KV cache, 컨텍스트 길이, 실행 오버헤드를 포함해 실제 로딩으로 확인합니다.

## 1. Linux NVIDIA 서버 준비

서버에서 GPU와 Python을 확인합니다.

```bash
nvidia-smi
python3.12 --version
```

연구 전용 가상환경을 만든 뒤 GPU 드라이버에 맞는 vLLM 버전을 설치합니다. 버전 번호는 서버 확인 없이 임의로 확정하지 않았습니다. 아래 `VLLM_VERSION`에 팀이 선택한 실제 버전을 넣으세요. 공식 GPU 설치 문서는 새 가상환경과 CUDA/PyTorch 호환성 확인을 안내합니다. [설치 근거](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)

```bash
python3.12 -m venv .venv-serving
source .venv-serving/bin/activate
python -m pip install --upgrade pip
export VLLM_VERSION='여기에_검토한_실제_버전'
python -m pip install "vllm==$VLLM_VERSION"
python -m pip freeze > serving-lock.txt
```

EXAONE 4.0 공식 모델 카드는 vLLM 0.10.0 지원을 명시합니다. 이는 GPU 환경 확인 없이 0.10.0을 무조건 설치하라는 뜻은 아닙니다. 모델별 chat template와 추론 모드도 기록해야 합니다. [EXAONE 모델 카드](https://huggingface.co/LGAI-EXAONE/EXAONE-4.0-1.2B)

## 2. 키 관리

연구 프로젝트에서 `.env.example`을 `.env`로 복사하고 로컬 편집기로 입력합니다. 실제 파일을 이미 만들었다면 덮어쓰지 않습니다.

```bash
cp -n .env.example .env
chmod 600 .env
set -a
source .env
set +a
```

`.env`는 로컬에서 작성한 신뢰 가능한 셸 설정 파일입니다. 외부에서 받은 파일을 확인 없이 source하지 마세요. 따옴표로 값을 감싸고, 실제 키를 명령 인자나 테스트 결과에 넣지 않습니다. 예시에는 키가 비어 있으며 실제 키를 자동 생성·발급하지 않았습니다.

키 역할은 다음과 같습니다.

- `VLLM_API_KEY`: GPU 서버 접근 토큰. 서버와 클라이언트에 같은 값을 설정합니다.
- `COMMERCIAL_API_KEY`: 선택한 외부 API 제공사에서 발급한 키.
- `COMMERCIAL_BASE_URL`, `COMMERCIAL_MODEL`: 키와 짝이 맞는 제공사의 endpoint와 모델.

키가 모델의 messages나 에이전트 컨테이너 환경으로 들어가면 안 됩니다. 이 클라이언트는 호스트 환경변수에서 키를 읽어 HTTP Authorization 헤더에만 넣습니다. 오류 응답 원문과 헤더는 로그에 저장하지 않고, 자동 재시도도 하지 않습니다. 환경의 HTTP 프록시와 리디렉션을 기본 차단합니다. 프록시를 꼭 써야 하는 환경은 별도 검토가 필요합니다.

## 3. Qwen 서버 실행

서버의 프로젝트 폴더에서:

```bash
export QWEN_MODEL='Qwen/Qwen3-8B'
bash serving/serve.sh qwen
```

기본값은 GPU 1장, 컨텍스트 4096, 메모리 사용 비율 0.85, loopback 포트 8000입니다. 실행 가능성이나 OOM 없음은 아직 검증하지 않았습니다. 공식 모델 카드는 vLLM 기반 호환 API 서빙과 thinking 모드를 안내합니다. 이 클라이언트의 Qwen smoke는 짧은 연결 확인을 위해 `enable_thinking=false`를 요청합니다. 본실험 설정과 별도로 기록하세요. [Qwen3-8B 모델 카드](https://huggingface.co/Qwen/Qwen3-8B)

## 4. 맥에서 서버로 연결

맥 터미널에서 실제 서버 주소로 SSH 포트 전달을 설정합니다. 비밀 키를 URL에 넣지 않습니다.

```bash
ssh -N -L 8000:127.0.0.1:8000 YOUR_USER@YOUR_GPU_HOST
```

다른 맥 터미널에서 프로젝트 환경변수를 읽은 뒤:

```bash
python3 -m scope_lab smoke --profile qwen --out artifacts/qwen-smoke.json
```

이 명령은 “READY라고 답하라”는 작은 요청을 실제 서버에 보냅니다. 로컬 문서나 저장소 내용은 전송하지 않습니다. 출력에 응답, 모델 식별자, 제공된 토큰 사용량, 처리 시간이 저장됩니다. `completed`는 연결 검증 성공이며 코딩 에이전트 기능 검증을 뜻하지 않습니다.

## 5. EXAONE 실행

GPU 한 장이라면 먼저 Qwen 서버를 종료하고 GPU 메모리 해제를 확인한 뒤 EXAONE을 실행합니다. 정확한 모델 ID는 팀이 결정해야 하므로 기본값을 강제로 넣지 않았습니다.

```bash
export EXAONE_MODEL='팀이_확정한_EXAONE_모델_ID'
bash serving/serve.sh exaone
```

클라이언트 환경에도 같은 `EXAONE_MODEL`을 설정한 뒤:

```bash
python3 -m scope_lab smoke --profile exaone --max-tokens 512 --out artifacts/exaone-smoke.json
```

실재하는 4.0 모델 식별자는 `LGAI-EXAONE/EXAONE-4.0-1.2B`, `LGAI-EXAONE/EXAONE-4.0-32B` 등이지만, 작은 모델을 편의상 선택하고 계획된 본실험 모델을 검증했다고 보고하면 안 됩니다. 크기·정밀도·revision과 vLLM 버전을 기록하세요. 추론 모드의 경우 reasoning parser와 출력 토큰 예산을 모델 카드에 맞게 별도로 설정해야 합니다. 현재 레시피는 기본 텍스트 연결 확인용이며 native tool calling까지 검증한 설정이 아닙니다.

## 6. 상용 API 연결

`.env`에 제공사가 안내한 HTTPS base URL(통상 `/v1` 포함), 실제 모델 ID, API 키를 입력합니다.

```bash
python3 -m scope_lab smoke --profile api --out artifacts/commercial-smoke.json
```

이 클라이언트는 **OpenAI 호환 Chat Completions endpoint**만 지원합니다. 자체 규격만 지원하는 API는 어댑터가 추가로 필요합니다. 모델에 따라 `max_tokens` 파라미터 지원이 다를 수 있으므로 사용 모델의 규격을 확인해야 합니다. 모든 상용 API가 그대로 작동한다고 보장하지 않습니다. 에러 응답은 상태 코드만 남기므로 제공사 대시보드에서 상세 원인을 확인하세요.

## 실제 완료 증거

세 smoke 결과의 `status=completed`, `finish_reason=stop`, 비어 있지 않은 응답을 확인합니다. 추가로 GPU에서 `nvidia-smi`, 설치 패키지 목록, 모델 ID·revision·dtype·컨텍스트 길이·추론 모드 기록을 남깁니다. 연결 실패를 성공 기록으로 혼동하지 않도록 smoke 시작 시 기존 출력 상태를 pending으로 바꾸며 실패 시 failed로 기록합니다.

**모의 HTTP 테스트가 통과해도 위 세 실제 모델 검증을 대체하지 않습니다.**
