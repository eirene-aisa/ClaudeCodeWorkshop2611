"use strict";
// 오늘 넣을 수 있는 청약: ① 지금 올라온 공고 → ② 내 조건 → ③ 유형별로 넣을 수 있는 공고.
// 서버 응답은 textContent로만 넣고(HTML 주입 방지), 링크는 청약홈 주소일 때만 만든다.

const SIDO = ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종",
  "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];
const YEARS = [["lt1", "1년 미만"], ...Array.from({ length: 14 }, (_, i) => [`${i + 1}y`, `${i + 1}년 이상`]), ["15y+", "15년 이상"]];
const ACCOUNT = [["none", "통장 없음"], ["lt6m", "6개월 미만"], ["6m-1y", "6개월~1년"],
  ...Array.from({ length: 14 }, (_, i) => [`${i + 1}y`, `${i + 1}년 이상 ${i + 2}년 미만`]), ["15y+", "15년 이상"]];
const YN = [["true", "예"], ["false", "아니오"]];
const YNU = [["true", "예"], ["false", "아니오"], ["unknown", "모름"]];

const GROUPS = [
  { title: "기본 정보", required: true, open: true, fields: [
    { key: "age_band", label: "나이(만)", req: true, opts: [["19-29", "19~29세"], ["30-34", "30~34세"], ["35-39", "35~39세"], ["40-49", "40대"], ["50-64", "50~64세"], ["65+", "65세 이상"], ["under19", "19세 미만"]] },
    { key: "residence_sido", label: "거주 시·도", req: true, opts: SIDO.map(s => [s, s]) },
    { key: "_house", label: "세대 주택 보유", req: true, opts: [["0", "세대원 전원 무주택"], ["1", "1주택"], ["2+", "2주택 이상"]] },
    { key: "account_period", label: "청약통장 가입기간", req: true, opts: ACCOUNT },
    { key: "is_householder", label: "세대주", opts: YN },
    { key: "residence_years", label: "그 시·도 거주기간", opts: [["lt1", "1년 미만"], ["1-2", "1~2년"], ["2+", "2년 이상"]] },
    { key: "deposit_band", label: "청약통장 예치금(만원)", opts: [["0-199", "200 미만"], ["200-249", "200~249"], ["250-299", "250~299"], ["300-399", "300~399"], ["400-599", "400~599"], ["600-699", "600~699"], ["700-999", "700~999"], ["1000-1499", "1,000~1,499"], ["1500+", "1,500 이상"]] },
    { key: "won_within_5y", label: "5년 내 당첨 이력", opts: YNU },
  ]},
  { title: "혼인과 자녀", fields: [
    { key: "marital_status", label: "혼인 상태", opts: [["single", "미혼"], ["engaged", "예비신혼(결혼 예정)"], ["married", "기혼"]] },
    { key: "married_years", label: "혼인 기간", opts: [["0-2", "2년 이내"], ["3-7", "2년 초과~7년"], ["7+", "7년 초과"]] },
    { key: "children_count", label: "미성년 자녀(태아 포함)", opts: [["0", "없음"], ["1", "1명"], ["2", "2명"], ["3+", "3명 이상"]] },
    { key: "youngest_child_age", label: "막내 나이", opts: [["none", "자녀 없음"], ["under2", "2세 미만"], ["2-6", "2~6세"], ["7-18", "7~18세"]] },
    { key: "pregnant", label: "임신 중", opts: YN },
    { key: "single_parent", label: "한부모 가구", opts: YN },
  ]},
  { title: "소득과 자산", fields: [
    { key: "household_size", label: "가구원 수", opts: [["1", "1명"], ["2", "2명"], ["3", "3명"], ["4", "4명"], ["5", "5명"], ["6+", "6명 이상"]] },
    { key: "monthly_income_manwon", label: "가구 월평균소득(세전, 만원)", type: "number" },
    { key: "dual_income", label: "맞벌이", opts: YN },
    { key: "real_estate", label: "부동산 자산", opts: [["none", "없음"], ["le33100", "3억 3,100만원 이하"], ["gt33100", "3억 3,100만원 초과"], ["unknown", "모름"]] },
    { key: "income_tax_5y", label: "소득세 5년 이상 납부", opts: YN },
  ]},
  { title: "이력과 가점", fields: [
    { key: "first_home_ever", label: "세대원 모두 주택 소유 이력 없음", opts: YN },
    { key: "prior_special_win", label: "세대 내 특공 당첨 이력", opts: YNU },
    { key: "supports_parent_65_3y", label: "65세 이상 부모 3년 이상 부양", opts: YN },
    { key: "institution_eligible", label: "기관추천 대상(국가유공자·장애인 등)", opts: YN },
    { key: "homeless_years", label: "무주택기간(만30세·혼인부터)", opts: [["under30_single", "30세 미만 미혼"], ...YEARS] },
    { key: "dependents_count", label: "부양가족 수", opts: ["0", "1", "2", "3", "4", "5", "6+"].map(v => [v, v === "6+" ? "6명 이상" : `${v}명`]) },
    { key: "payments_count", label: "납입 인정 회차(국민주택)", opts: [["lt6", "6회 미만"], ["6-11", "6~11회"], ["12-23", "12~23회"], ["24+", "24회 이상"]] },
  ]},
];
const ALL_FIELDS = GROUPS.flatMap(g => g.fields);

// 판정 유형 ↔ 공고 연결 규칙: 배정 세대 필드, 해당 접수일 필드
const LINK = {
  "GEN-1-PRIVATE": { alloc: "SUPLY_HSHLDCO", date: (n, other) => other ? n.GNRL_RNK1_ETC_AREA_RCPTDE : n.GNRL_RNK1_CRSPAREA_RCPTDE, dateLabel: "1순위", area: true },
  "GEN-1-NATIONAL": { alloc: "SUPLY_HSHLDCO", date: (n, other) => other ? n.GNRL_RNK1_ETC_AREA_RCPTDE : n.GNRL_RNK1_CRSPAREA_RCPTDE, dateLabel: "1순위" },
  "GEN-2": { alloc: "SUPLY_HSHLDCO", date: (n, other) => other ? n.GNRL_RNK2_ETC_AREA_RCPTDE : n.GNRL_RNK2_CRSPAREA_RCPTDE, dateLabel: "2순위" },
  "SP-NEWLYWED": { alloc: "NWWDS_HSHLDCO", date: n => n.SPSPLY_RCEPT_BGNDE, dateLabel: "특공", allocLabel: "신혼" },
  "SP-FIRSTHOME": { alloc: "LFE_FRST_HSHLDCO", date: n => n.SPSPLY_RCEPT_BGNDE, dateLabel: "특공", allocLabel: "생애최초" },
  "SP-NEWBORN": { alloc: "NWBB_HSHLDCO", date: n => n.SPSPLY_RCEPT_BGNDE, dateLabel: "특공", allocLabel: "신생아" },
  "SP-MULTICHILD": { alloc: "MNYCH_HSHLDCO", date: n => n.SPSPLY_RCEPT_BGNDE, dateLabel: "특공", allocLabel: "다자녀" },
  "SP-ELDERLY": { alloc: "OLD_PARNTS_SUPORT_HSHLDCO", date: n => n.SPSPLY_RCEPT_BGNDE, dateLabel: "특공", allocLabel: "노부모" },
  "SP-INSTITUTION": { alloc: "INSTT_RECOMEND_HSHLDCO", date: n => n.SPSPLY_RCEPT_BGNDE, dateLabel: "특공", allocLabel: "기관추천" },
  "SP-YOUTH": { alloc: null, date: n => n.SPSPLY_RCEPT_BGNDE, dateLabel: "특공" },
};
const AREA_LIMIT = { "전용 85㎡ 이하": 85, "전용 102㎡ 이하": 102, "전용 135㎡ 이하": 135, "모든 면적": Infinity };
const STATUS = { "가능": ["is-ok", "가능"], "확인필요": ["is-check", "확인"], "불가": ["is-no", "불가"], "해당없음": ["is-na", "해당없음"], "참고": ["is-na", "참고"] };
const SAFE_URL = /^https:\/\/www\.applyhome\.co\.kr\//;

const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    // CSP(style-src 'self')는 style 속성을 막으므로 CSSOM으로 넣는다
    else if (k === "style") v.split(";").filter(Boolean).forEach(d => { const [p, ...val] = d.split(":"); n.style.setProperty(p.trim(), val.join(":").trim()); });
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids) if (k != null) n.append(k);
  return n;
};
const md = (d) => d ? d.slice(5).replace("-", ".") : "";
const guOf = (n) => (n.HSSPLY_ADRES || "").split(/\s+/)[1] || "";
const domId = (n) => `n-${n._kind}-${n.HOUSE_MANAGE_NO}`;

const state = { notices: [], models: {}, gu: "", judged: null, profile: null };

// CloudFront OAC가 Lambda 함수 URL로 POST를 서명해 넘기려면 본문 SHA-256 헤더가 필요하다
async function bodyHash(body) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (opts.body) headers["x-amz-content-sha256"] = await bodyHash(opts.body);
  const r = await fetch(path, { ...opts, headers });
  const data = await r.json().catch(() => ({ error: "응답을 해석할 수 없습니다" }));
  if (!r.ok) throw new Error(data.error || `요청 실패(${r.status})`);
  return data;
}

function setProgress(step) {
  [1, 2, 3].forEach(i => {
    const p = $("#p" + i);
    p.classList.toggle("is-on", i === step);
    p.classList.toggle("is-done", i < step);
  });
}

// ── ① 지금 올라온 공고 ─────────────────────────────────────
async function loadNotices() {
  const sido = $("#target_sido").value;
  $("#s1-label").textContent = `${sido}에서 지금 접수 중이거나 예정인 공고`;
  const list = $("#notice-list");
  list.replaceChildren(el("p", { class: "hint", text: "공고를 불러오는 중입니다." }));
  $("#gu-chips").replaceChildren();
  state.gu = ""; state.notices = []; state.models = {};
  let apt, rem;
  try {
    const q = (t) => `api/notices?sido=${encodeURIComponent(sido)}&only_open=true&house_type=${t}`;
    [apt, rem] = await Promise.all([api(q("APT")), api(q("REMNDR"))]);
  } catch (e) {
    list.replaceChildren(el("p", { class: "error", text: `공고를 불러오지 못했습니다. ${e.message}` }));
    return;
  }
  state.notices = [...apt.notices.map(n => ({ ...n, _kind: "APT" })), ...rem.notices.map(n => ({ ...n, _kind: "REMNDR" }))];
  // 특공 배정·면적 판단에 쓰는 주택형 정보는 APT 공고마다 미리 받아 둔다
  await Promise.all(state.notices.filter(n => n._kind === "APT").map(async n => {
    try { state.models[n.HOUSE_MANAGE_NO] = (await api(`api/models?house_manage_no=${encodeURIComponent(n.HOUSE_MANAGE_NO)}&pblanc_no=${encodeURIComponent(n.PBLANC_NO || n.HOUSE_MANAGE_NO)}`)).models || []; }
    catch { state.models[n.HOUSE_MANAGE_NO] = null; }
  }));
  renderGuChips();
  renderNotices();
  if (state.judged) renderTypes();
}

function renderGuChips() {
  const counts = {};
  state.notices.forEach(n => { const g = guOf(n) || "기타"; counts[g] = (counts[g] || 0) + 1; });
  const box = $("#gu-chips"); box.replaceChildren();
  if (!state.notices.length) return;
  const chip = (value, label, n) => {
    const b = el("button", { type: "button", class: "chip", "aria-pressed": String(state.gu === value) }, label, el("b", { text: String(n) }));
    b.addEventListener("click", () => { state.gu = value; renderGuChips(); renderNotices(); if (state.judged) renderTypes(); });
    return b;
  };
  box.append(chip("", "전체", state.notices.length));
  Object.entries(counts).sort((a, b) => b[1] - a[1]).forEach(([g, n]) => box.append(chip(g, g, n)));
}

const visibleNotices = () => state.notices.filter(n => !state.gu || guOf(n) === state.gu);

function timeline(n) {
  const pts = [["모집공고", n.RCRIT_PBLANC_DE], ["특별공급", n.SPSPLY_RCEPT_BGNDE], ["1순위", n.GNRL_RNK1_CRSPAREA_RCPTDE],
    ["2순위", n.GNRL_RNK2_CRSPAREA_RCPTDE], ["무순위 접수", n.SUBSCRPT_RCEPT_BGNDE], ["당첨 발표", n.PRZWNER_PRESNATN_DE], ["계약", n.CNTRCT_CNCLS_BGNDE]]
    .filter(([, d]) => d);
  if (pts.length < 2) return null;
  const t = (d) => new Date(d + "T00:00:00").getTime();
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const lo = t(pts[0][1]), hi = Math.max(t(pts[pts.length - 1][1]), lo + 86400000);
  const pos = (ms) => Math.min(100, Math.max(0, ((ms - lo) / (hi - lo)) * 100));
  const w = el("div", { class: "timeline", role: "img", "aria-label": pts.map(([k, d]) => `${k} ${d}`).join(", ") }, el("div", { class: "timeline__line" }));
  pts.forEach(([k, d]) => w.append(el("div", { class: "tl-pt" + (t(d) < today.getTime() ? " is-past" : ""), style: `left:${pos(t(d))}%` }, el("b", { text: md(d) }), k)));
  if (today.getTime() >= lo && today.getTime() <= hi) w.append(el("div", { class: "tl-today", style: `left:${pos(today.getTime())}%` }, el("span", { text: "오늘" })));
  return w;
}

function allocSummary(n) {
  const ms = state.models[n.HOUSE_MANAGE_NO];
  if (!ms) return null;
  const sum = (k) => ms.reduce((a, m) => a + (Number(m[k]) || 0), 0);
  const parts = [["일반", "SUPLY_HSHLDCO"], ["신혼", "NWWDS_HSHLDCO"], ["생애최초", "LFE_FRST_HSHLDCO"], ["신생아", "NWBB_HSHLDCO"],
    ["다자녀", "MNYCH_HSHLDCO"], ["노부모", "OLD_PARNTS_SUPORT_HSHLDCO"]].map(([l, k]) => [l, sum(k)]).filter(([, v]) => v > 0);
  const areas = ms.map(m => parseFloat(m.HOUSE_TY)).filter(x => !isNaN(x));
  const area = areas.length ? `전용 ${Math.min(...areas).toFixed(0)}~${Math.max(...areas).toFixed(0)}㎡` : "";
  return `${area}${area && parts.length ? " · " : ""}${parts.map(([l, v]) => `${l} ${v}`).join(" · ")}세대`;
}

function modelsTable(n) {
  const ms = state.models[n.HOUSE_MANAGE_NO] || [];
  const cols = [["HOUSE_TY", "주택형"], ["SUPLY_HSHLDCO", "일반"], ["NWWDS_HSHLDCO", "신혼"], ["LFE_FRST_HSHLDCO", "생애최초"], ["NWBB_HSHLDCO", "신생아"],
    ["MNYCH_HSHLDCO", "다자녀"], ["OLD_PARNTS_SUPORT_HSHLDCO", "노부모"], ["LTTOT_TOP_AMOUNT", "최고분양가(만원)"]];
  const fmt = (k, v) => v == null || v === "" ? "-" : k === "HOUSE_TY" || isNaN(Number(v)) ? String(v).trim() : Number(v).toLocaleString("ko-KR");
  return el("div", { class: "table-wrap" }, el("table", { class: "models" },
    el("thead", {}, el("tr", {}, ...cols.map(([, h]) => el("th", { text: h })))),
    el("tbody", {}, ...ms.map(m => el("tr", {}, ...cols.map(([k]) => el("td", { text: fmt(k, m[k]) })))))));
}

function renderNotices() {
  const list = $("#notice-list"); list.replaceChildren();
  const ns = visibleNotices();
  if (!ns.length) {
    list.append(el("div", { class: "empty" }, el("p", { text: state.notices.length ? "이 구에는 지금 공고가 없습니다. 다른 구를 골라 보세요." : `${$("#target_sido").value}에는 지금 접수 마감 전인 공고가 없습니다. 다른 시·도를 골라 보세요.` })));
    return;
  }
  ns.forEach(n => {
    const reg = n.SPECLT_RDN_EARTH_AT === "Y" || n.MDAT_TRGET_AREA_SECD === "Y";
    const kind = n._kind === "REMNDR" ? "무순위·잔여세대" : (n.HOUSE_DTL_SECD_NM || "분양");
    const head = el("div", { class: "notice__head" }, el("h3", { class: "notice__name", text: n.HOUSE_NM || "이름 없음" }),
      el("span", { class: "notice__meta", text: [guOf(n), kind, n.TOT_SUPLY_HSHLDCO ? `총 ${n.TOT_SUPLY_HSHLDCO}세대` : ""].filter(Boolean).join(" · ") }),
      reg ? el("span", { class: "tag tag--reg", text: "규제지역" }) : null);
    const card = el("article", { class: "notice", id: domId(n) }, head);
    const tl = timeline(n); if (tl) card.append(tl);
    const alloc = allocSummary(n); if (alloc) card.append(el("p", { class: "notice__alloc", text: alloc }));
    const links = el("div", { class: "notice__links" });
    if (n.PBLANC_URL && SAFE_URL.test(n.PBLANC_URL)) links.append(el("a", { href: n.PBLANC_URL, target: "_blank", rel: "noopener noreferrer", text: "청약홈 공고 보기" }));
    const holder = el("div");
    if (state.models[n.HOUSE_MANAGE_NO]?.length) {
      const b = el("button", { type: "button", class: "linkbtn", "aria-expanded": "false", text: "주택형별 공급 세대" });
      b.addEventListener("click", () => { const open = b.getAttribute("aria-expanded") === "true"; b.setAttribute("aria-expanded", String(!open)); holder.replaceChildren(...(open ? [] : [modelsTable(n)])); });
      links.append(b);
    }
    card.append(links, holder, el("div", { class: "notice__mine", hidden: true }));
    list.append(card);
  });
}

// ── ② 내 조건 ─────────────────────────────────────────────
function renderForm() {
  const tsel = $("#target_sido");
  SIDO.forEach(s => tsel.append(el("option", { value: s, text: s })));
  tsel.value = "서울";
  const host = $("#groups");
  GROUPS.forEach((g, gi) => {
    const body = el("div", { class: "group__body" });
    g.fields.forEach(f => {
      let input;
      if (f.type === "number") input = el("input", { type: "number", min: "0", max: "999999", step: "1", inputmode: "numeric", id: f.key, placeholder: "예: 780" });
      else {
        input = el("select", { id: f.key });
        input.append(el("option", { value: "", text: f.req ? "선택" : "모름·해당 없음" }));
        f.opts.forEach(([v, t]) => input.append(el("option", { value: v, text: t })));
      }
      input.addEventListener("change", updateCounts);
      body.append(el("label", { class: "field" + (f.req ? " is-required" : "") }, el("span", { text: f.label }), input));
    });
    const sum = el("summary", {}, g.title, el("span", { class: "group__count", id: `gc-${gi}` }));
    host.append(el("details", { class: "group" + (g.required ? " group--required" : ""), open: g.open || null }, sum, body));
  });
  $("#residence_sido").value = "서울";
  updateCounts();
}

function updateCounts() {
  GROUPS.forEach((g, gi) => {
    const filled = g.fields.filter(f => $("#" + f.key).value).length;
    const req = g.fields.filter(f => f.req);
    const reqLeft = req.filter(f => !$("#" + f.key).value).length;
    $(`#gc-${gi}`).textContent = req.length && reqLeft ? `필수 ${reqLeft}개 남음 · ${filled}/${g.fields.length}` : `${filled}/${g.fields.length} 입력`;
  });
}

function readProfile() {
  const p = {};
  ALL_FIELDS.forEach(f => {
    const v = $("#" + f.key).value.trim();
    if (!v) return;
    if (f.key === "_house") { p.homeless_household = v === "0"; p.house_count = v; }
    else if (v === "true" || v === "false") p[f.key] = v === "true";
    else p[f.key] = v;
  });
  p.target_sido = $("#target_sido").value;
  return p;
}

// ── ③ 유형별로 넣을 수 있는 공고 ───────────────────────────
function scopeOf(n) {
  const kind = `${n.HOUSE_SECD_NM || ""} ${n.HOUSE_DTL_SECD_NM || ""}`;
  return /국민/.test(kind) ? "국민" : /공공|신혼희망|뉴홈/.test(kind) ? "공공" : "민영";
}

// 한 유형(r)이 한 공고(n)에 대해 어떤 상태인지: 판정 + 공고 구분·규제 + 배정 세대 + 면적
function matchNotice(r, n, j) {
  if (n._kind === "REMNDR") return null;
  const L = LINK[r.rule_id]; if (!L) return null;
  const reg = n.SPECLT_RDN_EARTH_AT === "Y" || n.MDAT_TRGET_AREA_SECD === "Y";
  const scope = scopeOf(n);
  let st;
  if (r.rule_id === "GEN-1-PRIVATE") { if (scope === "국민") return null; st = r.by_regulation[reg ? "규제지역" : "비규제지역"].status; }
  else if (r.rule_id === "GEN-1-NATIONAL") { if (scope !== "국민") return null; st = r.by_regulation[reg ? "규제지역" : "비규제지역"].status; }
  else if (r.rule_id === "SP-YOUTH") { if (scope !== "공공") return null; st = r.status; }
  else st = r.by_scope ? (r.by_scope[scope] || {}).status : r.status;
  if (!st || st === "불가") return null;
  const ms = state.models[n.HOUSE_MANAGE_NO];
  let seats = null, note = "";
  if (ms && L.alloc) {
    let usable = ms;
    if (L.area) {
      const lim = AREA_LIMIT[j.deposit_max_area] ?? Infinity;
      usable = ms.filter(m => (parseFloat(m.HOUSE_TY) || 0) <= lim + 0.5);
      if (!usable.length) return null;
      if (usable.length < ms.length) note = `예치금 기준 ${j.deposit_max_area} 주택형만`;
    }
    seats = usable.reduce((a, m) => a + (Number(m[L.alloc]) || 0), 0);
    if (seats === 0) return null;
  }
  const region = j.results.find(x => x.rule_id === "REGION");
  const other = region && region.reasons.some(x => x.includes("기타지역"));
  return { n, st, seats, date: L.date(n, other), dateLabel: L.dateLabel + (L.dateLabel.endsWith("순위") ? (other ? " 기타지역" : " 해당지역") : ""), note };
}

function renderTypes() {
  const j = state.judged;
  const sum = $("#summary"); sum.replaceChildren();
  const region = j.results.find(r => r.rule_id === "REGION");
  const score = j.results.find(r => r.rule_id === "GEN-SCORE");
  const item = (dt, dd) => sum.append(el("div", {}, el("dt", { text: dt }), el("dd", { text: dd })));
  item("공급 지역 신청", region ? (region.status === "가능" ? (region.reasons[0] || "가능") : `${region.status}: ${region.reasons[0] || ""}`) : "-");
  item("가구 소득", j.income_band_of_urban_avg ? `도시근로자 월평균의 ${j.income_band_of_urban_avg}` : "미입력(특공은 확인 필요)");
  item("예치금 기준 면적", j.deposit_max_area || "미입력");
  item("가점 예상", score && score.total != null ? `${score.total}점 / 84점` : "가점 항목 미입력");

  const ns = visibleNotices();
  const order = { "가능": 0, "확인필요": 1, "불가": 2, "해당없음": 3 };
  const rows = j.results.filter(r => LINK[r.rule_id]).map(r => ({ r, hits: ns.map(n => matchNotice(r, n, j)).filter(Boolean) }));
  rows.sort((a, b) => (order[a.r.status] - order[b.r.status]) || (b.hits.length - a.hits.length));
  const on = rows.filter(x => x.r.status !== "불가"), off = rows.filter(x => x.r.status === "불가");
  const where = `${$("#target_sido").value}${state.gu ? " " + state.gu : ""}`;

  const build = (box, list, animate) => {
    box.replaceChildren(); box.classList.remove("just-judged");
    list.forEach(({ r, hits }, i) => {
      const [c, word] = STATUS[r.status] || STATUS["해당없음"];
      const sub = r.by_scope || r.by_regulation;
      const subTxt = sub ? Object.entries(sub).map(([k, v]) => `${k} ${v.status}`).join(" · ") : "";
      const why = [...(r.reasons || []), ...Object.values(sub || {}).flatMap(v => v.reasons || [])].filter(Boolean)[0] || "";
      const hitList = el("ul", { class: "type__hits" });
      if (r.status !== "불가") {
        if (!hits.length) hitList.append(el("li", { class: "none", text: `${where}에 지금 올라온 공고 중 이 유형으로 넣을 수 있는 곳이 없습니다` }));
        else hits.forEach(h => {
          const a = el("a", { href: "#" + domId(h.n), text: h.n.HOUSE_NM });
          a.addEventListener("click", (e) => { e.preventDefault(); const t = document.getElementById(domId(h.n)); t.scrollIntoView({ block: "center" }); t.classList.add("is-flash"); setTimeout(() => t.classList.remove("is-flash"), 1600); });
          hitList.append(el("li", {}, a,
            el("span", { text: [h.date ? `${h.dateLabel} ${md(h.date)}` : "", h.seats != null ? `${LINK[r.rule_id].allocLabel || "일반공급"} ${h.seats}세대` : "", h.st === "확인필요" ? "자격 확인 필요" : "", h.note].filter(Boolean).join(" · ") })));
        });
      }
      box.append(el("article", { class: `type ${c}` },
        el("span", { class: `stamp type__stamp ${c}`, style: `--i:${i}`, text: word }),
        el("h3", { class: "type__name" }, r.type, subTxt ? el("small", { text: subTxt }) : null),
        why ? el("p", { class: "type__why", text: why }) : null,
        hitList.childNodes.length ? hitList : null));
    });
    if (animate) { void box.offsetWidth; box.classList.add("just-judged"); }
  };
  build($("#types"), on, true);
  $("#types-off-wrap").hidden = !off.length;
  $("#types-off-sum").textContent = `해당하지 않는 유형 ${off.length}개 보기`;
  build($("#types-off"), off, false);

  // ① 공고 카드에도 "내 조건으로 넣을 수 있는 유형"을 거꾸로 표시
  state.notices.forEach(n => {
    const box = document.querySelector(`#${CSS.escape(domId(n))} .notice__mine`);
    if (!box) return;
    const mine = rows.flatMap(({ r, hits }) => hits.filter(h => h.n === n).map(h => [r.type.replace(" 특별공급", " 특공").replace("일반공급 ", ""), h.st]));
    box.replaceChildren(el("b", { text: "내 조건으로:" }));
    if (n._kind === "REMNDR") box.append(el("span", { class: "scope is-check", text: "무순위 자격은 공고문 확인" }));
    else if (!mine.length) box.append(el("span", { class: "scope is-no", text: "넣을 수 있는 유형 없음" }));
    else mine.forEach(([k, s]) => box.append(el("span", { class: `scope ${(STATUS[s] || STATUS["해당없음"])[0]}`, text: `${k} ${s}` })));
    box.hidden = false;
  });
  $("#foot").textContent = `${j.disclaimer} 기준: 청약홈 청약자격·특별공급 안내(${j.as_of} 확인).`;
}

// ── 에이전트 실행(SSE) ──────────────────────────────────────
function mdToNodes(text) {
  const root = document.createDocumentFragment();
  const inline = (t) => {
    const span = el("span"); const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g; let last = 0, m;
    while ((m = re.exec(t))) {
      span.append(t.slice(last, m.index)); const s = m[0];
      if (s.startsWith("**")) span.append(el("b", { text: s.slice(2, -2) }));
      else if (s.startsWith("`")) span.append(el("code", { text: s.slice(1, -1) }));
      else { const [, label, url] = s.match(/\[([^\]]+)\]\(([^)]+)\)/); span.append(SAFE_URL.test(url) ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: label }) : label); }
      last = m.index + s.length;
    }
    span.append(t.slice(last)); return span;
  };
  const lines = text.replace(/\r/g, "").split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]; let m;
    if (/^\s*$/.test(line) || /^`?★ Insight|^`?─{5,}/.test(line)) continue;
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) { root.append(el("h" + Math.min(4, m[1].length + 1), {}, inline(m[2]))); continue; }
    if (/^\s*\|/.test(line)) {
      const rows = []; while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]); i--;
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const table = el("table");
      rows.filter(r => !/^\s*\|[\s:|-]+\|\s*$/.test(r)).forEach((r, k) => table.append(el("tr", {}, ...cells(r).map(c => el(k ? "td" : "th", {}, inline(c))))));
      root.append(table); continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ul = el("ul"); while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) ul.append(el("li", {}, inline(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, "")))); i--;
      root.append(ul); continue;
    }
    if ((m = line.match(/^>\s?(.*)/))) { root.append(el("blockquote", {}, inline(m[1]))); continue; }
    root.append(el("p", {}, inline(line)));
  }
  return root;
}

async function runAgent() {
  if (!state.profile) return;
  const btn = $("#btn-agent"), log = $("#agent-log"), ans = $("#agent-answer");
  btn.disabled = true; log.replaceChildren(); ans.hidden = true;
  const add = (kind, text, detail) => { const li = el("li", { class: "k-" + kind }, text); if (detail) li.append(" ", el("code", { text: detail })); log.append(li); };
  const LABEL = { "applyhome-kit:eligibility-checker": "판정 에이전트", "applyhome-kit:notice-finder": "공고 탐색 에이전트", "applyhome-kit:privacy-reviewer": "개인정보 점검 에이전트" };
  const show = (s) => {
    if (s.kind === "agent") add("agent", LABEL[s.label] || s.label);
    else if (s.kind === "mcp") add("mcp", s.label === "search_notices" ? "공고 조회" : "주택형 조회", JSON.stringify(s.detail));
    else if (s.kind === "blocked") add("blocked", `차단·오류: ${s.label}`);
    else if (s.kind === "result") { ans.replaceChildren(mdToNodes(s.text || "")); ans.hidden = false; add("tool", `완료: ${s.turns ?? "-"}턴, 약 $${(s.cost_usd ?? 0).toFixed(2)}, 권한 거부 ${s.denials}건`); }
    else add("tool", s.label);
  };
  try {
    // 작업을 시작하고 2초마다 새 단계만 받아 온다(긴 연결을 열어 두지 않아 프록시에서 끊기지 않음)
    const { job } = await api("api/agent-run", { method: "POST", body: JSON.stringify({ profile: state.profile, sigungu: state.gu || null }) });
    let since = 0, misses = 0;
    for (;;) {
      await new Promise(r => setTimeout(r, 2000));
      let d;
      try { d = await api(`api/agent-run?job=${encodeURIComponent(job)}&since=${since}`); misses = 0; }
      catch (e) { if (++misses >= 5) throw e; continue; }   // 일시적인 네트워크 오류는 다시 시도
      d.events.forEach(show); since = d.next;
      if (d.done) break;
    }
  } catch (e) { add("blocked", e.message); }
  finally { btn.disabled = false; }
}

// ── 연결 ─────────────────────────────────────────────────
async function onJudge(ev) {
  ev.preventDefault();
  const btn = $("#btn-judge"), err = $("#error");
  err.hidden = true;
  const missing = ALL_FIELDS.filter(f => f.req && !$("#" + f.key).value);
  if (missing.length) {
    err.textContent = `필수 항목을 골라 주세요: ${missing.map(f => f.label).join(", ")}`; err.hidden = false;
    $("#" + missing[0].key).focus(); return;
  }
  btn.disabled = true;
  const p = readProfile();
  try {
    state.judged = await api("api/judge", { method: "POST", body: JSON.stringify({ profile: p }) });
    state.profile = p;
    $("#s3-empty").hidden = true; $("#s3-body").hidden = false;
    renderTypes(); setProgress(3);
    $("#s3").scrollIntoView({ block: "start" });
  } catch (e) {
    err.textContent = e.message.replace(/'([a-z_]+)'/, (_, k) => `'${(ALL_FIELDS.find(f => f.key === k) || {}).label || k}'`);
    err.hidden = false;
  } finally { btn.disabled = false; }
}

async function loadStatus() {
  try {
    const s = await api("api/status"); const st = $("#status"); st.textContent = "";
    state.agentAvailable = s.agent_available !== false;
    $("#agent").hidden = !state.agentAvailable;
    st.append("기준일 ", el("b", { text: s.today }), " · 공고 조회 ", el("b", { text: s.key_registered ? "연결됨" : "인증키 없음(판정만 가능)" }));
  } catch { $("#status").textContent = "서버에 연결할 수 없습니다"; }
}

renderForm();
loadStatus();
loadNotices();
$("#target_sido").addEventListener("change", () => { loadNotices(); });
$("#form").addEventListener("submit", onJudge);
$("#form").addEventListener("focusin", () => { if (!state.judged) setProgress(2); });
$("#btn-reset").addEventListener("click", () => { $("#form").reset(); $("#residence_sido").value = "서울"; updateCounts(); });
$("#btn-agent").addEventListener("click", runAgent);
