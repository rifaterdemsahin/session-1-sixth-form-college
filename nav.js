(() => {
  const LINKS = [
    { href: "index.html", label: "📋 Plan" },
    { href: "specs.html", label: "📐 Specs" },
    { href: "improvements.html", label: "✨ Improvements" },
    { href: "recommendations.html", label: "🎯 Recommendations" },
    { href: "render.html", label: "🎬 Render Hub" },
    { href: "performance.html", label: "⚡ Performance" },
  ];

  const path = window.location.pathname.split("/").pop() || "index.html";

  const style = document.createElement("style");
  style.textContent = `
    .site-topbar {
      position: sticky;
      top: 0;
      z-index: 999;
      background: #111827;
      color: #ffffff;
      border-bottom: 3px solid #dc2626;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
    }
    .site-topbar-inner {
      max-width: 1080px;
      margin: 0 auto;
      padding: 10px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .site-brand {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: #ffffff;
      text-decoration: none;
      font-weight: 800;
      font-size: 14px;
      letter-spacing: 0.02em;
    }
    .site-brand-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #ef4444;
      display: inline-block;
    }
    .site-nav {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }
    .site-nav a {
      color: #e5e7eb;
      text-decoration: none;
      font-size: 13px;
      font-weight: 600;
      padding: 6px 11px;
      border-radius: 8px;
      border: 1px solid transparent;
      transition: background 0.15s, border-color 0.15s, color 0.15s;
    }
    .site-nav a:hover,
    .site-nav a:focus-visible {
      background: #1f2937;
      color: #ffffff;
      border-color: #ef4444;
      outline: 2px solid #fca5a5;
      outline-offset: 1px;
    }
    .site-nav a[aria-current="page"] {
      background: #dc2626;
      color: #ffffff;
      border-color: #ef4444;
    }
  `;
  document.head.appendChild(style);

  const bar = document.createElement("div");
  bar.className = "site-topbar";
  bar.setAttribute("role", "banner");

  const inner = document.createElement("div");
  inner.className = "site-topbar-inner";

  const brand = document.createElement("a");
  brand.className = "site-brand";
  brand.href = "index.html";
  brand.innerHTML = '<span class="site-brand-dot" aria-hidden="true"></span>Session 1 · AI Training Course';

  const nav = document.createElement("nav");
  nav.className = "site-nav";
  nav.setAttribute("aria-label", "Primary navigation");

  LINKS.forEach((item) => {
    const a = document.createElement("a");
    a.href = item.href;
    a.textContent = item.label;
    if (path === item.href || (path === "" && item.href === "index.html")) {
      a.setAttribute("aria-current", "page");
    }
    nav.appendChild(a);
  });

  inner.appendChild(brand);
  inner.appendChild(nav);
  bar.appendChild(inner);

  document.body.insertBefore(bar, document.body.firstChild);
})();
