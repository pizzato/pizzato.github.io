/* ============================================================
   REVAMP — Luiz Pizzato
   Minimal JS: scroll reveals + active nav
   ============================================================ */

// ── Scroll reveal ─────────────────────────────────────────────
const revealObs = new IntersectionObserver((entries) => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      e.target.classList.add('in');
      revealObs.unobserve(e.target);
    }
  });
}, { threshold: 0.06, rootMargin: '0px 0px -32px 0px' });

document.querySelectorAll('.reveal').forEach(el => revealObs.observe(el));

// ── Active nav link ────────────────────────────────────────────
const sections = document.querySelectorAll('[data-section]');
const navLinks  = document.querySelectorAll('.nav-link[href^="#"]');

const navObs = new IntersectionObserver((entries) => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      const id = e.target.dataset.section;
      navLinks.forEach(l => {
        l.classList.toggle('active', l.getAttribute('href') === '#' + id);
      });
    }
  });
}, { rootMargin: '-35% 0px -55% 0px' });

sections.forEach(s => navObs.observe(s));

// ── Smooth scroll ─────────────────────────────────────────────
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', e => {
    const target = document.querySelector(a.getAttribute('href'));
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

// ── Post row click ────────────────────────────────────────────
document.querySelectorAll('.post-entry[data-href]').forEach(row => {
  row.addEventListener('click', () => { window.location.href = row.dataset.href; });
});
