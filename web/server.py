#!/usr/bin/env python3
"""청약 자격·공고 확인 로컬 웹 화면 서버 (표준 라이브러리만 사용).

  python3 -I web/server.py            # http://127.0.0.1:8765

가드레일
- 기본 127.0.0.1에만 바인딩하고 Host 헤더를 검사한다(DNS 리바인딩 방지).
- 인증키는 시작 시 ~/.claude.json의 applyhome MCP 등록값을 읽어 **메모리 변수**에만 둔다
  (환경변수에 넣지 않음 → /proc/<pid>/environ으로 노출되지 않음). 응답·로그에 내보내지 않는다.
- 요청 본문(개인 조건)은 로그에 남기지 않고 파일로 저장하지 않는다. 응답은 Cache-Control: no-store.
- 공고 조회는 MCP 서버 모듈의 검증 함수를 그대로 써서 비개인 필터만 API로 보낸다.
- 판정은 eligibility.py를 셸 없이(인자 목록) 실행해 같은 입력 검증을 거친다.
- "에이전트 실행"은 workspace에서 claude -p로 플러그인 스킬을 돌린다(플러그인 훅이 그대로 적용됨).
"""
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugins", "applyhome-kit")
WORKSPACE = os.path.join(ROOT, "workspace")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
ELIG = os.path.join(PLUGIN, "scripts", "eligibility.py")

HOST = os.environ.get("APPLYHOME_WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("APPLYHOME_WEB_PORT", "8765"))
# CloudFront 등 앞단 프록시에서 들어오는 Host 이름(쉼표 구분). 기본은 로컬만.
EXTRA_HOSTS = [h.strip() for h in os.environ.get("APPLYHOME_WEB_ALLOWED_HOSTS", "").split(",") if h.strip()]
MAX_BODY = 8 * 1024
AGENT_TIMEOUT = 900

spec = importlib.util.spec_from_file_location("applyhome_mcp", os.path.join(PLUGIN, "mcp", "applyhome_server.py"))
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


def load_key_from_user_config():
    """~/.claude.json에서 applyhome MCP의 APPLYHOME_API_KEY를 찾는다(workspace 프로젝트 우선)."""
    path = os.path.expanduser("~/.claude.json")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return None
    candidates = []
    projects = cfg.get("projects") or {}
    if isinstance(projects, dict):
        if WORKSPACE in projects:
            candidates.append(projects[WORKSPACE])
        candidates += [v for k, v in projects.items() if k != WORKSPACE]
    candidates.append(cfg)
    for c in candidates:
        try:
            k = c["mcpServers"]["applyhome"]["env"]["APPLYHOME_API_KEY"]
        except (KeyError, TypeError):
            continue
        if isinstance(k, str) and k.strip():
            return k.strip()
    return None


AGENT_LOCK = threading.Lock()
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/app.css": ("app.css", "text/css; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8")}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
NOTICE_ARGS = {"sido", "sigungu", "house_type", "only_open", "date_from", "date_to", "page"}


def run_eligibility(profile):
    if not isinstance(profile, dict):
        return 400, {"error": "프로필은 객체여야 합니다"}
    args = []
    for k, v in profile.items():
        if v in (None, ""):
            continue
        if not isinstance(k, str) or not k.replace("_", "").isalnum():
            return 400, {"error": "허용되지 않은 항목 이름"}
        v = "true" if v is True else "false" if v is False else str(v)
        args.append(f"{k}={v}")
    p = subprocess.run([sys.executable, "-I", ELIG, *args], capture_output=True, text=True, timeout=20)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        return 500, {"error": "판정 스크립트 응답을 해석할 수 없습니다"}
    return (200 if p.returncode == 0 else 400), out


def agent_prompt(profile, sigungu):
    kv = " ".join(f"{k}={'true' if v is True else 'false' if v is False else v}"
                  for k, v in profile.items() if v not in (None, ""))
    region = profile.get("target_sido", "서울") + (f" {sigungu}" if sigungu else " 전체")
    return ("/applyhome-kit:check-eligibility\n"
            f"조회 지역은 {region}로 이미 골랐습니다. 조건은 아래 key=value로 모두 드리니 질문 단계는 건너뛰고 진행해 주세요"
            "(0단계의 구별 공고 수 확인은 해 주세요).\n" + kv)


def summarize_event(ev):
    """stream-json 이벤트를 화면용 단계로 줄인다(도구 입력의 개인 조건은 내보내지 않음)."""
    t = ev.get("type")
    if t == "assistant":
        steps = []
        for c in ev.get("message", {}).get("content", []) or []:
            if c.get("type") != "tool_use":
                continue
            name, inp = c.get("name", ""), c.get("input") or {}
            if name in ("Agent", "Task"):
                steps.append({"kind": "agent", "label": inp.get("subagent_type", "agent")})
            elif name.startswith("mcp__applyhome__"):
                shown = {k: v for k, v in inp.items() if k in NOTICE_ARGS | {"house_manage_no", "pblanc_no"}}
                steps.append({"kind": "mcp", "label": name.replace("mcp__applyhome__", ""), "detail": shown})
            elif name == "Bash":
                steps.append({"kind": "tool", "label": "판정 스크립트 실행" if "eligibility.py" in inp.get("command", "") else "Bash"})
            else:
                steps.append({"kind": "tool", "label": name})
        return steps
    if t == "user":
        out = []
        for c in ev.get("message", {}).get("content", []) or []:
            if c.get("type") == "tool_result" and c.get("is_error"):
                text = c.get("content")
                text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
                out.append({"kind": "blocked", "label": mcp._mask(text)[:240]})
        return out
    if t == "result":
        return [{"kind": "result", "text": mcp._mask(ev.get("result") or ""),
                 "cost_usd": ev.get("total_cost_usd"), "turns": ev.get("num_turns"),
                 "denials": len(ev.get("permission_denials") or [])}]
    return []


class Handler(BaseHTTPRequestHandler):
    server_version = "applyhome-web"
    sys_version = ""

    # 요청 본문·쿼리는 기록하지 않는다(경로와 상태 코드만)
    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        sys.stderr.write(f"{time.strftime('%H:%M:%S')} {self.command} {urlparse(self.path).path} {code}\n")

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        allowed = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"} | {h.lower() for h in EXTRA_HOSTS}
        if host not in allowed:
            sys.stderr.write(f"Host 거부: {host[:80]}\n")   # Host 이름은 개인정보가 아님(설정 확인용)
            return False
        return True

    def _headers(self, code, ctype, length=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._headers(code, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            raise ValueError("요청 본문 크기가 올바르지 않습니다")
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise ValueError("JSON 요청만 받습니다")
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _url(self):
        # http.server는 요청 줄을 latin-1로 해석한다. 인코딩되지 않은 한글이 와도 원래 UTF-8로 되돌린다.
        try:
            return urlparse(self.path.encode("latin-1").decode("utf-8"))
        except UnicodeError:
            return urlparse(self.path)

    def do_GET(self):
        if not self._host_ok():
            return self._json(421, {"error": "허용되지 않은 Host"})
        u = self._url()
        if u.path in STATIC_FILES:
            name, ctype = STATIC_FILES[u.path]
            with open(os.path.join(STATIC, name), "rb") as f:
                body = f.read()
            self._headers(200, ctype, len(body))
            return self.wfile.write(body)
        if u.path == "/api/status":
            return self._json(200, {"key_registered": bool(mcp.API_KEY), "agent_busy": AGENT_LOCK.locked(),
                                    "today": time.strftime("%Y-%m-%d")})
        if u.path in ("/api/notices", "/api/models"):
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/notices":
                    extra = set(q) - NOTICE_ARGS
                    if extra:
                        return self._json(400, {"error": "허용되지 않은 조회 항목: " + ", ".join(sorted(extra))})
                    if "only_open" in q:
                        q["only_open"] = q["only_open"] != "false"
                    return self._json(200, mcp.search_notices(q))
                extra = set(q) - {"house_manage_no", "pblanc_no"}
                if extra:
                    return self._json(400, {"error": "허용되지 않은 조회 항목"})
                return self._json(200, mcp.get_notice_models(q))
            except mcp.ToolError as e:
                return self._json(502, {"error": str(e)})
        return self._json(404, {"error": "없는 경로"})

    def do_POST(self):
        if not self._host_ok():
            return self._json(421, {"error": "허용되지 않은 Host"})
        u = urlparse(self.path)
        try:
            body = self._body()
        except (ValueError, UnicodeDecodeError) as e:
            return self._json(400, {"error": str(e) if isinstance(e, ValueError) and str(e) else "요청을 해석할 수 없습니다"})
        if u.path == "/api/judge":
            code, out = run_eligibility(body.get("profile"))
            return self._json(code, out)
        if u.path == "/api/agent-run":
            return self._agent_run(body)
        return self._json(404, {"error": "없는 경로"})

    def _agent_run(self, body):
        profile, sigungu = body.get("profile"), body.get("sigungu")
        code, judged = run_eligibility(profile)          # 같은 검증을 먼저 통과해야 실행
        if code != 200:
            return self._json(code, judged)
        if sigungu and not mcp.SIGUNGU_RE.match(sigungu):
            return self._json(400, {"error": "구 이름이 올바르지 않습니다"})
        if not AGENT_LOCK.acquire(blocking=False):
            return self._json(409, {"error": "다른 에이전트 실행이 진행 중입니다. 끝난 뒤 다시 실행하세요."})
        try:
            self._headers(200, "text/event-stream; charset=utf-8")
            cmd = ["claude", "-p", agent_prompt(profile, sigungu),
                   "--allowedTools", "Skill,Agent,Task,Bash(python3:*),Read,Grep,Glob,WebFetch,"
                                     "mcp__applyhome__search_notices,mcp__applyhome__get_notice_models",
                   "--output-format", "stream-json", "--verbose"]
            env = {k: v for k, v in os.environ.items() if k != "APPLYHOME_API_KEY"}
            p = subprocess.Popen(cmd, cwd=WORKSPACE, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, env=env)
            start = time.time()
            self._sse({"kind": "start", "label": "에이전트 실행 시작"})
            # 출력은 별도 스레드로 읽고, 조용한 동안에는 10초마다 하트비트를 보낸다
            # (CloudFront 오리진 읽기 30초·ALB 유휴 60초 제한에 걸려 연결이 끊기지 않도록)
            lines = queue.Queue()
            threading.Thread(target=lambda: ([lines.put(l) for l in p.stdout], lines.put(None)), daemon=True).start()
            while True:
                if time.time() - start > AGENT_TIMEOUT:
                    p.kill()
                    self._sse({"kind": "blocked", "label": "시간 초과로 중단했습니다"})
                    break
                try:
                    line = lines.get(timeout=10)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n"); self.wfile.flush()
                    continue
                if line is None:
                    break
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                for step in summarize_event(ev):
                    self._sse(step)
            p.wait(timeout=10)
            self._sse({"kind": "end", "label": f"종료 코드 {p.returncode}"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            AGENT_LOCK.release()

    def _sse(self, obj):
        self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()


def main():
    mcp.API_KEY = load_key_from_user_config()
    print(f"applyhome 화면: http://{HOST}:{PORT}  (인증키 {'등록됨' if mcp.API_KEY else '없음 — 공고 조회 불가'})",
          file=sys.stderr)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
