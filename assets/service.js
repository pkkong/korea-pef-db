(() => {
  const archive = Array.isArray(window.KPEF_DAILY_ARCHIVE) ? window.KPEF_DAILY_ARCHIVE : [];
  const lpMonitor = Array.isArray(window.KPEF_LP_MONITOR) ? window.KPEF_LP_MONITOR : [];
  const legacyArticles = Array.isArray(window.KPEF_ARTICLES) ? window.KPEF_ARTICLES : [];
  const storageKey = "kpef.saved.urls";
  const searchInput = document.getElementById("clipSearch");
  const searchArea = document.getElementById("searchArea");
  const searchToggle = document.getElementById("searchToggle");
  const searchClose = document.getElementById("searchClose");
  const dateSelect = document.getElementById("briefDateSelect");
  const dateInput = document.getElementById("briefDateInput");
  const dateLabel = document.getElementById("briefDateLabel");
  const weekdayLabel = document.getElementById("briefWeekday");
  const datePrev = document.getElementById("datePrev");
  const dateNext = document.getElementById("dateNext");
  const dateRail = document.getElementById("briefDateRail");
  const briefMeta = document.getElementById("briefMeta");
  const todayList = document.getElementById("todayList");
  const savedList = document.getElementById("savedList");
  const savedEmpty = document.getElementById("savedEmpty");
  const todayView = document.getElementById("todayView");
  const savedView = document.getElementById("savedView");
  const lpMonitorPanel = document.getElementById("lpMonitorPanel");
  const lpMonitorList = document.getElementById("lpMonitorList");
  const lpDetailBackdrop = document.getElementById("lpDetailBackdrop");
  const lpDetailSheet = document.getElementById("lpDetailSheet");
  const lpDetailBody = document.getElementById("lpDetailBody");
  const lpDetailClose = document.getElementById("lpDetailClose");
  const skeleton = document.querySelector(".skeleton-list");
  const navItems = [...document.querySelectorAll(".bottom-nav [data-view]")];

  const loadSaved = () => {
    try {
      return new Set(JSON.parse(localStorage.getItem(storageKey) || "[]"));
    } catch {
      return new Set();
    }
  };

  const queryDate = new URLSearchParams(window.location.search).get("date");
  let activeBrief = archive.find((brief) => brief.reportDate === queryDate) || archive[0] || {
    reportDate: "",
    visibleDate: "",
    basis: "",
    countLabel: `주요 뉴스 ${legacyArticles.length}건`,
    articles: legacyArticles
  };
  let articles = Array.isArray(activeBrief.articles) ? activeBrief.articles : [];
  let saved = loadSaved();
  let currentView = "today";

  const persistSaved = () => {
    localStorage.setItem(storageKey, JSON.stringify([...saved]));
  };

  const setSearchOpen = (open) => {
    if (!searchArea) return;
    const shouldOpen = Boolean(open || queryText());
    searchArea.classList.toggle("active", shouldOpen);
    if (searchToggle) searchToggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
    if (shouldOpen) window.requestAnimationFrame(() => searchInput && searchInput.focus());
  };

  const queryText = () => (searchInput ? searchInput.value.trim().toLowerCase() : "");

  const textMatches = (values, query) => {
    if (!query) return true;
    return values
      .filter((value) => value !== null && value !== undefined)
      .join(" ")
      .toLowerCase()
      .includes(query);
  };

  const allArchiveArticles = () => {
    const byUrl = new Map();
    const briefs = archive.length ? archive : [{
      reportDate: activeBrief.reportDate,
      visibleDate: activeBrief.visibleDate,
      articles: legacyArticles
    }];
    briefs.forEach((brief) => {
      const rows = Array.isArray(brief.articles) ? brief.articles : [];
      rows.forEach((article) => {
        if (!article.url || byUrl.has(article.url)) return;
        byUrl.set(article.url, {
          ...article,
          reportDate: brief.reportDate,
          visibleDate: brief.visibleDate
        });
      });
    });
    return [...byUrl.values()];
  };

  const weekdayName = (dateText) => {
    const date = new Date(`${dateText}T00:00:00+09:00`);
    if (Number.isNaN(date.getTime())) return "";
    return ["일", "월", "화", "수", "목", "금", "토"][date.getDay()];
  };

  const activeBriefIndex = () => archive.findIndex((brief) => brief.reportDate === activeBrief.reportDate);

  const setBriefByOffset = (offset) => {
    const index = activeBriefIndex();
    if (index < 0) return;
    const next = archive[index + offset];
    if (next) setActiveBrief(next.reportDate);
  };

  const updateDateControl = () => {
    const index = activeBriefIndex();
    if (dateInput) dateInput.value = activeBrief.reportDate || "";
    if (dateLabel) dateLabel.textContent = activeBrief.visibleDate || activeBrief.reportDate || "";
    if (weekdayLabel) weekdayLabel.textContent = activeBrief.reportDate ? weekdayName(activeBrief.reportDate) : "";
    if (datePrev) datePrev.disabled = index < 0 || index >= archive.length - 1;
    if (dateNext) dateNext.disabled = index <= 0;
  };

  const updateBriefChrome = (counts = {}) => {
    articles = Array.isArray(activeBrief.articles) ? activeBrief.articles : [];
    if (dateSelect) dateSelect.value = activeBrief.reportDate || "";
    updateDateControl();
    if (dateRail) {
      dateRail.querySelectorAll(".date-pill").forEach((button) => {
        const active = button.dataset.date === activeBrief.reportDate;
        button.classList.toggle("active", active);
        if (active) button.scrollIntoView({ block: "nearest", inline: "center" });
      });
    }
    if (briefMeta) {
      const query = queryText();
      if (query) {
        const newsCount = Number.isFinite(counts.newsCount) ? counts.newsCount : filtered().length;
        const noticeCount = Number.isFinite(counts.noticeCount) ? counts.noticeCount : filteredLpMonitor().length;
        briefMeta.textContent = `검색 결과 뉴스 ${newsCount}건 · 공식공고 ${noticeCount}건`;
        return;
      }
      const countLabel = activeBrief.countLabel || `주요 뉴스 ${articles.length}건`;
      briefMeta.textContent = countLabel;
    }
  };

  const setActiveBrief = (reportDate, options = {}) => {
    const next = archive.find((brief) => brief.reportDate === reportDate);
    if (!next) return;
    activeBrief = next;
    updateBriefChrome();
    render();
    if (options.updateUrl !== false && activeBrief.reportDate) {
      const url = new URL(window.location.href);
      url.searchParams.set("date", activeBrief.reportDate);
      window.history.replaceState({}, "", url);
    }
  };

  const filtered = () => {
    const query = queryText();
    if (!query) return articles;
    return articles.filter((article) => textMatches([
        article.title,
        article.source,
        article.section,
        article.subCategory,
        article.rawSection,
        Array.isArray(article.gpNames) ? article.gpNames.join(" ") : "",
        Array.isArray(article.searchTerms) ? article.searchTerms.join(" ") : ""
      ], query));
  };

  const filteredLpMonitor = () => {
    const query = queryText();
    if (!query) return lpMonitor;
    return lpMonitor.filter((item) => textMatches([
      item.title,
      item.displayTitle,
      item.lpName,
      item.programName,
      item.roundName,
      item.purpose,
      item.strategy,
      item.defaultTeam,
      eventLabel(item.eventType),
      assetClassLabel(item.assetClass),
      amountLabel(item.allocationAmount),
      item.announcedDate,
      item.applicationDeadline,
      Array.isArray(item.selectedGpNames) ? item.selectedGpNames.join(" ") : ""
    ], query));
  };

  const issueStopwords = new Set([
    "단독", "인터뷰", "인수", "매각", "매물", "품는다", "사들인다", "추진", "마무리", "엑시트",
    "리캡", "인수금융", "우선협상", "입찰", "지분", "지분매각", "회수", "전망", "기대감", "언급",
    "신규", "최종", "공식", "전략", "전문", "국내", "해외", "업계"
  ]);

  const issueTokens = (article) => {
    const text = [
      article.title,
      Array.isArray(article.gpNames) ? article.gpNames.join(" ") : ""
    ].join(" ");
    return new Set(
      text
        .toLowerCase()
        .replace(/[()[\]'"“”‘’….,·:：]/g, " ")
        .split(/\s+/)
        .map((token) => token.trim())
        .filter((token) => token.length >= 2 && !issueStopwords.has(token))
    );
  };

  const issueOverlap = (left, right) => {
    if (left.section !== right.section) return 0;
    const a = issueTokens(left);
    const b = issueTokens(right);
    let score = 0;
    a.forEach((token) => {
      if (b.has(token)) score += 1;
    });
    return score;
  };

  const clusterOrder = (items) => {
    const remaining = items.slice().sort((a, b) => (a.sectionOrder - b.sectionOrder) || ((a.rank || 0) - (b.rank || 0)));
    const ordered = [];
    while (remaining.length) {
      const seed = remaining.shift();
      ordered.push(seed);
      for (let index = 0; index < remaining.length; index += 1) {
        if (issueOverlap(seed, remaining[index]) >= 2) {
          ordered.push(remaining.splice(index, 1)[0]);
          index -= 1;
        }
      }
    }
    return ordered;
  };

  const groupBySection = (items) => {
    const groups = new Map();
    clusterOrder(items).forEach((article) => {
      if (!groups.has(article.section)) groups.set(article.section, []);
      groups.get(article.section).push(article);
    });
    return groups;
  };

  const eventLabel = (value) => ({
    new_notice: "신규 공고",
    deadline_soon: "마감 임박",
    deadline_closed: "마감",
    shortlist: "숏리스트",
    final_selection: "최종 선정",
    revision: "정정",
    cancellation: "취소",
    performance_update: "성과"
  }[value] || "후보");

  const amountLabel = (value) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return "";
    if (parsed >= 10000) return `${(parsed / 10000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}조`;
    return `${Math.round(parsed).toLocaleString("ko-KR")}억`;
  };

  const assetClassLabel = (value) => {
    const text = String(value || "");
    if (/private credit|credit|크레딧/i.test(text)) return "Credit";
    if (/vc|벤처/i.test(text)) return "VC";
    if (/pe|buyout|private equity|사모/i.test(text)) return "PE";
    return text;
  };

  const daysUntil = (dateText) => {
    if (!dateText) return null;
    const today = new Date();
    const target = new Date(`${dateText}T23:59:59+09:00`);
    if (Number.isNaN(target.getTime())) return null;
    return Math.ceil((target.getTime() - today.getTime()) / 86400000);
  };

  const deadlineBadge = (dateText) => {
    if (!dateText) return null;
    const remaining = daysUntil(dateText);
    if (remaining === null) return { label: "마감일 확인", urgent: false };
    if (remaining > 0) return { label: `D-${remaining}`, urgent: remaining <= 7 };
    if (remaining === 0) return { label: "오늘 마감", urgent: true };
    return { label: "마감", urgent: false };
  };

  const lpMonitorBadges = (item) => {
    const badges = [];
    const deadline = deadlineBadge(item.applicationDeadline);
    if (deadline) badges.push({ ...deadline, type: "deadline" });
    const amount = amountLabel(item.allocationAmount);
    if (amount) badges.push({ label: amount, type: "amount", urgent: false });
    const assetClass = assetClassLabel(item.assetClass);
    if (assetClass) badges.push({ label: assetClass, type: "asset", urgent: false });
    badges.push({ label: "공식", type: "official", urgent: false });
    return badges;
  };

  const scheduleLabel = (item) => {
    if (item.applicationDeadline) {
      const remaining = daysUntil(item.applicationDeadline);
      if (remaining === null) return `신청 마감 ${item.applicationDeadline}`;
      if (remaining > 0) return `신청 마감 ${item.applicationDeadline} · D-${remaining}`;
      if (remaining === 0) return `신청 마감 ${item.applicationDeadline} · 오늘 마감`;
      return `신청 마감 ${item.applicationDeadline} · 마감`;
    }
    if (item.eventDate) return `공고 확인 ${item.eventDate}`;
    return "공식 공고 확인";
  };

  const detailValue = (value, fallback = "-") => {
    if (Array.isArray(value)) return value.filter(Boolean).join(", ") || fallback;
    const text = String(value || "").trim();
    return text || fallback;
  };

  const appendDetailRow = (list, label, value) => {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = detailValue(value);
    list.append(dt, dd);
  };

  const openLpDetail = (item) => {
    if (!lpDetailSheet || !lpDetailBody || !lpDetailBackdrop) return;
    lpDetailBody.replaceChildren();

    const title = document.createElement("h3");
    title.className = "lp-detail-title";
    title.textContent = item.displayTitle || item.title;

    const summary = document.createElement("div");
    summary.className = "lp-detail-summary";
    [item.lpName, eventLabel(item.eventType), assetClassLabel(item.assetClass), amountLabel(item.allocationAmount)]
      .filter(Boolean)
      .forEach((label) => {
        const chip = document.createElement("span");
        chip.textContent = label;
        summary.append(chip);
      });

    const details = document.createElement("dl");
    details.className = "lp-detail-grid";
    appendDetailRow(details, "사업명", item.programName || item.displayTitle || item.title);
    appendDetailRow(details, "기관", item.lpName);
    appendDetailRow(details, "주목적", item.purpose || item.strategy || item.programName);
    appendDetailRow(details, "PE/VC 분류", assetClassLabel(item.assetClass));
    appendDetailRow(details, "담당자/팀", item.defaultTeam);
    appendDetailRow(details, "공고일", item.announcedDate || item.eventDate);
    appendDetailRow(details, "마감일", item.applicationDeadline);
    appendDetailRow(details, "향후 일정", scheduleLabel(item));

    const actions = document.createElement("div");
    actions.className = "lp-detail-actions";
    const official = document.createElement("a");
    official.href = item.url;
    official.target = "_blank";
    official.rel = "noreferrer";
    official.textContent = "공식 공고 보기";
    actions.append(official);

    lpDetailBody.append(title, summary, details, actions);

    const attachments = Array.isArray(item.attachments) ? item.attachments.filter((file) => file && file.url) : [];
    if (attachments.length) {
      const attachmentTitle = document.createElement("h4");
      attachmentTitle.className = "lp-attachment-title";
      attachmentTitle.textContent = "공식 첨부파일";
      const list = document.createElement("div");
      list.className = "lp-attachment-list";
      attachments.forEach((file, index) => {
        const link = document.createElement("a");
        link.href = file.url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = file.name || `공식 첨부파일 ${index + 1}`;
        list.append(link);
      });
      lpDetailBody.append(attachmentTitle, list);
    }

    lpDetailBackdrop.hidden = false;
    lpDetailSheet.hidden = false;
    document.body.style.overflow = "hidden";
  };

  const closeLpDetail = () => {
    if (!lpDetailSheet || !lpDetailBackdrop) return;
    lpDetailSheet.hidden = true;
    lpDetailBackdrop.hidden = true;
    document.body.style.overflow = "";
  };

  const renderLpMonitor = (items = lpMonitor) => {
    if (!lpMonitorPanel || !lpMonitorList) return;
    const visibleItems = items;
    lpMonitorPanel.hidden = !visibleItems.length;
    lpMonitorList.replaceChildren();
    const headTitle = lpMonitorPanel.querySelector(".lp-monitor-head h2");
    if (headTitle) headTitle.textContent = `공식 공고 ${items.length}건`;
    visibleItems.forEach((item) => {
      const link = document.createElement("button");
      link.type = "button";
      link.className = "lp-monitor-item";
      link.addEventListener("click", () => openLpDetail(item));

      const badges = document.createElement("span");
      badges.className = "lp-monitor-badges";
      lpMonitorBadges(item).forEach((badge) => {
        const pill = document.createElement("span");
        pill.className = `lp-badge ${badge.type || ""} ${badge.urgent ? "urgent" : ""}`.trim();
        pill.textContent = badge.label;
        badges.append(pill);
      });

      const title = document.createElement("strong");
      title.textContent = item.displayTitle || item.title;

      const meta = document.createElement("span");
      meta.className = "lp-monitor-meta";
      [item.lpName, eventLabel(item.eventType), item.applicationDeadline && `마감 ${item.applicationDeadline}`]
        .filter(Boolean)
        .forEach((label) => {
          const part = document.createElement("span");
          part.textContent = label;
          meta.append(part);
        });
      link.append(badges, title, meta);
      lpMonitorList.append(link);
    });
  };

  const makeCell = (article) => {
    const item = document.createElement("li");
    item.className = "clip-cell";

    const mark = document.createElement("span");
    mark.className = "publisher-icon";
    mark.setAttribute("aria-label", article.source || "언론사");
    const fallback = document.createElement("span");
    fallback.className = "publisher-fallback";
    fallback.textContent = article.sourceBadge || "뉴";
    if (article.sourceIconUrl) {
      const icon = document.createElement("img");
      icon.src = article.sourceIconUrl;
      icon.alt = "";
      icon.loading = "lazy";
      icon.addEventListener("error", () => mark.classList.add("fallback"));
      mark.append(icon, fallback);
    } else {
      mark.classList.add("fallback-only");
      mark.append(fallback);
    }

    const main = document.createElement("div");
    main.className = "cell-main-wrap";

    const link = document.createElement("a");
    link.className = "cell-main";
    link.href = article.url;
    link.target = "_blank";
    link.rel = "noreferrer";

    const title = document.createElement("span");
    title.className = "cell-title";
    const titleBadges = Array.isArray(article.titleBadges) ? article.titleBadges.filter(Boolean) : [];
    titleBadges.forEach((label) => {
      const badge = document.createElement("span");
      badge.className = "title-badge";
      badge.textContent = label;
      title.append(badge);
    });
    const titleText = document.createElement("span");
    titleText.textContent = article.title;
    title.append(titleText);

    const meta = document.createElement("span");
    meta.className = "cell-meta";
    const taxonomy = document.createElement("span");
    taxonomy.className = "taxonomy-meta";
    taxonomy.textContent = article.subCategory ? `${article.section} · ${article.subCategory}` : (article.section || "");
    const source = document.createElement("span");
    source.textContent = article.source || "출처 미확인";
    if (taxonomy.textContent) meta.append(taxonomy);
    meta.append(source);
    link.append(title, meta);
    main.append(link);

    const chips = document.createElement("span");
    chips.className = "cell-tags";
    const appendChip = (label, extraClass = "") => {
      if (!label) return;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = `context-chip ${extraClass}`.trim();
      chip.dataset.filter = label;
      chip.textContent = label;
      chips.append(chip);
    };
    const gpNames = Array.isArray(article.gpNames) ? article.gpNames.filter(Boolean) : [];
    gpNames.forEach((name) => appendChip(name));
    if (chips.childElementCount) main.append(chips);

    const save = document.createElement("button");
    save.className = "save-button";
    save.type = "button";
    save.dataset.url = article.url;
    const updateSaveState = () => {
      const isSaved = saved.has(article.url);
      save.classList.toggle("saved", isSaved);
      save.setAttribute("aria-label", isSaved ? "저장 해제" : "저장");
      save.title = isSaved ? "저장 해제" : "저장";
    };
    updateSaveState();

    item.append(mark, main, save);
    return item;
  };

  const renderGrouped = (target, items) => {
    target.replaceChildren();
    const groups = groupBySection(items);
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state visible";
      empty.innerHTML = "<strong>결과가 없습니다</strong><span>검색어를 줄여 다시 확인합니다.</span>";
      target.append(empty);
      return;
    }
    groups.forEach((groupItems, section) => {
      const block = document.createElement("section");
      block.className = "section-block";
      const title = document.createElement("h2");
      title.className = "section-title";
      title.textContent = section || "뉴스";
      const list = document.createElement("ul");
      list.className = "cell-list";
      groupItems.forEach((article) => list.append(makeCell(article)));
      block.append(title, list);
      target.append(block);
    });
  };

  const renderSaved = () => {
    const items = allArchiveArticles().filter((article) => saved.has(article.url));
    savedList.replaceChildren();
    savedEmpty.classList.toggle("visible", !items.length);
    if (items.length) renderGrouped(savedList, items);
  };

  const render = () => {
    if (skeleton) skeleton.classList.add("hidden");
    const newsItems = filtered();
    const noticeItems = filteredLpMonitor();
    updateBriefChrome({ newsCount: newsItems.length, noticeCount: noticeItems.length });
    renderLpMonitor(noticeItems);
    renderGrouped(todayList, newsItems);
    renderSaved();
  };

  const setView = (view) => {
    currentView = view;
    todayView.classList.toggle("active", view === "today");
    savedView.classList.toggle("active", view === "saved");
    navItems.forEach((item) => item.classList.toggle("active", item.dataset.view === view));
    if (view === "saved") renderSaved();
  };

  document.addEventListener("click", (event) => {
    const dateButton = event.target.closest(".date-pill[data-date]");
    if (dateButton) {
      setActiveBrief(dateButton.dataset.date);
      return;
    }

    const filterChip = event.target.closest(".context-chip[data-filter]");
    if (filterChip) {
      searchInput.value = filterChip.dataset.filter || "";
      setSearchOpen(true);
      setView("today");
      render();
      searchInput.focus();
      return;
    }

    const saveButton = event.target.closest(".save-button");
    if (saveButton) {
      const url = saveButton.dataset.url;
      if (saved.has(url)) saved.delete(url);
      else saved.add(url);
      persistSaved();
      document.querySelectorAll(`.save-button[data-url="${CSS.escape(url)}"]`).forEach((button) => {
        button.classList.toggle("saved", saved.has(url));
        button.setAttribute("aria-label", saved.has(url) ? "저장 해제" : "저장");
        button.title = saved.has(url) ? "저장 해제" : "저장";
      });
      if (currentView === "saved") renderSaved();
      return;
    }

    const navButton = event.target.closest("[data-view]");
    if (navButton) setView(navButton.dataset.view);
  });

  if (lpDetailClose) lpDetailClose.addEventListener("click", closeLpDetail);
  if (lpDetailBackdrop) lpDetailBackdrop.addEventListener("click", closeLpDetail);
  if (searchToggle) searchToggle.addEventListener("click", () => setSearchOpen(true));
  if (searchClose) {
    searchClose.addEventListener("click", () => {
      if (searchInput && searchInput.value) {
        searchInput.value = "";
        render();
      }
      setSearchOpen(false);
    });
  }
  if (datePrev) datePrev.addEventListener("click", () => setBriefByOffset(1));
  if (dateNext) dateNext.addEventListener("click", () => setBriefByOffset(-1));
  if (dateInput) {
    dateInput.addEventListener("change", () => {
      const next = archive.find((brief) => brief.reportDate === dateInput.value);
      if (next) {
        setActiveBrief(next.reportDate);
        return;
      }
      const missing = dateInput.value;
      updateDateControl();
      if (briefMeta && missing) briefMeta.textContent = `${missing.replaceAll("-", ".")} 브리프가 아직 없습니다`;
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeLpDetail();
      if (searchInput && !searchInput.value) setSearchOpen(false);
    }
  });

  if (searchInput) searchInput.addEventListener("input", () => {
    setSearchOpen(true);
    render();
  });
  if (dateSelect) {
    dateSelect.addEventListener("change", () => setActiveBrief(dateSelect.value));
  }
  render();
})(); 
