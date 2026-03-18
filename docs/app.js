(function () {
  var updatedEl = document.getElementById('updated');
  var contentEl = document.getElementById('content');
  var loadingEl = document.getElementById('loading');
  var errorEl = document.getElementById('error');

  function showError(msg) {
    loadingEl.style.display = 'none';
    errorEl.textContent = msg;
    errorEl.style.display = 'block';
  }

  function renderFeed(feed) {
    loadingEl.style.display = 'none';
    if (feed.updated) {
      updatedEl.textContent = 'Last updated: ' + feed.updated;
    }
    if (!feed.sources || !feed.sources.length) {
      contentEl.innerHTML = '<p>No sources yet.</p>';
      return;
    }
    var html = '';
    feed.sources.forEach(function (source) {
      var title = source.title || source.id || 'Untitled';
      var url = source.url || '#';
      var error = source.error ? ' <span style="color:#b00">(' + source.error + ')</span>' : '';
      html += '<section>';
      html += '<div class="source-title"><a href="' + escapeHtml(url) + '" target="_blank" rel="noopener">' + escapeHtml(title) + '</a>' + error + '</div>';
      html += '<ul class="items">';
      (source.items || []).forEach(function (item) {
        var itemUrl = item.url || '#';
        var itemTitle = item.title || 'Link';
        html += '<li class="item">';
        html += '<a href="' + escapeHtml(itemUrl) + '" target="_blank" rel="noopener">' + escapeHtml(itemTitle) + '</a>';
        if (item.date) {
          html += '<div class="item-date">' + escapeHtml(item.date) + '</div>';
        }
        if (item.snippet) {
          html += '<div class="item-snippet">' + escapeHtml(item.snippet) + '</div>';
        }
        html += '</li>';
      });
      html += '</ul></section>';
    });
    contentEl.innerHTML = html;
  }

  function escapeHtml(s) {
    if (!s) return '';
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  fetch('data/feed.json')
    .then(function (res) {
      if (!res.ok) throw new Error('Failed to load feed: ' + res.status);
      return res.json();
    })
    .then(renderFeed)
    .catch(function (err) {
      showError(err.message || 'Could not load feed.');
    });
})();
