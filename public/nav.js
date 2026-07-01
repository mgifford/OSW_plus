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
          '<li><a class="site-nav-submit" href="' + SUBMIT_EVENT_URL + '" target="_blank" rel="noopener noreferrer">' +
            '\u2795 Submit Event<span class="visually-hidden"> (opens in new tab)</span>' +
          '</a></li>' +
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

  // Append contribution CTA to the page footer
  var footer = document.querySelector('footer');
  if (footer) {
    var ctaHtml =
      '<p class="footer-cta">' +
        '<a href="' + SUBMIT_EVENT_URL + '" target="_blank" rel="noopener noreferrer">' +
          '\u2795 Submit an event<span class="visually-hidden"> (opens in new tab)</span>' +
        '</a>' +
        ' \u00b7 ' +
        '<a href="' + SUBMIT_PLACE_URL + '" target="_blank" rel="noopener noreferrer">' +
          '\ud83d\udccd Suggest a place<span class="visually-hidden"> (opens in new tab)</span>' +
        '</a>' +
        ' via GitHub Issues' +
      '</p>';
    footer.insertAdjacentHTML('beforeend', ctaHtml);
  }
}());
