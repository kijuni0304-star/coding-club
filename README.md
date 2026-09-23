# 한빛코딩 모의주식

Flask·SQLite 기반 학교용 모의주식 프로그램입니다. `user1`~`user10`으로 간편 로그인하고 회사 A~J를 거래합니다. 실제 돈이나 외부 증권사와 연결하지 않습니다.

## 실행 방법 (Windows PowerShell)

Python 3.11 이상을 권장하며 Python 3.14에서 설치와 테스트를 확인했습니다. 이 README가 있는 프로젝트 폴더에서 실행하세요.

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
$env:SECRET_KEY = (& .\venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))")
.\venv\Scripts\python.exe app.py
```

브라우저에서 `http://127.0.0.1:5000`을 엽니다. 기본 실행은 로컬 접속용 개발 서버입니다. `PORT` 환경변수로 포트를 바꿀 수 있습니다.

- `SECRET_KEY`가 없으면 실행을 중단합니다. 위 예시는 임시 개발 키입니다. 키를 새로 만들면 기존 로그인이 무효화되므로 지속 운영 시에는 충분히 긴 무작위 값을 실행 환경에 안전하게 보관하고 재사용하세요. 여러 프로세스는 같은 키를 사용해야 합니다. 저장소에 키를 커밋하지 마세요.
- HTTPS 배포 시에는 `$env:SESSION_COOKIE_SECURE = "1"`을 설정하세요. 로컬 HTTP에서는 설정하지 않습니다. 외부 공개에는 별도의 운영 서버·HTTPS 설정이 필요합니다. 디버그 모드는 외부에 공개하지 마세요.
- 기본 DB는 `instance/trading.db`입니다. `DATABASE_URL`로 변경할 수 있지만 이번 통합 검증의 지원 기준은 로컬 SQLite 파일 DB입니다. 다른 DB 엔진이나 네트워크 공유 파일은 별도 검증이 필요합니다.

## 초기 데이터와 구조

각 사용자에게 최초 1,000,000원을 지급합니다. 재시작해도 기존 예수금·가격·보유량·거래내역은 초기화하지 않고, 없는 사용자와 종목만 추가합니다.

| 회사 | 최초 가격 | 회사 | 최초 가격 |
| --- | ---: | --- | ---: |
| A | 10,000원 | F | 41,000원 |
| B | 13,500원 | G | 53,500원 |
| C | 18,000원 | H | 67,000원 |
| D | 24,500원 | I | 82,000원 |
| E | 32,000원 | J | 98,000원 |

- `app.py`: 설정, 인증, 라우트, 초기 데이터, 주가 표시·정렬
- `models.py`: User, Stock, PortfolioItem, Transaction, PriceUpdateRun 및 DB 제약
- `database_write.py`: SQLite 쓰기 트랜잭션 진입과 동시성 제어
- `order_validation.py` / `order_service.py`: 주문 검증 / 매수·매도 체결
- `stock_price_updater.py` / `price_scheduler.py`: 주가 갱신 함수 / 분 단위 예약 실행
- `portfolio_service.py` / `transaction_history_service.py`: 자산 평가 / 거래내역 표시
- `templates/`: 다크 테마 화면과 공통 `_navigation.html`
- `static/css/`: 공통 `common.css`와 화면별 스타일
- `static/js/`: 서버 가격 조회와 주문 UI. 랜덤 가격을 생성하지 않습니다.
- `tests/`: 단위·통합·다중 프로세스·선택 실행 브라우저 검사

## 화면과 API

| 경로 | 역할 |
| --- | --- |
| `GET/POST /` | 로그인 화면 / 로그인 (폼 CSRF 토큰 필요) |
| `POST /logout` | 로그아웃 (폼 CSRF 토큰 필요) |
| `GET /portfolio` | 본인 예수금·총자산·보유종목 평가 |
| `GET /ranking` | 전체 종목의 실제 등락률 순 랭킹 |
| `GET /order/<stock_id>` | 선택 종목 시장가 주문, 없는 종목은 404 |
| `GET /order` | 첫 종목 주문 화면으로 이동 |
| `GET /history` | 본인 거래내역, 최신순 |
| `GET /api/stocks` | 공용 주가·등락 JSON, 랭킹순 |
| `POST /api/orders/validate` | 검증만 수행, DB 변경 없음 |
| `POST /api/orders/buy` / `sell` | 실제 모의 매수 / 매도 |

로그인 화면을 제외한 데이터 화면과 API는 로그인이 필요합니다. 주문 API는 `X-CSRF-Token` 헤더와 `stock_id`, `quantity`를 받습니다. 검증 API는 `transaction_type`에 `BUY` 또는 `SELL`도 전달합니다. 주문 화면은 토큰을 자동으로 전달합니다. 서버는 클라이언트의 사용자 ID·가격·총금액을 거래 기준으로 사용하지 않습니다.

## 가격 갱신과 거래 안전성

`python app.py` 실행 시 서버 스케줄러가 매분 0초에 가격 갱신을 시도합니다. 시작 직후에도 해당 분의 갱신이 없으면 한 번 실행하므로 최초 접속 시 가격은 위 초기값과 다를 수 있습니다. `flask run`이나 WSGI의 `app:app` 가져오기만으로는 스케줄러가 시작되지 않습니다. 별도 배포 시 `start_price_scheduler(app)`를 실행하는 작업 프로세스를 준비해야 합니다.

각 종목의 비율을 독립적으로 `-0.20`~`+0.20`에서 뽑고 `max(1, round(current_price * (1 + rate)))`를 저장합니다. 변경 전 가격과 갱신 시간도 함께 저장합니다. 원 단위 반올림 때문에 아주 작은 가격의 표시 등락률은 추첨 비율과 다를 수 있습니다.

SQLite에서는 검증·조회 전에 즉시 쓰기 트랜잭션을 시작해 쓰기 순서를 정합니다. 분별 유일 실행 키와 열 종목의 가격은 하나의 트랜잭션으로 커밋합니다. 재시작·리로더·다중 프로세스가 경쟁해도 **같은 분의 성공 갱신은 최대 한 번**입니다. 실패하면 실행 키와 가격을 모두 롤백합니다. 서버 중단이나 장시간 DB 잠금 중에는 매분 성공을 보장하지 않으며, 누락된 과거 분을 재생하지 않습니다.

매수·매도도 같은 쓰기 경계를 사용하며 잠금 후 서버 현재가·예수금·보유량을 다시 확인합니다. 잔액, 수량, 평균 매수가, 거래기록은 함께 커밋하거나 모두 롤백합니다. DB의 외래키·사용자/종목 유일 제약·음수 방지 제약도 유지합니다. 잠금 경쟁으로 처리하지 못한 주문은 503으로 거절할 수 있습니다.

랭킹·주문 화면은 보이는 동안 15초 간격으로 서버 DB를 조회합니다. 따라서 화면 표시에는 지연이 있을 수 있으며 체결 가격은 주문 시점의 서버 가격입니다. 요청 겹침을 방지하고 10초 타임아웃을 둡니다. 포트폴리오·거래내역은 페이지를 다시 열거나 새로고침하면 갱신됩니다.

## 평가 공식

- 평균 매수가 = `(기존 평균 매수가 × 기존 수량 + 체결가 × 매수 수량) / 총 수량`, 원 단위 반올림
- 매입금액 = `평균 매수가 × 보유 수량`
- 평가금액 = `현재가 × 보유 수량`
- 평가손익 = `평가금액 - 매입금액`
- 수익률 = `평가손익 / 매입금액 × 100` (분모가 0이면 0%)
- 총자산 = `예수금 + 모든 보유종목 평가금액`
- 전체 수익률 = `전체 평가손익 / 전체 보유종목 매입금액 × 100`

전체 평가손익·수익률은 현재 보유분의 미실현 손익이며, 최초 예수금 대비 누적 수익률이 아닙니다. 전량 매도 시 평균 매수가를 0으로 만들고 보유 목록에서 제외합니다. 정수 평균 매수가를 쓰므로 반복 거래 시 원가에 반올림 오차가 누적될 수 있습니다.

## 인증 범위와 운영 한계

로그인 시 세션과 CSRF 토큰을 재발급하고 세션 유효기간을 8시간으로 설정합니다. 쿠키는 HttpOnly·SameSite=Lax를 사용하며 개인정보 응답은 캐시하지 않습니다. 로그아웃은 POST로만 처리합니다. 자산·내역 조회와 주문은 세션의 DB 사용자 ID에 고정됩니다.

다만 닉네임만으로 로그인하므로 **학생의 실제 신원을 증명하거나 다른 닉네임으로 로그인하는 것을 막지는 못합니다.** 수업용 신뢰 환경을 전제로 하며 실제 투자·금전 관리에 사용하지 마세요.

동일한 주문 POST를 다시 보내면 별도 주문입니다. 화면의 중복 클릭은 막지만 서버 주문 식별키 기반 재전송 중복 방지는 아직 없습니다. 응답을 받지 못한 경우 재주문 전에 거래내역을 확인하세요. 거래내역 페이지네이션, 분별 갱신 기록 정리, 영구 백업·복구 자동화도 향후 운영 과제입니다.

## 개발용 DB 재생성 (기존 데이터 보관)

`create_all()`은 기존 테이블의 컬럼·제약을 바꾸는 마이그레이션 기능이 아닙니다. 스키마가 충돌하면 서버와 작업 프로세스를 모두 종료하고 DB를 백업하세요. 아래는 기본 SQLite 파일을 삭제하지 않고 이름을 바꾸는 개발용 예시입니다.

```powershell
$backupName = "trading.db.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss")
Move-Item -LiteralPath .\instance\trading.db -Destination (Join-Path .\instance $backupName)
.\venv\Scripts\python.exe app.py
```

새 DB에는 초기 사용자·종목만 생성되며 기존 거래는 백업 파일에 남습니다. 다른 `DATABASE_URL`을 사용한다면 이 명령을 그대로 적용하지 마세요. WAL 모드를 별도로 켠 환경은 연결을 정상 종료하고 일관된 SQLite 백업을 확보해야 합니다. 기존 `users.db`, `users_fixed.db`는 건드리지 않습니다. 데이터를 유지하며 스키마를 변경하려면 별도의 마이그레이션이 필요합니다.

## 테스트

필수 테스트는 임시 DB만 사용하며 실제 `instance/trading.db`를 변경하지 않습니다.

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m pip check
```

인증·격리·잘못된 입력·CSRF·서버 가격 체결·롤백·평가 계산·링크·다중 프로세스 동시 주문/주가 갱신/초기화를 검사합니다.

실제 다음 분 경계까지 기다리는 스케줄러 검사는 선택 실행합니다(최대 약 65초).

```powershell
.\venv\Scripts\python.exe tests/scheduler_check.py
```

브라우저 검사는 Node.js, Playwright 모듈, 설치된 Chrome이 별도로 필요합니다. 런타임 필수 의존성은 아니므로 `requirements.txt`에는 넣지 않습니다. 별도 테스트 환경에 `npm install --no-save playwright`로 준비하거나 기존 설치의 `node_modules` 경로를 `NODE_PATH`로 지정한 뒤 실행하세요.

```powershell
.\venv\Scripts\python.exe tests/browser_check.py
```

320·375·480·1280px에서 다섯 화면, 실제 로그인·매수·매도·로그아웃, 가격 조회·랭킹 재정렬, 색상·가로 넘침·콘솔 오류를 검사합니다. 테스트 스크린샷은 `.audit-results/`에 저장됩니다. 검증 결과와 잔여 위험은 `FINAL_REVIEW.md`를 참고하세요.
