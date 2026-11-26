FROM nginx:1.27-alpine
COPY index.html specs.html improvements.html recommendations.html render.html eta.html performance.html result.html nav.js PLAN.md SPECS.md IMPROVEMENTS.md RECOMMENDATIONS.md PERFORMANCE.md /usr/share/nginx/html/
EXPOSE 80
