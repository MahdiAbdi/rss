(function () {
  var feedUrl = window.FEED_URL || "data/feed.json";
  var feed = null;
  var activeFilterId = "all";

  var updatedEl = document.getElementById("updated");
  var daterangeEl = document.getElementById("daterange");
  var filtersEl = document.getElementById("filters");
  var loadingEl = document.getElementById("loading");
  var errorEl = document.getElementById("error");
  var cardListEl = document.getElementById("card-list");
  var readerOverlayEl = document.getElementById("reader-overlay");
  var readerCloseEl = document.getElementById("reader-close");
  var readerMetaEl = document.getElementById("reader-meta");
  var readerTitleEl = document.getElementById("reader-title");
  var readerOriginalEl = document.getElementById("reader-original");
  var readerBodyEl = document.getElementById("reader-body");
  var themeToggleEl = document.getElementById("theme-toggle");

  function escapeHtml(s) {
    if (s == null || s === undefined) return "";
    var div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function formatDate(isoStr) {
    if (!isoStr) return "";
    try {
      var d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return d.toLocaleDateString(undefined, { dateStyle: "medium" });
    } catch (e) {
      return isoStr;
    }
  }

  function formatDateRange(minStr, maxStr) {
    if (!minStr && !maxStr) return "";
    if (minStr && maxStr) return "Articles from " + formatDate(minStr) + " to " + formatDate(maxStr);
    if (minStr) return "From " + formatDate(minStr);
    return "Until " + formatDate(maxStr);
  }

  function applyTheme(theme) {
    var root = document.documentElement;
    if (theme === "dark" || theme === "light") {
      root.setAttribute("data-theme", theme);
      try { localStorage.setItem("feed-theme", theme); } catch (e) {}
      themeToggleEl.textContent = theme === "dark" ? "Light" : "Dark";
    }
  }

  function initTheme() {
    var stored = "";
    try { stored = localStorage.getItem("feed-theme"); } catch (e) {}
    var theme = stored === "dark" || stored === "light" ? stored : "light";
    applyTheme(theme);
  }

  function handleThemeToggle() {
    var root = document.documentElement;
    var current = root.getAttribute("data-theme") || "light";
    applyTheme(current === "dark" ? "light" : "dark");
  }

  function showError(msg) {
    loadingEl.style.display = "none";
    cardListEl.style.display = "none";
    errorEl.textContent = msg || "Could not load feed.";
    errorEl.style.display = "block";
  }

  function getFlatItems() {
    if (!feed || !feed.sources) return [];
    var items = [];
    feed.sources.forEach(function (source) {
      (source.items || []).forEach(function (item) {
        items.push({ source: source, item: item });
      });
    });
    return items;
  }

  function getFilteredItems() {
    var flat = getFlatItems();
    if (activeFilterId === "all") return flat;
    return flat.filter(function (entry) { return entry.source.id === activeFilterId; });
  }

  function renderDateRange() {
    if (!feed || !feed.date_range) {
      daterangeEl.textContent = "";
      daterangeEl.style.display = "none";
      return;
    }
    var min = feed.date_range.min;
    var max = feed.date_range.max;
    var text = formatDateRange(min, max);
    if (!text) {
      daterangeEl.textContent = "";
      daterangeEl.style.display = "none";
      return;
    }
    daterangeEl.textContent = text;
    daterangeEl.style.display = "block";
  }

  function renderFilters() {
    if (!feed || !feed.sources || !feed.sources.length) {
      filtersEl.innerHTML = "";
      return;
    }
    var html = '<button type="button" class="filter-chip' + (activeFilterId === "all" ? " is-active" : "") + '" data-filter-id="all">All</button>';
    feed.sources.forEach(function (source) {
      var id = source.id || "";
      var title = escapeHtml(source.title || id);
      html += '<button type="button" class="filter-chip' + (activeFilterId === id ? " is-active" : "") + '" data-filter-id="' + escapeHtml(id) + '">' + title + "</button>";
    });
    filtersEl.innerHTML = html;
    filtersEl.querySelectorAll(".filter-chip").forEach(function (btn) {
      btn.addEventListener("click", function () {
        activeFilterId = btn.getAttribute("data-filter-id") || "all";
        filtersEl.querySelectorAll(".filter-chip").forEach(function (b) { b.classList.remove("is-active"); });
        btn.classList.add("is-active");
        renderCardList();
      });
    });
  }

  function renderCardList() {
    var items = getFilteredItems();
    if (items.length === 0) {
      cardListEl.innerHTML = "<li class=\"loading\">No articles in this filter.</li>";
      cardListEl.style.display = "block";
      loadingEl.style.display = "none";
      return;
    }
    var html = "";
    items.forEach(function (entry) {
      var src = entry.source;
      var item = entry.item;
      var title = escapeHtml(item.title || "Untitled");
      var snippet = escapeHtml((item.snippet || "").trim().slice(0, 200));
      if (snippet && (item.snippet || "").length > 200) snippet += "…";
      var date = escapeHtml(formatDate(item.date));
      var sourceTitle = escapeHtml(src.title || src.id || "");
      html += "<li class=\"card\" data-source-id=\"" + escapeHtml(src.id || "") + "\" data-item-url=\"" + escapeHtml(item.url || "#") + "\">";
      html += "<span class=\"card__source\">" + sourceTitle + "</span>";
      html += "<h2 class=\"card__title\">" + title + "</h2>";
      if (snippet) html += "<p class=\"card__snippet\">" + snippet + "</p>";
      if (date) html += "<p class=\"card__date\">" + date + "</p>";
      html += "</li>";
    });
    cardListEl.innerHTML = html;
    cardListEl.style.display = "block";
    loadingEl.style.display = "none";

    cardListEl.querySelectorAll(".card").forEach(function (card) {
      card.addEventListener("click", function () {
        var sourceId = card.getAttribute("data-source-id");
        var itemUrl = card.getAttribute("data-item-url");
        var source = feed.sources.find(function (s) { return s.id === sourceId; });
        var item = null;
        if (source && source.items) {
          for (var i = 0; i < source.items.length; i++) {
            if (source.items[i].url === itemUrl) { item = source.items[i]; break; }
          }
        }
        if (item) openReader(source, item);
      });
    });
  }

  function openReader(source, item) {
    var title = item.title || "Untitled";
    var content = item.content != null && item.content !== "" ? item.content : (item.snippet || "No content.");
    readerMetaEl.textContent = (source ? source.title || source.id : "") + (item.date ? " · " + formatDate(item.date) : "");
    readerTitleEl.textContent = title;
    readerOriginalEl.href = item.url || "#";
    readerOriginalEl.style.display = item.url ? "inline-block" : "none";
    readerBodyEl.textContent = content;
    readerBodyEl.className = "reader__body";
    readerBodyEl.setAttribute("dir", "auto");
    readerOverlayEl.classList.add("is-open");
    readerOverlayEl.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    readerCloseEl.focus();
  }

  function closeReader() {
    readerOverlayEl.classList.remove("is-open");
    readerOverlayEl.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function renderFeed(data) {
    feed = data;
    if (feed.updated) {
      updatedEl.textContent = "Last updated: " + feed.updated.slice(0, 19).replace("T", " ");
    }
    renderDateRange();
    renderFilters();
    renderCardList();
  }

  themeToggleEl.addEventListener("click", handleThemeToggle);
  readerCloseEl.addEventListener("click", closeReader);
  readerOverlayEl.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeReader();
  });

  initTheme();

  fetch(feedUrl)
    .then(function (res) {
      if (!res.ok) throw new Error("Failed to load feed: " + res.status);
      return res.json();
    })
    .then(renderFeed)
    .catch(function (err) {
      showError(err.message || "Could not load feed.");
    });
})();
