/* nav.js — injects the shared site navigation bar and footer contribution CTA
   into every page that includes <script src="nav.js" defer></script>        */
(function () {
  'use strict';

  // Root-absolute hrefs so the nav works from nested knowledge pages
  // (e.g. /speakers/<slug>.html) as well as the top-level pages.
  var PAGES = [
    { href: '/index.html',           label: '🏠 Home' },
    { href: '/events.html',          label: '📋 Events' },
    { href: '/calendar-view.html',   label: '📅 Calendar' },
    { href: '/explore.html',         label: '🧭 Knowledge' },
    { href: '/graph.html',           label: '🕸️ Relationship map' },
    { href: '/places-map.html',      label: '☕ Meet Up / Food / Coffee' },
    { href: '/search.html',          label: '🔍 Search' },
    { href: '/2025-resources.html',  label: '🗓️ 2025 Resources' }
  ];

  var SUBMIT_EVENT_URL = 'https://github.com/mgifford/unosw.plus/issues/new?template=submit-event.yml';
  var SUBMIT_PLACE_URL = 'https://github.com/mgifford/unosw.plus/issues/new?template=submit-place.yml';

  // ── Event-submission window ─────────────────────────────────────────────
  // Side-event submissions are open from January 1 until one week after UN
  // Open Source Week ends — nobody should be invited to submit in August for
  // an event that finished in June. UPDATE this to the conference's last day
  // (YYYY-MM-DD) each cycle; submissions reopen automatically on January 1.
  var SUBMISSION_EVENT_END = '2026-06-26';
  var SUBMISSION_GRACE_DAYS = 7;
  var SUBMISSION_CLOSED_MSG =
    'Event submissions are open from January 1 until one week after UN Open Source Week ends.';

  function submissionsOpen() {
    var now = window.__NAV_NOW ? new Date(window.__NAV_NOW) : new Date();
    var end = new Date(SUBMISSION_EVENT_END + 'T23:59:59');
    var openFrom = new Date(end.getFullYear() + '-01-01T00:00:00');
    var closeAfter = new Date(end.getTime());
    closeAfter.setDate(closeAfter.getDate() + SUBMISSION_GRACE_DAYS);
    return now >= openFrom && now <= closeAfter;
  }
  var SUBMISSIONS_OPEN = submissionsOpen();

  // Detect current page by matching the filename portion of the URL
  var currentFile = window.location.pathname.split('/').pop() || 'index.html';

  var linksHtml = PAGES.map(function (p) {
    var hrefFile = p.href.split('/').pop();
    var current = (hrefFile === currentFile) ? ' aria-current="page"' : '';
    return '<li><a href="' + p.href + '"' + current + '>' + p.label + '</a></li>';
  }).join('');

  var navHtml =
    '<nav class="site-nav" aria-label="Site navigation">' +
      '<div class="site-nav-inner">' +
        '<a class="site-nav-brand" href="/" aria-label="OSW+ NYC \u2014 Home">OSW+\u00a0NYC</a>' +
        '<button class="site-nav-toggle" aria-controls="site-nav-menu" aria-expanded="false" aria-label="Toggle navigation menu">' +
          '<span></span><span></span><span></span>' +
        '</button>' +
        '<ul id="site-nav-menu" class="site-nav-links" role="list">' +
          linksHtml +
          (SUBMISSIONS_OPEN
            ? '<li><a class="site-nav-submit" href="' + SUBMIT_EVENT_URL + '" target="_blank" rel="noopener noreferrer">' +
                '\u2795 Submit Event<span class="visually-hidden"> (opens in new tab)</span>' +
              '</a></li>'
            : '<li><span class="site-nav-submit submit-closed" role="note" title="' + SUBMISSION_CLOSED_MSG + '">' +
                'Submissions closed' +
              '</span></li>') +
        '</ul>' +
      '</div>' +
    '</nav>';

  // Insert nav immediately after the skip link, or as the first element in <body>
  var skipLink = document.querySelector('.skip-link');
  if (skipLink && skipLink.parentNode) {
    skipLink.insertAdjacentHTML('afterend', navHtml);
  } else {
    document.body.insertAdjacentHTML('afterbegin', navHtml);
  }

  // Mobile hamburger toggle
  var toggle = document.querySelector('.site-nav-toggle');
  var menu   = document.getElementById('site-nav-menu');
  if (toggle && menu) {
    toggle.addEventListener('click', function () {
      var expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!expanded));
      menu.classList.toggle('open', !expanded);
    });

    // Close menu on outside click
    document.addEventListener('click', function (e) {
      if (!toggle.contains(e.target) && !menu.contains(e.target)) {
        toggle.setAttribute('aria-expanded', 'false');
        menu.classList.remove('open');
      }
    });

    // Close menu on Escape key
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        toggle.setAttribute('aria-expanded', 'false');
        menu.classList.remove('open');
        toggle.focus();
      }
    });
  }

  // Append contribution CTA to the page footer (place suggestions stay open
  // year-round; event submissions honour the seasonal window).
  var footer = document.querySelector('footer');
  if (footer) {
    var eventCta = SUBMISSIONS_OPEN
      ? '<a href="' + SUBMIT_EVENT_URL + '" target="_blank" rel="noopener noreferrer">' +
          '\u2795 Submit an event<span class="visually-hidden"> (opens in new tab)</span></a>'
      : '<span class="submit-closed" title="' + SUBMISSION_CLOSED_MSG + '">' +
          'Event submissions are closed until January 1</span>';
    var ctaHtml =
      '<p class="footer-cta">' +
        eventCta +
        ' \u00b7 ' +
        '<a href="' + SUBMIT_PLACE_URL + '" target="_blank" rel="noopener noreferrer">' +
          '\ud83d\udccd Suggest a place<span class="visually-hidden"> (opens in new tab)</span>' +
        '</a>' +
        ' via GitHub Issues' +
      '</p>';
    footer.insertAdjacentHTML('beforeend', ctaHtml);
  }

  // When closed, neutralise every other "submit an event" link on the page
  // (quick-action cards, empty-state prompts) \u2014 including ones injected later.
  if (!SUBMISSIONS_OPEN) {
    var gateSubmitLinks = function (root) {
      var links = (root || document).querySelectorAll(
        'a[href*="submit-event.yml"]:not([data-submit-gated])');
      Array.prototype.forEach.call(links, function (a) {
        a.setAttribute('data-submit-gated', '1');
        a.setAttribute('aria-disabled', 'true');
        a.setAttribute('title', SUBMISSION_CLOSED_MSG);
        a.classList.add('submit-closed');
        a.addEventListener('click', function (e) { e.preventDefault(); });
      });
    };
    gateSubmitLinks(document);
    if (window.MutationObserver) {
      new MutationObserver(function (mutations) {
        mutations.forEach(function (m) {
          Array.prototype.forEach.call(m.addedNodes, function (node) {
            if (node.nodeType === 1) { gateSubmitLinks(node); }
          });
        });
      }).observe(document.body, { childList: true, subtree: true });
    }
  }
}());
