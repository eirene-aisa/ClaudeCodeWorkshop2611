# 공개 배포 (CloudFront + S3 + Lambda)

```
브라우저 ─HTTPS─▶ CloudFront ─┬─ /*     → S3 (비공개 버킷, OAC)
                               └─ /api/* → Lambda 함수 URL (AWS_IAM, OAC) → 청약홈 분양정보 API
```
- 판정·공고 로직은 플러그인 코드를 그대로 묶어 배포합니다(`build.sh`).
- 인증키는 SSM SecureString(`/applyhome/api-key`) → Lambda 모듈 변수. 환경변수·응답·로그에 없습니다.
- 요청 본문은 기록하지 않고(로그 보존 1일, 시작·종료 줄만), 판정 응답은 `no-store`, 공고 응답만 5분 캐시합니다.
- 동시 실행 상한 5, 에이전트 실행(claude -p)은 공개판에 없습니다(403).
- Lambda URL·S3 직접 호출은 403. 브라우저는 POST 본문 SHA-256을 `x-amz-content-sha256`으로 보냅니다(OAC 서명용).

## 절차
1. `bash deploy/build.sh` → `deploy/build/lambda.zip`
2. `bash deploy/put-key.sh` → `~/.claude.json`의 키를 SSM으로 복사(화면·명령행에 노출 없음)
3. `template.yaml`로 스택 `applyhome-public` 생성(CAPABILITY_IAM)
4. Lambda 코드 갱신(`UpdateFunctionCode`, 임시 S3 키에서 가져온 뒤 즉시 삭제)
5. `web/static/*`를 버킷 루트에 업로드(Cache-Control: no-cache) → CloudFront `/*` 무효화
6. 확인: `python3 -I deploy/test_handler.py`, 공개 주소에서 status·notices·judge, 직접 호출 403

## 삭제
버킷을 비운 뒤 스택 `applyhome-public` 삭제, SSM 파라미터 `/applyhome/api-key` 삭제.
