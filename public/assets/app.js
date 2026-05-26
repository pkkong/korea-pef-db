const DATA_URL = "data/service_data.json";
const CHART_COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2"];

const state = {
  data: null,
  period: null,
  basis: "primary",
  view: "ranking",
  selectedGp: null,
  selectedPersonId: null,
  profilePeopleSchoolFilter: "",
  compareGps: [],
  fundById: new Map(),
  lookup: new Map(),
  rankingSort: { key: "aum", dir: "desc" },
  fundSort: { key: "amount", dir: "desc" },
  profileFundSort: { key: "amount", dir: "desc" },
  profilePeopleSort: { key: "title", dir: "asc" },
  selectedLpCode: null,
  lpNoticeStage: ""
};

const fmtInt = new Intl.NumberFormat("ko-KR");
const fmtOne = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 });

function byId(id) {
  return document.getElementById(id);
}

function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function splitNames(value) {
  return String(value || "").split(";").map((name) => name.trim()).filter(Boolean);
}

function normalize(value) {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, "");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[ch]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function fmtEokFromTrn(value) {
  return `${fmtInt.format(Math.round(num(value) * 10000))}억`;
}

function fmtEok(value) {
  const parsed = num(value);
  return parsed ? `${fmtInt.format(Math.round(parsed))}억` : "-";
}

function fmtAmount(value) {
  const parsed = num(value);
  if (!parsed) return "-";
  if (parsed >= 10000) return `${fmtOne.format(parsed / 10000)}조`;
  return `${fmtInt.format(Math.round(parsed))}억`;
}

function fmtDate(value) {
  const text = String(value || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text.replaceAll("-", ".") : text || "-";
}

function fmtPct(value) {
  return `${fmtOne.format(num(value))}%`;
}

function fmtRank(value) {
  return value ? `#${fmtInt.format(value)}` : "-";
}

function fmtChange(value) {
  const parsed = num(value);
  if (!parsed) return `<span class="subtle">-</span>`;
  const cls = parsed > 0 ? "change-up" : "change-down";
  const mark = parsed > 0 ? "▲" : "▼";
  return `<span class="${cls}">${mark} ${fmtEokFromTrn(Math.abs(parsed))}</span>`;
}

function categoryLabel(value) {
  return {
    "PE_HOUSE": "PE 하우스",
    "PE_HOUSE_FINANCIAL_GROUP_AFFILIATE": "금융그룹 계열 PE",
    "ASSET_MANAGER": "자산운용사",
    "PRIVATE_CREDIT_MANAGER": "프라이빗 크레딧",
    "MULTI_ASSET_ALTERNATIVE_MANAGER": "대체투자 운용사",
    "SECURITIES": "증권사"
  }[value] || String(value || "-");
}

function sourceLabel(value) {
  return {
    "OFFICIAL_SOURCE_VERIFIED": "공식 출처",
    "IDENTIFIER_VERIFIED": "식별자 확인",
    "SUPPORTING_SOURCE_ONLY": "보조 출처",
    "FSS_NAME_ONLY": "FSS명"
  }[value] || "-";
}

function lpStageLabel(value) {
  return {
    "selection_result": "선정결과",
    "shortlist": "숏리스트",
    "notice": "공고",
    "application": "접수",
    "briefing": "설명회",
    "performance_update": "성과",
    "candidate": "후보"
  }[value] || "후보";
}

function lpEventLabel(value) {
  return {
    "new_notice": "신규 공고",
    "deadline_soon": "마감 임박",
    "deadline_closed": "마감",
    "shortlist": "숏리스트",
    "final_selection": "최종 선정",
    "revision": "정정",
    "cancellation": "취소",
    "performance_update": "성과",
    "candidate": "후보"
  }[value] || lpStageLabel(value);
}

function lpSourceLabel(value) {
  return value === "official" ? "공식" : "뉴스";
}

function periodRows() {
  return state.basis === "full" ? state.data.gp_period_full_credit : state.data.gp_period_primary;
}

function currentPeriod() {
  return state.data.periods.find((period) => period.period_label === state.period) || state.data.periods.at(-1);
}

function previousPeriodLabel() {
  const idx = state.data.periods.findIndex((period) => period.period_label === state.period);
  return idx > 0 ? state.data.periods[idx - 1].period_label : "";
}

function gpRow(gpName, periodLabel = state.period) {
  return periodRows().find((row) => row.period_label === periodLabel && row.gp_name === gpName);
}

function profileFor(gpName) {
  return state.data.gp_profiles.find((profile) => profile.gp_name === gpName);
}

function cumulativeFor(gpName) {
  return state.data.gp_cumulative.find((row) => row.gp_name === gpName);
}

function aliasesFor(gpName) {
  return state.data.gp_aliases.filter((row) => row.canonical_gp_name === gpName).map((row) => row.alias_gp_name);
}

function buildLookup() {
  const names = new Set();
  state.data.gp_period_primary.forEach((row) => names.add(row.gp_name));
  state.data.gp_period_full_credit.forEach((row) => names.add(row.gp_name));
  names.forEach((name) => state.lookup.set(normalize(name), name));
  state.data.gp_aliases.forEach((row) => {
    if (row.alias_gp_name && row.canonical_gp_name) state.lookup.set(normalize(row.alias_gp_name), row.canonical_gp_name);
  });
  state.data.gp_profiles.forEach((profile) => {
    [profile.display_name_ko, profile.legal_entity_name_ko, profile.legal_entity_name_en, profile.alias_names]
      .filter(Boolean)
      .forEach((alias) => state.lookup.set(normalize(alias), profile.gp_name));
  });
}

function resolveGp(value) {
  return state.lookup.get(normalize(value)) || "";
}

function searchText(gpName) {
  const profile = profileFor(gpName);
  return normalize([
    gpName,
    profile?.display_name_ko,
    profile?.legal_entity_name_ko,
    profile?.legal_entity_name_en,
    profile?.alias_names,
    ...aliasesFor(gpName)
  ].filter(Boolean).join(" "));
}

function qoqChange(gpName) {
  const prev = previousPeriodLabel();
  if (!prev) return 0;
  const current = gpRow(gpName, state.period);
  const previous = gpRow(gpName, prev);
  return num(current?.commitment_aum_proxy_trn_krw) - num(previous?.commitment_aum_proxy_trn_krw);
}

function rankingBase() {
  const rows = periodRows().filter((row) => row.period_label === state.period);
  const total = rows.reduce((sum, row) => sum + num(row.commitment_aum_proxy_trn_krw), 0);
  return rows
    .slice()
    .sort((a, b) => num(b.commitment_aum_proxy_trn_krw) - num(a.commitment_aum_proxy_trn_krw) || String(a.gp_name).localeCompare(String(b.gp_name), "ko"))
    .map((row, index) => {
      const cumulative = cumulativeFor(row.gp_name);
      const profile = profileFor(row.gp_name);
      return {
        ...row,
        rank: index + 1,
        share: total ? (num(row.commitment_aum_proxy_trn_krw) / total) * 100 : 0,
        cumulative: num(cumulative?.cumulative_commitment_trn_krw),
        cumulativeFundCount: num(cumulative?.cumulative_fund_count),
        qoq: qoqChange(row.gp_name),
        profileReady: Boolean(profile?.service_ready),
        profileLabel: sourceLabel(profile?.verification_level)
      };
    });
}

function sortRows(rows, sort, valueFor) {
  const dir = sort.dir === "asc" ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const av = valueFor(a, sort.key);
    const bv = valueFor(b, sort.key);
    if (typeof av === "string" || typeof bv === "string") {
      return String(av).localeCompare(String(bv), "ko") * dir;
    }
    return (num(av) - num(bv)) * dir;
  });
}

function cycleSort(sort, key, defaultDir = "desc") {
  if (sort.key === key) {
    sort.dir = sort.dir === "asc" ? "desc" : "asc";
  } else {
    sort.key = key;
    sort.dir = defaultDir;
  }
}

function rankingRows() {
  return sortRows(rankingBase(), state.rankingSort, (row, key) => ({
    rank: row.rank,
    name: row.gp_name,
    aum: row.commitment_aum_proxy_trn_krw,
    cumulative: row.cumulative,
    funds: row.active_fund_count,
    share: row.share,
    qoq: row.qoq,
    profile: row.profileReady ? 1 : 0
  }[key]));
}

function activeFundRows() {
  return state.data.fund_snapshots
    .filter((row) => row.period_label === state.period)
    .map((row) => {
      const master = state.fundById.get(Number(row.fund_id)) || {};
      return {
        ...row,
        master,
        established: master.established_date || "",
        firstSeen: master.first_seen_period || "",
        lastSeen: master.last_seen_period || "",
        latestCommitment: num(row.commitment_trn_krw)
      };
    });
}

function sortedFundRows(rows, sort) {
  return sortRows(rows, sort, (row, key) => ({
    name: row.fund_name,
    gp: row.canonical_gp_names,
    amount: row.latestCommitment,
    established: row.established || "9999-99-99",
    raw_gp: row.raw_gp_names,
    observed: row.firstSeen
  }[key]));
}

function gpSeries(gpName) {
  const rows = new Map(periodRows().filter((row) => row.gp_name === gpName).map((row) => [row.period_label, row]));
  return state.data.periods.map((period) => ({
    x: period.period_label,
    y: rows.has(period.period_label) ? num(rows.get(period.period_label).commitment_aum_proxy_trn_krw) : 0
  }));
}

function peopleForGp(gpName) {
  const summaries = new Map((state.data.people_profile_summary || []).map((row) => [Number(row.person_id), row]));
  return (state.data.people_current_gp || [])
    .filter((row) => row.gp_name === gpName)
    .map((row) => ({
      ...row,
      summary: summaries.get(Number(row.person_id)) || {},
      roles: rolesForPerson(row.person_id),
      education: educationForPerson(row.person_id)
    }));
}

function sortedPeopleRows(rows, sort) {
  return sortRows(rows, sort, (row, key) => ({
    name: row.person_name_ko,
    title: row.current_title || row.role_title || "",
    team: row.team || "",
    roles: careerSummary(row),
    education: educationSummary(row),
    status: row.profile_status || row.summary?.profile_status || ""
  }[key]));
}

function rolesForPerson(personId) {
  return (state.data.people_roles || []).filter((row) => Number(row.person_id) === Number(personId));
}

function educationForPerson(personId) {
  return (state.data.people_education || []).filter((row) => Number(row.person_id) === Number(personId));
}

function meaningfulDegree(value) {
  const degree = String(value || "").trim();
  if (!degree || degree === "졸업") return "";
  return degree;
}

function educationLabel(item, options = {}) {
  const degree = meaningfulDegree(item.degree);
  const major = String(item.major || "").trim();
  const parts = [item.school_name || "-"];
  if (degree) parts.push(degree);
  if (major && options.includeMajor !== false) parts.push(major);
  return parts.join(" · ");
}

function schoolsForPerson(row) {
  return [...new Set((row.education || []).map((item) => item.school_name).filter(Boolean))];
}

function currentRole(row) {
  return row.current_title || row.role_title || "-";
}

function careerSummary(row, limit = 3) {
  const previous = (row.roles || []).filter((role) => !Number(role.is_current)).map((role) => role.org_name).filter(Boolean);
  const unique = [...new Set(previous)];
  if (!unique.length) return "-";
  const visible = unique.slice(0, limit).join(" · ");
  return unique.length > limit ? `${visible} 외 ${unique.length - limit}` : visible;
}

function educationSummary(row, limit = 2) {
  const schools = (row.education || []).map((item) => educationLabel(item, { includeMajor: false })).filter(Boolean);
  const unique = [...new Set(schools)];
  if (!unique.length) return "-";
  const visible = unique.slice(0, limit).join(" · ");
  return unique.length > limit ? `${visible} 외 ${unique.length - limit}` : visible;
}

function schoolCounts(rows) {
  const counts = new Map();
  rows.forEach((row) => {
    schoolsForPerson(row).forEach((school) => {
      counts.set(school, (counts.get(school) || 0) + 1);
    });
  });
  return Array.from(counts.entries())
    .map(([school, count]) => ({ school, count }))
    .sort((a, b) => b.count - a.count || a.school.localeCompare(b.school, "ko"));
}

function selectGp(gpName, options = {}) {
  if (!gpName) return;
  state.selectedGp = gpName;
  state.selectedPersonId = null;
  state.profilePeopleSchoolFilter = "";
  if (!state.compareGps.includes(gpName)) state.compareGps = [gpName, ...state.compareGps].slice(0, 6);
  if (options.view !== false) setView("profile");
  renderAll();
}

function setView(view) {
  if (!["ranking", "profile", "funds", "lp", "compare"].includes(view)) return;
  state.view = view;
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === view);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  if (window.location.hash.replace("#", "") !== view) {
    window.history.replaceState({}, "", `#${view}`);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderControls() {
  byId("periodSelect").innerHTML = state.data.periods.map((period) => (
    `<option value="${period.period_label}">${period.period_label} · ${period.as_of_date}</option>`
  )).join("");
  byId("periodSelect").value = state.period;
  byId("basisSelect").value = state.basis;

  const suggestions = new Set();
  state.lookup.forEach((canonical) => suggestions.add(canonical));
  state.data.gp_aliases.forEach((row) => {
    if (row.alias_gp_name) suggestions.add(row.alias_gp_name);
  });
  byId("gpList").innerHTML = Array.from(suggestions)
    .sort((a, b) => a.localeCompare(b, "ko"))
    .map((name) => `<option value="${escapeHtml(name)}"></option>`)
    .join("");

  byId("dataMeta").textContent = `${state.data.meta.latest_period} · ${state.data.meta.latest_as_of_date}`;
  setView(state.view);
}

function renderMetrics() {
  const period = currentPeriod();
  const rows = rankingBase();
  const total = rows.reduce((sum, row) => sum + num(row.commitment_aum_proxy_trn_krw), 0);
  const top10 = rows.slice(0, 10).reduce((sum, row) => sum + num(row.commitment_aum_proxy_trn_krw), 0);
  const year = Number(String(period.as_of_date || "").slice(0, 4));
  const formation = state.data.new_funds_by_year.find((row) => Number(row.year) === year);

  byId("metricAum").textContent = fmtEokFromTrn(period.commitment_trn_krw);
  byId("metricFunds").textContent = fmtInt.format(num(period.fund_count));
  byId("metricGps").textContent = fmtInt.format(rows.length);
  byId("metricNewFormation").textContent = formation ? fmtEokFromTrn(formation.first_seen_commitment_trn_krw) : "-";
  byId("metricNewFormationNote").textContent = formation ? `${year}년 신규 ${fmtInt.format(num(formation.new_fund_count))}개` : "선택 연도 데이터 없음";
  byId("metricTop10").textContent = total ? fmtPct((top10 / total) * 100) : "-";
}

function renderRanking() {
  const q = normalize(byId("rankingSearch").value);
  const limit = Number(byId("rankingLimit").value);
  const rows = rankingRows().filter((row) => !q || searchText(row.gp_name).includes(q)).slice(0, limit);
  byId("rankingCards").innerHTML = rows.map((row) => `
    <article class="mobile-row-card">
      <button class="mobile-card-main gp-link" type="button" data-gp="${escapeAttr(row.gp_name)}">
        <span>
          <strong>${escapeHtml(row.gp_name)}</strong>
          <em>${categoryLabel(profileFor(row.gp_name)?.company_category)}</em>
        </span>
        <b>${fmtRank(row.rank)}</b>
      </button>
      <div class="mobile-card-grid">
        <span>약정액 <strong>${fmtEokFromTrn(row.commitment_aum_proxy_trn_krw)}</strong></span>
        <span>누적 <strong>${row.cumulative ? fmtEokFromTrn(row.cumulative) : "-"}</strong></span>
        <span>펀드 <strong>${fmtInt.format(num(row.active_fund_count))}</strong></span>
        <span>비중 <strong>${fmtPct(row.share)}</strong></span>
      </div>
    </article>
  `).join("") || `<div class="empty">검색 결과가 없습니다.</div>`;
  byId("rankingBody").innerHTML = rows.map((row) => `
    <tr>
      <td class="numeric">${fmtRank(row.rank)}</td>
      <td>
        <button class="gp-link" type="button" data-gp="${escapeAttr(row.gp_name)}">${escapeHtml(row.gp_name)}</button>
        <span class="subtle">${categoryLabel(profileFor(row.gp_name)?.company_category)}</span>
      </td>
      <td class="numeric">${fmtEokFromTrn(row.commitment_aum_proxy_trn_krw)}</td>
      <td class="numeric">${row.cumulative ? fmtEokFromTrn(row.cumulative) : "-"}</td>
      <td class="numeric">${fmtInt.format(num(row.active_fund_count))}</td>
      <td class="numeric">${fmtPct(row.share)}</td>
      <td class="numeric">${fmtChange(row.qoq)}</td>
      <td><span class="status">${row.profileReady ? "검증" : row.profileLabel}</span></td>
    </tr>
  `).join("") || `<tr><td colspan="8"><div class="empty">검색 결과가 없습니다.</div></td></tr>`;
  byId("rankingBody").querySelectorAll(".gp-link").forEach((button) => {
    button.addEventListener("click", () => selectGp(button.dataset.gp));
  });
  byId("rankingCards").querySelectorAll(".gp-link").forEach((button) => {
    button.addEventListener("click", () => selectGp(button.dataset.gp));
  });
}

function renderProfile() {
  const selected = state.selectedGp || rankingBase()[0]?.gp_name;
  if (!selected) return;
  state.selectedGp = selected;
  const row = rankingBase().find((item) => item.gp_name === selected) || gpRow(selected);
  const profile = profileFor(selected);
  const cumulative = cumulativeFor(selected);
  const funds = sortedFundRows(
    activeFundRows().filter((fund) => splitNames(fund.canonical_gp_names).includes(selected)),
    state.profileFundSort
  );

  byId("profileName").textContent = selected;
  byId("profileSubtitle").textContent = profile
    ? `${categoryLabel(profile.company_category)} · 관측 ${profile.first_seen_period || "-"} ~ ${profile.last_seen_period || "-"}`
    : "금감원 공시 기준 GP";
  byId("profileRank").textContent = fmtRank(row?.rank);
  byId("profileAum").textContent = row ? fmtEokFromTrn(row.commitment_aum_proxy_trn_krw) : "-";
  byId("profileCumulative").textContent = cumulative ? fmtEokFromTrn(cumulative.cumulative_commitment_trn_krw) : "-";
  byId("profileFundCount").textContent = cumulative
    ? `${fmtInt.format(num(row?.active_fund_count))} / ${fmtInt.format(num(cumulative.cumulative_fund_count))}`
    : fmtInt.format(num(row?.active_fund_count));

  const homepage = profile?.homepage_url
    ? `<a href="${escapeAttr(profile.homepage_url)}" target="_blank" rel="noreferrer">홈페이지</a>`
    : "-";
  const source = profile?.primary_source_url
    ? `<a href="${escapeAttr(profile.primary_source_url)}" target="_blank" rel="noreferrer">근거</a>`
    : "-";
  byId("profileInfo").innerHTML = [
    ["법인명", profile?.legal_entity_name_ko || profile?.display_name_ko || selected],
    ["영문명", profile?.legal_entity_name_en || "-"],
    ["대표자", profile?.representative_name || "-"],
    ["설립일", profile?.established_date || profile?.firm_founded_date || profile?.firm_founded_year || "-"],
    ["사업자번호", profile?.business_registration_number || "-"],
    ["주소", profile?.headquarters_address || "-"],
    ["링크", `${homepage} · ${source}`],
    ["검증", sourceLabel(profile?.verification_level)]
  ].map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${String(value).includes("<a ") ? value : escapeHtml(value)}</dd>`).join("");

  byId("profileFundNote").textContent = `${state.period} 기준 ${fmtInt.format(funds.length)}개`;
  renderProfilePeople();
  renderProfileFunds(funds);
  renderLineChart("profileChart", [{ name: selected, color: CHART_COLORS[0], values: gpSeries(selected) }], fmtEokFromTrn);
}

function renderProfilePeople() {
  const q = normalize(byId("profilePeopleSearch").value);
  const allRows = sortedPeopleRows(peopleForGp(state.selectedGp), state.profilePeopleSort);
  renderSchoolFilter(allRows);
  document.querySelectorAll("[data-profile-people-sort]").forEach((button) => {
    button.classList.toggle("active", button.dataset.profilePeopleSort === state.profilePeopleSort.key);
  });
  const rows = allRows
    .filter((row) => {
      const text = `${row.person_name_ko} ${currentRole(row)} ${row.team || ""} ${careerSummary(row, 99)} ${educationSummary(row, 99)}`;
      const schoolMatched = !state.profilePeopleSchoolFilter || schoolsForPerson(row).includes(state.profilePeopleSchoolFilter);
      return schoolMatched && (!q || normalize(text).includes(q));
    });
  const visibleIds = new Set(rows.map((row) => Number(row.person_id)));
  if (!state.selectedPersonId || !visibleIds.has(Number(state.selectedPersonId))) {
    state.selectedPersonId = rows.length ? Number(rows[0].person_id) : null;
  }
  byId("profilePeopleNote").textContent = `${state.selectedGp || "-"} 기준 ${fmtInt.format(rows.length)}명${state.profilePeopleSchoolFilter ? ` · ${state.profilePeopleSchoolFilter}` : ""}`;
  byId("profilePeopleBody").innerHTML = rows.map((row) => `
    <article class="person-card ${Number(row.person_id) === Number(state.selectedPersonId) ? "active" : ""}" data-person-id="${Number(row.person_id)}">
      <div class="person-card-main">
        <div>
          <strong>${escapeHtml(row.person_name_ko)}</strong>
          ${row.person_name_en ? `<span>${escapeHtml(row.person_name_en)}</span>` : ""}
        </div>
        <button class="text-button ${Number(row.person_id) === Number(state.selectedPersonId) ? "active" : ""}" type="button">보기</button>
      </div>
      <div class="person-card-role">${escapeHtml(currentRole(row))}${row.team ? ` · ${escapeHtml(row.team)}` : ""}</div>
      <dl class="person-card-facts">
        <div>
          <dt>주요 경력</dt>
          <dd>${escapeHtml(careerSummary(row))}</dd>
        </div>
        <div>
          <dt>학력</dt>
          <dd>${educationChips(row)}</dd>
        </div>
      </dl>
      <div class="person-card-source">${escapeHtml(sourceLabel(row.verification_level || row.summary?.verification_level))} · 공식 팀 페이지</div>
    </article>
  `).join("") || `<div class="empty">연결된 인력 데이터가 없습니다.</div>`;
  byId("profilePeopleBody").querySelectorAll("[data-person-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedPersonId = Number(button.dataset.personId);
      renderProfilePeople();
    });
  });
  byId("profilePeopleBody").querySelectorAll("[data-school-filter]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      state.profilePeopleSchoolFilter = button.dataset.schoolFilter || "";
      renderProfilePeople();
    });
  });
  renderPersonDetail(rows.find((row) => Number(row.person_id) === Number(state.selectedPersonId)));
}

function educationChips(row) {
  const schools = schoolsForPerson(row);
  if (!schools.length) return "-";
  return schools.slice(0, 3).map((school) => `
    <button class="school-chip ${state.profilePeopleSchoolFilter === school ? "active" : ""}" type="button" data-school-filter="${escapeAttr(school)}">${escapeHtml(school)}</button>
  `).join(" ");
}

function renderSchoolFilter(rows) {
  const counts = schoolCounts(rows);
  byId("profileSchoolFilter").innerHTML = [
    `<button class="${state.profilePeopleSchoolFilter ? "" : "active"}" type="button" data-school-filter="">전체</button>`,
    ...counts.map((row) => `
      <button class="${state.profilePeopleSchoolFilter === row.school ? "active" : ""}" type="button" data-school-filter="${escapeAttr(row.school)}">${escapeHtml(row.school)} <span>${fmtInt.format(row.count)}</span></button>
    `)
  ].join("");
  byId("profileSchoolFilter").querySelectorAll("[data-school-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.profilePeopleSchoolFilter = button.dataset.schoolFilter || "";
      state.selectedPersonId = null;
      renderProfilePeople();
    });
  });
}

function renderPersonDetail(person) {
  const el = byId("profilePersonDetail");
  if (!person) {
    el.innerHTML = `<div class="empty">선택한 인물이 없습니다.</div>`;
    return;
  }
  const roles = rolesForPerson(person.person_id);
  const education = educationForPerson(person.person_id);
  const sourceUrl = person.primary_source_url || person.summary?.primary_source_url;
  const roleRows = roles.map((role) => `
    <tr>
      <td>${role.is_current ? "현재" : "이전"}</td>
      <td>${escapeHtml(role.org_name || "-")}</td>
      <td>${escapeHtml(role.title || "-")}</td>
      <td>${escapeHtml(role.team || "-")}</td>
    </tr>
  `).join("") || `<tr><td colspan="4"><div class="empty">경력 정보가 없습니다.</div></td></tr>`;
  const educationRows = education.map((item) => `
    <tr>
      <td><button class="school-link" type="button" data-school-filter="${escapeAttr(item.school_name || "")}">${escapeHtml(item.school_name || "-")}</button></td>
      <td>${escapeHtml(meaningfulDegree(item.degree) || "-")}</td>
      <td>${escapeHtml(item.major || "-")}</td>
    </tr>
  `).join("") || `<tr><td colspan="3"><div class="empty">학력 정보가 없습니다.</div></td></tr>`;
  el.innerHTML = `
    <h3>${escapeHtml(person.person_name_ko)}</h3>
    <p>${escapeHtml(person.current_title || person.role_title || "-")} · ${escapeHtml(person.team || "-")}
      ${sourceUrl ? ` · <a href="${escapeAttr(sourceUrl)}" target="_blank" rel="noreferrer">공식 출처</a>` : ""}
    </p>
    <div class="person-detail-grid">
      <div class="person-detail-block">
        <h4>경력</h4>
        <div class="table-wrap">
          <table>
            <thead><tr><th>구분</th><th>조직</th><th>직책/역할</th><th>부서</th></tr></thead>
            <tbody>${roleRows}</tbody>
          </table>
        </div>
      </div>
      <div class="person-detail-block">
        <h4>학력</h4>
        <div class="table-wrap">
          <table>
            <thead><tr><th>학교</th><th>학위</th><th>전공</th></tr></thead>
            <tbody>${educationRows}</tbody>
          </table>
        </div>
      </div>
    </div>
  `;
  el.querySelectorAll("[data-school-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.profilePeopleSchoolFilter = button.dataset.schoolFilter || "";
      state.selectedPersonId = null;
      renderProfilePeople();
    });
  });
}

function renderProfileFunds(precomputedRows) {
  const q = normalize(byId("profileFundSearch").value);
  const rows = (precomputedRows || sortedFundRows(
    activeFundRows().filter((fund) => splitNames(fund.canonical_gp_names).includes(state.selectedGp)),
    state.profileFundSort
  )).filter((row) => !q || normalize(row.fund_name).includes(q));
  byId("profileFundCards").innerHTML = rows.map((row) => `
    <article class="mobile-row-card">
      <div class="mobile-card-main">
        <span>
          <strong>${escapeHtml(row.fund_name)}</strong>
          <em>${escapeHtml(row.established || "설립일 미확인")}</em>
        </span>
        <b>${fmtEokFromTrn(row.latestCommitment)}</b>
      </div>
      <div class="mobile-card-note">${escapeHtml(row.raw_gp_names || row.canonical_gp_names || "-")}</div>
    </article>
  `).join("") || `<div class="empty">운용중 펀드가 없습니다.</div>`;
  byId("profileFundBody").innerHTML = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.fund_name)}</td>
      <td class="numeric">${fmtEokFromTrn(row.latestCommitment)}</td>
      <td>${escapeHtml(row.established || "-")}</td>
      <td>${escapeHtml(row.raw_gp_names || row.canonical_gp_names || "-")}</td>
      <td>${escapeHtml(row.firstSeen || "-")} ~ ${escapeHtml(row.lastSeen || "-")}</td>
    </tr>
  `).join("") || `<tr><td colspan="5"><div class="empty">운용중 펀드가 없습니다.</div></td></tr>`;
}

function renderFunds() {
  const q = normalize(byId("fundSearch").value);
  const limit = Number(byId("fundLimit").value);
  const rows = sortedFundRows(activeFundRows(), state.fundSort)
    .filter((row) => !q || normalize(`${row.fund_name} ${row.canonical_gp_names} ${row.raw_gp_names}`).includes(q))
    .slice(0, limit);
  byId("fundCards").innerHTML = rows.map((row) => `
    <article class="mobile-row-card">
      <div class="mobile-card-main">
        <span>
          <strong>${escapeHtml(row.fund_name)}</strong>
          <em>${escapeHtml(row.established || "설립일 미확인")}</em>
        </span>
        <b>${fmtEokFromTrn(row.latestCommitment)}</b>
      </div>
      <div class="mobile-card-links">
        ${splitNames(row.canonical_gp_names).slice(0, 4).map((gp) => `<button class="gp-link" type="button" data-gp="${escapeAttr(gp)}">${escapeHtml(gp)}</button>`).join("")}
      </div>
    </article>
  `).join("") || `<div class="empty">검색 결과가 없습니다.</div>`;
  byId("fundBody").innerHTML = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.fund_name)}</td>
      <td>${splitNames(row.canonical_gp_names).map((gp) => `<button class="gp-link" type="button" data-gp="${escapeAttr(gp)}">${escapeHtml(gp)}</button>`).join(" · ")}</td>
      <td class="numeric">${fmtEokFromTrn(row.latestCommitment)}</td>
      <td>${escapeHtml(row.established || "-")}</td>
      <td>${escapeHtml(row.firstSeen || "-")} ~ ${escapeHtml(row.lastSeen || "-")}</td>
    </tr>
  `).join("") || `<tr><td colspan="5"><div class="empty">검색 결과가 없습니다.</div></td></tr>`;
  byId("fundBody").querySelectorAll(".gp-link").forEach((button) => {
    button.addEventListener("click", () => selectGp(button.dataset.gp));
  });
  byId("fundCards").querySelectorAll(".gp-link").forEach((button) => {
    button.addEventListener("click", () => selectGp(button.dataset.gp));
  });
}

function lpInstitutionRows() {
  const q = normalize(byId("lpInstitutionSearch").value);
  return lpProfiles()
    .filter((row) => {
      const text = `${row.lp_name} ${row.lp_name_en} ${row.lp_type} ${row.ownership_type} ${row.default_team} ${row.focus_asset_classes} ${row.aliases} ${row.notes}`;
      return !q || normalize(text).includes(q);
    });
}

function lpNoticeRows() {
  const q = normalize(byId("lpNoticeSearch").value);
  const stage = byId("lpNoticeStage").value;
  return (state.data.lp_commitment_notices || [])
    .filter((row) => Number(row.public_visible) !== 0)
    .filter((row) => !stage || row.event_type === stage)
    .filter((row) => {
      const text = `${row.lp_name} ${row.title} ${row.event_type} ${row.program_name} ${row.asset_class} ${row.strategy} ${row.selected_gp_names} ${row.raw_excerpt}`;
      return !q || normalize(text).includes(q);
    });
}

function gpSummary(value) {
  const names = splitNames(value);
  if (!names.length) return "";
  const visible = names.slice(0, 2).join(" · ");
  return names.length > 2 ? `${visible} 외 ${names.length - 2}` : visible;
}

function lpNoticeGpLinks(noticeId) {
  return (state.data.lp_notice_gp_links || [])
    .filter((row) => String(row.notice_id) === String(noticeId));
}

function renderLpGpLinks(row) {
  const links = lpNoticeGpLinks(row.notice_id);
  if (links.length) {
    return links.slice(0, 3).map((link) => `
      <button class="gp-link lp-gp-link" type="button" data-gp="${escapeAttr(link.gp_name)}">${escapeHtml(link.gp_name)}</button>
    `).join(" · ") + (links.length > 3 ? ` <span class="subtle">외 ${links.length - 3}</span>` : "");
  }
  return escapeHtml(gpSummary(row.selected_gp_names) || "-");
}

function ownershipLabel(value) {
  return {
    public: "공공",
    private: "민간",
    mutual_aid: "공제회"
  }[value] || value || "-";
}

function semicolonLabel(value) {
  const values = splitNames(value);
  return values.length ? values.join(" · ") : "-";
}

function lpFactSectionLabel(value) {
  return {
    general: "일반현황",
    investment_status: "투자현황",
    investment_strategy: "투자전략",
    investment_org: "PE 관련 조직",
    investment_governance: "투자 의사결정",
    public_people: "공개 인물",
    notice_history: "출자공고 히스토리",
    data_gap: "확인 필요"
  }[value] || value || "기타";
}

function lpFactSectionRank(value) {
  return {
    general: 10,
    investment_status: 20,
    investment_strategy: 30,
    investment_org: 40,
    investment_governance: 50,
    public_people: 60,
    notice_history: 70,
    data_gap: 90
  }[value] || 99;
}

function lpProfiles() {
  if (Array.isArray(state.data.lp_profiles) && state.data.lp_profiles.length) {
    return state.data.lp_profiles;
  }
  const statsByCode = new Map((state.data.lp_institution_stats || []).map((row) => [row.lp_code, row]));
  return (state.data.lp_institutions || []).map((row) => ({ ...row, ...(statsByCode.get(row.lp_code) || {}) }));
}

function lpProfileFacts(lpCode) {
  return (state.data.lp_profile_facts || [])
    .filter((row) => Number(row.public_visible) !== 0 && row.lp_code === lpCode)
    .sort((a, b) => {
      const section = lpFactSectionRank(a.section) - lpFactSectionRank(b.section);
      if (section) return section;
      return num(a.sort_order) - num(b.sort_order) || String(a.label || "").localeCompare(String(b.label || ""), "ko");
    });
}

function selectLp(lpCode) {
  if (!lpCode) return;
  state.selectedLpCode = lpCode;
  renderLp();
}

function renderLp() {
  const profiles = lpProfiles();
  const notices = state.data.lp_commitment_notices || [];
  const visibleNotices = notices.filter((row) => Number(row.public_visible) !== 0);
  const officialNoticeCount = visibleNotices.filter((row) => row.source_type === "official").length;
  const gpSet = new Set();
  visibleNotices.forEach((row) => splitNames(row.selected_gp_names).forEach((name) => gpSet.add(name)));

  byId("lpMetricInstitutions").textContent = fmtInt.format(profiles.length);
  byId("lpMetricNotices").textContent = fmtInt.format(visibleNotices.length);
  byId("lpMetricAmount").textContent = fmtInt.format(officialNoticeCount);
  byId("lpMetricSelectedGps").textContent = fmtInt.format(gpSet.size);

  const lpRows = lpInstitutionRows();
  if (lpRows.length && !lpRows.some((row) => row.lp_code === state.selectedLpCode)) {
    state.selectedLpCode = lpRows[0]?.lp_code || profiles[0]?.lp_code || null;
  } else if (!state.selectedLpCode || !profiles.some((row) => row.lp_code === state.selectedLpCode)) {
    state.selectedLpCode = profiles[0]?.lp_code || null;
  }
  const selectedLp = profiles.find((row) => row.lp_code === state.selectedLpCode) || lpRows[0] || profiles[0];
  byId("lpProfileSummary").innerHTML = selectedLp ? `
    <div class="lp-profile-main">
      <div>
        <span class="status">${escapeHtml(ownershipLabel(selectedLp.ownership_type))}</span>
        <h2>${escapeHtml(selectedLp.lp_name)}</h2>
        <p>${escapeHtml(selectedLp.lp_name_en || selectedLp.notes || "-")}</p>
      </div>
      <dl>
        <div><dt>기관 유형</dt><dd>${escapeHtml(selectedLp.lp_type || "-")}</dd></div>
        <div><dt>담당 조직</dt><dd>${escapeHtml(selectedLp.default_team || "-")}</dd></div>
        <div><dt>관심 자산군</dt><dd>${escapeHtml(semicolonLabel(selectedLp.focus_asset_classes))}</dd></div>
        <div><dt>공개 이벤트</dt><dd>${fmtInt.format(num(selectedLp.notice_count))}건</dd></div>
        <div><dt>공식 공고</dt><dd>${fmtInt.format(num(selectedLp.official_notice_count))}건</dd></div>
        <div><dt>최근 업데이트</dt><dd>${escapeHtml(fmtDate(selectedLp.latest_event_date || selectedLp.latest_announced_date || selectedLp.latest_discovered_at))}</dd></div>
      </dl>
      <p>${escapeHtml(selectedLp.notes || "")}</p>
      <div class="lp-profile-links">
        ${selectedLp.homepage_url ? `<a href="${escapeAttr(selectedLp.homepage_url)}" target="_blank" rel="noreferrer">홈페이지</a>` : ""}
        ${selectedLp.notice_url ? `<a href="${escapeAttr(selectedLp.notice_url)}" target="_blank" rel="noreferrer">공식 공고 채널</a>` : ""}
        ${selectedLp.latest_notice_url ? `<a href="${escapeAttr(selectedLp.latest_notice_url)}" target="_blank" rel="noreferrer">최근 공고</a>` : ""}
      </div>
    </div>
  ` : `<div class="empty">LP 프로필 데이터가 없습니다.</div>`;

  const facts = selectedLp ? lpProfileFacts(selectedLp.lp_code) : [];
  const factsBySection = facts.reduce((acc, row) => {
    const section = row.section || "other";
    if (!acc.has(section)) acc.set(section, []);
    acc.get(section).push(row);
    return acc;
  }, new Map());
  byId("lpFactGrid").innerHTML = [...factsBySection.entries()].map(([section, sectionRows]) => `
    <article class="lp-fact-card">
      <h3>${escapeHtml(lpFactSectionLabel(section))}</h3>
      <dl>
        ${sectionRows.map((row) => `
          <div>
            <dt>${escapeHtml(row.label || "-")}</dt>
            <dd>
              <span>${escapeHtml(row.value || "-")}</span>
              ${row.source_url ? `<a href="${escapeAttr(row.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(row.source_name || "출처")}</a>` : ""}
            </dd>
          </div>
        `).join("")}
      </dl>
    </article>
  `).join("") || `<div class="empty">선택 LP의 공개 프로필 팩트가 없습니다.</div>`;

  byId("lpInstitutionCards").innerHTML = lpRows.map((row) => `
    <button class="lp-card ${row.lp_code === state.selectedLpCode ? "active" : ""}" type="button" data-lp-code="${escapeAttr(row.lp_code)}">
      <div>
        <strong>${escapeHtml(row.lp_name)}</strong>
        <span>${escapeHtml(row.lp_type || "-")} · ${escapeHtml(ownershipLabel(row.ownership_type))}</span>
      </div>
      <dl>
        <div><dt>공고/뉴스</dt><dd>${fmtInt.format(num(row.notice_count))}</dd></div>
        <div><dt>공식</dt><dd>${fmtInt.format(num(row.official_notice_count))}건</dd></div>
        <div><dt>최근</dt><dd>${escapeHtml(fmtDate(row.latest_event_date || row.latest_announced_date || row.latest_discovered_at))}</dd></div>
      </dl>
      <p>${escapeHtml(row.default_team || "-")} · ${escapeHtml(semicolonLabel(row.focus_asset_classes))}</p>
    </button>
  `).join("") || `<div class="empty">검색 결과가 없습니다.</div>`;
  byId("lpInstitutionCards").querySelectorAll("[data-lp-code]").forEach((button) => {
    button.addEventListener("click", () => selectLp(button.dataset.lpCode));
  });

  const rows = lpNoticeRows();
  byId("lpNoticeCards").innerHTML = rows.map((row) => `
    <article class="mobile-row-card">
      <a class="mobile-card-main" href="${escapeAttr(row.notice_url)}" target="_blank" rel="noreferrer">
        <span>
          <strong>${escapeHtml(row.title)}</strong>
          <em>${escapeHtml(row.lp_name || "LP 미분류")} · ${lpSourceLabel(row.source_type)} · ${lpEventLabel(row.event_type)}</em>
        </span>
        <b>${fmtAmount(row.allocation_amount_krw_100mn)}</b>
      </a>
      <div class="mobile-card-note">${escapeHtml([row.program_name, row.asset_class, row.strategy].filter(Boolean).join(" · ") || row.raw_excerpt || "-")}</div>
      <div class="mobile-card-links">${renderLpGpLinks(row)}</div>
    </article>
  `).join("") || `<div class="empty">검색 결과가 없습니다.</div>`;

  byId("lpNoticeBody").innerHTML = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.lp_name || "-")}<span class="subtle">${escapeHtml(row.default_team || "")}</span></td>
      <td><a href="${escapeAttr(row.notice_url)}" target="_blank" rel="noreferrer">${escapeHtml(row.title)}</a><span class="subtle">${lpSourceLabel(row.source_type)}</span></td>
      <td><span class="status">${lpEventLabel(row.event_type)}</span></td>
      <td>${escapeHtml(row.asset_class || row.strategy || "-")}</td>
      <td class="numeric">${fmtAmount(row.allocation_amount_krw_100mn)}</td>
      <td>${renderLpGpLinks(row)}</td>
      <td>${escapeHtml(fmtDate(row.event_date || row.announced_date || row.notice_year))}</td>
    </tr>
  `).join("") || `<tr><td colspan="7"><div class="empty">검색 결과가 없습니다.</div></td></tr>`;
  byId("lpNoticeBody").querySelectorAll(".lp-gp-link").forEach((button) => {
    button.addEventListener("click", () => selectGp(button.dataset.gp));
  });
  byId("lpNoticeCards").querySelectorAll(".lp-gp-link").forEach((button) => {
    button.addEventListener("click", () => selectGp(button.dataset.gp));
  });
}

function renderCompare() {
  byId("compareChips").innerHTML = state.compareGps.map((gp) => `
    <span>${escapeHtml(gp)} <button type="button" data-gp="${escapeAttr(gp)}">×</button></span>
  `).join("");
  byId("compareChips").querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.compareGps = state.compareGps.filter((gp) => gp !== button.dataset.gp);
      renderCompare();
    });
  });
  renderLineChart("compareChart", state.compareGps.map((gp, index) => ({
    name: gp,
    color: CHART_COLORS[index % CHART_COLORS.length],
    values: gpSeries(gp)
  })), fmtEokFromTrn);

  const rows = state.compareGps.map((gp) => rankingBase().find((row) => row.gp_name === gp)).filter(Boolean);
  byId("compareCards").innerHTML = rows.map((row) => `
    <article class="mobile-row-card">
      <div class="mobile-card-main">
        <span>
          <strong>${escapeHtml(row.gp_name)}</strong>
          <em>${fmtRank(row.rank)} · 펀드 ${fmtInt.format(num(row.active_fund_count))}개</em>
        </span>
        <b>${fmtEokFromTrn(row.commitment_aum_proxy_trn_krw)}</b>
      </div>
      <div class="mobile-card-grid">
        <span>누적 <strong>${row.cumulative ? fmtEokFromTrn(row.cumulative) : "-"}</strong></span>
        <span>전기 대비 <strong>${fmtChange(row.qoq)}</strong></span>
      </div>
    </article>
  `).join("");
  byId("compareBody").innerHTML = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.gp_name)}</td>
      <td class="numeric">${fmtRank(row.rank)}</td>
      <td class="numeric">${fmtEokFromTrn(row.commitment_aum_proxy_trn_krw)}</td>
      <td class="numeric">${row.cumulative ? fmtEokFromTrn(row.cumulative) : "-"}</td>
      <td class="numeric">${fmtInt.format(num(row.active_fund_count))}</td>
      <td class="numeric">${fmtChange(row.qoq)}</td>
    </tr>
  `).join("");
}

function renderLineChart(id, series, formatter) {
  const el = byId(id);
  if (!series.length) {
    el.innerHTML = `<div class="empty">비교할 GP가 없습니다.</div>`;
    return;
  }
  const width = Math.max(320, el.clientWidth - 20);
  const height = width < 520 ? 220 : 280;
  const pad = width < 520
    ? { top: 18, right: 12, bottom: 34, left: 58 }
    : { top: 18, right: 18, bottom: 36, left: 78 };
  const allValues = series.flatMap((item) => item.values.map((point) => num(point.y)));
  const maxY = Math.max(...allValues, 1);
  const xCount = series[0].values.length;
  const x = (idx) => pad.left + (xCount <= 1 ? 0 : idx * (width - pad.left - pad.right) / (xCount - 1));
  const y = (value) => height - pad.bottom - (num(value) / maxY) * (height - pad.top - pad.bottom);
  const ticks = [0, 0.5, 1].map((ratio) => maxY * ratio);
  const labels = [0, Math.floor((xCount - 1) / 2), xCount - 1].filter((idx, i, arr) => idx >= 0 && arr.indexOf(idx) === i);
  const grid = ticks.map((tick) => `
    <line x1="${pad.left}" x2="${width - pad.right}" y1="${y(tick)}" y2="${y(tick)}" stroke="#e5e5e5" />
    <text x="${pad.left - 9}" y="${y(tick) + 4}" text-anchor="end" font-size="11" fill="#737373">${formatter(tick)}</text>
  `).join("");
  const paths = series.map((item) => {
    const points = item.values.map((point, idx) => `${x(idx)},${y(point.y)}`).join(" ");
    return `<polyline points="${points}" fill="none" stroke="${item.color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />`;
  }).join("");
  const xLabels = labels.map((idx) => {
    const point = series[0].values[idx];
    return `<text x="${x(idx)}" y="${height - 10}" text-anchor="middle" font-size="11" fill="#737373">${point ? point.x : ""}</text>`;
  }).join("");
  const legend = series.map((item) => `<span><i class="dot" style="background:${item.color}"></i>${escapeHtml(item.name)}</span>`).join("");
  el.innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}">${grid}${paths}${xLabels}</svg><div class="legend">${legend}</div>`;
}

function renderAll() {
  renderMetrics();
  renderRanking();
  renderProfile();
  renderFunds();
  renderLp();
  renderCompare();
}

function runGlobalSearch() {
  selectGp(resolveGp(byId("globalGpSearch").value));
}

function wireEvents() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  byId("periodSelect").addEventListener("change", (event) => {
    state.period = event.target.value;
    renderAll();
  });
  byId("basisSelect").addEventListener("change", (event) => {
    state.basis = event.target.value;
    renderAll();
  });
  byId("globalGpButton").addEventListener("click", runGlobalSearch);
  byId("globalGpSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") runGlobalSearch();
  });
  byId("rankingSearch").addEventListener("input", renderRanking);
  byId("rankingLimit").addEventListener("change", renderRanking);
  document.querySelectorAll("[data-ranking-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.rankingSort;
      cycleSort(state.rankingSort, key, key === "rank" || key === "name" ? "asc" : "desc");
      renderRanking();
    });
  });
  byId("profileFundSearch").addEventListener("input", () => renderProfileFunds());
  byId("profilePeopleSearch").addEventListener("input", () => renderProfilePeople());
  document.querySelectorAll("[data-profile-people-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.profilePeopleSort;
      cycleSort(state.profilePeopleSort, key, key === "name" || key === "title" || key === "team" || key === "status" ? "asc" : "desc");
      renderProfilePeople();
    });
  });
  document.querySelectorAll("[data-profile-fund-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.profileFundSort;
      cycleSort(state.profileFundSort, key, key === "name" || key === "established" ? "asc" : "desc");
      renderProfile();
    });
  });
  byId("fundSearch").addEventListener("input", renderFunds);
  byId("fundLimit").addEventListener("change", renderFunds);
  document.querySelectorAll("[data-fund-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.fundSort;
      cycleSort(state.fundSort, key, key === "name" || key === "gp" || key === "established" ? "asc" : "desc");
      renderFunds();
    });
  });
  byId("lpInstitutionSearch").addEventListener("input", renderLp);
  byId("lpNoticeSearch").addEventListener("input", renderLp);
  byId("lpNoticeStage").addEventListener("change", renderLp);
  byId("compareButton").addEventListener("click", () => {
    const gp = resolveGp(byId("compareInput").value);
    if (gp && !state.compareGps.includes(gp)) {
      state.compareGps = [...state.compareGps, gp].slice(0, 6);
      byId("compareInput").value = "";
      renderCompare();
    }
  });
  byId("compareInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") byId("compareButton").click();
  });
  window.addEventListener("resize", () => {
    renderProfile();
    renderCompare();
  });
}

async function boot() {
  const response = await fetch(DATA_URL);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  state.data = await response.json();
  state.period = state.data.meta.latest_period;
  const hashView = window.location.hash.replace("#", "");
  if (["ranking", "profile", "funds", "lp", "compare"].includes(hashView)) state.view = hashView;
  state.fundById = new Map(state.data.funds.map((fund) => [Number(fund.fund_id), fund]));
  buildLookup();
  state.selectedGp = rankingBase()[0]?.gp_name || null;
  state.compareGps = rankingBase().slice(0, 5).map((row) => row.gp_name);
  renderControls();
  wireEvents();
  renderAll();
}

boot().catch((error) => {
  console.error(error);
  document.body.innerHTML = `<main class="site-shell"><section class="panel"><h2>서비스 화면 로딩 실패</h2><p>open_public_dashboard.bat로 정적 서버를 실행해야 데이터를 불러올 수 있습니다.</p></section></main>`;
});
