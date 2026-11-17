"use strict";
// 청약 자격·공고 확인 화면. 서버 응답은 모두 textContent로 넣고(HTML 주입 방지),
// 링크는 https://www.applyhome.co.kr/ 아래일 때만 만든다.

const SIDO = ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종",
  "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];
const YEARS = [["lt1", "1년 미만"], ...Array.from({ length: 14 }, (_, i) => [`${i + 1}y`, `${i + 1}년 이상`]), ["15y+", "15년 이상"]];
const ACCOUNT = [["none", "통장 없음"], ["lt6m", "6개월 미만"], ["6m-1y", "6개월~1년"],
  ...Array.from({ length: 14 }, (_, i) => [`${i + 1}y`, `${i + 1}년 이상 ${i + 2}년 미만`]), ["15y+", "15년 이상"]];
const YN = [["true", "예"], ["false", "아니오"]];
const YNU = [["true", "예"], ["false", "아니오"], ["unknown", "모름"]];

// 입력 단계(실제 진행 순서). type: select | number. req: 필수
const STEPS = [
  { title: "나와 세대", fields: [
    { key: "age_band", label: "나이(만)", req: true, opts: [["19-29", "19~29세"], ["30-34", "30~34세"], ["35-39", "35~39세"], ["40-49", "40대"], ["50-64", "50~64세"], ["65+", "65세 이상"], ["under19", "19세 미만"]] },
    { key: "residence_sido", label: "거주 시·도", req: true, opts: SIDO.map(s => [s, s]) },
    { key: "residence_years", label: "그 시·도 거주기간", opts: [["lt1", "1년 미만"], ["1-2", "1~2년"], ["2+", "2년 이상"]] },
    { key: "is_householder", label: "세대주", opts: YN },
    { key: "_house", label: "세대 주택 보유", req: true, wide: true, opts: [["0", "세대원 전원 무주택"], ["1", "1주택"], ["2+", "2주택 이상"]] },
  ]},
  { title: "청약통장", fields: [
    { key: "account_period", label: "가입기간", req: true, opts: ACCOUNT },
    { key: "deposit_band", label: "예치금(만원)", opts: [["0-199", "200 미만"], ["200-249", "200~249"], ["250-299", "250~299"], ["300-399", "300~399"], ["400-599", "400~599"], ["600-699", "600~699"], ["700-999", "700~999"], ["1000-1499", "1,000~1,499"], ["1500+", "1,500 이상"]] },
    { key: "payments_count", label: "납입 인정 회차(국민)", opts: [["lt6", "6회 미만"], ["6-11", "6~11회"], ["12-23", "12~23회"], ["24+", "24회 이상"]] },
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
    { key: "income_tax_5y", label: "소득세 5년 이상 납부", wide: true, opts: YN },
  ]},
  { title: "이력과 가점", fields: [
    { key: "first_home_ever", label: "세대원 모두 주택 소유 이력 없음", wide: true, opts: YN },
    { key: "prior_special_win", label: "세대 내 특공 당첨 이력", opts: YNU },
    { key: "supports_parent_65_3y", label: "65세 이상 부모 3년 이상 부양", opts: YN },
    { key: "homeless_years", label: "무주택기간(만30세·혼인부터)", opts: [["under30_single", "30세 미만 미혼"], ...YEARS] },
    { key: "dependents_count", label: "부양가족 수", opts: ["0", "1", "2", "3", "4", "5", "6+"].map(v => [v, v === "6+" ? "6명 이상" : `${v}명`]) },
    { key: "institution_eligible", label: "기관추천 대상(국가유공자·장애인 등)", wide: true, opts: YN },
  ]},
];

const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    // CSP(style-src 'self')는 style 속성을 막으므로 CSSOM으로 넣는다
    else if (k === "style") v.split(";").filter(Boolean).forEach(d => { const [p, ...val] = d.split(":"); n.style.setProperty(p.trim(), val.join(":").trim()); });
    else n.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) n.append(k);
  return n;
};
const STATUS = { "가능": ["is-ok", "가능"], "확인필요": ["is-check", "확인"], "불가": ["is-no", "불가"], "해당없음": ["is-na", "해당없음"], "참고": ["is-na", "참고"] };
const cls = (s) => (STATUS[s] || STATUS["해당없음"])[0];
const SAFE_URL = /^https:\/\/www\.applyhome\.co\.kr\//;

let lastJudged = null, lastProfile = null;

// ── 입력 화면 ───────────────────────────────────────────────
function renderForm() {
  const tsel = $("#target_sido");
  SIDO.forEach(s => tsel.append(el("option", { value: s, text: s })));
  tsel.value = "서울";
  const host = $("#steps");
  STEPS.forEach((st, i) => {
    const fs = el("fieldset", { class: "step" }, el("legend", {}, el("span", { class: "step__no", text: String(i + 2) }), st.title));
    const row = el("div", { class: "row" });
    st.fields.forEach(f => {
      let input;
      if (f.type === "number") {
        input = el("input", { type: "number", min: "0", max: "999999", step: "1", inputmode: "numeric", id: f.key, name: f.key, placeholder: "예: 780" });
      } else {
        input = el("select", { id: f.key, name: f.key });
        input.append(el("option", { value: "", text: f.req ? "선택" : "모름·해당 없음" }));
        f.opts.forEach(([v, t]) => input.append(el("option", { value: v, text: t })));
      }
      row.append(el("label", { class: "field" + (f.wide ? " field--wide" : "") + (f.req ? " is-required" : "") }, el("span", { text: f.label }), input));
    });
    fs.append(row);
    host.append(fs);
  });
  $("#residence_sido").value = "서울";
}

function readProfile() {
  const p = {};
  STEPS.flatMap(s => s.fields).forEach(f => {
    const v = $("#" + f.key).value.trim();
    if (!v) return;
    if (f.key === "_house") {
      p.homeless_household = v === "0"; p.house_count = v;
    } else if (v === "true" || v === "false") {
      p[f.key] = v === "true";
    } else {
      p[f.key] = v;
    }
  });
  p.target_sido = $("#target_sido").value;
  return p;
}

// ── 서버 호출 ───────────────────────────────────────────────
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await r.json().catch(() => ({ error: "응답을 해석할 수 없습니다" }));
  if (!r.ok) throw new Error(data.error || `요청 실패(${r.status})`);
  return data;
}

async function loadStatus() {
  try {
    const s = await api("api/status");
    const st = $("#status");
    st.textContent = "";
    st.append("기준일 ", el("b", { text: s.today }), " · 공고 조회 ",
      el("b", { text: s.key_registered ? "연결됨" : "인증키 없음(판정만 가능)" }));
  } catch (e) { $("#status").textContent = "서버에 연결할 수 없습니다"; }
}

async function loadSigungu() {
  const sido = $("#target_sido").value;
  const sel = $("#sigungu"), hint = $("#sigungu-hint");
  sel.replaceChildren(el("option", { value: "", text: "전체" }));
  hint.textContent = `${sido} 공고를 불러오는 중입니다.`;
  try {
    const d = await api(`api/notices?sido=${encodeURIComponent(sido)}&only_open=true`);
    const counts = Object.entries(d.sigungu_counts || {});
    sel.firstChild.textContent = `전체 (${d.returned}건)`;
    counts.forEach(([g, n]) => sel.append(el("option", { value: g === "기타" ? "" : g, text: `${g} (${n}건)` })));
    hint.textContent = d.returned ? `${sido}에서 접수 마감 전인 아파트 공고 ${d.returned}건이 있습니다.`
                                  : `${sido}에는 지금 접수 마감 전인 아파트 공고가 없습니다. 다른 시·도를 골라 보세요.`;
  } catch (e) { hint.textContent = `공고 수를 불러오지 못했습니다: ${e.message}`; }
}

// ── 판정 결과 ───────────────────────────────────────────────
function renderVerdict(j) {
  const sum = $("#summary"); sum.replaceChildren();
  const region = j.results.find(r => r.rule_id === "REGION");
  const score = j.results.find(r => r.rule_id === "GEN-SCORE");
  const item = (dt, dd) => sum.append(el("div", {}, el("dt", { text: dt }), el("dd", { text: dd })));
  item("조회 지역", `${j.notice_filters.sido}${$("#sigungu").value ? " " + $("#sigungu").value : " 전체"}`);
  if (region) item("공급 지역 신청", region.status === "가능" ? (region.reasons[0] || "가능") : `${region.status}: ${region.reasons[0] || ""}`);
  item("가구 소득", j.income_band_of_urban_avg ? `도시근로자 월평균의 ${j.income_band_of_urban_avg}` : "미입력(특공은 확인필요)");
  item("예치금 기준 면적", j.deposit_max_area || "미입력");
  if (score) item("가점 예상", score.total != null ? `${score.total}점 / 84점` : "입력 부족");

  const box = $("#stamps"); box.replaceChildren(); box.classList.remove("just-judged");
  j.results.filter(r => !["REGION", "GEN-SCORE"].includes(r.rule_id)).forEach((r, i) => {
    const [c, word] = STATUS[r.status] || STATUS["해당없음"];
    const card = el("article", { class: `verdict-card ${c}` },
      el("div", {}, el("h3", { text: r.type }), el("span", { class: "rid", text: r.rule_id })),
      el("span", { class: `stamp ${c}`, style: `--i:${i}`, text: word }));
    const sub = r.by_scope || r.by_regulation;
    if (sub) {
      const sc = el("div", { class: "scopes" });
      Object.entries(sub).forEach(([k, v]) => sc.append(el("span", { class: `scope ${cls(v.status)}`, title: (v.reasons || []).join(" / "), text: `${k} ${v.status}` })));
      card.append(sc);
    }
    const reasons = [...(r.reasons || []), ...Object.entries(sub || {}).flatMap(([k, v]) => (v.reasons || []).filter(Boolean).map(x => `${k}: ${x}`))];
    if (reasons.length) card.append(el("ul", {}, ...reasons.slice(0, 5).map(x => el("li", { text: x }))));
    box.append(card);
  });
  void box.offsetWidth; box.classList.add("just-judged");
  $("#foot").textContent = `${j.disclaimer} 기준: 청약홈 청약자격·특별공급 안내(${j.as_of} 확인).`;
}

// 공고 하나에 판정을 맞춰 본다
function fitFor(n, j) {
  const reg = n.SPECLT_RDN_EARTH_AT === "Y" || n.MDAT_TRGET_AREA_SECD === "Y";
  const kind = `${n.HOUSE_SECD_NM || ""} ${n.HOUSE_DTL_SECD_NM || ""}`;
  const scope = /국민/.test(kind) ? "국민" : /공공|신혼희망|뉴홈/.test(kind) ? "공공" : "민영";
  const out = [];
  for (const r of j.results) {
    let st;
    if (r.rule_id === "GEN-1-PRIVATE" && scope !== "국민") st = r.by_regulation[reg ? "규제지역" : "비규제지역"].status;
    else if (r.rule_id === "GEN-1-NATIONAL" && scope === "국민") st = r.by_regulation[reg ? "규제지역" : "비규제지역"].status;
    else if (r.rule_id === "GEN-2") st = r.status;
    else if (r.rule_id.startsWith("SP-") && r.rule_id !== "SP-INSTITUTION") {
      if (r.rule_id === "SP-YOUTH" && scope !== "공공") continue;
      st = r.by_scope ? (r.by_scope[scope] || {}).status || "불가" : r.status;
    } else continue;
    out.push([r.type.replace(" 특별공급", " 특공"), st]);
  }
  return { reg, scope, fits: out };
}

function timeline(n) {
  const pts = [
    ["모집공고", n.RCRIT_PBLANC_DE], ["특별공급", n.SPSPLY_RCEPT_BGNDE], ["1순위", n.GNRL_RNK1_CRSPAREA_RCPTDE],
    ["2순위", n.GNRL_RNK2_CRSPAREA_RCPTDE], ["무순위 접수", n.SUBSCRPT_RCEPT_BGNDE], ["당첨 발표", n.PRZWNER_PRESNATN_DE],
    ["계약", n.CNTRCT_CNCLS_BGNDE],
  ].filter(([, d]) => d);
  if (pts.length < 2) return null;
  const t = (d) => new Date(d + "T00:00:00").getTime();
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const lo = t(pts[0][1]), hi = Math.max(t(pts[pts.length - 1][1]), lo + 86400000);
  const pos = (ms) => Math.min(100, Math.max(0, ((ms - lo) / (hi - lo)) * 100));
  const wrap = el("div", { class: "timeline", role: "img", "aria-label": pts.map(([k, d]) => `${k} ${d}`).join(", ") }, el("div", { class: "timeline__line" }));
  pts.forEach(([k, d]) => wrap.append(el("div", { class: "tl-pt" + (t(d) < today.getTime() ? " is-past" : ""), style: `left:${pos(t(d))}%` }, el("b", { text: d.slice(5).replace("-", ".") }), k)));
  if (today.getTime() >= lo && today.getTime() <= hi) wrap.append(el("div", { class: "tl-today", style: `left:${pos(today.getTime())}%` }, el("span", { text: "오늘" })));
  return wrap;
}

async function showModels(n, holder, btn) {
  btn.disabled = true;
  try {
    const d = await api(`api/models?house_manage_no=${encodeURIComponent(n.HOUSE_MANAGE_NO)}&pblanc_no=${encodeURIComponent(n.PBLANC_NO || n.HOUSE_MANAGE_NO)}`);
    const cols = [["HOUSE_TY", "주택형"], ["SUPLY_HSHLDCO", "일반"], ["SPSPLY_HSHLDCO", "특공 계"], ["NWWDS_HSHLDCO", "신혼"], ["LFE_FRST_HSHLDCO", "생애최초"],
      ["NWBB_HSHLDCO", "신생아"], ["MNYCH_HSHLDCO", "다자녀"], ["OLD_PARNTS_SUPORT_HSHLDCO", "노부모"], ["LTTOT_TOP_AMOUNT", "최고분양가(만원)"]];
    const table = el("table", { class: "models" }, el("thead", {}, el("tr", {}, ...cols.map(([, h]) => el("th", { text: h })))));
    const tb = el("tbody");
    const fmt = (k, v) => v == null || v === "" ? "-" : k === "HOUSE_TY" || isNaN(Number(v)) ? String(v) : Number(v).toLocaleString("ko-KR");
    (d.models || []).forEach(m => tb.append(el("tr", {}, ...cols.map(([k]) => el("td", { text: fmt(k, m[k]) })))));
    table.append(tb);
    holder.replaceChildren(el("div", { class: "table-wrap" }, table));
    btn.hidden = true;
  } catch (e) { holder.replaceChildren(el("p", { class: "hint", text: `주택형을 불러오지 못했습니다: ${e.message}` })); btn.disabled = false; }
}

async function renderNotices(j) {
  const sido = j.notice_filters.sido, gu = $("#sigungu").value;
  const list = $("#notice-list");
  $("#notices").hidden = false;
  $("#notices-title").textContent = `${sido}${gu ? " " + gu : ""} 현재 공고`;
  list.replaceChildren(el("p", { class: "hint", text: "공고를 불러오는 중입니다." }));
  const q = (t) => `api/notices?sido=${encodeURIComponent(sido)}${gu ? "&sigungu=" + encodeURIComponent(gu) : ""}&only_open=true&house_type=${t}`;
  let apt, rem;
  try { [apt, rem] = await Promise.all([api(q("APT")), api(q("REMNDR"))]); }
  catch (e) { list.replaceChildren(el("p", { class: "error", text: `공고를 불러오지 못했습니다: ${e.message}` })); return; }
  const notices = [...apt.notices.map(n => ({ ...n, _kind: "APT" })), ...rem.notices.map(n => ({ ...n, _kind: "무순위" }))];
  list.replaceChildren();
  if (!notices.length) {
    list.append(el("div", { class: "empty" }, el("p", { class: "empty__title", text: "접수 마감 전인 공고가 없습니다" }),
      el("p", { text: gu ? "구를 '전체'로 바꾸거나 다른 시·도를 골라 다시 판정해 보세요." : "다른 시·도를 골라 다시 판정해 보세요." })));
    return;
  }
  notices.forEach(n => {
    const { reg, scope, fits } = fitFor(n, j);
    const gu2 = (n.HSSPLY_ADRES || "").split(/\s+/)[1] || "";
    const head = el("div", { class: "notice__head" }, el("h3", { class: "notice__name", text: n.HOUSE_NM || "이름 없음" }),
      el("span", { class: "notice__meta", text: `${gu2} · ${n._kind === "무순위" ? "무순위·잔여세대" : scope}${n.TOT_SUPLY_HSHLDCO ? " · " + n.TOT_SUPLY_HSHLDCO + "세대" : ""}` }));
    if (reg) head.append(el("span", { class: "tag tag--reg", text: "규제지역" }));
    const card = el("article", { class: "notice" }, head);
    const tl = timeline(n); if (tl) card.append(tl);
    const fit = el("div", { class: "fit" });
    if (n._kind === "무순위") fit.append(el("span", { class: "scope is-check", text: "무순위 자격은 공고문 확인" }));
    else fits.filter(([, s]) => s !== "불가").forEach(([k, s]) => fit.append(el("span", { class: `scope ${cls(s)}`, text: `${k} ${s}` })));
    if (!fit.childNodes.length) fit.append(el("span", { class: "scope is-no", text: "신청 가능한 유형 없음" }));
    card.append(fit);
    const links = el("div", { class: "notice__links" });
    if (n.PBLANC_URL && SAFE_URL.test(n.PBLANC_URL)) links.append(el("a", { href: n.PBLANC_URL, target: "_blank", rel: "noopener noreferrer", text: "청약홈 공고 보기" }));
    const holder = el("div");
    if (n._kind === "APT") {
      const b = el("button", { type: "button", class: "linkbtn", text: "주택형별 공급 세대 보기" });
      b.addEventListener("click", () => showModels(n, holder, b));
      links.append(b);
    }
    card.append(links, holder);
    list.append(card);
  });
}

// ── 에이전트 실행(SSE 스트림) ───────────────────────────────
function mdToNodes(md) {
  // 아주 작은 마크다운 렌더러: 제목·표·목록·인용·굵게·코드·청약홈 링크만. 나머지는 텍스트.
  const root = document.createDocumentFragment();
  const inline = (text) => {
    const span = el("span");
    const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      span.append(text.slice(last, m.index));
      const t = m[0];
      if (t.startsWith("**")) span.append(el("b", { text: t.slice(2, -2) }));
      else if (t.startsWith("`")) span.append(el("code", { text: t.slice(1, -1) }));
      else { const [, label, url] = t.match(/\[([^\]]+)\]\(([^)]+)\)/); span.append(SAFE_URL.test(url) ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: label }) : label); }
      last = m.index + t.length;
    }
    span.append(text.slice(last));
    return span;
  };
  const lines = md.replace(/\r/g, "").split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*$/.test(line) || /^`?★ Insight|^`?─{5,}/.test(line)) continue;
    let m;
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) { root.append(el("h" + Math.min(4, m[1].length + 1), {}, inline(m[2]))); continue; }
    if (/^\s*\|/.test(line)) {
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      i--;
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const table = el("table");
      rows.filter(r => !/^\s*\|[\s:|-]+\|\s*$/.test(r)).forEach((r, k) => table.append(el("tr", {}, ...cells(r).map(c => el(k === 0 ? "th" : "td", {}, inline(c))))));
      root.append(table); continue;
    }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ul = el("ul");
      while (i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || /^\s*\d+\.\s+/.test(lines[i]))) ul.append(el("li", {}, inline(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""))));
      i--; root.append(ul); continue;
    }
    if ((m = line.match(/^>\s?(.*)/))) { root.append(el("blockquote", {}, inline(m[1]))); continue; }
    root.append(el("p", {}, inline(line)));
  }
  return root;
}

async function runAgent() {
  if (!lastProfile) return;
  const btn = $("#btn-agent"), log = $("#agent-log"), ans = $("#agent-answer");
  btn.disabled = true; log.replaceChildren(); ans.hidden = true;
  const add = (kind, text, detail) => {
    const li = el("li", { class: "k-" + kind }, text);
    if (detail) li.append(" ", el("code", { text: detail }));
    log.append(li);
  };
  const LABEL = { "applyhome-kit:eligibility-checker": "판정 에이전트", "applyhome-kit:notice-finder": "공고 탐색 에이전트", "applyhome-kit:privacy-reviewer": "개인정보 점검 에이전트" };
  try {
    const r = await fetch("api/agent-run", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: lastProfile, sigungu: $("#sigungu").value || null }) });
    if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.error || `요청 실패(${r.status})`); }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let k;
      while ((k = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, k); buf = buf.slice(k + 2);
        if (!chunk.startsWith("data: ")) continue;
        const s = JSON.parse(chunk.slice(6));
        if (s.kind === "agent") add("agent", LABEL[s.label] || s.label);
        else if (s.kind === "mcp") add("mcp", s.label === "search_notices" ? "공고 조회" : "주택형 조회", JSON.stringify(s.detail));
        else if (s.kind === "tool") add("tool", s.label);
        else if (s.kind === "blocked") add("blocked", `차단·오류: ${s.label}`);
        else if (s.kind === "start" || s.kind === "end") add("tool", s.label);
        else if (s.kind === "result") {
          ans.replaceChildren(mdToNodes(s.text || "")); ans.hidden = false;
          add("tool", `완료: ${s.turns ?? "-"}턴, 약 $${(s.cost_usd ?? 0).toFixed(2)}, 권한 거부 ${s.denials}건`);
        }
      }
    }
  } catch (e) { add("blocked", e.message); }
  finally { btn.disabled = false; }
}

// ── 이벤트 연결 ─────────────────────────────────────────────
async function onJudge(ev) {
  ev.preventDefault();
  const btn = $("#btn-judge"), err = $("#error");
  err.hidden = true; btn.disabled = true;
  const p = readProfile();
  try {
    const j = await api("api/judge", { method: "POST", body: JSON.stringify({ profile: p }) });
    lastJudged = j; lastProfile = p;
    $("#empty").hidden = true; $("#verdict").hidden = false; $("#agent").hidden = false;
    renderVerdict(j);
    await renderNotices(j);
  } catch (e) {
    err.textContent = e.message.replace(/^'([a-z_]+)'/, (_, k) => `'${(STEPS.flatMap(s => s.fields).find(f => f.key === k) || {}).label || k}'`);
    err.hidden = false;
  } finally { btn.disabled = false; }
}

renderForm();
loadStatus();
loadSigungu();
$("#target_sido").addEventListener("change", loadSigungu);
$("#form").addEventListener("submit", onJudge);
$("#btn-reset").addEventListener("click", () => { $("#form").reset(); $("#target_sido").value = "서울"; $("#residence_sido").value = "서울"; loadSigungu(); });
$("#btn-agent").addEventListener("click", runAgent);
