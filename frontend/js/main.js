(() => {
  'use strict';

  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isTouch = window.matchMedia('(hover: none)').matches;
  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

  /* ---------- STICKY NAV ---------- */
  const nav = $('#nav');
  const onScroll = () => nav.classList.toggle('is-stuck', window.scrollY > 24);
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  /* ---------- MOBILE MENU ---------- */
  const navToggle = $('#navToggle');
  const navLinks = $('#navLinks');

  navToggle.addEventListener('click', () => {
    const open = navLinks.classList.toggle('is-open');
    navToggle.classList.toggle('is-open', open);
    navToggle.setAttribute('aria-expanded', String(open));
    navToggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    document.body.style.overflow = open ? 'hidden' : '';
  });

  $$('#navLinks a').forEach((link) =>
    link.addEventListener('click', () => {
      navLinks.classList.remove('is-open');
      navToggle.classList.remove('is-open');
      navToggle.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
    })
  );

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && navLinks.classList.contains('is-open')) navToggle.click();
  });

  /* ---------- CUSTOM CURSOR ---------- */
  if (!isTouch && !prefersReduced) {
    const dot = $('.cursor-dot');
    const ring = $('.cursor-ring');
    let mx = innerWidth / 2, my = innerHeight / 2;
    let rx = mx, ry = my;

    window.addEventListener('mousemove', (e) => {
      mx = e.clientX;
      my = e.clientY;
      dot.style.transform = `translate(${mx}px, ${my}px)`;
    });

    (function loop() {
      rx += (mx - rx) * 0.16;
      ry += (my - ry) * 0.16;
      ring.style.transform = `translate(${rx}px, ${ry}px)`;
      requestAnimationFrame(loop);
    })();

    document.addEventListener('mouseover', (e) => {
      if (e.target.closest('[data-cursor="link"], a, button')) ring.classList.add('is-link');
    });
    document.addEventListener('mouseout', (e) => {
      if (e.target.closest('[data-cursor="link"], a, button')) ring.classList.remove('is-link');
    });
  } else {
    document.body.classList.add('no-cursor');
  }

  /* ---------- SCROLL REVEAL ---------- */
  const revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        revealObserver.unobserve(entry.target);
      });
    },
    { threshold: 0.12, rootMargin: '0px 0px -60px 0px' }
  );

  $$('.reveal').forEach((el, i) => {
    el.style.transitionDelay = `${(i % 6) * 70}ms`;
    revealObserver.observe(el);
  });

  /* ---------- HERO TITLE REVEAL ---------- */
  const heroLines = $$('.hero__title .line__in');
  heroLines.forEach((line, i) => {
    setTimeout(() => {
      line.style.transition = 'transform .95s cubic-bezier(.22,1,.36,1)';
      line.style.transform = 'translateY(0)';
    }, prefersReduced ? 0 : 140 * i + 120);
  });

  /* ---------- TILT CARDS ---------- */
  if (!isTouch && !prefersReduced) {
    $$('[data-tilt]').forEach((card) => {
      const max = 8;
      card.addEventListener('mousemove', (e) => {
        const r = card.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width - 0.5;
        const py = (e.clientY - r.top) / r.height - 0.5;
        card.style.transform = `perspective(900px) rotateY(${px * max}deg) rotateX(${-py * max}deg) translateZ(0)`;
        card.style.setProperty('--mx', `${e.clientX - r.left}px`);
        card.style.setProperty('--my', `${e.clientY - r.top}px`);
      });
      card.addEventListener('mouseleave', () => {
        card.style.transform = 'perspective(900px) rotateY(0deg) rotateX(0deg)';
      });
    });
  }

  /* ---------- PROJECT SPOTLIGHT ---------- */
  if (!isTouch && !prefersReduced) {
    $$('[data-spotlight]').forEach((card) => {
      card.addEventListener('mousemove', (e) => {
        const r = card.getBoundingClientRect();
        card.style.setProperty('--mx', `${e.clientX - r.left}px`);
        card.style.setProperty('--my', `${e.clientY - r.top}px`);
      });
    });
  }

  /* ---------- SKILL BARS ---------- */
  const barObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const fill = $('.bar__fill', entry.target);
        fill.style.width = `${entry.target.dataset.value}%`;
        barObserver.unobserve(entry.target);
      });
    },
    { threshold: 0.4 }
  );
  $$('.bar').forEach((bar) => barObserver.observe(bar));

  /* ---------- COUNTERS ---------- */
  const countObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        const to = Number(el.dataset.to);
        const dur = 1600;
        const start = performance.now();

        const tick = (now) => {
          const p = Math.min((now - start) / dur, 1);
          const eased = 1 - Math.pow(1 - p, 3);
          el.textContent = Math.round(to * eased);
          if (p < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
        countObserver.unobserve(el);
      });
    },
    { threshold: 0.5 }
  );
  $$('.counter').forEach((c) => countObserver.observe(c));

  /* ---------- ACTIVE NAV LINK ---------- */
  const sections = $$('main section[id]');
  const navAnchors = $$('#navLinks a');
  const spy = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const id = `#${entry.target.id}`;
        navAnchors.forEach((a) => {
          const active = a.getAttribute('href') === id;
          a.style.color = active ? 'var(--white)' : '';
          if (active) a.setAttribute('aria-current', 'true');
          else a.removeAttribute('aria-current');
        });
      });
    },
    { rootMargin: '-45% 0px -50% 0px' }
  );
  sections.forEach((s) => spy.observe(s));

  /* ---------- SMOOTH ANCHORS ---------- */
  $$('a[href^="#"]').forEach((link) => {
    link.addEventListener('click', (e) => {
      const id = link.getAttribute('href');
      if (!id || id === '#') return;
      const target = document.querySelector(id);
      if (!target) return;
      e.preventDefault();
      const offset = nav.offsetHeight + 10;
      window.scrollTo({
        top: target.getBoundingClientRect().top + window.scrollY - offset,
        behavior: prefersReduced ? 'auto' : 'smooth'
      });
    });
  });

  /* ---------- CONTACT FORM ---------- */
  const form = $('#contactForm');
  const status = $('#formStatus');

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    let valid = true;

    $$('.field', form).forEach((field) => {
      const input = $('input, textarea', field);
      if (!input) return;
      const ok = input.value.trim() !== '' && (input.type !== 'email' || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.value));
      field.classList.toggle('is-invalid', !ok);
      if (!ok) valid = false;
    });

    if (!valid) {
      status.textContent = 'Please fill in every field with a valid email.';
      status.classList.add('is-error');
      return;
    }

    status.classList.remove('is-error');
    status.textContent = 'Sending…';

    setTimeout(() => {
      form.reset();
      status.textContent = 'Message sent — I’ll get back to you within 48 hours.';
    }, 900);
  });

  $$('input, textarea', form).forEach((input) =>
    input.addEventListener('input', () => input.closest('.field').classList.remove('is-invalid'))
  );

  /* ---------- YEAR ---------- */
  $('#year').textContent = new Date().getFullYear();

  /* ---------- LIVE SYSTEM TELEMETRY ---------- */
  const telemetry = $('#telemetry');
  if (telemetry) {
    const base = telemetry.dataset.api;
    const setTile = (id, value, sub) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (value !== undefined && value !== null && value !== '') el.textContent = value;
      if (sub !== undefined && sub !== null && sub !== '') {
        const s = document.getElementById(id + 'Sub');
        if (s) s.textContent = sub;
      }
    };

    const fetchJson = (path) =>
      fetch(base + path, { mode: 'cors' }).then((r) => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status))));

    Promise.allSettled([fetchJson('/api/health'), fetchJson('/api/analytics'), fetchJson('/api/catalog'), fetchJson('/api/rules')])
      .then(([health, analytics, catalog, registry]) => {
        if (health.status === 'fulfilled') {
          const h = health.value;
          const ver = h.version ? (h.version.startsWith('v') ? h.version : 'v' + h.version) : '';
          setTile('tVer', ver, h.engines ? h.engines.ocr : undefined);
          telemetry.classList.add('is-online');
          document.getElementById('telemetryState').textContent = 'Engine online';
          document.getElementById('telemetryMeta').textContent = h.app + ' · ' + h.version;
        } else {
          telemetry.classList.add('is-offline');
          document.getElementById('telemetryState').textContent = 'Engine offline — start the Flask API';
        }
        if (registry.status === 'fulfilled') {
          const s = registry.value.summary || {};
          const mix = [s.critical, s.major, s.minor].filter(Boolean).join(' · ');
          const sub = s.disabled ? mix + ' · ' + s.disabled + ' disabled' : mix;
          setTile('tRules', s.active, sub ? s.total + ' live — ' + sub : 'live rules');
        } else if (health.status === 'fulfilled') {
          const h = health.value;
          if (h.engines && h.engines.rules) {
            const m = h.engines.rules.match(/(\d+)\s+Legal Metrology/);
            if (m) setTile('tRules', m[1], 'Legal Metrology Act, 2009');
          }
        }
        if (analytics.status === 'fulfilled') {
          const a = analytics.value;
          setTile('tScans', a.total_scans, a.total_scans ? a.compliance_rate + '% compliance rate' : 'no scans yet');
        }
        if (catalog.status === 'fulfilled') {
          setTile('tSku', catalog.value.count, 'reference prices on file');
        }
      })
      .catch(() => {
        telemetry.classList.add('is-offline');
        document.getElementById('telemetryState').textContent = 'Engine offline — start the Flask API';
      });
  }

  /* ---------- PARALLAX BLOBS ---------- */
  if (!prefersReduced) {
    const blobs = $$('.blob');
    window.addEventListener(
      'scroll',
      () => {
        const y = window.scrollY;
        blobs.forEach((b, i) => {
          b.style.transform = `translate3d(0, ${y * (i % 2 ? 0.08 : -0.06)}px, 0)`;
        });
      },
      { passive: true }
    );
  }
})();
