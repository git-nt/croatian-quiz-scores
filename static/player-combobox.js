(function () {
  'use strict';

  /** Max rows when filtering by typed text (substring matches can be huge). */
  var MAX_FILTERED = 200;

  function fold(s) {
    if (!s) return '';
    try {
      return s
        .toLowerCase()
        .normalize('NFD')
        .replace(/\p{M}/gu, '');
    } catch (e) {
      return s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    }
  }

  function parsePlayers(root) {
    var el = root.querySelector('script.player-combobox-data[type="application/json"]');
    if (!el || !el.textContent.trim()) return [];
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      return [];
    }
  }

  function init(root) {
    var players = parsePlayers(root);
    if (!players.length) return;

    var sorted = players.slice().sort(function (a, b) {
      return a.name.localeCompare(b.name, 'hr', { sensitivity: 'base' });
    });

    var baseUrl = (root.getAttribute('data-base-url') || '').replace(/\/$/, '');
    var currentSlug = root.getAttribute('data-current-slug') || '';
    var input = root.querySelector('.player-combobox-input');
    var listEl = root.querySelector('.player-combobox-list');
    if (!input || !listEl) return;

    var matches = [];
    var activeIndex = -1;
    var blurTimer;

    function go(slug) {
      if (!slug) return;
      if (currentSlug && slug === currentSlug) return;
      window.location.href = baseUrl + '/players/' + encodeURIComponent(slug) + '/';
    }

    /** Empty query → full list (like a native select). Otherwise substring filter. */
    function filter(q) {
      var n = fold(q.trim());
      if (!n) return sorted.slice();
      var out = [];
      for (var i = 0; i < sorted.length; i++) {
        if (fold(sorted[i].name).indexOf(n) !== -1) out.push(sorted[i]);
        if (out.length >= MAX_FILTERED) break;
      }
      return out;
    }

    function renderList(filtered) {
      matches = filtered;
      listEl.innerHTML = '';
      activeIndex = matches.length ? 0 : -1;

      var frag = document.createDocumentFragment();
      for (var i = 0; i < matches.length; i++) {
        var p = matches[i];
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.setAttribute('data-slug', p.slug);
        li.id = input.id + '-opt-' + i;
        li.textContent = p.name;
        li.className = 'player-combobox-option';
        if (i === 0) li.classList.add('active');
        li.setAttribute('aria-selected', i === 0 ? 'true' : 'false');
        li.addEventListener('mousedown', function (ev) {
          ev.preventDefault();
          go(this.getAttribute('data-slug'));
        });
        frag.appendChild(li);
      }
      listEl.appendChild(frag);

      var show = matches.length > 0;
      listEl.hidden = !show;
      input.setAttribute('aria-expanded', show ? 'true' : 'false');
      if (show && matches[0]) {
        input.setAttribute('aria-activedescendant', input.id + '-opt-0');
      } else {
        input.removeAttribute('aria-activedescendant');
      }
    }

    function setActive(i) {
      if (i < 0 || i >= matches.length) return;
      activeIndex = i;
      var items = listEl.querySelectorAll('.player-combobox-option');
      for (var j = 0; j < items.length; j++) {
        var on = j === activeIndex;
        items[j].classList.toggle('active', on);
        items[j].setAttribute('aria-selected', on ? 'true' : 'false');
      }
      var cur = items[activeIndex];
      if (cur) {
        input.setAttribute('aria-activedescendant', cur.id);
        cur.scrollIntoView({ block: 'nearest' });
      }
    }

    /** After opening list: jump keyboard highlight to current player (detail page). */
    function highlightCurrentIfAny() {
      if (!currentSlug || !matches.length) return;
      for (var i = 0; i < matches.length; i++) {
        if (matches[i].slug === currentSlug) {
          setActive(i);
          return;
        }
      }
    }

    function openList() {
      clearTimeout(blurTimer);
      renderList(filter(input.value));
      highlightCurrentIfAny();
    }

    function onInput() {
      clearTimeout(blurTimer);
      renderList(filter(input.value));
      highlightCurrentIfAny();
    }

    input.addEventListener('focus', function () {
      openList();
    });

    input.addEventListener('input', onInput);

    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') {
        if (listEl.hidden || !matches.length) {
          openList();
          return;
        }
        e.preventDefault();
        setActive(Math.min(activeIndex + 1, matches.length - 1));
      } else if (e.key === 'ArrowUp') {
        if (listEl.hidden || !matches.length) return;
        e.preventDefault();
        setActive(Math.max(activeIndex - 1, 0));
      } else if (e.key === 'Enter') {
        if (!listEl.hidden && activeIndex >= 0 && matches[activeIndex]) {
          e.preventDefault();
          go(matches[activeIndex].slug);
        }
      } else if (e.key === 'Escape') {
        listEl.hidden = true;
        input.setAttribute('aria-expanded', 'false');
        input.removeAttribute('aria-activedescendant');
      }
    });

    input.addEventListener('blur', function () {
      blurTimer = setTimeout(function () {
        listEl.hidden = true;
        input.setAttribute('aria-expanded', 'false');
        input.removeAttribute('aria-activedescendant');
      }, 180);
    });
  }

  document.querySelectorAll('[data-player-combobox]').forEach(init);
})();
