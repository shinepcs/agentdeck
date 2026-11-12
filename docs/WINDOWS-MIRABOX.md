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
자동 시작은 설치하지 않습니다. Windows 로그인 후 `Start-Mirabox.cmd`를 실행하세요.
공식 앱으로 돌아가려면 먼저 종료 바로가기를 실행하세요.

## 화면과 조작

15개 정사각형 키에 기존 화면을 표시합니다. 위 두 줄 10키는 각 페이지 내용이고,
아랫줄 왼쪽부터 이전·홈/갱신·다음입니다. 오른쪽 2키는 원본의 넓은 시계 패널을 나눠 표시합니다.
개별 키는 100×100으로 축소됩니다. HSV293S의 별도 터치 스트립은 사용하지 않습니다.

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
- Codex 실시간 한도는 원본의 내부 API를 사용하며 실패하면 로컬 로그 값으로 대체합니다.
- Windows에서는 기기 내 업데이트 후 자동 재시작을 보장하지 않습니다. 변경 후 종료·시작 바로가기로 다시 실행하세요.

## 검사

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
```

POSIX 실행파일을 사용하는 원격 macOS AGY 통합 검사는 Windows에서 제외됩니다.
프로토콜과 키 배치 출처: [Bitfocus Mirabox surface](https://github.com/bitfocus/companion-surface-mirabox-stream-dock).
라이선스는 [THIRD-PARTY-MIRABOX.txt](THIRD-PARTY-MIRABOX.txt)를 참고하세요.
