# Windows + Mirabox HSV293S

이 포크는 Windows에서 USB ID `6603:1014`인 Mirabox HSV293S 계열을 지원합니다.
원본 D200 드라이버는 유지하며 `config.json`의 `"device": "mirabox"`로 선택합니다.
펌웨어를 바꾸지 않습니다. Stream Dock 공식 앱은 먼저 종료하세요.

## 설치와 실행

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.windows.example.json config.json
.\Start-Mirabox.cmd
```

이미 `config.json`이 있으면 복사하지 말고 필요한 설정만 합치세요.
종료는 `Stop-Mirabox.cmd`입니다. 로그는 `dashboard.log`, `dashboard-error.log`에 남습니다.
Windows 로그인 때 자동으로 시작하려면 다음 명령을 한 번 실행하세요.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/install-windows-startup.ps1
```

현재 사용자 시작프로그램 폴더에 `Agentdeck Mirabox.lnk`가 만들어집니다.
중복 실행은 방지합니다. 해제하려면 `shell:startup`에서 이 바로가기만 삭제하세요.
공식 앱으로 돌아가려면 먼저 종료 바로가기를 실행하세요.

## 화면과 조작

15개 정사각형 키에 기존 화면을 표시합니다. 위 두 줄 10키는 각 페이지 내용이고,
아랫줄 왼쪽부터 이전·홈/갱신·다음입니다. 오른쪽 2키는 원본의 넓은 시계 패널을 나눠 표시합니다.
각 키의 해상도는 100×100입니다. HSV293S의 별도 터치 스트립은 사용하지 않습니다.

정보 화면의 글자는 100×100에서 직접 그리며 **최소 16px 굵은 글꼴**을 사용합니다.
흐린 보조색은 배경 대비 **7:1 이상**의 밝은 대체색으로 올립니다. 긴 프로젝트명·안내는
글씨를 더 줄이지 않고 두 줄 또는 말줄임으로 표시합니다. CPU/RAM/DISK는 항목별 수치를 크게 보여주며,
3항목 게이지 칸의 보조 설명은 기기 상세에서 확인합니다. 하단 시계·타이머·안내는 두 키에 나눠 다시 배치합니다.
시작 애니메이션과 게임·어항의 그림에 포함된 글자는 기존 이미지 표시를 유지합니다.

Windows의 맑은 고딕·Segoe 글꼴, 로컬 CPU/메모리/디스크 상태,
페이지 이동·게임·어항·타이머를 기존 코드로 사용합니다.
타이머 완료는 Windows 알림음을 냅니다.

## 범위와 제한

- 지원 USB ID와 키 배치는 HSV293S용입니다. 다른 Mirabox 모델에 그대로 적용하지 마세요.
- Herdr, Mole 정리 기능과 macOS 터미널 창 이동, 배경음은 Windows에서 지원하지 않습니다.
  원격 Mac 설정과 소리 설정은 기본 예제에서 비활성화했습니다.
- 에이전트 상태는 훅 기록을 사용합니다. `.\.venv\Scripts\python.exe -X utf8 scripts/install-hooks.py --codex`로
  Claude Code 훅과 Codex 완료 알림을 연결합니다. 기존 연동은 보존하고 설정 백업을 남깁니다.
  훅을 설치하기 전 실행 중이던 세션에는 기록이 없을 수 있습니다.
- Claude 구독 한도는 [공식 status line 데이터](https://code.claude.com/docs/en/statusline#rate-limit-usage)의
  `rate_limits`를 Python 수집기가 저장합니다. 기존 status line 명령은 그대로 이어서 실행하고,
  초기 화면처럼 한도 데이터가 없는 입력은 기존 값을 지우지 않습니다. 최신 값은 Claude Code의
  작업 응답이나 `/usage` 조회 뒤 전달되며, Claude를 실행하지 않는 동안은 마지막 수집 값입니다.
- 짧은 작업이 끝나 프로세스가 종료돼도 완료·오류 알림은 최대 하루 유지합니다.
  기기에서 해당 작업을 누르면 기존 확인 처리로 깜빡임이 꺼집니다.
- Claude 알림은 **Claude Code 훅**에서 수집합니다. Claude 데스크톱의 일반 Chat이나
  웹 채팅은 이 훅을 발생시키지 않으므로 이 연결만으로 완료 알림이 들어오지 않습니다.
- Codex 실시간 한도는 원본의 내부 API를 사용하며 실패하면 로컬 로그 값으로 대체합니다.
- Windows에서는 기기 내 업데이트 후 자동 재시작을 보장하지 않습니다. 변경 후 종료·시작 바로가기로 다시 실행하세요.

## 로컬 네트워크의 Mac

Mac에서 원격 로그인(SSH)을 켜고 이 PC의 공개키를 Mac 계정의 `~/.ssh/authorized_keys`에 등록합니다.
개인키는 Windows PC에만 두고 비밀번호·개인키를 저장소에 넣지 마세요.
Windows의 `~/.ssh/config`에 해당 Mac 별칭을 등록하고 `ssh 별칭 hostname`으로 인증을 확인한 뒤,
Mac에도 `agent_hook.py`와 `statusline_hook.py`를 설치합니다. 설치기에는 Python 3.11 이상이 필요합니다.
Mac 훅 명령의 Python 경로는 SSH의 제한된 PATH에서도 찾을 수 있게 절대 경로를 사용하세요.

개인 `config.json`의 `hooks.hosts`에 `null`(이 PC)과 SSH 별칭을 함께 넣으면
작업 현황에 원격 프로젝트와 호스트 이름이 표시됩니다. `machines`에도 별칭을 추가하면 Mac 자원 상태를 봅니다.

```json
{
  "hooks": {"hosts": [null, "my-mac"]},
  "machines": [
    {"name": "This PC", "ssh": null, "mole": false},
    {"name": "Mac mini", "ssh": "my-mac", "mole": false}
  ]
}
```

Mac의 IP가 DHCP로 바뀌면 SSH 별칭의 HostName도 새 주소로 맞춰야 합니다.
Windows에서 원격 Mac 창을 직접 앞으로 가져오는 기능은 지원하지 않습니다.

## 검사

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
```

POSIX 실행파일을 사용하는 원격 macOS AGY 통합 검사는 Windows에서 제외됩니다.
프로토콜과 키 배치 출처: [Bitfocus Mirabox surface](https://github.com/bitfocus/companion-surface-mirabox-stream-dock).
라이선스는 [THIRD-PARTY-MIRABOX.txt](THIRD-PARTY-MIRABOX.txt)를 참고하세요.
