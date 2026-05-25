const COLORS = ["#171717", "#525252", "#737373", "#a3a3a3", "#404040", "#d4d4d4"];

const state = {
  data: null,
  period: null,
  basis: "primary",
  selectedGp: null,
  compareGps: [],
  activeProfileView: "overview",
  fundById: new Map(),
  lookup: new Map()
};

const fmtInt = new Intl.NumberFormat("ko-KR");
const fmtNum = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 });
const fmtRank = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });

function byId(id) {
  return document.getElementById(id);
}

function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function fmtEokFromTrn(value) {
  return `${fmtInt.format(Math.round(num(value) * 10000))}억`;
}

function fmtEokCompact(value) {
  const eok = num(value) * 10000;
  if (Math.abs(eok) >= 10000) return `${fmtNum.format(eok / 10000)}조`;
  return `${fmtInt.format(Math.round(eok))}억`;
}

function fmtPct(value) {
  return `${fmtNum.format(num(value))}%`;
}

function splitNames(value) {
  return String(value || "").split(";").map((v) => v.trim()).filter(Boolean);
}

function normalizeLookup(value) {
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

function dash(value) {
  const text = String(value ?? "").trim();
  return text ? escapeHtml(text) : "-";
}

function verificationLabel(value) {
  return {
    "OFFICIAL_SOURCE_VERIFIED": "공식 출처 확인",
    "IDENTIFIER_VERIFIED": "식별자 확인",
    "SUPPORTING_SOURCE_ONLY": "보조 출처",
    "FSS_NAME_ONLY": "FSS명만"
  }[value] || "-";
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

function actionClass(value) {
  if (value === "유지" || value === "뉴스레터에 GP/People 맥락 연결" || value === "People coverage 유지 점검") return "";
  if (String(value || "").includes("선택정보") || String(value || "").includes("검증")) return "warn";
  return "danger";
}

function ownerLabel(value) {
  return {
    "GP profile": "GP 프로필",
    "People DB": "인물 DB",
    "Newsletter": "뉴스레터"
  }[value] || value || "-";
}

function shortActionLabel(value) {
  const text = String(value || "-");
  if (text.includes("프로필 필수정보")) return "프로필 보강";
  if (text.includes("식별자")) return "식별자 보강";
  if (text.includes("People 1차")) return "인물 수집";
  if (text.includes("한글명")) return "인물 검증";
  if (text.includes("뉴스레터")) return "뉴스 맥락";
  if (text.includes("유지")) return "유지";
  return text;
}

function periodRows() {
  return state.basis === "full" ? state.data.gp_period_full_credit : state.data.gp_period_primary;
}

function currentPeriod() {
  return state.data.periods.find((row) => row.period_label === state.period) || state.data.periods.at(-1);
}

function currentRanking() {
  const rows = periodRows().filter((row) => row.period_label === state.period);
  const total = rows.reduce((sum, row) => sum + num(row.commitment_aum_proxy_trn_krw), 0);
  return rows
    .slice()
    .sort((a, b) => num(b.commitment_aum_proxy_trn_krw) - num(a.commitment_aum_proxy_trn_krw) || String(a.gp_name).localeCompare(String(b.gp_name), "ko"))
    .map((row, index) => ({
      ...row,
      rank: index + 1,
      share: total ? (num(row.commitment_aum_proxy_trn_krw) / total) * 100 : 0
    }));
}

function gpNames() {
  const names = new Set();
  state.data.gp_period_primary.forEach((row) => names.add(row.gp_name));
  state.data.gp_period_full_credit.forEach((row) => names.add(row.gp_name));
  return Array.from(names).filter(Boolean).sort((a, b) => a.localeCompare(b, "ko"));
}

function buildLookup() {
  const lookup = new Map();
  gpNames().forEach((name) => lookup.set(normalizeLookup(name), name));
  state.data.gp_aliases.forEach((row) => {
    if (row.alias_gp_name && row.canonical_gp_name) {
      lookup.set(normalizeLookup(row.alias_gp_name), row.canonical_gp_name);
    }
  });
  state.data.gp_profiles.forEach((profile) => {
    const canonical = profile.gp_name;
    [
      profile.display_name_ko,
      profile.legal_entity_name_ko,
      profile.legal_entity_name_en,
      ...(splitNames(profile.alias_names))
    ].forEach((alias) => {
      if (alias && canonical) lookup.set(normalizeLookup(alias), canonical);
    });
  });
  state.lookup = lookup;
}

function resolveGpInput(value) {
  return state.lookup.get(normalizeLookup(value)) || "";
}

function profileForGp(gpName) {
  return state.data.gp_profiles.find((row) => row.gp_name === gpName);
}

function fallbackRowForGp(gpName) {
  const profile = profileForGp(gpName);
  const news = newsForGp(gpName);
  if (!profile && !news) return null;
  return {
    gp_name: profile?.gp_name || news?.standard_gp_name || gpName,
    rank: num(profile?.latest_primary_rank || news?.latest_primary_rank),
    active_fund_count: num(profile?.latest_primary_active_fund_count || news?.latest_primary_active_fund_count),
    commitment_aum_proxy_trn_krw: num(profile?.latest_primary_aum_proxy_krw_100mn || news?.["latest_primary_aum_억원"]) / 10000,
    share: 0,
    out_of_ranking: true
  };
}

function cumulativeForGp(gpName) {
  return state.data.gp_cumulative.find((row) => row.gp_name === gpName);
}

function aliasesForGp(gpName) {
  return state.data.gp_aliases.filter((row) => row.canonical_gp_name === gpName);
}

function newsForGp(gpName) {
  const profile = profileForGp(gpName);
  const integration = (state.data.service_integration_queue || []).find((row) => (
    row.standard_gp_name === gpName ||
    String(row.source_gp_id || "") === String(profile?.source_gp_id || "")
  ));
  if (integration) return integration;
  return (state.data.news_gp_update_queue || []).find((row) => (
    row.standard_gp_name === gpName ||
    String(row.source_gp_id || "") === String(profile?.source_gp_id || "")
  ));
}

function actionText(row) {
  return row?.integrated_action || row?.suggested_action || row?.news_action || "-";
}

function queueRows() {
  return (state.data.service_integration_queue || []).length
    ? state.data.service_integration_queue
    : (state.data.news_gp_update_queue || []);
}

function peopleForGp(gpName, profile = profileForGp(gpName)) {
  const gpId = String(profile?.source_gp_id || "");
  return (state.data.people_current_gp || [])
    .filter((person) => (
      (gpId && String(person.gp_id || "") === gpId) ||
      person.gp_name === gpName
    ))
    .sort((a, b) => String(a.person_name_ko || "").localeCompare(String(b.person_name_ko || ""), "ko"));
}

function rolesForPerson(personId) {
  return (state.data.people_roles || []).filter((role) => String(role.person_id) === String(personId));
}

function educationForPerson(personId) {
  return (state.data.people_education || []).filter((row) => String(row.person_id) === String(personId));
}

function searchTextForGp(gpName) {
  const profile = profileForGp(gpName);
  const aliases = aliasesForGp(gpName).map((row) => row.alias_gp_name);
  return normalizeLookup([
    gpName,
    profile?.display_name_ko,
    profile?.legal_entity_name_ko,
    profile?.legal_entity_name_en,
    profile?.alias_names,
    ...aliases
  ].filter(Boolean).join(" "));
}

function gpSeries(gpName) {
  const rowsByPeriod = new Map(periodRows().filter((row) => row.gp_name === gpName).map((row) => [row.period_label, row]));
  return state.data.periods.map((period) => ({
    x: period.period_label,
    date: period.as_of_date,
    y: rowsByPeriod.has(period.period_label) ? num(rowsByPeriod.get(period.period_label).commitment_aum_proxy_trn_krw) : 0
  }));
}

function activeFundsForGp(gpName) {
  return state.data.fund_snapshots
    .filter((row) => row.period_label === state.period && splitNames(row.canonical_gp_names).includes(gpName))
    .sort((a, b) => num(b.commitment_trn_krw) - num(a.commitment_trn_krw) || String(a.fund_name).localeCompare(String(b.fund_name), "ko"));
}

function setText(id, value) {
  byId(id).textContent = value;
}

function setHtml(id, value) {
  byId(id).innerHTML = value;
}

function renderControls() {
  const periodSelect = byId("periodSelect");
  periodSelect.innerHTML = state.data.periods
    .map((period) => `<option value="${period.period_label}">${period.period_label} · ${period.as_of_date}</option>`)
    .join("");
  periodSelect.value = state.period;

  const list = byId("gpList");
  const suggestions = new Set(gpNames());
  state.data.gp_aliases.forEach((row) => {
    if (row.alias_gp_name) suggestions.add(row.alias_gp_name);
  });
  state.data.gp_profiles.forEach((profile) => {
    [profile.display_name_ko, profile.legal_entity_name_ko, profile.legal_entity_name_en].forEach((name) => {
      if (name) suggestions.add(name);
    });
  });
  list.innerHTML = Array.from(suggestions)
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b, "ko"))
    .map((name) => `<option value="${escapeHtml(name)}"></option>`)
    .join("");

  byId("basisSelect").value = state.basis;
  setText("dataMeta", `${state.data.meta.latest_period} · ${state.data.meta.latest_as_of_date}`);
  const basisLabel = String(state.data.meta.aum_basis || "").replace(/proxy\s+AUM/gi, "AUM 프록시");
  setText("sourceLine", `${basisLabel} · 생성 ${String(state.data.meta.generated_at).slice(0, 10)}`);
}

function renderMetrics() {
  const period = currentPeriod();
  const year = Number(String(period.as_of_date).slice(0, 4));
  const yearNew = state.data.new_funds_by_year.find((row) => Number(row.year) === year);
  const ranking = currentRanking();
  const totalRanking = ranking.reduce((sum, row) => sum + num(row.commitment_aum_proxy_trn_krw), 0);
  const top5 = ranking.slice(0, 5).reduce((sum, row) => sum + num(row.commitment_aum_proxy_trn_krw), 0);

  setText("metricFunds", fmtInt.format(num(period.fund_count)));
  setText("metricFundsNote", `${period.as_of_date} 기준 운용중`);
  setText("metricGps", fmtInt.format(ranking.length || num(period.primary_gp_count)));
  const people = state.data.people_current_gp || [];
  const peopleGps = new Set(people.map((person) => person.gp_id || person.gp_name).filter(Boolean));
  setText("metricPeople", fmtInt.format(people.length));
  setText("metricPeopleNote", `연결 GP ${fmtInt.format(peopleGps.size)}곳`);
  setText("metricAum", fmtEokCompact(period.commitment_trn_krw));
  setText("metricNewFunds", yearNew ? fmtInt.format(num(yearNew.new_fund_count)) : "-");
  setText("metricNewFundsNote", `${year}년 신규 · ${yearNew ? fmtEokFromTrn(yearNew.first_seen_commitment_trn_krw) : "0억"}`);
  setText("metricTopShare", totalRanking ? fmtPct((top5 / totalRanking) * 100) : "-");
}

function renderRanking() {
  const q = normalizeLookup(byId("rankSearch").value);
  const limit = Number(byId("rankLimit").value);
  const rows = currentRanking()
    .filter((row) => !q || searchTextForGp(row.gp_name).includes(q))
    .slice(0, limit);

  byId("rankingBody").innerHTML = rows.map((row) => {
    const profile = profileForGp(row.gp_name);
    const news = newsForGp(row.gp_name);
    const sub = [
      profile?.service_ready ? "프로필 준비" : "프로필 보강",
      `펀드 ${fmtInt.format(num(row.active_fund_count))}개`,
      news ? "뉴스 큐" : ""
    ].filter(Boolean).join(" · ");
    return `
      <tr class="clickable ${row.gp_name === state.selectedGp ? "selected" : ""}" data-gp="${escapeAttr(row.gp_name)}">
        <td><span class="rank-no">#${row.rank}</span></td>
        <td>
          <div class="gp-name-cell">
            <strong>${escapeHtml(row.gp_name)}</strong>
            <span>${escapeHtml(sub)}</span>
          </div>
        </td>
        <td class="numeric">${fmtEokCompact(row.commitment_aum_proxy_trn_krw)}</td>
        <td class="numeric">${fmtPct(row.share)}</td>
      </tr>
    `;
  }).join("");

  byId("rankingBody").querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      selectGp(tr.dataset.gp);
    });
  });
}

function renderNewsQueue() {
  const rows = queueRows();
  const list = byId("newsQueueList");
  if (!rows.length) {
    list.innerHTML = `<div class="empty-state">최근 뉴스에 연결된 GP 업데이트 큐가 없습니다.</div>`;
    return;
  }
  list.innerHTML = rows.slice(0, 8).map((row) => `
    <article class="queue-item" data-gp="${escapeAttr(row.standard_gp_name)}">
      <div class="queue-top">
        <div>
          <div class="queue-name">${escapeHtml(row.standard_gp_name)}</div>
          <div class="queue-meta">${escapeHtml(ownerLabel(row.owner) || row.latest_publisher || "-")} · 기사 ${escapeHtml(row.article_count || "0")}건 · 인물 ${escapeHtml(row.people_count || "0")}명</div>
        </div>
        <span class="badge ${actionClass(actionText(row))}" title="${escapeAttr(actionText(row))}">${escapeHtml(shortActionLabel(actionText(row)))}</span>
      </div>
      <div class="queue-title">${escapeHtml(row.latest_title || row.people_next_action || "")}</div>
    </article>
  `).join("");
  list.querySelectorAll(".queue-item").forEach((item) => {
    item.addEventListener("click", () => selectGp(item.dataset.gp));
  });
}

function selectGp(gpName) {
  if (!gpName) return;
  state.selectedGp = gpName;
  if (!state.compareGps.includes(gpName)) {
    state.compareGps = [gpName, ...state.compareGps].slice(0, 6);
  }
  renderAll();
  byId("profile").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderGpDetail() {
  const ranking = currentRanking();
  const row = ranking.find((item) => item.gp_name === state.selectedGp)
    || fallbackRowForGp(state.selectedGp)
    || ranking[0];
  if (!row) return;
  state.selectedGp = row.gp_name;

  const profile = profileForGp(row.gp_name);
  const cumulative = cumulativeForGp(row.gp_name);
  const aliases = aliasesForGp(row.gp_name);
  const news = newsForGp(row.gp_name);

  setText("gpTitle", row.gp_name);
  setText(
    "gpSubtitle",
    profile
      ? `관측 ${profile.first_seen_period || "-"} ~ ${profile.last_seen_period || "-"} · alias ${aliases.length}개`
      : "GP 기준표 프로필 없음"
  );
  setText("gpStatus", profile ? verificationLabel(profile.verification_level) : "프로필 없음");
  byId("gpStatus").className = `status ${profile?.service_ready ? "" : "warn"}`;
  setText("gpNewsStatus", news ? `뉴스 ${shortActionLabel(actionText(news))}` : "뉴스 없음");
  byId("gpNewsStatus").className = `status secondary ${news ? actionClass(actionText(news)) : ""}`;
  setText("gpRank", row.rank ? `#${fmtRank.format(row.rank)}` : "-");
  setText("gpAum", row.commitment_aum_proxy_trn_krw ? fmtEokCompact(row.commitment_aum_proxy_trn_krw) : "-");
  setText("gpCumulativeAum", cumulative ? fmtEokCompact(cumulative.cumulative_commitment_trn_krw) : "-");
  setText("gpCumulativeNote", cumulative ? `누적 순위 #${fmtRank.format(cumulative.cumulative_rank)}` : "역대 최대 약정액 합산");
  setText(
    "gpFundCount",
    cumulative
      ? `${fmtInt.format(num(row.active_fund_count))} / ${fmtInt.format(num(cumulative.cumulative_fund_count))}`
      : fmtInt.format(num(row.active_fund_count))
  );
  setText("gpFundCountNote", "운용중 / 누적");

  renderGpProfile(profile);
  renderFunds(row.gp_name);
  renderPeople(row.gp_name, profile);
  renderQuality(profile, news);
  renderLineChart("gpTrendChart", [{ name: row.gp_name, color: COLORS[0], values: gpSeries(row.gp_name) }], fmtEokCompact);
}

function renderGpProfile(profile) {
  if (!profile) {
    ["gpLegalKo", "gpLegalEn", "gpCategory", "gpEstablished", "gpRepresentative", "gpPhone", "gpBusinessNo", "gpCorpNo", "gpAddress", "gpLinks"]
      .forEach((id) => setText(id, "-"));
    return;
  }
  setHtml("gpLegalKo", dash(profile.legal_entity_name_ko || profile.display_name_ko || profile.gp_name));
  setHtml("gpLegalEn", dash(profile.legal_entity_name_en));
  setHtml("gpCategory", escapeHtml(categoryLabel(profile.company_category)));
  setHtml("gpEstablished", dash(profile.established_date || profile.firm_founded_date || profile.firm_founded_year));
  setHtml("gpRepresentative", dash(profile.representative_name));
  setHtml("gpPhone", dash(profile.phone_number));
  setHtml("gpBusinessNo", dash(profile.business_registration_number));
  setHtml("gpCorpNo", dash(profile.corporate_registration_number));
  setHtml("gpAddress", dash(profile.headquarters_address));
  const links = [];
  if (profile.homepage_url) links.push(`<a href="${escapeAttr(profile.homepage_url)}" target="_blank" rel="noreferrer">홈페이지</a>`);
  if (profile.primary_source_url) links.push(`<a href="${escapeAttr(profile.primary_source_url)}" target="_blank" rel="noreferrer">근거</a>`);
  setHtml("gpLinks", links.length ? links.join(" · ") : "-");
}

function renderFunds(gpName) {
  const funds = activeFundsForGp(gpName);
  setText("fundListSubtitle", `${state.period} 기준 ${gpName} 관련 운용중 펀드 ${fmtInt.format(funds.length)}개`);
  byId("fundBody").innerHTML = funds.map((fund) => {
    const master = state.fundById.get(Number(fund.fund_id));
    return `
      <tr>
        <td>${escapeHtml(fund.fund_name)}</td>
        <td>${escapeHtml(fund.raw_gp_names || fund.canonical_gp_names)}</td>
        <td>${escapeHtml(master?.established_date || "")}</td>
        <td class="numeric">${fmtEokFromTrn(fund.commitment_trn_krw)}</td>
        <td>${escapeHtml(fund.period_label)}</td>
      </tr>
    `;
  }).join("") || `<tr><td colspan="5">선택 시점 운용중 펀드가 없습니다.</td></tr>`;
}

function renderPeople(gpName, profile) {
  const people = peopleForGp(gpName, profile);
  setText("peopleListSubtitle", `${gpName} 연결 인물 ${fmtInt.format(people.length)}명`);
  const target = byId("peopleList");
  if (!people.length) {
    target.innerHTML = `
      <div class="empty-state">
        <strong>연결된 인물 DB가 없습니다</strong>
        <span>뉴스 노출 또는 Top GP 우선순위에 따라 인력 수집 큐로 넘깁니다.</span>
      </div>
    `;
    return;
  }
  target.innerHTML = people.map((person) => {
    const roles = rolesForPerson(person.person_id);
    const education = educationForPerson(person.person_id);
    const priorRoles = roles
      .filter((role) => !Number(role.is_current))
      .slice(0, 3)
      .map((role) => role.org_name)
      .filter(Boolean);
    const schools = education
      .slice(0, 3)
      .map((row) => [row.school_name, row.degree, row.major].filter(Boolean).join(" "))
      .filter(Boolean);
    return `
      <article class="person-card">
        <div>
          <strong>${escapeHtml(person.person_name_ko || person.person_name_en || "-")}</strong>
          <span>${escapeHtml(person.person_name_en || "")}</span>
        </div>
        <div class="queue-meta">${escapeHtml(person.current_title || person.role_title || "-")}${person.team ? ` · ${escapeHtml(person.team)}` : ""}</div>
        ${priorRoles.length ? `<div class="person-detail">이전/기타: ${escapeHtml(priorRoles.join(" · "))}</div>` : ""}
        ${schools.length ? `<div class="person-detail">학력: ${escapeHtml(schools.join(" · "))}</div>` : ""}
        ${person.primary_source_url ? `<a href="${escapeAttr(person.primary_source_url)}" target="_blank" rel="noreferrer">인물 근거 열기</a>` : ""}
      </article>
    `;
  }).join("");
}

function renderQuality(profile, news) {
  const checks = [
    ["공식/준공식 출처", profile && profile.verification_level !== "FSS_NAME_ONLY"],
    ["서비스 필수 프로필", Boolean(profile?.service_ready)],
    ["사업자등록번호", Boolean(profile?.business_registration_number)],
    ["법인등록번호", Boolean(profile?.corporate_registration_number)],
    ["홈페이지", Boolean(profile?.homepage_url)]
  ];
  byId("gpQualityList").innerHTML = checks.map(([label, ok]) => `
    <div class="quality-item">
      <span class="badge ${ok ? "" : "warn"}">${ok ? "확보" : "비어있음"}</span>
      ${escapeHtml(label)}
    </div>
  `).join("");

  if (!news) {
    setHtml("gpNewsDetail", `<div class="empty-state">최근 뉴스 업데이트 큐에 없는 GP입니다.</div>`);
    return;
  }
  setHtml("gpNewsDetail", `
    <div class="quality-item"><span class="badge ${actionClass(actionText(news))}" title="${escapeAttr(actionText(news))}">${escapeHtml(shortActionLabel(actionText(news)))}</span> 기사 ${escapeHtml(news.article_count || "0")}건</div>
    ${news.owner ? `<div class="quality-item">담당: ${escapeHtml(ownerLabel(news.owner))}<br>${escapeHtml(news.people_next_action || "")}</div>` : ""}
    <div class="quality-item">${escapeHtml(news.latest_publisher || "-")} · ${escapeHtml(news.latest_article_at || "-")}<br>${escapeHtml(news.latest_title || "")}</div>
    ${news.latest_url ? `<div class="quality-item"><a href="${escapeAttr(news.latest_url)}" target="_blank" rel="noreferrer">최근 기사 열기</a></div>` : ""}
  `);
}

function renderMarketChart() {
  const values = state.data.periods.map((period) => ({
    x: period.period_label,
    date: period.as_of_date,
    y: num(period.commitment_trn_krw)
  }));
  renderLineChart("marketChart", [{ name: "시장 전체 약정액", color: COLORS[1], values }], fmtEokCompact);
}

function renderNewFundsChart() {
  const values = state.data.new_funds_by_year.map((row) => ({
    label: String(row.year),
    value: num(row.first_seen_commitment_trn_krw),
    count: num(row.new_fund_count)
  }));
  renderBarChart("newFundsChart", values);
}

function renderCompare() {
  if (state.selectedGp && !state.compareGps.includes(state.selectedGp)) {
    state.compareGps = [state.selectedGp, ...state.compareGps].slice(0, 6);
  }
  byId("compareChips").innerHTML = state.compareGps.map((gp) => `
    <span class="chip">${escapeHtml(gp)} <button data-gp="${escapeAttr(gp)}" title="remove">×</button></span>
  `).join("");
  byId("compareChips").querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.compareGps = state.compareGps.filter((gp) => gp !== button.dataset.gp);
      renderCompare();
    });
  });

  const series = state.compareGps.map((gp, index) => ({
    name: gp,
    color: COLORS[index % COLORS.length],
    values: gpSeries(gp)
  }));
  renderLineChart("compareChart", series, fmtEokCompact);
}

function renderSourceDocs() {
  const docs = (state.data.source_documents || []).slice(-8).reverse();
  byId("sourceDocs").innerHTML = docs.map((doc) => `
    <article class="source-item">
      <strong>${escapeHtml(doc.period_label || "")} · ${escapeHtml(doc.as_of_date || "")}</strong><br>
      ${doc.source_url ? `<a href="${escapeAttr(doc.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(doc.title || doc.source_url)}</a>` : escapeHtml(doc.title || "")}
    </article>
  `).join("");
}

function renderLineChart(id, series, formatter) {
  const el = byId(id);
  if (!el) return;
  const width = Math.max(640, el.clientWidth - 24);
  const height = 270;
  const pad = { top: 22, right: 18, bottom: 34, left: 62 };
  const allValues = series.flatMap((s) => s.values.map((v) => num(v.y)));
  const maxY = Math.max(...allValues, 1);
  const xCount = series[0] ? series[0].values.length : 0;
  const x = (idx) => pad.left + (xCount <= 1 ? 0 : idx * (width - pad.left - pad.right) / (xCount - 1));
  const y = (value) => height - pad.bottom - (num(value) / maxY) * (height - pad.top - pad.bottom);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((v) => maxY * v);
  const labelIndexes = [0, Math.floor((xCount - 1) / 2), xCount - 1].filter((v, i, arr) => v >= 0 && arr.indexOf(v) === i);

  const grid = ticks.map((tick) => `
    <line x1="${pad.left}" x2="${width - pad.right}" y1="${y(tick)}" y2="${y(tick)}" stroke="rgba(104,115,134,0.18)" />
        <text x="${pad.left - 9}" y="${y(tick) + 4}" text-anchor="end" font-size="11" fill="#737373">${formatter(tick)}</text>
  `).join("");

  const paths = series.map((s) => {
    const points = s.values.map((point, idx) => `${x(idx)},${y(point.y)}`).join(" ");
    return `<polyline points="${points}" fill="none" stroke="${s.color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />`;
  }).join("");

  const labels = labelIndexes.map((idx) => {
    const point = series[0]?.values[idx];
    return `<text x="${x(idx)}" y="${height - 10}" text-anchor="middle" font-size="11" fill="#737373">${point ? point.x : ""}</text>`;
  }).join("");

  const legend = series.map((s) => `<span><i class="dot" style="background:${s.color}"></i>${escapeHtml(s.name)}</span>`).join("");
  el.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" role="img">
      ${grid}
      ${paths}
      ${labels}
    </svg>
    <div class="legend">${legend}</div>
  `;
}

function renderBarChart(id, values) {
  const el = byId(id);
  const width = Math.max(760, el.clientWidth - 24);
  const height = 280;
  const pad = { top: 20, right: 18, bottom: 42, left: 62 };
  const maxY = Math.max(...values.map((v) => v.value), 1);
  const gap = 5;
  const barW = (width - pad.left - pad.right - gap * (values.length - 1)) / values.length;
  const y = (value) => height - pad.bottom - (num(value) / maxY) * (height - pad.top - pad.bottom);
  const ticks = [0, 0.5, 1].map((v) => maxY * v).map((tick) => `
    <line x1="${pad.left}" x2="${width - pad.right}" y1="${y(tick)}" y2="${y(tick)}" stroke="rgba(104,115,134,0.18)" />
    <text x="${pad.left - 9}" y="${y(tick) + 4}" text-anchor="end" font-size="11" fill="#737373">${fmtEokCompact(tick)}</text>
  `).join("");
  const bars = values.map((v, idx) => {
    const x = pad.left + idx * (barW + gap);
    const h = height - pad.bottom - y(v.value);
    return `
      <rect x="${x}" y="${y(v.value)}" width="${barW}" height="${h}" rx="5" fill="${COLORS[idx % COLORS.length]}" opacity="0.88">
        <title>${v.label}: ${fmtEokFromTrn(v.value)} / ${fmtInt.format(v.count)}개</title>
      </rect>
      ${idx % 2 === 0 ? `<text x="${x + barW / 2}" y="${height - 14}" text-anchor="middle" font-size="10" fill="#737373">${v.label}</text>` : ""}
    `;
  }).join("");
  el.innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}">${ticks}${bars}</svg>`;
}

function setProfileView(view) {
  state.activeProfileView = view;
  document.querySelectorAll(".profile-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === view);
  });
  document.querySelectorAll(".profile-view").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === view);
  });
  if (view === "analytics") {
    renderGpDetail();
    renderMarketChart();
  }
}

function renderAll() {
  renderMetrics();
  renderRanking();
  renderNewsQueue();
  renderGpDetail();
  renderMarketChart();
  renderNewFundsChart();
  renderCompare();
  renderSourceDocs();
}

function wireEvents() {
  byId("periodSelect").addEventListener("change", (event) => {
    state.period = event.target.value;
    renderAll();
  });
  byId("basisSelect").addEventListener("change", (event) => {
    state.basis = event.target.value;
    renderAll();
  });
  byId("rankSearch").addEventListener("input", renderRanking);
  byId("rankLimit").addEventListener("change", renderRanking);
  byId("selectGpButton").addEventListener("click", () => {
    const resolved = resolveGpInput(byId("gpInput").value);
    if (resolved) {
      byId("gpInput").classList.remove("input-error");
      selectGp(resolved);
    } else {
      byId("gpInput").classList.add("input-error");
    }
  });
  byId("gpInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") byId("selectGpButton").click();
  });
  byId("addCompareButton").addEventListener("click", () => {
    const resolved = resolveGpInput(byId("compareInput").value);
    if (resolved && !state.compareGps.includes(resolved)) {
      state.compareGps = [...state.compareGps, resolved].slice(0, 6);
      byId("compareInput").value = "";
      renderCompare();
    }
  });
  byId("compareInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") byId("addCompareButton").click();
  });
  document.querySelectorAll(".profile-tab").forEach((tab) => {
    tab.addEventListener("click", () => setProfileView(tab.dataset.view));
  });
  document.querySelectorAll("[data-profile-tab-target]").forEach((link) => {
    link.addEventListener("click", () => {
      setProfileView(link.dataset.profileTabTarget);
      byId("profile").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  window.addEventListener("resize", () => {
    renderGpDetail();
    renderMarketChart();
    renderNewFundsChart();
    renderCompare();
  });
}

async function boot() {
  const response = await fetch("data/dashboard_data.json");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  state.data = await response.json();
  state.period = state.data.meta.latest_period;
  state.fundById = new Map(state.data.funds.map((fund) => [Number(fund.fund_id), fund]));
  buildLookup();
  const top = currentRanking()[0];
  state.selectedGp = top ? top.gp_name : null;
  state.compareGps = currentRanking().slice(0, 5).map((row) => row.gp_name);
  renderControls();
  wireEvents();
  renderAll();
}

boot().catch((error) => {
  console.error(error);
  document.body.innerHTML = `
    <main class="app-shell">
      <section class="panel">
        <h2>대시보드 로딩 실패</h2>
        <p class="footnote">정적 서버에서 열어야 data/dashboard_data.json을 불러올 수 있습니다.</p>
        <p class="footnote">실행: open_dashboard.bat 또는 python scripts/serve_dashboard.py</p>
      </section>
    </main>
  `;
});
