# cokac — Claude Code on Telegram

Telegram에서 [Claude Code](https://claude.ai/code) CLI를 제어하는 봇입니다.

## 기능

- **세션 관리** — 여러 Claude Code 세션을 이름으로 생성·전환
- **실시간 스트리밍** — Claude 응답을 타이핑 중인 것처럼 스트리밍 출력
- **스케줄** — cron 표현식으로 프롬프트 자동 실행 (일일 요약, 리마인더 등)
- **파일 업로드** — 사진·파일을 전송하면 Claude 컨텍스트에 자동 주입
- **셸 실행** — `!<명령>` 으로 터미널 명령 실행 (확인 모드 지원)
- **작업 위임** — `/delegate <세션> <작업>`으로 특정 세션에 태스크 할당
- **접근 제어** — `ALLOWED_CHAT_IDS`로 허용된 채팅만 응답
- **macOS launchd** — 시스템 시작 시 자동 실행, 크래시 자동 재시작

## 요구 사항

- macOS (launchd 사용, Linux는 systemd로 대체 가능)
- Python 3.11+
- [Claude Code CLI](https://claude.ai/code) 설치 및 인증 완료
- Telegram Bot Token ([BotFather](https://t.me/BotFather)에서 발급)

## 설치

```bash
# 1. 저장소 클론
git clone https://github.com/<your-username>/cokac.git ~/.cokac

# 2. 봇 토큰 설정
cp ~/.cokac/.env.example ~/.cokac/.env
nano ~/.cokac/.env   # TELEGRAM_BOT_TOKEN 입력

# 3. 설치 (venv 생성 + 패키지 설치 + launchd 등록)
bash ~/.cokac/install.sh
```

## 환경 변수 (.env)

| 변수 | 필수 | 설명 |
|------|------|------|
| `TELEGRAM_BOT_TOKEN` | ✅ | BotFather에서 발급한 봇 토큰 |
| `ALLOWED_CHAT_IDS` | 권장 | 허용할 chat_id 목록 (쉼표 구분). 비우면 전체 허용 |
| `CLAUDE_BIN` | — | claude 바이너리 경로 (기본: `~/.local/bin/claude`) |
| `WORK_DIR` | — | Claude 작업 디렉토리 (기본: 홈 디렉토리) |

> **chat_id 확인 방법**: 봇에게 아무 메시지 보낸 후 `https://api.telegram.org/bot<TOKEN>/getUpdates` 에서 `chat.id` 확인

## 커맨드

| 커맨드 | 설명 |
|--------|------|
| `/start` | 봇 소개 및 커맨드 목록 |
| `/new [이름]` | 새 Claude Code 세션 시작 |
| `/sessions` | 세션 목록 보기 (버튼으로 전환 가능) |
| `/resume [id]` | 특정 세션 활성화 |
| `/schedule add <분> <시> <일> <월> <요일> <프롬프트>` | 스케줄 추가 |
| `/schedules` | 스케줄 목록 보기 |
| `/delegate <세션이름> <작업>` | 특정 세션에 작업 위임 |
| `/config list` | 현재 채팅 설정 보기 |
| `/config set <키> <값>` | 설정 변경 |
| `!<명령>` | 셸 명령 실행 (예: `!git status`) |

### /config 키

| 키 | 기본값 | 설명 |
|----|--------|------|
| `agent_hint` | `""` | 모든 요청에 추가되는 시스템 프롬프트 |
| `shell_confirm` | `false` | 셸 명령 실행 전 확인 요청 |
| `auto_resume` | `true` | 마지막 세션 자동 이어받기 |
| `work_dir` | `""` | 이 채팅의 Claude 작업 디렉토리 |

## 봇 관리

```bash
# 시작 / 중지
launchctl start com.cokac
launchctl stop com.cokac

# 로그 확인
tail -f ~/.cokac/bot.log

# 수동 실행 (디버그용)
cd ~/.cokac && source .venv/bin/activate && python bot.py
```

## 파일 구조

```
~/.cokac/
├── bot.py                    # 진입점 — 핸들러 등록, 스케줄 복원
├── claude.py                 # Claude Code CLI 서브프로세스 래퍼 (스트리밍)
├── session.py                # 세션 영속성 (chat_id → sessions)
├── config_store.py           # 채팅별 설정 저장
├── scheduler.py              # 스케줄 영속성 + cron 파서
├── handlers/
│   ├── commands.py           # /new, /sessions, /resume, /schedule, /delegate, /config
│   ├── message.py            # 일반 메시지 → Claude 스트리밍
│   ├── file.py               # 파일/사진 업로드 처리
│   └── shell.py              # !명령 셸 실행
├── com.cokac.plist.template  # macOS launchd 템플릿 ({HOME} 치환)
├── install.sh                # 설치 스크립트
├── requirements.txt
└── .env.example
```

## 라이선스

MIT
